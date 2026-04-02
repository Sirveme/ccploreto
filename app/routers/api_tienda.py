"""
app/routers/api_tienda.py
Endpoints públicos para la tienda/catálogo de merchandising CCPL.
Series B800 (boleta) y F800 (factura) para portal web.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from app.database import get_db

router = APIRouter(prefix="/api/publico", tags=["Tienda Pública"])

TZ_PERU = timezone(timedelta(hours=-5))


# ── ENDPOINT 1: Catálogo público ──────────────────────────────
@router.get("/catalogo")
async def catalogo_publico(db: Session = Depends(get_db)):
    """
    Catálogo de productos disponibles para compra pública.
    No requiere autenticación.
    """
    from app.models import ConceptoCobro

    CATEGORIA_LABELS = {
        'mercaderia': 'Merchandising',
        'alquileres': 'Alquileres',
        'eventos':    'Eventos',
        'recreacion': 'Recreación',
        'otros':      'Otros',
    }
    CATEGORIA_ICONS = {
        'mercaderia': '🛍️',
        'alquileres': '🏛️',
        'eventos':    '🎉',
        'recreacion': '⚽',
        'otros':      '📦',
    }

    conceptos = db.query(ConceptoCobro).filter(
        ConceptoCobro.organization_id  == 1,
        ConceptoCobro.activo           == True,
        ConceptoCobro.aplica_a_publico == True,
        ConceptoCobro.genera_deuda     == False,
    ).order_by(ConceptoCobro.categoria, ConceptoCobro.orden).all()

    # Agrupar por categoría
    categorias: dict = {}
    for c in conceptos:
        agotado = c.maneja_stock and (c.stock_actual or 0) <= 0
        item = {
            "id":              c.id,
            "codigo":          c.codigo,
            "nombre":          c.nombre,
            "nombre_corto":    c.nombre_corto or c.nombre,
            "descripcion":     c.descripcion,
            "categoria":       c.categoria,
            "categoria_label": CATEGORIA_LABELS.get(c.categoria, c.categoria.title()),
            "categoria_icon":  CATEGORIA_ICONS.get(c.categoria, '📦'),
            "precio":          float(c.monto_base),
            "permite_monto_libre": c.permite_monto_libre,
            "maneja_stock":    c.maneja_stock,
            "stock":           c.stock_actual if c.maneja_stock else None,
            "agotado":         agotado,
        }
        cat = c.categoria
        if cat not in categorias:
            categorias[cat] = {
                "key":   cat,
                "label": CATEGORIA_LABELS.get(cat, cat.title()),
                "icon":  CATEGORIA_ICONS.get(cat, '📦'),
                "items": [],
            }
        categorias[cat]['items'].append(item)

    return JSONResponse({
        "categorias":  list(categorias.values()),
        "total_items": sum(len(c['items']) for c in categorias.values()),
    })


# ── ENDPOINT 2: Comprar ───────────────────────────────────────
@router.post("/comprar")
async def comprar_publico(
    request: Request,
    db:      Session = Depends(get_db),
):
    """
    Registra una compra pública y emite CPE vía Facturalo serie B800/F800.

    Body JSON:
    {
        "items": [{"concepto_id": 5, "cantidad": 2}],
        "tipo_comprobante": "boleta" | "factura",
        "comprador": {"nombre": "Juan Pérez", "dni": "12345678"},
        "factura": {"ruc": "20123456789", "razon_social": "...", "direccion": "..."},
        "metodo_pago": "yape" | "plin" | "transferencia" | "tarjeta",
        "nro_operacion": "123456789"
    }
    """
    import json as _json
    from app.models import ConceptoCobro, Payment, Organization

    data           = await request.json()
    items_req      = data.get("items", [])
    tipo_comp      = data.get("tipo_comprobante", "boleta")
    comprador      = data.get("comprador", {})
    factura_data   = data.get("factura", {})
    metodo_pago    = data.get("metodo_pago", "")
    nro_operacion  = data.get("nro_operacion", "")

    if not items_req:
        return JSONResponse({"error": "Sin items"}, status_code=400)

    org = db.query(Organization).filter(Organization.id == 1).first()
    if not org:
        return JSONResponse({"error": "Organización no encontrada"}, status_code=500)

    # ── Validar items y calcular total ────────────────────────
    total = Decimal("0")
    items_procesados = []

    for item_req in items_req:
        concepto = db.query(ConceptoCobro).filter(
            ConceptoCobro.id              == item_req["concepto_id"],
            ConceptoCobro.activo          == True,
            ConceptoCobro.aplica_a_publico == True,
        ).first()

        if not concepto:
            return JSONResponse(
                {"error": f"Producto {item_req['concepto_id']} no encontrado"},
                status_code=400,
            )

        cantidad = int(item_req.get("cantidad", 1))

        if concepto.maneja_stock:
            if (concepto.stock_actual or 0) < cantidad:
                return JSONResponse({
                    "error": f"Stock insuficiente de {concepto.nombre}. "
                             f"Disponible: {concepto.stock_actual}"
                }, status_code=400)
            concepto.stock_actual -= cantidad

        monto_unitario = Decimal(str(concepto.monto_base))
        monto_total    = monto_unitario * cantidad
        total         += monto_total

        items_procesados.append({
            "concepto_id":    concepto.id,
            "codigo":         concepto.codigo,
            "nombre":         concepto.nombre,
            "cantidad":       cantidad,
            "monto_unitario": float(monto_unitario),
            "monto_total":    float(monto_total),
            "afecto_igv":     concepto.afecto_igv,
        })

    # ── Crear Payment ─────────────────────────────────────────
    notes_data = {
        "flujo":            "tienda_publica",
        "comprador":        comprador,
        "items":            items_procesados,
        "tipo_comprobante": tipo_comp,
    }
    if factura_data:
        notes_data["factura"] = factura_data

    # Status según método: reportar → review | tarjeta → pending (OpenPay lo aprueba)
    status_pago = "review" if metodo_pago in ("yape", "plin", "transferencia") else "pending"

    payment = Payment(
        organization_id = org.id,
        amount          = total,
        payment_method  = metodo_pago or "pendiente",
        operation_code  = nro_operacion or "pendiente",
        notes           = _json.dumps(notes_data, ensure_ascii=False),
        status          = status_pago,
    )
    db.add(payment)
    db.flush()

    # ── Emitir CPE vía Facturalo serie B800/F800 ──────────────
    cpe_info = None
    if metodo_pago == "tarjeta":
        # Para tarjeta OpenPay aprueba y luego emite — no emitir aquí
        pass
    else:
        # Para Yape/Plin/Transferencia — emitir al registrar (status review)
        # El CCPL decidirá si emitir antes o después de validar
        try:
            from app.services.facturacion import FacturacionService

            facturacion = FacturacionService(db, org.id)
            if facturacion.esta_configurado():
                tipo_cpe = "01" if tipo_comp == "factura" else "03"

                # Datos del cliente
                if tipo_comp == "factura" and factura_data.get("ruc"):
                    datos_cliente = {
                        "tipo_doc":  "6",
                        "num_doc":   factura_data["ruc"],
                        "nombre":    factura_data.get("razon_social", ""),
                        "direccion": factura_data.get("direccion", ""),
                    }
                else:
                    datos_cliente = {
                        "tipo_doc": "1",
                        "num_doc":  comprador.get("dni", "00000000"),
                        "nombre":   comprador.get("nombre", "CLIENTE VARIOS"),
                    }

                # Ajustar items para Facturalo (descripción + formato)
                items_cpe = [{
                    "descripcion":         i["nombre"],
                    "cantidad":            i["cantidad"],
                    "unidad_medida":       "NIU",
                    "precio_unitario":     i["monto_unitario"],
                    "tipo_afectacion_igv": "20",
                } for i in items_procesados]

                resultado = await facturacion.emitir_comprobante_por_pago(
                    payment_id           = payment.id,
                    tipo                 = tipo_cpe,
                    sede_id              = "8",    # ← B800 / F800
                    forma_pago           = metodo_pago or "contado",
                    forzar_datos_cliente = datos_cliente,
                )

                if resultado.get("success"):
                    cpe_info = resultado
                    payment.status = "approved"  # pago con comprobante = aprobado

        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"[Tienda] Error CPE: {e}")

    db.commit()

    return JSONResponse({
        "ok":         True,
        "payment_id": payment.id,
        "total":      float(total),
        "estado":     payment.status,
        "comprobante": {
            "numero_formato": cpe_info.get("numero_formato") if cpe_info else None,
            "pdf_url":        cpe_info.get("pdf_url")        if cpe_info else None,
        } if cpe_info else None,
        "mensaje": (
            f"Compra registrada. Comprobante {cpe_info['numero_formato']} emitido."
            if cpe_info else
            "Compra registrada. El comprobante se emitirá al validar el pago."
        ),
    })
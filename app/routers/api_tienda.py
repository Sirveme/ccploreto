"""
Endpoints públicos para la tienda/catálogo de merchandising CCPL
Agregar en app/routers/pagos_publicos.py o crear app/routers/api_tienda.py
Prefix: /api/publico
"""

# ── IMPORTS A AGREGAR ─────────────────────────────────────────
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from app.database import get_db

router = APIRouter(prefix="/api/publico", tags=["Tienda Pública"])

# ── ENDPOINT 1: Catálogo público ──────────────────────────────
@router.get("/catalogo")
async def catalogo_publico(
    db: Session = Depends(get_db),
):
    """
    Catálogo de productos disponibles para compra pública.
    No requiere autenticación.
    """
    from app.models import ConceptoCobro

    conceptos = db.query(ConceptoCobro).filter(
        ConceptoCobro.organization_id == 1,  # TODO: multi-tenant
        ConceptoCobro.activo          == True,
        ConceptoCobro.aplica_a_publico == True,
        ConceptoCobro.genera_deuda    == False,
    ).order_by(ConceptoCobro.categoria, ConceptoCobro.orden).all()

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

    items = []
    for c in conceptos:
        agotado = c.maneja_stock and (c.stock_actual or 0) <= 0
        items.append({
            "id":              c.id,
            "codigo":          c.codigo,
            "nombre":          c.nombre,
            "nombre_corto":    c.nombre_corto or c.nombre,
            "descripcion":     c.descripcion,
            "categoria":       c.categoria,
            "categoria_label": CATEGORIA_LABELS.get(c.categoria, c.categoria),
            "categoria_icon":  CATEGORIA_ICONS.get(c.categoria, '📦'),
            "precio":          float(c.monto_base),
            "permite_monto_libre": c.permite_monto_libre,
            "maneja_stock":    c.maneja_stock,
            "stock":           c.stock_actual if c.maneja_stock else None,
            "agotado":         agotado,
            "imagen_url":      None,  # TODO: agregar campo imagen a conceptos_cobro
        })

    # Agrupar por categoría
    categorias = {}
    for item in items:
        cat = item['categoria']
        if cat not in categorias:
            categorias[cat] = {
                "key":   cat,
                "label": item['categoria_label'],
                "icon":  item['categoria_icon'],
                "items": [],
            }
        categorias[cat]['items'].append(item)

    return JSONResponse({
        "categorias": list(categorias.values()),
        "total_items": len(items),
    })


# ── ENDPOINT 2: Iniciar compra pública ────────────────────────
@router.post("/comprar")
async def comprar_publico(
    request: Request,
    db:      Session = Depends(get_db),
):
    """
    Inicia una compra pública (sin login).
    Crea el payment y emite CPE vía Facturalo serie B800/F800.
    Body JSON: {
        "items": [{"concepto_id": 1, "cantidad": 2}],
        "tipo_comprobante": "boleta" | "factura",
        "comprador": {"nombre": "...", "dni": "..."},
        "factura": {"ruc": "...", "razon_social": "...", "direccion": "..."},
        "metodo_pago": "yape" | "plin" | "transferencia" | "tarjeta",
        "voucher_base64": "...",  // opcional
        "nro_operacion": "...",
    }
    """
    from app.models import ConceptoCobro, Payment, Organization
    from app.models_debt_management import Comprobante
    from decimal import Decimal
    import json as _json

    data = await request.json()

    items_req       = data.get("items", [])
    tipo_comp       = data.get("tipo_comprobante", "boleta")
    comprador       = data.get("comprador", {})
    factura_data    = data.get("factura", {})
    metodo_pago     = data.get("metodo_pago", "")
    nro_operacion   = data.get("nro_operacion", "")

    if not items_req:
        return JSONResponse({"error": "Sin items"}, status_code=400)

    org = db.query(Organization).filter(Organization.id == 1).first()
    if not org:
        return JSONResponse({"error": "Organización no encontrada"}, status_code=500)

    # Validar items y calcular total
    total = Decimal("0")
    items_procesados = []

    for item_req in items_req:
        concepto = db.query(ConceptoCobro).filter(
            ConceptoCobro.id             == item_req["concepto_id"],
            ConceptoCobro.activo         == True,
            ConceptoCobro.aplica_a_publico == True,
        ).first()

        if not concepto:
            return JSONResponse({"error": f"Producto {item_req['concepto_id']} no encontrado"}, status_code=400)

        cantidad = int(item_req.get("cantidad", 1))

        if concepto.maneja_stock:
            if (concepto.stock_actual or 0) < cantidad:
                return JSONResponse({
                    "error": f"Stock insuficiente de {concepto.nombre}. Disponible: {concepto.stock_actual}"
                }, status_code=400)
            concepto.stock_actual -= cantidad

        monto_unitario = Decimal(str(concepto.monto_base))
        monto_total    = monto_unitario * cantidad
        total         += monto_total

        items_procesados.append({
            "concepto_id":     concepto.id,
            "codigo":          concepto.codigo,
            "nombre":          concepto.nombre,
            "cantidad":        cantidad,
            "monto_unitario":  float(monto_unitario),
            "monto_total":     float(monto_total),
            "afecto_igv":      concepto.afecto_igv,
        })

    # Crear Payment
    notes_data = {
        "flujo":          "tienda_publica",
        "comprador":      comprador,
        "items":          items_procesados,
        "tipo_comprobante": tipo_comp,
    }
    if factura_data:
        notes_data["factura"] = factura_data

    # Serie según tipo: B800 boleta, F800 factura
    serie = "F800" if tipo_comp == "factura" else "B800"

    payment = Payment(
        organization_id = org.id,
        amount          = total,
        payment_method  = metodo_pago or "pendiente",
        operation_code  = nro_operacion or "pendiente",
        notes           = _json.dumps(notes_data, ensure_ascii=False),
        status          = "review" if metodo_pago in ("yape","plin","transferencia") else "pending",
    )
    db.add(payment)
    db.flush()

    # Emitir CPE vía Facturalo
    cpe_info = None
    try:
        from app.services.facturacion import FacturacionService
        facturacion = FacturacionService(db, org.id)

        if facturacion.esta_configurado():
            tipo_cpe = "01" if tipo_comp == "factura" else "03"

            cliente = {}
            if tipo_comp == "factura" and factura_data.get("ruc"):
                cliente = {
                    "tipo_documento": "6",
                    "numero_documento": factura_data["ruc"],
                    "razon_social":    factura_data.get("razon_social", ""),
                    "direccion":       factura_data.get("direccion", ""),
                }
            else:
                cliente = {
                    "tipo_documento": "1",
                    "numero_documento": comprador.get("dni", "00000000"),
                    "razon_social":    comprador.get("nombre", "CLIENTE VARIOS"),
                }

            items_cpe = [{
                "descripcion":        i["nombre"],
                "cantidad":           i["cantidad"],
                "unidad_medida":      "NIU",
                "precio_unitario":    i["monto_unitario"],
                "tipo_afectacion_igv": "20" if i.get("afecto_igv") else "20",
            } for i in items_procesados]

            resultado = await facturacion.emitir_comprobante(
                tipo_comprobante = tipo_cpe,
                serie            = serie,
                cliente          = cliente,
                items            = items_cpe,
                payment_id       = payment.id,
                forma_pago       = "Contado",
            )

            if resultado.get("exito"):
                cpe_info = resultado.get("comprobante")
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"[Tienda] Error CPE: {e}")

    db.commit()

    return JSONResponse({
        "ok":          True,
        "payment_id":  payment.id,
        "total":       float(total),
        "estado":      payment.status,
        "comprobante": cpe_info,
        "mensaje":     "Compra registrada. " + (
            f"Comprobante {cpe_info['numero_formato']} emitido." if cpe_info else
            "El comprobante se emitirá al validar el pago."
        ),
    })
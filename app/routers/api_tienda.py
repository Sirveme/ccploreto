"""
app/routers/api_tienda.py
Endpoints públicos para la tienda/catálogo de merchandising CCPL.
Series B800 (boleta) y F800 (factura) para portal web.
"""

import base64
import json
import logging
import os

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from app.database import get_db

router = APIRouter(prefix="/api/publico", tags=["Tienda Pública"])

# Router sin prefix para páginas HTML de la tienda
router_paginas = APIRouter(tags=["Tienda Páginas"])

TZ_PERU = timezone(timedelta(hours=-5))

logger = logging.getLogger(__name__)

# apis.net.pe — funciona sin token (rate limited) o con token vía env
APIS_NET_PE_KEY = os.getenv("APIS_NET_PE_KEY", "")

# OpenAI — usado por /analizar-voucher (visión multimodal)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")


# ── ENDPOINT 0: Consulta DNI pública (RENIEC vía apis.net.pe) ──
@router.get("/dni/{dni}")
async def consultar_dni_publico(dni: str):
    """
    Consulta DNI en apis.net.pe — sin login requerido.
    Retorna: { ok, dni, nombre } o { ok: false, error }
    """
    import httpx

    if not dni.isdigit() or len(dni) != 8:
        return JSONResponse(
            {"ok": False, "error": "DNI debe tener 8 dígitos"},
            status_code=400,
        )

    try:
        headers = {"Accept": "application/json"}
        if APIS_NET_PE_KEY:
            headers["Authorization"] = f"Bearer {APIS_NET_PE_KEY}"

        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(
                f"https://api.apis.net.pe/v1/reniec/dni?numero={dni}",
                headers=headers,
            )

        if r.status_code == 200:
            d = r.json()
            nombre = (
                d.get("nombreCompleto")
                or f"{d.get('nombres','')} {d.get('apellidoPaterno','')} {d.get('apellidoMaterno','')}".strip()
            )
            return JSONResponse({"ok": True, "dni": dni, "nombre": nombre})

    except Exception as e:
        logger.warning(f"[DNI] Error consultando {dni}: {e}")

    # Fallback — dejar campo editable
    return JSONResponse({"ok": False, "error": "No se pudo consultar el DNI"})


# ── ENDPOINT 0b: Analizar voucher público (OCR IA sin login) ──
@router.post("/analizar-voucher")
async def analizar_voucher_publico(
    voucher: UploadFile = File(...),
):
    """
    Analiza una imagen de voucher (Yape/Plin/transferencia) con OpenAI
    GPT-4o-mini. SIN login requerido, SIN upload a GCS, SIN persistencia en BD.

    Retorna: { ok, amount, operation_code, date, bank, app_emisora }
    """
    from openai import OpenAI

    if not OPENAI_API_KEY:
        return JSONResponse({"ok": False, "msg": "OCR no configurado"}, status_code=503)

    raw = ""
    try:
        contents     = await voucher.read()
        base64_image = base64.b64encode(contents).decode("utf-8")
        content_type = voucher.content_type or "image/jpeg"

        client = OpenAI(api_key=OPENAI_API_KEY)

        prompt = """
Analiza esta imagen de un comprobante de pago (Yape, Plin, Transferencia BCP/Interbank/BBVA/Scotiabank).

Extrae estrictamente en formato JSON:
- "amount": monto total (número decimal, sin símbolo de moneda, ej: 500.00)
- "operation_code": número de operación o ID de transacción (string)
- "date": fecha y hora si es visible (formato YYYY-MM-DD HH:MM), si no: null
- "app_emisora": app o banco que EMITIÓ el documento — leer del título o encabezado
  (ej: "Yape", "Plin", "BCP", "Interbank", "BBVA", "Scotiabank")
- "destino": valor exacto del campo "Destino" en el voucher (ej: "Yape", "Plin", "BBVA")
- "bank": banco detectado — derivar de app_emisora
  (Yape→BCP, Plin→Interbank, si no está claro usar el nombre del banco directamente)

Si no encuentras algún dato, pon null. No inventes datos.
Responde SOLO el JSON, sin texto adicional ni markdown.
"""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {
                        "url": f"data:{content_type};base64,{base64_image}"
                    }},
                ],
            }],
            max_tokens=300,
        )

        raw   = response.choices[0].message.content
        clean = raw.replace("```json", "").replace("```", "").strip()
        data  = json.loads(clean)

        logger.info(f"[OCR público] banco={data.get('bank')} monto={data.get('amount')}")

        return JSONResponse({
            "ok":             True,
            "amount":         data.get("amount"),
            "operation_code": data.get("operation_code"),
            "date":           data.get("date"),
            "bank":           data.get("bank"),
            "app_emisora":    data.get("app_emisora"),
        })

    except json.JSONDecodeError:
        logger.warning(f"[OCR público] Respuesta no parseable: {raw[:200] if raw else '(vacío)'}")
        return JSONResponse({
            "ok":  False,
            "msg": "No se pudo leer el voucher. Ingresa los datos manualmente.",
        })
    except Exception as e:
        logger.error(f"[OCR público] Error: {e}", exc_info=True)
        return JSONResponse({"ok": False, "msg": "Error al analizar el voucher."})


# ══════════════════════════════════════════════════════════════
#  HELPERS INTERNOS (reusados por /comprar y webhook OpenPay)
# ══════════════════════════════════════════════════════════════
async def _emitir_cpe_tienda_y_stock(db: Session, payment, org) -> dict | None:
    """
    Para un Payment de flujo 'tienda_publica_openpay' o 'tienda_publica':
      1. Descuenta el stock de cada item en conceptos_cobro
      2. Emite CPE vía FacturacionService con sede_id="8" (B800/F800)
      3. Actualiza payment.notes con 'cpe_numero' y 'cpe_pdf_url' si se emitió

    Retorna el dict de resultado de FacturacionService o None si no se emitió.
    NO hace commit — eso lo hace el caller.
    """
    import json as _json
    import logging
    from app.models import ConceptoCobro

    logger = logging.getLogger(__name__)

    try:
        notas = _json.loads(payment.notes or "{}") if payment.notes else {}
    except Exception:
        notas = {}

    items_procesados = notas.get("items", [])
    comprador        = notas.get("comprador", {}) or {}
    factura_data     = notas.get("factura", {}) or {}
    tipo_comp        = notas.get("tipo_comprobante", "boleta")

    # ── 1. Descontar stock ───────────────────────────────────
    for it in items_procesados:
        concepto = db.query(ConceptoCobro).filter(
            ConceptoCobro.id == it.get("concepto_id")
        ).first()
        if concepto and concepto.maneja_stock:
            nuevo_stock = (concepto.stock_actual or 0) - int(it.get("cantidad", 0))
            concepto.stock_actual = max(0, nuevo_stock)

    # ── 2. Emitir CPE ────────────────────────────────────────
    cpe_info = None
    try:
        from app.services.facturacion import FacturacionService

        svc = FacturacionService(db, org.id)
        if not svc.esta_configurado():
            logger.warning(f"[Tienda helper] Facturación no configurada payment={payment.id}")
            return None

        tipo_cpe = "01" if tipo_comp == "factura" else "03"

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

        resultado = await svc.emitir_comprobante_por_pago(
            payment_id           = payment.id,
            tipo                 = tipo_cpe,
            sede_id              = "8",   # B800 / F800
            forma_pago           = notas.get("metodo_pago") or "tarjeta",
            forzar_datos_cliente = datos_cliente,
        )

        if resultado.get("success"):
            cpe_info = resultado
            # Anotar CPE en notes para referencia futura
            notas["cpe_numero"]  = resultado.get("numero_formato")
            notas["cpe_pdf_url"] = resultado.get("pdf_url")
            payment.notes = _json.dumps(notas, ensure_ascii=False)
            logger.info(f"[Tienda helper] CPE emitido payment={payment.id} numero={notas['cpe_numero']}")
        else:
            logger.warning(f"[Tienda helper] CPE falló payment={payment.id}: {resultado.get('error')}")

    except Exception as e:
        logger.error(f"[Tienda helper] Error emitiendo CPE payment={payment.id}: {e}", exc_info=True)

    return cpe_info


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


# ── ENDPOINT 3: Iniciar cargo OpenPay público (tarjeta sin login) ──
@router.post("/openpay/iniciar")
async def iniciar_openpay_publico(
    request: Request,
    db:      Session = Depends(get_db),
):
    """
    Crea un Payment público (status=pending) y un cargo OpenPay redirect
    para que un visitante (sin login) pague la tienda con tarjeta.

    Body JSON:
    {
        "items":            [{"concepto_id": 5, "cantidad": 2}],
        "tipo_comprobante": "boleta" | "factura",
        "comprador":        {"nombre": "Juan Pérez", "dni": "12345678", "email": "a@b.com"},
        "factura":          {"ruc": "20...", "razon_social": "...", "direccion": "..."}  # opcional
    }

    Respuesta:
    { "ok": true, "payment_id": 123, "redirect_url": "https://..." }
    """
    import json as _json
    from app.models import ConceptoCobro, Payment, Organization
    from app.services import openpay_service
    from app.services.openpay_service import OpenPayError, APP_BASE_URL

    data         = await request.json()
    items_req    = data.get("items", [])
    tipo_comp    = data.get("tipo_comprobante", "boleta")
    comprador    = data.get("comprador", {}) or {}
    factura_data = data.get("factura", {}) or {}

    if not items_req:
        return JSONResponse({"error": "Sin items en el carrito"}, status_code=400)

    # Validación mínima del comprador
    nombre = (comprador.get("nombre") or "").strip()
    dni    = (comprador.get("dni")    or "").strip()
    email  = (comprador.get("email")  or "").strip()
    if not nombre or not dni or not email:
        return JSONResponse(
            {"error": "Nombre, DNI y email son obligatorios"},
            status_code=400,
        )
    if len(dni) != 8 or not dni.isdigit():
        return JSONResponse({"error": "DNI inválido (8 dígitos)"}, status_code=400)

    org = db.query(Organization).filter(Organization.id == 1).first()
    if not org:
        return JSONResponse({"error": "Organización no encontrada"}, status_code=500)

    # ── Validar items y calcular total (misma lógica que /comprar) ──
    total            = Decimal("0")
    items_procesados = []

    for item_req in items_req:
        concepto = db.query(ConceptoCobro).filter(
            ConceptoCobro.id               == item_req["concepto_id"],
            ConceptoCobro.activo           == True,
            ConceptoCobro.aplica_a_publico == True,
        ).first()

        if not concepto:
            return JSONResponse(
                {"error": f"Producto {item_req.get('concepto_id')} no encontrado"},
                status_code=400,
            )

        cantidad = int(item_req.get("cantidad", 1))

        if concepto.maneja_stock and (concepto.stock_actual or 0) < cantidad:
            return JSONResponse({
                "error": f"Stock insuficiente de {concepto.nombre}. "
                         f"Disponible: {concepto.stock_actual}"
            }, status_code=400)

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

    if total <= 0:
        return JSONResponse({"error": "Total inválido"}, status_code=400)

    # ── Crear Payment en status pending (stock se descuenta al aprobar webhook) ──
    notes_data = {
        "flujo":            "tienda_publica_openpay",
        "comprador":        {"nombre": nombre, "dni": dni, "email": email},
        "items":            items_procesados,
        "tipo_comprobante": tipo_comp,
    }
    if factura_data:
        notes_data["factura"] = factura_data

    payment = Payment(
        organization_id = org.id,
        amount          = total,
        payment_method  = "tarjeta",
        operation_code  = "pendiente",
        notes           = _json.dumps(notes_data, ensure_ascii=False),
        status          = "pending",
    )
    db.add(payment)
    db.flush()

    # ── Crear cargo OpenPay redirect ──
    try:
        order_id      = openpay_service.construir_order_id(payment.id)
        # Ej: "CCPL: Gorro Institucional x2, Polo Institucional x1"
        partes = [f"{i['nombre']} x{i['cantidad']}" for i in items_procesados]
        descripcion = f"CCPL: {', '.join(partes)}"[:250]
        redirect_url  = f"{APP_BASE_URL}/tienda/pago-resultado?payment={payment.id}"

        resultado = await openpay_service.crear_cargo_redirect(
            order_id       = order_id,
            amount         = float(total),
            description    = descripcion,
            customer_name  = nombre,
            customer_email = email,
            redirect_url   = redirect_url,
        )

        # Guardar transaction_id de OpenPay en el Payment
        tx_id = resultado.get("id")
        if tx_id:
            notes_data["openpay_transaction_id"] = tx_id
            payment.notes          = _json.dumps(notes_data, ensure_ascii=False)
            payment.operation_code = tx_id

        pay_url = (resultado.get("payment_method") or {}).get("url")
        if not pay_url:
            raise OpenPayError("OpenPay no devolvió URL de pago", code="NO_URL")

        db.commit()

        return JSONResponse({
            "ok":           True,
            "payment_id":   payment.id,
            "redirect_url": pay_url,
        })

    except OpenPayError as e:
        db.rollback()
        return JSONResponse(
            {"error": f"OpenPay: {str(e)}", "code": getattr(e, "code", None)},
            status_code=502,
        )
    except Exception as e:
        db.rollback()
        import logging
        logging.getLogger(__name__).error(f"[Tienda/OpenPay] Error: {e}", exc_info=True)
        return JSONResponse(
            {"error": "No se pudo iniciar el pago. Intenta más tarde."},
            status_code=500,
        )


# ══════════════════════════════════════════════════════════════
#  PÁGINA DE RESULTADO TRAS REDIRECT DE OPENPAY
#  (registrada en router_paginas SIN prefix /api/publico)
# ══════════════════════════════════════════════════════════════
@router_paginas.get("/tienda/pago-resultado", response_class=HTMLResponse)
async def tienda_pago_resultado(
    request: Request,
    payment: int,
    db:      Session = Depends(get_db),
):
    """
    Página HTML de retorno tras el checkout OpenPay público.
    - Lee el Payment por id
    - Consulta estado en OpenPay vía consultar_cargo(transaction_id)
    - Muestra confirmación, nº de comprobante (si ya se emitió) o mensaje de espera
    """
    import json as _json
    import logging
    from app.models import Payment
    from app.services.openpay_service import consultar_cargo, OpenPayError

    logger = logging.getLogger(__name__)

    pay = db.query(Payment).filter(Payment.id == payment).first()
    if not pay:
        return HTMLResponse(
            _render_tienda_resultado(
                titulo="Pago no encontrado",
                estado="error",
                mensaje="No encontramos la transacción indicada. Si ya pagaste, revisa tu correo o contáctanos.",
                cpe_numero=None,
                cpe_pdf_url=None,
            ),
            status_code=404,
        )

    # Leer notes para CPE y transaction_id
    try:
        notas = _json.loads(pay.notes or "{}") if pay.notes else {}
    except Exception:
        notas = {}

    tx_id       = notas.get("openpay_transaction_id") or (pay.operation_code or "")
    cpe_numero  = notas.get("cpe_numero")
    cpe_pdf_url = notas.get("cpe_pdf_url")

    # Si el payment ya está approved (webhook procesó) → mostrar éxito directo
    if pay.status == "approved":
        return HTMLResponse(_render_tienda_resultado(
            titulo="¡Pago exitoso!",
            estado="ok",
            mensaje=(
                "Tu compra fue registrada correctamente. "
                "El comprobante también llegará a tu correo."
            ),
            cpe_numero=cpe_numero,
            cpe_pdf_url=cpe_pdf_url,
        ))

    # Consultar estado directamente en OpenPay (fallback al webhook)
    estado_op = None
    if tx_id:
        try:
            cargo = await consultar_cargo(tx_id)
            estado_op = cargo.get("status")
        except OpenPayError as e:
            logger.error(f"[Tienda resultado] consultar_cargo {tx_id}: {e}")

    if estado_op == "completed":
        return HTMLResponse(_render_tienda_resultado(
            titulo="¡Pago exitoso!",
            estado="ok",
            mensaje=(
                "Hemos recibido la confirmación de OpenPay. "
                "Tu comprobante se emitirá en breve y te llegará por correo."
            ),
            cpe_numero=cpe_numero,
            cpe_pdf_url=cpe_pdf_url,
        ))

    if estado_op in ("charge_pending", "in_progress"):
        return HTMLResponse(_render_tienda_resultado(
            titulo="Pago en proceso",
            estado="pending",
            mensaje=(
                "Tu pago está siendo procesado por OpenPay. "
                "Recibirás un correo cuando se confirme."
            ),
            cpe_numero=None,
            cpe_pdf_url=None,
        ))

    # Rechazado, cancelado, expirado o desconocido
    return HTMLResponse(_render_tienda_resultado(
        titulo="Pago no completado",
        estado="error",
        mensaje=(
            "El pago no se pudo completar. "
            "Puedes volver a intentarlo desde la tienda."
        ),
        cpe_numero=None,
        cpe_pdf_url=None,
    ))


def _render_tienda_resultado(
    titulo:      str,
    estado:      str,          # 'ok' | 'pending' | 'error'
    mensaje:     str,
    cpe_numero:  str | None,
    cpe_pdf_url: str | None,
) -> str:
    """Template HTML inline para la página de resultado de tienda."""
    colores = {
        "ok":      {"c": "#22c55e", "bg": "rgba(34,197,94,.12)",  "bd": "rgba(34,197,94,.35)",  "icon": "check_circle"},
        "pending": {"c": "#f59e0b", "bg": "rgba(245,158,11,.12)", "bd": "rgba(245,158,11,.35)", "icon": "hourglass_top"},
        "error":   {"c": "#ef4444", "bg": "rgba(239,68,68,.12)",  "bd": "rgba(239,68,68,.35)",  "icon": "error"},
    }.get(estado, {"c": "#94a3b8", "bg": "rgba(148,163,184,.12)", "bd": "rgba(148,163,184,.35)", "icon": "info"})

    cpe_block = ""
    if cpe_numero:
        pdf_link = ""
        if cpe_pdf_url:
            pdf_link = (
                f'<a href="{cpe_pdf_url}" target="_blank" rel="noopener" '
                f'style="display:inline-flex;align-items:center;gap:6px;margin-top:10px;'
                f'padding:8px 16px;background:rgba(16,185,129,.12);border:1px solid rgba(16,185,129,.35);'
                f'border-radius:8px;color:#22c55e;text-decoration:none;font-size:13px;font-weight:600">'
                f'<span class="material-icons" style="font-size:16px">download</span> Descargar PDF</a>'
            )
        cpe_block = (
            f'<div style="margin-top:14px;padding:12px;background:rgba(255,255,255,.03);'
            f'border:1px solid rgba(255,255,255,.08);border-radius:10px">'
            f'<div style="font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:#64748b;margin-bottom:4px">'
            f'Comprobante emitido</div>'
            f'<div style="font-size:16px;font-weight:700;color:#e2eaf7">{cpe_numero}</div>'
            f'{pdf_link}</div>'
        )

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{titulo} — Tienda CCPL</title>
  <link href="https://fonts.googleapis.com/icon?family=Material+Icons" rel="stylesheet">
  <link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700&family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
  <style>
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      font-family: 'Inter', system-ui, sans-serif;
      background: radial-gradient(ellipse at top, #0f172a 0%, #020617 100%);
      color: #e2eaf7;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 20px;
    }}
    .card {{
      max-width: 440px;
      width: 100%;
      padding: 36px 28px;
      background: rgba(255,255,255,.04);
      backdrop-filter: blur(14px);
      -webkit-backdrop-filter: blur(14px);
      border: 1px solid rgba(255,255,255,.08);
      border-radius: 20px;
      text-align: center;
      box-shadow: 0 20px 60px rgba(0,0,0,.4);
    }}
    .icon-wrap {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 80px; height: 80px;
      border-radius: 50%;
      background: {colores['bg']};
      border: 2px solid {colores['bd']};
      margin-bottom: 18px;
    }}
    .icon-wrap .material-icons {{
      font-size: 44px;
      color: {colores['c']};
    }}
    h1 {{
      font-family: 'Playfair Display', serif;
      font-size: 26px;
      margin: 0 0 10px;
      color: #e2eaf7;
    }}
    p.msg {{
      font-size: 14px;
      line-height: 1.6;
      color: #94a3b8;
      margin: 0;
    }}
    .actions {{
      margin-top: 22px;
      display: flex;
      gap: 10px;
      justify-content: center;
      flex-wrap: wrap;
    }}
    .btn {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 11px 20px;
      border-radius: 999px;
      font-size: 13px;
      font-weight: 700;
      text-decoration: none;
      border: none;
      cursor: pointer;
      font-family: inherit;
    }}
    .btn-primary {{
      background: linear-gradient(135deg,#10b981,#059669);
      color: #fff;
      box-shadow: 0 6px 18px rgba(16,185,129,.25);
    }}
    .btn-ghost {{
      background: transparent;
      color: #94a3b8;
      border: 1px solid rgba(255,255,255,.15);
    }}
  </style>
</head>
<body>
  <div class="card">
    <div class="icon-wrap">
      <span class="material-icons">{colores['icon']}</span>
    </div>
    <h1>{titulo}</h1>
    <p class="msg">{mensaje}</p>
    {cpe_block}
    <div class="actions">
      <a href="/" class="btn btn-primary">
        <span class="material-icons" style="font-size:16px">home</span> Ir al inicio
      </a>
      <a href="/#tienda" class="btn btn-ghost">
        <span class="material-icons" style="font-size:16px">storefront</span> Ver tienda
      </a>
    </div>
  </div>
</body>
</html>"""
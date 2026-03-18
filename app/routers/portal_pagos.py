"""
Router: Pagos del Portal de Colegiados
app/routers/portal_pagos.py

Endpoints:
  POST /api/portal/reportar-pago      → reporta pago manual con voucher
  POST /api/portal/analizar-voucher   → OCR de voucher con GPT-4o-mini
  GET  /api/portal/ruc/{ruc}          → consulta RUC en apis.net.pe
"""

from datetime import datetime
from typing import Optional

import base64
import json
import httpx
import os
import logging

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from openai import OpenAI

from app.database import get_db
from app.models import Colegiado, Member, Payment, Comprobante
from app.models_debt_management import Debt
from app.routers.dashboard import get_current_member
from app.utils.gcs import upload_documento
from app.services.motor_matching import matching_al_reportar, aplicar_match

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/portal", tags=["portal-pagos"])

OPENAI_API_KEY  = os.getenv("OPENAI_API_KEY", "")
APIS_NET_PE_KEY = os.getenv("APIS_NET_PE_KEY", "")
METODOS_VALIDOS = {'yape', 'plin', 'transferencia', 'bbva', 'bcp', 'interbank', 'scotiabank'}
MAX_VOUCHER_MB  = 10


# ── Shared helpers ────────────────────────────────────────────────────────────
def _get_colegiado_by_member(member: Member, db: Session) -> Colegiado:
    """Obtiene el colegiado por member_id o DNI."""
    col = db.query(Colegiado).filter(
        Colegiado.member_id       == member.id,
        Colegiado.organization_id == member.organization_id,
    ).first()
    if not col and member.user:
        col = db.query(Colegiado).filter(
            Colegiado.organization_id == member.organization_id,
            Colegiado.dni             == member.user.public_id,
        ).first()
    return col


# ── Endpoint ───────────────────────────────────────────────────────────────────
@router.post("/reportar-pago")
async def reportar_pago(
    monto:                float         = Form(...),
    nro_operacion:        str           = Form(...),
    metodo:               str           = Form(...),
    deuda_ids:            str           = Form(""),
    fracc_codigo:         Optional[str] = Form(None),
    concepto:             Optional[str] = Form(None),
    solicitar_constancia: bool          = Form(False),
    # Comprobante electrónico
    tipo_comprobante:     Optional[str] = Form(None),   # 'boleta' | 'factura'
    factura_ruc:          Optional[str] = Form(None),
    factura_razon_social: Optional[str] = Form(None),
    factura_direccion:    Optional[str] = Form(None),
    voucher:              UploadFile    = File(...),
    member:               Member        = Depends(get_current_member),
    db:                   Session       = Depends(get_db),
):
    # ── Validaciones ─────────────────────────────────────────────────────────
    if monto <= 0:
        return JSONResponse(
            {"ok": False, "error": "El monto debe ser mayor a cero."},
            status_code=400
        )
 
    nro_operacion = nro_operacion.strip()
    if not nro_operacion:
        return JSONResponse(
            {"ok": False, "error": "El N° de operación es obligatorio."},
            status_code=400
        )
 
    if metodo.lower() not in METODOS_VALIDOS:
        return JSONResponse(
            {"ok": False, "error": f"Método inválido: {metodo}"},
            status_code=400
        )
 
    if not voucher or not voucher.filename:
        return JSONResponse(
            {"ok": False, "error": "El voucher es obligatorio."},
            status_code=400
        )
 
    voucher_bytes = await voucher.read()
    if len(voucher_bytes) > MAX_VOUCHER_MB * 1024 * 1024:
        return JSONResponse(
            {"ok": False, "error": f"El voucher no debe superar {MAX_VOUCHER_MB}MB."},
            status_code=400
        )
 
    # ── Obtener colegiado ─────────────────────────────────────────────────────
    colegiado = db.query(Colegiado).filter(
        Colegiado.member_id       == member.id,
        Colegiado.organization_id == member.organization_id,
    ).first()
 
    if not colegiado:
        return JSONResponse(
            {"ok": False, "error": "Colegiado no encontrado."},
            status_code=404
        )
 
    # ── Subir voucher a GCS ───────────────────────────────────────────────────
    ts           = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    ext          = _ext_segura(voucher.content_type, voucher.filename)
    blob_path    = f"{member.organization_id}/pagos/{colegiado.id}/voucher_{ts}.{ext}"
    content_type = voucher.content_type or 'image/jpeg'
 
    voucher_path = upload_documento(
        file_bytes   = voucher_bytes,
        content_type = content_type,
        blob_path    = blob_path,
    )
 
    if not voucher_path:
        logger.warning(
            f'[ReportePago] GCS no disponible — '
            f'voucher no subido para colegiado {colegiado.id}'
        )
 
    # ── Preparar notas ────────────────────────────────────────────────────────
    notas = {
        "deuda_ids":            [int(x) for x in deuda_ids.split(',') if x.strip().isdigit()],
        "fracc_codigo":         fracc_codigo or None,
        "concepto":             concepto or None,
        "tipo_comprobante":     tipo_comprobante or None,
        "factura_ruc":          factura_ruc or None,
        "factura_razon_social": factura_razon_social or None,
        "factura_direccion":    factura_direccion or None,
    }
 
    # ── Crear Payment ─────────────────────────────────────────────────────────
    nombre_colegiado = getattr(colegiado, 'nombre_completo', None) \
                    or getattr(colegiado, 'nombres', None)
 
    payment = Payment(
        organization_id = member.organization_id,
        colegiado_id    = colegiado.id,
        amount          = round(monto, 2),
        currency        = 'PEN',
        payment_method  = metodo.lower(),
        operation_code  = nro_operacion.upper(),
        voucher_url     = voucher_path,
        pagador_tipo    = 'titular',
        pagador_nombre  = nombre_colegiado,
        status          = 'review',
        notes           = json.dumps(notas, ensure_ascii=False),
    )
    db.add(payment)
    db.flush()  # necesitamos payment.id antes del commit
 
    # ── Matching automático con notificaciones bancarias ──────────────────────
    nivel        = 0
    notificacion = None
 
    try:
        notificacion, nivel = matching_al_reportar(
            nro_operacion   = nro_operacion,
            monto           = round(monto, 2),
            fecha_pago      = datetime.utcnow(),
            metodo          = metodo,
            organization_id = member.organization_id,
            db              = db,
        )
 
        if notificacion and nivel >= 2:
            aplicar_match(
                notificacion    = notificacion,
                reporte_pago_id = payment.id,
                nivel           = nivel,
                conciliado_por  = 'auto',
                db              = db,
            )
            # Nivel 3 = aprobación automática, nivel 2 = sigue en review para caja
            if nivel == 3:
                payment.status = 'approved'
            notificacion.payment_id = payment.id
            db.flush()
 
    except Exception as e:
        logger.error(f'[ReportePago] Error en matching: {e}', exc_info=True)
        # El pago se guarda igual aunque el matching falle
 
    # ── Emitir comprobante si pago auto-aprobado (nivel 3) ─────────────────────
    comprobante_info = None
    if payment.status == 'approved' and tipo_comprobante in ('boleta', 'factura'):
        try:
            from app.services.facturacion import FacturacionService
            svc = FacturacionService(db, member.organization_id)
            if svc.esta_configurado():
                tipo_doc     = "01" if tipo_comprobante == "factura" else "03"
                forzar_datos = None
                if tipo_comprobante == "factura" and factura_ruc:
                    forzar_datos = {
                        "tipo_doc":  "6",
                        "num_doc":   factura_ruc,
                        "nombre":    factura_razon_social or "CLIENTE",
                        "direccion": factura_direccion or "",
                        "email":     None,
                    }
                comprobante_info = await svc.emitir_comprobante_por_pago(
                    payment.id,
                    tipo                 = tipo_doc,
                    forzar_datos_cliente = forzar_datos,
                )
                if comprobante_info.get("success"):
                    logger.info(
                        f'[ReportePago] Comprobante emitido: '
                        f'{comprobante_info.get("numero_formato")} '
                        f'pdf={comprobante_info.get("pdf_url")}'
                    )
                else:
                    logger.warning(
                        f'[ReportePago] Comprobante no emitido: '
                        f'{comprobante_info.get("error")}'
                    )
        except Exception as e:
            logger.error(f'[ReportePago] Error emitiendo comprobante: {e}', exc_info=True)

    db.commit()
 
    # ── Mensaje para el chat ──────────────────────────────────────────────────
    if nivel == 3:
        pdf_link = ""
        if comprobante_info and comprobante_info.get("success") and comprobante_info.get("pdf_url"):
            num_fmt  = comprobante_info.get("numero_formato", "")
            pdf_url  = comprobante_info["pdf_url"]
            tipo_nom = "Factura" if tipo_comprobante == "factura" else "Boleta"
            pdf_link = (
                f'<br>📄 <a href="{pdf_url}" target="_blank" '
                f'style="color:var(--emerald-soft)">'
                f'{tipo_nom} {num_fmt} — Descargar PDF</a>'
            )
        mensaje = (
            f'✅ ¡Pago verificado automáticamente! El N° de operación '
            f'<strong>{nro_operacion}</strong> coincide con la notificación '
            f'del banco. Tu cuenta será actualizada en breve.{pdf_link}'
        )
    elif nivel == 2:
        mensaje = (
            f'✅ Pago reportado. El monto S/ {monto:.2f} coincide con un '
            f'registro del banco. La caja confirmará en pocas horas.'
        )
    else:
        mensaje = (
            f'📤 Pago reportado correctamente. La caja validará tu voucher '
            f'en hasta 24h y recibirás una notificación al aprobar.'
        )
 
    logger.info(
        f'[ReportePago] payment_id={payment.id} colegiado={colegiado.id} '
        f'monto={monto} nivel_match={nivel} status={payment.status}'
    )
 
    return JSONResponse({
        "ok":          True,
        "payment_id":  payment.id,
        "estado":      payment.status,
        "nivel_match": nivel,
        "mensaje":     mensaje,
    })
 
 
def _ext_segura(content_type: str, filename: str) -> str:
    ct_map = {
        'image/jpeg':      'jpg',
        'image/jpg':       'jpg',
        'image/png':       'png',
        'image/webp':      'webp',
        'image/gif':       'gif',
        'application/pdf': 'pdf',
    }
    ext = ct_map.get((content_type or '').lower())
    if ext:
        return ext
    if filename and '.' in filename:
        return filename.rsplit('.', 1)[-1].lower()[:5]
    return 'jpg'




# ══════════════════════════════════════════════════════════════════════════════
# AGREGAR A app/routers/portal_colegiado.py
#
# Imports adicionales:
#   import base64, json
#   from openai import OpenAI
#   import httpx
# ══════════════════════════════════════════════════════════════════════════════

import base64
import json
import httpx
import os
import logging

from fastapi import File, UploadFile
from fastapi.responses import JSONResponse
from openai import OpenAI

logger = logging.getLogger(__name__)

OPENAI_API_KEY  = os.getenv("OPENAI_API_KEY", "")
APIS_NET_PE_KEY = os.getenv("APIS_NET_PE_KEY", "")   # opcional — sin token igual funciona


# ── OCR del voucher ────────────────────────────────────────────────────────────
@router.post("/analizar-voucher")
async def analizar_voucher(
    voucher: UploadFile = File(...),
    member:  Member     = Depends(get_current_member),
):
    """
    Recibe imagen del voucher, devuelve JSON con datos extraídos:
    { amount, operation_code, date, bank, ok }
    """
    if not OPENAI_API_KEY:
        return JSONResponse({"ok": False, "msg": "OCR no configurado"}, status_code=503)

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

        raw     = response.choices[0].message.content
        clean   = raw.replace("```json", "").replace("```", "").strip()
        data    = json.loads(clean)

        logger.info(f"[OCR] colegiado={member.id} banco={data.get('bank')} monto={data.get('amount')}")

        return JSONResponse({
            "ok":             True,
            "amount":         data.get("amount"),
            "operation_code": data.get("operation_code"),
            "date":           data.get("date"),
            "bank":           data.get("bank"),
        })

    except json.JSONDecodeError:
        logger.warning(f"[OCR] Respuesta no parseable: {raw[:200]}")
        return JSONResponse({"ok": False, "msg": "No se pudo leer el voucher. Ingresa los datos manualmente."})
    except Exception as e:
        logger.error(f"[OCR] Error: {e}", exc_info=True)
        return JSONResponse({"ok": False, "msg": "Error al analizar el voucher."})


# ── Consulta RUC (apis.net.pe) ─────────────────────────────────────────────────
@router.get("/ruc/{ruc}")
async def consultar_ruc_portal(ruc: str):
    """
    Consulta RUC en apis.net.pe.
    Retorna: { ok, ruc, nombre, direccion, estado, tipo_ruc }
    tipo_ruc: 'natural' (RUC 10) | 'empresa' (RUC 20)
    Para RUC 10 la dirección puede venir vacía — el frontend la deja editable.
    """
    if len(ruc) != 11 or not ruc.isdigit():
        return JSONResponse({"ok": False, "error": "RUC inválido"}, status_code=400)

    tipo_ruc = "natural" if ruc.startswith("10") else "empresa"

    try:
        headers = {"Accept": "application/json"}
        if APIS_NET_PE_KEY:
            headers["Authorization"] = f"Bearer {APIS_NET_PE_KEY}"

        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(
                f"https://api.apis.net.pe/v1/ruc?numero={ruc}",
                headers={"Accept": "application/json"},
            )

        if r.status_code == 200:
            d = r.json()
            return JSONResponse({
                "ok":        True,
                "ruc":       ruc,
                "nombre":    d.get("nombre") or d.get("razonSocial") or "",
                "direccion": d.get("direccion") or "",
                "estado":    d.get("estado", "ACTIVO"),
                "tipo_ruc":  tipo_ruc,
            })

    except Exception as e:
        logger.warning(f"[RUC] Error consultando {ruc}: {e}")

    # Fallback — dejar campos editables
    return JSONResponse({
        "ok":        False,
        "ruc":       ruc,
        "nombre":    "",
        "direccion": "",
        "estado":    "NO VERIFICADO",
        "tipo_ruc":  tipo_ruc,
        "msg":       "API no disponible — ingresa los datos manualmente.",
    })



"""
Agregar a app/routers/portal_colegiado.py (o a un router de admin)

Endpoint: POST /api/portal/admin/generar-cuotas-ordinarias
- Solo admin
- Para cada colegiado inhábil, genera las cuotas mensuales 2026
  que aún no estén cubiertas por ningún registro en debts
- Idempotente: puede correrse varias veces sin duplicar

Lógica de cobertura de periodos:
  "2026"         → cubre meses 1-12
  "2026-03"      → cubre mes 3
  "2026-01:02"   → cubre meses 1 y 2
  "2026-03:12"   → cubre meses 3 a 12

Imports adicionales necesarios en portal_colegiado.py:
  from app.models import ConceptoCobro  (ya importado)
"""

import calendar
from datetime import date
from typing import Optional
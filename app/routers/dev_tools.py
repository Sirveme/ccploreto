"""
app/routers/dev_tools.py — ColegiosPro
Herramientas de desarrollo — SOLO activas fuera de produccion.

Registrar en main.py:
    import os
    if os.getenv("ENVIRONMENT", "development") != "production":
        from app.routers.dev_tools import router as dev_router
        app.include_router(dev_router)
"""

import logging
import os

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/dev", tags=["Dev Tools"])
IS_DEV = os.getenv("ENVIRONMENT", "development") != "production"


def _check_dev():
    if not IS_DEV:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Not found")


# ── Simular email bancario ─────────────────────────────────────────────────────
@router.post("/simular-email-banco", summary="Simula llegada de email bancario")
async def simular_email_banco(
    raw_email: str = Body(
        ...,
        media_type="text/plain",
        description=(
            "Pega el email completo tal como llega del banco, con saltos de linea reales.\n\n"
            "Ejemplo:\n\n"
            "From: BBVA <procesos@bbva.com.pe>\n"
            "Subject: Transferencia recibida\n"
            "Message-ID: <test-001>\n\n"
            "Importe 500.00\n"
            "Numero de operacion OP-123456\n"
            "Fecha y hora 16/03/2026 14:32:10\n"
            "Ordenante JUAN PEREZ GARCIA"
        ),
    ),
    organization_id: int = 1,
    db: Session = Depends(get_db),
):
    _check_dev()

    from app.services.email_parser import parsear_email
    from app.services.imap_listener import guardar_notificacion

    if not raw_email or not raw_email.strip():
        return JSONResponse({"ok": False, "error": "Email vacio"}, status_code=400)

    raw_bytes = raw_email.encode("utf-8")
    org_id    = organization_id

    import app.services.imap_listener as _listener
    org_original = _listener.ORG_ID
    _listener.ORG_ID = org_id

    try:
        pago = parsear_email(raw_bytes, organization_id=org_id)

        if not pago:
            return JSONResponse({
                "ok": False,
                "motivo": "Parser descarto el email — no parece bancario o es operacion propia.",
            })

        if not pago.es_valido:
            return JSONResponse({
                "ok": False,
                "motivo": "Email parseado pero sin monto valido.",
                "parse_result": {
                    "banco":     pago.banco,
                    "monto":     pago.monto,
                    "nro_op":    pago.nro_operacion,
                    "confianza": pago.confianza,
                },
            })

        if not pago.es_pago_recibido:
            return JSONResponse({
                "ok": False,
                "motivo": f"Operacion propia descartada (tipo: {pago.tipo_operacion}).",
                "parse_result": {
                    "banco":          pago.banco,
                    "monto":          pago.monto,
                    "tipo_operacion": pago.tipo_operacion,
                },
            })

        guardado = guardar_notificacion(pago, from_header="simulado@dev.test", db=db)

        return JSONResponse({
            "ok":      True,
            "guardado": guardado,
            "parse": {
                "banco":          pago.banco,
                "monto":          pago.monto,
                "nro_operacion":  pago.nro_operacion,
                "fecha":          str(pago.fecha_operacion),
                "remitente":      pago.remitente_nombre,
                "concepto":       pago.concepto,
                "tipo_operacion": pago.tipo_operacion,
                "confianza":      f"{pago.confianza}%",
                "es_recibido":    pago.es_pago_recibido,
            },
            "nota": "Guardado en notificaciones_bancarias." if guardado else "Duplicado — ya existia.",
        })

    except Exception as e:
        logger.error(f"[SimularEmail] Error: {e}", exc_info=True)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    finally:
        _listener.ORG_ID = org_original


# ── Ver notificaciones bancarias ───────────────────────────────────────────────
@router.get("/notificaciones", summary="Ultimas notificaciones bancarias en BD")
async def ver_notificaciones(
    limite: int = 20,
    estado: str = "",
    db: Session = Depends(get_db),
):
    _check_dev()
    from app.models import NotificacionBancaria

    q = db.query(NotificacionBancaria).order_by(NotificacionBancaria.created_at.desc())
    if estado:
        q = q.filter(NotificacionBancaria.estado == estado)
    registros = q.limit(limite).all()

    return JSONResponse([{
        "id":            r.id,
        "banco":         r.banco,
        "monto":         float(r.monto),
        "codigo_op":     r.codigo_operacion,
        "fecha_op":      str(r.fecha_operacion),
        "remitente":     r.remitente_nombre,
        "estado":        r.estado,
        "payment_id":    r.payment_id,
        "confianza":     r.observaciones,
        "email_subject": r.email_subject,
        "created_at":    str(r.created_at),
    } for r in registros])


# ── Ver reportes de pago ───────────────────────────────────────────────────────
@router.get("/reportes-pago", summary="Ultimos reportes de pago del portal")
async def ver_reportes_pago(
    limite: int = 20,
    db: Session = Depends(get_db),
):
    _check_dev()
    from app.models import Payment

    pagos = db.query(Payment).filter(
        Payment.voucher_url.isnot(None)
    ).order_by(Payment.created_at.desc()).limit(limite).all()

    return JSONResponse([{
        "id":           p.id,
        "colegiado_id": p.colegiado_id,
        "monto":        p.amount,
        "metodo":       p.payment_method,
        "nro_op":       p.operation_code,
        "status":       p.status,
        "voucher":      p.voucher_url,
        "notes":        p.notes,
        "created_at":   str(p.created_at),
    } for p in pagos])
"""
app/routers/dev_tools.py — ColegiosPro
Herramientas de desarrollo — SOLO activas fuera de producción.

Registrar en main.py:
    import os
    if os.getenv("ENVIRONMENT", "development") != "production":
        from app.routers.dev_tools import router as dev_router
        app.include_router(dev_router)

Endpoints disponibles en /docs cuando ENVIRONMENT != production:
  POST /dev/simular-email-banco    → procesa email pegado como texto
  GET  /dev/notificaciones         → lista últimas notificaciones bancarias en BD
  GET  /dev/reportes-pago          → lista últimos reportes de pago
"""

import os
import logging
from datetime import datetime

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db

logger   = logging.getLogger(__name__)
router   = APIRouter(prefix="/dev", tags=["🛠 Dev Tools"])
IS_DEV   = os.getenv("ENVIRONMENT", "development") != "production"


def _check_dev():
    if not IS_DEV:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Not found")


# ── Simular email bancario ─────────────────────────────────────────────────────
class EmailSimulado(BaseModel):
    raw_email:       str    # texto completo — pegar el email reenviado por Walter
    organization_id: int  = 1
    marcar_leido:    bool = False   # si True, no re-procesa si lo vuelves a enviar

    class Config:
        json_schema_extra = {
            "example": {
                "raw_email": (
                    "From: BBVA <procesos@bbva.com.pe>\n"
                    "Subject: Transferencia recibida en tu cuenta\n"
                    "Message-ID: <test-001@bbva.com.pe>\n"
                    "\n"
                    "Hola, CCPL\n"
                    "TRANSFERENCIA RECIBIDA\n"
                    "Fecha y hora 16/03/2026 14:32:10\n"
                    "Numero de operacion OP-2026031600123\n"
                    "Importe 500.00\n"
                    "Ordenante JUAN CARLOS PEREZ LOPEZ\n"
                    "Concepto Cuota ordinaria mat 10-0274\n"
                ),
                "organization_id": 1,
            }
        }


@router.post("/simular-email-banco", summary="Simula llegada de email bancario")
async def simular_email_banco(
    payload: EmailSimulado,
    db:      Session = Depends(get_db),
):
    _check_dev()

    from app.services.email_parser  import parsear_email
    from app.services.imap_listener import guardar_notificacion

    # Parchar ORG_ID en el listener para esta simulación
    import app.services.imap_listener as _listener
    org_original     = _listener.ORG_ID
    _listener.ORG_ID = payload.organization_id

    raw_bytes = payload.raw_email.encode("utf-8")

    try:
        pago = parsear_email(raw_bytes, organization_id=payload.organization_id)

        if not pago:
            return JSONResponse({
                "ok":     False,
                "motivo": "Parser descartó el email — no parece bancario o es operación propia.",
            })

        if not pago.es_valido:
            return JSONResponse({
                "ok":          False,
                "motivo":      "Email parseado pero sin monto válido.",
                "parse_result": {
                    "banco":     pago.banco,
                    "monto":     pago.monto,
                    "nro_op":    pago.nro_operacion,
                    "confianza": pago.confianza,
                },
            })

        if not pago.es_pago_recibido:
            return JSONResponse({
                "ok":          False,
                "motivo":      f"Operación propia descartada (tipo: {pago.tipo_operacion}).",
                "parse_result": {
                    "banco":          pago.banco,
                    "monto":          pago.monto,
                    "tipo_operacion": pago.tipo_operacion,
                },
            })

        guardado = guardar_notificacion(pago, from_header="simulado@dev.test", db=db)

        return JSONResponse({
            "ok":       True,
            "guardado": guardado,
            "parse":    {
                "banco":           pago.banco,
                "monto":           pago.monto,
                "nro_operacion":   pago.nro_operacion,
                "fecha":           str(pago.fecha_operacion),
                "remitente":       pago.remitente_nombre,
                "concepto":        pago.concepto,
                "tipo_operacion":  pago.tipo_operacion,
                "confianza":       f"{pago.confianza}%",
                "es_recibido":     pago.es_pago_recibido,
            },
            "nota": "Guardado en notificaciones_bancarias." if guardado else "Duplicado — ya existía.",
        })

    finally:
        _listener.ORG_ID = org_original  # restaurar siempre


# ── Ver notificaciones bancarias ───────────────────────────────────────────────
@router.get("/notificaciones", summary="Últimas notificaciones bancarias en BD")
async def ver_notificaciones(
    limite: int      = 20,
    estado: str      = "",
    db:     Session  = Depends(get_db),
):
    _check_dev()
    from app.models import NotificacionBancaria

    q = db.query(NotificacionBancaria).order_by(NotificacionBancaria.created_at.desc())
    if estado:
        q = q.filter(NotificacionBancaria.estado == estado)
    registros = q.limit(limite).all()

    return JSONResponse([{
        "id":              r.id,
        "banco":           r.banco,
        "monto":           float(r.monto),
        "codigo_op":       r.codigo_operacion,
        "fecha_op":        str(r.fecha_operacion),
        "remitente":       r.remitente_nombre,
        "estado":          r.estado,
        "payment_id":      r.payment_id,
        "confianza":       r.observaciones,
        "email_subject":   r.email_subject,
        "created_at":      str(r.created_at),
    } for r in registros])


# ── Ver reportes de pago (payments con método = voucher) ──────────────────────
@router.get("/reportes-pago", summary="Últimos reportes de pago del portal")
async def ver_reportes_pago(
    limite: int     = 20,
    db:     Session = Depends(get_db),
):
    _check_dev()
    from app.models import Payment

    pagos = db.query(Payment).filter(
        Payment.voucher_url.isnot(None)
    ).order_by(Payment.created_at.desc()).limit(limite).all()

    return JSONResponse([{
        "id":             p.id,
        "colegiado_id":   p.colegiado_id,
        "monto":          p.amount,
        "metodo":         p.payment_method,
        "nro_op":         p.operation_code,
        "status":         p.status,
        "voucher":        p.voucher_url,
        "notes":          p.notes,
        "created_at":     str(p.created_at),
    } for p in pagos])
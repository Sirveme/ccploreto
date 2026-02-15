"""
Servicio: Aprobación Automática de Pagos
app/services/aprobar_pago.py

Extrae la lógica de aprobación de pagos_publicos.py en una función reutilizable.
Usada por:
  1. Admin manual: POST /admin/validar/{pago_id} (accion=aprobar)
  2. Auto verificación: POST /api/conciliacion/verificar-pago (cuando el banco confirma)
"""

import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def aprobar_pago(db: Session, payment_id: int, aprobado_por: str = "admin") -> dict:
    """
    Aprueba un pago e imputa a deudas pendientes (FIFO).

    Args:
        db: Sesión de base de datos
        payment_id: ID del pago a aprobar
        aprobado_por: "admin", "auto_realtime", "auto_conciliacion"

    Returns:
        dict con: success, mensaje, saldo_a_favor, certificado (si se emitió)
    """
    from app.models import Payment, Debt, Colegiado

    pago = db.query(Payment).filter(Payment.id == payment_id).first()
    if not pago:
        return {"success": False, "mensaje": "Pago no encontrado"}

    if pago.status == "approved":
        return {"success": True, "mensaje": "Pago ya estaba aprobado", "ya_aprobado": True}

    if pago.status not in ("review", "pending"):
        return {"success": False, "mensaje": f"Pago en estado '{pago.status}', no se puede aprobar"}

    # ── Aprobar ──
    pago.status = "approved"
    pago.reviewed_at = datetime.now(timezone.utc)
    pago.reviewed_by = aprobado_por  # Campo opcional, agregar si no existe

    # ── Imputar a deudas (FIFO por fecha de vencimiento) ──
    deudas = db.query(Debt).filter(
        Debt.colegiado_id == pago.colegiado_id,
        Debt.status.in_(["pending", "partial"])
    ).order_by(Debt.due_date.asc(), Debt.created_at.asc()).all()

    monto_restante = pago.amount

    for deuda in deudas:
        if monto_restante <= 0:
            break
        if monto_restante >= deuda.balance:
            monto_restante -= deuda.balance
            deuda.balance = 0
            deuda.status = "paid"
        else:
            deuda.balance -= monto_restante
            deuda.status = "partial"
            monto_restante = 0

    # ── Verificar si quedó al día → cambiar condición a hábil ──
    deudas_pendientes = db.query(Debt).filter(
        Debt.colegiado_id == pago.colegiado_id,
        Debt.status.in_(["pending", "partial"])
    ).count()

    cambio_habilidad = False
    if deudas_pendientes == 0:
        colegiado = db.query(Colegiado).filter(
            Colegiado.id == pago.colegiado_id
        ).first()
        if colegiado and colegiado.condicion == "inhabil":
            colegiado.condicion = "habil"
            colegiado.fecha_actualizacion_condicion = datetime.now(timezone.utc)
            cambio_habilidad = True
            logger.info(f"Colegiado {pago.colegiado_id} → HÁBIL (pago #{payment_id} por {aprobado_por})")

    # Flush antes de emitir certificado
    db.flush()

    # ── Emitir certificado automáticamente ──
    certificado_info = None
    try:
        from app.services.emitir_certificado_service import emitir_certificado_automatico
        certificado_info = emitir_certificado_automatico(
            db=db,
            colegiado_id=pago.colegiado_id,
            payment_id=pago.id
        )
    except Exception as e:
        logger.warning(f"Error emitiendo certificado para pago #{payment_id}: {e}")

    db.commit()

    # ── Respuesta ──
    respuesta = {
        "success": True,
        "mensaje": "Pago aprobado",
        "aprobado_por": aprobado_por,
        "saldo_a_favor": float(monto_restante) if monto_restante > 0 else 0,
        "cambio_habilidad": cambio_habilidad,
    }

    if certificado_info and certificado_info.get("emitido"):
        respuesta["certificado"] = certificado_info
        respuesta["mensaje"] = f"Pago aprobado. Certificado {certificado_info['codigo']} emitido."

    logger.info(f"Pago #{payment_id} aprobado por {aprobado_por}: {respuesta['mensaje']}")
    return respuesta
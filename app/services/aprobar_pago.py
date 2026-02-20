"""
Servicio: Aprobación Automática de Pagos
app/services/aprobar_pago.py

Extrae la lógica de aprobación de pagos_publicos.py en una función reutilizable.
Usada por:
  1. Admin manual: POST /admin/validar/{pago_id} (accion=aprobar)
  2. Auto verificación: POST /api/conciliacion/verificar-pago (cuando el banco confirma)
"""

import json
import logging
from datetime import date as dt_date, datetime, timedelta, timezone

from dateutil.relativedelta import relativedelta
from sqlalchemy.orm import Session

from app.models_debt_management import (
    Debt,
    Fraccionamiento,
    FraccionamientoCuota,
)

logger = logging.getLogger(__name__)


def aprobar_pago(db: Session, payment_id: int, aprobado_por: str = "admin") -> dict:
    """
    Aprueba un pago e imputa a deudas pendientes (FIFO).

    Args:
        db:           Sesión de base de datos
        payment_id:   ID del pago a aprobar
        aprobado_por: "admin" | "auto_realtime" | "auto_conciliacion"

    Returns:
        dict con: success, mensaje, saldo_a_favor, cambio_habilidad, certificado
    """
    from app.models import Payment, Colegiado

    # ── Obtener y validar pago ────────────────────────────────────────────────
    pago = db.query(Payment).filter(Payment.id == payment_id).first()
    if not pago:
        return {"success": False, "mensaje": "Pago no encontrado"}

    if pago.status == "approved":
        return {"success": True, "mensaje": "Pago ya estaba aprobado", "ya_aprobado": True}

    if pago.status not in ("review", "pending"):
        return {"success": False, "mensaje": f"Pago en estado '{pago.status}', no se puede aprobar"}

    # ── Aprobar ───────────────────────────────────────────────────────────────
    pago.status      = "approved"
    pago.reviewed_at = datetime.now(timezone.utc)
    pago.reviewed_by = aprobado_por

    # ── Imputar a deudas FIFO (por due_date asc, luego created_at asc) ───────
    deudas = (
        db.query(Debt)
        .filter(
            Debt.colegiado_id == pago.colegiado_id,
            Debt.status.in_(["pending", "partial"]),
        )
        .order_by(Debt.due_date.asc(), Debt.created_at.asc())
        .all()
    )

    monto_restante = float(pago.amount or 0)
    for deuda in deudas:
        if monto_restante <= 0:
            break
        if monto_restante >= deuda.balance:
            monto_restante -= deuda.balance
            deuda.balance   = 0.0
            deuda.status    = "paid"
        else:
            deuda.balance  -= monto_restante
            deuda.status    = "partial"
            monto_restante  = 0.0

    # ── Cargar colegiado ──────────────────────────────────────────────────────
    colegiado = db.query(Colegiado).filter(Colegiado.id == pago.colegiado_id).first()

    # ── Determinar habilidad ──────────────────────────────────────────────────
    cambio_habilidad  = False
    habilidad_temporal = False
    habilidad_vence   = None

    deudas_pendientes = (
        db.query(Debt)
        .filter(
            Debt.colegiado_id == pago.colegiado_id,
            Debt.status.in_(["pending", "partial"]),
        )
        .count()
    )

    if deudas_pendientes == 0:
        # Sin deudas → hábil permanente
        if colegiado and colegiado.condicion != "habil":
            colegiado.condicion                      = "habil"
            colegiado.fecha_actualizacion_condicion  = datetime.now(timezone.utc)
            colegiado.tiene_fraccionamiento          = False
            colegiado.habilidad_vence                = None
            cambio_habilidad = True
            logger.info(f"Colegiado {pago.colegiado_id} → HÁBIL permanente (pago #{payment_id})")

    else:
        # Puede tener fraccionamiento activo → procesar cuota específica
        # El portal envía en Payment.notes: {"fraccionamiento_id": N, "numero_cuota": N}
        # Los pagos manuales desde caja no traen meta_fracc → rama genérica
        _procesar_fraccionamiento(db, pago, colegiado, payment_id)

        # Si el bloque anterior cambió la condición ya lo logueó.
        # Leemos si cambió para construir la respuesta.
        if colegiado and colegiado.condicion == "habil":
            cambio_habilidad  = True
            habilidad_temporal = True
            if colegiado.habilidad_vence:
                habilidad_vence = colegiado.habilidad_vence.strftime("%d/%m/%Y")

    # ── Flush antes de emitir certificado ────────────────────────────────────
    db.flush()

    # ── Emitir certificado automáticamente ───────────────────────────────────
    certificado_info = None
    try:
        from app.services.emitir_certificado_service import emitir_certificado_automatico
        certificado_info = emitir_certificado_automatico(
            db=db,
            colegiado_id=pago.colegiado_id,
            payment_id=pago.id,
        )
    except Exception as e:
        logger.warning(f"Error emitiendo certificado para pago #{payment_id}: {e}")

    db.commit()

    # ── Respuesta ─────────────────────────────────────────────────────────────
    respuesta = {
        "success":           True,
        "mensaje":           "Pago aprobado",
        "aprobado_por":      aprobado_por,
        "saldo_a_favor":     round(monto_restante, 2) if monto_restante > 0 else 0,
        "cambio_habilidad":  cambio_habilidad,
        "habilidad_temporal": habilidad_temporal,
        "habilidad_vence":   habilidad_vence,
    }

    if certificado_info and certificado_info.get("emitido"):
        respuesta["certificado"] = certificado_info
        respuesta["mensaje"]     = f"Pago aprobado. Certificado {certificado_info['codigo']} emitido."

    logger.info(f"Pago #{payment_id} aprobado por {aprobado_por}: {respuesta['mensaje']}")
    return respuesta


# ═════════════════════════════════════════════════════════════════════════════
# HELPER PRIVADO: lógica de fraccionamiento
# ═════════════════════════════════════════════════════════════════════════════

def _procesar_fraccionamiento(db: Session, pago, colegiado, payment_id: int) -> None:
    """
    Procesa la cuota de un plan de fraccionamiento cuando viene identificada
    en Payment.notes como JSON {"fraccionamiento_id": N, "numero_cuota": N}.

    Si no viene meta_fracc (pago manual desde caja), usa la lógica genérica
    de politicas_financieras como fallback.

    Nunca lanza excepción — errores se loguean como warning.
    """
    try:
        meta         = json.loads(pago.notes or '{}')
        fracc_id     = meta.get('fraccionamiento_id')
        numero_cuota = meta.get('numero_cuota')   # 0 = inicial, 1..12 = mensual

        # ── Sin meta_fracc → fallback genérico (caja / conciliación) ─────────
        if fracc_id is None or numero_cuota is None:
            _habilitar_por_fracc_generico(db, pago, colegiado, payment_id)
            return

        # ── Obtener plan activo ───────────────────────────────────────────────
        fracc = db.query(Fraccionamiento).filter(
            Fraccionamiento.id     == fracc_id,
            Fraccionamiento.estado == 'activo',
        ).first()

        if not fracc:
            logger.warning(
                f"Fraccionamiento #{fracc_id} no encontrado o no activo "
                f"— pago #{payment_id}"
            )
            return

        # ── Marcar cuota individual como pagada ───────────────────────────────
        cuota = db.query(FraccionamientoCuota).filter(
            FraccionamientoCuota.fraccionamiento_id == fracc_id,
            FraccionamientoCuota.numero_cuota       == numero_cuota,
            FraccionamientoCuota.pagada             == False,
        ).first()

        if cuota:
            cuota.pagada     = True
            cuota.fecha_pago = dt_date.today()
            cuota.payment_id = payment_id

        # ── Actualizar contadores del plan ────────────────────────────────────
        fracc.cuotas_pagadas   = (fracc.cuotas_pagadas  or 0) + 1
        fracc.saldo_pendiente  = max(0.0, (fracc.saldo_pendiente or 0) - float(pago.amount or 0))
        fracc.cuotas_atrasadas = 0   # reset si estaba en mora y pagó

        hoy = dt_date.today()

        # ── Cuota inicial (numero_cuota == 0) ─────────────────────────────────
        if numero_cuota == 0:
            fracc.cuota_inicial_pagada = True
            fracc.proxima_cuota_fecha  = (
                fracc.fecha_inicio.replace(day=15) + relativedelta(months=1)
            )
            fracc.proxima_cuota_numero = 1

            fin_mes = (hoy.replace(day=1) + relativedelta(months=1)) - timedelta(days=1)
            _set_habil(colegiado, fin_mes)
            logger.info(
                f"Colegiado {fracc.colegiado_id} → HÁBIL hasta {fin_mes} "
                f"(cuota inicial fracc #{fracc_id}, pago #{payment_id})"
            )

        # ── Cuota mensual (numero_cuota >= 1) ─────────────────────────────────
        else:
            if cuota and cuota.habilidad_hasta:
                nueva_habilidad = cuota.habilidad_hasta
            else:
                # Fallback: último día del mes de vencimiento
                venc            = cuota.fecha_vencimiento if cuota else hoy
                nueva_habilidad = (venc.replace(day=1) + relativedelta(months=1)) - timedelta(days=1)

            _set_habil(colegiado, nueva_habilidad)
            logger.info(
                f"Colegiado {fracc.colegiado_id} → HÁBIL hasta {nueva_habilidad} "
                f"(cuota {numero_cuota}/{fracc.num_cuotas} fracc #{fracc_id}, pago #{payment_id})"
            )

            # Avanzar proxima_cuota
            fracc.proxima_cuota_numero = numero_cuota + 1
            if fracc.proxima_cuota_numero <= fracc.num_cuotas:
                fracc.proxima_cuota_fecha = (
                    (fracc.proxima_cuota_fecha + relativedelta(months=1))
                    if fracc.proxima_cuota_fecha
                    else hoy.replace(day=15) + relativedelta(months=1)
                )
            else:
                fracc.proxima_cuota_fecha = None   # sin más cuotas pendientes

        # ── ¿Plan completado? ─────────────────────────────────────────────────
        cuotas_mensuales_pagadas = db.query(FraccionamientoCuota).filter(
            FraccionamientoCuota.fraccionamiento_id == fracc_id,
            FraccionamientoCuota.numero_cuota       >= 1,
            FraccionamientoCuota.pagada             == True,
        ).count()

        if cuotas_mensuales_pagadas >= fracc.num_cuotas:
            fracc.estado          = 'completado'
            fracc.saldo_pendiente = 0.0

            # Todas las deudas fraccionadas → paid
            db.query(Debt).filter(
                Debt.fraccionamiento_id == fracc_id,
                Debt.status             != 'paid',
            ).update(
                {'status': 'paid', 'balance': 0.0, 'estado_gestion': 'vigente'},
                synchronize_session=False,
            )

            # Habilidad permanente: hasta 31 Dic del año en curso como mínimo
            _set_habil(colegiado, dt_date(hoy.year, 12, 31), permanente=True)
            logger.info(
                f"Fraccionamiento #{fracc_id} COMPLETADO — "
                f"colegiado {fracc.colegiado_id} → HÁBIL permanente (pago #{payment_id})"
            )

    except Exception as exc:
        logger.warning(f"_procesar_fraccionamiento: error en pago #{payment_id}: {exc}")


def _habilitar_por_fracc_generico(db: Session, pago, colegiado, payment_id: int) -> None:
    """
    Fallback para pagos sin meta_fracc (caja manual, conciliación bancaria).
    Usa politicas_financieras para calcular la próxima cuota del plan activo.
    """
    try:
        from app.services.politicas_financieras import (
            habilitar_por_fraccionamiento,
            proxima_cuota_fraccionamiento,
        )
        proxima = proxima_cuota_fraccionamiento(db, pago.colegiado_id)
        if proxima and colegiado:
            habilitar_por_fraccionamiento(db, pago.colegiado_id, proxima)
            logger.info(
                f"Colegiado {pago.colegiado_id} → HÁBIL temporal hasta {proxima} "
                f"(fallback genérico, pago #{payment_id})"
            )
    except Exception as exc:
        logger.warning(f"_habilitar_por_fracc_generico: error en pago #{payment_id}: {exc}")


def _set_habil(colegiado, fecha_hasta: dt_date, permanente: bool = False) -> None:
    """Actualiza condición y fecha de habilidad del colegiado."""
    if not colegiado:
        return
    colegiado.condicion              = 'habil'
    colegiado.habilidad_vence        = fecha_hasta
    colegiado.tiene_fraccionamiento  = not permanente
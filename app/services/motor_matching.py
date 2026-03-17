"""
app/services/motor_matching.py — ColegiosPro
Motor de matching: reporte del colegiado vs NotificacionBancaria en BD.

Se llama desde:
  1. POST /api/portal/reportar-pago      → matching_al_reportar()
  2. imap_listener → guardar_notificacion → intentar_matching_automatico()

Niveles:
  3 → nro_operacion exacto          → conciliado automáticamente
  2 → monto + mismo día + banco     → conciliado con aviso a caja
  1 → monto + misma semana          → pendiente_revision
  0 → sin match                     → pendiente_revision
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, Tuple

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def matching_al_reportar(
    nro_operacion:   Optional[str],
    monto:           float,
    fecha_pago:      Optional[datetime],
    metodo:          str,
    organization_id: int,
    db:              Session,
) -> Tuple[Optional[object], int]:
    """
    Busca en NotificacionBancaria el match más probable para un reporte de pago.
    Retorna (notificacion, nivel) donde nivel 0-3.
    """
    from app.models import NotificacionBancaria

    nro_op = nro_operacion.strip().upper() if nro_operacion else None

    # Candidatos: mismo org, pendiente, mismo monto (±0.01 por redondeo)
    candidatos = db.query(NotificacionBancaria).filter(
        NotificacionBancaria.organization_id == organization_id,
        NotificacionBancaria.estado          == 'pendiente',
        NotificacionBancaria.monto.between(monto - 0.01, monto + 0.01),
    ).order_by(NotificacionBancaria.created_at.desc()).all()

    if not candidatos:
        logger.info(f'[Matching] Sin candidatos para monto={monto}')
        return None, 0

    # ── Nivel 3: codigo_operacion exacto ──────────────────────────────────────
    if nro_op:
        for c in candidatos:
            if c.codigo_operacion and c.codigo_operacion.upper() == nro_op:
                logger.info(f'[Matching] ✅ Nivel 3 — cod_op exacto: {nro_op}')
                return c, 3

    # ── Nivel 2: monto + mismo día + banco compatible ─────────────────────────
    if fecha_pago:
        dia_pago       = fecha_pago.date()
        banco_esperado = _metodo_a_banco(metodo)

        mismo_dia = [
            c for c in candidatos
            if c.fecha_operacion and c.fecha_operacion.date() == dia_pago
        ]

        if banco_esperado:
            mismo_dia_banco = [c for c in mismo_dia if c.banco == banco_esperado]
            if len(mismo_dia_banco) == 1:
                logger.info('[Matching] ✅ Nivel 2 — monto+día+banco')
                return mismo_dia_banco[0], 2

        if len(mismo_dia) == 1:
            logger.info('[Matching] ✅ Nivel 2 — monto+día (único)')
            return mismo_dia[0], 2

    # ── Nivel 1: monto + misma semana ─────────────────────────────────────────
    if fecha_pago:
        semana_atras = fecha_pago - timedelta(days=7)
        misma_semana = [
            c for c in candidatos
            if c.fecha_operacion and c.fecha_operacion >= semana_atras
        ]
        if len(misma_semana) == 1:
            logger.info('[Matching] ⚠️ Nivel 1 — monto+semana (único)')
            return misma_semana[0], 1

    logger.info(f'[Matching] ❌ Nivel 0 — {len(candidatos)} candidatos, sin match confiable')
    return None, 0


def aplicar_match(
    notificacion,
    reporte_pago_id: int,
    nivel:           int,
    conciliado_por:  str,
    db:              Session,
) -> str:
    """
    Vincula la notificacion con el reporte de pago.
    Retorna el nuevo estado del reporte.
    """
    from app.models import NotificacionBancaria

    ahora = datetime.utcnow()

    if nivel >= 2:
        notificacion.estado         = 'conciliado'
        notificacion.payment_id     = reporte_pago_id
        notificacion.conciliado_por = conciliado_por
        notificacion.conciliado_at  = ahora
        db.commit()

        if nivel == 3:
            logger.info(f'[Matching] Aplicado nivel 3 → verificado_auto')
            return 'verificado_auto'
        else:
            logger.info(f'[Matching] Aplicado nivel 2 → verificado_probable')
            return 'verificado_probable'
    else:
        logger.info('[Matching] Sin match aplicable → pendiente_revision')
        return 'pendiente_revision'


def intentar_matching_automatico(notificacion, organization_id: int, db: Session):
    """
    Se llama desde imap_listener cuando llega email nuevo.
    Busca si hay ReportePago pendientes que coincidan con esta notificación.
    """
    try:
        from app.models import ReportePago   # ajustar si el modelo tiene otro nombre
    except ImportError:
        logger.debug('[Matching AUTO] Modelo ReportePago no encontrado aún')
        return

    reportes = db.query(ReportePago).filter(
        ReportePago.organization_id == organization_id,
        ReportePago.estado.in_(['pendiente', 'pendiente_revision']),
        ReportePago.monto.between(
            float(notificacion.monto) - 0.01,
            float(notificacion.monto) + 0.01
        ),
    ).all()

    for reporte in reportes:
        _, nivel = matching_al_reportar(
            nro_operacion   = reporte.nro_operacion,
            monto           = float(reporte.monto),
            fecha_pago      = reporte.fecha_pago,
            metodo          = getattr(reporte, 'metodo', ''),
            organization_id = organization_id,
            db              = db,
        )
        if nivel >= 2:
            nuevo_estado = aplicar_match(
                notificacion    = notificacion,
                reporte_pago_id = reporte.id,
                nivel           = nivel,
                conciliado_por  = 'auto',
                db              = db,
            )
            reporte.estado = nuevo_estado
            db.commit()
            logger.info(
                f'[Matching AUTO] ReportePago {reporte.id} → {nuevo_estado} '
                f'(nivel {nivel})'
            )
            break


def _metodo_a_banco(metodo: str) -> Optional[str]:
    m = (metodo or '').lower()
    if 'bbva'      in m: return 'bbva'
    if 'bcp'       in m: return 'bcp'
    if 'interbank' in m: return 'interbank'
    if 'scotiabank'in m: return 'scotiabank'
    if 'yape'      in m: return 'yape'
    if 'plin'      in m: return 'plin'
    return None
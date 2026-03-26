"""
app/services/fomo_engine.py
Motor FOMO — mensajes automáticos cada hora + activación manual
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)

# ── Plantillas de mensajes FOMO ───────────────────────────────
PLANTILLAS = {
    "transparencia": [
        "💰 Este mes el CCPL recaudó S/ {monto} en cuotas y pagos",
        "📊 {habiles} colegiados están habilitados este mes",
        "✅ {pagos_hoy} pagos fueron procesados hoy",
    ],
    "tendencias": [
        "🔥 El comunicado más visto: \"{titulo}\" — {vistas} lecturas",
        "👍 \"{titulo}\" tiene {likes} reacciones esta semana",
        "📢 {total} comunicados publicados este mes",
    ],
    "eventos": [
        "📅 Quedan {dias} días para: {evento} — {confirmados} ya confirmaron",
        "⏰ {evento} es {cuando} — ¿ya confirmaste tu asistencia?",
        "🎯 {confirmados} colegiados confirmaron para {evento}",
    ],
    "comunidad": [
        "🎉 {nuevos} nuevos colegiados se incorporaron este mes",
        "👥 {activos} colegiados activos en el portal hoy",
        "💪 {pagaron} colegiados regularizaron su situación esta semana",
    ],
}

# Cooldown: no mostrar FOMO más de 1 vez cada 3 min por usuario
COOLDOWN_MINUTOS = 3
_ultimo_fomo: dict = {}  # org_id -> datetime


def puede_enviar_fomo(org_id: int) -> bool:
    ultimo = _ultimo_fomo.get(org_id)
    if not ultimo:
        return True
    diff = (datetime.now(timezone.utc) - ultimo).total_seconds() / 60
    return diff >= COOLDOWN_MINUTOS


def registrar_envio(org_id: int):
    _ultimo_fomo[org_id] = datetime.now(timezone.utc)


# ── Generadores de datos reales ───────────────────────────────
async def generar_fomo_automatico(db: Session, org_id: int) -> Optional[dict]:
    """Genera el mensaje FOMO más relevante para esta hora."""
    import random

    now = datetime.now(timezone.utc)
    hora = now.hour

    # Mañana (8-12): transparencia financiera
    # Tarde (13-17): comunidad y tendencias
    # Noche (18-21): eventos próximos
    if 8 <= hora < 12:
        return await _fomo_transparencia(db, org_id)
    elif 13 <= hora < 17:
        tipo = random.choice(['comunidad', 'tendencias'])
        if tipo == 'comunidad':
            return await _fomo_comunidad(db, org_id)
        return await _fomo_tendencias(db, org_id)
    elif 18 <= hora < 22:
        ev = await _fomo_eventos(db, org_id)
        return ev or await _fomo_comunidad(db, org_id)
    return await _fomo_comunidad(db, org_id)


async def _fomo_transparencia(db: Session, org_id: int) -> Optional[dict]:
    import random
    try:
        # Recaudación del mes
        mes_inicio = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0)
        row = db.execute(text("""
            SELECT
                COALESCE(SUM(p.amount),0) as monto,
                COUNT(p.id) as pagos_hoy,
                (SELECT COUNT(*) FROM colegiados WHERE organization_id=:org
                 AND condicion='habil') as habiles
            FROM payments p
            JOIN members m ON m.id=p.member_id
            WHERE m.organization_id=:org
              AND p.status='approved'
              AND p.created_at >= :mes
        """), {"org": org_id, "mes": mes_inicio}).fetchone()

        if not row: return None
        monto    = f"{float(row.monto):,.0f}"
        habiles  = row.habiles or 0
        pag_hoy  = row.pagos_hoy or 0

        tpl = random.choice(PLANTILLAS["transparencia"])
        msg = tpl.format(monto=monto, habiles=habiles, pagos_hoy=pag_hoy)
        return {"mensaje": msg, "tipo": "transparencia", "icono": "💰"}
    except Exception as e:
        logger.warning(f"[FOMO] transparencia error: {e}")
        return None


async def _fomo_comunidad(db: Session, org_id: int) -> Optional[dict]:
    import random
    try:
        mes_inicio = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0)
        semana = datetime.now(timezone.utc) - timedelta(days=7)

        row = db.execute(text("""
            SELECT
                (SELECT COUNT(*) FROM colegiados
                 WHERE organization_id=:org
                   AND created_at >= :mes) as nuevos,
                (SELECT COUNT(DISTINCT p.colegiado_id) FROM payments p
                 JOIN colegiados c ON c.id=p.colegiado_id
                 WHERE c.organization_id=:org
                   AND p.status='approved'
                   AND p.created_at >= :semana) as pagaron
        """), {"org": org_id, "mes": mes_inicio, "semana": semana}).fetchone()

        if not row: return None
        nuevos  = row.nuevos  or 0
        pagaron = row.pagaron or 0

        if nuevos == 0 and pagaron == 0: return None

        tpl = random.choice(PLANTILLAS["comunidad"])
        msg = tpl.format(nuevos=nuevos, activos=nuevos+pagaron, pagaron=pagaron)
        return {"mensaje": msg, "tipo": "comunidad", "icono": "👥"}
    except Exception as e:
        logger.warning(f"[FOMO] comunidad error: {e}")
        return None


async def _fomo_tendencias(db: Session, org_id: int) -> Optional[dict]:
    import random
    try:
        semana = datetime.now(timezone.utc) - timedelta(days=7)
        row = db.execute(text("""
            SELECT b.title,
                   COUNT(be.id) as vistas,
                   COUNT(CASE WHEN be.status='liked' THEN 1 END) as likes
            FROM bulletins b
            LEFT JOIN bulletin_events be ON be.bulletin_id=b.id
            WHERE b.organization_id=:org
              AND b.created_at >= :semana
            GROUP BY b.id, b.title
            ORDER BY vistas DESC
            LIMIT 1
        """), {"org": org_id, "semana": semana}).fetchone()

        total = db.execute(text("""
            SELECT COUNT(*) as total FROM bulletins
            WHERE organization_id=:org
              AND DATE_TRUNC('month',created_at)=DATE_TRUNC('month',NOW())
        """), {"org": org_id}).scalar() or 0

        if not row or row.vistas == 0:
            if total == 0: return None
            return {"mensaje": f"📢 {total} comunicados publicados este mes",
                    "tipo": "tendencias", "icono": "📊"}

        tpl = random.choice(PLANTILLAS["tendencias"])
        titulo = (row.title or '')[:35] + ('…' if len(row.title or '')>35 else '')
        msg = tpl.format(titulo=titulo, vistas=row.vistas, likes=row.likes or 0, total=total)
        return {"mensaje": msg, "tipo": "tendencias", "icono": "🔥"}
    except Exception as e:
        logger.warning(f"[FOMO] tendencias error: {e}")
        return None


async def _fomo_eventos(db: Session, org_id: int) -> Optional[dict]:
    import random
    try:
        row = db.execute(text("""
            SELECT b.title,
                   b.fecha_evento,
                   COUNT(be.id) as confirmados
            FROM bulletins b
            LEFT JOIN bulletin_events be
                ON be.bulletin_id=b.id AND be.status='confirmed'
            WHERE b.organization_id=:org
              AND b.tipo='evento'
              AND b.fecha_evento > NOW()
              AND b.fecha_evento < NOW() + INTERVAL '30 days'
            GROUP BY b.id, b.title, b.fecha_evento
            ORDER BY b.fecha_evento ASC
            LIMIT 1
        """), {"org": org_id}).fetchone()

        if not row or not row.fecha_evento: return None

        dias = (row.fecha_evento - datetime.now(timezone.utc)).days
        titulo = (row.title or '')[:40]
        confirmados = row.confirmados or 0

        if dias == 0:   cuando = "HOY"
        elif dias == 1: cuando = "mañana"
        else:           cuando = f"en {dias} días"

        tpl = random.choice(PLANTILLAS["eventos"])
        msg = tpl.format(
            dias=dias, evento=titulo,
            confirmados=confirmados, cuando=cuando
        )
        return {"mensaje": msg, "tipo": "eventos", "icono": "📅"}
    except Exception as e:
        logger.warning(f"[FOMO] eventos error: {e}")
        return None


# ── Mensajes manuales predefinidos ────────────────────────────
FOMO_MANUALES = {
    "transparencia": {
        "label": "💰 Transparencia financiera",
        "desc":  "Recaudación del mes y pagos procesados",
    },
    "tendencias": {
        "label": "🔥 Comunicado más visto",
        "desc":  "El contenido con más lecturas esta semana",
    },
    "eventos": {
        "label": "📅 Próximo evento",
        "desc":  "Recordatorio del evento más cercano",
    },
    "comunidad": {
        "label": "👥 Actividad de la comunidad",
        "desc":  "Nuevos colegiados y regularizaciones recientes",
    },
}
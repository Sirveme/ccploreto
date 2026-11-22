"""
app/services/aportes_marca_service.py
La marca de aportes a la Junta (colegiados.aporta_jdccpp) SIGUE a la condición.

Problema que resuelve: la marca solo se actualizaba cuando la condición se cambiaba
desde la pantalla del padrón de Aportes. Si un colegiado volvía a hábil por un pago
o por el motor de habilidad, seguía marcado "no aporta — Inhábil" y no se contaba
en el aporte mensual a la Junta (150 casos al 21-nov-2026).

Regla (la misma de la pantalla de Aportes, aportes_junta.padron_set_condicion):
    hábil      → aporta = SÍ,  sin motivo
    inhábil    → aporta = NO,  motivo 'Inhábil'
    vitalicio  → aporta = NO,  motivo 'Vitalicio'
    fallecido / retirado / suspendido / otras → aporta = NO, motivo = la condición
Excepción: un motivo puesto A MANO (p. ej. 'Past Decano') NUNCA se toca. Solo se
gestionan las marcas vacías o con uno de los motivos automáticos.

Cómo se engancha (un solo lugar):
  · Cambios por el ORM (pagos en Caja y Secretaría, motor de habilidad, aprobación
    de pagos, conciliación, cambio manual de condición): un oyente de SQLAlchemy
    detecta que `Colegiado.condicion` cambió y ajusta la marca en la MISMA
    transacción. Se activa al importar este módulo (lo hace app/main.py).
  · Cambios por SQL directo (confirmación de pagos OpenPay): llaman a
    `sincronizar_marca_aportes` explícitamente.

Las columnas aporta_jdccpp* no están en el modelo ORM: se escriben por SQL.
Nunca lanza: un fallo aquí no debe impedir un cobro.
"""
import logging

from sqlalchemy import event, text
from sqlalchemy.orm import Session, attributes

logger = logging.getLogger(__name__)

# Motivos que el sistema pone solo (con y sin tilde: la carga del 1-jul-2026 usó 'Inhabil').
MOTIVOS_AUTOMATICOS = ("Inhabil", "Inhábil", "Vitalicio", "Fallecido", "Retirado", "Suspendido",
                       "Candidato a retiro", "Candidato A Retiro")

_SQL_DERIVADO_APORTA = "(c.condicion = 'habil')"
_SQL_DERIVADO_MOTIVO = """CASE c.condicion
        WHEN 'habil'      THEN NULL
        WHEN 'inhabil'    THEN 'Inhábil'
        WHEN 'vitalicio'  THEN 'Vitalicio'
        WHEN 'fallecido'  THEN 'Fallecido'
        WHEN 'retirado'   THEN 'Retirado'
        WHEN 'suspendido' THEN 'Suspendido'
        WHEN 'candidato_retiro' THEN 'Candidato a retiro'
        ELSE initcap(replace(coalesce(c.condicion, 'inhabil'), '_', ' ')) END"""

# Sentencia única (la reutiliza el SQL de puesta al día: sql/zClaude-marca-aportes-resync.sql).
SQL_SINCRONIZAR = f"""
    UPDATE colegiados c
    SET aporta_jdccpp = {_SQL_DERIVADO_APORTA},
        aporta_jdccpp_motivo = {_SQL_DERIVADO_MOTIVO},
        aporta_jdccpp_actualizado_por = NULL,
        aporta_jdccpp_actualizado_at = NOW()
    WHERE c.id = ANY(:ids)
      AND (c.aporta_jdccpp_motivo IS NULL OR c.aporta_jdccpp_motivo = '' OR c.aporta_jdccpp_motivo = ANY(:auto))
      AND (coalesce(c.aporta_jdccpp, TRUE) IS DISTINCT FROM {_SQL_DERIVADO_APORTA}
           OR c.aporta_jdccpp_motivo IS DISTINCT FROM {_SQL_DERIVADO_MOTIVO})
"""


def sincronizar_marca_aportes(db, colegiado_ids) -> int:
    """Ajusta la marca de aportes de esos colegiados a su condición actual. Sin commit.
    Devuelve cuántas marcas cambió. Nunca lanza."""
    ids = [int(i) for i in (colegiado_ids or []) if i]
    if not ids:
        return 0
    try:
        # Punto de guardado a nivel de CONEXIÓN (no de sesión): se puede usar también
        # mientras la sesión está guardando, y si el SQL falla no arrastra la transacción.
        conn = db.connection()
        with conn.begin_nested():
            r = conn.execute(text(SQL_SINCRONIZAR), {"ids": ids, "auto": list(MOTIVOS_AUTOMATICOS)})
            return int(r.rowcount or 0)
    except Exception as e:
        logger.warning("marca de aportes no sincronizada para %s: %s", ids[:5], str(e)[:160])
        return 0


@event.listens_for(Session, "after_flush")
def _al_guardar(session, flush_context):
    """Si en este guardado cambió la condición de algún colegiado, su marca la sigue."""
    try:
        from app.models import Colegiado
        ids = []
        for obj in list(session.dirty) + list(session.new):
            if isinstance(obj, Colegiado) and obj.id is not None:
                if obj in session.new or attributes.get_history(obj, "condicion").has_changes():
                    ids.append(obj.id)
        if ids:
            sincronizar_marca_aportes(session, ids)
    except Exception as e:      # jamás romper un guardado por esto
        logger.warning("oyente de marca de aportes: %s", str(e)[:160])

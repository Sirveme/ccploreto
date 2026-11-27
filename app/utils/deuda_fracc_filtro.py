"""
app/utils/deuda_fracc_filtro.py
Filtro COMPARTIDO de presentación de deuda (fix vista doble conteo de fracc).

Regla (solo VISTA — no cambia datos ni status):
  Una deuda ORIGINAL absorbida por un fraccionamiento VIGENTE ('activo') no se
  muestra ni se suma; la representan las cuotas del plan. PERO las cuotas del
  propio plan (debt_type='fraccionamiento') SÍ son exigibles y NO se ocultan.
  Si el fracc NO está 'activo' (perdido/completado), la deuda original vuelve a
  verse.

Valores reales BD (confirmados Fase 0):
  - fraccionamientos.estado vigente = 'activo' (otros: 'perdido','completado').
  - cuotas del plan → debt_type = 'fraccionamiento'.

CRÍTICO: sin la cláusula `debt_type != 'fraccionamiento'` se ocultarían las 1229
cuotas de plan exigibles (~S/128k). Por eso vive centralizada aquí y se aplica
igual en detalle y en totales.
"""

from sqlalchemy import and_, not_, exists, func

from app.models_debt_management import Debt, Fraccionamiento


def excluir_absorbidas_por_fracc_activo():
    """Cláusula booleana para usar en `.filter(...)` de queries sobre `debts`.

    Descarta las deudas originales absorbidas por un fracc activo, preservando
    las cuotas del propio plan. Sirve tanto en queries de detalle como en
    agregados (func.sum / func.count)."""
    return not_(and_(
        Debt.fraccionamiento_id.isnot(None),
        Debt.debt_type != 'fraccionamiento',      # NO ocultar cuotas del plan
        exists().where(and_(
            Fraccionamiento.id == Debt.fraccionamiento_id,
            Fraccionamiento.estado == 'activo',
        )),
    ))


# ── Tanda 19: deudas ORIGINALES marcadas «fraccionada» ────────────────────────────────────────────
# Al crear un plan, sus deudas originales pasan a estado_gestion='fraccionada': las representa el plan.
# El filtro de arriba solo las oculta mientras su plan está 'activo' y enlazado por fraccionamiento_id;
# las de planes completados, perdidos o refinanciados, y las 'fraccionada' sin plan enlazado, se seguían
# sumando. Ésta las excluye SIEMPRE.
# CRÍTICO: las cuotas del propio plan (debt_type='fraccionamiento') también llevan 'fraccionada' y SON
# deuda exigible: no se excluyen. (Por eso no sirve filtrar solo estado_gestion IN ('vigente','en_cobranza'):
# borraría la deuda de los planes de los totales que suman Debt.balance.)
# Null-safe: sin coalesce, un debt_type NULL haría que la fila desaparezca del total.
def excluir_originales_fraccionadas():
    """Cláusula para `.filter(...)` sobre `debts`: descarta las deudas originales 'fraccionada' y
    conserva las cuotas del plan. Se usa junto con `excluir_absorbidas_por_fracc_activo()`."""
    return not_(and_(
        func.coalesce(Debt.estado_gestion, '') == 'fraccionada',
        func.coalesce(Debt.debt_type, '') != 'fraccionamiento',
    ))


def sql_excluir_originales_fraccionadas(alias="d"):
    """La misma regla, para SQL escrito a mano (`... WHERE ... AND <esto>`)."""
    return ("NOT (coalesce({a}.estado_gestion,'') = 'fraccionada' "
            "AND coalesce({a}.debt_type,'') <> 'fraccionamiento')").format(a=alias)

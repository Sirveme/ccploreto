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

from sqlalchemy import and_, not_, exists

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

"""
Condiciones vigentes del fraccionamiento, en lenguaje sencillo (tanda 14).
app/services/condiciones_fracc_service.py

Una sola fuente para el bloque «Condiciones vigentes» de Caja, Secretaría (crear y
refinanciar) y, más adelante, del portal del colegiado («¿Puedo fraccionar mi deuda?»).

Los valores salen SIEMPRE de `_resolver_parametros_fracc` (monto mínimo, inicial %,
cuota mínima, máximo de cuotas) y de `dia_vencimiento_plan` (día de vencimiento de los
planes nuevos): los mismos que usa la creación del plan. Si se cambia un Parámetro, el
bloque cambia solo. Aquí no hay cifras fijas.

«Cuotas en soles enteros» no es un parámetro: es la regla de cálculo vigente
(app/utils/cuotas_enteras.py) y se enuncia como tal.

Solo lectura. Nunca lanza: `_resolver_parametros_fracc` ya cae a sus valores de respaldo.
"""
from sqlalchemy.orm import Session


def _soles(v: float) -> str:
    """S/ 250 · S/ 250.50 (sin decimales cuando el monto es entero)."""
    v = round(float(v or 0), 2)
    return "S/ {:,.0f}".format(v) if abs(v - round(v)) < 0.005 else "S/ {:,.2f}".format(v)


def _pct(v: float) -> str:
    v = round(float(v or 0), 2)
    return ("%d" % round(v)) if abs(v - round(v)) < 0.005 else ("%s" % v)


def condiciones_vigentes(db: Session, organization_id: int = 1) -> dict:
    from app.services.fraccionamiento_service import _resolver_parametros_fracc, dia_vencimiento_plan

    deuda_min, cuota_min, max_cuotas, inicial_frac = _resolver_parametros_fracc(db, organization_id)
    dia = dia_vencimiento_plan(db, organization_id)
    inicial_pct = round(float(inicial_frac) * 100, 2)

    items = [
        {"clave": "monto_minimo", "texto": "Deuda mínima %s" % _soles(deuda_min)},
        {"clave": "inicial_pct", "texto": "Inicial sugerida %s %%" % _pct(inicial_pct)},
        {"clave": "cuota_minima", "texto": "Cuota mínima %s" % _soles(cuota_min)},
        {"clave": "max_cuotas", "texto": "Hasta %d cuotas" % int(max_cuotas)},
        {"clave": "dia_vencimiento", "texto": "Vence el día %d de cada mes" % int(dia)},
        {"clave": "soles_enteros", "texto": "Cuotas en soles enteros"},
    ]
    return {
        "monto_minimo": float(deuda_min),
        "inicial_pct": inicial_pct,
        "cuota_minima": float(cuota_min),
        "max_cuotas": int(max_cuotas),
        "dia_vencimiento": int(dia),
        "items": items,
        "texto": " · ".join(i["texto"] for i in items),
        "monto_minimo_texto": _soles(deuda_min),
    }


def linea_minimo(condiciones: dict, deuda: float) -> str:
    """«Fraccionamiento disponible desde S/ 250; deuda actual S/ X.» (para cuando no llega)."""
    return "Fraccionamiento disponible desde %s; deuda actual %s." % (
        condiciones["monto_minimo_texto"], _soles(deuda))

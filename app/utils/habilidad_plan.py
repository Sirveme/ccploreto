"""
Tope de la habilidad al pagar cuotas de un plan (tanda 16, regla aprobada por Duilio el 25-nov-2026).
app/utils/habilidad_plan.py

Regla:
  El pago de una cuota mantiene hábil al colegiado hasta el fin del mes de esa cuota.
  Si un cobro ADELANTA cuotas o COMPLETA el plan, la fecha «hábil hasta» no pasa del fin
  del último periodo que cubren las deudas incluidas en el plan.

Para que pagar todo nunca dé menos que pagar la cuota del mes, el tope es el MAYOR de:
  a) el fin del último periodo cubierto por las deudas del plan (y, si el plan nace de un
     refinanciamiento, por las del plan anterior, siguiendo refinanciado_por_id);
  b) el fin del mes de la cuota del plan que vence a continuación (la «cuota del mes»).
El tope es por FECHA, no por orden de pago: adelantar cuotas en cobros separados tampoco
lo supera. Pagar solo la cuota del mes queda igual que antes.

Lo de siempre se mantiene: la fecha nunca se acorta si ya era mayor por otro motivo (eso lo
aplica cada llamador, con `no_acortar`).

Solo lectura. Si no hay periodos legibles, no hay tope (comportamiento anterior).
"""
import re
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text

PERU_TZ = timezone(timedelta(hours=-5))


def _fin_de_mes(anio: int, mes: int) -> date:
    return (date(anio + (mes == 12), (mes % 12) + 1, 1) - timedelta(days=1))


def fin_periodo(periodo) -> date:
    """Último día que cubre un periodo de deuda. Formatos del sistema:
    'YYYY' → 31/12 · 'YYYY-MM' → fin de ese mes · 'YYYY-MM:MM' y 'YYYY-MM,MM:MM' → fin del último mes ·
    'YYYY-MM-DD' (multas por fecha) → fin de ese mes. Devuelve None si no se puede leer."""
    p = (periodo or "").strip()
    if not re.match(r"^\d{4}", p):
        return None
    anio = int(p[:4])
    resto = p[4:]
    if not resto:
        return date(anio, 12, 31)
    if not resto.startswith("-"):
        return None
    resto = resto[1:]
    if re.match(r"^\d{2}-\d{2}$", resto):          # fecha completa
        mes = int(resto[:2])
    else:
        meses = re.findall(r"\d{2}", resto)
        if not meses:
            return None
        mes = int(meses[-1])
    if not 1 <= mes <= 12:
        return None
    return _fin_de_mes(anio, mes)


def fin_cobertura_plan(db, fraccionamiento_id: int) -> date:
    """Fin del último periodo cubierto por las deudas del plan (y de los planes que refinanció)."""
    fin, visto, actual = None, set(), fraccionamiento_id
    while actual and actual not in visto and len(visto) < 10:
        visto.add(actual)
        for (per,) in db.execute(text("""
                SELECT periodo FROM debts
                WHERE fraccionamiento_id = :f AND coalesce(debt_type, '') <> 'fraccionamiento'"""), {"f": actual}):
            f = fin_periodo(per)
            if f and (fin is None or f > fin):
                fin = f
        actual = db.execute(text("SELECT refinanciado_por_id FROM fraccionamientos WHERE id = :f"),
                            {"f": actual}).scalar()
    return fin


def tope_habilidad_plan(db, fraccionamiento_id: int, hoy: date = None) -> date:
    """Fecha máxima de «hábil hasta» que puede dar un cobro de cuotas de este plan (None = sin tope)."""
    hoy = hoy or datetime.now(PERU_TZ).date()
    cobertura = fin_cobertura_plan(db, fraccionamiento_id)
    if cobertura is None:
        return None
    r = db.execute(text("""
        SELECT min(fecha_vencimiento) FILTER (WHERE fecha_vencimiento >= :hoy) proxima, max(fecha_vencimiento) ultima
        FROM fraccionamiento_cuotas WHERE fraccionamiento_id = :f AND numero_cuota >= 1"""),
        {"f": fraccionamiento_id, "hoy": hoy}).fetchone()
    ref = (r.proxima or r.ultima) if r else None
    cuota_del_mes = _fin_de_mes(ref.year, ref.month) if ref else None
    return max(cobertura, cuota_del_mes) if cuota_del_mes else cobertura


def limitar(db, fraccionamiento_id: int, candidata: date, hoy: date = None) -> date:
    """`candidata` (fin de mes de la cuota más lejana pagada) recortada al tope del plan."""
    if candidata is None or not fraccionamiento_id:
        return candidata
    tope = tope_habilidad_plan(db, fraccionamiento_id, hoy)
    return min(candidata, tope) if tope else candidata


def no_acortar(actual, nueva: date) -> date:
    """Nunca acorta: si la fecha vigente ya era mayor por otro motivo, se conserva."""
    from app.utils.habilidad_fecha import fecha_habilidad
    a = fecha_habilidad(actual) if actual is not None else None
    return a if (a is not None and nueva is not None and a > nueva) else nueva

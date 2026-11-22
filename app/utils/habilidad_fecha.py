"""
app/utils/habilidad_fecha.py — Fecha "hábil hasta" (colegiados.habilidad_vence).

FORMA ÚNICA DE GUARDARLA (desde tanda 8): "fecha sin hora" = las 00:00 UTC del día.
  - La conexión de producción está en UTC: así `valor.date()` da el día correcto en
    TODO lector, incluidos los que no se pueden tocar (facturacion.py arma la boleta con
    `.date()`; el motor evaluar_habilidad.py ya guarda una `date`, que queda a las 00:00 UTC).
  - "Fin del día en Lima" (23:59 Lima = 04:59 UTC del día SIGUIENTE) haría que esos
    lectores mostraran el día siguiente; por eso no se usa.

LECTURA para mostrar: `fecha_habilidad(valor)` tolera los tres estilos que hay en la base
  - 00:00 UTC (fecha sin hora)              → ese día
  - 00:00 Lima (05:00 UTC)                  → ese día (en Lima)
  - con hora del día (escritos antiguos)    → el día en Lima
"""
from datetime import date, datetime, time, timedelta, timezone

UTC = timezone.utc
LIMA = timezone(timedelta(hours=-5))


def vence_hasta(d):
    """date | datetime → valor a guardar en habilidad_vence (00:00 UTC de ese día).
    Un datetime se interpreta en hora de Lima antes de tomar su día."""
    if d is None:
        return None
    if isinstance(d, datetime):
        d = fecha_habilidad(d)
    return datetime.combine(d, time.min, tzinfo=UTC)


def fecha_habilidad(v):
    """Valor de habilidad_vence → date (el día que se debe mostrar), o None."""
    if v is None:
        return None
    if isinstance(v, datetime):
        if v.tzinfo is None:
            return v.date()
        u = v.astimezone(UTC)
        if u.time() == time.min:
            return u.date()
        return v.astimezone(LIMA).date()
    if isinstance(v, date):
        return v
    return None


def fmt_habilidad(v, formato="%d/%m/%Y"):
    f = fecha_habilidad(v)
    return f.strftime(formato) if f else None


def fin_de_mes(d):
    """Último día del mes de `d` (date o datetime; un datetime se toma en hora de Lima)."""
    if isinstance(d, datetime):
        d = d.astimezone(LIMA).date() if d.tzinfo else d.date()
    sig = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return sig - timedelta(days=1)


def hoy_lima():
    return datetime.now(LIMA).date()


# Expresión SQL equivalente a fecha_habilidad() (para reportes y pruebas).
SQL_FECHA_HABILIDAD = ("(CASE WHEN (habilidad_vence AT TIME ZONE 'UTC')::time = '00:00' "
                       "THEN (habilidad_vence AT TIME ZONE 'UTC')::date "
                       "ELSE (habilidad_vence AT TIME ZONE 'America/Lima')::date END)")

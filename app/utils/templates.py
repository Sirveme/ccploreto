"""
app/utils/templates.py
======================
Instancia ÚNICA de Jinja2Templates compartida por todos los routers.
Agregar filtros y globals aquí — se propagan automáticamente.

Uso en cualquier router:
    from app.utils.templates import templates
"""

from fastapi.templating import Jinja2Templates
from datetime import timezone, timedelta


templates = Jinja2Templates(directory="app/templates")


# ── Filtros globales ──────────────────────────────────────────

def _fmt_lima(dt):
    """Convierte datetime UTC → hora Lima (UTC-5) y formatea."""
    if dt is None:
        return "nunca"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    lima = dt + timedelta(hours=-5)
    return lima.strftime('%d/%m/%Y %H:%M')


def _fmt_lima_short(dt):
    """Versión corta: dd/mm/yy HH:MM"""
    if dt is None:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    lima = dt + timedelta(hours=-5)
    return lima.strftime('%d/%m/%y %H:%M')


def _fmt_sol(value):
    """Formatea número como moneda S/ con 2 decimales."""
    try:
        return f"S/ {float(value):,.2f}"
    except (TypeError, ValueError):
        return "S/ 0.00"


def _fmt_fecha(dt):
    """Solo fecha en formato peruano dd/mm/yyyy (sin hora)."""
    if dt is None:
        return "—"
    if hasattr(dt, 'tzinfo'):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt + timedelta(hours=-5)
    return dt.strftime('%d/%m/%Y')


templates.env.filters["lima"]       = _fmt_lima
templates.env.filters["lima_short"] = _fmt_lima_short
templates.env.filters["sol"]        = _fmt_sol
templates.env.filters["fecha"]      = _fmt_fecha
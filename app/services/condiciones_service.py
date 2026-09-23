"""
app/services/condiciones_service.py
Resolver ÚNICO de las reglas de Condiciones y Exoneraciones (módulo Presets).

Un solo punto de lectura para los umbrales de inhabilidad/retiro/pérdida y las
reglas de vitalicio/exoneración. Los lectores (evaluar_habilidad, generador_deudas,
fraccionamiento_perdida_service, deuda_cuotas_service) se conectarán en el PASO 3;
este módulo NO los toca todavía.

Cascada de fallback (nunca rompe):
    1) preset ACTIVO en presets_condiciones/preset_valores (organizacion_id)
    2) org.config.finanzas.habilidad  (overrides legacy de los 5 umbrales)
    3) DEFAULTS del código  (red de seguridad — clona lo vigente al 2026-09)

Si las tablas de presets no existen aún (pre-deploy) o vienen vacías, o si el
lookup falla por cualquier motivo, se cae a la capa siguiente sin excepción.

Cache por organización, invalidable con invalidar_cache() al activar/editar preset.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# ── DEFAULTS del código (capa 3 · red de seguridad = "Valores Vigentes") ──────
# 13 claves canónicas. Debe ser IDÉNTICO al preset seed "Valores Vigentes".
DEFAULTS_CONDICIONES: Dict[str, Any] = {
    # Inhabilidad
    "inhab_cuotas_ordinarias":          3,      # Art. 18
    "inhab_extraordinaria":             1,      # Art. 18-g
    "inhab_multa":                      1,      # Art. 18
    "inhab_fracc_cuotas":               3,      # Acuerdo fracc.
    # Retiro
    "retiro_auto_meses":                24,     # Art. 114 Reglamento
    # Fraccionamiento — pérdida
    "perdida_fracc_consecutivas":       2,      # Acuerdo interno
    "perdida_automatica":               False,
    # Vitalicio
    "vitalicio_declaracion":            "manual",   # Art. 8
    "vitalicio_anios":                  30,         # Art. 8
    "vitalicio_exige_cotizacion":       False,      # Art. 8 (Vigentes=NO; Estatuto=SÍ)
    "vitalicio_exento_cuotas":          True,       # Art. 8
    # Exoneraciones — DOS claves distintas (no se fusionan)
    "condiciones_exentas_generacion":   {"vitalicio", "fallecido", "retirado", "baja", "suspendido"},
    "condiciones_sin_deuda_computable": {"vitalicio", "fallecido", "retirado"},
}

# Mapeo de las 5 claves legacy de org.config.finanzas.habilidad → claves canónicas.
# (evaluar_habilidad.DEFAULTS_HABILIDAD usa estos nombres.)
_MAP_ORG_CONFIG = {
    "cuotas_para_inhabilitar":          "inhab_cuotas_ordinarias",
    "extraordinarias_para_inhabilitar": "inhab_extraordinaria",
    "multas_para_inhabilitar":          "inhab_multa",
    "fracc_cuotas_para_inhabilitar":    "inhab_fracc_cuotas",
    "cuotas_para_retiro":               "retiro_auto_meses",
}

# Claves que son SET (se guardan como lista JSON en preset_valores.valor_json).
_CLAVES_SET = ("condiciones_exentas_generacion", "condiciones_sin_deuda_computable")

# Cache simple por organizacion_id.
_CACHE: Dict[int, Dict[str, Any]] = {}


def invalidar_cache(org_id: int | None = None) -> None:
    """Invalida el cache. Sin argumento limpia todo. Llamar al activar/editar preset."""
    if org_id is None:
        _CACHE.clear()
    else:
        _CACHE.pop(org_id, None)


def _snapshot_defaults() -> Dict[str, Any]:
    """Copia profunda-suficiente de los DEFAULTS (los sets se copian, no se comparten)."""
    out = dict(DEFAULTS_CONDICIONES)
    for k in _CLAVES_SET:
        out[k] = set(DEFAULTS_CONDICIONES[k])
    return out


def _valor_nativo(tipo: str, num, boo, txt, js):
    """preset_valores → valor Python nativo según tipo ('int'|'bool'|'enum'|'set')."""
    if tipo == "int":
        return int(round(float(num))) if num is not None else None
    if tipo == "bool":
        return bool(boo) if boo is not None else None
    if tipo == "enum":
        return txt
    if tipo == "set":
        return set(js) if js is not None else None
    # tipo desconocido → intenta el primer no-nulo
    for v in (num, boo, txt, js):
        if v is not None:
            return v
    return None


def _aplicar_org_config(db: Session, org_id: int, cond: Dict[str, Any]) -> None:
    """Capa 2: overrides legacy de org.config.finanzas.habilidad (solo los 5 umbrales)."""
    try:
        row = db.execute(
            text("SELECT config FROM organizations WHERE id = :o"), {"o": org_id}
        ).first()
        if not row or not row[0]:
            return
        config = row[0]
        if isinstance(config, str):
            import json
            config = json.loads(config)
        habilidad = ((config or {}).get("finanzas", {}) or {}).get("habilidad", {}) or {}
        for legacy_key, canon_key in _MAP_ORG_CONFIG.items():
            if legacy_key in habilidad and habilidad[legacy_key] is not None:
                try:
                    cond[canon_key] = int(habilidad[legacy_key])
                except (TypeError, ValueError):
                    pass
    except Exception as e:  # nunca rompe — cae a lo que ya haya
        logger.debug("condiciones_service: org.config no aplicable (%s)", e)


def _aplicar_preset_activo(db: Session, org_id: int, cond: Dict[str, Any]) -> str | None:
    """Capa 1: preset ACTIVO. Devuelve el nombre del preset aplicado, o None si no hay."""
    try:
        preset = db.execute(text(
            "SELECT id, nombre FROM presets_condiciones "
            "WHERE organizacion_id = :o AND activo = TRUE LIMIT 1"
        ), {"o": org_id}).first()
        if not preset:
            return None
        filas = db.execute(text(
            "SELECT clave, tipo, valor_numerico, valor_booleano, valor_texto, valor_json "
            "FROM preset_valores WHERE preset_id = :p"
        ), {"p": preset[0]}).fetchall()
        for f in filas:
            if f.clave not in DEFAULTS_CONDICIONES:
                continue  # ignora claves ajenas al contrato
            val = _valor_nativo(f.tipo, f.valor_numerico, f.valor_booleano,
                                f.valor_texto, f.valor_json)
            if val is not None:
                cond[f.clave] = val
        return preset[1]
    except Exception as e:  # tablas ausentes / error → red de seguridad
        logger.debug("condiciones_service: preset no aplicable (%s)", e)
        return None


def get_condiciones(db: Session, org_id: int = 1, *, use_cache: bool = True) -> Dict[str, Any]:
    """Snapshot resuelto de las 13 reglas de condiciones para la organización.

    Cascada: DEFAULTS → org.config → preset activo (cada capa sobre-escribe la anterior).
    Devuelve SIEMPRE las 13 claves canónicas. Nunca lanza excepción.
    """
    if use_cache and org_id in _CACHE:
        cached = _CACHE[org_id]
        out = dict(cached)
        for k in _CLAVES_SET:
            out[k] = set(cached[k])
        return out

    cond = _snapshot_defaults()          # capa 3
    _aplicar_org_config(db, org_id, cond)  # capa 2
    _aplicar_preset_activo(db, org_id, cond)  # capa 1

    if use_cache:
        cacheable = dict(cond)
        for k in _CLAVES_SET:
            cacheable[k] = set(cond[k])
        _CACHE[org_id] = cacheable
    return cond

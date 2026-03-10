"""
app/services/evaluar_habilidad.py
===================================
Motor de evaluación de habilidad colegiada.

Reglas configurables por organización (config JSONB → finanzas → habilidad):

  X  cuotas_para_inhabilitar    int     default 3
     Cuotas ordinarias vencidas >= X  →  INHÁBIL

  Y  monto_otras_para_inhabilitar  float | None   default None
     Deuda por conceptos distintos a cuotas ordinarias >= Y  →  INHÁBIL
     None = regla desactivada

  Fraccionamiento activo:
     Siempre HÁBIL temporal (ya manejado por aprobar_pago / politicas_financieras).
     Este servicio NO lo revierte.

Uso:
    from app.services.evaluar_habilidad import evaluar_habilidad, debe_inhabilitar

    resultado = evaluar_habilidad(deuda_info, org_config, colegiado)
    if resultado.debe_inhabilitar:
        colegiado.condicion = "inhabil"
        colegiado.motivo_inhabilidad = resultado.motivo
"""

from dataclasses import dataclass
from typing import Optional
import logging

logger = logging.getLogger(__name__)


# ── Defaults SAAS (usados si la org no configura nada) ────────
DEFAULTS_HABILIDAD = {
    "cuotas_para_inhabilitar":        3,     # X: cuotas ordinarias vencidas
    "monto_otras_para_inhabilitar": None,    # Y: None = desactivado
}


@dataclass
class ResultadoHabilidad:
    debe_inhabilitar:  bool
    motivo:            Optional[str]
    # Detalles para UI
    cuotas_vencidas:   int
    deuda_otras:       float
    tiene_fracc:       bool
    # Config efectiva aplicada
    umbral_cuotas:     int
    umbral_monto_otras: Optional[float]


def get_config_habilidad(org: dict) -> dict:
    """
    Lee la configuración de habilidad de la organización.
    La org puede provenir de request.state.org (dict) o del modelo Organization.
    """
    finanzas = {}
    if isinstance(org, dict):
        config = org.get("config", {}) or {}
        if isinstance(config, str):
            import json
            try:
                config = json.loads(config)
            except Exception:
                config = {}
        finanzas = config.get("finanzas", {}) or {}
    
    habilidad = finanzas.get("habilidad", {}) or {}

    x = habilidad.get("cuotas_para_inhabilitar",
                       DEFAULTS_HABILIDAD["cuotas_para_inhabilitar"])
    y = habilidad.get("monto_otras_para_inhabilitar",
                       DEFAULTS_HABILIDAD["monto_otras_para_inhabilitar"])

    # Sanitizar
    try:
        x = int(x)
        if x < 1:
            x = 1
    except (TypeError, ValueError):
        x = DEFAULTS_HABILIDAD["cuotas_para_inhabilitar"]

    if y is not None:
        try:
            y = float(y)
            if y <= 0:
                y = None
        except (TypeError, ValueError):
            y = None

    return {"cuotas_para_inhabilitar": x, "monto_otras_para_inhabilitar": y}


def evaluar_habilidad(
    deuda_info: dict,
    org: dict,
    colegiado=None,         # objeto SQLAlchemy Colegiado (opcional, para leer fraccionamiento)
) -> ResultadoHabilidad:
    """
    Evalúa si un colegiado debe ser INHÁBIL según las reglas de la organización.

    Args:
        deuda_info: resultado de calcular_deuda_total()
        org:        dict de organización (request.state.org)
        colegiado:  objeto Colegiado (para leer tiene_fraccionamiento)

    Returns:
        ResultadoHabilidad
    """
    cfg            = get_config_habilidad(org)
    umbral_cuotas  = cfg["cuotas_para_inhabilitar"]
    umbral_otras   = cfg["monto_otras_para_inhabilitar"]

    cuotas_vencidas = int(deuda_info.get("cantidad_cuotas", 0))
    deuda_otras     = float(deuda_info.get("deuda_otras", 0) or 0)

    # Fraccionamiento activo → protegido, no inhabilitar por monto
    tiene_fracc = False
    if colegiado is not None:
        tiene_fracc = bool(getattr(colegiado, "tiene_fraccionamiento", False))
    elif deuda_info.get("fraccionamiento"):
        fracc = deuda_info["fraccionamiento"]
        tiene_fracc = fracc.get("estado") in ("activo", "vigente") if fracc else False

    motivos = []

    # ── Regla 1: cuotas ordinarias vencidas ───────────────────
    if cuotas_vencidas >= umbral_cuotas:
        motivos.append(
            f"{cuotas_vencidas} cuota{'s' if cuotas_vencidas > 1 else ''} "
            f"ordinaria{'s' if cuotas_vencidas > 1 else ''} vencida{'s' if cuotas_vencidas > 1 else ''} "
            f"(límite: {umbral_cuotas})"
        )

    # ── Regla 2: deuda por otros conceptos ────────────────────
    # No aplica si tiene fraccionamiento activo
    if umbral_otras is not None and not tiene_fracc:
        if deuda_otras >= umbral_otras:
            motivos.append(
                f"Deuda por otros conceptos S/ {deuda_otras:.2f} "
                f"(límite: S/ {umbral_otras:.2f})"
            )

    debe_inhabilitar = len(motivos) > 0
    motivo = " | ".join(motivos) if motivos else None

    if debe_inhabilitar:
        logger.debug(
            f"evaluar_habilidad: INHÁBIL — {motivo} "
            f"(fracc={tiene_fracc})"
        )

    return ResultadoHabilidad(
        debe_inhabilitar   = debe_inhabilitar,
        motivo             = motivo,
        cuotas_vencidas    = cuotas_vencidas,
        deuda_otras        = deuda_otras,
        tiene_fracc        = tiene_fracc,
        umbral_cuotas      = umbral_cuotas,
        umbral_monto_otras = umbral_otras,
    )


def debe_mostrar_portal_inactivo(
    deuda_info: dict,
    org: dict,
    colegiado=None,
) -> bool:
    """
    Versión booleana simple para el partial pagos.html:
    ¿Debe redirigirse al colegiado al portal_inactivo en vez de mostrar deudas aquí?
    """
    r = evaluar_habilidad(deuda_info, org, colegiado)
    return r.debe_inhabilitar


def sincronizar_condicion(db, colegiado, org: dict) -> bool:
    """
    Evalúa la deuda actual y actualiza colegiado.condicion en BD si corresponde.
    Llama a calcular_deuda_total internamente.
    Retorna True si se cambió la condición.

    Uso típico: tarea Celery periódica o post-pago.
    NO llama a db.commit() — el llamador debe hacerlo.
    """
    from app.routers.pagos_publicos import calcular_deuda_total

    # Si es VITALICIO, nunca inhabilitar
    if getattr(colegiado, "condicion", "") == "vitalicio":
        return False

    deuda_info = calcular_deuda_total(db, colegiado.id)
    resultado  = evaluar_habilidad(deuda_info, org, colegiado)

    condicion_actual = getattr(colegiado, "condicion", "inhabil")

    if resultado.debe_inhabilitar and condicion_actual == "habil":
        # Solo inhabilitar si NO tiene fraccionamiento activo
        if not resultado.tiene_fracc:
            colegiado.condicion         = "inhabil"
            colegiado.motivo_inhabilidad = resultado.motivo
            logger.info(
                f"sincronizar_condicion: #{colegiado.id} → INHÁBIL | {resultado.motivo}"
            )
            return True

    elif not resultado.debe_inhabilitar and condicion_actual == "inhabil":
        # Rehabilitar si ya no hay motivos de inhabilidad
        # (solo si no tiene fraccionamiento — en ese caso lo maneja aprobar_pago)
        if not resultado.tiene_fracc:
            from datetime import date
            colegiado.condicion         = "habil"
            colegiado.motivo_inhabilidad = None
            colegiado.habilidad_vence   = date(date.today().year, 12, 31)
            logger.info(
                f"sincronizar_condicion: #{colegiado.id} → HÁBIL (deuda normalizada)"
            )
            return True

    return False
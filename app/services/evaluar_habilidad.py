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


Motor de evaluación de habilidad colegiada.

Reglas según Estatuto CCPL 2018 (Art. 18°) y Reglamento 2019 (Art. 114°),
más Acuerdo interno de fraccionamiento:

  1. >= X cuotas ordinarias impagas          → INHÁBIL   (X configurable, default 3)
  2. >= 1 cuota extraordinaria impaga        → INHÁBIL   (configurable, default 1)
  3. >= 1 multa impaga (cualquier tipo)      → INHÁBIL   (configurable, default 1)
  4. >= 3 cuotas de fraccionamiento atrasadas → INHÁBIL  (configurable, default 3)
  5. >= 24 cuotas ordinarias impagas         → RETIRADO  (Art. 114° Reglamento)

  Fraccionamiento activo y al día: PROTEGIDO (no se inhabilita por cuotas ordinarias).
  Fraccionamiento activo pero con >= umbral_fracc_atrasadas: INHÁBIL (regla 4).

Para otras organizaciones SaaS, las reglas 2, 3 y 4 son configurables
por organización en organizations.config JSONB → finanzas → habilidad.        
"""

from dataclasses import dataclass, field
from typing import Optional
import logging

logger = logging.getLogger(__name__)


# ── Defaults SaaS (usados si la org no configura nada) ────────────────────────
DEFAULTS_HABILIDAD = {
    "cuotas_para_inhabilitar":            3,    # X: cuotas ordinarias vencidas
    "extraordinarias_para_inhabilitar":   1,    # 1 cuota extraordinaria = inhábil
    "multas_para_inhabilitar":            1,    # 1 multa = inhábil
    "fracc_cuotas_para_inhabilitar":      3,    # 3 cuotas fracc atrasadas = inhábil
    "cuotas_para_retiro":                24,    # Art. 114° Reglamento
}


dataclass
@dataclass
class ResultadoHabilidad:
    debe_inhabilitar:   bool
    debe_retirar:       bool                    # Art. 114°: >= 24 cuotas impagas
    motivo:             Optional[str]
    # Detalles para UI
    cuotas_vencidas:    int
    tiene_multa:        bool
    tiene_extraordinaria: bool
    tiene_fracc:        bool
    fracc_atrasadas:    int
    # Config efectiva aplicada
    umbral_cuotas:      int
    umbral_extraordinarias: int
    umbral_multas:      int
    umbral_fracc_atrasadas: int
    umbral_retiro:      int


def get_config_habilidad(org: dict) -> dict:
    """
    Lee la configuración de habilidad de la organización.
    org puede ser dict (request.state.org) o modelo Organization.
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

    def _int(key):
        val = habilidad.get(key, DEFAULTS_HABILIDAD[key])
        try:
            return max(1, int(val))
        except (TypeError, ValueError):
            return DEFAULTS_HABILIDAD[key]

    return {
        "cuotas_para_inhabilitar":          _int("cuotas_para_inhabilitar"),
        "extraordinarias_para_inhabilitar": _int("extraordinarias_para_inhabilitar"),
        "multas_para_inhabilitar":          _int("multas_para_inhabilitar"),
        "fracc_cuotas_para_inhabilitar":    _int("fracc_cuotas_para_inhabilitar"),
        "cuotas_para_retiro":               _int("cuotas_para_retiro"),
    }


def evaluar_habilidad(
    deuda_info: dict,
    org: dict,
    colegiado=None,
) -> ResultadoHabilidad:
    """
    Evalúa si un colegiado debe ser INHÁBIL o RETIRADO.

    Args:
        deuda_info: resultado de calcular_deuda_total()
        org:        dict de organización (request.state.org)
        colegiado:  objeto SQLAlchemy Colegiado (opcional)
    Returns:
        ResultadoHabilidad
    """
    cfg = get_config_habilidad(org)

    umbral_cuotas      = cfg["cuotas_para_inhabilitar"]
    umbral_extras      = cfg["extraordinarias_para_inhabilitar"]
    umbral_multas      = cfg["multas_para_inhabilitar"]
    umbral_fracc_atr   = cfg["fracc_cuotas_para_inhabilitar"]
    umbral_retiro      = cfg["cuotas_para_retiro"]

    # ── Leer datos de deuda_info ───────────────────────────────────────────
    cuotas_vencidas = int(
        deuda_info.get("cantidad_cuotas") or
        deuda_info.get("resumen", {}).get("cuotas_pendientes", 0)
    )

    # Obligaciones por tipo — leer de la lista 'obligaciones'
    obligaciones = deuda_info.get("obligaciones", [])

    tiene_multa = any(
        float(o.get("balance", 0)) > 0 and o.get("categoria") == "multa"
        for o in obligaciones
    )
    tiene_extraordinaria = any(
        float(o.get("balance", 0)) > 0 and o.get("categoria") == "cuota_extraordinaria"
        for o in obligaciones
    )

    # ── Fraccionamiento ────────────────────────────────────────────────────
    fracc_info      = deuda_info.get("fraccionamiento") or {}
    tiene_fracc     = fracc_info.get("estado") in ("activo", "vigente") if fracc_info else False
    fracc_atrasadas = int(fracc_info.get("cuotas_atrasadas", 0)) if fracc_info else 0

    # Si el colegiado tiene atributo directo, tiene prioridad
    if colegiado is not None:
        _tf = getattr(colegiado, "tiene_fraccionamiento", None)
        if _tf is not None:
            tiene_fracc = bool(_tf)

    # ── Evaluación reglas ─────────────────────────────────────────────────
    motivos = []

    # Regla 1: multas (prioridad alta — cualquier multa inhabilita)
    if tiene_multa:
        n_multas = sum(
            1 for o in obligaciones
            if float(o.get("balance", 0)) > 0 and o.get("categoria") == "multa"
        )
        if n_multas >= umbral_multas:
            motivos.append(
                f"{n_multas} multa{'s' if n_multas > 1 else ''} impaga{'s' if n_multas > 1 else ''}"
            )

    # Regla 2: cuotas extraordinarias
    if tiene_extraordinaria:
        n_extras = sum(
            1 for o in obligaciones
            if float(o.get("balance", 0)) > 0 and o.get("categoria") == "cuota_extraordinaria"
        )
        if n_extras >= umbral_extras:
            motivos.append(
                f"{n_extras} cuota{'s' if n_extras > 1 else ''} extraordinaria{'s' if n_extras > 1 else ''} impaga{'s' if n_extras > 1 else ''}"
            )

    # Regla 3: fraccionamiento con cuotas atrasadas
    if tiene_fracc and fracc_atrasadas >= umbral_fracc_atr:
        motivos.append(
            f"Fraccionamiento con {fracc_atrasadas} cuota{'s' if fracc_atrasadas > 1 else ''} atrasada{'s' if fracc_atrasadas > 1 else ''} "
            f"(límite: {umbral_fracc_atr})"
        )

    # Regla 4: cuotas ordinarias
    # Solo aplica si NO tiene fraccionamiento activo y al día
    fracc_al_dia = tiene_fracc and fracc_atrasadas < umbral_fracc_atr
    if not fracc_al_dia and cuotas_vencidas >= umbral_cuotas:
        motivos.append(
            f"{cuotas_vencidas} cuota{'s' if cuotas_vencidas > 1 else ''} "
            f"ordinaria{'s' if cuotas_vencidas > 1 else ''} vencida{'s' if cuotas_vencidas > 1 else ''} "
            f"(límite: {umbral_cuotas})"
        )

    # Regla 5: retiro automático (Art. 114° Reglamento)
    debe_retirar = cuotas_vencidas >= umbral_retiro

    debe_inhabilitar = len(motivos) > 0

    motivo = " | ".join(motivos) if motivos else None

    if debe_inhabilitar:
        logger.debug(
            f"evaluar_habilidad: INHÁBIL — {motivo} "
            f"(fracc={tiene_fracc}, fracc_atrasadas={fracc_atrasadas})"
        )
    if debe_retirar:
        logger.warning(
            f"evaluar_habilidad: RETIRO — {cuotas_vencidas} cuotas vencidas "
            f"(umbral retiro: {umbral_retiro})"
        )

    return ResultadoHabilidad(
        debe_inhabilitar      = debe_inhabilitar,
        debe_retirar          = debe_retirar,
        motivo                = motivo,
        cuotas_vencidas       = cuotas_vencidas,
        tiene_multa           = tiene_multa,
        tiene_extraordinaria  = tiene_extraordinaria,
        tiene_fracc           = tiene_fracc,
        fracc_atrasadas       = fracc_atrasadas,
        umbral_cuotas         = umbral_cuotas,
        umbral_extraordinarias = umbral_extras,
        umbral_multas         = umbral_multas,
        umbral_fracc_atrasadas = umbral_fracc_atr,
        umbral_retiro         = umbral_retiro,
    )


def debe_mostrar_portal_inactivo(
    deuda_info: dict,
    org: dict,
    colegiado=None,
) -> bool:
    """
    Atajo: ¿debe redirigirse al colegiado al portal_inactivo?
    Equivale a evaluar_habilidad().debe_inhabilitar.
    """
    return evaluar_habilidad(deuda_info, org, colegiado).debe_inhabilitar


#print(EVALUAR_HABILIDAD_NUEVO)


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
"""
Clasificacion de deudas para el modal de fraccionamiento.
zClaude-77 — usado por:
  - GET /api/caja/deudas/{colegiado_id}
  - GET /api/finanzas/situacion/{colegiado_id}

Salida (campos de UI, no alteran la DB):
  mostrar          → si la fila aparece en el listado principal del modal
  preseleccionada  → si el checkbox arranca marcado
  bloqueada        → si el checkbox arranca disabled (no se puede desmarcar)
  categoria        → etiqueta para badges/agrupacion
"""
from datetime import date
import re

PATRON_MES = re.compile(r"^(\d{4})-(\d{2})$")


def clasificar_deuda_para_fraccionamiento(debt) -> dict:
    hoy = date.today()
    periodo = getattr(debt, "periodo", None) or ""
    debt_type = getattr(debt, "debt_type", None)
    m = PATRON_MES.match(periodo)

    if debt_type == "cuota_ordinaria" and m:
        anio = int(m.group(1))
        mes = int(m.group(2))

        if anio == hoy.year:
            if mes < hoy.month:
                return {
                    "mostrar": True,
                    "preseleccionada": True,
                    "bloqueada": True,
                    "categoria": "ordinaria_actual_vencida",
                }
            if mes == hoy.month:
                return {
                    "mostrar": True,
                    "preseleccionada": True,
                    "bloqueada": False,
                    "categoria": "ordinaria_actual_mes_en_curso",
                }
            return {
                "mostrar": False,
                "preseleccionada": False,
                "bloqueada": False,
                "categoria": "ordinaria_actual_futura",
            }
        if anio < hoy.year:
            return {
                "mostrar": True,
                "preseleccionada": True,
                "bloqueada": False,
                "categoria": "historica",
            }

    return {
        "mostrar": True,
        "preseleccionada": True,
        "bloqueada": False,
        "categoria": "historica",
    }

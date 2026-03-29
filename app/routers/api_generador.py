"""
Endpoints para el Generador de Deudas
Agregar en app/routers/finanzas.py (o crear app/routers/api_generador.py)

Prefix: /api/finanzas
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from datetime import date
from typing import Optional

from app.database import get_db
from app.routers.security import get_current_member

router = APIRouter(prefix="/api/finanzas", tags=["Generador Deudas"])


# ── Importar en el router de finanzas existente ──────────────
# from app.services.generador_deudas import (
#     generar_cuotas_ordinarias,
#     generar_cuotas_fraccionamiento,
#     resumen_fraccionamientos,
# )


# ── ENDPOINT: Resumen fraccionamientos (para Caja y Dashboard) ─
@router.get("/fraccionamientos/resumen")
async def resumen_fracc(
    db: Session = Depends(get_db),
    member = Depends(get_current_member),
):
    """Panel de control de fraccionamientos activos."""
    from app.services.generador_deudas import resumen_fraccionamientos
    data = resumen_fraccionamientos(db, member.organization_id)
    return JSONResponse(data)


# ── ENDPOINT: Generar deudas cuotas ordinarias ────────────────
@router.post("/generador/cuotas-ordinarias")
async def generar_ord(
    request: Request,
    db:      Session = Depends(get_db),
    member           = Depends(get_current_member),
):
    """
    Genera deudas de cuota ordinaria para el mes indicado.
    Body JSON: { "anio": 2026, "mes": 3, "motivo_no_ejecucion": null }
    """
    ROLES_PERMITIDOS = ("decano", "admin", "cajero", "tesorero", "sote", "superadmin")
    if member.role not in ROLES_PERMITIDOS:
        return JSONResponse({"error": "Sin permiso"}, status_code=403)

    from app.services.generador_deudas import generar_cuotas_ordinarias
    data = await request.json()

    motivo_no = data.get("motivo_no_ejecucion", "").strip()
    if motivo_no:
        # Registrar que se decidió NO generar, con motivo
        return JSONResponse({
            "ok":     True,
            "accion": "no_ejecutado",
            "motivo": motivo_no,
            "mensaje": f"Generación omitida: {motivo_no}",
        })

    anio = data.get("anio", date.today().year)
    mes  = data.get("mes",  date.today().month)

    resultado = generar_cuotas_ordinarias(
        db              = db,
        organization_id = member.organization_id,
        anio            = anio,
        mes             = mes,
        created_by      = member.user_id,
    )
    return JSONResponse({"ok": True, **resultado})


# ── ENDPOINT: Generar deudas cuotas fraccionamiento ───────────
@router.post("/generador/cuotas-fraccionamiento")
async def generar_fracc(
    request: Request,
    db:      Session = Depends(get_db),
    member           = Depends(get_current_member),
):
    """
    Revisa fraccionamientos activos y genera deudas por cuotas vencidas.
    Body JSON: { "motivo_no_ejecucion": null }
    """
    ROLES_PERMITIDOS = ("decano", "admin", "cajero", "tesorero", "sote", "superadmin")
    if member.role not in ROLES_PERMITIDOS:
        return JSONResponse({"error": "Sin permiso"}, status_code=403)

    from app.services.generador_deudas import generar_cuotas_fraccionamiento
    data = await request.json()

    motivo_no = data.get("motivo_no_ejecucion", "").strip()
    if motivo_no:
        return JSONResponse({
            "ok":     True,
            "accion": "no_ejecutado",
            "motivo": motivo_no,
            "mensaje": f"Generación omitida: {motivo_no}",
        })

    resultado = generar_cuotas_fraccionamiento(
        db              = db,
        organization_id = member.organization_id,
        created_by      = member.user_id,
    )
    return JSONResponse({"ok": True, **resultado})
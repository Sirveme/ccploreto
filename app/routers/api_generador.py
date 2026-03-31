"""
Endpoints para el Generador de Deudas
Agregar en app/routers/finanzas.py (o crear app/routers/api_generador.py)

Prefix: /api/finanzas
"""

from fastapi import APIRouter, Depends, Request, BackgroundTasks
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


# ── ENDPOINT: Rollback de un lote ─────────────────────────────
@router.post("/generador/rollback")
async def rollback_lote(
    request:          Request,
    background_tasks: BackgroundTasks,
    db:               Session = Depends(get_db),
    member                    = Depends(get_current_member),
):
    """
    Revierte un lote de deudas generadas automáticamente.
    Solo borra deudas con status='pending' — no toca las que ya tienen pagos.
    Body JSON: { "lote_id": "GEN-ORD-202601-123456", "motivo": "..." }
    """
    ROLES_PERMITIDOS = ("decano", "admin", "cajero", "tesorero", "sote", "superadmin")
    if member.role not in ROLES_PERMITIDOS:
        return JSONResponse({"error": "Sin permiso"}, status_code=403)

    from app.models_debt_management import Debt
    data    = await request.json()
    lote_id = data.get("lote_id", "").strip()
    motivo  = data.get("motivo", "").strip()

    if not lote_id:
        return JSONResponse({"error": "lote_id requerido"}, status_code=400)
    if not lote_id.startswith("GEN-"):
        return JSONResponse(
            {"error": "Solo se puede revertir lotes generados automáticamente"},
            status_code=400,
        )

    # Contar antes de borrar
    total = db.query(Debt).filter(
        Debt.lote_migracion == lote_id,
    ).count()

    con_pagos = db.query(Debt).filter(
        Debt.lote_migracion == lote_id,
        Debt.status.in_(["partial", "paid"]),
    ).count()

    pendientes = db.query(Debt).filter(
        Debt.lote_migracion == lote_id,
        Debt.status         == "pending",
    ).count()

    if total == 0:
        return JSONResponse({"error": f"Lote '{lote_id}' no encontrado"}, status_code=404)

    # Borrar solo las pendientes
    db.query(Debt).filter(
        Debt.lote_migracion == lote_id,
        Debt.status         == "pending",
    ).delete(synchronize_session=False)

    db.commit()

    import logging
    logging.getLogger(__name__).info(
        f"[Rollback] lote={lote_id} borradas={pendientes} "
        f"preservadas={con_pagos} motivo={motivo} user={member.id}"
    )

    # Re-sincronizar condiciones en background
    background_tasks.add_task(_sincronizar_condiciones, member.organization_id)

    return JSONResponse({
        "ok":             True,
        "lote_id":        lote_id,
        "borradas":       pendientes,
        "preservadas":    con_pagos,
        "sincronizacion": "en_progreso",
        "mensaje":        f"Se revirtieron {pendientes} deuda(s). "
                          f"{con_pagos} preservada(s) por tener pagos asociados.",
    })


# =======================================================
# mostrar el resumen de condiciones en el panel Generador
# =======================================================

# ═══════════════════════════════════════════════════════════════
# PATCH 3: En app/routers/api_generador.py
# Endpoint resumen-padron — mostrar candidatos_retiro como alerta
# REEMPLAZAR el endpoint completo:
# ═══════════════════════════════════════════════════════════════
 
@router.get("/generador/resumen-padron")
async def resumen_padron(
    db:     Session = Depends(get_db),
    member          = Depends(get_current_member),
):
    """Resumen de colegiados por condición para el panel Generador."""
    from app.models import Colegiado
    from sqlalchemy import func
 
    rows = db.query(
        func.lower(Colegiado.condicion).label('condicion'),
        func.count(Colegiado.id).label('total')
    ).filter(
        Colegiado.organization_id == member.organization_id
    ).group_by(func.lower(Colegiado.condicion)).all()
 
    padron = [{"condicion": r.condicion, "total": r.total} for r in rows]
 
    # Contar candidatos a retiro específicamente para la alerta
    candidatos_retiro = next(
        (r["total"] for r in padron if r["condicion"] == "candidato_retiro"), 0
    )
 
    return JSONResponse({
        "padron":            padron,
        "candidatos_retiro": candidatos_retiro,
        "alerta_retiro":     candidatos_retiro > 0,
    })



# =========================================================================
# GENERADOR DE CUOTAS ORDINARIAS: EVALUA Y ACTUALIZA CONDICION DE HABILIDAD
# =========================================================================

# ── ENDPOINT: Generar deudas cuotas ordinarias ────────────────
@router.post("/generador/cuotas-ordinarias")
async def generar_ord(
    request:          Request,
    background_tasks: BackgroundTasks,
    db:               Session = Depends(get_db),
    member                    = Depends(get_current_member),
):
    ROLES_PERMITIDOS = ("decano", "admin", "cajero", "tesorero", "sote", "superadmin")
    if member.role not in ROLES_PERMITIDOS:
        return JSONResponse({"error": "Sin permiso"}, status_code=403)

    from app.services.generador_deudas import generar_cuotas_ordinarias
    data = await request.json()

    motivo_no = data.get("motivo_no_ejecucion", "").strip()
    if motivo_no:
        return JSONResponse({
            "ok": True, "accion": "no_ejecutado",
            "motivo": motivo_no,
            "mensaje": f"Generación omitida: {motivo_no}",
        })

    anio = data.get("anio", date.today().year)
    mes  = data.get("mes",  date.today().month)

    resultado = generar_cuotas_ordinarias(
        db=db, organization_id=member.organization_id,
        anio=anio, mes=mes, created_by=member.user_id,
    )

    # Sincronizar condiciones en background
    background_tasks.add_task(_sincronizar_condiciones, member.organization_id)

    return JSONResponse({"ok": True, **resultado, "sincronizacion": "en_progreso"})


def _sincronizar_condiciones(organization_id: int):
    """
    Tarea background: evalúa y actualiza condición de todos los colegiados.
    - Detecta candidatos a retiro (>= 24 cuotas ordinarias impagas)
    - Sincroniza hábil/inhábil para el resto
    """
    print(f"[Sincronizar] INICIANDO org={organization_id}")
    from app.database import SessionLocal
    from app.services.evaluar_habilidad import sincronizar_condicion
    from app.models import Colegiado, Organization
    from app.models_debt_management import Debt
    import logging
    logger = logging.getLogger(__name__)
 
    UMBRAL_RETIRO = 24  # cuotas ordinarias impagas
 
    db = SessionLocal()
    try:
        org = db.query(Organization).filter(Organization.id == organization_id).first()
        org_dict = {"id": org.id, "config": {}} if org else {}
 
        # Excluir condiciones permanentes — candidato_retiro se re-evalúa siempre
        colegiados = db.query(Colegiado).filter(
            Colegiado.organization_id == organization_id,
            Colegiado.condicion.notin_({'fallecido', 'retirado', 'vitalicio', 'baja', 'suspendido'}),
        ).all()
 
        cambios          = 0
        candidatos       = 0
        rehabilitados    = 0
 
        for col in colegiados:
            # ── Detectar candidatos a retiro ──────────────────
            cuotas_impagas = db.query(Debt).filter(
                Debt.colegiado_id == col.id,
                Debt.debt_type    == 'cuota_ordinaria',
                Debt.status.in_(['pending', 'partial']),
            ).count()
 
            if cuotas_impagas >= UMBRAL_RETIRO:
                if col.condicion != 'candidato_retiro':
                    col.condicion          = 'candidato_retiro'
                    col.motivo_inhabilidad = f'{cuotas_impagas} cuotas ordinarias impagas — candidato a retiro'
                    cambios   += 1
                    candidatos += 1
                continue  # No evaluar más condiciones para este colegiado
 
            # ── Si era candidato y ya no llega al umbral → re-evaluar ──
            if col.condicion == 'candidato_retiro':
                col.condicion          = 'inhabil'
                col.motivo_inhabilidad = f'Reclasificado desde candidato_retiro ({cuotas_impagas} cuotas impagas)'
                cambios += 1
 
            # ── Sincronizar hábil/inhábil normal ─────────────
            if sincronizar_condicion(db, col, org_dict):
                cambios += 1
                if col.condicion == 'habil':
                    rehabilitados += 1
 
        db.commit()
        logger.info(
            f"[Sincronizar] org={organization_id} → "
            f"{cambios} cambios | {candidatos} candidatos retiro | {rehabilitados} rehabilitados"
        )
        print(
            f"[Sincronizar] COMPLETADO org={organization_id} → "
            f"{cambios} cambios | {candidatos} candidatos retiro | {rehabilitados} rehabilitados"
        )
 
    except Exception as e:
        logger.error(f"[Sincronizar] Error: {e}")
        print(f"[Sincronizar] ERROR: {e}")
        db.rollback()
    finally:
        db.close()
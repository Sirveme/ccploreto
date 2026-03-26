"""
app/services/fomo_scheduler.py
APScheduler setup para FOMO automático cada hora
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
import logging

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()


def iniciar_scheduler():
    """Llamar desde app/main.py en el startup event."""
    if not scheduler.running:
        scheduler.add_job(
            job_fomo_automatico,
            trigger=IntervalTrigger(hours=1),
            id="fomo_automatico",
            replace_existing=True,
            max_instances=1,
        )
        scheduler.start()
        logger.info("[FOMO] Scheduler iniciado — job cada 1 hora")


async def job_fomo_automatico():
    """Job ejecutado cada hora — genera y broadcast FOMO a todas las orgs."""
    from app.database import SessionLocal
    from app.routers.ws import manager
    from app.models import Organization
    from app.services.fomo_engine import (
        generar_fomo_automatico, puede_enviar_fomo, registrar_envio
    )

    db = SessionLocal()
    try:
        orgs = db.query(Organization).filter(Organization.is_active == True).all()
        for org in orgs:
            if not puede_enviar_fomo(org.id):
                continue
            fomo = await generar_fomo_automatico(db, org.id)
            if fomo:
                await manager.broadcast({
                    "type":    "FOMO",
                    "mensaje": fomo["mensaje"],
                    "icono":   fomo.get("icono", "📢"),
                    "tipo":    fomo["tipo"],
                    "org_id":  org.id,
                    "duracion": 5000,
                })
                registrar_envio(org.id)
                logger.info(f"[FOMO] org={org.id} → {fomo['mensaje'][:60]}")
    except Exception as e:
        logger.error(f"[FOMO] job error: {e}")
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════
# AGREGAR EN app/main.py:
#
# from app.services.fomo_scheduler import iniciar_scheduler
#
# @app.on_event("startup")
# async def startup_event():
#     iniciar_scheduler()
# ══════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════
# ENDPOINTS — agregar en app/routers/api_comunicados.py
# ══════════════════════════════════════════════════════════════
"""
from app.services.fomo_engine import (
    generar_fomo_automatico, FOMO_MANUALES,
    puede_enviar_fomo, registrar_envio
)

@router.get("/fomo/opciones")
async def fomo_opciones(member: Member = Depends(get_current_member)):
    ROLES = ("decano","admin","secretaria","cajero","sote","superadmin")
    if member.role not in ROLES:
        return JSONResponse({"error":"Sin permiso"}, status_code=403)
    return JSONResponse({"opciones": [
        {"id": k, **v} for k, v in FOMO_MANUALES.items()
    ]})


@router.post("/fomo/activar")
async def fomo_activar(
    request: Request,
    member: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
):
    ROLES = ("decano","admin","secretaria","cajero","sote","superadmin")
    if member.role not in ROLES:
        return JSONResponse({"error":"Sin permiso"}, status_code=403)

    from app.routers.ws import manager
    data = await request.json()
    tipo = data.get("tipo", "comunidad")

    # Generar mensaje real desde BD
    from app.services.fomo_engine import (
        _fomo_transparencia, _fomo_comunidad,
        _fomo_tendencias, _fomo_eventos
    )
    generadores = {
        "transparencia": _fomo_transparencia,
        "comunidad":     _fomo_comunidad,
        "tendencias":    _fomo_tendencias,
        "eventos":       _fomo_eventos,
    }
    gen = generadores.get(tipo, _fomo_comunidad)
    fomo = await gen(db, member.organization_id)

    if not fomo:
        return JSONResponse({"ok": False, "mensaje": "Sin datos suficientes para este tipo"})

    await manager.broadcast({
        "type":    "FOMO",
        "mensaje": fomo["mensaje"],
        "icono":   fomo.get("icono","📢"),
        "tipo":    fomo["tipo"],
        "org_id":  member.organization_id,
        "duracion": 5000,
    })
    registrar_envio(member.organization_id)

    return JSONResponse({"ok": True, "mensaje": fomo["mensaje"]})
"""
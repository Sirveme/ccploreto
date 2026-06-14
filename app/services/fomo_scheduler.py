"""
app/services/fomo_scheduler.py
APScheduler setup para FOMO automático cada hora
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
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
        # zClaude-97n: resúmenes de notificaciones — cada hora en punto.
        scheduler.add_job(
            procesar_resumenes_diarios,
            trigger=CronTrigger(minute=0),
            id="notif_resumenes",
            replace_existing=True,
            max_instances=1,
        )
        scheduler.start()
        logger.info("[FOMO] Scheduler iniciado — fomo cada 1h + resúmenes notif cada hora en punto")


# ══════════════════════════════════════════════════════════════
# zClaude-97n — JOB DE RESÚMENES DE NOTIFICACIONES
# ══════════════════════════════════════════════════════════════
def procesar_resumenes_diarios():
    """Corre cada hora en punto. Si un user tiene modo='resumen_diario' y su
    hora_resumen coincide con la hora actual (America/Lima), le envía un
    resumen agrupado y marca los eventos encolados como procesados.

    Es síncrona: el AsyncIOScheduler la ejecuta en su thread-pool executor.
    """
    from datetime import datetime, timezone, timedelta
    from sqlalchemy import text
    from app.database import SessionLocal
    from app.services.push_service import enviar_push_member

    # Hora local de Lima (Perú = UTC-5 todo el año, sin DST).
    try:
        from zoneinfo import ZoneInfo
        ahora = datetime.now(ZoneInfo("America/Lima"))
    except Exception:
        ahora = datetime.now(timezone.utc) - timedelta(hours=5)
    hora_lima = ahora.hour

    db = SessionLocal()
    try:
        pendientes = db.execute(text("""
            SELECT q.user_id, q.categoria,
                   COUNT(q.id)        AS cnt,
                   array_agg(q.id)    AS ids
            FROM notif_queue q
            JOIN notif_config nc
              ON nc.user_id = q.user_id AND nc.categoria = q.categoria
            WHERE q.procesado_at IS NULL
              AND q.modo = 'resumen_diario'
              AND nc.modo = 'resumen_diario'
              AND nc.activo = TRUE
              AND EXTRACT(HOUR FROM nc.hora_resumen) = :hora
            GROUP BY q.user_id, q.categoria
        """), {"hora": hora_lima}).fetchall()

        for row in pendientes:
            user_id, cat, cnt, ids = row[0], row[1], row[2], row[3]

            titulo = f"📊 Resumen — {cnt} novedades"
            cuerpo = f"Tienes {cnt} notificaciones de {cat}. Toca para ver detalles."

            member = db.execute(text("""
                SELECT id FROM members WHERE user_id = :uid AND is_active = TRUE LIMIT 1
            """), {"uid": user_id}).fetchone()
            if member:
                try:
                    # enviar_push_member(db, member_id, mensaje, titulo, url) — nota: 'mensaje', no 'cuerpo'.
                    enviar_push_member(db=db, member_id=member[0], mensaje=cuerpo, titulo=titulo, url="/portal")
                except Exception as e:
                    logger.warning(f"[notif] Resumen no enviado a user={user_id}: {e}")

            # Marcar procesados (siempre, haya o no device, para no reintentar infinito).
            db.execute(text("""
                UPDATE notif_queue SET procesado_at = NOW() WHERE id = ANY(:ids)
            """), {"ids": list(ids)})

        db.commit()
        if pendientes:
            logger.info(f"[notif] Resúmenes procesados: {len(pendientes)} (hora Lima={hora_lima})")
    except Exception as e:
        logger.error(f"[notif] Error en procesar_resumenes_diarios: {e}")
        db.rollback()
    finally:
        db.close()


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
        # zClaude-97n (§8): Organization NO tiene columna is_active; el filtro
        # original lanzaba AttributeError y abortaba el job. CCPL es la única org.
        orgs = db.query(Organization).all()
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
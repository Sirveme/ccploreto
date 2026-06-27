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
        # zClaude-97p: detector de avisos FOMO de asambleas — cada 30 min.
        scheduler.add_job(
            detectar_fomo_avisos_asambleas,
            trigger=IntervalTrigger(minutes=30),
            id="fomo_asambleas",
            replace_existing=True,
            max_instances=1,
        )
        # zClaude-aportes-junta: cierre por calendario (01:30) + recálculo (02:00).
        # El cierre va antes del recálculo para que un periodo recién vencido no se
        # recalcule el mismo día tras cerrarse.
        scheduler.add_job(
            cerrar_aportes_diario,
            trigger=CronTrigger(hour=1, minute=30),
            id="aportes_cierre_diario",
            replace_existing=True,
            max_instances=1,
        )
        scheduler.add_job(
            recalcular_aportes_diario,
            trigger=CronTrigger(hour=2, minute=0),
            id="aportes_recalculo_diario",
            replace_existing=True,
            max_instances=1,
        )
        scheduler.start()
        logger.info("[FOMO] Scheduler iniciado — fomo 1h + resúmenes 1h + asambleas 30min "
                    "+ aportes (cierre 01:30, recálculo 02:00)")


# ══════════════════════════════════════════════════════════════
# zClaude-aportes-junta — JOBS DE APORTES A LA JUNTA (JDCCPP)
# Síncronos: el AsyncIOScheduler los corre en su thread-pool executor.
# ══════════════════════════════════════════════════════════════
def recalcular_aportes_diario():
    """Cron diario 02:00: recalcula el periodo del mes en curso (org 1 = CCPL)."""
    from app.database import SessionLocal
    from app.services.aportes_junta_service import calcular_periodo_actual
    db = SessionLocal()
    try:
        result = calcular_periodo_actual(db, organizacion_id=1)
        if result:
            logger.info(
                f"[aportes] Periodo {result['anio']}-{result['mes']:02d}: "
                f"{result['cantidad_nuevos']} nuevos, {result['cantidad_habiles']} hábiles, "
                f"S/{result['monto_total']:.2f}, {result['pendientes_registro']} alertas"
            )
    except Exception as e:
        logger.error(f"[aportes] Error recalculando: {e}")
    finally:
        db.close()


def cerrar_aportes_diario():
    """Cron diario 01:30: cierra periodos vencidos por calendario (inmutables)."""
    from app.database import SessionLocal
    from app.services.aportes_junta_service import cerrar_periodos_vencidos
    db = SessionLocal()
    try:
        cerrar_periodos_vencidos(db)
    except Exception as e:
        logger.error(f"[aportes] Error cerrando periodos: {e}")
    finally:
        db.close()


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


# ══════════════════════════════════════════════════════════════
# zClaude-97p — DETECTOR DE AVISOS FOMO DE ASAMBLEAS (7d / 1d / 1h)
# ══════════════════════════════════════════════════════════════
def detectar_fomo_avisos_asambleas():
    """Corre cada 30 min. Para cada asamblea próxima crea fomo_avisos idempotentes
    (uq_fomo_aviso_idempotente) según la regla activa y dispara UN push por regla.

    Reglas:
      - 7 días → 1 día antes : 'asamblea_7d'  N3  campana.mp3
      - 1 día  → 1 hora antes: 'asamblea_1d'  N4  campana.mp3
      - 1 hora → inicio       : 'asamblea_1h'  N4  campana_fuerte.mp3

    Síncrona: el AsyncIOScheduler la ejecuta en su thread-pool executor.
    """
    from datetime import datetime, timezone, timedelta
    from sqlalchemy import text
    from app.database import SessionLocal
    from app.services.notif_service import disparar_evento

    ahora = datetime.now(timezone.utc)
    lima = timedelta(hours=-5)  # Perú UTC-5 sin DST
    creados_total = 0
    db = SessionLocal()
    try:
        asambleas = db.execute(text("""
            SELECT id, organization_id, title, lugar_evento, fecha_evento
            FROM bulletins
            WHERE tipo = 'asamblea'
              AND fecha_evento > :ahora
              AND fecha_evento < :limite
            ORDER BY fecha_evento
        """), {"ahora": ahora, "limite": ahora + timedelta(days=8)}).fetchall()

        for a in asambleas:
            if not a.fecha_evento:
                continue
            restante = a.fecha_evento - ahora

            # Determinar regla activa (una sola)
            if timedelta(days=1) < restante <= timedelta(days=7):
                regla, nivel, sonido = 'asamblea_7d', 'N3', 'campana.mp3'
            elif timedelta(hours=1) < restante <= timedelta(days=1):
                regla, nivel, sonido = 'asamblea_1d', 'N4', 'campana.mp3'
            elif timedelta(0) < restante <= timedelta(hours=1):
                regla, nivel, sonido = 'asamblea_1h', 'N4', 'campana_fuerte.mp3'
            else:
                continue

            cuando = a.fecha_evento + lima  # hora Lima para mostrar
            lugar = a.lugar_evento or 'CCPL'
            if regla == 'asamblea_7d':
                mensaje = f"En 1 semana: {lugar} — {cuando.strftime('%d/%m %H:%M')}"
            elif regla == 'asamblea_1d':
                mensaje = f"MAÑANA: {lugar} — {cuando.strftime('%H:%M')}"
            else:
                mensaje = f"En 1 hora: {lugar} — {cuando.strftime('%H:%M')}"
            titulo = f"📅 {a.title}"

            # ¿Primera vez que se activa esta regla? (decide si se dispara el push)
            ya = db.execute(text("""
                SELECT 1 FROM fomo_avisos
                WHERE evento_origen_tipo = 'bulletins' AND evento_origen_id = :bid AND tipo = :regla
                LIMIT 1
            """), {"bid": a.id, "regla": regla}).fetchone()

            # Crear avisos idempotentes para todos los colegiados hábiles/vitalicios
            res = db.execute(text("""
                INSERT INTO fomo_avisos (
                    organization_id, user_id, tipo, evento_origen_tipo, evento_origen_id,
                    titulo, mensaje, nivel, sonido, url_accion,
                    fecha_disparar, fecha_caducidad, created_at
                )
                SELECT :org, m.user_id, :regla, 'bulletins', :bid,
                       :titulo, :mensaje, :nivel, :sonido, :url,
                       :ahora, :caducidad, :ahora
                FROM members m
                JOIN colegiados c ON c.member_id = m.id
                WHERE m.organization_id = :org
                  AND m.is_active = TRUE
                  AND m.user_id IS NOT NULL
                  AND c.condicion IN ('habil', 'vitalicio')
                ON CONFLICT ON CONSTRAINT uq_fomo_aviso_idempotente DO NOTHING
                RETURNING id
            """), {
                "org": a.organization_id, "regla": regla, "bid": a.id,
                "titulo": titulo, "mensaje": mensaje, "nivel": nivel, "sonido": sonido,
                "url": f"/asambleas/{a.id}",
                "ahora": ahora, "caducidad": a.fecha_evento + timedelta(hours=2),
            })
            creados = len(res.fetchall())
            creados_total += creados
            db.commit()

            # Push real (una sola vez por regla/asamblea)
            if not ya:
                try:
                    disparar_evento(
                        db,
                        organization_id=a.organization_id,
                        evento_tipo='asambleas',
                        audiencia='todos_habilitados',
                        payload={"titulo": a.title, "mensaje": mensaje, "url": f"/asambleas/{a.id}"},
                        nivel=nivel,
                        sonido=sonido,
                    )
                    db.commit()
                except Exception as e:
                    db.rollback()
                    logger.warning(f"[FOMO-asamblea] push no enviado bid={a.id} {regla}: {e}")

        if creados_total:
            logger.info(f"[FOMO-asamblea] avisos creados: {creados_total} ({len(asambleas)} asambleas)")
    except Exception as e:
        logger.error(f"[FOMO-asamblea] error: {e}")
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
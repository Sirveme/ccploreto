"""
Celery Task: Sincronización de emails bancarios en background
app/tasks/sync_emails.py

Se ejecuta cada 30-60 segundos:
1. Lee emails bancarios nuevos de Gmail
2. Parsea y guarda en notificaciones_bancarias
3. Intenta auto-conciliar con pagos pendientes

Así, cuando cajera o colegiado consulta /verificar-pago,
la respuesta es instantánea (solo consulta tabla local).

Configuración en celery_app.py:
    app.conf.beat_schedule = {
        'sync-emails-bancarios': {
            'task': 'app.tasks.sync_emails.sincronizar_emails_bancarios',
            'schedule': 45.0,  # cada 45 segundos
        },
    }
"""

import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

TZ_PERU = timezone(timedelta(hours=-5))


def sincronizar_emails_bancarios():
    """
    Task principal: lee Gmail y guarda notificaciones.

    Si usas Celery, decorar con @celery_app.task
    Si usas APScheduler o similar, llamar directamente.
    """
    from app.database import SessionLocal
    from app.services.gmail_service import GmailService
    from app.services.conciliacion_service import ConciliacionService

    db = SessionLocal()

    try:
        gmail = GmailService()

        # Leer últimos 10 minutos (overlap intencional para no perder nada)
        desde = datetime.now(TZ_PERU) - timedelta(minutes=10)
        emails = gmail.leer_notificaciones_bancarias(desde=desde, max_results=20)

        if not emails:
            return {"nuevos": 0}

        svc = ConciliacionService(db)
        stats = svc.procesar_emails(organization_id=1, emails=emails)

        if stats.get("nuevos", 0) > 0:
            logger.info(f"Sync emails: {stats}")

        return stats

    except Exception as e:
        logger.error(f"Error en sync_emails: {e}", exc_info=True)
        return {"error": str(e)}

    finally:
        db.close()


# ══════════════════════════════════════════════════════════
# ALTERNATIVA SIN CELERY: Usar BackgroundTasks de FastAPI
# ══════════════════════════════════════════════════════════

"""
Si aún no tienes Celery configurado, puedes usar un thread simple
que se ejecuta al iniciar la app:

En app/main.py, agregar:

import threading
import time

def _background_sync():
    '''Loop infinito que sincroniza emails cada 45 seg.'''
    time.sleep(10)  # Esperar a que la app inicie
    while True:
        try:
            from app.tasks.sync_emails import sincronizar_emails_bancarios
            sincronizar_emails_bancarios()
        except Exception as e:
            logger.error(f"Background sync error: {e}")
        time.sleep(45)

# Al final de main.py, después de crear la app:
sync_thread = threading.Thread(target=_background_sync, daemon=True)
sync_thread.start()
"""


# ══════════════════════════════════════════════════════════
# ALTERNATIVA: Endpoint manual + JS polling del dashboard
# ══════════════════════════════════════════════════════════

"""
Si no quieres ni Celery ni thread, el dashboard del tesorero
puede llamar a POST /sincronizar automáticamente cada 30 seg:

setInterval(() => {
    fetch('/api/conciliacion/sincronizar?horas=1', {method:'POST'})
        .then(r => r.json())
        .then(d => {
            if (d.stats?.nuevos > 0) cargarNotificaciones();
        });
}, 30000);

Funciona para 1-2 usuarios concurrentes. Para más, usar Celery.
"""
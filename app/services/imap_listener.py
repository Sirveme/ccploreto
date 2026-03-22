"""
app/services/imap_listener.py — ColegiosPro
Servicio permanente IMAP IDLE.
Usa los modelos NotificacionBancaria y CuentaReceptora ya existentes en app/models.py

Variables de entorno (Railway):
  IMAP_HOST        = mail.colegiospro.org.pe   ← Hostinger
  IMAP_PORT        = 993
  IMAP_USER        = info@colegiospro.org.pe
  IMAP_PASSWORD    = ****
  IMAP_MAILBOX     = INBOX
  DATABASE_URL     = postgresql://...
  ORG_ID_DEFAULT   = 1   ← organization_id del CCPL
"""

import email as _email
import imaplib
import logging
import os
import time
from datetime import datetime

logger = logging.getLogger('imap_listener')

# ── Config ─────────────────────────────────────────────────────────────────────
IMAP_HOST     = os.getenv('IMAP_HOST',     'mail.colegiospro.org.pe')
IMAP_PORT     = int(os.getenv('IMAP_PORT', '993'))
IMAP_USER     = os.getenv('IMAP_USER',     '')
IMAP_PASSWORD = os.getenv('IMAP_PASSWORD', '')
IMAP_MAILBOX  = os.getenv('IMAP_MAILBOX',  'INBOX')
DATABASE_URL  = os.getenv('DATABASE_URL',  '')
ORG_ID        = int(os.getenv('ORG_ID_DEFAULT', '1'))

RECONECTAR_EN = 25 * 60   # IMAP IDLE max ~30 min, reconectar antes
RETRY_DELAY   = 30        # segundos entre reintentos si falla la conexión


# ── BD ─────────────────────────────────────────────────────────────────────────
def get_db_session():
    """Crea sesión independiente (el listener corre fuera de FastAPI)."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    if not DATABASE_URL:
        raise RuntimeError('DATABASE_URL no configurada')
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    Session = sessionmaker(bind=engine)
    return Session()


# ── Guardar en BD usando modelos existentes ────────────────────────────────────
def guardar_notificacion(pago, from_header: str, db) -> bool:
    """
    Guarda el pago parseado en NotificacionBancaria (modelo existente).
    Retorna True si se insertó, False si era duplicado.
    """
    from app.models import NotificacionBancaria, CuentaReceptora

    if not pago or not pago.es_valido:
        logger.warning('[BD] Pago inválido, descartando')
        return False

    # Deduplicar por email_message_id
    if pago.email_message_id:
        existe = db.query(NotificacionBancaria).filter_by(
            email_message_id=pago.email_message_id
        ).first()
        if existe:
            logger.info('[BD] Duplicado por message_id, ignorado')
            return False

    # Buscar cuenta receptora por banco
    cuenta_id = None
    if pago.banco:
        cuenta = db.query(CuentaReceptora).filter(
            CuentaReceptora.organization_id == ORG_ID,
            CuentaReceptora.banco.ilike(f'%{pago.banco}%'),
            CuentaReceptora.activo == True,
        ).first()
        if cuenta:
            cuenta_id = cuenta.id

    # Mapear tipo_operacion al formato del modelo existente
    tipo_map = {
        'yape':          'yape_recibido',
        'plin':          'plin_recibido',
        'transferencia': 'transferencia',
    }
    tipo_op = tipo_map.get(pago.tipo_operacion, 'transferencia')

    registro = NotificacionBancaria(
        organization_id     = ORG_ID,
        cuenta_receptora_id = cuenta_id,
        email_message_id    = pago.email_message_id[:200] if pago.email_message_id else None,
        email_from          = from_header[:200] if from_header else '',
        email_subject       = pago.raw_subject[:500] if pago.raw_subject else '',
        email_date          = pago.fecha_operacion or datetime.utcnow(),
        banco               = pago.banco,
        tipo_operacion      = tipo_op,
        monto               = pago.monto,
        moneda              = 'PEN',
        fecha_operacion     = pago.fecha_operacion,
        codigo_operacion    = pago.nro_operacion,
        remitente_nombre    = pago.remitente_nombre,
        cuenta_destino      = pago.cuenta_destino,
        destino_tipo        = pago.tipo_operacion.capitalize() if pago.tipo_operacion else None,
        estado              = 'pendiente',
        raw_body            = pago.raw_subject,
        observaciones       = f'Parser confianza: {pago.confianza}% | Concepto: {pago.concepto or ""}',
    )

    db.add(registro)
    db.commit()
    db.refresh(registro)

    logger.info(
        f'[BD] ✅ NotificacionBancaria id={registro.id} '
        f'banco={pago.banco} monto={pago.monto} '
        f'cod_op={pago.nro_operacion} confianza={pago.confianza}%'
    )

    # Intentar matching automático con reportes de pago pendientes
    try:
        from app.services.motor_matching import intentar_matching_automatico
        intentar_matching_automatico(registro, ORG_ID, db)
    except Exception as e:
        logger.debug(f'[BD] Matching automático omitido: {e}')

    return True


# ── IMAP helpers ───────────────────────────────────────────────────────────────
def conectar_imap() -> imaplib.IMAP4_SSL:
    logger.info(f'[IMAP] Conectando {IMAP_USER} @ {IMAP_HOST}:{IMAP_PORT}')
    conn = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    conn.login(IMAP_USER, IMAP_PASSWORD)
    conn.select(IMAP_MAILBOX)
    logger.info('[IMAP] Conectado ✅')
    return conn


def obtener_ids_no_leidos(conn: imaplib.IMAP4_SSL) -> list:
    _, data = conn.search(None, 'UNSEEN')
    return data[0].split() if data[0] else []


def leer_email_raw(conn: imaplib.IMAP4_SSL, uid: bytes) -> bytes:
    _, data = conn.fetch(uid, '(RFC822)')
    if data and data[0] and isinstance(data[0], tuple):
        return data[0][1]
    return b''


def marcar_leido(conn: imaplib.IMAP4_SSL, uid: bytes):
    conn.store(uid, '+FLAGS', '\\Seen')


def esperar_idle(conn: imaplib.IMAP4_SSL, timeout_seg: int = RECONECTAR_EN) -> bool:
    """
    Envía IDLE y bloquea hasta recibir EXISTS (email nuevo) o timeout.
    Retorna True si llegó email nuevo.
    """
    logger.info('[IMAP] IDLE activo — esperando email nuevo...')
    conn.send(b'IDLE\r\n')
    conn.sock.settimeout(timeout_seg)
    inicio = time.monotonic()

    try:
        while True:
            linea = conn.readline().decode('utf-8', errors='replace').strip()
            if not linea:
                continue
            logger.debug(f'[IMAP] {linea}')
            if 'EXISTS' in linea or 'RECENT' in linea:
                logger.info('[IMAP] 📬 Email nuevo detectado')
                conn.send(b'DONE\r\n')
                conn.readline()
                return True
            if time.monotonic() - inicio > timeout_seg:
                conn.send(b'DONE\r\n')
                conn.readline()
                return False
    except (TimeoutError, OSError):
        logger.info('[IMAP] Timeout IDLE')
        return False


# ── Capa 1: Verificacion DKIM ─────────────────────────────────────────────────
def verificar_dkim(raw_bytes: bytes) -> bool:
    # Verifica la firma DKIM. Requiere: pip install dkimpy
    # Si no esta instalado, retorna True (Capa 2 dominio sigue activa).
    try:
        import dkim
        resultado = dkim.verify(raw_bytes)
        if not resultado:
            logger.warning('[DKIM] Firma invalida o ausente')
        return resultado
    except ImportError:
        logger.debug('[DKIM] dkimpy no disponible — omitido')
        return True
    except Exception as e:
        logger.warning(f'[DKIM] Error: {e}')
        return True



# ── Procesamiento ──────────────────────────────────────────────────────────────
def procesar_no_leidos(conn: imaplib.IMAP4_SSL, db):
    from app.services.email_parser import parsear_email

    ids = obtener_ids_no_leidos(conn)
    if not ids:
        return

    logger.info(f'[IMAP] {len(ids)} email(s) no leído(s)')
    for uid in ids:
        try:
            raw = leer_email_raw(conn, uid)
            if not raw:
                continue

            msg      = _email.message_from_bytes(raw)
            from_hdr = msg.get('From', '')

            # Capa 1: DKIM
            if not verificar_dkim(raw):
                logger.warning(
                    f'[IMAP] SEGURIDAD — DKIM invalido, descartado: '
                    f'From={from_hdr[:60]}'
                )
                marcar_leido(conn, uid)
                continue

            # Capa 2: dominio (en parser) + parseo
            pago = parsear_email(raw, organization_id=ORG_ID)

            if pago and pago.es_valido and pago.es_pago_recibido:
                guardar_notificacion(pago, from_hdr, db)
            else:
                if pago:
                    motivo = 'no es recibido' if not pago.es_pago_recibido else 'sin monto'
                else:
                    motivo = 'no bancario o dominio no autorizado'
                logger.info(f'[IMAP] Descartado ({motivo}): {msg.get("Subject","")[:60]}')

            marcar_leido(conn, uid)

        except Exception as e:
            logger.error(f'[IMAP] Error uid={uid}: {e}', exc_info=True)


# ── Bucle principal con reconexión automática ──────────────────────────────────
def run():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    )
    logger.info('═══ IMAP Listener iniciando ═══')
    logger.info(f'    Host:   {IMAP_HOST}:{IMAP_PORT}')
    logger.info(f'    Buzón:  {IMAP_USER} / {IMAP_MAILBOX}')
    logger.info(f'    Org ID: {ORG_ID}')

    while True:
        conn = None
        db   = None
        try:
            db   = get_db_session()
            conn = conectar_imap()

            # Procesar emails no leídos acumulados al arrancar
            procesar_no_leidos(conn, db)

            # Bucle IDLE
            while True:
                hay_nuevo = esperar_idle(conn)
                if hay_nuevo:
                    procesar_no_leidos(conn, db)
                else:
                    logger.info('[IMAP] Reconexión preventiva')
                    break

        except imaplib.IMAP4.error as e:
            logger.error(f'[IMAP] Error protocolo: {e}')
        except ConnectionError as e:
            logger.error(f'[IMAP] Error conexión: {e}')
        except Exception as e:
            logger.error(f'[IMAP] Error inesperado: {e}', exc_info=True)
        finally:
            if conn:
                try: conn.logout()
                except: pass
            if db:
                try: db.close()
                except: pass

        logger.info(f'[IMAP] Reintentando en {RETRY_DELAY}s...')
        time.sleep(RETRY_DELAY)


if __name__ == '__main__':
    if not IMAP_USER or not IMAP_PASSWORD:
        print('Configura: IMAP_USER, IMAP_PASSWORD, DATABASE_URL')
        exit(1)
    run()
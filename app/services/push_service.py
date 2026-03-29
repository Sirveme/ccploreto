"""
app/services/push_service.py
Servicio genérico de Push Notifications para CCPL.

Usos:
  - Pago validado → colegiado HÁBIL
  - Pago reportado (recibido)
  - Pago rechazado
  - Pago en línea confirmado (OpenPay)
  - Cuota fraccionamiento vencida
  - Comunicados institucionales

Llamar desde:
  - aprobar_pago.py       → al validar
  - conciliacion.py       → al auto-aprobar
  - pagos_publicos.py     → al reportar
  - generador_deudas.py   → al generar deuda vencida
"""

import json
import logging
import os
from typing import Optional

from pywebpush import webpush, WebPushException
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

VAPID_PRIVATE = os.getenv("VAPID_PRIVATE_KEY")
VAPID_EMAIL   = os.getenv("VAPID_CLAIMS_EMAIL")


# ── Mensajes predefinidos ────────────────────────────────────
MENSAJES = {
    "pago_validado_habil":     ("✅ Pago validado", "Ya eres HÁBIL. Tu constancia está disponible."),
    "pago_validado_fracc":     ("✅ Cuota registrada", "Tu cuota de fraccionamiento fue validada."),
    "pago_reportado":          ("📤 Pago recibido", "Lo validaremos en breve. Te notificaremos."),
    "pago_rechazado":          ("❌ Pago no validado", "Tu pago no pudo ser verificado. Contáctanos."),
    "pago_online_confirmado":  ("💳 Pago confirmado", "Tu pago con tarjeta fue procesado exitosamente."),
    "cuota_vencida":           ("⚠️ Cuota vencida", "Tu cuota de fraccionamiento está vencida. Paga para mantener tu habilidad."),
    "constancia_lista":        ("📄 Constancia lista", "Tu Constancia de Habilidad está disponible."),
}


def enviar_push_colegiado(
    db:           Session,
    colegiado_id: int,
    mensaje:      str,
    titulo:       str = "CCPL",
    url:          Optional[str] = None,
    imagen:       Optional[str] = None,
) -> int:
    """
    Envía Push Notification a todos los dispositivos activos del colegiado.

    Args:
        db:           Sesión de BD
        colegiado_id: ID del colegiado
        mensaje:      Texto del cuerpo de la notificación
        titulo:       Título (default: "CCPL")
        url:          URL a abrir al tocar la notificación (opcional)
        imagen:       URL de imagen para la notificación (opcional)

    Returns:
        Número de dispositivos a los que se envió exitosamente.
    """
    from app.models import Device, Colegiado

    col = db.query(Colegiado).filter(Colegiado.id == colegiado_id).first()
    if not col or not col.member_id:
        logger.warning(f"[Push] Colegiado {colegiado_id} sin member_id")
        return 0

    devices = db.query(Device).filter(
        Device.member_id == col.member_id,
        Device.is_active == True,
    ).all()

    if not devices:
        logger.info(f"[Push] Colegiado {colegiado_id} sin dispositivos registrados")
        return 0

    payload = {
        "title": titulo,
        "body":  mensaje,
        "icon":  "/static/img/icon-192.png",
        "badge": "/static/img/icon-192.png",
    }
    if url:
        payload["url"] = url
    if imagen:
        payload["image"] = imagen

    enviados   = 0
    expirados  = []

    for dev in devices:
        try:
            webpush(
                subscription_info={
                    "endpoint": dev.push_endpoint,
                    "keys": {
                        "p256dh": dev.push_p256dh,
                        "auth":   dev.push_auth,
                    },
                },
                data=json.dumps(payload),
                vapid_private_key=VAPID_PRIVATE,
                vapid_claims={"sub": VAPID_EMAIL},
            )
            enviados += 1
        except WebPushException as e:
            if e.response and e.response.status_code in (404, 410):
                expirados.append(dev)
            logger.warning(f"[Push] Falló device {dev.id}: {e}")
        except Exception as e:
            logger.warning(f"[Push] Error device {dev.id}: {e}")

    # Marcar suscripciones expiradas como inactivas
    for dev in expirados:
        dev.is_active = False
    if expirados:
        db.flush()

    logger.info(
        f"[Push] Colegiado {colegiado_id} → {enviados}/{len(devices)} enviados"
        + (f" ({len(expirados)} expirados)" if expirados else "")
    )
    return enviados


def enviar_push_por_tipo(
    db:           Session,
    colegiado_id: int,
    tipo:         str,
    extra_info:   str = "",
    url:          Optional[str] = None,
) -> int:
    """
    Envía Push usando un tipo predefinido de MENSAJES.

    Args:
        tipo:       Clave de MENSAJES, ej: "pago_validado_habil"
        extra_info: Texto adicional que se agrega al mensaje (opcional)
        url:        URL a abrir al tocar

    Ejemplo:
        enviar_push_por_tipo(db, col_id, "pago_validado_habil",
                             extra_info="Constancia CERT-2026-00123 emitida.")
    """
    if tipo not in MENSAJES:
        logger.warning(f"[Push] Tipo '{tipo}' no definido en MENSAJES")
        return 0

    titulo, mensaje = MENSAJES[tipo]
    if extra_info:
        mensaje = f"{mensaje} {extra_info}"

    return enviar_push_colegiado(db, colegiado_id, mensaje, titulo, url=url)


def enviar_push_member(
    db:        Session,
    member_id: int,
    mensaje:   str,
    titulo:    str = "CCPL",
    url:       Optional[str] = None,
) -> int:
    """
    Envía Push directamente por member_id (para directivos, cajeros, etc.)
    """
    from app.models import Device

    devices = db.query(Device).filter(
        Device.member_id == member_id,
        Device.is_active == True,
    ).all()

    enviados = 0
    for dev in devices:
        try:
            webpush(
                subscription_info={
                    "endpoint": dev.push_endpoint,
                    "keys": {
                        "p256dh": dev.push_p256dh,
                        "auth":   dev.push_auth,
                    },
                },
                data=json.dumps({
                    "title": titulo,
                    "body":  mensaje,
                    "icon":  "/static/img/icon-192.png",
                    **({"url": url} if url else {}),
                }),
                vapid_private_key=VAPID_PRIVATE,
                vapid_claims={"sub": VAPID_EMAIL},
            )
            enviados += 1
        except WebPushException as e:
            if e.response and e.response.status_code in (404, 410):
                dev.is_active = False
        except Exception:
            pass

    db.flush()
    return enviados
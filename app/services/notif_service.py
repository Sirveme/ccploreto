"""
app/services/notif_service.py
Sistema unificado de notificaciones push para CCPL (zClaude-97n).

Despacha cualquier evento del sistema hacia destinatarios configurables,
respetando preferencias personales (inmediato/resumen/silencio).

Contrato de uso:

    from app.services.notif_service import disparar_evento

    disparar_evento(
        db=db,
        organization_id=1,
        evento_tipo="pago_caja",
        audiencia="categoria:pagos",
        payload={...},
        actor_user_id=user_id,            # se excluye del envío
        destinatarios_extra_ids=[uid],    # se agregan SIEMPRE
    )

NOTA (zClaude-97n): este service usa enviar_push_member(db, member_id, mensaje,
titulo, url) de push_service.py — el parámetro del cuerpo se llama `mensaje`
(no `cuerpo`) y la función retorna el número de devices a los que se envió (int).
"""
import hashlib
import json
import logging
from datetime import time
from typing import List, Optional, Dict, Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.push_service import enviar_push_member

log = logging.getLogger(__name__)

# Catálogo de eventos → categoría + template
EVENTO_CATALOGO = {
    # Categoría 'pagos'
    "pago_caja": {
        "categoria": "pagos",
        "titulo_template": "💰 Pago en Caja — S/{monto:.2f}",
        "body_template": "{colegiado_nombre} ({matricula}) • {conceptos} • {cobrador_nombre}",
        "url_template": "{url_detalle}",
    },
    "pago_web": {
        "categoria": "pagos",
        "titulo_template": "🌐 Pago Web — S/{monto:.2f}",
        "body_template": "{colegiado_nombre} ({matricula}) • {conceptos}",
        "url_template": "{url_detalle}",
    },
    "pago_rechazado": {
        "categoria": "pagos",
        "titulo_template": "❌ Pago rechazado — S/{monto:.2f}",
        "body_template": "{colegiado_nombre} • {motivo}",
        "url_template": "{url_detalle}",
    },
    # Categoría 'mi_cuenta'
    "mi_pago_confirmado": {
        "categoria": "mi_cuenta",
        "titulo_template": "✅ Pago confirmado — S/{monto:.2f}",
        "body_template": "Tu comprobante {comprobante_serie}-{comprobante_numero} está listo",
        "url_template": "{url_detalle}",
    },
    "deuda_nueva": {
        "categoria": "mi_cuenta",
        "titulo_template": "📋 Nueva deuda — S/{monto:.2f}",
        "body_template": "{concepto} • Vence: {fecha_vencimiento}",
        "url_template": "/portal/mis-deudas",
    },
    "cuota_proxima_vencer": {
        "categoria": "mi_cuenta",
        "titulo_template": "⏰ Cuota vence en {dias_restantes} días",
        "body_template": "{concepto} — S/{monto:.2f}",
        "url_template": "/portal/mis-deudas",
    },
    "fraccion_riesgo": {
        "categoria": "mi_cuenta",
        "titulo_template": "⚠️ Tu fraccionamiento en riesgo",
        "body_template": "{cuotas_vencidas} cuotas vencidas — actúa hoy",
        "url_template": "/portal/mis-fraccionamientos",
    },
    # Categoría 'ccpl'
    "comunicado_nuevo": {
        "categoria": "ccpl",
        "titulo_template": "{icono} {tipo_comunicado}",
        "body_template": "{titulo}",
        "url_template": "/comunicaciones",
    },
    "fomo_motivacional": {
        "categoria": "ccpl",
        "titulo_template": "{titulo}",
        "body_template": "{body}",
        "url_template": "{url}",
    },
    # Categoría 'tributario_propio'
    "vencimiento_propio": {
        "categoria": "tributario_propio",
        "titulo_template": "📅 Vence tu obligación SUNAT",
        "body_template": "{tributo} • Fecha límite: {fecha_limite}",
        "url_template": "/portal/tributario",
    },
    "vencimiento_cliente": {
        "categoria": "tributario_propio",
        "titulo_template": "📅 Vence obligación de cliente",
        "body_template": "RUC ...{ultimos_digitos} • {tributo} • {fecha_limite}",
        "url_template": "/portal/tributario",
    },
    # Categoría 'gestion'
    "nuevo_colegiado": {
        "categoria": "gestion",
        "titulo_template": "👤 Nuevo colegiado",
        "body_template": "{matricula} {nombre} dado de alta",
        "url_template": "/caja",
    },
    "reporte_diario": {
        "categoria": "gestion",
        "titulo_template": "📊 Resumen del día",
        "body_template": "Recaudo S/{recaudo:.2f} • {pagos} pagos • {nuevos_morosos} morosos",
        "url_template": "/finanzas/dashboard",
    },
    "aprobacion_pendiente": {
        "categoria": "gestion",
        "titulo_template": "✍️ Operación pendiente de tu firma",
        "body_template": "{descripcion}",
        "url_template": "/finanzas/aprobaciones",
    },
    "panico_activado": {
        "categoria": "gestion",
        "titulo_template": "🚨 ALERTA DE SEGURIDAD",
        "body_template": "{ubicacion} • {fecha_hora}",
        "url_template": "/admin/panico",
    },
}


def _hash_payload(evento_tipo: str, payload: dict) -> str:
    base = f"{evento_tipo}|{json.dumps(payload, sort_keys=True, default=str)}"
    return hashlib.sha256(base.encode()).hexdigest()[:32]


def _users_por_categoria(db: Session, organization_id: int, categoria: str) -> List[int]:
    """user_ids de users cuyo role tiene permiso sobre la categoría."""
    rows = db.execute(text("""
        SELECT DISTINCT m.user_id
        FROM members m
        JOIN notif_role_categoria nrc
          ON nrc.role = m.role AND nrc.organization_id = m.organization_id
        WHERE nrc.organization_id = :org
          AND nrc.categoria = :cat
          AND nrc.activo = TRUE
          AND m.is_active = TRUE
          AND m.user_id IS NOT NULL
    """), {"org": organization_id, "cat": categoria}).fetchall()
    return [r[0] for r in rows]


def _users_por_role(db: Session, organization_id: int, role: str) -> List[int]:
    rows = db.execute(text("""
        SELECT DISTINCT user_id FROM members
        WHERE organization_id = :org AND role = :role AND is_active = TRUE
          AND user_id IS NOT NULL
    """), {"org": organization_id, "role": role}).fetchall()
    return [r[0] for r in rows]


def _todos_habilitados(db: Session, organization_id: int) -> List[int]:
    """Colegiados habilitados (habil o vitalicio) con device activo.

    zClaude-97n: incluimos 'vitalicio' además de 'habil' porque, según las
    reglas de negocio congeladas (30+ años → VITALICIO), un vitalicio es un
    colegiado hábil y debe recibir comunicados institucionales.
    """
    rows = db.execute(text("""
        SELECT DISTINCT m.user_id
        FROM members m
        JOIN colegiados c ON c.member_id = m.id
        JOIN devices d ON d.member_id = m.id AND d.is_active = TRUE
        WHERE m.organization_id = :org
          AND c.condicion IN ('habil', 'vitalicio')
          AND m.user_id IS NOT NULL
    """), {"org": organization_id}).fetchall()
    return [r[0] for r in rows]


def _resolver_audiencia(db: Session, organization_id: int, audiencia: str, payload: dict) -> List[int]:
    if audiencia.startswith("categoria:"):
        return _users_por_categoria(db, organization_id, audiencia[10:])
    if audiencia.startswith("role:"):
        return _users_por_role(db, organization_id, audiencia[5:])
    if audiencia == "colegiado_propio":
        cid = payload.get("colegiado_id")
        if not cid:
            return []
        row = db.execute(text("""
            SELECT m.user_id FROM members m
            JOIN colegiados c ON c.member_id = m.id
            WHERE c.id = :cid AND m.user_id IS NOT NULL
        """), {"cid": cid}).fetchone()
        return [row[0]] if row else []
    if audiencia == "todos_habilitados":
        return _todos_habilitados(db, organization_id)
    if audiencia.startswith("user_ids:"):
        try:
            ids = json.loads(audiencia[9:])
            return [int(x) for x in ids]
        except Exception:
            return []
    return []


def _config_usuario(db: Session, user_id: int, categoria: str) -> dict:
    """Lee notif_config; si no existe, retorna defaults sanos."""
    row = db.execute(text("""
        SELECT activo, modo, hora_resumen, monto_minimo, config_extra
        FROM notif_config
        WHERE user_id = :uid AND categoria = :cat
    """), {"uid": user_id, "cat": categoria}).fetchone()
    if row:
        return {
            "activo": row[0],
            "modo": row[1],
            "hora_resumen": row[2],
            "monto_minimo": float(row[3] or 0),
            "config_extra": row[4] or {},
        }
    return {
        "activo": True,
        "modo": "inmediato",
        "hora_resumen": time(20, 0),
        "monto_minimo": 0,
        "config_extra": {},
    }


def _construir_mensaje(evento_tipo: str, payload: dict) -> Dict[str, str]:
    cfg = EVENTO_CATALOGO.get(evento_tipo)
    if not cfg:
        return {"titulo": evento_tipo, "body": "", "url": "/"}
    try:
        return {
            "titulo": cfg["titulo_template"].format(**payload),
            "body": cfg["body_template"].format(**payload),
            "url": cfg["url_template"].format(**payload),
        }
    except (KeyError, ValueError, IndexError) as e:
        log.warning(f"[notif] Error formateando {evento_tipo}: {e}. Payload: {payload}")
        return {"titulo": evento_tipo, "body": json.dumps(payload, default=str)[:140], "url": "/"}


def _log(db: Session, organization_id: int, user_id: int, evento_tipo: str, categoria: str,
         payload_hash: str, canal: str, resultado: str, error: Optional[str] = None):
    try:
        db.execute(text("""
            INSERT INTO notif_log (organization_id, user_id, evento_tipo, categoria, payload_hash, canal, resultado, error_detalle)
            VALUES (:org, :uid, :et, :cat, :ph, :ca, :re, :err)
        """), {"org": organization_id, "uid": user_id, "et": evento_tipo, "cat": categoria,
               "ph": payload_hash, "ca": canal, "re": resultado, "err": error})
    except Exception as e:
        log.warning(f"[notif] No se pudo loggear: {e}")


def _enviar_inmediato(db: Session, user_id: int, mensaje: dict, organization_id: int,
                      evento_tipo: str, categoria: str, payload_hash: str) -> bool:
    """Envía push inmediato. Retorna True si se envió a >=1 device."""
    member = db.execute(text("""
        SELECT id FROM members
        WHERE user_id = :uid AND organization_id = :org AND is_active = TRUE
        LIMIT 1
    """), {"uid": user_id, "org": organization_id}).fetchone()
    if not member:
        _log(db, organization_id, user_id, evento_tipo, categoria, payload_hash, "silencio", "sin_member")
        return False

    try:
        # push_service.enviar_push_member(db, member_id, mensaje, titulo, url) -> int (nº enviados)
        enviados = enviar_push_member(
            db=db,
            member_id=member[0],
            mensaje=mensaje["body"],
            titulo=mensaje["titulo"],
            url=mensaje.get("url", "/"),
        )
        if enviados and enviados > 0:
            _log(db, organization_id, user_id, evento_tipo, categoria, payload_hash, "push", "enviado")
            return True
        _log(db, organization_id, user_id, evento_tipo, categoria, payload_hash, "silencio", "sin_device")
        return False
    except Exception as e:
        log.error(f"[notif] Error enviando a user_id={user_id}: {e}")
        _log(db, organization_id, user_id, evento_tipo, categoria, payload_hash, "push", "error", str(e))
        return False


def _encolar_resumen(db: Session, organization_id: int, user_id: int, evento_tipo: str,
                     categoria: str, payload: dict, modo: str):
    db.execute(text("""
        INSERT INTO notif_queue (organization_id, user_id, evento_tipo, categoria, payload, modo)
        VALUES (:org, :uid, :et, :cat, :pl, :mo)
    """), {"org": organization_id, "uid": user_id, "et": evento_tipo, "cat": categoria,
           "pl": json.dumps(payload, default=str), "mo": modo})


def disparar_evento(
    db: Session,
    organization_id: int,
    evento_tipo: str,
    audiencia: str,
    payload: Dict[str, Any],
    actor_user_id: Optional[int] = None,
    destinatarios_extra_ids: Optional[List[int]] = None,
) -> Dict[str, int]:
    """
    Despacha un evento. Retorna estadísticas:
    {enviados, encolados, silenciados, errores}.

    No hace commit: el llamador controla la transacción (los hooks lo hacen
    en un try/except aislado para que un fallo de push nunca rompa el pago).
    """
    cfg_evento = EVENTO_CATALOGO.get(evento_tipo)
    if not cfg_evento:
        log.warning(f"[notif] Evento desconocido: {evento_tipo}")
        return {"enviados": 0, "encolados": 0, "silenciados": 0, "errores": 1}

    categoria = cfg_evento["categoria"]

    # 1. Resolver audiencia
    user_ids = set(_resolver_audiencia(db, organization_id, audiencia, payload))

    # 2. Agregar destinatarios extra (p. ej. el colegiado dueño del pago)
    if destinatarios_extra_ids:
        user_ids.update(int(x) for x in destinatarios_extra_ids if x)

    # 3. Excluir actor
    if actor_user_id:
        user_ids.discard(actor_user_id)

    if not user_ids:
        return {"enviados": 0, "encolados": 0, "silenciados": 0, "errores": 0}

    # 4. Construir mensaje
    mensaje = _construir_mensaje(evento_tipo, payload)
    payload_hash = _hash_payload(evento_tipo, payload)

    # 5. Para cada destinatario aplicar su config
    stats = {"enviados": 0, "encolados": 0, "silenciados": 0, "errores": 0}

    for uid in user_ids:
        try:
            cfg = _config_usuario(db, uid, categoria)

            if not cfg["activo"] or cfg["modo"] == "silencioso":
                _log(db, organization_id, uid, evento_tipo, categoria, payload_hash, "silencio", "silenciado_por_config")
                stats["silenciados"] += 1
                continue

            # Filtro de monto mínimo (solo aplica cuando el payload trae 'monto')
            if "monto" in payload and cfg["monto_minimo"] > 0:
                try:
                    if float(payload.get("monto", 0)) < cfg["monto_minimo"]:
                        _log(db, organization_id, uid, evento_tipo, categoria, payload_hash, "silencio", "bajo_monto_minimo")
                        stats["silenciados"] += 1
                        continue
                except (TypeError, ValueError):
                    pass

            if cfg["modo"] == "inmediato":
                if _enviar_inmediato(db, uid, mensaje, organization_id, evento_tipo, categoria, payload_hash):
                    stats["enviados"] += 1
                else:
                    stats["silenciados"] += 1
            else:
                _encolar_resumen(db, organization_id, uid, evento_tipo, categoria, payload, cfg["modo"])
                stats["encolados"] += 1

        except Exception as e:
            log.error(f"[notif] Error procesando user_id={uid}: {e}")
            stats["errores"] += 1

    return stats

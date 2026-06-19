"""
app/routers/api_comunicados.py
API Comunicados — feed del colegiado + envío desde directivos
"""

import json
import os
import secrets
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

from fastapi import UploadFile
import shutil, uuid
from pathlib import Path

from app.database import get_db
from app.models import Member, Bulletin, BulletinEvent
from app.routers.dashboard import get_current_member

router = APIRouter(prefix="/api/comunicados", tags=["Comunicados"])

# Perú = UTC-5 todo el año (sin DST). Los <input type="datetime-local"> llegan en
# hora local de Lima sin zona; los convertimos a UTC-aware para comparar con NOW().
_LIMA_OFFSET = timedelta(hours=-5)


def _parse_fecha_local(valor) -> Optional[datetime]:
    """Convierte un string datetime-local (hora Lima) a datetime UTC-aware.
    Acepta también datetime ya parseado. Devuelve None si no se puede."""
    if valor is None or valor == "":
        return None
    if isinstance(valor, datetime):
        dt = valor
    else:
        try:
            dt = datetime.fromisoformat(str(valor))
        except ValueError:
            return None
    if dt.tzinfo is None:
        # Interpretar como hora de Lima y pasar a UTC
        return (dt - _LIMA_OFFSET).replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ── GET /api/comunicados/recientes ───────────────────────────
@router.get("/recientes")
async def comunicados_recientes(
    limit: int = 3,
    member: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
):
    """Feed de comunicados recientes para el dashboard del colegiado."""
    now = datetime.now(timezone.utc)

    bulletins = db.query(Bulletin).filter(
        Bulletin.organization_id == member.organization_id,
        (Bulletin.expires_at == None) | (Bulletin.expires_at > now),
    ).order_by(Bulletin.created_at.desc()).limit(limit).all()

    if not bulletins:
        return JSONResponse({"comunicados": []})

    # Cuáles ya leyó este member
    leidos = {
        e.bulletin_id
        for e in db.query(BulletinEvent).filter(
            BulletinEvent.member_id   == member.id,
            BulletinEvent.bulletin_id.in_([b.id for b in bulletins]),
            BulletinEvent.status.in_(["read", "confirmed"]),
        ).all()
    }

    return JSONResponse({
        "comunicados": [{
            "id":             b.id,
            "title":          b.title,
            "content":        (b.content or "")[:120],
            "priority":       b.priority or "info",
            "image_url":      b.image_url,
            "action_payload": b.action_payload,
            "created_at":     b.created_at.isoformat() if b.created_at else None,
            "leido":          b.id in leidos,
        } for b in bulletins]
    })


# ── POST /api/comunicados/{id}/leer ─────────────────────────
@router.post("/{bulletin_id}/leer")
async def marcar_leido(
    bulletin_id: int,
    member: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
):
    """Marca un comunicado como leído."""
    existente = db.query(BulletinEvent).filter(
        BulletinEvent.bulletin_id == bulletin_id,
        BulletinEvent.member_id   == member.id,
    ).first()

    if not existente:
        db.add(BulletinEvent(
            bulletin_id   = bulletin_id,
            member_id     = member.id,
            status        = "read",
        ))
        db.commit()

    return JSONResponse({"ok": True})


# ── POST /api/comunicados/enviar ─────────────────────────────
class ComunicadoInput(BaseModel):
    title:           str
    content:         str
    tipo:            str = "comunicado"
    priority:        str = "info"
    image_url:       Optional[str] = None
    video_url:       Optional[str] = None  # ← agregar
    segmento:        str = "todos"
    expires_at:      Optional[str] = None
    fecha_evento:    Optional[str] = None
    lugar_evento:    Optional[str] = None
    requiere_confirmacion: bool = False
    genera_multa:    bool = False
    target_criteria: Optional[dict] = None
    # zClaude-97p — campos específicos de asamblea
    modalidad:         Optional[str] = None   # 'presencial' | 'virtual' | 'hibrida'
    plantilla_botones: Optional[str] = None   # 'T1' | 'T2' | 'T7'
    link_virtual:      Optional[str] = None
    obligatoria:       bool = False
    quorum_minimo:     Optional[int] = None


@router.post("/enviar")
async def enviar_comunicado(
    data: ComunicadoInput,
    request: Request,
    member: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
):
    """Crea y envía un comunicado. Solo roles directivos."""
    from app.models import Device
    from app.routers.ws import manager

    ROLES_PERMITIDOS = ("decano", "admin", "director_finanzas", "tesorero",
                        "secretaria", "superadmin", "sote")
    if member.role not in ROLES_PERMITIDOS:
        return JSONResponse({"error": "Sin permiso"}, status_code=403)

    # zClaude-97p — la fecha del evento/asamblea llega como hora local de Lima
    fecha_evento_utc = _parse_fecha_local(data.fecha_evento)

    # Validación específica de asambleas
    if data.tipo == "asamblea":
        if not fecha_evento_utc:
            return JSONResponse({"error": "La asamblea requiere fecha y hora del evento"}, status_code=400)
        if not (data.lugar_evento and data.lugar_evento.strip()):
            return JSONResponse({"error": "La asamblea requiere indicar el lugar"}, status_code=400)
        if data.plantilla_botones not in ("T1", "T2", "T7"):
            return JSONResponse({"error": "La asamblea requiere una plantilla válida (T1, T2 o T7)"}, status_code=400)
        if fecha_evento_utc <= datetime.now(timezone.utc):
            return JSONResponse({"error": "La fecha del evento debe ser futura"}, status_code=400)

    # Guardar en BD
    bulletin = Bulletin(
        organization_id = member.organization_id,
        author_id       = member.id,
        title           = data.title,
        content         = data.content,
        priority        = data.priority,
        image_url       = data.image_url or None,
        video_url       = data.video_url or None,
        target_criteria = data.target_criteria or {"segmento": data.segmento},
        tipo            = data.tipo or "comunicado",
        fecha_evento    = fecha_evento_utc,
        lugar_evento    = data.lugar_evento or None,
        requiere_confirmacion = bool(data.requiere_confirmacion),
        genera_multa    = bool(data.genera_multa),
        # campos asamblea (None/False para otros tipos)
        modalidad         = data.modalidad if data.tipo == "asamblea" else None,
        plantilla_botones = data.plantilla_botones if data.tipo == "asamblea" else None,
        link_virtual      = data.link_virtual if data.tipo == "asamblea" else None,
        obligatoria       = bool(data.obligatoria) if data.tipo == "asamblea" else False,
        quorum_minimo     = data.quorum_minimo if data.tipo == "asamblea" else None,
    )
    db.add(bulletin)
    db.commit()
    db.refresh(bulletin)

    # zClaude-97p — Si es asamblea: token QR (zona 20-50 m) + recordatorio push
    if data.tipo == "asamblea":
        token_qr = secrets.token_urlsafe(32)
        db.execute(text("""
            INSERT INTO asamblea_qr_tokens
              (bulletin_id, token, organization_id, vigente_desde, vigente_hasta)
            VALUES (:bid, :tk, :org, :vd, :vh)
        """), {
            "bid": bulletin.id, "tk": token_qr,
            "org": member.organization_id,
            "vd": fecha_evento_utc - timedelta(hours=1),
            "vh": fecha_evento_utc + timedelta(hours=2),
        })
        db.commit()

        # Push inmediato solo si la asamblea es dentro de 7 días
        if (fecha_evento_utc - datetime.now(timezone.utc)) <= timedelta(days=7):
            try:
                from app.services.notif_service import disparar_evento
                cuando = fecha_evento_utc.astimezone(timezone.utc) + _LIMA_OFFSET
                disparar_evento(
                    db,
                    organization_id=member.organization_id,
                    evento_tipo="asambleas",
                    audiencia="todos_habilitados",
                    payload={
                        "titulo": data.title,
                        "mensaje": f"{data.lugar_evento} — {cuando.strftime('%d/%m/%Y %H:%M')}",
                        "url": f"/asambleas/{bulletin.id}",
                    },
                    actor_user_id=member.user_id,
                    nivel="N3",
                    sonido="campana.mp3",
                )
                db.commit()
            except Exception as _e:
                db.rollback()
                print(f"[Asamblea] push inicial no enviado: {_e}")

    # FOMO — broadcast a todos los conectados
    await manager.broadcast({
        "type":    "FOMO",
        "mensaje": f"📢 Nueva publicación: {data.title[:40]}",
        "tiempo":  4000,  # ms que permanece visible
    })

    db.refresh(bulletin)

    # WebSocket — notificar en tiempo real
    try:
        await manager.broadcast({
            "type":     "BULLETIN",
            "title":    data.title,
            "body":     data.content[:100],
            "priority": data.priority,
            "image":    data.image_url,
            "org_id":   member.organization_id,
        })
    except Exception as e:
        print(f"[Comunicados] WS error: {e}")

    # Push notifications
    query = db.query(Device).join(Member).filter(
        Member.organization_id == member.organization_id,
        Device.is_active == True,
    )

    if data.segmento == "habiles":
        from app.models import Colegiado as _Col
        query = query.join(_Col, _Col.member_id == Member.id).filter(
            _Col.condicion == "habil"
        )
    elif data.segmento == "inhabiles":
        from app.models import Colegiado as _Col
        query = query.join(_Col, _Col.member_id == Member.id).filter(
            _Col.condicion == "inhabil"
        )

    devices       = query.all()
    destinatarios = len(devices)

    private_key = os.getenv("VAPID_PRIVATE_KEY")
    email       = os.getenv("VAPID_CLAIMS_EMAIL")

    # zClaude-97p: las asambleas usan el push dedicado (disparar_evento, con
    # nivel/sonido y URL al modal); evitamos el push genérico para no duplicar.
    if private_key and devices and data.tipo != "asamblea":
        from pywebpush import webpush, WebPushException
        sent = 0
        for dev in devices:
            try:
                webpush(
                    subscription_info={
                        "endpoint": dev.push_endpoint,
                        "keys": {"p256dh": dev.push_p256dh, "auth": dev.push_auth}
                    },
                    data=json.dumps({
                        "type":  data.priority,
                        "title": f"CCPL — {data.title}",
                        "body":  data.content[:120],
                        "url":   "/comunicaciones",
                        "icon":  "/static/img/icon-192.png",
                        "image": data.image_url,
                    }),
                    vapid_private_key = private_key,
                    vapid_claims      = {"sub": email},
                    ttl               = 3600,
                )
                sent += 1
            except WebPushException as ex:
                if ex.response and ex.response.status_code == 410:
                    dev.is_active = False
                print(f"[Push ERROR] {ex} — response: {ex.response.text if ex.response else 'none'}")
            except Exception as ex:
                print(f"[Push ERROR general] {ex}")
        db.commit()
        print(f"[Comunicados] Push enviado a {sent}/{len(devices)} dispositivos")

    return JSONResponse({
        "ok":           True,
        "bulletin_id":  bulletin.id,
        "destinatarios": destinatarios,
        "mensaje":      f"Comunicado enviado a {destinatarios} dispositivos",
    })


# ── GET /api/comunicados/lista ───────────────────────────────
@router.get("/lista")
async def comunicados_lista(
    tipo: str = None,
    limit: int = 30,
    member: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
):
    """Lista de comunicados para /comunicaciones."""
    from app.models import Member as _Member
    now = datetime.now(timezone.utc)

    query = db.query(Bulletin).filter(
        Bulletin.organization_id == member.organization_id,
        (Bulletin.expires_at == None) | (Bulletin.expires_at > now),
    )

    if tipo and tipo != 'todos':
        query = query.filter(Bulletin.tipo == tipo)

    bulletins = query.order_by(Bulletin.created_at.desc()).limit(limit).all()

    leidos = {
        e.bulletin_id
        for e in db.query(BulletinEvent).filter(
            BulletinEvent.member_id   == member.id,
            BulletinEvent.bulletin_id.in_([b.id for b in bulletins] or [0]),
            BulletinEvent.status.in_(["read", "confirmed"]),
        ).all()
    }

    return JSONResponse({
        "comunicados": [{
            "id":                    b.id,
            "tipo":                  getattr(b, 'tipo', 'comunicado') or 'comunicado',
            "title":                 b.title,
            "content":               b.content or "",
            "priority":              b.priority or "info",
            "image_url":             b.image_url,
            "video_url":             getattr(b, 'video_url', None),
            "action_payload":        b.action_payload,
            "fecha_evento":          getattr(b, 'fecha_evento', None).isoformat() if getattr(b, 'fecha_evento', None) else None,
            "lugar_evento":          getattr(b, 'lugar_evento', None),
            "requiere_confirmacion": getattr(b, 'requiere_confirmacion', False),
            "genera_multa":          getattr(b, 'genera_multa', False),
            "created_at":            b.created_at.isoformat() if b.created_at else None,
            "leido":                 b.id in leidos,
            "autor":                 None,
        } for b in bulletins]
    })



# ── POST /api/comunicados/push/registrar ────────────────────
class PushSubscripcion(BaseModel):
    endpoint: str
    p256dh:   str
    auth:     str
    # zZClaud-fix-VAPID (aditivo): huella opcional del dispositivo. Devices viejos
    # y payloads que no envíen estos campos siguen funcionando: quedan NULL.
    platform:          Optional[str]  = None
    timezone:          Optional[str]  = None
    is_pwa:            Optional[bool] = None
    user_agent:        Optional[str]  = None
    permission_status: Optional[str]  = None

@router.post("/push/registrar")
async def registrar_push(
    data: PushSubscripcion,
    request: Request,
    member: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
):
    """Guarda o actualiza la suscripción push del dispositivo.

    zZClaud-fix-VAPID: persiste metadata (platform/timezone/is_pwa/user_agent/
    permission_status) de forma ADITIVA. La firma sigue siendo compatible: si el
    payload no trae esos campos, no se sobreescribe metadata previa (no se borra).
    """
    from app.models import Device

    # user_agent: preferir el del payload; si no viene, usar el del header.
    ua = data.user_agent or request.headers.get("user-agent")

    device = db.query(Device).filter(
        Device.push_endpoint == data.endpoint,
    ).first()

    if device:
        device.push_p256dh = data.p256dh
        device.push_auth   = data.auth
        device.member_id   = member.id
        device.is_active   = True
        # Aditivo: solo sobreescribir cuando el valor viene (no borrar lo previo).
        if data.platform is not None:          device.platform          = data.platform
        if data.timezone is not None:          device.timezone          = data.timezone
        if data.is_pwa is not None:            device.is_pwa            = data.is_pwa
        if data.permission_status is not None: device.permission_status = data.permission_status
        if ua:                                 device.user_agent        = ua
        device.last_seen = datetime.now(timezone.utc)
    else:
        device = Device(
            member_id     = member.id,
            push_endpoint = data.endpoint,
            push_p256dh   = data.p256dh,
            push_auth     = data.auth,
            is_active     = True,
            platform          = data.platform,
            timezone          = data.timezone,
            is_pwa            = data.is_pwa if data.is_pwa is not None else False,
            user_agent        = ua,
            permission_status = data.permission_status,
        )
        db.add(device)

    db.commit()
    return JSONResponse({"ok": True})



@router.post("/subir-imagen")
async def subir_imagen(
    imagen: UploadFile,
    member: Member = Depends(get_current_member),
):
    import uuid
    from app.utils.gcs import _get_client, BUCKET_NAME

    ext = imagen.filename.split('.')[-1].lower()
    if ext not in ('jpg','jpeg','png','gif','webp'):
        return JSONResponse({"error": "Formato no permitido"}, status_code=400)

    contenido = await imagen.read()
    nombre    = f"{uuid.uuid4().hex[:12]}.{ext}"
    blob_path = f"{member.organization_id}/comunicados/{nombre}"

    client = _get_client()
    if client:
        bucket = client.bucket(BUCKET_NAME)
        blob   = bucket.blob(blob_path)
        blob.upload_from_string(contenido, content_type=imagen.content_type)
        url = f"https://storage.googleapis.com/{BUCKET_NAME}/{blob_path}"
    else:
        return JSONResponse({"error": "GCS no configurado"}, status_code=500)

    return JSONResponse({"url": url})
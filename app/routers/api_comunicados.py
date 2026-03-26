"""
app/routers/api_comunicados.py
API Comunicados — feed del colegiado + envío desde directivos
"""

import json
import os
from datetime import datetime, timezone
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
    )
    db.add(bulletin)
    db.commit()

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

    if private_key and devices:
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
            except Exception:
                pass
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

@router.post("/push/registrar")
async def registrar_push(
    data: PushSubscripcion,
    member: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
):
    """Guarda o actualiza la suscripción push del dispositivo."""
    from app.models import Device

    device = db.query(Device).filter(
        Device.push_endpoint == data.endpoint,
    ).first()

    if device:
        device.push_p256dh = data.p256dh
        device.push_auth   = data.auth
        device.member_id   = member.id
        device.is_active   = True
    else:
        device = Device(
            organization_id = member.organization_id,
            member_id       = member.id,
            push_endpoint   = data.endpoint,
            push_p256dh     = data.p256dh,
            push_auth       = data.auth,
            is_active       = True,
        )
        db.add(device)

    db.commit()
    return JSONResponse({"ok": True})



@router.post("/subir-imagen")
async def subir_imagen(
    imagen: UploadFile,
    member: Member = Depends(get_current_member),
):
    ext = imagen.filename.split('.')[-1].lower()
    if ext not in ('jpg','jpeg','png','gif','webp'):
        return JSONResponse({"error": "Formato no permitido"}, status_code=400)
    nombre  = f"{uuid.uuid4().hex[:12]}.{ext}"
    destino = Path(f"static/uploads/comunicados/{nombre}")
    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open("wb") as f:
        shutil.copyfileobj(imagen.file, f)
    return JSONResponse({"url": f"/static/uploads/comunicados/{nombre}"})



from app.services.fomo_engine import (
    generar_fomo_automatico, FOMO_MANUALES,
    _fomo_transparencia, _fomo_comunidad,
    _fomo_tendencias, _fomo_eventos,
    registrar_envio
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
    tipo = data.get("tipo","comunidad")
    generadores = {
        "transparencia": _fomo_transparencia,
        "comunidad":     _fomo_comunidad,
        "tendencias":    _fomo_tendencias,
        "eventos":       _fomo_eventos,
    }
    fomo = await generadores.get(tipo, _fomo_comunidad)(db, member.organization_id)
    if not fomo:
        return JSONResponse({"ok":False,"mensaje":"Sin datos suficientes"})
    await manager.broadcast({
        "type":"FOMO","mensaje":fomo["mensaje"],
        "icono":fomo.get("icono","📢"),"tipo":fomo["tipo"],
        "org_id":member.organization_id,"duracion":5000,
    })
    registrar_envio(member.organization_id)
    return JSONResponse({"ok":True,"mensaje":fomo["mensaje"]})
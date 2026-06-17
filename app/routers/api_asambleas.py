"""
app/routers/api_asambleas.py — zClaude-97p (Sprint 2: Asambleas)

Endpoints del colegiado para asambleas:
  GET  /api/asambleas/{id}            → datos de la asamblea (modal)
  POST /api/asambleas/{id}/responder  → confirmar/asumir mayoría (T1/T2/T7)
  POST /api/asambleas/{id}/asistir    → marcar asistencia (GPS / QR / virtual)

Y rutas de página (sin prefijo):
  GET  /asambleas/{id}                → página que abre el modal de asamblea
  GET  /asistir/{token}               → URL universal del QR físico (pública)

Reconciliado con el esquema vivo: bulletins usa title/content/lugar_evento; la
asistencia se indexa por user_id (= members.user_id). Ver sql/zClaude97p_asambleas.sql
"""
import math
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Member
from app.routers.dashboard import get_current_member
from app.utils.templates import templates

router = APIRouter(prefix="/api/asambleas", tags=["asambleas"])
page_router = APIRouter(tags=["asambleas-ui"])


# ── Helpers ──────────────────────────────────────────────────────────────────
def haversine_metros(lat1, lng1, lat2, lng2) -> float:
    """Distancia entre dos coordenadas (grados decimales) en metros."""
    R = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    return R * (2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))


def _asamblea_row(db: Session, bulletin_id: int, organization_id: int):
    return db.execute(text("""
        SELECT id, title, content, fecha_evento, lugar_evento, modalidad,
               plantilla_botones, link_virtual, obligatoria, quorum_minimo
        FROM bulletins
        WHERE id = :id AND tipo = 'asamblea' AND organization_id = :org
    """), {"id": bulletin_id, "org": organization_id}).fetchone()


# ── GET /api/asambleas/{id} ──────────────────────────────────────────────────
@router.get("/{bulletin_id}")
async def get_asamblea(
    bulletin_id: int,
    member: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
):
    row = _asamblea_row(db, bulletin_id, member.organization_id)
    if not row:
        return JSONResponse({"error": "Asamblea no encontrada"}, status_code=404)

    mi = db.execute(text("""
        SELECT respuesta, asistio_real, tipo_asistencia
        FROM asistencia_asamblea
        WHERE bulletin_id = :bid AND user_id = :uid
    """), {"bid": bulletin_id, "uid": member.user_id}).fetchone()

    return JSONResponse({
        "id": row.id,
        "titulo": row.title,
        "contenido": row.content,
        "fecha_evento": row.fecha_evento.isoformat() if row.fecha_evento else None,
        "lugar": row.lugar_evento,
        "modalidad": row.modalidad,
        "plantilla_botones": row.plantilla_botones,
        "link_virtual": row.link_virtual,
        "obligatoria": row.obligatoria,
        "quorum_minimo": row.quorum_minimo,
        "mi_respuesta": mi.respuesta if mi else None,
        "mi_asistencia": (mi.tipo_asistencia if mi and mi.asistio_real else None),
    })


# ── POST /api/asambleas/{id}/responder ───────────────────────────────────────
class RespuestaAsamblea(BaseModel):
    respuesta: str


@router.post("/{bulletin_id}/responder")
async def responder_asamblea(
    bulletin_id: int,
    payload: RespuestaAsamblea,
    member: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
):
    validas = ['asistire', 'no_podre', 'recordarme_luego',
               'presencial', 'virtual', 'asumo_mayoria']
    if payload.respuesta not in validas:
        return JSONResponse({"error": "Respuesta inválida"}, status_code=400)

    if not _asamblea_row(db, bulletin_id, member.organization_id):
        return JSONResponse({"error": "Asamblea no encontrada"}, status_code=404)

    db.execute(text("""
        INSERT INTO asistencia_asamblea (bulletin_id, user_id, respuesta, respondida_at, created_at)
        VALUES (:bid, :uid, :resp, NOW(), NOW())
        ON CONFLICT (bulletin_id, user_id) DO UPDATE
            SET respuesta = :resp, respondida_at = NOW()
    """), {"bid": bulletin_id, "uid": member.user_id, "resp": payload.respuesta})
    db.commit()
    return JSONResponse({"ok": True, "respuesta": payload.respuesta})


# ── POST /api/asambleas/{id}/asistir ─────────────────────────────────────────
class AsistenciaGPS(BaseModel):
    tipo: str  # 'gps' | 'qr' | 'virtual_self'
    lat: Optional[float] = None
    lng: Optional[float] = None
    accuracy_m: Optional[float] = None
    qr_token: Optional[str] = None


def _registrar_asistencia(db, bid, uid, tipo_asist, metodo,
                          lat=None, lng=None, acc=None, dist=None, dudoso=False):
    db.execute(text("""
        INSERT INTO asistencia_asamblea (
            bulletin_id, user_id, asistio_real, tipo_asistencia,
            asistencia_registrada_at, asistencia_metodo,
            gps_lat, gps_lng, gps_accuracy_m, gps_distancia_sede_m, gps_dudoso, created_at
        ) VALUES (
            :bid, :uid, TRUE, :ta, NOW(), :me,
            :lat, :lng, :acc, :dist, :dud, NOW()
        )
        ON CONFLICT (bulletin_id, user_id) DO UPDATE SET
            asistio_real = TRUE, tipo_asistencia = :ta,
            asistencia_registrada_at = NOW(), asistencia_metodo = :me,
            gps_lat = :lat, gps_lng = :lng, gps_accuracy_m = :acc,
            gps_distancia_sede_m = :dist, gps_dudoso = :dud
    """), {"bid": bid, "uid": uid, "ta": tipo_asist, "me": metodo,
           "lat": lat, "lng": lng, "acc": acc, "dist": dist, "dud": dudoso})


@router.post("/{bulletin_id}/asistir")
async def marcar_asistencia(
    bulletin_id: int,
    payload: AsistenciaGPS,
    member: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
):
    asamblea = db.execute(text("""
        SELECT b.id, b.fecha_evento, b.modalidad,
               ac.sede_lat, ac.sede_lng, ac.radio_automatico_m, ac.radio_con_qr_m
        FROM bulletins b
        JOIN asambleas_config ac ON ac.organization_id = b.organization_id
        WHERE b.id = :id AND b.tipo = 'asamblea' AND b.organization_id = :org
    """), {"id": bulletin_id, "org": member.organization_id}).fetchone()

    if not asamblea:
        return JSONResponse({"error": "Asamblea no encontrada"}, status_code=404)

    # Ventana: 1 h antes hasta 2 h después del inicio
    ahora = datetime.now(timezone.utc)
    if asamblea.fecha_evento:
        if ahora < asamblea.fecha_evento - timedelta(hours=1):
            return JSONResponse({"error": "Aún no es momento de marcar asistencia"}, status_code=400)
        if ahora > asamblea.fecha_evento + timedelta(hours=2):
            return JSONResponse({"error": "Ya pasó el plazo para marcar asistencia"}, status_code=400)

    # Caso 1: virtual auto-reportado
    if payload.tipo == 'virtual_self':
        _registrar_asistencia(db, bulletin_id, member.user_id, 'virtual', 'virtual_self')
        db.commit()
        return JSONResponse({"estado": "presente", "tipo": "virtual"})

    # Caso 2: QR (zona 20-50 m verificada con el código físico)
    if payload.tipo == 'qr':
        valido = db.execute(text("""
            SELECT 1 FROM asamblea_qr_tokens
            WHERE bulletin_id = :bid AND token = :tk
              AND vigente_desde <= NOW() AND vigente_hasta >= NOW()
        """), {"bid": bulletin_id, "tk": payload.qr_token}).fetchone()
        if not valido:
            return JSONResponse({"error": "QR inválido o expirado"}, status_code=400)
        _registrar_asistencia(db, bulletin_id, member.user_id, 'presencial', 'qr')
        db.commit()
        return JSONResponse({"estado": "presente", "tipo": "presencial", "metodo": "qr"})

    # Caso 3: GPS
    if payload.tipo != 'gps' or payload.lat is None or payload.lng is None:
        return JSONResponse({"error": "GPS requiere coordenadas"}, status_code=400)

    distancia = haversine_metros(
        float(payload.lat), float(payload.lng),
        float(asamblea.sede_lat), float(asamblea.sede_lng),
    )
    radio_auto = float(asamblea.radio_automatico_m)
    radio_qr = float(asamblea.radio_con_qr_m)
    # Marca dudosa si la precisión reportada es peor que el radio automático
    dudoso = bool(payload.accuracy_m and float(payload.accuracy_m) > radio_auto)

    if distancia <= radio_auto:
        _registrar_asistencia(db, bulletin_id, member.user_id, 'presencial', 'gps',
                              lat=payload.lat, lng=payload.lng,
                              acc=payload.accuracy_m, dist=distancia, dudoso=dudoso)
        db.commit()
        return JSONResponse({"estado": "presente", "tipo": "presencial",
                             "distancia_m": round(distancia, 1)})

    if distancia <= radio_qr:
        return JSONResponse({
            "estado": "requiere_qr",
            "distancia_m": round(distancia, 1),
            "mensaje": f"Estás a {distancia:.0f} m. Escanea el QR de la entrada.",
        })

    return JSONResponse({
        "estado": "fuera_de_zona",
        "distancia_m": round(distancia, 1),
        "mensaje": f"Estás a {distancia:.0f} m de la sede.",
    })


# ── Páginas ──────────────────────────────────────────────────────────────────
@page_router.get("/asambleas/{bulletin_id}")
async def pagina_asamblea(
    bulletin_id: int,
    request: Request,
    member: Member = Depends(get_current_member),
):
    """Página que abre el modal de la asamblea (destino del push y del QR)."""
    return templates.TemplateResponse("pages/asamblea_detalle.html", {
        "request": request,
        "member": member,
        "user": member,
        "bulletin_id": bulletin_id,
        "qr_token": request.query_params.get("qr_token", ""),
        "org": getattr(request.state, "org", {}),
        "theme": getattr(request.state, "theme", None),
    })


@page_router.get("/asistir/{token}")
async def asistir_via_qr(token: str, db: Session = Depends(get_db)):
    """URL universal del QR físico (pública). Valida el token y redirige a la
    página de la asamblea con el token en query (allí se exige sesión)."""
    qr = db.execute(text("""
        SELECT bulletin_id FROM asamblea_qr_tokens
        WHERE token = :tk AND vigente_desde <= NOW() AND vigente_hasta >= NOW()
    """), {"tk": token}).fetchone()

    if not qr:
        return HTMLResponse(
            "<h1 style='font-family:sans-serif;text-align:center;margin-top:60px'>"
            "QR expirado o inválido</h1>", status_code=400)

    return RedirectResponse(f"/asambleas/{qr.bulletin_id}?qr_token={token}")

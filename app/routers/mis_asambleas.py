"""
app/routers/mis_asambleas.py — zClaude-97p (resto)

  GET /mis-asambleas       → página del colegiado (próximas + últimas pasadas)
  GET /api/mis-asambleas    → JSON {proximas: [...], pasadas: [...]}

Sin SQL nuevo: usa bulletins (tipo='asamblea') + asistencia_asamblea (user_id).
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Member
from app.routers.dashboard import get_current_member
from app.utils.templates import templates

router = APIRouter(tags=["mis-asambleas"])


def _fila(r):
    return {
        "id": r.id,
        "titulo": r.title,
        "fecha_evento": r.fecha_evento.isoformat() if r.fecha_evento else None,
        "lugar": r.lugar_evento,
        "modalidad": r.modalidad,
        "respuesta": r.respuesta,
        "asistio_real": r.asistio_real,
        "tipo_asistencia": r.tipo_asistencia,
    }


@router.get("/mis-asambleas")
async def pagina_mis_asambleas(
    request: Request,
    member: Member = Depends(get_current_member),
):
    return templates.TemplateResponse("pages/mis_asambleas.html", {
        "request": request,
        "member": member,
        "user": member,
        "org": getattr(request.state, "org", {}),
        "theme": getattr(request.state, "theme", None),
    })


@router.get("/api/mis-asambleas")
async def api_mis_asambleas(
    member: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
):
    params = {"uid": member.user_id, "org": member.organization_id}

    proximas = db.execute(text("""
        SELECT b.id, b.title, b.fecha_evento, b.lugar_evento, b.modalidad,
               aa.respuesta, aa.asistio_real, aa.tipo_asistencia
        FROM bulletins b
        LEFT JOIN asistencia_asamblea aa
               ON aa.bulletin_id = b.id AND aa.user_id = :uid
        WHERE b.tipo = 'asamblea' AND b.organization_id = :org
          AND b.fecha_evento > NOW()
        ORDER BY b.fecha_evento ASC
    """), params).fetchall()

    pasadas = db.execute(text("""
        SELECT b.id, b.title, b.fecha_evento, b.lugar_evento, b.modalidad,
               aa.respuesta, aa.asistio_real, aa.tipo_asistencia
        FROM bulletins b
        LEFT JOIN asistencia_asamblea aa
               ON aa.bulletin_id = b.id AND aa.user_id = :uid
        WHERE b.tipo = 'asamblea' AND b.organization_id = :org
          AND b.fecha_evento <= NOW()
        ORDER BY b.fecha_evento DESC
        LIMIT 5
    """), params).fetchall()

    return JSONResponse({
        "proximas": [_fila(r) for r in proximas],
        "pasadas": [_fila(r) for r in pasadas],
    })

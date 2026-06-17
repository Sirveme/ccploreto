"""
app/routers/asambleas_admin.py — zClaude-97p (Sprint 2: panel admin de asistencia)

  GET  /admin/asambleas/{id}/asistencia          → página (resumen + tabla)
  GET  /admin/asambleas/{id}/asistencia/data      → JSON (resumen + filas, búsqueda)
  POST /admin/asambleas/{id}/asistencia/manual    → marcar asistencia manual
  GET  /admin/asambleas/{id}/asistencia/export    → CSV (Excel)

Roles con acceso (marcado manual incluido): decano, admin, secretaria, sote, superadmin.
"""
import csv
import io
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Member
from app.routers.dashboard import get_current_member
from app.utils.templates import templates

router = APIRouter(prefix="/admin/asambleas", tags=["asambleas-admin"])

ROLES_ADMIN = ("decano", "admin", "secretaria", "superadmin", "sote")


def _check_rol(member: Member):
    return member.role in ROLES_ADMIN


def _asamblea(db: Session, bid: int, org: int):
    return db.execute(text("""
        SELECT id, title, fecha_evento, lugar_evento, modalidad, plantilla_botones, quorum_minimo
        FROM bulletins
        WHERE id = :id AND tipo = 'asamblea' AND organization_id = :org
    """), {"id": bid, "org": org}).fetchone()


def _resumen(db: Session, bid: int, org: int) -> dict:
    r = db.execute(text("""
        SELECT
          COUNT(*) FILTER (WHERE respuesta IS NOT NULL)                              AS respondieron,
          COUNT(*) FILTER (WHERE respuesta IN ('asistire','presencial','virtual'))  AS confirmados,
          COUNT(*) FILTER (WHERE respuesta = 'asumo_mayoria')                        AS asumen_mayoria,
          COUNT(*) FILTER (WHERE respuesta = 'no_podre')                             AS no_podran,
          COUNT(*) FILTER (WHERE asistio_real)                                       AS asistieron,
          COUNT(*) FILTER (WHERE asistio_real AND tipo_asistencia = 'presencial')    AS presenciales,
          COUNT(*) FILTER (WHERE asistio_real AND tipo_asistencia = 'virtual')       AS virtuales,
          COUNT(*) FILTER (WHERE gps_dudoso)                                         AS dudosos
        FROM asistencia_asamblea WHERE bulletin_id = :bid
    """), {"bid": bid}).fetchone()
    total = db.execute(text("""
        SELECT COUNT(DISTINCT m.user_id)
        FROM members m JOIN colegiados c ON c.member_id = m.id
        WHERE m.organization_id = :org AND m.is_active = TRUE
          AND c.condicion IN ('habil','vitalicio')
    """), {"org": org}).scalar() or 0
    return {
        "total_habilitados": total,
        "respondieron": r.respondieron or 0,
        "confirmados": r.confirmados or 0,
        "asumen_mayoria": r.asumen_mayoria or 0,
        "no_podran": r.no_podran or 0,
        "no_respondieron": max(0, total - (r.respondieron or 0)),
        "asistieron": r.asistieron or 0,
        "presenciales": r.presenciales or 0,
        "virtuales": r.virtuales or 0,
        "dudosos": r.dudosos or 0,
    }


@router.get("/{bulletin_id}/asistencia")
async def pagina_asistencia(
    bulletin_id: int,
    request: Request,
    member: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
):
    if not _check_rol(member):
        return JSONResponse({"error": "Sin permiso"}, status_code=403)
    a = _asamblea(db, bulletin_id, member.organization_id)
    if not a:
        return JSONResponse({"error": "Asamblea no encontrada"}, status_code=404)
    return templates.TemplateResponse("pages/admin/asamblea_asistencia.html", {
        "request": request,
        "member": member,
        "bulletin_id": bulletin_id,
        "titulo": a.title,
        "lugar": a.lugar_evento,
        "quorum_minimo": a.quorum_minimo or 0,
        "fecha_evento": a.fecha_evento.isoformat() if a.fecha_evento else "",
        "org": getattr(request.state, "org", {}),
        "theme": getattr(request.state, "theme", None),
    })


@router.get("/{bulletin_id}/asistencia/data")
async def asistencia_data(
    bulletin_id: int,
    q: str = "",
    estado: str = "",
    member: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
):
    if not _check_rol(member):
        return JSONResponse({"error": "Sin permiso"}, status_code=403)
    org = member.organization_id
    if not _asamblea(db, bulletin_id, org):
        return JSONResponse({"error": "Asamblea no encontrada"}, status_code=404)

    params = {"bid": bulletin_id, "org": org}
    where_extra = ""
    if q:
        where_extra += " AND (c.apellidos_nombres ILIKE :q OR c.dni ILIKE :q OR c.codigo_matricula ILIKE :q)"
        params["q"] = f"%{q}%"
    if estado == "asistieron":
        where_extra += " AND aa.asistio_real = TRUE"
    elif estado == "respondieron":
        where_extra += " AND aa.respuesta IS NOT NULL"
    elif estado == "sin_responder":
        where_extra += " AND aa.respuesta IS NULL AND aa.asistio_real IS NOT TRUE"

    # Sin búsqueda: solo quienes interactuaron (más liviano). Con búsqueda: cualquiera.
    join_filter = where_extra
    if not q and not estado:
        join_filter += " AND (aa.respuesta IS NOT NULL OR aa.asistio_real = TRUE)"

    rows = db.execute(text(f"""
        SELECT c.id AS colegiado_id, c.apellidos_nombres, c.dni, c.codigo_matricula,
               c.condicion, m.user_id,
               aa.respuesta, aa.respondida_at,
               aa.asistio_real, aa.tipo_asistencia, aa.asistencia_metodo,
               aa.gps_distancia_sede_m, aa.gps_dudoso, aa.asistencia_registrada_at
        FROM colegiados c
        JOIN members m ON m.id = c.member_id
        LEFT JOIN asistencia_asamblea aa ON aa.bulletin_id = :bid AND aa.user_id = m.user_id
        WHERE c.organization_id = :org AND m.is_active = TRUE
          AND c.condicion IN ('habil','vitalicio')
          {join_filter}
        ORDER BY aa.asistio_real DESC NULLS LAST, c.apellidos_nombres ASC
        LIMIT 500
    """), params).fetchall()

    return JSONResponse({
        "resumen": _resumen(db, bulletin_id, org),
        "filas": [{
            "colegiado_id": r.colegiado_id,
            "nombre": r.apellidos_nombres,
            "dni": r.dni,
            "matricula": r.codigo_matricula,
            "condicion": r.condicion,
            "user_id": r.user_id,
            "respuesta": r.respuesta,
            "asistio_real": r.asistio_real,
            "tipo_asistencia": r.tipo_asistencia,
            "metodo": r.asistencia_metodo,
            "distancia_m": float(r.gps_distancia_sede_m) if r.gps_distancia_sede_m is not None else None,
            "dudoso": r.gps_dudoso,
        } for r in rows],
    })


class MarcadoManual(BaseModel):
    colegiado_id: int
    tipo_asistencia: str = "presencial"  # 'presencial' | 'virtual'
    notas: str = ""


@router.post("/{bulletin_id}/asistencia/manual")
async def marcar_manual(
    bulletin_id: int,
    payload: MarcadoManual,
    member: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
):
    if not _check_rol(member):
        return JSONResponse({"error": "Sin permiso"}, status_code=403)
    org = member.organization_id
    if not _asamblea(db, bulletin_id, org):
        return JSONResponse({"error": "Asamblea no encontrada"}, status_code=404)
    if payload.tipo_asistencia not in ("presencial", "virtual"):
        return JSONResponse({"error": "Tipo inválido"}, status_code=400)

    col = db.execute(text("""
        SELECT m.user_id FROM colegiados c
        JOIN members m ON m.id = c.member_id
        WHERE c.id = :cid AND c.organization_id = :org AND m.user_id IS NOT NULL
    """), {"cid": payload.colegiado_id, "org": org}).fetchone()
    if not col:
        return JSONResponse({"error": "Colegiado sin usuario vinculado"}, status_code=400)

    db.execute(text("""
        INSERT INTO asistencia_asamblea (
            bulletin_id, user_id, asistio_real, tipo_asistencia,
            asistencia_registrada_at, asistencia_metodo, registrado_por_user_id, notas, created_at
        ) VALUES (:bid, :uid, TRUE, :ta, NOW(), 'manual', :reg, :notas, NOW())
        ON CONFLICT (bulletin_id, user_id) DO UPDATE SET
            asistio_real = TRUE, tipo_asistencia = :ta,
            asistencia_registrada_at = NOW(), asistencia_metodo = 'manual',
            registrado_por_user_id = :reg, notas = :notas
    """), {"bid": bulletin_id, "uid": col.user_id, "ta": payload.tipo_asistencia,
           "reg": member.user_id, "notas": payload.notas or None})
    db.commit()
    return JSONResponse({"ok": True})


@router.get("/{bulletin_id}/asistencia/export")
async def exportar_asistencia(
    bulletin_id: int,
    member: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
):
    if not _check_rol(member):
        return JSONResponse({"error": "Sin permiso"}, status_code=403)
    org = member.organization_id
    a = _asamblea(db, bulletin_id, org)
    if not a:
        return JSONResponse({"error": "Asamblea no encontrada"}, status_code=404)

    rows = db.execute(text("""
        SELECT c.apellidos_nombres, c.dni, c.codigo_matricula, c.condicion,
               aa.respuesta, aa.asistio_real, aa.tipo_asistencia, aa.asistencia_metodo,
               aa.gps_distancia_sede_m, aa.gps_dudoso, aa.asistencia_registrada_at
        FROM colegiados c
        JOIN members m ON m.id = c.member_id
        LEFT JOIN asistencia_asamblea aa ON aa.bulletin_id = :bid AND aa.user_id = m.user_id
        WHERE c.organization_id = :org AND m.is_active = TRUE
          AND c.condicion IN ('habil','vitalicio')
          AND (aa.respuesta IS NOT NULL OR aa.asistio_real = TRUE)
        ORDER BY c.apellidos_nombres ASC
    """), {"bid": bulletin_id, "org": org}).fetchall()

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Apellidos y Nombres", "DNI", "Matrícula", "Condición",
                "Respuesta", "Asistió", "Tipo", "Método", "Distancia (m)", "Dudoso", "Registrado"])
    for r in rows:
        w.writerow([
            r.apellidos_nombres, r.dni, r.codigo_matricula, r.condicion,
            r.respuesta or "", "SÍ" if r.asistio_real else "", r.tipo_asistencia or "",
            r.asistencia_metodo or "",
            f"{float(r.gps_distancia_sede_m):.0f}" if r.gps_distancia_sede_m is not None else "",
            "SÍ" if r.gps_dudoso else "",
            r.asistencia_registrada_at.strftime("%Y-%m-%d %H:%M") if r.asistencia_registrada_at else "",
        ])
    buf.seek(0)
    fname = f"asistencia_asamblea_{bulletin_id}_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )

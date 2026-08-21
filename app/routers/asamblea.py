"""
app/routers/asamblea.py
=======================
Asistencia a asamblea: mesa de captura + lista pública + proyección + export.
Alcance estricto: solo asistencia. Robusto para 3 mesas en paralelo.
"""
import base64

from fastapi import APIRouter, Request, Depends, HTTPException, Body
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Member, Colegiado, Organization
from app.routers.dashboard import get_current_member
from app.services import asamblea_service as svc
from app.utils.gcs import upload_asamblea_foto
from app.utils.templates import templates

router = APIRouter(prefix="/asamblea", tags=["Asamblea"])

# Personal de mesa (Morelia entra con emisor_carnes; Anggie por su rol).
ROLES_MESA = ("admin", "decano", "secretaria", "sote", "emisor_carnes")
ROLES_CERRAR = ("admin", "decano")


def require_mesa(current_member: Member = Depends(get_current_member)) -> Member:
    if current_member.role not in ROLES_MESA:
        raise HTTPException(403, "Acceso restringido a la mesa de asistencia")
    return current_member


def _org_id(request: Request):
    org = getattr(request.state, "org", None)
    if not org or not org.get("id"):
        raise HTTPException(500, "Organización no resuelta por el middleware")
    return org["id"]


# ─────────────────────────── MESA (interno) ───────────────────────────
@router.get("/mesa", response_class=HTMLResponse)
async def mesa(request: Request, db: Session = Depends(get_db),
               member: Member = Depends(require_mesa)):
    org_id = _org_id(request)
    asamblea = svc.asamblea_abierta(db, org_id)
    total = svc.total_asistentes(db, asamblea.id) if asamblea else 0
    return templates.TemplateResponse("pages/asamblea/mesa.html", {
        "request": request, "asamblea": asamblea, "total": total,
    })


@router.get("/api/buscar")
async def api_buscar(request: Request, q: str = "", db: Session = Depends(get_db),
                     member: Member = Depends(require_mesa)):
    org_id = _org_id(request)
    asamblea = svc.asamblea_abierta(db, org_id)
    if not asamblea:
        raise HTTPException(400, "No hay una asamblea abierta")
    resultados = []
    for c in svc.buscar_colegiado(db, org_id, q):
        reg = svc.estado_registro(db, asamblea.id, c.id)
        resultados.append({
            "id": c.id,
            "nombre": c.apellidos_nombres,
            "matricula": c.codigo_matricula,
            "condicion": (c.condicion or "").upper(),
            "registrado": reg is not None,
            "hora": reg.hora_registro.strftime("%H:%M") if reg else None,
        })
    return {"asamblea_id": asamblea.id, "resultados": resultados}


@router.post("/api/registrar")
async def api_registrar(request: Request, body: dict = Body(default={}),
                        db: Session = Depends(get_db),
                        member: Member = Depends(require_mesa)):
    org_id = _org_id(request)
    asamblea = svc.asamblea_abierta(db, org_id)
    if not asamblea:
        raise HTTPException(400, "No hay una asamblea abierta")
    colegiado_id = body.get("colegiado_id")
    if not colegiado_id:
        raise HTTPException(400, "Falta el colegiado")
    col = db.query(Colegiado).filter(Colegiado.id == colegiado_id,
                                     Colegiado.organization_id == org_id).first()
    if not col:
        raise HTTPException(404, "Colegiado no encontrado en el padrón")

    # Foto OPCIONAL (dataURL base64). Si falla la subida, NO bloquea el registro.
    foto_url = None
    foto = body.get("foto")
    if foto and isinstance(foto, str) and foto.startswith("data:"):
        try:
            cabecera, datos = foto.split(",", 1)
            ctype = cabecera.split(";")[0].replace("data:", "") or "image/jpeg"
            foto_url = upload_asamblea_foto(base64.b64decode(datos), ctype, org_id, asamblea.id)
        except Exception:
            foto_url = None

    res = svc.registrar(db, org_id, asamblea.id, colegiado_id, member.id, foto_url)
    return {
        "status": res["status"],
        "hora": res["hora"].strftime("%H:%M") if res.get("hora") else None,
        "total": res["total"],
        "nombre": col.apellidos_nombres,
        "matricula": col.codigo_matricula,
    }


@router.post("/{asamblea_id}/cerrar")
async def cerrar(asamblea_id: int, request: Request, db: Session = Depends(get_db),
                 member: Member = Depends(get_current_member)):
    if member.role not in ROLES_CERRAR:
        raise HTTPException(403, "Solo Administrador o Decano pueden cerrar la asamblea")
    org_id = _org_id(request)
    asamblea = svc.get_asamblea(db, org_id, asamblea_id)
    if not asamblea:
        raise HTTPException(404, "Asamblea no encontrada")
    asamblea.estado = "cerrada"
    db.commit()
    return {"ok": True, "estado": asamblea.estado}


# ───────────────────── ESTADO / LISTA (contadores) ─────────────────────
@router.get("/api/estado/{asamblea_id}")
async def api_estado(asamblea_id: int, db: Session = Depends(get_db)):
    """Solo el total (ligero) — todas las mesas juntas. Para contadores en vivo."""
    return {"total": svc.total_asistentes(db, asamblea_id)}


@router.get("/api/lista/{asamblea_id}")
async def api_lista(asamblea_id: int, db: Session = Depends(get_db)):
    """Lista pública: SOLO nombre + matrícula."""
    asistentes = svc.lista_publica(db, asamblea_id)
    return {"total": len(asistentes), "asistentes": asistentes}


# ─────────────────────── PÚBLICO (sin login) ───────────────────────
@router.get("/publica/{asamblea_id}", response_class=HTMLResponse)
async def publica(asamblea_id: int, request: Request, db: Session = Depends(get_db)):
    org_dict = getattr(request.state, "org", None)
    org_id = org_dict["id"] if org_dict and org_dict.get("id") else None
    asamblea = svc.get_asamblea(db, org_id, asamblea_id) if org_id else None
    return templates.TemplateResponse("pages/asamblea/publica.html", {
        "request": request, "asamblea": asamblea, "asamblea_id": asamblea_id,
    })


@router.get("/proyeccion/{asamblea_id}", response_class=HTMLResponse)
async def proyeccion(asamblea_id: int, request: Request, db: Session = Depends(get_db)):
    org_dict = getattr(request.state, "org", None)
    org_id = org_dict["id"] if org_dict and org_dict.get("id") else None
    asamblea = svc.get_asamblea(db, org_id, asamblea_id) if org_id else None
    if not asamblea:
        raise HTTPException(404, "Asamblea no encontrada")
    return templates.TemplateResponse("pages/asamblea/proyeccion.html", {
        "request": request, "asamblea": asamblea, "asamblea_id": asamblea_id,
    })


# ─────────────────────────── EXPORT (interno) ───────────────────────────
@router.get("/export/{asamblea_id}.xlsx")
async def export_xlsx(asamblea_id: int, request: Request, db: Session = Depends(get_db),
                      member: Member = Depends(require_mesa)):
    from io import BytesIO
    from openpyxl import Workbook
    from openpyxl.styles import Font

    org_id = _org_id(request)
    asamblea = svc.get_asamblea(db, org_id, asamblea_id)
    if not asamblea:
        raise HTTPException(404, "Asamblea no encontrada")

    wb = Workbook()
    ws = wb.active
    ws.title = "Asistencia"
    encabezados = ["N°", "Apellidos y Nombres", "Matrícula", "Condición", "Hora de registro"]
    ws.append(encabezados)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for i, r in enumerate(svc.filas_export(db, asamblea_id), start=1):
        hora = r[3].strftime("%d/%m/%Y %H:%M:%S") if r[3] else ""
        ws.append([i, r[0], r[1], (r[2] or "").upper(), hora])
    ws.append([])
    ws.append(["", "TOTAL", svc.total_asistentes(db, asamblea_id)])

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    fname = "asistencia_%s.xlsx" % asamblea.fecha
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="%s"' % fname},
    )

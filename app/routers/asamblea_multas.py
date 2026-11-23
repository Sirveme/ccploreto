"""
app/routers/asamblea_multas.py — Asistencia y multas por inasistencia (tanda 10).

Completa el módulo de Asambleas (mesa en asamblea.py). La lógica vive en
app/services/multas_asamblea_service.py.

Roles:
  - Ver la pantalla y la asistencia: admin, sote, secretaria, decano.
  - Marcar asistentes: los de la mesa (admin, decano, secretaria, sote, emisor_carnes, cajero).
  - Desmarcar / importar desde Excel: admin, sote, secretaria, decano.
  - Vista previa, generar, justificar y deshacer: SOLO admin y sote.
  - Cerrar la asamblea: la ruta existente /asamblea/{id}/cerrar (admin, decano).
"""
from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Member
from app.routers.dashboard import get_current_member
from app.services import asamblea_service as asvc
from app.services import multas_asamblea_service as M
from app.utils.sesion_api import exigir_roles
from app.utils.templates import templates

router = APIRouter(prefix="/api/asamblea-multas", tags=["asamblea-multas"])
page_router = APIRouter(tags=["asamblea-multas-ui"])

ROLES_VER = ("admin", "sote", "secretaria", "decano")
ROLES_MESA = ("admin", "decano", "secretaria", "sote", "emisor_carnes", "cajero")
ROLES_CORREGIR = ("admin", "sote", "secretaria", "decano")
ROLES_MULTA = ("admin", "sote")


def _org_id(request: Request) -> int:
    org = getattr(request.state, "org", None) or {}
    return int(org.get("id") or 1)


def _run(fn, *a, **k):
    try:
        return fn(*a, **k)
    except M.MultaError as e:
        raise HTTPException(e.status, e.detalle)


@page_router.get("/admin/asambleas/multas", response_class=HTMLResponse)
async def pagina(request: Request, member: Member = Depends(get_current_member)):
    if member.role not in ROLES_VER:
        raise HTTPException(403, "Sin acceso a Asistencia y multas")
    return templates.TemplateResponse("pages/asamblea/multas.html", {
        "request": request, "puede_multar": member.role in ROLES_MULTA,
        "puede_corregir": member.role in ROLES_CORREGIR, "puede_cerrar": member.role in ("admin", "decano"),
    })


@router.get("/asambleas")
async def listar(request: Request, db: Session = Depends(get_db), member: Member = Depends(exigir_roles(*ROLES_VER))):
    rows = db.execute(text("""SELECT a.id, a.fecha, a.titulo, a.estado,
                (SELECT count(*) FROM asamblea_asistencia x WHERE x.asamblea_id=a.id) asistentes
            FROM asambleas a WHERE a.organization_id=:o ORDER BY a.fecha DESC, a.id DESC"""), {"o": _org_id(request)}).fetchall()
    out = []
    for r in rows:
        lote = M.lote_activo(db, r.id)
        out.append({"id": r.id, "fecha": r.fecha.isoformat(), "titulo": r.titulo, "estado": r.estado,
                    "asistentes": int(r.asistentes), "lote": lote.lote if lote else None})
    return {"asambleas": out}


@router.get("/{asamblea_id}/asistencia")
async def asistencia(asamblea_id: int, request: Request, db: Session = Depends(get_db),
                     member: Member = Depends(exigir_roles(*ROLES_VER))):
    org = _org_id(request)
    a = _run(M.asamblea, db, org, asamblea_id)
    return {"asamblea": {"id": a.id, "fecha": a.fecha.isoformat(), "titulo": a.titulo, "estado": a.estado},
            "asistentes": M.lista_asistencia(db, org, asamblea_id), "lote": M.estado_lote(db, org, asamblea_id)}


@router.get("/{asamblea_id}/buscar")
async def buscar(asamblea_id: int, request: Request, q: str = "", db: Session = Depends(get_db),
                 member: Member = Depends(exigir_roles(*ROLES_MESA))):
    org = _org_id(request)
    _run(M.asamblea, db, org, asamblea_id)
    res = []
    for c in asvc.buscar_colegiado(db, org, q):
        res.append({"id": c.id, "matricula": c.codigo_matricula, "nombre": c.apellidos_nombres, "condicion": c.condicion,
                    "presente": asvc.estado_registro(db, asamblea_id, c.id) is not None})
    return {"resultados": res}


@router.post("/{asamblea_id}/asistencia")
async def marcar(asamblea_id: int, request: Request, body: dict = Body(default={}), db: Session = Depends(get_db),
                 member: Member = Depends(exigir_roles(*ROLES_MESA))):
    presente = bool(body.get("presente", True))
    if not presente and member.role not in ROLES_CORREGIR:
        raise HTTPException(403, "Quitar a un asistente lo hace Secretaría, Decano o Administración")
    cid = body.get("colegiado_id")
    if not cid:
        raise HTTPException(400, "Falta el colegiado")
    total = _run(M.marcar, db, _org_id(request), asamblea_id, int(cid), presente, member.id)
    return {"ok": True, "total": total}


@router.post("/{asamblea_id}/asistencia/importar")
async def importar(asamblea_id: int, request: Request, archivo: UploadFile = File(...), aplicar: bool = Form(False),
                   db: Session = Depends(get_db), member: Member = Depends(exigir_roles(*ROLES_CORREGIR))):
    contenido = await archivo.read()
    if len(contenido) > 5 * 1024 * 1024:
        raise HTTPException(400, "El archivo supera 5 MB")
    return _run(M.importar_excel, db, _org_id(request), asamblea_id, contenido, member.id, aplicar)


@router.get("/{asamblea_id}/vista-previa")
async def vista_previa(asamblea_id: int, request: Request, db: Session = Depends(get_db),
                       member: Member = Depends(exigir_roles(*ROLES_MULTA))):
    return _run(M.previsualizar, db, _org_id(request), asamblea_id)


@router.post("/{asamblea_id}/generar")
async def generar(asamblea_id: int, request: Request, body: dict = Body(default={}), db: Session = Depends(get_db),
                  member: Member = Depends(exigir_roles(*ROLES_MULTA))):
    if (body.get("confirmacion") or "").strip().upper() != "GENERAR":
        raise HTTPException(400, "Confirme escribiendo GENERAR")
    return _run(M.generar, db, _org_id(request), asamblea_id, body.get("token"), member.user_id, member.id)


@router.post("/{asamblea_id}/justificar")
async def justificar(asamblea_id: int, request: Request, body: dict = Body(default={}), db: Session = Depends(get_db),
                     member: Member = Depends(exigir_roles(*ROLES_MULTA))):
    cid = body.get("colegiado_id")
    if not cid:
        raise HTTPException(400, "Falta el colegiado")
    return _run(M.justificar, db, _org_id(request), asamblea_id, int(cid), body.get("motivo"), member.user_id, member.id)


@router.post("/{asamblea_id}/deshacer")
async def deshacer(asamblea_id: int, request: Request, body: dict = Body(default={}), db: Session = Depends(get_db),
                   member: Member = Depends(exigir_roles(*ROLES_MULTA))):
    if (body.get("confirmacion") or "").strip().upper() != "DESHACER":
        raise HTTPException(400, "Confirme escribiendo DESHACER")
    return _run(M.deshacer, db, _org_id(request), asamblea_id, body.get("motivo"), member.user_id, member.id)


@router.get("/{asamblea_id}/multas")
async def multas(asamblea_id: int, request: Request, db: Session = Depends(get_db),
                 member: Member = Depends(exigir_roles(*ROLES_MULTA))):
    """Multas del lote vigente (para justificar una)."""
    org = _org_id(request)
    _run(M.asamblea, db, org, asamblea_id)
    rows = db.execute(text("""SELECT d.colegiado_id, c.codigo_matricula mat, c.apellidos_nombres nombre, d.amount, d.balance, d.status, d.estado_gestion
            FROM debts d JOIN colegiados c ON c.id=d.colegiado_id
            WHERE d.lote_migracion LIKE :p AND coalesce(d.estado_gestion,'') <> 'anulada' ORDER BY c.apellidos_nombres"""),
                      {"p": "%s%d-%%" % (M.PREFIJO_LOTE, asamblea_id)}).fetchall()
    return {"multas": [{"colegiado_id": r.colegiado_id, "matricula": r.mat, "nombre": r.nombre, "monto": float(r.amount),
                        "saldo": float(r.balance), "estado": r.estado_gestion if r.estado_gestion == "justificada" else r.status} for r in rows]}

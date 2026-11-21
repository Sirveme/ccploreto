"""
Router: Conciliación de deuda por acta con firmas
app/routers/conciliacion_deuda.py

API   /api/conciliacion-deuda/...
Página /conciliacion-deuda/actas   (bandeja "Actas pendientes de firma")

Solo los ROLES FIRMANTES (parámetro conciliacion.roles_firmantes; nunca sote)
pueden ver la vista previa, crear y firmar. Toda la lógica vive en
app/services/conciliacion_deuda_service.py.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Member
from app.routers.dashboard import get_current_member
from app.services import conciliacion_deuda_service as svc
from app.utils.sesion_api import sesion_api
from app.utils.templates import templates

router = APIRouter(prefix="/api/conciliacion-deuda", tags=["conciliacion-deuda"])
page_router = APIRouter(tags=["conciliacion-deuda"])


def _org(member: Member) -> int:
    return member.organization_id or 1


def _es_firmante(db: Session, member: Member) -> bool:
    rol = (member.role or "").lower()
    return rol != "sote" and rol in svc.get_config(db, _org(member))["roles_firmantes"]


def firmante(member: Member = Depends(sesion_api), db: Session = Depends(get_db)) -> Member:
    """Sesión válida (401) y rol firmante (403)."""
    if not _es_firmante(db, member):
        raise HTTPException(403, "Solo los roles firmantes de conciliación pueden usar esta función.")
    return member


def _http(e: svc.ErrorConciliacion):
    return HTTPException(e.codigo, e.mensaje)


class CrearActaIn(BaseModel):
    colegiado_id: int
    monto_fijado: float
    motivo: str
    documento_url: Optional[str] = None


class FirmarIn(BaseModel):
    decision: str                      # 'aprobar' | 'rechazar'
    comentario: Optional[str] = None


@router.get("/config")
def config(member: Member = Depends(sesion_api), db: Session = Depends(get_db)):
    """Para que las pantallas sepan si deben mostrar el botón. No expone datos."""
    cfg = svc.get_config(db, _org(member))
    puedo = _es_firmante(db, member)
    return {**cfg, "puedo_firmar": puedo, "mi_rol": member.role,
            "pendientes_mi_firma": svc.contar_pendientes_mi_firma(db, member) if puedo else 0}


@router.get("/actas/{acta_id}/pdf")
def pdf_acta(acta_id: int, member: Member = Depends(firmante), db: Session = Depends(get_db)):
    """PDF del acta ejecutada (número, colegiado, deuda antes/después, motivo, detalle y firmas)."""
    from fastapi.responses import Response
    try:
        contenido, nombre = svc.generar_pdf_acta(db, _org(member), acta_id)
    except svc.ErrorConciliacion as e:
        raise _http(e)
    return Response(content=contenido, media_type="application/pdf",
                    headers={"Content-Disposition": 'attachment; filename="%s"' % nombre})


@router.get("/preview")
def preview(colegiado_id: int, monto_fijado: float,
            member: Member = Depends(firmante), db: Session = Depends(get_db)):
    """Vista previa: deudas a tocar, deuda antes/después y condición antes/después. No escribe."""
    try:
        return {"ok": True, **svc.previsualizar(db, colegiado_id, monto_fijado),
                **svc.get_config(db, _org(member))}
    except svc.ErrorConciliacion as e:
        raise _http(e)


@router.get("/deuda/{colegiado_id}")
def deuda(colegiado_id: int, member: Member = Depends(firmante), db: Session = Depends(get_db)):
    """Deuda total única (la que usa la habilidad) y si tiene plan activo."""
    from app.models import Colegiado
    col = db.query(Colegiado).filter(Colegiado.id == colegiado_id).first()
    if not col:
        raise HTTPException(404, "Colegiado no encontrado")
    det = svc._detalle_deuda(db, col.id, col.organization_id)
    return {"colegiado_id": col.id, "nombre": col.apellidos_nombres, "matricula": col.codigo_matricula,
            "deuda_total": det["total"], "condicion": col.condicion, "tiene_plan_activo": bool(det["plan_activo"])}


@router.post("/actas")
def crear(datos: CrearActaIn, member: Member = Depends(firmante), db: Session = Depends(get_db)):
    try:
        return svc.crear_acta(db, member, datos.colegiado_id, datos.monto_fijado, datos.motivo, datos.documento_url)
    except svc.ErrorConciliacion as e:
        raise _http(e)


@router.get("/actas")
def listar(estado: str = "pendiente", colegiado_id: Optional[int] = None,
           member: Member = Depends(firmante), db: Session = Depends(get_db)):
    return {"actas": svc.listar_actas(db, _org(member), estado=estado, colegiado_id=colegiado_id, member=member),
            **svc.get_config(db, _org(member))}


@router.post("/actas/{acta_id}/firmar")
def firmar(acta_id: int, datos: FirmarIn, member: Member = Depends(firmante), db: Session = Depends(get_db)):
    try:
        return svc.firmar_acta(db, member, acta_id, datos.decision, datos.comentario)
    except svc.ErrorConciliacion as e:
        raise _http(e)


# ── Página: bandeja de actas ────────────────────────────────────────────────
@page_router.get("/conciliacion-deuda/actas", response_class=HTMLResponse)
async def pagina_actas(request: Request, member: Member = Depends(get_current_member),
                       db: Session = Depends(get_db)):
    if not _es_firmante(db, member):
        raise HTTPException(403, "Solo los roles firmantes de conciliación pueden ver esta bandeja.")
    return templates.TemplateResponse("pages/conciliacion_actas.html", {
        "request": request, "rol": member.role,
        "org": getattr(request.state, "org", None), "theme": getattr(request.state, "theme", None),
    })

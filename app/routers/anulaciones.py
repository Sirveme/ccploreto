"""
app/routers/anulaciones.py
Vista del Administrador para el flujo de dos pasos de anulación / Notas de Crédito.
  GET  /admin/anulaciones                 → pendientes + historial (con filtros)
  POST /admin/anulaciones/{id}/aprobar    → emite la NC (vía anulacion_service) y aprueba
  POST /admin/anulaciones/{id}/rechazar   → rechaza la solicitud (+ nota)

El historial usa anulacion_service.listar_historial_nc (reutilizado por /decano).
NO reimplementa emitir_nota_credito.
"""

from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Member
from app.routers.dashboard import get_current_member
from app.utils.templates import templates
from app.services.anulacion_service import (
    listar_historial_nc, aprobar_solicitud, rechazar_solicitud,
)

router = APIRouter(prefix="/admin/anulaciones", tags=["anulaciones"])

ORG_CCPL = 1
_ROLES_GESTION = ("admin", "sote")

MOTIVOS_09 = {
    "01": "Anulación de la operación", "02": "Anulación por error en RUC",
    "03": "Corrección por error en descripción", "04": "Descuento global",
    "05": "Descuento por ítem", "06": "Devolución total", "07": "Devolución parcial",
}


def require_gestion(current_member: Member = Depends(get_current_member)) -> Member:
    if current_member is None or current_member.role not in _ROLES_GESTION:
        raise HTTPException(status_code=403, detail="Solo el Administrador puede gestionar anulaciones")
    return current_member


@router.get("", response_class=HTMLResponse)
async def anulaciones_page(
    request: Request,
    fecha_desde: str = None, fecha_hasta: str = None,
    motivo: str = None, q_comprobante: str = None, q_colegiado: str = None,
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_gestion),
):
    pend = db.execute(text("""
        SELECT sa.id, sa.monto, sa.es_parcial, sa.motivo_sunat, sa.motivo_interno,
               sa.solicitante_nombre, sa.created_at,
               cmp.serie AS c_serie, cmp.numero AS c_numero, cmp.tipo AS c_tipo, cmp.total AS c_total,
               col.apellidos_nombres, col.dni
        FROM solicitud_anulacion sa
        LEFT JOIN comprobantes cmp ON cmp.id = sa.comprobante_id
        LEFT JOIN colegiados col ON col.id = sa.colegiado_id
        WHERE sa.organization_id = :org AND sa.estado = 'pendiente'
        ORDER BY sa.created_at ASC
    """), {"org": ORG_CCPL}).fetchall()

    _tn = {"01": "Factura", "03": "Boleta"}
    pendientes = [{
        "id": p.id,
        "monto": float(p.monto) if p.monto is not None else float(p.c_total or 0),
        "es_parcial": p.es_parcial,
        "motivo_sunat": p.motivo_sunat,
        "motivo_label": MOTIVOS_09.get(p.motivo_sunat, p.motivo_sunat),
        "motivo_interno": p.motivo_interno,
        "solicitante": p.solicitante_nombre or "—",
        "fecha": p.created_at,
        "comprobante": (f"{_tn.get(p.c_tipo, p.c_tipo)} {p.c_serie}-{p.c_numero}" if p.c_serie else "—"),
        "colegiado": p.apellidos_nombres or "—",
        "dni": p.dni or "—",
    } for p in pend]

    historial = listar_historial_nc(
        db, ORG_CCPL, fecha_desde=fecha_desde or None, fecha_hasta=fecha_hasta or None,
        motivo=motivo or None, q_comprobante=q_comprobante or None, q_colegiado=q_colegiado or None,
    )

    return templates.TemplateResponse("pages/admin/anulaciones.html", {
        "request": request,
        "pendientes": pendientes,
        "historial": historial,
        "motivos": MOTIVOS_09,
        "filtros": {"fecha_desde": fecha_desde or "", "fecha_hasta": fecha_hasta or "",
                    "motivo": motivo or "", "q_comprobante": q_comprobante or "",
                    "q_colegiado": q_colegiado or ""},
    })


def _get_solicitud(db, solicitud_id):
    from app.models import SolicitudAnulacion
    sol = db.query(SolicitudAnulacion).filter(
        SolicitudAnulacion.id == solicitud_id,
        SolicitudAnulacion.organization_id == ORG_CCPL,
    ).first()
    if not sol:
        raise HTTPException(404, detail="Solicitud no encontrada")
    if sol.estado != "pendiente":
        raise HTTPException(400, detail=f"La solicitud ya está '{sol.estado}'")
    return sol


@router.post("/{solicitud_id}/aprobar")
async def aprobar(
    solicitud_id: int,
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_gestion),
):
    sol = _get_solicitud(db, solicitud_id)
    motivo_texto = MOTIVOS_09.get(sol.motivo_sunat, "Anulación de la operación")
    resultado = await aprobar_solicitud(db, sol, current_member, motivo_texto)
    if not resultado.get("success"):
        return JSONResponse(resultado, status_code=400)
    return JSONResponse({"success": True, "nota_credito": resultado.get("nota_credito")})


@router.post("/{solicitud_id}/rechazar")
async def rechazar(
    solicitud_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_gestion),
):
    sol = _get_solicitud(db, solicitud_id)
    data = await request.json()
    nota = (data.get("nota") or "").strip()
    await rechazar_solicitud(db, sol, current_member, nota)
    return JSONResponse({"success": True})

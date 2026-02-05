"""
Router: Vistas Admin (HTML)
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models import Organization, Colegiado, Payment, Member
from app.routers.dashboard import get_current_member  # <-- Importar de dashboard

router = APIRouter(tags=["admin-views"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/admin/config", response_class=HTMLResponse)
async def admin_config_page(
    request: Request,
    member: Member = Depends(get_current_member),  # <-- Usar la dependencia
    db: Session = Depends(get_db)
):
    """Panel de configuración del colegio"""
    
    # Org desde el middleware
    org = getattr(request.state, 'org', None)
    if not org:
        org_obj = db.query(Organization).filter(
            Organization.id == member.organization_id
        ).first()
        org = {
            "id": org_obj.id,
            "name": org_obj.name,
            "slug": org_obj.slug,
            "config": org_obj.config or {}
        } if org_obj else None
    
    config = org.get("config", {}) if org else {}
    
    # Stats rápidas
    stats = {"total_colegiados": 0, "habiles": 0, "morosos": 0, "pagos_pendientes": 0}
    org_id = org.get("id") if org else member.organization_id
    
    if org_id:
        total = db.query(func.count(Colegiado.id)).filter(
            Colegiado.organization_id == org_id
        ).scalar() or 0
        
        habiles = db.query(func.count(Colegiado.id)).filter(
            Colegiado.organization_id == org_id,
            Colegiado.condicion == 'habil'
        ).scalar() or 0
        
        pendientes = db.query(func.count(Payment.id)).filter(
            Payment.organization_id == org_id,
            Payment.status == 'review'
        ).scalar() or 0
        
        stats = {
            "total_colegiados": total,
            "habiles": habiles,
            "morosos": total - habiles,
            "porcentaje_habiles": round(habiles / total * 100, 1) if total > 0 else 0,
            "pagos_pendientes": pendientes
        }
    
    return templates.TemplateResponse(
    "pages/admin/admin-config.html",
    {
        "request": request,
        "user": {
            "id": member.id,
            "name": member.user.name if member.user else "Admin",
            "role": member.role
        },
        "org": org,
        "config": config,
        "stats": stats
    }
)
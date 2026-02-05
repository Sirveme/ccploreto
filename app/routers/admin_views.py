"""
Router: Vistas Admin (HTML)
===========================
Páginas del panel de administración
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models import Organization, Colegiado, Payment

router = APIRouter(tags=["admin-views"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/admin/config", response_class=HTMLResponse)
async def admin_config_page(
    request: Request,
    db: Session = Depends(get_db)
):
    """Panel de configuración del colegio"""
    
    # Auth check
    user = getattr(request.state, 'user', None)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    
    # Org
    org = getattr(request.state, 'org', None)
    if not org:
        org = db.query(Organization).first()
    
    config = org.config if org and org.config else {}
    
    # Stats rápidas
    stats = {"total_colegiados": 0, "habiles": 0, "morosos": 0}
    if org:
        total = db.query(func.count(Colegiado.id)).filter(
            Colegiado.organization_id == org.id
        ).scalar() or 0
        
        habiles = db.query(func.count(Colegiado.id)).filter(
            Colegiado.organization_id == org.id,
            Colegiado.condicion == 'habil'
        ).scalar() or 0
        
        pendientes = db.query(func.count(Payment.id)).filter(
            Payment.organization_id == org.id,
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
            "user": user,
            "org": org,
            "config": config,
            "stats": stats
        }
    )
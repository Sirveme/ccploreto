from fastapi import APIRouter, Request, Depends
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import or_
from app.database import get_db
from app.models import Member, Partner
from app.routers.dashboard import get_current_member

router = APIRouter(tags=["services"])
templates = Jinja2Templates(directory="app/templates")

@router.get("/services")
async def services_home(
    request: Request, 
    category: str = None,
    db: Session = Depends(get_db), 
    member: Member = Depends(get_current_member)
):
    current_theme = getattr(request.state, "theme", None)

    # Lógica de Filtrado:
    # Mostrar Partners GLOBALES (org_id es NULL) OR Partners de MI EDIFICIO
    query = db.query(Partner).filter(
        or_(
            Partner.organization_id == None,
            Partner.organization_id == member.organization_id
        )
    )

    # Filtro por categoría si se selecciona
    if category:
        query = query.filter(Partner.category == category)

    # Ordenar: Promocionados primero, luego verificados
    partners = query.order_by(Partner.is_promoted.desc(), Partner.is_verified.desc()).all()

    return templates.TemplateResponse("pages/services/home_services.html", {
        "request": request,
        "user": member,
        "partners": partners,
        "theme": current_theme,
        "selected_category": category
    })
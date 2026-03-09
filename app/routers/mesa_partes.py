from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, Member
from app.routers.dashboard import get_current_member

templates = Jinja2Templates(directory="app/templates")
router = APIRouter(prefix="/mesa-partes", tags=["mesa_partes"])


def require_secretaria(current_member: Member = Depends(get_current_member)):
    if current_member.role not in ("secretaria", "admin", "sote"):
        raise HTTPException(status_code=403, detail="Acceso restringido a Mesa de Partes")
    return current_member


@router.get("", response_class=HTMLResponse)
async def mesa_partes_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_secretaria),
):
    user = db.query(User).filter(User.id == current_member.user_id).first()
    return templates.TemplateResponse("pages/mesa_partes/dashboard.html", {
        "request": request,
        "user": current_member,   # base.html espera user.organization
        "user_name": user.name,
        "org": getattr(request.state, "org", {}),
    })
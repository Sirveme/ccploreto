"""Página de configuración personal de notificaciones (zClaude-97o).

Usa el `templates` del proyecto (app.utils.templates) para heredar el contexto
de tenant/tema, en vez de instanciar un Jinja2Templates aparte.
"""
from fastapi import APIRouter, Request, Depends

from app.utils.templates import templates
from app.models import Member
from app.routers.dashboard import get_current_member

router = APIRouter(tags=["notificaciones-ui"])


@router.get("/notificaciones")
async def pagina_notificaciones(
    request: Request,
    member: Member = Depends(get_current_member),
):
    return templates.TemplateResponse("pages/notificaciones.html", {
        "request": request,
        "member": member,
        "user": member,
        "org": getattr(request.state, "org", {}),
        "theme": getattr(request.state, "theme", None),
    })

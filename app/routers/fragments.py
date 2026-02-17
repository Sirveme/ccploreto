"""
Módulo: Fragments — HTML parciales para modales lazy
app/routers/fragments.py

Sirve templates Jinja2 con contexto del colegiado actual.
Los modales del dashboard se cargan bajo demanda (lazy loading)
para reducir el HTML inicial de ~900 a ~256 líneas.
"""

from fastapi import APIRouter, Request, Depends
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.routers.dashboard import get_current_member
from app.models import Member, Colegiado, Organization
from app.config import DEFAULT_THEME, THEMES

templates = Jinja2Templates(directory="app/templates")
router = APIRouter(prefix="/fragments", tags=["Fragments"])

# Modales permitidos (whitelist de seguridad)
ALLOWED_FRAGMENTS = {
    'modal_perfil',
    'modal_pagos',
    'modal_herramientas',
    'modal_mi_sitio',
    'modal_avisos',
}


@router.get("/{fragment_name}", response_class=HTMLResponse)
async def get_fragment(
    fragment_name: str,
    request: Request,
    member: Member = Depends(get_current_member),
    db: Session = Depends(get_db)
):
    """
    Sirve un fragment HTML renderizado con Jinja2.
    Solo permite fragments de la whitelist.
    """
    if fragment_name not in ALLOWED_FRAGMENTS:
        return HTMLResponse(
            '<div class="empty-state"><p>Módulo no encontrado</p></div>',
            status_code=404
        )

    # Obtener colegiado vinculado al member
    colegiado = db.query(Colegiado).filter(
        Colegiado.id == member.colegiado_id
    ).first() if hasattr(member, 'colegiado_id') and member.colegiado_id else None

    # Obtener config de la organización
    org = db.query(Organization).filter(
        Organization.id == member.organization_id
    ).first() if hasattr(member, 'organization_id') else None

    config = org.config if org and hasattr(org, 'config') else {}
    theme = THEMES.get(org.theme, DEFAULT_THEME) if org and hasattr(org, 'theme') else DEFAULT_THEME

    return templates.TemplateResponse(
        f"fragments/{fragment_name}.html",
        {
            "request": request,
            "user": member,
            "colegiado": colegiado,
            "config": config,
            "theme": theme,
        }
    )
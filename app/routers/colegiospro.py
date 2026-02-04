"""
Router: Páginas públicas de colegiospro.org.pe
==============================================
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(tags=["colegiospro"])

templates = Jinja2Templates(directory="app/templates/colegiospro")


@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Landing page de colegiospro.org.pe"""
    return templates.TemplateResponse("index.html", {"request": request})


@router.get("/verificar", response_class=HTMLResponse)
async def pagina_verificar(request: Request):
    """Página de verificación (redirige a home con ancla)"""
    return templates.TemplateResponse("index.html", {"request": request})
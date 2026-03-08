# ── Agregar en app/routers/public.py (o crear app/routers/partials.py)
# Sirve los fragmentos HTML que el modal carga via fetch()

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router_partials = APIRouter(prefix="/partials", tags=["Partials"])
templates = Jinja2Templates(directory="app/templates")


@router_partials.get("/institucional", response_class=HTMLResponse)
async def partial_institucional(request: Request):
    return templates.TemplateResponse(
        "partials/institucional.html",
        {"request": request}
    )


@router_partials.get("/transparencia", response_class=HTMLResponse)
async def partial_transparencia(request: Request):
    return templates.TemplateResponse(
        "partials/transparencia.html",
        {"request": request}
    )


# ── Agregar en main.py ─────────────────────────────────────────────────
# from app.routers.public import router_partials   (si lo pones en public.py)
# o:
# from app.routers.partials import router_partials
#
# app.include_router(router_partials)
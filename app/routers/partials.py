# app/routers/partials.py
# Sirve todos los fragmentos HTML que el modal carga via fetch()

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from app.utils.templates import templates

router_partials = APIRouter(prefix="/partials", tags=["Partials"])
PARTIALS = [
    "institucional",
    "transparencia",
    "consejo_directivo",
    "contacto",
    "directorio",
    "comite_electoral",
    "publicaciones",
    "constancia",
    "pagos",
    "alertas_tributarias",
]

for _key in PARTIALS:
    def _make_route(key):
        @router_partials.get(f"/{key}", response_class=HTMLResponse)
        async def _route(request: Request, _k=key):
            return templates.TemplateResponse(
                f"partials/{_k}.html", {"request": request}
            )
        _route.__name__ = f"partial_{key}"
        return _route
    _make_route(_key)


# ── Agregar en main.py ──────────────────────────────────────────
# from app.routers.partials import router_partials
# app.include_router(router_partials)
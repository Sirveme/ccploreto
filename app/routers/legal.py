from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

router = APIRouter(tags=["legal"])
templates = Jinja2Templates(directory="app/templates")

@router.get("/politicas")
async def politicas(request: Request):
    return templates.TemplateResponse("pages/legal/politicas.html", {"request": request})

@router.get("/terminos")
async def terminos(request: Request):
    return templates.TemplateResponse("pages/legal/terminos.html", {"request": request})
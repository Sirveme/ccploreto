from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.credenciales_service import CredencialesService
from app.utils.templates import templates

router = APIRouter(
    prefix="/credenciales",
    tags=["Credenciales"]
)


@router.get("/preview/{colegiado_id}", response_class=HTMLResponse)
async def preview_credencial(
    colegiado_id: int,
    request: Request,
    db: Session = Depends(get_db)
):

    service = CredencialesService(db)

    contexto = service.obtener_contexto_credencial(
        request=request,
        colegiado_id=colegiado_id
    )

    return templates.TemplateResponse(
        "pages/credenciales/preview.html",
        contexto
    )
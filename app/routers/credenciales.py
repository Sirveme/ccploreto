from fastapi import APIRouter, Request, Depends, HTTPException, Body
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Member
from app.models_credenciales import CredentialIssuance
from app.routers.dashboard import get_current_member
from app.services.credenciales_service import CredencialesService
from app.services import credenciales_emision_service as emision
from app.services.credencial_reportlab import generar_credencial_pdf
from app.utils.templates import templates

router = APIRouter(
    prefix="/credenciales",
    tags=["Credenciales"]
)

# Roles por FUNCIÓN (no por persona): si cambia el operador, el rol sigue válido.
ROLES_EMISION = ("emisor_carnes", "secretaria", "admin", "decano")
ROLES_STOCK   = ("admin", "decano")


def require_credenciales_emision(current_member: Member = Depends(get_current_member)) -> Member:
    if current_member.role not in ROLES_EMISION:
        raise HTTPException(403, "Acceso restringido a la emisión de credenciales")
    return current_member


def require_credenciales_stock(current_member: Member = Depends(get_current_member)) -> Member:
    if current_member.role not in ROLES_STOCK:
        raise HTTPException(403, "Solo Administrador o Decano pueden cargar stock")
    return current_member


def _pdf_response(pdf_bytes, colegiado, version, issuance_id=None):
    filename = "carne_%s_v%s.pdf" % (getattr(colegiado, "codigo_matricula", "") or "sn", version)
    headers = {"Content-Disposition": 'inline; filename="%s"' % filename}
    if issuance_id is not None:
        headers["X-Issuance-Id"] = str(issuance_id)
        headers["X-Card-Version"] = str(version)
    return StreamingResponse(iter([pdf_bytes]), media_type="application/pdf", headers=headers)


@router.get("/preview/{colegiado_id}", response_class=HTMLResponse)
async def preview_credencial(
    colegiado_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    service = CredencialesService(db)
    contexto = service.obtener_contexto_credencial(request=request, colegiado_id=colegiado_id)
    return templates.TemplateResponse("pages/credenciales/preview.html", contexto)


@router.get("/muestra/{colegiado_id}/pdf")
async def muestra_credencial(
    colegiado_id: int,
    request: Request,
    db: Session = Depends(get_db),
    member: Member = Depends(require_credenciales_emision),
):
    """Vista previa / impresión de prueba: PDF con marca 'MUESTRA - NO VÁLIDO',
    QR sin token válido. NO crea issuance, NO consume derecho, NO descuenta stock."""
    ctx = CredencialesService(db).obtener_contexto_credencial(request=request, colegiado_id=colegiado_id)
    pdf = generar_credencial_pdf(ctx["colegiado"], ctx["organization"], ctx["template"],
                                 token=None, muestra=True)
    filename = "muestra_carne_%s.pdf" % (ctx["colegiado"].codigo_matricula or "sn")
    return StreamingResponse(iter([pdf]), media_type="application/pdf",
                             headers={"Content-Disposition": 'inline; filename="%s"' % filename})


@router.post("/emitir/{colegiado_id}")
async def emitir_credencial(
    colegiado_id: int,
    request: Request,
    db: Session = Depends(get_db),
    member: Member = Depends(require_credenciales_emision),
):
    """Emite el carné (token + copia + estado vigente + descuento de stock) y devuelve el PDF."""
    ctx = CredencialesService(db).obtener_contexto_credencial(request=request, colegiado_id=colegiado_id)
    try:
        iss, pdf = emision.emitir(db, ctx["organization"], ctx["template"], ctx["colegiado"], usuario_id=member.id)
        db.commit()
    except ValueError as e:
        db.rollback()
        raise HTTPException(400, str(e))
    except Exception:
        db.rollback()
        raise
    return _pdf_response(pdf, ctx["colegiado"], iss.version, issuance_id=iss.id)


@router.get("/emision/{issuance_id}/pdf")
async def pdf_emision(
    issuance_id: int,
    request: Request,
    db: Session = Depends(get_db),
    member: Member = Depends(require_credenciales_emision),
):
    """Re-descarga el PDF de una emisión existente (reimpresión tras desecho)."""
    iss = db.query(CredentialIssuance).filter(CredentialIssuance.id == issuance_id).first()
    if not iss:
        raise HTTPException(404, "Emisión no encontrada")
    ctx = CredencialesService(db).obtener_contexto_credencial(request=request, colegiado_id=iss.colegiado_id)
    pdf = generar_credencial_pdf(ctx["colegiado"], ctx["organization"], ctx["template"], token=iss.codigo_verificacion)
    return _pdf_response(pdf, ctx["colegiado"], iss.version)


@router.post("/desechar")
async def desechar_credencial(
    request: Request,
    body: dict = Body(default={}),
    db: Session = Depends(get_db),
    member: Member = Depends(require_credenciales_emision),
):
    """Registra un carné en blanco arruinado: descuenta stock SIN consumir el derecho."""
    org = request.state.org
    try:
        disp = emision.desechar(db, org["id"], member.id, body.get("motivo"), body.get("issuance_id"))
        db.commit()
    except ValueError as e:
        db.rollback()
        raise HTTPException(400, str(e))
    return {"status": "ok", "disponibles": disp}


@router.post("/stock/ingreso")
async def ingreso_stock_ep(
    request: Request,
    body: dict = Body(default={}),
    db: Session = Depends(get_db),
    member: Member = Depends(require_credenciales_stock),
):
    """Ingreso de carnés en blanco al stock (solo Administrador/Decano)."""
    org = request.state.org
    try:
        disp = emision.ingreso_stock(db, org["id"], member.id, int(body.get("cantidad", 0)), body.get("motivo"))
        db.commit()
    except ValueError as e:
        db.rollback()
        raise HTTPException(400, str(e))
    return {"status": "ok", "disponibles": disp}


@router.get("/stock")
async def ver_stock(
    request: Request,
    db: Session = Depends(get_db),
    member: Member = Depends(require_credenciales_emision),
):
    org = request.state.org
    return {"disponibles": emision.stock_actual(db, org["id"])}


@router.get("/panel", response_class=HTMLResponse)
async def panel_emision(
    request: Request,
    db: Session = Depends(get_db),
    member: Member = Depends(require_credenciales_emision),
):
    """Panel operativo de emisión (Morelia). Sin búsqueda libre: solo las listas."""
    org = request.state.org
    listas = emision.listas_panel(db, org["id"])
    puede_stock = member.role in ROLES_STOCK
    return templates.TemplateResponse("pages/credenciales/panel.html", {
        "request": request,
        "org": org,
        "theme": getattr(request.state, "theme", None),
        "stock": emision.stock_actual(db, org["id"]),
        "nuevos": listas["nuevos"],
        "antiguos": listas["antiguos"],
        "gratuitos": listas["gratuitos"],
        "puede_stock": puede_stock,
    })

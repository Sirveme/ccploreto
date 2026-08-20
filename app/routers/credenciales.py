import re
import datetime
from types import SimpleNamespace
from urllib.parse import quote

from fastapi import APIRouter, Request, Depends, HTTPException, Body
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Member, Colegiado, Organization
from app.models_credenciales import CredentialIssuance, CredentialTemplate
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

# Token CENTINELA del PDF de revisión: su QR resuelve a "Carné no encontrado" en
# /verificar → el preview sin marca NO puede usarse como carné válido (anti-backdoor).
PREVIEW_TOKEN = "PREVIEW-NO-EMITIDO"

# Host canónico del enlace compartido (igual que el QR: solo ccploreto.org.pe es
# público/indexable). Evita que un host *.duilio.store se filtre en el link.
SHARE_BASE = "https://ccploreto.org.pe"


def _telefono_wa(colegiado):
    """Devuelve el número normalizado para wa.me (+51) o None si no hay teléfono usable.
    NO arma wa.me con teléfono vacío."""
    raw = getattr(colegiado, "telefono", None) or ""
    digits = re.sub(r"\D", "", raw)
    if len(digits) >= 9:
        return "51" + digits[-9:]
    return None


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


@router.get("/verificar/{token}", response_class=HTMLResponse)
async def verificar_credencial(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Verificación PÚBLICA del carné por el token del QR (SIN login).
    Privacidad: muestra solo nombre, matrícula, condición y foto. NUNCA DNI/RUC."""
    iss = db.query(CredentialIssuance).filter(
        CredentialIssuance.codigo_verificacion == token
    ).first()

    estado = "no_encontrado"
    colegiado = None
    emitido = ""
    if iss:
        colegiado = db.query(Colegiado).filter(Colegiado.id == iss.colegiado_id).first()
        if iss.emitido_en:
            try:
                emitido = iss.emitido_en.strftime("%d/%m/%Y")
            except Exception:
                emitido = ""
        estado = "vigente" if iss.estado == "vigente" else "invalido"

    org_dict = getattr(request.state, "org", None)
    organization = None
    if org_dict and org_dict.get("id"):
        organization = db.query(Organization).filter(Organization.id == org_dict["id"]).first()

    return templates.TemplateResponse("pages/credenciales/verificar.html", {
        "request": request,
        "org": organization,
        "estado": estado,
        "colegiado": colegiado,
        "emitido": emitido,
    })


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


@router.get("/modelo/pdf")
async def modelo_pdf(
    request: Request,
    db: Session = Depends(get_db),
    member: Member = Depends(require_credenciales_emision),
):
    """Carné MODELO genérico con marca 'MUESTRA - NO VÁLIDO' — para calibrar la
    impresora y revisar composición/formatos/contrastes. NO es de ningún colegiado."""
    org_dict = getattr(request.state, "org", None)
    organization = None
    template = None
    if org_dict and org_dict.get("id"):
        organization = db.query(Organization).filter(Organization.id == org_dict["id"]).first()
        template = db.query(CredentialTemplate).filter(
            CredentialTemplate.organization_id == org_dict["id"],
            CredentialTemplate.activa == True,
        ).first()
    modelo = SimpleNamespace(
        apellidos_nombres="APELLIDO PATERNO MATERNO NOMBRE",
        codigo_matricula="10-0000",
        dni="00000000",
        fecha_colegiatura=datetime.date(2015, 3, 12),
        fecha_nacimiento=datetime.date(1985, 6, 20),
        tipo_sangre="O+",
        condicion="habil",
        especialidad="",
        foto_url=None,
    )
    pdf = generar_credencial_pdf(modelo, organization, template, token=None, muestra=True)
    return StreamingResponse(iter([pdf]), media_type="application/pdf",
                             headers={"Content-Disposition": 'inline; filename="modelo_carne.pdf"'})


@router.get("/revisar/{colegiado_id}", response_class=HTMLResponse)
async def revisar_credencial(
    colegiado_id: int,
    request: Request,
    db: Session = Depends(get_db),
    member: Member = Depends(require_credenciales_emision),
):
    """Página de REVISIÓN previa a imprimir: muestra el carné real del colegiado
    (embebido, sin marca) + qué falta. Solo IMPRIMIR (aquí adentro) emite de verdad."""
    ctx = CredencialesService(db).obtener_contexto_credencial(request=request, colegiado_id=colegiado_id)
    val = emision.validar_emision(ctx["template"], ctx["colegiado"])
    puede = not val["faltan_colegiado"] and not val["faltan_plantilla"]
    return templates.TemplateResponse("pages/credenciales/preview_colegiado.html", {
        "request": request,
        "org": ctx["organization"],
        "colegiado": ctx["colegiado"],
        "faltan_colegiado": val["faltan_colegiado"],
        "faltan_plantilla": val["faltan_plantilla"],
        "puede_imprimir": puede,
        "tiene_telefono": _telefono_wa(ctx["colegiado"]) is not None,
        "share_horas": emision.SHARE_TTL_HORAS,
    })


@router.get("/revisar/{colegiado_id}/pdf")
async def revisar_pdf(
    colegiado_id: int,
    request: Request,
    db: Session = Depends(get_db),
    member: Member = Depends(require_credenciales_emision),
):
    """PDF del carné REAL (sin marca) para revisión embebida. Token CENTINELA → su QR
    resuelve a 'Carné no encontrado' → NO usable como carné válido. NO emite, NO descuenta."""
    ctx = CredencialesService(db).obtener_contexto_credencial(request=request, colegiado_id=colegiado_id)
    pdf = generar_credencial_pdf(ctx["colegiado"], ctx["organization"], ctx["template"],
                                 token=PREVIEW_TOKEN, muestra=False)
    filename = "revision_carne_%s.pdf" % (ctx["colegiado"].codigo_matricula or "sn")
    return StreamingResponse(iter([pdf]), media_type="application/pdf",
                             headers={"Content-Disposition": 'inline; filename="%s"' % filename})


@router.post("/compartir/{colegiado_id}")
async def compartir_credencial(
    colegiado_id: int,
    request: Request,
    db: Session = Depends(get_db),
    member: Member = Depends(require_credenciales_emision),
):
    """Genera un enlace TEMPORAL (24h, revocable) para que el colegiado revise su carné
    en MUESTRA. NO emite, NO descuenta stock. Devuelve link + wa.me (si hay teléfono)."""
    ctx = CredencialesService(db).obtener_contexto_credencial(request=request, colegiado_id=colegiado_id)
    col = ctx["colegiado"]
    try:
        tok = emision.crear_share_token(db, ctx["organization"].id, col.id, member.id)
        db.commit()
    except Exception:
        db.rollback()
        raise
    link = "%s/credenciales/carne-compartido/%s" % (SHARE_BASE, tok)
    num = _telefono_wa(col)
    wa_url = None
    if num:
        msg = ("Hola, este es el diseño de tu carné del CCPL para que revises tu foto y "
               "datos. Es solo una MUESTRA (no es el carné final). Enlace válido por %d horas: %s"
               % (emision.SHARE_TTL_HORAS, link))
        wa_url = "https://wa.me/%s?text=%s" % (num, quote(msg))
    return {"link": link, "wa_url": wa_url, "tiene_telefono": wa_url is not None,
            "horas": emision.SHARE_TTL_HORAS}


@router.get("/carne-compartido/{token}", response_class=HTMLResponse)
async def carne_compartido(token: str, request: Request, db: Session = Depends(get_db)):
    """Página PÚBLICA (sin login) para que el colegiado revise su carné en MUESTRA.
    Valida el token temporal; si venció / no existe → aviso. Solo expone el carné-muestra."""
    colegiado_id = emision.resolver_share_token(db, token)
    valido = colegiado_id is not None
    colegiado = None
    organization = None
    if valido:
        colegiado = db.query(Colegiado).filter(Colegiado.id == colegiado_id).first()
    org_dict = getattr(request.state, "org", None)
    if org_dict and org_dict.get("id"):
        organization = db.query(Organization).filter(Organization.id == org_dict["id"]).first()
    return templates.TemplateResponse("pages/credenciales/carne_compartido.html", {
        "request": request,
        "org": organization,
        "valido": valido,
        "colegiado": colegiado,
        "token": token,
    })


@router.get("/carne-compartido/{token}/pdf")
async def carne_compartido_pdf(token: str, request: Request, db: Session = Depends(get_db)):
    """PDF PÚBLICO del carné en MUESTRA (marca de agua + QR no verificable). Requiere
    token temporal válido. NO emite, NO descuenta stock."""
    colegiado_id = emision.resolver_share_token(db, token)
    if colegiado_id is None:
        raise HTTPException(404, "Enlace no válido o vencido")
    ctx = CredencialesService(db).obtener_contexto_credencial(request=request, colegiado_id=colegiado_id)
    pdf = generar_credencial_pdf(ctx["colegiado"], ctx["organization"], ctx["template"],
                                 token=None, muestra=True)
    return StreamingResponse(iter([pdf]), media_type="application/pdf",
                             headers={"Content-Disposition": 'inline; filename="carne_muestra.pdf"'})


@router.post("/emitir/{colegiado_id}")
async def emitir_credencial(
    colegiado_id: int,
    request: Request,
    db: Session = Depends(get_db),
    member: Member = Depends(require_credenciales_emision),
):
    """Emite el carné (token + copia + estado vigente + descuento de stock) y devuelve el PDF."""
    ctx = CredencialesService(db).obtener_contexto_credencial(request=request, colegiado_id=colegiado_id)

    # GATE server-side: no se emite si faltan campos mínimos (el front deshabilita
    # IMPRIMIR, pero esta es la defensa dura — rechaza de verdad).
    val = emision.validar_emision(ctx["template"], ctx["colegiado"])
    faltan = val["faltan_colegiado"] + val["faltan_plantilla"]
    if faltan:
        raise HTTPException(400, "No se puede imprimir. Faltan: " + "; ".join(faltan))

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

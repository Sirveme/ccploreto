import re
import json
import datetime
from types import SimpleNamespace
from urllib.parse import quote

from fastapi import APIRouter, Request, Depends, HTTPException, Body, UploadFile, File, Form
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Member, Colegiado, Organization
from app.models_credenciales import CredentialIssuance, CredentialTemplate
from app.routers.dashboard import get_current_member
from app.services.credenciales_service import CredencialesService
from app.services import credenciales_emision_service as emision
from app.services import credenciales_editor_service as editor
from app.services.credencial_reportlab import generar_credencial_pdf, DEFAULT_LAYOUT
from app.utils.gcs import upload_credencial_fondo
from app.utils.templates import templates

router = APIRouter(
    prefix="/credenciales",
    tags=["Credenciales"]
)

# Roles por FUNCIÓN (no por persona): si cambia el operador, el rol sigue válido.
ROLES_EMISION = ("emisor_carnes", "secretaria", "admin", "decano")
ROLES_STOCK   = ("admin", "decano")
ROLES_LOCK    = ("admin", "decano")   # desbloquean/bloquean la edición de la plantilla


def _template_activo(db: Session, org_id):
    return db.query(CredentialTemplate).filter(
        CredentialTemplate.organization_id == org_id,
        CredentialTemplate.activa == True,
    ).first()

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


# ═══════════════════════════════════════════════════════════════════
# PARTE 7A — Editor visual de layout (fuente de verdad = layout JSONB)
# ═══════════════════════════════════════════════════════════════════

@router.get("/editor", response_class=HTMLResponse)
async def editor_layout(
    request: Request,
    db: Session = Depends(get_db),
    member: Member = Depends(require_credenciales_emision),
):
    """Editor visual del TEMPLATE ACTIVO de la org. El candado (bloqueado_edicion)
    decide si el operador puede editar; admin/decano puede editar y (des)bloquear."""
    org_dict = request.state.org
    organization = db.query(Organization).filter(Organization.id == org_dict["id"]).first()
    tpl = _template_activo(db, org_dict["id"])
    if not tpl:
        raise HTTPException(404, "No hay plantilla activa para esta organización")
    layout = tpl.layout or DEFAULT_LAYOUT
    bloqueado = bool(tpl.bloqueado_edicion)
    es_admin = member.role in ROLES_LOCK
    puede_editar = es_admin or (not bloqueado)
    cfg = {
        "puede_editar": puede_editar,
        "es_admin": es_admin,
        "bloqueado": bloqueado,
        "fondos": {"frente": tpl.fondo_frente_url, "reverso": tpl.fondo_reverso_url},
    }
    return templates.TemplateResponse("pages/credenciales/editor.html", {
        "request": request,
        "org": organization,
        "tpl": tpl,
        "layout_json": json.dumps(layout, ensure_ascii=False),
        "cfg_json": json.dumps(cfg, ensure_ascii=False),
        "bloqueado": bloqueado,
        "es_admin": es_admin,
        "puede_editar": puede_editar,
    })


@router.post("/editor/guardar")
async def editor_guardar(
    request: Request,
    body: dict = Body(default={}),
    db: Session = Depends(get_db),
    member: Member = Depends(require_credenciales_emision),
):
    """Guarda el layout. 'Si guarda, imprime': candado + límites CR80 + test-render.
    Si el PDF revienta, RECHAZA el guardado (nunca persiste un layout que no imprime)."""
    org_dict = request.state.org
    organization = db.query(Organization).filter(Organization.id == org_dict["id"]).first()
    tpl = _template_activo(db, org_dict["id"])
    if not tpl:
        raise HTTPException(404, "No hay plantilla activa")

    # (1) Candado SERVER-SIDE (no solo ocultar el botón).
    if tpl.bloqueado_edicion and member.role not in ROLES_LOCK:
        raise HTTPException(403, "La plantilla está bloqueada. Pide a un administrador que la desbloquee.")

    nuevo = body.get("layout")
    if not isinstance(nuevo, dict) or "frente" not in nuevo or "reverso" not in nuevo:
        raise HTTPException(400, "Layout inválido (faltan caras frente/reverso)")

    # (2) Límites CR80.
    errs = editor.validar_bounds(nuevo)
    if errs:
        raise HTTPException(400, "Fuera de los límites del carné: " + " · ".join(errs[:6]))

    # (3) Test-render con el layout nuevo.
    ok, err = editor.test_render_layout(organization, tpl, nuevo)
    if not ok:
        raise HTTPException(400, "El diseño no se puede imprimir: " + str(err))

    # (4) Undo de un nivel + persistir.
    try:
        tpl.layout_backup = tpl.layout
        tpl.layout = nuevo
        tpl.updated_at = datetime.datetime.utcnow()
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"ok": True}


@router.post("/editor/restaurar")
async def editor_restaurar(
    request: Request,
    db: Session = Depends(get_db),
    member: Member = Depends(require_credenciales_emision),
):
    """Restaura la ÚLTIMA versión guardada (layout_backup → layout). Un solo nivel.
    NO toca layout_backup: el respaldo sobrevive a la restauración → el usuario nunca
    queda sin red y no es un 'deshacer' infinito. Mismo candado que el guardado."""
    org_dict = request.state.org
    tpl = _template_activo(db, org_dict["id"])
    if not tpl:
        raise HTTPException(404, "No hay plantilla activa")
    if tpl.bloqueado_edicion and member.role not in ROLES_LOCK:
        raise HTTPException(403, "La plantilla está bloqueada. Pide a un administrador que la desbloquee.")
    if not tpl.layout_backup:
        raise HTTPException(400, "No hay una versión guardada anterior para restaurar")
    try:
        tpl.layout = tpl.layout_backup   # layout_backup se conserva a propósito (red intacta)
        tpl.updated_at = datetime.datetime.utcnow()
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"ok": True, "layout": tpl.layout}


@router.post("/editor/preview-pdf")
async def editor_preview_pdf(
    request: Request,
    body: dict = Body(default={}),
    db: Session = Depends(get_db),
    member: Member = Depends(require_credenciales_emision),
):
    """'Ver PDF real' de los cambios EN CURSO (sin guardar). El PDF es el juez final."""
    org_dict = request.state.org
    organization = db.query(Organization).filter(Organization.id == org_dict["id"]).first()
    tpl = _template_activo(db, org_dict["id"])
    if not tpl:
        raise HTTPException(404, "No hay plantilla activa")
    nuevo = body.get("layout")
    if not isinstance(nuevo, dict):
        raise HTTPException(400, "Layout inválido")
    shim = SimpleNamespace(
        layout=nuevo,
        fondo_frente_url=tpl.fondo_frente_url,
        fondo_reverso_url=tpl.fondo_reverso_url,
        codigo_matricula="modelo",
    )
    try:
        pdf = generar_credencial_pdf(editor.colegiado_demo(), organization, shim, token=None, muestra=True)
    except Exception as e:
        raise HTTPException(400, "No se pudo generar el PDF: %s" % e)
    return StreamingResponse(iter([pdf]), media_type="application/pdf",
                             headers={"Content-Disposition": 'inline; filename="editor_preview.pdf"'})


@router.post("/editor/fondo")
async def editor_fondo(
    request: Request,
    cara: str = Form(...),
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db),
    member: Member = Depends(require_credenciales_emision),
):
    """Sube el fondo (anverso/reverso) a GCS (UBLA-safe) y actualiza fondo_{cara}_url."""
    org_dict = request.state.org
    tpl = _template_activo(db, org_dict["id"])
    if not tpl:
        raise HTTPException(404, "No hay plantilla activa")
    if tpl.bloqueado_edicion and member.role not in ROLES_LOCK:
        raise HTTPException(403, "La plantilla está bloqueada.")
    if cara not in ("frente", "reverso"):
        raise HTTPException(400, "Cara inválida (frente|reverso)")
    data = await archivo.read()
    if not data:
        raise HTTPException(400, "Archivo vacío")
    url = upload_credencial_fondo(data, archivo.content_type or "image/png", org_dict["id"], cara)
    if not url:
        raise HTTPException(500, "No se pudo subir el fondo (GCS no configurado)")
    try:
        if cara == "frente":
            tpl.fondo_frente_url = url
        else:
            tpl.fondo_reverso_url = url
        tpl.updated_at = datetime.datetime.utcnow()
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"ok": True, "url": url, "cara": cara}


@router.post("/editor/bloqueo")
async def editor_bloqueo(
    request: Request,
    body: dict = Body(default={}),
    db: Session = Depends(get_db),
    member: Member = Depends(require_credenciales_emision),
):
    """(Des)bloquea la edición del template. Solo Administrador/Decano."""
    if member.role not in ROLES_LOCK:
        raise HTTPException(403, "Solo Administrador o Decano pueden bloquear/desbloquear la edición")
    org_dict = request.state.org
    tpl = _template_activo(db, org_dict["id"])
    if not tpl:
        raise HTTPException(404, "No hay plantilla activa")
    tpl.bloqueado_edicion = bool(body.get("bloqueado", True))
    tpl.updated_at = datetime.datetime.utcnow()
    db.commit()
    return {"ok": True, "bloqueado": tpl.bloqueado_edicion}

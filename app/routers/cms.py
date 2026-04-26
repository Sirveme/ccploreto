"""
app/routers/cms.py — Panel CMS público + endpoints CRUD (zClaude-55).

Acceso: roles 'admin' o 'editor' (vía Member.role).
Sin alertas/confirmaciones nativas — todas las acciones devuelven JSON.
"""
from datetime import datetime, timezone, timedelta
from typing import Optional, List
import logging

from fastapi import APIRouter, Depends, HTTPException, Body, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc, asc, or_

from app.database import get_db
from app.models import (
    Member, Organization, Bulletin, Partner, Resource, CarruselSlide,
    ConceptoCobro,
)
from app.routers.dashboard import get_current_member
from app.utils.templates import templates

logger = logging.getLogger(__name__)

PERU_TZ = timezone(timedelta(hours=-5))
ROLES_CMS = ("admin", "editor")


def require_admin_or_editor(
    current_member: Member = Depends(get_current_member),
) -> Member:
    if current_member.role not in ROLES_CMS:
        raise HTTPException(status_code=403, detail="Acceso restringido a admin/editor")
    return current_member


def _a_lima(dt, fmt: str = "%d/%m/%Y %H:%M"):
    if dt is None:
        return None
    if getattr(dt, "tzinfo", None) is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(PERU_TZ).strftime(fmt)


def _org_id(request: Request, member: Member) -> int:
    org = getattr(request.state, "org", None)
    if isinstance(org, dict) and org.get("id"):
        return org["id"]
    return member.organization_id or 1


def _parse_iso(s: Optional[str]):
    if not s:
        return None
    s = str(s).strip()
    if not s:
        return None
    for fmt in (
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=PERU_TZ)
            return dt
        except ValueError:
            continue
    return None


# ============================================================
# PÁGINA HTML /admin/cms
# ============================================================
page_router = APIRouter(tags=["CMS"])


@page_router.get("/admin/cms", response_class=HTMLResponse)
async def cms_index(
    request: Request,
    member: Member = Depends(require_admin_or_editor),
):
    return templates.TemplateResponse(
        "pages/admin/cms.html",
        {
            "request": request,
            "user": {
                "id":   member.id,
                "name": member.user.name if member.user else "Editor",
                "role": member.role,
            },
        },
    )


# ============================================================
# PÁGINAS PÚBLICAS BLOG (zClaude-56 PARTE B) — sin login
# ============================================================
public_router = APIRouter(tags=["CMS Público"])


def _org_publica(request: Request) -> int:
    org = getattr(request.state, "org", None)
    if isinstance(org, dict) and org.get("id"):
        return org["id"]
    return 1


def _org_publica_dict(request: Request) -> dict:
    org = getattr(request.state, "org", None)
    if isinstance(org, dict):
        return org
    return {"id": 1, "name": "CCPL", "slug": "ccp-loreto", "config": {}}


# ── Comunicados ──
@public_router.get("/comunicados", response_class=HTMLResponse)
async def public_comunicados(
    request: Request,
    page: int = 1,
    db: Session = Depends(get_db),
):
    org_id = _org_publica(request)
    per_page = 20
    ahora = datetime.now(timezone.utc)

    base_q = db.query(Bulletin).filter(
        Bulletin.organization_id == org_id,
        Bulletin.tipo == "comunicado",
        or_(Bulletin.expires_at.is_(None), Bulletin.expires_at > ahora),
    )
    total = base_q.count()
    items = (
        base_q.order_by(desc(Bulletin.created_at))
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    return templates.TemplateResponse(
        "public/comunicados.html",
        {
            "request":    request,
            "org":        _org_publica_dict(request),
            "theme":      getattr(request.state, "theme", None),
            "comunicados":[_bulletin_dict(b) for b in items],
            "page":       page,
            "per_page":   per_page,
            "total":      total,
            "total_pages":(total + per_page - 1) // per_page if total else 1,
        },
    )


@public_router.get("/comunicados/{bulletin_id}", response_class=HTMLResponse)
async def public_comunicado_detalle(
    bulletin_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    org_id = _org_publica(request)
    b = (
        db.query(Bulletin)
        .filter(
            Bulletin.id == bulletin_id,
            Bulletin.organization_id == org_id,
            Bulletin.tipo == "comunicado",
        )
        .first()
    )
    if not b:
        raise HTTPException(404, "Comunicado no encontrado")

    return templates.TemplateResponse(
        "public/comunicado_detalle.html",
        {
            "request":    request,
            "org":        _org_publica_dict(request),
            "theme":      getattr(request.state, "theme", None),
            "comunicado": _bulletin_dict(b),
        },
    )


# ── Capacitaciones ──
@public_router.get("/capacitaciones", response_class=HTMLResponse)
async def public_capacitaciones(
    request: Request,
    db: Session = Depends(get_db),
):
    org_id = _org_publica(request)
    items = (
        db.query(Bulletin)
        .filter(
            Bulletin.organization_id == org_id,
            Bulletin.tipo == "capacitacion",
        )
        .order_by(asc(Bulletin.fecha_evento), desc(Bulletin.created_at))
        .all()
    )
    return templates.TemplateResponse(
        "public/capacitaciones.html",
        {
            "request":        request,
            "org":            _org_publica_dict(request),
            "theme":          getattr(request.state, "theme", None),
            "capacitaciones": [_bulletin_dict(b) for b in items],
        },
    )


@public_router.get("/capacitaciones/{bulletin_id}", response_class=HTMLResponse)
async def public_capacitacion_detalle(
    bulletin_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    org_id = _org_publica(request)
    b = (
        db.query(Bulletin)
        .filter(
            Bulletin.id == bulletin_id,
            Bulletin.organization_id == org_id,
            Bulletin.tipo == "capacitacion",
        )
        .first()
    )
    if not b:
        raise HTTPException(404, "Capacitación no encontrada")
    return templates.TemplateResponse(
        "public/capacitacion_detalle.html",
        {
            "request":      request,
            "org":          _org_publica_dict(request),
            "theme":        getattr(request.state, "theme", None),
            "capacitacion": _bulletin_dict(b),
        },
    )


# ── Convenios ──
@public_router.get("/convenios", response_class=HTMLResponse)
async def public_convenios(
    request: Request,
    db: Session = Depends(get_db),
):
    org_id = _org_publica(request)
    items = (
        db.query(Partner)
        .filter(or_(Partner.organization_id == org_id, Partner.organization_id.is_(None)))
        .order_by(desc(Partner.is_promoted), desc(Partner.is_verified), asc(Partner.name))
        .all()
    )
    convenios = [_partner_dict(p) for p in items]
    categorias = sorted({c["category"] for c in convenios if c.get("category")})
    return templates.TemplateResponse(
        "public/convenios.html",
        {
            "request":    request,
            "org":        _org_publica_dict(request),
            "theme":      getattr(request.state, "theme", None),
            "convenios":  convenios,
            "categorias": categorias,
        },
    )


# ============================================================
# API /api/cms/*
# ============================================================
router = APIRouter(prefix="/api/cms", tags=["CMS"])


# ────────────────────────────────────────────────────────────
# UPLOAD DE IMÁGENES A GCS (zClaude-56 PARTE A)
# ────────────────────────────────────────────────────────────
_CARPETAS_VALIDAS = {
    "carrusel", "comunicados", "capacitaciones", "convenios",
    "ambientes", "tienda", "cms",
}
_CARPETAS_PDF = {
    "comunicados", "capacitaciones", "convenios",
    "documentos", "reglamentos",
}
_TIPOS_IMG_VALIDOS = {
    "image/jpeg", "image/jpg", "image/pjpeg",
    "image/png", "image/webp", "image/gif",
}
_TIPOS_PDF_VALIDOS = {"application/pdf"}
_MAX_IMG_SIZE = 5 * 1024 * 1024     # 5 MB
_MAX_PDF_SIZE = 20 * 1024 * 1024    # 20 MB


@router.post("/upload-imagen")
async def upload_imagen_cms(
    request: Request,
    file: UploadFile = File(...),
    carpeta: str = Form("cms"),
    member: Member = Depends(require_admin_or_editor),
):
    """Sube una imagen al bucket GCS y devuelve la URL pública.
    Usado por todos los formularios del panel CMS."""
    from app.utils.gcs import upload_cms_imagen

    ct = (file.content_type or "").lower()
    if ct not in _TIPOS_IMG_VALIDOS:
        raise HTTPException(400, "Solo se aceptan imágenes JPG, PNG, WebP o GIF")

    carpeta_norm = (carpeta or "").strip().lower()
    if carpeta_norm not in _CARPETAS_VALIDAS:
        carpeta_norm = "cms"

    contenido = await file.read()
    if len(contenido) > _MAX_IMG_SIZE:
        raise HTTPException(400, "Imagen demasiado grande (máx 5 MB)")
    if not contenido:
        raise HTTPException(400, "Archivo vacío")

    org_id = _org_id(request, member)
    url = upload_cms_imagen(
        file_bytes      = contenido,
        filename        = file.filename or "image.jpg",
        content_type    = ct,
        organization_id = org_id,
        carpeta         = carpeta_norm,
    )
    if not url:
        raise HTTPException(500, "GCS no disponible o falló la subida")

    return {"ok": True, "url": url, "carpeta": carpeta_norm}


@router.post("/upload-pdf")
async def upload_pdf_cms(
    request: Request,
    file: UploadFile = File(...),
    carpeta: str = Form("documentos"),
    member: Member = Depends(require_admin_or_editor),
):
    """Sube un PDF al bucket GCS y devuelve la URL pública + nombre original."""
    from app.utils.gcs import upload_cms_imagen

    ct = (file.content_type or "").lower()
    if ct not in _TIPOS_PDF_VALIDOS:
        raise HTTPException(400, "Solo se aceptan archivos PDF")

    carpeta_norm = (carpeta or "").strip().lower()
    if carpeta_norm not in _CARPETAS_PDF:
        carpeta_norm = "documentos"

    contenido = await file.read()
    if len(contenido) > _MAX_PDF_SIZE:
        raise HTTPException(400, "PDF demasiado grande (máx 20 MB)")
    if not contenido:
        raise HTTPException(400, "Archivo vacío")

    org_id = _org_id(request, member)
    url = upload_cms_imagen(
        file_bytes      = contenido,
        filename        = file.filename or "documento.pdf",
        content_type    = "application/pdf",
        organization_id = org_id,
        carpeta         = carpeta_norm,
    )
    if not url:
        raise HTTPException(500, "GCS no disponible o falló la subida")

    return {
        "ok":      True,
        "url":     url,
        "nombre":  file.filename or "documento.pdf",
        "carpeta": carpeta_norm,
    }


# ────────────────────────────────────────────────────────────
# C1. CARRUSEL
# ────────────────────────────────────────────────────────────
def _slide_dict(s: CarruselSlide) -> dict:
    return {
        "id":          s.id,
        "orden":       s.orden or 0,
        "imagen_url":  s.imagen_url,
        "titulo":      s.titulo or "",
        "subtitulo":   s.subtitulo or "",
        "boton_texto": s.boton_texto or "",
        "boton_url":   s.boton_url or "",
        "activo":      bool(s.activo),
        "created_at":  _a_lima(s.created_at),
        "updated_at":  _a_lima(s.updated_at),
    }


@router.get("/carrusel")
async def listar_slides(
    request: Request,
    db: Session = Depends(get_db),
    member: Member = Depends(require_admin_or_editor),
):
    org_id = _org_id(request, member)
    slides = (
        db.query(CarruselSlide)
        .filter(CarruselSlide.organization_id == org_id)
        .order_by(asc(CarruselSlide.orden), asc(CarruselSlide.id))
        .all()
    )
    return {"ok": True, "items": [_slide_dict(s) for s in slides]}


@router.post("/carrusel")
async def crear_slide(
    request: Request,
    body: dict = Body(...),
    db: Session = Depends(get_db),
    member: Member = Depends(require_admin_or_editor),
):
    org_id = _org_id(request, member)
    imagen = (body.get("imagen_url") or "").strip()
    if not imagen:
        raise HTTPException(400, "imagen_url es requerida")

    max_orden = (
        db.query(CarruselSlide)
        .filter(CarruselSlide.organization_id == org_id)
        .order_by(desc(CarruselSlide.orden))
        .first()
    )
    siguiente = (max_orden.orden + 1) if max_orden else 1

    s = CarruselSlide(
        organization_id = org_id,
        orden           = int(body.get("orden") or siguiente),
        imagen_url      = imagen,
        titulo          = (body.get("titulo") or "")[:200],
        subtitulo       = (body.get("subtitulo") or "")[:300],
        boton_texto     = (body.get("boton_texto") or "")[:100],
        boton_url       = (body.get("boton_url") or "")[:300],
        activo          = bool(body.get("activo", True)),
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return {"ok": True, "item": _slide_dict(s)}


@router.put("/carrusel/{slide_id}")
async def editar_slide(
    slide_id: int,
    body: dict = Body(...),
    db: Session = Depends(get_db),
    member: Member = Depends(require_admin_or_editor),
):
    s = db.query(CarruselSlide).filter(CarruselSlide.id == slide_id).first()
    if not s:
        raise HTTPException(404, "Slide no encontrado")

    if "imagen_url" in body:
        v = (body.get("imagen_url") or "").strip()
        if v: s.imagen_url = v
    if "titulo"      in body: s.titulo      = (body.get("titulo") or "")[:200]
    if "subtitulo"   in body: s.subtitulo   = (body.get("subtitulo") or "")[:300]
    if "boton_texto" in body: s.boton_texto = (body.get("boton_texto") or "")[:100]
    if "boton_url"   in body: s.boton_url   = (body.get("boton_url") or "")[:300]
    if "activo"      in body: s.activo      = bool(body.get("activo"))
    if "orden"       in body and body.get("orden") is not None:
        try: s.orden = int(body.get("orden"))
        except (TypeError, ValueError): pass

    db.commit()
    db.refresh(s)
    return {"ok": True, "item": _slide_dict(s)}


@router.delete("/carrusel/{slide_id}")
async def eliminar_slide(
    slide_id: int,
    db: Session = Depends(get_db),
    member: Member = Depends(require_admin_or_editor),
):
    s = db.query(CarruselSlide).filter(CarruselSlide.id == slide_id).first()
    if not s:
        raise HTTPException(404, "Slide no encontrado")
    db.delete(s)
    db.commit()
    return {"ok": True}


@router.put("/carrusel/{slide_id}/orden")
async def mover_slide(
    slide_id: int,
    body: dict = Body(...),
    db: Session = Depends(get_db),
    member: Member = Depends(require_admin_or_editor),
):
    """body.direccion: 'subir' | 'bajar'"""
    direccion = (body.get("direccion") or "").lower()
    if direccion not in ("subir", "bajar"):
        raise HTTPException(400, "direccion debe ser 'subir' o 'bajar'")

    s = db.query(CarruselSlide).filter(CarruselSlide.id == slide_id).first()
    if not s:
        raise HTTPException(404, "Slide no encontrado")

    q = db.query(CarruselSlide).filter(CarruselSlide.organization_id == s.organization_id)
    if direccion == "subir":
        vecino = (
            q.filter(CarruselSlide.orden < (s.orden or 0))
            .order_by(desc(CarruselSlide.orden))
            .first()
        )
    else:
        vecino = (
            q.filter(CarruselSlide.orden > (s.orden or 0))
            .order_by(asc(CarruselSlide.orden))
            .first()
        )

    if vecino:
        s.orden, vecino.orden = vecino.orden, s.orden
        db.commit()

    return {"ok": True}


# ────────────────────────────────────────────────────────────
# C2. COMUNICADOS y CAPACITACIONES (Bulletin)
# ────────────────────────────────────────────────────────────
def _strip_html(texto: str) -> str:
    """Quita etiquetas HTML para previews seguros en listados."""
    import re as _re
    if not texto:
        return ""
    return _re.sub(r"<[^>]+>", "", texto).strip()


def _bulletin_dict(b: Bulletin) -> dict:
    content_raw = b.content or ""
    preview_txt = _strip_html(content_raw)
    if len(preview_txt) > 150:
        preview_txt = preview_txt[:150].rstrip() + "..."

    return {
        "id":                    b.id,
        "title":                 b.title or "",
        "content":               content_raw,
        "preview":               preview_txt,
        "image_url":             b.image_url or "",
        "file_url":              b.file_url or "",
        "video_url":             b.video_url or "",
        "priority":              b.priority or "info",
        "tipo":                  b.tipo or "comunicado",
        "fecha_evento":          _a_lima(b.fecha_evento),
        "fecha_evento_iso":      b.fecha_evento.isoformat() if b.fecha_evento else None,
        "lugar_evento":          b.lugar_evento or "",
        "expires_at":            _a_lima(b.expires_at),
        "expires_at_iso":        b.expires_at.isoformat() if b.expires_at else None,
        "requiere_confirmacion": bool(b.requiere_confirmacion),
        "created_at":            _a_lima(b.created_at),
        "fecha":                 _a_lima(b.created_at),
    }


def _listar_bulletins(
    request: Request, member: Member, db: Session,
    tipo: str, page: int, per_page: int, search: str,
):
    org_id = _org_id(request, member)
    q = db.query(Bulletin).filter(
        Bulletin.organization_id == org_id,
        Bulletin.tipo == tipo,
    )
    if search:
        like = f"%{search}%"
        q = q.filter(or_(Bulletin.title.ilike(like), Bulletin.content.ilike(like)))

    total = q.count()
    items = (
        q.order_by(desc(Bulletin.created_at))
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    return {
        "ok":       True,
        "total":    total,
        "page":     page,
        "per_page": per_page,
        "items":    [_bulletin_dict(b) for b in items],
    }


def _crear_bulletin(
    request: Request, member: Member, db: Session, body: dict, tipo: str,
):
    org_id = _org_id(request, member)
    title = (body.get("title") or body.get("titulo") or "").strip()
    if not title:
        raise HTTPException(400, "title es requerido")

    b = Bulletin(
        organization_id        = org_id,
        author_id              = member.id,
        title                  = title[:300],
        content                = body.get("content") or body.get("contenido") or "",
        image_url              = (body.get("image_url") or "")[:500] or None,
        file_url               = (body.get("file_url") or "")[:500] or None,
        video_url              = (body.get("video_url") or "")[:500] or None,
        priority               = (body.get("priority") or "info")[:30],
        tipo                   = tipo,
        fecha_evento           = _parse_iso(body.get("fecha_evento")),
        lugar_evento           = (body.get("lugar_evento") or "")[:200] or None,
        expires_at             = _parse_iso(body.get("expires_at")),
        requiere_confirmacion  = bool(body.get("requiere_confirmacion", False)),
    )
    db.add(b)
    db.commit()
    db.refresh(b)
    return _bulletin_dict(b)


def _editar_bulletin(db: Session, bulletin_id: int, body: dict, tipo: str):
    b = (
        db.query(Bulletin)
        .filter(Bulletin.id == bulletin_id, Bulletin.tipo == tipo)
        .first()
    )
    if not b:
        raise HTTPException(404, f"{tipo.capitalize()} no encontrado")

    if "title"     in body or "titulo" in body:
        v = (body.get("title") or body.get("titulo") or "").strip()
        if v: b.title = v[:300]
    if "content"   in body or "contenido" in body:
        b.content = body.get("content") or body.get("contenido") or ""
    if "image_url" in body: b.image_url = (body.get("image_url") or "")[:500] or None
    if "file_url"  in body: b.file_url  = (body.get("file_url")  or "")[:500] or None
    if "video_url" in body: b.video_url = (body.get("video_url") or "")[:500] or None
    if "priority"  in body: b.priority  = (body.get("priority")  or "info")[:30]
    if "lugar_evento" in body: b.lugar_evento = (body.get("lugar_evento") or "")[:200] or None
    if "fecha_evento" in body: b.fecha_evento = _parse_iso(body.get("fecha_evento"))
    if "expires_at"   in body: b.expires_at   = _parse_iso(body.get("expires_at"))
    if "requiere_confirmacion" in body:
        b.requiere_confirmacion = bool(body.get("requiere_confirmacion"))

    db.commit()
    db.refresh(b)
    return _bulletin_dict(b)


def _eliminar_bulletin(db: Session, bulletin_id: int, tipo: str):
    b = (
        db.query(Bulletin)
        .filter(Bulletin.id == bulletin_id, Bulletin.tipo == tipo)
        .first()
    )
    if not b:
        raise HTTPException(404, f"{tipo.capitalize()} no encontrado")
    db.delete(b)
    db.commit()
    return {"ok": True}


# ── Comunicados ──
@router.get("/comunicados")
async def listar_comunicados(
    request: Request,
    page: int = 1, per_page: int = 50, search: str = "",
    db: Session = Depends(get_db),
    member: Member = Depends(require_admin_or_editor),
):
    return _listar_bulletins(request, member, db, "comunicado", page, per_page, search)


@router.post("/comunicados")
async def crear_comunicado(
    request: Request,
    body: dict = Body(...),
    db: Session = Depends(get_db),
    member: Member = Depends(require_admin_or_editor),
):
    return {"ok": True, "item": _crear_bulletin(request, member, db, body, "comunicado")}


@router.put("/comunicados/{bulletin_id}")
async def editar_comunicado(
    bulletin_id: int,
    body: dict = Body(...),
    db: Session = Depends(get_db),
    member: Member = Depends(require_admin_or_editor),
):
    return {"ok": True, "item": _editar_bulletin(db, bulletin_id, body, "comunicado")}


@router.delete("/comunicados/{bulletin_id}")
async def eliminar_comunicado(
    bulletin_id: int,
    db: Session = Depends(get_db),
    member: Member = Depends(require_admin_or_editor),
):
    return _eliminar_bulletin(db, bulletin_id, "comunicado")


# ── Capacitaciones ──
@router.get("/capacitaciones")
async def listar_capacitaciones(
    request: Request,
    page: int = 1, per_page: int = 50, search: str = "",
    db: Session = Depends(get_db),
    member: Member = Depends(require_admin_or_editor),
):
    return _listar_bulletins(request, member, db, "capacitacion", page, per_page, search)


@router.post("/capacitaciones")
async def crear_capacitacion(
    request: Request,
    body: dict = Body(...),
    db: Session = Depends(get_db),
    member: Member = Depends(require_admin_or_editor),
):
    return {"ok": True, "item": _crear_bulletin(request, member, db, body, "capacitacion")}


@router.put("/capacitaciones/{bulletin_id}")
async def editar_capacitacion(
    bulletin_id: int,
    body: dict = Body(...),
    db: Session = Depends(get_db),
    member: Member = Depends(require_admin_or_editor),
):
    return {"ok": True, "item": _editar_bulletin(db, bulletin_id, body, "capacitacion")}


@router.delete("/capacitaciones/{bulletin_id}")
async def eliminar_capacitacion(
    bulletin_id: int,
    db: Session = Depends(get_db),
    member: Member = Depends(require_admin_or_editor),
):
    return _eliminar_bulletin(db, bulletin_id, "capacitacion")


# ────────────────────────────────────────────────────────────
# C3. CONVENIOS (partners)
# ────────────────────────────────────────────────────────────
def _partner_dict(p: Partner) -> dict:
    return {
        "id":           p.id,
        "name":         p.name or "",
        "category":     p.category or "",
        "description":  p.description or "",
        "logo_url":     p.logo_url or "",
        "cover_url":    p.cover_url or "",
        "phone":        p.phone or "",
        "whatsapp":     p.whatsapp or "",
        "website_url":  p.website_url or "",
        "is_verified":  bool(p.is_verified),
        "is_promoted":  bool(p.is_promoted),
    }


@router.get("/convenios")
async def listar_convenios(
    request: Request,
    db: Session = Depends(get_db),
    member: Member = Depends(require_admin_or_editor),
):
    org_id = _org_id(request, member)
    items = (
        db.query(Partner)
        .filter(or_(Partner.organization_id == org_id, Partner.organization_id.is_(None)))
        .order_by(desc(Partner.is_promoted), asc(Partner.name))
        .all()
    )
    return {"ok": True, "items": [_partner_dict(p) for p in items]}


@router.post("/convenios")
async def crear_convenio(
    request: Request,
    body: dict = Body(...),
    db: Session = Depends(get_db),
    member: Member = Depends(require_admin_or_editor),
):
    org_id = _org_id(request, member)
    name = (body.get("name") or body.get("nombre") or "").strip()
    if not name:
        raise HTTPException(400, "name es requerido")

    p = Partner(
        organization_id = org_id,
        name            = name[:200],
        category        = (body.get("category") or "")[:100] or None,
        description     = body.get("description") or None,
        logo_url        = (body.get("logo_url") or "")[:500] or None,
        cover_url       = (body.get("cover_url") or "")[:500] or None,
        phone           = (body.get("phone") or "")[:50] or None,
        whatsapp        = (body.get("whatsapp") or "")[:50] or None,
        website_url     = (body.get("website_url") or "")[:300] or None,
        is_verified     = bool(body.get("is_verified", False)),
        is_promoted     = bool(body.get("is_promoted", False)),
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return {"ok": True, "item": _partner_dict(p)}


@router.put("/convenios/{partner_id}")
async def editar_convenio(
    partner_id: int,
    body: dict = Body(...),
    db: Session = Depends(get_db),
    member: Member = Depends(require_admin_or_editor),
):
    p = db.query(Partner).filter(Partner.id == partner_id).first()
    if not p:
        raise HTTPException(404, "Convenio no encontrado")

    for clave, max_len in [
        ("name", 200), ("category", 100), ("logo_url", 500), ("cover_url", 500),
        ("phone", 50), ("whatsapp", 50), ("website_url", 300),
    ]:
        if clave in body:
            v = (body.get(clave) or "").strip()
            setattr(p, clave, v[:max_len] if v else None)
    if "description" in body:
        p.description = body.get("description") or None
    if "is_verified" in body: p.is_verified = bool(body.get("is_verified"))
    if "is_promoted" in body: p.is_promoted = bool(body.get("is_promoted"))

    db.commit()
    db.refresh(p)
    return {"ok": True, "item": _partner_dict(p)}


@router.delete("/convenios/{partner_id}")
async def eliminar_convenio(
    partner_id: int,
    db: Session = Depends(get_db),
    member: Member = Depends(require_admin_or_editor),
):
    p = db.query(Partner).filter(Partner.id == partner_id).first()
    if not p:
        raise HTTPException(404, "Convenio no encontrado")
    db.delete(p)
    db.commit()
    return {"ok": True}


# ────────────────────────────────────────────────────────────
# C4 + C5. RESOURCES (ambientes y productos de tienda)
# ────────────────────────────────────────────────────────────
def _resource_dict(r: Resource) -> dict:
    rules = r.rules or {}
    if not isinstance(rules, dict):
        rules = {}
    precio_attr = float(r.precio) if getattr(r, "precio", None) is not None else None
    return {
        "id":                r.id,
        "name":               r.name or "",
        "tipo":               getattr(r, "tipo", None) or "ambiente",
        "is_active":          bool(r.is_active),
        "imagen_url":         getattr(r, "imagen_url", None) or "",
        "descripcion":        getattr(r, "descripcion", None) or "",
        "precio":             precio_attr,
        "stock":              getattr(r, "stock", None) or 0,
        # Campos especificos de ambientes (alojados en rules)
        "precio_colegiado":   rules.get("precio_colegiado"),
        "precio_publico":     rules.get("precio_publico"),
        "horarios":           rules.get("horarios"),
        "requisitos":         rules.get("requisitos"),
        "aforo":              rules.get("aforo"),
        "rules":              rules,
    }


def _aplicar_campos_ambiente(r: Resource, body: dict):
    rules = dict(r.rules or {})
    cambio = False
    for k in ("precio_colegiado", "precio_publico", "horarios", "requisitos", "aforo"):
        if k in body:
            v = body.get(k)
            if v in ("", None):
                rules.pop(k, None)
            else:
                if k in ("precio_colegiado", "precio_publico", "aforo"):
                    try:
                        v = float(v) if k != "aforo" else int(v)
                    except (TypeError, ValueError):
                        continue
                rules[k] = v
            cambio = True
    if cambio:
        r.rules = rules


# ── Ambientes ──
@router.get("/ambientes")
async def listar_ambientes(
    request: Request,
    db: Session = Depends(get_db),
    member: Member = Depends(require_admin_or_editor),
):
    org_id = _org_id(request, member)
    items = (
        db.query(Resource)
        .filter(
            Resource.organization_id == org_id,
            (Resource.tipo == "ambiente") | (Resource.tipo.is_(None)),
        )
        .order_by(asc(Resource.name))
        .all()
    )
    return {"ok": True, "items": [_resource_dict(r) for r in items]}


@router.post("/ambientes")
async def crear_ambiente(
    request: Request,
    body: dict = Body(...),
    db: Session = Depends(get_db),
    member: Member = Depends(require_admin_or_editor),
):
    org_id = _org_id(request, member)
    name = (body.get("name") or body.get("nombre") or "").strip()
    if not name:
        raise HTTPException(400, "name es requerido")

    r = Resource(
        organization_id = org_id,
        name            = name[:150],
        tipo            = "ambiente",
        is_active       = bool(body.get("is_active", True)),
        imagen_url      = (body.get("imagen_url") or "")[:500] or None,
        descripcion     = body.get("descripcion") or None,
        rules           = {},
    )
    _aplicar_campos_ambiente(r, body)
    db.add(r)
    db.commit()
    db.refresh(r)
    return {"ok": True, "item": _resource_dict(r)}


@router.put("/ambientes/{resource_id}")
async def editar_ambiente(
    resource_id: int,
    body: dict = Body(...),
    db: Session = Depends(get_db),
    member: Member = Depends(require_admin_or_editor),
):
    r = db.query(Resource).filter(Resource.id == resource_id).first()
    if not r:
        raise HTTPException(404, "Ambiente no encontrado")

    if "name"        in body or "nombre" in body:
        v = (body.get("name") or body.get("nombre") or "").strip()
        if v: r.name = v[:150]
    if "is_active"   in body: r.is_active   = bool(body.get("is_active"))
    if "imagen_url"  in body: r.imagen_url  = (body.get("imagen_url") or "")[:500] or None
    if "descripcion" in body: r.descripcion = body.get("descripcion") or None

    _aplicar_campos_ambiente(r, body)
    if r.tipo is None:
        r.tipo = "ambiente"

    db.commit()
    db.refresh(r)
    return {"ok": True, "item": _resource_dict(r)}


@router.delete("/ambientes/{resource_id}")
async def eliminar_ambiente(
    resource_id: int,
    db: Session = Depends(get_db),
    member: Member = Depends(require_admin_or_editor),
):
    r = db.query(Resource).filter(Resource.id == resource_id).first()
    if not r:
        raise HTTPException(404, "Ambiente no encontrado")
    db.delete(r)
    db.commit()
    return {"ok": True}


# ── Tienda (productos · ConceptoCobro categoria='mercaderia') ──
def _producto_tienda_dict(p: ConceptoCobro) -> dict:
    return {
        "id":           p.id,
        "codigo":       p.codigo,
        "nombre":       p.nombre or "",
        "descripcion":  p.descripcion or "",
        "precio":       float(p.monto_base or 0),
        "stock":        int(p.stock_actual or 0),
        "stock_min":    int(p.stock_minimo or 0),
        "maneja_stock": bool(p.maneja_stock),
        "activo":       bool(p.activo),
        "orden":        int(p.orden or 0),
        "imagen_url":   getattr(p, "imagen_url", None) or "",
        "is_active":    bool(p.activo),  # alias para compatibilidad UI
    }


@router.get("/tienda")
async def listar_productos(
    request: Request,
    db: Session = Depends(get_db),
    member: Member = Depends(require_admin_or_editor),
):
    org_id = _org_id(request, member)
    items = (
        db.query(ConceptoCobro)
        .filter(
            ConceptoCobro.organization_id == org_id,
            ConceptoCobro.categoria == "mercaderia",
        )
        .order_by(asc(ConceptoCobro.orden), asc(ConceptoCobro.nombre))
        .all()
    )
    return {"ok": True, "items": [_producto_tienda_dict(p) for p in items]}


@router.post("/tienda")
async def crear_producto(
    request: Request,
    body: dict = Body(...),
    db: Session = Depends(get_db),
    member: Member = Depends(require_admin_or_editor),
):
    import uuid as _uuid

    org_id = _org_id(request, member)
    nombre = (body.get("nombre") or body.get("name") or "").strip()
    if not nombre:
        raise HTTPException(400, "nombre es requerido")

    codigo = (body.get("codigo") or "").strip().upper()
    if not codigo:
        codigo = f"MERC-{_uuid.uuid4().hex[:4].upper()}"
    if (
        db.query(ConceptoCobro.id)
        .filter(
            ConceptoCobro.organization_id == org_id,
            ConceptoCobro.codigo == codigo,
        )
        .first()
    ):
        raise HTTPException(400, f"Ya existe un concepto con código '{codigo}'")

    try:    precio = float(body.get("precio") or 0)
    except (TypeError, ValueError): precio = 0.0
    try:    stock = int(body.get("stock") or 0)
    except (TypeError, ValueError): stock = 0
    try:    stock_min = int(body.get("stock_min") or 0)
    except (TypeError, ValueError): stock_min = 0
    try:    orden = int(body.get("orden") or 0)
    except (TypeError, ValueError): orden = 0

    actor_id = getattr(member, "user_id", None) or getattr(member, "id", None)

    p = ConceptoCobro(
        organization_id          = org_id,
        codigo                   = codigo[:20],
        nombre                   = nombre[:150],
        descripcion              = body.get("descripcion") or None,
        categoria                = "mercaderia",
        periodicidad             = "unico",
        monto_base               = precio,
        maneja_stock             = True,
        stock_actual             = stock,
        stock_minimo             = stock_min,
        activo                   = bool(body.get("activo", body.get("is_active", True))),
        orden                    = orden,
        requiere_colegiado       = False,
        aplica_a_publico         = True,
        genera_deuda             = False,
        requiere_aprobacion      = False,
        genera_comprobante       = True,
        tipo_comprobante_default = "03",
        afecto_igv               = False,
        tipo_afectacion_igv      = "20",
        imagen_url               = (body.get("imagen_url") or "")[:500] or None,
        created_by               = actor_id,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return {"ok": True, "item": _producto_tienda_dict(p)}


@router.put("/tienda/{producto_id}")
async def editar_producto(
    producto_id: int,
    request: Request,
    body: dict = Body(...),
    db: Session = Depends(get_db),
    member: Member = Depends(require_admin_or_editor),
):
    org_id = _org_id(request, member)
    p = (
        db.query(ConceptoCobro)
        .filter(
            ConceptoCobro.id == producto_id,
            ConceptoCobro.organization_id == org_id,
            ConceptoCobro.categoria == "mercaderia",
        )
        .first()
    )
    if not p:
        raise HTTPException(404, "Producto no encontrado")

    if "nombre" in body or "name" in body:
        v = (body.get("nombre") or body.get("name") or "").strip()
        if v: p.nombre = v[:150]
    if "descripcion" in body: p.descripcion = body.get("descripcion") or None
    if "imagen_url"  in body: p.imagen_url  = (body.get("imagen_url") or "")[:500] or None
    if "activo"      in body: p.activo      = bool(body.get("activo"))
    elif "is_active" in body: p.activo      = bool(body.get("is_active"))
    if "precio" in body:
        try: p.monto_base = float(body.get("precio") or 0)
        except (TypeError, ValueError): pass
    if "stock" in body:
        try: p.stock_actual = int(body.get("stock") or 0)
        except (TypeError, ValueError): pass
    if "stock_min" in body:
        try: p.stock_minimo = int(body.get("stock_min") or 0)
        except (TypeError, ValueError): pass
    if "orden" in body:
        try: p.orden = int(body.get("orden") or 0)
        except (TypeError, ValueError): pass

    db.commit()
    db.refresh(p)
    return {"ok": True, "item": _producto_tienda_dict(p)}


@router.delete("/tienda/{producto_id}")
async def desactivar_producto(
    producto_id: int,
    request: Request,
    db: Session = Depends(get_db),
    member: Member = Depends(require_admin_or_editor),
):
    """Soft-delete: solo desactiva (activo=False) para no romper FKs históricas."""
    org_id = _org_id(request, member)
    p = (
        db.query(ConceptoCobro)
        .filter(
            ConceptoCobro.id == producto_id,
            ConceptoCobro.organization_id == org_id,
            ConceptoCobro.categoria == "mercaderia",
        )
        .first()
    )
    if not p:
        raise HTTPException(404, "Producto no encontrado")
    p.activo = False
    db.commit()
    return {"ok": True, "mensaje": "Producto desactivado"}


# ============================================================
# HELPERS PÚBLICOS — usados por el endpoint home (/) para inyectar
# datos dinámicos (PARTE E del plan zClaude-55).
# ============================================================
def get_home_context(db: Session, organization_id: int = 1) -> dict:
    """
    Devuelve el contexto dinámico que el home público debe consumir:
      - carrusel_slides (activos, ordenados)
      - comunicados     (últimos 3 sin expirar)
      - capacitaciones  (próximas 4 con fecha_evento >= hoy)
      - convenios       (verificados; primeros)
      - ambientes       (activos)

    Manejo defensivo: si una tabla aún no existe (ej. carrusel_slides
    en entornos sin migrar), se devuelve lista vacía y se loggea.
    """
    ahora = datetime.now(timezone.utc)
    ctx = {
        "carrusel_slides":  [],
        "comunicados":      [],
        "capacitaciones":   [],
        "convenios":        [],
        "ambientes":        [],
        "productos_tienda": [],
    }

    try:
        slides = (
            db.query(CarruselSlide)
            .filter(
                CarruselSlide.organization_id == organization_id,
                CarruselSlide.activo.is_(True),
            )
            .order_by(asc(CarruselSlide.orden), asc(CarruselSlide.id))
            .all()
        )
        ctx["carrusel_slides"] = [_slide_dict(s) for s in slides]
    except Exception as e:
        logger.warning("get_home_context: carrusel_slides no disponible: %s", e)

    try:
        comunicados = (
            db.query(Bulletin)
            .filter(
                Bulletin.organization_id == organization_id,
                Bulletin.tipo == "comunicado",
                or_(Bulletin.expires_at.is_(None), Bulletin.expires_at > ahora),
            )
            .order_by(desc(Bulletin.created_at))
            .limit(3)
            .all()
        )
        ctx["comunicados"] = [_bulletin_dict(b) for b in comunicados]
    except Exception as e:
        logger.warning("get_home_context: comunicados no disponibles: %s", e)

    try:
        capacitaciones = (
            db.query(Bulletin)
            .filter(
                Bulletin.organization_id == organization_id,
                Bulletin.tipo == "capacitacion",
                or_(Bulletin.fecha_evento.is_(None), Bulletin.fecha_evento >= ahora),
            )
            .order_by(asc(Bulletin.fecha_evento))
            .limit(4)
            .all()
        )
        ctx["capacitaciones"] = [_bulletin_dict(b) for b in capacitaciones]
    except Exception as e:
        logger.warning("get_home_context: capacitaciones no disponibles: %s", e)

    try:
        convenios = (
            db.query(Partner)
            .filter(or_(Partner.organization_id == organization_id, Partner.organization_id.is_(None)))
            .order_by(desc(Partner.is_promoted), desc(Partner.is_verified), asc(Partner.name))
            .limit(24)
            .all()
        )
        ctx["convenios"] = [_partner_dict(p) for p in convenios]
    except Exception as e:
        logger.warning("get_home_context: convenios no disponibles: %s", e)

    try:
        ambientes = (
            db.query(Resource)
            .filter(
                Resource.organization_id == organization_id,
                Resource.is_active.is_(True),
                (Resource.tipo == "ambiente") | (Resource.tipo.is_(None)),
            )
            .order_by(asc(Resource.name))
            .all()
        )
        ctx["ambientes"] = [_resource_dict(r) for r in ambientes]
    except Exception as e:
        logger.warning("get_home_context: ambientes no disponibles: %s", e)

    try:
        productos = (
            db.query(ConceptoCobro)
            .filter(
                ConceptoCobro.organization_id == organization_id,
                ConceptoCobro.categoria == "mercaderia",
                ConceptoCobro.activo.is_(True),
            )
            .order_by(asc(ConceptoCobro.orden), asc(ConceptoCobro.nombre))
            .all()
        )
        ctx["productos_tienda"] = [
            {
                "id":         p.id,
                "codigo":     p.codigo,
                "nombre":     p.nombre or "",
                "precio":     float(p.monto_base or 0),
                "stock":      int(p.stock_actual or 0),
                "imagen_url": getattr(p, "imagen_url", None) or "",
                "agotado":    bool(p.maneja_stock and (p.stock_actual or 0) <= 0),
            }
            for p in productos
        ]
    except Exception as e:
        logger.warning("get_home_context: productos_tienda no disponibles: %s", e)

    return ctx

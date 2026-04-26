"""
app/routers/catalogo.py — Catálogo de Servicios (zClaude-59).

Panel admin para gestionar conceptos_cobro: cuotas, multas, constancias,
derechos, capacitaciones, alquileres, recreación, mercadería, etc.

Acceso: rol 'admin' EXCLUSIVAMENTE. El rol 'editor' (CMS público) no
debe llegar acá — esto es configuración financiera.
"""
from typing import Optional, List
import logging

from fastapi import APIRouter, Depends, HTTPException, Body, Request, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import asc, desc, func

from app.database import get_db
from app.models import Member, Organization, ConceptoCobro
from app.routers.dashboard import get_current_member
from app.utils.templates import templates

logger = logging.getLogger(__name__)


CATEGORIAS_VALIDAS = (
    "cuotas", "extraordinarias", "multas", "constancias", "derechos",
    "capacitacion", "alquileres", "recreacion", "mercaderia", "otros",
)
PERIODICIDADES_VALIDAS = ("mensual", "anual", "unico", "por_uso", "variable")
TIPOS_COMPROBANTE = ("01", "03")            # 01=Factura, 03=Boleta
TIPOS_AFECTACION_IGV = ("10", "20", "30")   # 10=Gravado, 20=Exonerado, 30=Inafecto


def require_admin(current_member: Member = Depends(get_current_member)) -> Member:
    if current_member.role != "admin":
        raise HTTPException(403, "Acceso restringido al rol admin")
    return current_member


def _org_id(request: Request, member: Member) -> int:
    org = getattr(request.state, "org", None)
    if isinstance(org, dict) and org.get("id"):
        return org["id"]
    return member.organization_id or 1


def _concepto_dict(c: ConceptoCobro) -> dict:
    return {
        "id":                       c.id,
        "codigo":                   c.codigo,
        "nombre":                   c.nombre or "",
        "nombre_corto":             c.nombre_corto or "",
        "descripcion":              c.descripcion or "",
        "categoria":                c.categoria or "otros",
        "periodicidad":             c.periodicidad or "unico",
        "monto_base":               float(c.monto_base or 0),
        "monto_minimo":             float(c.monto_minimo or 0),
        "monto_maximo":             float(c.monto_maximo or 0),
        "permite_monto_libre":      bool(c.permite_monto_libre),
        "afecto_igv":               bool(c.afecto_igv),
        "tipo_afectacion_igv":      c.tipo_afectacion_igv or "20",
        "genera_comprobante":       bool(c.genera_comprobante),
        "tipo_comprobante_default": c.tipo_comprobante_default or "03",
        "requiere_colegiado":       bool(c.requiere_colegiado),
        "aplica_a_publico":         bool(c.aplica_a_publico),
        "genera_deuda":             bool(c.genera_deuda),
        "requiere_aprobacion":      bool(c.requiere_aprobacion),
        "es_cuota_mensual":         bool(c.es_cuota_mensual),
        "dia_vencimiento":          int(c.dia_vencimiento or 0),
        "meses_aplicables":         c.meses_aplicables or "",
        "maneja_stock":             bool(c.maneja_stock),
        "stock_actual":             int(c.stock_actual or 0),
        "stock_minimo":             int(c.stock_minimo or 0),
        "imagen_url":               getattr(c, "imagen_url", None) or "",
        "activo":                   bool(c.activo),
        "orden":                    int(c.orden or 0),
    }


# ============================================================
# PÁGINA HTML /admin/catalogo
# ============================================================
page_router = APIRouter(tags=["Catálogo"])


@page_router.get("/admin/catalogo", response_class=HTMLResponse)
async def catalogo_index(
    request: Request,
    member: Member = Depends(require_admin),
):
    return templates.TemplateResponse(
        "pages/admin/catalogo.html",
        {
            "request": request,
            "user": {
                "id":   member.id,
                "name": member.user.name if member.user else "Admin",
                "role": member.role,
            },
            "categorias_validas":     list(CATEGORIAS_VALIDAS),
            "periodicidades_validas": list(PERIODICIDADES_VALIDAS),
        },
    )


# ============================================================
# API /api/catalogo/*
# ============================================================
router = APIRouter(prefix="/api/catalogo", tags=["Catálogo"])


@router.get("/categorias")
async def listar_categorias(
    request: Request,
    db: Session = Depends(get_db),
    member: Member = Depends(require_admin),
):
    """Devuelve las categorías reales en BD con su conteo + las definidas en código."""
    org_id = _org_id(request, member)
    rows = (
        db.query(ConceptoCobro.categoria, func.count(ConceptoCobro.id))
        .filter(ConceptoCobro.organization_id == org_id)
        .group_by(ConceptoCobro.categoria)
        .all()
    )
    en_bd = {(cat or "otros"): int(n) for cat, n in rows}
    items = []
    for cat in CATEGORIAS_VALIDAS:
        items.append({"codigo": cat, "total": en_bd.get(cat, 0)})
    # Detectar cualquier categoría en BD que no esté en CATEGORIAS_VALIDAS
    extras = sorted(set(en_bd) - set(CATEGORIAS_VALIDAS))
    for cat in extras:
        items.append({"codigo": cat, "total": en_bd[cat]})
    total = sum(en_bd.values())
    return {"ok": True, "items": items, "total": total}


@router.get("/conceptos")
async def listar_conceptos(
    request: Request,
    categoria: Optional[str] = Query(None),
    incluir_inactivos: bool = Query(True),
    search: str = Query(""),
    db: Session = Depends(get_db),
    member: Member = Depends(require_admin),
):
    org_id = _org_id(request, member)
    q = db.query(ConceptoCobro).filter(ConceptoCobro.organization_id == org_id)
    if categoria and categoria.lower() != "todos":
        q = q.filter(ConceptoCobro.categoria == categoria.lower())
    if not incluir_inactivos:
        q = q.filter(ConceptoCobro.activo.is_(True))
    if search:
        like = f"%{search.strip()}%"
        q = q.filter(
            (ConceptoCobro.nombre.ilike(like))
            | (ConceptoCobro.codigo.ilike(like))
            | (ConceptoCobro.descripcion.ilike(like))
        )
    items = (
        q.order_by(
            asc(ConceptoCobro.categoria),
            asc(ConceptoCobro.orden),
            asc(ConceptoCobro.nombre),
        )
        .all()
    )
    return {"ok": True, "items": [_concepto_dict(c) for c in items]}


@router.get("/conceptos/{concepto_id}")
async def obtener_concepto(
    concepto_id: int,
    request: Request,
    db: Session = Depends(get_db),
    member: Member = Depends(require_admin),
):
    org_id = _org_id(request, member)
    c = (
        db.query(ConceptoCobro)
        .filter(
            ConceptoCobro.id == concepto_id,
            ConceptoCobro.organization_id == org_id,
        )
        .first()
    )
    if not c:
        raise HTTPException(404, "Concepto no encontrado")
    return {"ok": True, "item": _concepto_dict(c)}


def _normalizar_payload(body: dict) -> dict:
    """Validaciones comunes de payload create/update."""
    out = {}

    if "codigo" in body:
        v = (body.get("codigo") or "").strip().upper()
        if v: out["codigo"] = v[:20]
    if "nombre" in body:
        v = (body.get("nombre") or "").strip()
        if v: out["nombre"] = v[:150]
    if "nombre_corto" in body:
        v = (body.get("nombre_corto") or "").strip()
        out["nombre_corto"] = v[:50] or None
    if "descripcion" in body:
        out["descripcion"] = body.get("descripcion") or None

    if "categoria" in body:
        v = (body.get("categoria") or "otros").strip().lower()
        out["categoria"] = v if v in CATEGORIAS_VALIDAS else "otros"
    if "periodicidad" in body:
        v = (body.get("periodicidad") or "unico").strip().lower()
        out["periodicidad"] = v if v in PERIODICIDADES_VALIDAS else "unico"

    for k_money in ("monto_base", "monto_minimo", "monto_maximo"):
        if k_money in body:
            try:
                out[k_money] = float(body.get(k_money) or 0)
            except (TypeError, ValueError):
                pass

    for k_int in ("dia_vencimiento", "stock_actual", "stock_minimo", "orden"):
        if k_int in body:
            try:
                out[k_int] = int(body.get(k_int) or 0)
            except (TypeError, ValueError):
                pass

    for k_bool in (
        "permite_monto_libre", "afecto_igv", "genera_comprobante",
        "requiere_colegiado", "aplica_a_publico", "genera_deuda",
        "requiere_aprobacion", "es_cuota_mensual", "maneja_stock",
        "activo",
    ):
        if k_bool in body:
            out[k_bool] = bool(body.get(k_bool))

    if "tipo_afectacion_igv" in body:
        v = (body.get("tipo_afectacion_igv") or "20").strip()
        out["tipo_afectacion_igv"] = v if v in TIPOS_AFECTACION_IGV else "20"
    if "tipo_comprobante_default" in body:
        v = (body.get("tipo_comprobante_default") or "03").strip()
        out["tipo_comprobante_default"] = v if v in TIPOS_COMPROBANTE else "03"

    if "meses_aplicables" in body:
        v = (body.get("meses_aplicables") or "").strip()
        out["meses_aplicables"] = v[:50] or None
    if "imagen_url" in body:
        v = (body.get("imagen_url") or "").strip()
        out["imagen_url"] = v[:500] or None

    return out


@router.post("/conceptos")
async def crear_concepto(
    request: Request,
    body: dict = Body(...),
    db: Session = Depends(get_db),
    member: Member = Depends(require_admin),
):
    import uuid as _uuid

    org_id = _org_id(request, member)
    data = _normalizar_payload(body)

    if not data.get("nombre"):
        raise HTTPException(400, "nombre es requerido")
    if "monto_base" not in data:
        data["monto_base"] = 0.0

    codigo = data.get("codigo") or ""
    if not codigo:
        prefijo = (data.get("categoria") or "otros")[:4].upper()
        codigo = f"{prefijo}-{_uuid.uuid4().hex[:4].upper()}"
    data["codigo"] = codigo[:20]

    duplicado = (
        db.query(ConceptoCobro.id)
        .filter(
            ConceptoCobro.organization_id == org_id,
            ConceptoCobro.codigo == codigo,
        )
        .first()
    )
    if duplicado:
        raise HTTPException(400, f"Ya existe un concepto con código '{codigo}'")

    actor_id = getattr(member, "user_id", None) or getattr(member, "id", None)

    c = ConceptoCobro(
        organization_id          = org_id,
        codigo                   = data.get("codigo"),
        nombre                   = data.get("nombre"),
        nombre_corto             = data.get("nombre_corto"),
        descripcion              = data.get("descripcion"),
        categoria                = data.get("categoria", "otros"),
        periodicidad             = data.get("periodicidad", "unico"),
        monto_base               = data.get("monto_base", 0.0),
        monto_minimo             = data.get("monto_minimo", 0.0),
        monto_maximo             = data.get("monto_maximo", 0.0),
        permite_monto_libre      = data.get("permite_monto_libre", False),
        afecto_igv               = data.get("afecto_igv", False),
        tipo_afectacion_igv      = data.get("tipo_afectacion_igv", "20"),
        genera_comprobante       = data.get("genera_comprobante", True),
        tipo_comprobante_default = data.get("tipo_comprobante_default", "03"),
        requiere_colegiado       = data.get("requiere_colegiado", True),
        aplica_a_publico         = data.get("aplica_a_publico", False),
        genera_deuda             = data.get("genera_deuda", False),
        requiere_aprobacion      = data.get("requiere_aprobacion", False),
        es_cuota_mensual         = data.get("es_cuota_mensual", False),
        dia_vencimiento          = data.get("dia_vencimiento", 0),
        meses_aplicables         = data.get("meses_aplicables"),
        maneja_stock             = data.get("maneja_stock", False),
        stock_actual             = data.get("stock_actual", 0),
        stock_minimo             = data.get("stock_minimo", 0),
        imagen_url               = data.get("imagen_url"),
        activo                   = data.get("activo", True),
        orden                    = data.get("orden", 0),
        created_by               = actor_id,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return {"ok": True, "item": _concepto_dict(c)}


@router.put("/conceptos/{concepto_id}")
async def editar_concepto(
    concepto_id: int,
    request: Request,
    body: dict = Body(...),
    db: Session = Depends(get_db),
    member: Member = Depends(require_admin),
):
    org_id = _org_id(request, member)
    c = (
        db.query(ConceptoCobro)
        .filter(
            ConceptoCobro.id == concepto_id,
            ConceptoCobro.organization_id == org_id,
        )
        .first()
    )
    if not c:
        raise HTTPException(404, "Concepto no encontrado")

    data = _normalizar_payload(body)

    # No permitir cambiar el codigo (es identificador inmutable de negocio)
    data.pop("codigo", None)

    for k, v in data.items():
        setattr(c, k, v)

    db.commit()
    db.refresh(c)
    return {"ok": True, "item": _concepto_dict(c)}


@router.put("/conceptos/{concepto_id}/toggle")
async def toggle_concepto(
    concepto_id: int,
    request: Request,
    db: Session = Depends(get_db),
    member: Member = Depends(require_admin),
):
    """Conmuta activo/inactivo sin pasar por el form."""
    org_id = _org_id(request, member)
    c = (
        db.query(ConceptoCobro)
        .filter(
            ConceptoCobro.id == concepto_id,
            ConceptoCobro.organization_id == org_id,
        )
        .first()
    )
    if not c:
        raise HTTPException(404, "Concepto no encontrado")
    c.activo = not bool(c.activo)
    db.commit()
    return {"ok": True, "activo": bool(c.activo)}


@router.delete("/conceptos/{concepto_id}")
async def desactivar_concepto(
    concepto_id: int,
    request: Request,
    db: Session = Depends(get_db),
    member: Member = Depends(require_admin),
):
    """Soft-delete: marca activo=False (no elimina por integridad histórica)."""
    org_id = _org_id(request, member)
    c = (
        db.query(ConceptoCobro)
        .filter(
            ConceptoCobro.id == concepto_id,
            ConceptoCobro.organization_id == org_id,
        )
        .first()
    )
    if not c:
        raise HTTPException(404, "Concepto no encontrado")
    c.activo = False
    db.commit()
    return {"ok": True, "mensaje": "Concepto desactivado"}

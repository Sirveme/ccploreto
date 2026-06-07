"""
app/routers/seo.py — Paquete SEO/GEO host-aware (zzClaude-1).

Todas las rutas SEO de la app viven aquí. Reglas:

- El ÚNICO host indexable es ccploreto.org.pe (canónico). Cualquier otro host que
  atienda esta misma app vía tenant_middleware (*.duilio.store, metraes.com,
  desconocidos) recibe robots con bloqueo TOTAL para evitar que Google indexe
  contenido duplicado del portal en otros dominios.
- /sitemap.xml se genera al vuelo (no es archivo estático): páginas públicas fijas
  + comunicados VIGENTES del CMS. La consulta es SOLO LECTURA y, si falla, el
  sitemap responde igual con las páginas fijas (nunca 500).
- /llms.txt y /llms-full.txt se sirven desde static/seo/ solo en el host canónico.

No toca tenant_middleware, routers de dinero ni archivos protegidos.
"""
from datetime import datetime, timezone
import logging

from fastapi import APIRouter, Request
from fastapi.responses import Response, FileResponse, PlainTextResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["SEO"])

CANONICAL_BASE = "https://ccploreto.org.pe"
CCPL_ORG_SLUG = "ccp-loreto"

# Páginas públicas fijas indexables (verificadas en Tarea 0.2: rutas GET sin auth
# que sirven HTML útil). (path, priority). El home con prioridad 1.0; el resto 0.6.
PAGINAS_FIJAS = [
    ("/",                    "1.0"),
    ("/comunicados",         "0.6"),
    ("/articulos",           "0.6"),
    ("/capacitaciones",      "0.6"),
    ("/convenios",           "0.6"),
    ("/galeria",             "0.6"),
    ("/politica-privacidad", "0.6"),
    ("/terminos",            "0.6"),
]


def _es_host_canonico(request: Request) -> bool:
    host = request.headers.get("host", "").lower().split(":")[0]
    return host in ("ccploreto.org.pe", "www.ccploreto.org.pe")


@router.get("/robots.txt", include_in_schema=False)
async def robots_txt(request: Request):
    if _es_host_canonico(request):
        body = (
            "User-agent: *\n"
            "Disallow: /login\n"
            "Disallow: /dashboard\n"
            "Disallow: /admin\n"
            "Disallow: /caja\n"
            "Disallow: /portal\n"
            "Disallow: /tesoreria\n"
            "Disallow: /api\n"
            "Allow: /\n"
            f"Sitemap: {CANONICAL_BASE}/sitemap.xml\n"
        )
    else:
        # Host NO canónico (duilio.store, metraes.com, desconocidos): bloqueo total.
        body = "User-agent: *\nDisallow: /\n"
    return PlainTextResponse(body, media_type="text/plain")


@router.get("/sitemap.xml", include_in_schema=False)
async def sitemap_xml(request: Request):
    # Solo el host canónico expone sitemap; otros hosts: 404.
    if not _es_host_canonico(request):
        return Response(status_code=404)

    # 1) Páginas fijas (siempre presentes, aunque falle la BD).
    urls = [(f"{CANONICAL_BASE}{path}", prio, None) for path, prio in PAGINAS_FIJAS]

    # 2) Comunicados vigentes del CMS (SOLO LECTURA). Si algo falla, seguimos
    #    con las páginas fijas — el sitemap nunca devuelve 500.
    try:
        from sqlalchemy import or_, desc
        from app.database import SessionLocal
        from app.models import Bulletin, Organization

        db = SessionLocal()
        try:
            org = (
                db.query(Organization)
                .filter(Organization.slug == CCPL_ORG_SLUG)
                .first()
            )
            if org:
                ahora = datetime.now(timezone.utc)
                comunicados = (
                    db.query(Bulletin)
                    .filter(
                        Bulletin.organization_id == org.id,
                        Bulletin.tipo == "comunicado",
                        or_(Bulletin.expires_at.is_(None), Bulletin.expires_at > ahora),
                    )
                    .order_by(desc(Bulletin.created_at))
                    .all()
                )
                for b in comunicados:
                    lastmod = b.created_at.date().isoformat() if b.created_at else None
                    urls.append((f"{CANONICAL_BASE}/comunicados/{b.id}", "0.7", lastmod))
        finally:
            db.close()
    except Exception as e:
        logger.warning("sitemap.xml: comunicados no disponibles (se omiten): %s", e)

    # 2b) Artículos institucionales publicados (zzClaude-2). SOLO LECTURA y a
    #     prueba de fallos: si algo falla, se omiten sin tumbar el sitemap.
    try:
        from sqlalchemy import desc
        from app.database import SessionLocal
        from app.models import Articulo, Organization

        db = SessionLocal()
        try:
            org = (
                db.query(Organization)
                .filter(Organization.slug == CCPL_ORG_SLUG)
                .first()
            )
            if org:
                articulos = (
                    db.query(Articulo)
                    .filter(
                        Articulo.organization_id == org.id,
                        Articulo.publicado.is_(True),
                    )
                    .order_by(desc(Articulo.published_at))
                    .all()
                )
                for a in articulos:
                    lastmod = a.updated_at.date().isoformat() if a.updated_at else None
                    urls.append((f"{CANONICAL_BASE}/articulos/{a.slug}", "0.8", lastmod))
        finally:
            db.close()
    except Exception as e:
        logger.warning("sitemap.xml: articulos no disponibles (se omiten): %s", e)

    # 3) Serializar XML al vuelo.
    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for loc, prio, lastmod in urls:
        parts.append("  <url>")
        parts.append(f"    <loc>{loc}</loc>")
        if lastmod:
            parts.append(f"    <lastmod>{lastmod}</lastmod>")
        parts.append(f"    <priority>{prio}</priority>")
        parts.append("  </url>")
    parts.append("</urlset>")

    return Response(content="\n".join(parts), media_type="application/xml")


@router.get("/llms.txt", include_in_schema=False)
async def llms_txt(request: Request):
    if not _es_host_canonico(request):
        return Response(status_code=404)
    return FileResponse("static/seo/llms.txt", media_type="text/plain; charset=utf-8")


@router.get("/llms-full.txt", include_in_schema=False)
async def llms_full_txt(request: Request):
    if not _es_host_canonico(request):
        return Response(status_code=404)
    return FileResponse("static/seo/llms-full.txt", media_type="text/plain; charset=utf-8")

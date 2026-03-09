"""
Router: SOTE (Soporte Técnico)
==============================
Dashboard de mantenimiento e inspección del sistema.
Solo accesible con role='sote'.

Rutas:
  GET  /sote                → Dashboard principal
  GET  /sote/usuarios       → Lista usuarios + último acceso (HTMX)
  POST /sote/reset-password → Reset password = DNI
  GET  /sote/activos        → Sesiones recientes (HTMX)
  GET  /sote/stats          → Stats del sistema (HTMX)
"""

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, timezone, timedelta

from app.database import get_db
from app.models import User, Member, Colegiado
from app.routers.dashboard import get_current_member
from app.utils.security import get_password_hash

router = APIRouter(prefix="/sote", tags=["sote"])


from fastapi.responses import Response as FastAPIResponse
from app.utils.templates import templates

def htmx_aware_redirect(request: Request, url: str):
    """Si es request HTMX, usar HX-Redirect. Si no, redirect normal."""
    from fastapi.responses import RedirectResponse
    if request.headers.get("HX-Request"):
        resp = FastAPIResponse(status_code=200)
        resp.headers["HX-Redirect"] = url
        return resp
    return RedirectResponse(url=url, status_code=302)


async def require_sote(
    request: Request,
    current_member: Member = Depends(get_current_member)
):
    if current_member is None or current_member.role != "sote":
        raise HTTPException(status_code=403, detail="Acceso restringido a SOTE")
    return current_member


# ── Dashboard principal ────────────────────────────────────
@router.get("", response_class=HTMLResponse)
async def sote_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_sote),
):
    user = db.query(User).filter(User.id == current_member.user_id).first()
    return templates.TemplateResponse("pages/sote/dashboard.html", {
        "request": request,
        "user": current_member,   # base.html espera user.organization (Member lo tiene)
        "user_name": user.name,   # nombre real para mostrar en el header SOTE
        "org": getattr(request.state, "org", {}),
        "theme": getattr(request.state, "theme", None),
    })


# ── Stats del sistema ──────────────────────────────────────
@router.get("/stats", response_class=HTMLResponse)
async def sote_stats(
    request: Request,
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_sote),
):
    org_id = current_member.organization_id

    stats = {}

    # Colegiados
    r = db.execute(text("""
        SELECT
          COUNT(*) as total,
          COUNT(*) FILTER (WHERE condicion = 'habil')    as habiles,
          COUNT(*) FILTER (WHERE condicion = 'vitalicio') as vitalicios,
          COUNT(*) FILTER (WHERE condicion NOT IN ('habil','vitalicio')) as inhabiles
        FROM colegiados WHERE organization_id = :org
    """), {"org": org_id}).fetchone()
    stats["colegiados"] = {"total": r[0], "habiles": r[1], "vitalicios": r[2], "inhabiles": r[3]}

    # Usuarios del sistema
    r2 = db.execute(text("""
        SELECT COUNT(*) as total,
               COUNT(*) FILTER (WHERE ultimo_login >= now() - interval '7 days') as activos_semana,
               COUNT(*) FILTER (WHERE ultimo_login >= now() - interval '1 day')  as activos_hoy
        FROM users u
        JOIN members m ON m.user_id = u.id
        WHERE m.organization_id = :org AND m.is_active = true
    """), {"org": org_id}).fetchone()
    stats["usuarios"] = {"total": r2[0], "activos_semana": r2[1], "activos_hoy": r2[2]}

    # Deudas
    r3 = db.execute(text("""
        SELECT COUNT(*) as total,
               COUNT(*) FILTER (WHERE status = 'pendiente') as pendientes,
               COALESCE(SUM(balance) FILTER (WHERE status = 'pendiente'), 0) as monto_pendiente
        FROM debts WHERE organization_id = :org
    """), {"org": org_id}).fetchone()
    stats["deudas"] = {"total": r3[0], "pendientes": r3[1], "monto_pendiente": float(r3[2])}

    # Pagos recientes (últimos 30 días)
    r4 = db.execute(text("""
        SELECT COUNT(*) as total,
               COALESCE(SUM(amount), 0) as monto
        FROM payments
        WHERE organization_id = :org AND created_at >= now() - interval '30 days'
    """), {"org": org_id}).fetchone()
    stats["pagos_30d"] = {"total": r4[0], "monto": float(r4[1])}

    return templates.TemplateResponse("pages/sote/partials/stats.html", {
        "request": request,
        "stats": stats,
    })


# ── Lista de usuarios (staff + directivos, no colegiados) ──
@router.get("/usuarios", response_class=HTMLResponse)
async def sote_usuarios(
    request: Request,
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_sote),
):
    """Lista completa de staff/directivos (no colegiados) — carga al entrar a la sección"""
    org_id = current_member.organization_id
    sql = """
        SELECT u.id, u.public_id, u.name, u.ultimo_login, u.login_count,
               u.debe_cambiar_clave, m.role, m.is_active
        FROM users u
        JOIN members m ON m.user_id = u.id
        WHERE m.organization_id = :org
          AND m.role != 'colegiado'
        ORDER BY m.role, u.name
        LIMIT 100
    """
    usuarios = db.execute(text(sql), {"org": org_id}).fetchall()
    return templates.TemplateResponse("pages/sote/partials/usuarios.html", {
        "request": request,
        "usuarios": usuarios,
        "q": "",
    })


@router.get("/usuarios/buscar", response_class=HTMLResponse)
async def sote_usuarios_buscar(
    request: Request,
    q: str = "",
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_sote),
):
    """Autocomplete: devuelve filas coincidentes mientras el usuario escribe"""
    org_id = current_member.organization_id
    termino = q.strip()

    if not termino or len(termino) < 1:
        # Sin término: devolver todos
        sql = """
            SELECT u.id, u.public_id, u.name, u.ultimo_login, u.login_count,
                   u.debe_cambiar_clave, m.role, m.is_active
            FROM users u
            JOIN members m ON m.user_id = u.id
            WHERE m.organization_id = :org
              AND m.role != 'colegiado'
            ORDER BY m.role, u.name LIMIT 100
        """
        usuarios = db.execute(text(sql), {"org": org_id}).fetchall()
    else:
        sql = """
            SELECT u.id, u.public_id, u.name, u.ultimo_login, u.login_count,
                   u.debe_cambiar_clave, m.role, m.is_active
            FROM users u
            JOIN members m ON m.user_id = u.id
            WHERE m.organization_id = :org
              AND m.role != 'colegiado'
              AND (u.public_id ILIKE :q OR u.name ILIKE :q)
            ORDER BY m.role, u.name LIMIT 50
        """
        usuarios = db.execute(text(sql), {"org": org_id, "q": f"%{termino}%"}).fetchall()

    return templates.TemplateResponse("pages/sote/partials/usuarios.html", {
        "request": request,
        "usuarios": usuarios,
        "q": termino,
    })


# ── Buscar colegiado (reutiliza lógica de consulta habilidad) ──
@router.get("/buscar-colegiado", response_class=HTMLResponse)
async def sote_buscar_colegiado(
    request: Request,
    q: str = "",
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_sote),
):
    org_id = current_member.organization_id
    colegiados = []

    if q and len(q.strip()) >= 2:
        termino = q.strip()
        es_dni = termino.isdigit()

        sql = """
            SELECT c.id, c.codigo_matricula, c.apellidos_nombres, c.dni,
                   c.condicion, u.id as user_id, u.public_id, u.login_count,
                   u.ultimo_login, u.debe_cambiar_clave,
                   m.id as member_id, m.role
            FROM colegiados c
            LEFT JOIN members m ON m.id = c.member_id
            LEFT JOIN users u ON u.id = m.user_id
            WHERE c.organization_id = :org
        """
        params = {"org": org_id}

        if es_dni:
            sql += " AND c.dni ILIKE :q"
            params["q"] = f"%{termino}%"
        else:
            sql += " AND c.apellidos_nombres ILIKE :q"
            params["q"] = f"%{termino}%"

        sql += " ORDER BY c.apellidos_nombres LIMIT 30"
        colegiados = db.execute(text(sql), params).fetchall()

    return templates.TemplateResponse("pages/sote/partials/colegiados.html", {
        "request": request,
        "colegiados": colegiados,
        "q": q,
    })


# ── Reset password = DNI ───────────────────────────────────
@router.post("/reset-password", response_class=HTMLResponse)
async def sote_reset_password(
    request: Request,
    user_id: int = Form(...),
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_sote),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return HTMLResponse('<span class="badge-error">Usuario no encontrado</span>')

    dni = user.public_id
    user.access_code = get_password_hash(dni)
    user.debe_cambiar_clave = True
    db.commit()

    return HTMLResponse(
        f'<span class="badge-ok">✓ Password reseteado al DNI ({dni})</span>'
    )


# ── Sesiones activas / recientes ──────────────────────────
@router.get("/activos", response_class=HTMLResponse)
async def sote_activos(
    request: Request,
    horas: int = 24,
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_sote),
):
    org_id = current_member.organization_id

    activos = db.execute(text("""
        SELECT u.public_id, u.name, m.role, u.ultimo_login, u.login_count
        FROM users u
        JOIN members m ON m.user_id = u.id
        WHERE m.organization_id = :org
          AND u.ultimo_login >= now() - (:horas || ' hours')::interval
        ORDER BY u.ultimo_login DESC
    """), {"org": org_id, "horas": horas}).fetchall()

    return templates.TemplateResponse("pages/sote/partials/activos.html", {
        "request": request,
        "activos": activos,
        "horas": horas,
    })
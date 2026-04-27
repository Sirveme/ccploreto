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

from fastapi import APIRouter, Depends, Request, Form, Body, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import text, or_, cast, Date
from datetime import datetime, timezone, timedelta

from app.database import get_db
from app.models import (
    User, Member, Colegiado,
    Rol, UsuarioAdmin, SesionCaja, Comprobante,
)
from app.routers.dashboard import get_current_member
from app.utils.security import get_password_hash

PERU_TZ = timezone(timedelta(hours=-5))
ROLES_OPERATIVOS = {"cajero", "secretaria", "editor", "tesorero", "admin"}
ROLES_CON_USUARIO_ADMIN = {"cajero", "secretaria", "tesorero", "admin"}

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


# ════════════════════════════════════════════════════════════════
# API JSON: gestión extendida de usuarios + estado sistema
# (mobile-first dashboard /sote — zClaude-60)
# ════════════════════════════════════════════════════════════════

# ── A2: buscar usuarios (todos los roles, JSON) ─────────────
@router.get("/api/usuarios/buscar")
async def api_buscar_usuario(
    q: str = "",
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_sote),
):
    """Busca usuarios por DNI o nombre — todos los roles, JSON."""
    termino = (q or "").strip()
    if len(termino) < 2:
        return {"ok": True, "usuarios": []}

    org_id = current_member.organization_id
    users = db.query(User).filter(
        or_(
            User.public_id.ilike(f"%{termino}%"),
            User.name.ilike(f"%{termino}%"),
        )
    ).limit(20).all()

    resultado = []
    for u in users:
        member = db.query(Member).filter(
            Member.user_id == u.id,
            Member.organization_id == org_id,
        ).first()
        resultado.append({
            "id":                u.id,
            "dni":               u.public_id,
            "nombre":            u.name,
            "email":             u.email or "",
            "rol":               member.role if member else "sin rol",
            "activo":            bool(member.is_active) if member else False,
            "debe_cambiar_clave": bool(u.debe_cambiar_clave),
        })

    return {"ok": True, "usuarios": resultado}


# ── A3: reset clave para cualquier usuario ──────────────────
@router.post("/api/usuarios/{user_id}/reset-clave")
async def api_reset_clave_usuario(
    user_id: int,
    body: dict = Body(default={}),
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_sote),
):
    """Resetea clave de cualquier usuario. Si no se provee nueva_clave usa el DNI."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    nueva_clave_input = (body or {}).get("nueva_clave")
    nueva_clave = (nueva_clave_input or "").strip() or user.public_id
    user.access_code = get_password_hash(nueva_clave)
    user.debe_cambiar_clave = True
    db.commit()

    es_dni = not (nueva_clave_input or "").strip()
    return {
        "ok": True,
        "mensaje": (
            f"Clave reseteada para {user.name}. "
            f"{'Clave = DNI' if es_dni else 'Clave personalizada'}. "
            f"Deberá cambiarla al próximo login."
        ),
    }


# ── A4: activar/desactivar usuario ──────────────────────────
@router.post("/api/usuarios/{user_id}/toggle-activo")
async def api_toggle_activo_usuario(
    user_id: int,
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_sote),
):
    org_id = current_member.organization_id
    member = db.query(Member).filter(
        Member.user_id == user_id,
        Member.organization_id == org_id,
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="Member no encontrado")

    member.is_active = not bool(member.is_active)
    db.commit()
    return {
        "ok": True,
        "activo": bool(member.is_active),
        "mensaje": f"Usuario {'activado' if member.is_active else 'desactivado'}",
    }


# ── B1: crear usuario operativo ─────────────────────────────
@router.post("/api/usuarios/crear")
async def api_crear_usuario(
    body: dict = Body(...),
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_sote),
):
    """Crea un nuevo usuario operativo (cajero, secretaria, editor, tesorero, admin)."""
    dni    = (body.get("dni") or "").strip()
    nombre = (body.get("nombre") or "").strip()
    rol    = (body.get("rol") or "").strip()
    email  = (body.get("email") or "").strip() or None

    if not dni or not nombre:
        raise HTTPException(status_code=400, detail="DNI y nombre son obligatorios")
    if rol not in ROLES_OPERATIVOS:
        raise HTTPException(
            status_code=400,
            detail=f"Rol inválido. Válidos: {', '.join(sorted(ROLES_OPERATIVOS))}",
        )

    if db.query(User).filter(User.public_id == dni).first():
        raise HTTPException(status_code=400, detail=f"Ya existe un usuario con DNI {dni}")

    org_id = current_member.organization_id

    nuevo_user = User(
        public_id          = dni,
        access_code        = get_password_hash(dni),
        name               = nombre,
        email              = email,
        debe_cambiar_clave = True,
        login_count        = 0,
    )
    db.add(nuevo_user)
    db.flush()

    db.add(Member(
        user_id         = nuevo_user.id,
        organization_id = org_id,
        role            = rol,
        is_active       = True,
    ))

    if rol in ROLES_CON_USUARIO_ADMIN:
        rol_obj = db.query(Rol).filter(
            Rol.organization_id == org_id,
            Rol.codigo == rol,
        ).first()
        if rol_obj:
            db.add(UsuarioAdmin(
                organization_id = org_id,
                user_id         = nuevo_user.id,
                rol_id          = rol_obj.id,
                nombre_completo = nombre,
                email           = email or "",
                cargo           = rol.capitalize(),
                activo          = True,
            ))

    db.commit()
    return {
        "ok":      True,
        "user_id": nuevo_user.id,
        "mensaje": f"Usuario {nombre} creado con rol {rol}. Clave inicial = DNI ({dni}).",
    }


# ── C1: estado general del sistema ──────────────────────────
@router.get("/api/sistema/estado")
async def api_estado_sistema(
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_sote),
):
    org_id = current_member.organization_id
    ahora = datetime.now(PERU_TZ)

    sesion_caja = db.query(SesionCaja).filter(
        SesionCaja.organization_id == org_id,
        SesionCaja.estado == "abierta",
    ).order_by(SesionCaja.id.desc()).first()

    sesion_colgada = False
    if sesion_caja and sesion_caja.hora_apertura:
        delta = datetime.now(timezone.utc) - sesion_caja.hora_apertura
        sesion_colgada = delta > timedelta(hours=24)

    ultima_boleta = db.query(Comprobante).filter(
        Comprobante.organization_id == org_id,
        Comprobante.tipo == "03",
    ).order_by(Comprobante.id.desc()).first()

    pendientes = db.query(Comprobante).filter(
        Comprobante.organization_id == org_id,
        Comprobante.status.in_(["pending", "rejected"]),
    ).count()

    usuarios_hoy = db.query(User).filter(
        cast(User.ultimo_login, Date) == ahora.date()
    ).count()

    return {
        "ok":            True,
        "hora_servidor": ahora.strftime("%d/%m/%Y %H:%M"),
        "caja": {
            "abierta": sesion_caja is not None,
            "id":      sesion_caja.id if sesion_caja else None,
            "desde": (
                sesion_caja.hora_apertura.astimezone(PERU_TZ).strftime("%H:%M")
                if sesion_caja and sesion_caja.hora_apertura else None
            ),
            "colgada": sesion_colgada,
        },
        "ultima_boleta": {
            "serie_numero": (
                f"{ultima_boleta.serie}-{str(ultima_boleta.numero).zfill(8)}"
                if ultima_boleta and ultima_boleta.serie else None
            ),
            "status": ultima_boleta.status if ultima_boleta else None,
            "total":  float(ultima_boleta.total) if ultima_boleta and ultima_boleta.total else None,
            "hora": (
                ultima_boleta.created_at.astimezone(PERU_TZ).strftime("%d/%m %H:%M")
                if ultima_boleta and ultima_boleta.created_at else None
            ),
        },
        "alertas": {
            "comprobantes_pendientes": pendientes,
        },
        "usuarios_activos_hoy": usuarios_hoy,
    }


# ── C2: cerrar sesión de caja colgada ───────────────────────
@router.post("/api/caja/cerrar-emergencia/{sesion_id}")
async def api_cerrar_caja_emergencia(
    sesion_id: int,
    body: dict = Body(default={}),
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_sote),
):
    """Cierre de emergencia de una sesión de caja colgada desde /sote."""
    org_id = current_member.organization_id
    sesion = db.query(SesionCaja).filter(
        SesionCaja.id == sesion_id,
        SesionCaja.organization_id == org_id,
    ).first()
    if not sesion:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")
    if sesion.estado == "cerrada":
        return {"ok": True, "mensaje": "La sesión ya estaba cerrada"}

    motivo = (body or {}).get("motivo") or "sin motivo"
    sesion.estado = "cerrada"
    sesion.hora_cierre = datetime.now(timezone.utc)
    sesion.observaciones_cierre = f"Cierre de emergencia desde /sote — {motivo}"
    db.commit()

    return {"ok": True, "mensaje": f"Sesión #{sesion_id} cerrada correctamente"}
"""
Middleware de Autorización
app/middleware/autorizacion.py

Dependencies de FastAPI para verificar permisos por rol.

Uso:
    @router.get("/caja")
    async def pantalla_caja(
        usuario: UsuarioAdmin = Depends(requiere_permiso("caja", "ver"))
    ):
        ...
"""

from typing import Optional, Callable
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import UsuarioAdmin, Rol
from jose import jwt


async def obtener_usuario_actual(
    request: Request,
    db: Session = Depends(get_db)
) -> UsuarioAdmin:
    """Extrae el usuario autenticado del request."""
    user_id = None

    # Opción 1: Middleware previo
    if hasattr(request.state, 'user_id'):
        user_id = request.state.user_id

    # Opción 2: Sesión
    if not user_id:
        session = getattr(request, 'session', {})
        user_id = session.get('user_id')

    # Opción 3: JWT
    if not user_id:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.replace("Bearer ", "")
            user_id = _decodificar_token(token)

    if not user_id:
        raise HTTPException(
            status_code=401,
            detail={"error": "No autenticado", "codigo": "AUTH_REQUIRED"}
        )

    usuario = db.query(UsuarioAdmin).options(
        joinedload(UsuarioAdmin.rol).joinedload(Rol.permisos),
        joinedload(UsuarioAdmin.centro_costo)
    ).filter(
        UsuarioAdmin.user_id == user_id,
        UsuarioAdmin.activo == True
    ).first()

    if not usuario:
        raise HTTPException(
            status_code=403,
            detail={"error": "Usuario sin acceso al sistema", "codigo": "NO_ACCESS"}
        )

    request.state.usuario_admin = usuario
    return usuario


def _decodificar_token(token: str) -> Optional[int]:
    """Decodifica JWT y retorna user_id."""
    try:
        import os
        from jose import jwt
        secret = os.getenv("JWT_SECRET", "your-secret-key")
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        return payload.get("user_id")
    except Exception:
        return None


def requiere_permiso(modulo: str, accion: str) -> Callable:
    """Verifica permiso específico: requiere_permiso("caja", "cobrar")"""
    async def verificar(
        usuario: UsuarioAdmin = Depends(obtener_usuario_actual)
    ) -> UsuarioAdmin:
        if usuario.rol.codigo == "admin":
            return usuario
        if not usuario.tiene_permiso(modulo, accion):
            raise HTTPException(
                status_code=403,
                detail={
                    "error": f"Sin permiso para {modulo}.{accion}",
                    "codigo": "FORBIDDEN",
                    "rol_actual": usuario.rol.codigo
                }
            )
        return usuario
    return verificar


def requiere_rol(*roles_permitidos: str) -> Callable:
    """Verifica rol: requiere_rol("admin", "tesorero")"""
    async def verificar(
        usuario: UsuarioAdmin = Depends(obtener_usuario_actual)
    ) -> UsuarioAdmin:
        if usuario.rol.codigo not in roles_permitidos:
            raise HTTPException(
                status_code=403,
                detail={
                    "error": f"Requiere rol: {', '.join(roles_permitidos)}",
                    "codigo": "FORBIDDEN",
                    "rol_actual": usuario.rol.codigo
                }
            )
        return usuario
    return verificar


def requiere_nivel(nivel_minimo: int) -> Callable:
    """Verifica nivel mínimo: requiere_nivel(80)"""
    async def verificar(
        usuario: UsuarioAdmin = Depends(obtener_usuario_actual)
    ) -> UsuarioAdmin:
        if usuario.rol.nivel < nivel_minimo:
            raise HTTPException(
                status_code=403,
                detail={"error": f"Nivel insuficiente", "codigo": "FORBIDDEN"}
            )
        return usuario
    return verificar


def requiere_centro_costo() -> Callable:
    """Verifica centro de costo asignado (admin/tesorero exentos)"""
    async def verificar(
        usuario: UsuarioAdmin = Depends(obtener_usuario_actual)
    ) -> UsuarioAdmin:
        if usuario.rol.codigo in ("admin", "tesorero"):
            return usuario
        if not usuario.centro_costo_id:
            raise HTTPException(
                status_code=403,
                detail={"error": "Sin centro de costo asignado", "codigo": "NO_CENTRO_COSTO"}
            )
        return usuario
    return verificar


def permisos_usuario(usuario: UsuarioAdmin) -> dict:
    """Dict de permisos para frontend: permisos.caja.cobrar → True"""
    result = {}
    for p in usuario.rol.permisos:
        if p.modulo not in result:
            result[p.modulo] = {}
        result[p.modulo][p.accion] = True
    return result


def menu_por_rol(usuario: UsuarioAdmin) -> list:
    """Items del menú lateral según permisos del usuario"""
    menu = [
        {"icono": "layout-dashboard", "label": "Dashboard", "url": "/dashboard",
         "modulo": "reportes", "accion": "dashboard"},
        {"icono": "cash-register", "label": "Caja", "url": "/caja",
         "modulo": "caja", "accion": "ver"},
        {"icono": "users", "label": "Colegiados", "url": "/colegiados",
         "modulo": "colegiados", "accion": "ver"},
        {"icono": "file-invoice", "label": "Deudas", "url": "/deudas",
         "modulo": "deudas", "accion": "ver"},
        {"icono": "credit-card", "label": "Pagos", "url": "/pagos",
         "modulo": "pagos", "accion": "ver"},
        {"icono": "receipt", "label": "Comprobantes", "url": "/comprobantes",
         "modulo": "comprobantes", "accion": "ver"},
        {"icono": "certificate", "label": "Constancias", "url": "/constancias",
         "modulo": "constancias", "accion": "ver"},
        {"icono": "inbox", "label": "Mesa de Partes", "url": "/tramites",
         "modulo": "tramites", "accion": "ver"},
        {"icono": "bell", "label": "Comunicaciones", "url": "/comunicaciones",
         "modulo": "comunicaciones", "accion": "ver"},
        {"icono": "chart-bar", "label": "Reportes", "url": "/reportes",
         "modulo": "reportes", "accion": "ver"},
        {"icono": "tags", "label": "Conceptos", "url": "/conceptos",
         "modulo": "conceptos", "accion": "ver"},
        {"icono": "settings", "label": "Configuración", "url": "/configuracion",
         "modulo": "configuracion", "accion": "ver"},
        {"icono": "user-cog", "label": "Usuarios", "url": "/usuarios",
         "modulo": "usuarios", "accion": "ver"},
    ]

    if usuario.rol.codigo == "admin":
        return menu

    return [
        item for item in menu
        if usuario.tiene_permiso(item["modulo"], item["accion"])
    ]
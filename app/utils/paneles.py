"""Panel de origen de cada rol (a dónde vuelve alguien desde una pantalla compartida).

Misma tabla que usa el login (auth.create_session_response). Sin BD: el rol se lee
del token de sesión, que ya lo trae.
"""
from jose import jwt

PANEL_POR_ROL = {
    "sote": ("/sote", "Panel de soporte"),
    "decano": ("/decano", "Panel del Decanato"),
    "admin": ("/admin", "Panel de administración"),
    "cajero": ("/caja", "Caja"),
    "tesorero": ("/caja", "Caja"),
    "secretaria": ("/secretaria", "Secretaría"),
    "editor": ("/admin/cms", "Contenido web"),
    "emisor_carnes": ("/credenciales/panel", "Carnés"),
    "junta_jdccpp": ("/junta/reporte", "Reporte de la Junta"),
}
PANEL_POR_DEFECTO = ("/dashboard", "Inicio")


def panel_de_rol(rol: str):
    """(url, etiqueta) del panel de origen del rol."""
    return PANEL_POR_ROL.get((rol or "").lower(), PANEL_POR_DEFECTO)


def rol_de_la_sesion(request) -> str:
    """Rol que viene en la cookie de sesión, o '' si no hay sesión válida. Nunca lanza."""
    try:
        from app.routers.dashboard import SECRET_KEY, ALGORITHM
        token = (request.cookies.get("access_token") or "").split()[-1]
        return str(jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM]).get("role") or "")
    except Exception:
        return ""

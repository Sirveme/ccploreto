"""Sesión y rol para rutas de API (responden JSON, no redirigen).

`sesion_api` NO valida por su cuenta: delega en `get_current_member`
(app/routers/dashboard.py), que es la validación de sesión de toda la app
(misma cookie `access_token`, misma clave, mismo algoritmo). Lo único que
cambia es la respuesta cuando no hay sesión válida: 401 en JSON en vez de la
redirección 302 a "/", que un fetch() seguiría hasta la portada y leería como 200.

Uso:
    from app.utils.sesion_api import sesion_api, exigir_roles

    @router.post("/algo")
    async def algo(member: Member = Depends(exigir_roles("admin", "tesorero"))): ...
"""
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Member
from app.routers.dashboard import get_current_member


def sesion_api(request: Request, db: Session = Depends(get_db)) -> Member:
    """Devuelve el Member de la sesión o responde 401."""
    try:
        member = get_current_member(request, db)
    except HTTPException:
        # get_current_member lanza 302 a "/" cuando no hay cookie o es inválida.
        raise HTTPException(status_code=401, detail="No autenticado")
    if member is None:
        raise HTTPException(status_code=401, detail="No autenticado")
    return member


def exigir_roles(*roles: str, mensaje: str = None):
    """Dependencia: sesión válida (401) y rol dentro de `roles` (403).
    `mensaje` (opcional, tanda 14): texto del 403 para quien no tiene el rol."""
    def _dep(member: Member = Depends(sesion_api)) -> Member:
        if member.role not in roles:
            raise HTTPException(status_code=403, detail=mensaje or "Tu rol no puede realizar esta operación")
        return member
    return _dep

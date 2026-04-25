"""
app/models_audit_finanzas.py

Modelo SQLAlchemy + helper para registrar cambios sobre deudas, pagos y
fraccionamientos en la tabla `audit_log_finanzas`.

La tabla ya existe en Railway con su propio schema. Este módulo se limita
a mapear los campos reales y NO intenta crearla.
"""
from typing import Optional, Any, Dict
from datetime import datetime, timezone, timedelta
import logging

from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Numeric
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from app.database import Base

logger = logging.getLogger(__name__)

PERU_TZ = timezone(timedelta(hours=-5))


class AuditLogFinanzas(Base):
    """Mapea la tabla real `audit_log_finanzas` de Railway."""
    __tablename__ = "audit_log_finanzas"

    id              = Column(Integer, primary_key=True)
    organization_id = Column(Integer)
    accion          = Column(String)
    actor_id        = Column(Integer)
    actor_nombre    = Column(String)
    actor_rol       = Column(String)
    ip_address      = Column(String, nullable=True)
    user_agent      = Column(Text, nullable=True)
    entidad_tipo    = Column(String)   # debts, payments, fraccionamientos, fraccionamiento_cuotas, ...
    entidad_id      = Column(Integer)
    monto           = Column(Numeric(12, 2), nullable=True)
    detalle         = Column(JSONB)    # {cambios, motivo, colegiado_id, ...}
    created_at      = Column(DateTime(timezone=True))


async def asegurar_tabla_audit(db: Session) -> None:
    """No-op: la tabla ya existe en Railway con su propio schema."""
    return None


def _extraer_actor(current_user) -> tuple:
    """Devuelve (actor_id, actor_nombre, actor_rol) tolerando Member o User."""
    actor_id = (
        getattr(current_user, "user_id", None)
        or getattr(current_user, "id", None)
    )
    nombre = None
    user_obj = getattr(current_user, "user", None)
    for src in (user_obj, current_user):
        if src is None:
            continue
        nombre = (
            getattr(src, "nombre", None)
            or getattr(src, "name", None)
            or getattr(src, "public_id", None)
            or getattr(src, "username", None)
        )
        if nombre:
            break
    if not nombre:
        nombre = str(actor_id) if actor_id is not None else "desconocido"

    rol = (
        getattr(current_user, "role", None)
        or getattr(current_user, "rol", None)
        or "desconocido"
    )
    return actor_id, nombre, rol


async def log_audit_finanzas(
    db: Session,
    *,
    organization_id: Optional[int],
    accion: str,
    entidad_tipo: str,
    entidad_id: int,
    current_user,
    cambios: Optional[Dict[str, Any]] = None,
    motivo: str = "",
    colegiado_id: Optional[int] = None,
    monto: Optional[float] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> Optional[AuditLogFinanzas]:
    """
    Inserta un registro en audit_log_finanzas. NO hace commit — el caller
    realiza commit junto con el cambio principal. Tolera fallos sin
    propagar excepción al caller.
    """
    try:
        actor_id, actor_nombre, actor_rol = _extraer_actor(current_user)
        log = AuditLogFinanzas(
            organization_id=organization_id,
            accion=accion,
            actor_id=actor_id,
            actor_nombre=actor_nombre,
            actor_rol=actor_rol,
            ip_address=ip_address,
            user_agent=user_agent,
            entidad_tipo=entidad_tipo,
            entidad_id=entidad_id,
            monto=monto,
            detalle={
                "cambios": cambios or {},
                "motivo": motivo or "",
                "colegiado_id": colegiado_id,
            },
            created_at=datetime.now(PERU_TZ),
        )
        db.add(log)
        return log
    except Exception as e:
        logger.exception(
            "Fallo log_audit_finanzas entidad=%s/%s: %s", entidad_tipo, entidad_id, e
        )
        return None

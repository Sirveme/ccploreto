"""
app/routers/api_notif.py
Endpoints de configuración personal de notificaciones (zClaude-97n).

NOTA (zClaude-97n): get_current_member vive en app.routers.dashboard
(no en app.routers.security), igual que en api_comunicados.py.
"""
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Member
from app.routers.dashboard import get_current_member

router = APIRouter(prefix="/api/notif", tags=["notificaciones"])

CATEGORIAS_DISPONIBLES = ["pagos", "mi_cuenta", "ccpl", "tributario_propio", "gestion"]
MODOS_VALIDOS = ["inmediato", "resumen_diario", "resumen_semanal", "silencioso"]


@router.get("/vapid-key")
async def vapid_public_key():
    """Devuelve la VAPID public key (zClaude-97n-bis).

    Es pública por diseño (la usa el navegador para suscribirse a push), así
    que no requiere autenticación. El partial 'activar_push.html' la consume
    para funcionar en dashboards que no inyectan la var en el contexto Jinja.
    """
    return {"vapid_public_key": os.getenv("VAPID_PUBLIC_KEY")}


class ConfigCategoria(BaseModel):
    activo: bool = True
    modo: str = "inmediato"
    hora_resumen: Optional[str] = "20:00"
    monto_minimo: Optional[float] = 0


@router.get("/categorias-permitidas")
async def categorias_permitidas(
    member: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
):
    """Categorías que el rol del usuario tiene permiso de recibir."""
    rows = db.execute(text("""
        SELECT DISTINCT categoria
        FROM notif_role_categoria
        WHERE organization_id = :org
          AND role = :role
          AND activo = TRUE
    """), {"org": member.organization_id, "role": member.role}).fetchall()
    return {"categorias": [r[0] for r in rows]}


@router.get("/config")
async def get_config(
    member: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
):
    """Configuración actual del usuario + defaults para categorías permitidas."""
    permitidas = db.execute(text("""
        SELECT categoria FROM notif_role_categoria
        WHERE organization_id = :org AND role = :role AND activo = TRUE
    """), {"org": member.organization_id, "role": member.role}).fetchall()
    cats_permitidas = [r[0] for r in permitidas]

    config_actual = db.execute(text("""
        SELECT categoria, activo, modo, hora_resumen, monto_minimo
        FROM notif_config
        WHERE user_id = :uid
    """), {"uid": member.user_id}).fetchall()

    config_dict = {r[0]: {
        "activo": r[1],
        "modo": r[2],
        "hora_resumen": r[3].strftime("%H:%M") if r[3] else "20:00",
        "monto_minimo": float(r[4] or 0),
    } for r in config_actual}

    # Defaults para categorías sin config
    for cat in cats_permitidas:
        if cat not in config_dict:
            config_dict[cat] = {
                "activo": True, "modo": "inmediato",
                "hora_resumen": "20:00", "monto_minimo": 0,
            }

    return {"categorias_permitidas": cats_permitidas, "config": config_dict}


@router.put("/config/{categoria}")
async def actualizar_config(
    categoria: str,
    config: ConfigCategoria,
    member: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
):
    if categoria not in CATEGORIAS_DISPONIBLES:
        raise HTTPException(422, "Categoría inválida")
    if config.modo not in MODOS_VALIDOS:
        raise HTTPException(422, "modo inválido")

    # Validar que el rol tenga permiso
    permitido = db.execute(text("""
        SELECT 1 FROM notif_role_categoria
        WHERE organization_id = :org AND role = :role AND categoria = :cat AND activo = TRUE
    """), {"org": member.organization_id, "role": member.role, "cat": categoria}).fetchone()
    if not permitido:
        raise HTTPException(403, f"Tu rol no tiene permiso sobre {categoria}")

    db.execute(text("""
        INSERT INTO notif_config (user_id, categoria, activo, modo, hora_resumen, monto_minimo, updated_at)
        VALUES (:uid, :cat, :ac, :mo, :hr, :mm, NOW())
        ON CONFLICT (user_id, categoria) DO UPDATE
        SET activo = EXCLUDED.activo,
            modo = EXCLUDED.modo,
            hora_resumen = EXCLUDED.hora_resumen,
            monto_minimo = EXCLUDED.monto_minimo,
            updated_at = NOW()
    """), {
        "uid": member.user_id, "cat": categoria,
        "ac": config.activo, "mo": config.modo,
        "hr": config.hora_resumen, "mm": config.monto_minimo,
    })
    db.commit()
    return {"ok": True}


@router.post("/test")
async def enviar_test(
    member: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
):
    """Envía un push de prueba al dispositivo del usuario."""
    from app.services.notif_service import disparar_evento
    stats = disparar_evento(
        db=db,
        organization_id=member.organization_id,
        evento_tipo="comunicado_nuevo",
        audiencia=f"user_ids:[{member.user_id}]",
        payload={
            "icono": "🔔",
            "tipo_comunicado": "Notificación de prueba",
            "titulo": "Si ves esto, todo funciona correctamente",
        },
        actor_user_id=None,
    )
    db.commit()
    return {"ok": True, "stats": stats}

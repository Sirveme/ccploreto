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
        SELECT categoria, activo, modo, hora_resumen, monto_minimo, subcategorias_activas
        FROM notif_config
        WHERE user_id = :uid
    """), {"uid": member.user_id}).fetchall()

    config_dict = {r[0]: {
        "activo": r[1],
        "modo": r[2],
        "hora_resumen": r[3].strftime("%H:%M") if r[3] else "20:00",
        "monto_minimo": float(r[4] or 0),
        "subcategorias": r[5] or {},   # zClaude-97o
    } for r in config_actual}

    # Defaults para categorías sin config
    for cat in cats_permitidas:
        if cat not in config_dict:
            config_dict[cat] = {
                "activo": True, "modo": "inmediato",
                "hora_resumen": "20:00", "monto_minimo": 0,
                "subcategorias": {},
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


# ── zClaude-97o: subcategorías finas dentro de una categoría gruesa ──────────
class SubcatToggle(BaseModel):
    subcategoria: str
    activo: bool


@router.put("/config/{categoria}/subcategoria")
async def actualizar_subcategoria(
    categoria: str,
    payload: SubcatToggle,
    member: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
):
    """Activa/desactiva una subcategoría fina. Las obligatorias no se desactivan."""
    es_obligatoria = db.execute(text("""
        SELECT 1 FROM notif_categorias_obligatorias
        WHERE organization_id = :org AND categoria_fina = :sc AND activo = TRUE
    """), {"org": member.organization_id, "sc": payload.subcategoria}).fetchone()

    if es_obligatoria and not payload.activo:
        raise HTTPException(403, "Esta categoría es obligatoria, no se puede desactivar")

    db.execute(text("""
        INSERT INTO notif_config (user_id, categoria, subcategorias_activas, updated_at)
        VALUES (:uid, :cat, jsonb_build_object(:sc, :ac), NOW())
        ON CONFLICT (user_id, categoria) DO UPDATE
        SET subcategorias_activas =
                COALESCE(notif_config.subcategorias_activas, '{}'::jsonb)
                || jsonb_build_object(:sc, :ac),
            updated_at = NOW()
    """), {
        "uid": member.user_id, "cat": categoria,
        "sc": payload.subcategoria, "ac": payload.activo,
    })
    db.commit()
    return {"ok": True}


# ── zClaude-97o (Pieza F): catálogo de sonidos para "Probar sonidos" ─────────
@router.get("/sonidos")
async def listar_sonidos(member: Member = Depends(get_current_member)):
    """Catálogo de sonidos disponibles para probar en la UI."""
    return {
        "sonidos": [
            {"archivo": "ka-ching.mp3", "icono": "💰", "descripcion": "Pagos en caja/web"},
            {"archivo": "campana.mp3", "icono": "🔔", "descripcion": "Asambleas y eventos institucionales"},
            {"archivo": "campana_fuerte.mp3", "icono": "🔔", "descripcion": "Última hora antes de asamblea"},
            {"archivo": "beep_notif.mp3", "icono": "🔵", "descripcion": "Encuestas y comunicados"},
            {"archivo": "beep_neutro.mp3", "icono": "📅", "descripcion": "Tributarias y multas"},
            {"archivo": "beep_urgente.mp3", "icono": "⚠️", "descripcion": "Vencimientos próximos"},
            {"archivo": "alarma.mp3", "icono": "🚨", "descripcion": "Emergencias"},
            {"archivo": "cumpleanos.mp3", "icono": "🎂", "descripcion": "Cumpleaños"},
        ]
    }


# ── zClaude-97o-b Pieza A: toggles globales (sonido / modal) ─────────────────
# Se persisten en una fila especial de notif_config con categoria = '__global__'.
class ConfigGlobal(BaseModel):
    sonido_activado: Optional[bool] = None
    modal_activado: Optional[bool] = None


@router.get("/config-global")
async def get_config_global(
    member: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
):
    row = db.execute(text("""
        SELECT sonido_activado, modal_activado
        FROM notif_config
        WHERE user_id = :uid AND categoria = '__global__'
    """), {"uid": member.user_id}).fetchone()
    if row:
        return {
            "sonido_activado": row[0] if row[0] is not None else True,
            "modal_activado": row[1] if row[1] is not None else True,
        }
    return {"sonido_activado": True, "modal_activado": True}


@router.put("/config-global")
async def update_config_global(
    payload: ConfigGlobal,
    member: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
):
    sets = []
    params = {"uid": member.user_id}

    if payload.sonido_activado is not None:
        sets.append("sonido_activado = :s")
        params["s"] = payload.sonido_activado
    if payload.modal_activado is not None:
        sets.append("modal_activado = :m")
        params["m"] = payload.modal_activado

    if not sets:
        return {"ok": True}

    db.execute(text(f"""
        INSERT INTO notif_config (user_id, categoria, activo, modo, sonido_activado, modal_activado, created_at, updated_at)
        VALUES (:uid, '__global__', TRUE, 'inmediato', :s_default, :m_default, NOW(), NOW())
        ON CONFLICT (user_id, categoria) DO UPDATE SET
            {', '.join(sets)},
            updated_at = NOW()
    """), {**params,
           "s_default": payload.sonido_activado if payload.sonido_activado is not None else True,
           "m_default": payload.modal_activado if payload.modal_activado is not None else True})
    db.commit()
    return {"ok": True}


# ══════════════════════════════════════════════════════════════════════════
# zClaude-97p — Avisos FOMO pendientes (para el splash N4 del dashboard)
# ══════════════════════════════════════════════════════════════════════════
@router.get("/avisos-pendientes")
async def avisos_pendientes(
    nivel: Optional[str] = None,
    member: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
):
    """Avisos FOMO no vistos y no caducados del colegiado (los N4 alimentan el splash)."""
    sql = """
        SELECT id, tipo, evento_origen_tipo, evento_origen_id,
               titulo, mensaje, nivel, sonido, url_accion
        FROM fomo_avisos
        WHERE user_id = :uid
          AND visto = FALSE
          AND fecha_disparar <= NOW()
          AND (fecha_caducidad IS NULL OR fecha_caducidad > NOW())
    """
    params = {"uid": member.user_id}
    if nivel:
        sql += " AND nivel = :nivel"
        params["nivel"] = nivel
    sql += " ORDER BY nivel DESC, fecha_disparar ASC"
    rows = db.execute(text(sql), params).fetchall()
    return {"avisos": [{
        "id": r.id,
        "tipo": r.tipo,
        "evento_origen_tipo": r.evento_origen_tipo,
        "evento_origen_id": r.evento_origen_id,
        "titulo": r.titulo,
        "mensaje": r.mensaje,
        "nivel": r.nivel,
        "sonido": r.sonido,
        "url_accion": r.url_accion,
    } for r in rows]}


@router.post("/avisos/{aviso_id}/visto")
async def marcar_aviso_visto(
    aviso_id: int,
    member: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
):
    """Marca un aviso FOMO como visto (solo si pertenece al colegiado)."""
    db.execute(text("""
        UPDATE fomo_avisos
        SET visto = TRUE, visto_at = NOW()
        WHERE id = :id AND user_id = :uid
    """), {"id": aviso_id, "uid": member.user_id})
    db.commit()
    return {"ok": True}

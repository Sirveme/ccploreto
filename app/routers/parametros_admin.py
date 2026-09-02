"""
app/routers/parametros_admin.py — API del Módulo de Parámetros del Sistema.

- LECTURA reutilizable: GET /api/admin/parametros/{seccion}  (cualquier autenticado)
    ?solo_valores=1 → {clave: valor} plano (drop-in para JS de front, p.ej. caja.js)
    sin flag        → {seccion, etiqueta, parametros:[...metadata...]} para el panel
- ESCRITURA (solo rol admin): POST /api/admin/parametros  → versiona vía set_param()
- HISTORIAL (solo rol admin): GET /api/admin/parametros/{seccion}/{clave}/historial

Fase CCPL: los parámetros se editan sobre la fila GLOBAL (organizacion_id NULL).
Override por organización = función futura.
"""
from fastapi import APIRouter, Depends, HTTPException, Body, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Member
from app.routers.dashboard import get_current_member
from app.services import parametros_service as PS

router = APIRouter(prefix="/api/admin/parametros", tags=["parametros"])

# Lectura resuelve override→global usando este org; escritura va a la fila global (None).
ORG_ID_LECTURA = 1


def require_admin(current_member: Member = Depends(get_current_member)) -> Member:
    """Gate de escritura/historial. TEMPORAL durante el desarrollo del módulo:
    incluye 'sote' (soporte/mantenedor) con el mismo acceso que 'admin'.
    Al cerrar el desarrollo, revertir a solo 'admin' (SOTE queda en solo consulta)."""
    if current_member.role not in ("admin", "sote"):
        raise HTTPException(403, "Acceso restringido a administración")
    return current_member


@router.get("")
def listar_secciones(
    member: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
):
    """Catálogo de secciones (para poblar el selector del panel)."""
    return {"secciones": PS.get_secciones(db, solo_activas=True)}


@router.get("/{seccion}")
def leer_seccion(
    seccion: str,
    solo_valores: bool = Query(False),
    member: Member = Depends(get_current_member),   # cualquier autenticado
    db: Session = Depends(get_db),
):
    """Parámetros vigentes de una sección. Reutilizable por el panel y por el front."""
    if solo_valores:
        # {clave: valor} — mismo shape que consumiría un lector JS.
        return PS.get_seccion(db, seccion, org_id=ORG_ID_LECTURA)

    secs = {s["seccion"]: s for s in PS.get_secciones(db, solo_activas=False)}
    etiqueta = secs.get(seccion, {}).get("etiqueta", seccion)
    return {
        "seccion": seccion,
        "etiqueta": etiqueta,
        "parametros": PS.get_seccion_detalle(db, seccion, org_id=ORG_ID_LECTURA),
    }


@router.post("")
def guardar_parametro(
    payload: dict = Body(...),
    member: Member = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Versiona un parámetro (cierra la fila vigente, inserta la nueva origen='admin').

    Validaciones las hace set_param: editable, rango (min/max) y existencia de fila
    vigente → ValueError → HTTP 400. created_by = member.user_id (la persona real).
    """
    seccion = (payload.get("seccion") or "").strip()
    clave = (payload.get("clave") or "").strip()
    motivo = (payload.get("motivo") or "").strip() or None
    valor = payload.get("valor")

    if not seccion or not clave:
        raise HTTPException(400, "Faltan 'seccion' o 'clave'")

    try:
        nuevo_id = PS.set_param(
            db, seccion, clave, valor,
            org_id=None,                 # fila global (Fase CCPL)
            usuario_id=member.user_id,   # la persona real
            motivo=motivo,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    # perdida_automatica: editable, pero el ejecutor aún no existe (aviso, no bloqueo).
    advertencia = None
    if seccion == "fraccionamiento" and clave == "perdida_automatica" and bool(valor):
        advertencia = (
            "Pérdida automática ACTIVADA, pero el ejecutor de pérdida automática aún "
            "no existe: no tendrá efecto hasta construirlo (hoy la pérdida es manual)."
        )

    return {"ok": True, "nuevo_id": nuevo_id, "valor": valor, "advertencia": advertencia}


@router.get("/{seccion}/{clave}/historial")
def historial_parametro(
    seccion: str,
    clave: str,
    member: Member = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Todas las versiones de un parámetro (auditoría: quién cambió qué y cuándo)."""
    versiones = PS.historial(db, seccion, clave, org_id=None)
    out = []
    for v in versiones:
        out.append({
            "valor": v["valor"],
            "vigencia_desde": v["vigencia_desde"].isoformat() if v["vigencia_desde"] else None,
            "vigencia_hasta": v["vigencia_hasta"].isoformat() if v["vigencia_hasta"] else None,
            "origen": v["origen"],
            "motivo": v["motivo"],
            # nombre si resuelve; user_id CRUDO si el join falla; None solo si created_by NULL.
            "cambio": PS.nombre_usuario(db, v["created_by"]),
            "created_at": v["created_at"].isoformat() if v["created_at"] else None,
        })
    return {"seccion": seccion, "clave": clave, "versiones": out}

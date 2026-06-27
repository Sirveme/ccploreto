"""
app/routers/aportes_junta.py
Módulo Aportes a la Junta de Decanos (JDCCPP) — Piezas D, E, J (incremento 1).

Pantallas admin (read/report). Prefix /admin/aportes-junta para evitar colisión
con el módulo de reportes/SUNAT y cualquier ruta /admin/aportes* existente:
  GET  /admin/aportes-junta                      → lista de periodos (E)
  GET  /admin/aportes-junta/config               → configuración read-only (D)
  GET  /admin/aportes-junta/periodo/{periodo_id} → detalle del periodo (E)
  POST /admin/aportes-junta/periodo/{periodo_id}/recalcular → recálculo manual

Acceso: roles admin/decano/tesorero/sote. Org fija = CCPL (1).
Pendiente (incremento 2): F (registro manual), G (carga histórica), H (PDF),
I (Excel), registrar depósito (upload a GCS).
"""

from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Member, User
from app.routers.dashboard import get_current_member
from app.utils.templates import templates

router = APIRouter(prefix="/admin/aportes-junta", tags=["aportes-junta"])

ORG_CCPL = 1
_ROLES_APORTES = ("admin", "decano", "tesorero", "sote")
MESES_ES = [
    "", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]


def require_aportes(current_member: Member = Depends(get_current_member)) -> Member:
    if current_member is None or current_member.role not in _ROLES_APORTES:
        raise HTTPException(status_code=403, detail="Acceso restringido a administración")
    return current_member


def _show_psp_footer(db: Session, current_member: Member) -> bool:
    """Pieza J: el footer de Perú Sistemas Pro aparece solo tras el onboarding
    (cuando el usuario ya cambió su clave inicial)."""
    user = db.query(User).filter(User.id == current_member.user_id).first()
    return bool(user and user.debe_cambiar_clave is False)


# ════════════════════════════════════════════════════════════════
# PIEZA E — LISTA DE PERIODOS
# ════════════════════════════════════════════════════════════════
@router.get("", response_class=HTMLResponse)
async def aportes_lista(
    request: Request,
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_aportes),
):
    periodos = db.execute(text("""
        SELECT ap.id, ap.anio, ap.mes, ap.estado,
               ap.cantidad_nuevos, ap.monto_nuevos,
               ap.cantidad_habiles, ap.monto_habiles, ap.monto_total,
               ap.cerrado_en,
               dep.id AS deposito_id, dep.numero_voucher, dep.fecha_deposito, dep.monto AS deposito_monto,
               (SELECT COUNT(*) FROM aporte_periodo_alerta a
                 WHERE a.aporte_periodo_id = ap.id AND a.tipo = 'colegiado_sin_pago'
                   AND a.resuelto = FALSE) AS alertas
        FROM aporte_periodos ap
        LEFT JOIN aporte_deposito dep ON dep.aporte_periodo_id = ap.id
        WHERE ap.organizacion_id = :org
        ORDER BY ap.anio DESC, ap.mes DESC
    """), {"org": ORG_CCPL}).fetchall()

    filas = [{
        "id": p.id,
        "periodo_label": f"{MESES_ES[p.mes]} {p.anio}",
        "anio": p.anio, "mes": p.mes,
        "estado": p.estado,
        "cantidad_nuevos": p.cantidad_nuevos or 0,
        "monto_nuevos": float(p.monto_nuevos or 0),
        "cantidad_habiles": p.cantidad_habiles or 0,
        "monto_habiles": float(p.monto_habiles or 0),
        "monto_total": float(p.monto_total or 0),
        "alertas": p.alertas or 0,
        "tiene_deposito": p.deposito_id is not None,
        "numero_voucher": p.numero_voucher,
    } for p in periodos]

    return templates.TemplateResponse("pages/admin/aportes_list.html", {
        "request": request,
        "periodos": filas,
        "show_psp_footer": _show_psp_footer(db, current_member),
    })


# ════════════════════════════════════════════════════════════════
# PIEZA D — CONFIGURACIÓN (read-only)
# ════════════════════════════════════════════════════════════════
@router.get("/config", response_class=HTMLResponse)
async def aportes_config(
    request: Request,
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_aportes),
):
    junta = db.execute(text("""
        SELECT j.id, j.nombre, j.nombre_corto, j.profesion, j.ruc,
               j.banco_destino, j.cuenta_destino, j.moneda, j.titular_cuenta,
               o.codigo_ante_junta
        FROM organizations o
        JOIN juntas j ON j.id = o.junta_id
        WHERE o.id = :org
    """), {"org": ORG_CCPL}).fetchone()

    config = None
    if junta:
        config = db.execute(text("""
            SELECT * FROM junta_config_aporte
            WHERE junta_id = :jid AND vigencia_hasta IS NULL
            ORDER BY vigencia_desde DESC LIMIT 1
        """), {"jid": junta.id}).fetchone()

    return templates.TemplateResponse("pages/admin/aportes_config.html", {
        "request": request,
        "junta": junta,
        "config": config,
        "show_psp_footer": _show_psp_footer(db, current_member),
    })


# ════════════════════════════════════════════════════════════════
# PIEZA E — DETALLE DEL PERIODO
# ════════════════════════════════════════════════════════════════
@router.get("/periodo/{periodo_id}", response_class=HTMLResponse)
async def aportes_detalle(
    periodo_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_aportes),
):
    periodo = db.execute(text("""
        SELECT ap.*, dep.id AS deposito_id, dep.numero_voucher, dep.fecha_deposito,
               dep.monto AS deposito_monto, dep.banco_emisor, dep.evidencia_url
        FROM aporte_periodos ap
        LEFT JOIN aporte_deposito dep ON dep.aporte_periodo_id = ap.id
        WHERE ap.id = :pid AND ap.organizacion_id = :org
    """), {"pid": periodo_id, "org": ORG_CCPL}).fetchone()

    if not periodo:
        raise HTTPException(status_code=404, detail="Periodo no encontrado")

    nuevos = db.execute(text("""
        SELECT codigo_matricula, apellidos_nombres, dni,
               fecha_pago_der_col, fecha_colegiatura, monto_aporte,
               fuente_registro
        FROM aporte_detalle_nuevos
        WHERE aporte_periodo_id = :pid
        ORDER BY codigo_matricula NULLS LAST, apellidos_nombres
    """), {"pid": periodo_id}).fetchall()

    alertas = db.execute(text("""
        SELECT colegiado_id, mensaje, created_at
        FROM aporte_periodo_alerta
        WHERE aporte_periodo_id = :pid AND tipo = 'colegiado_sin_pago' AND resuelto = FALSE
        ORDER BY created_at
    """), {"pid": periodo_id}).fetchall()

    ctx = {
        "request": request,
        "periodo": periodo,
        "periodo_label": f"{MESES_ES[periodo.mes]} {periodo.anio}",
        "nuevos": nuevos,
        "alertas": alertas,
        "show_psp_footer": _show_psp_footer(db, current_member),
    }
    return templates.TemplateResponse("pages/admin/aportes_detalle.html", ctx)


# ════════════════════════════════════════════════════════════════
# Recálculo manual (solo periodos abiertos)
# ════════════════════════════════════════════════════════════════
@router.post("/periodo/{periodo_id}/recalcular")
async def aportes_recalcular(
    periodo_id: int,
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_aportes),
):
    periodo = db.execute(text("""
        SELECT estado, anio, mes FROM aporte_periodos
        WHERE id = :pid AND organizacion_id = :org
    """), {"pid": periodo_id, "org": ORG_CCPL}).fetchone()

    if not periodo:
        raise HTTPException(status_code=404, detail="Periodo no encontrado")
    if periodo.estado == "cerrado":
        return JSONResponse({"ok": False, "error": "El periodo está cerrado (inmutable)."},
                            status_code=400)

    from app.services.aportes_junta_service import calcular_periodo_actual
    from datetime import datetime
    from app.services.aportes_junta_service import TZ_PERU
    ahora = datetime.now(TZ_PERU)
    if (periodo.anio, periodo.mes) != (ahora.year, ahora.month):
        return JSONResponse(
            {"ok": False, "error": "Solo se recalcula el periodo del mes en curso. "
             "Los anteriores se gestionan por carga manual."},
            status_code=400,
        )

    result = calcular_periodo_actual(db, organizacion_id=ORG_CCPL)
    if not result:
        return JSONResponse({"ok": False, "error": "No se pudo recalcular."}, status_code=400)
    return JSONResponse({"ok": True, "result": {
        "cantidad_nuevos": result["cantidad_nuevos"],
        "cantidad_habiles": result["cantidad_habiles"],
        "monto_total": result["monto_total"],
        "pendientes_registro": result["pendientes_registro"],
    }})

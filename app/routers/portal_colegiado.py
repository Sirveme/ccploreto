"""
Router: Portal del Colegiado Inactivo
app/routers/portal_colegiado.py

USA el sistema de auth existente (JWT en cookie access_token).
NO implementa login propio — el login es /auth/login.

Flujo:
  1. Colegiado inactivo hace login con DNI en /auth/login
  2. auth.py detecta condición → redirige a /portal/inactivo
  3. Este router provee los datos: deuda, cuentas, stats
"""

from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, text

from app.database import get_db
from app.models import Colegiado, Debt, Organization, Member
from app.routers.dashboard import get_current_member

router = APIRouter(prefix="/api/portal", tags=["portal"])

TZ_PERU = timezone(timedelta(hours=-5))


def _get_colegiado(member: Member, db: Session) -> Colegiado:
    """Obtiene el colegiado asociado al member autenticado."""
    col = db.query(Colegiado).filter(
        Colegiado.member_id == member.id,
        Colegiado.organization_id == member.organization_id,
    ).first()

    if not col and member.user:
        col = db.query(Colegiado).filter(
            Colegiado.organization_id == member.organization_id,
            Colegiado.nro_documento == member.user.public_id,
        ).first()

    if not col:
        raise HTTPException(404, "Colegiado no encontrado para este usuario")
    return col


@router.get("/mi-perfil")
async def mi_perfil(
    member: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
):
    col = _get_colegiado(member, db)
    org = db.query(Organization).filter(Organization.id == col.organization_id).first()

    nombre_completo = col.apellidos_nombres or ""
    if "," in nombre_completo:
        apellidos, nombres = nombre_completo.split(",", 1)
        nombre_corto = nombres.strip().split()[0] if nombres.strip() else apellidos.strip()
        nombres = nombres.strip()
    else:
        partes = nombre_completo.split()
        nombre_corto = partes[2] if len(partes) > 2 else partes[0] if partes else ""
        nombres = " ".join(partes[2:]) if len(partes) > 2 else nombre_completo

    return {
        "id": col.id,
        "nombre_completo": nombre_completo,
        "nombre_corto": nombre_corto,
        "nombres": nombres,
        "dni": col.nro_documento,
        "matricula": col.codigo_matricula,
        "condicion": col.condicion,
        "organizacion": org.name if org else "Colegio Profesional",
        "tiene_fraccionamiento": bool(getattr(col, 'tiene_fraccionamiento', False)),
        "telefono_colegio": getattr(org, 'phone', None),
    }


@router.get("/mi-deuda")
async def mi_deuda(
    member: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
):
    col = _get_colegiado(member, db)

    deudas = db.query(Debt).filter(
        Debt.colegiado_id == col.id,
        Debt.status.in_(["pending", "partial"]),
    ).order_by(Debt.due_date.asc()).all()

    total = sum(float(d.balance) for d in deudas)

    fracc_config = {
        "monto_minimo": 500,
        "cuota_inicial_pct": 20,
        "cuota_minima": 100,
        "max_cuotas": 12,
    }
    califica_fracc = total >= fracc_config["monto_minimo"]

    items = [{
        "id": d.id,
        "concepto": d.concept or "Cuota mensual",
        "monto_original": float(d.amount),
        "balance": float(d.balance),
        "fecha_venc": d.due_date.strftime("%m/%Y") if d.due_date else None,
        "tipo": getattr(d, 'debt_type', "cuota_ordinaria"),
        "estado": d.status,
    } for d in deudas]

    return {
        "deudas": items,
        "total": total,
        "cantidad": len(items),
        "califica_fraccionamiento": califica_fracc,
        "fraccionamiento": fracc_config if califica_fracc else None,
    }


@router.get("/cuentas-pago")
async def cuentas_pago(
    member: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
):
    try:
        cuentas = db.execute(text("""
            SELECT banco, numero_cuenta, tipo_cuenta, titular, moneda, cci
            FROM cuentas_receptoras
            WHERE organization_id = :org_id AND activa = true
            ORDER BY banco
        """), {"org_id": member.organization_id}).fetchall()

        return {"cuentas": [{
            "banco": c.banco,
            "numero_cuenta": c.numero_cuenta,
            "tipo_cuenta": c.tipo_cuenta,
            "titular": c.titular,
            "moneda": c.moneda or "PEN",
            "cci": c.cci,
        } for c in cuentas]}
    except Exception:
        return {"cuentas": []}


@router.get("/stats-servicios")
async def stats_servicios(
    member: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
):
    activos = db.query(func.count(Colegiado.id)).filter(
        Colegiado.organization_id == member.organization_id,
        Colegiado.condicion == "habil",
    ).scalar() or 0

    return {
        "colegiados_activos": activos,
        "rucs_monitoreados": 847,       # TODO: real
        "consultas_ia_mes": 186,        # TODO: real
        "proximo_evento": "Mar 2026",   # TODO: real
    }
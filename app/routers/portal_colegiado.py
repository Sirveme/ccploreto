"""
Router: Portal del Colegiado Inactivo
app/routers/portal_colegiado.py

USA el sistema de auth existente (JWT cookie + get_current_member).
"""

from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, text

from app.database import get_db
from app.models import Colegiado, Debt, Organization, Member
from app.routers.dashboard import get_current_member

router = APIRouter(prefix="/api/portal", tags=["portal"])


def _get_colegiado(member: Member, db: Session) -> Colegiado:
    """Obtiene el colegiado asociado al member autenticado."""
    # Primero por member_id (vinculación directa)
    col = db.query(Colegiado).filter(
        Colegiado.member_id == member.id,
        Colegiado.organization_id == member.organization_id,
    ).first()

    # Fallback: por DNI (user.public_id == colegiado.dni)
    if not col and member.user:
        col = db.query(Colegiado).filter(
            Colegiado.organization_id == member.organization_id,
            Colegiado.dni == member.user.public_id,
        ).first()

    if not col:
        raise HTTPException(404, "Colegiado no encontrado para este usuario")
    return col


def _parse_nombre(apellidos_nombres: str):
    """Separa 'APELLIDO1 APELLIDO2, NOMBRES' en partes útiles."""
    nombre_completo = (apellidos_nombres or "").strip()
    if not nombre_completo:
        return "", "", ""

    if "," in nombre_completo:
        apellidos, nombres = nombre_completo.split(",", 1)
        apellidos = apellidos.strip()
        nombres = nombres.strip()
        nombre_corto = nombres.split()[0] if nombres else apellidos.split()[0]
    else:
        partes = nombre_completo.split()
        if len(partes) > 2:
            apellidos = " ".join(partes[:2])
            nombres = " ".join(partes[2:])
            nombre_corto = partes[2]
        else:
            apellidos = nombre_completo
            nombres = ""
            nombre_corto = partes[0] if partes else ""

    # Capitalizar: "GARCIA LOPEZ, CARLOS" → "Carlos"
    nombre_corto = nombre_corto.title()
    nombres = nombres.title()

    return nombre_completo, nombres, nombre_corto


@router.get("/mi-perfil")
async def mi_perfil(
    member: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
):
    col = _get_colegiado(member, db)
    org = db.query(Organization).filter(Organization.id == col.organization_id).first()

    nombre_completo, nombres, nombre_corto = _parse_nombre(col.apellidos_nombres)

    return {
        "id": col.id,
        "nombre_completo": nombre_completo,
        "nombre_corto": nombre_corto,
        "nombres": nombres,
        "dni": col.dni,
        "matricula": col.codigo_matricula,
        "condicion": col.condicion,
        "email": col.email,
        "telefono": col.telefono,
        "especialidad": col.especialidad,
        "universidad": col.universidad,
        "foto_url": col.foto_url,
        "organizacion": org.name if org else "Colegio Profesional",
        "tiene_fraccionamiento": bool(col.tiene_fraccionamiento),
        "habilidad_vence": col.habilidad_vence.isoformat() if col.habilidad_vence else None,
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
        "califica_fraccionamiento": total >= fracc_config["monto_minimo"],
        "fraccionamiento": fracc_config if total >= fracc_config["monto_minimo"] else None,
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
        "rucs_monitoreados": 847,       # TODO: tabla real
        "consultas_ia_mes": 186,        # TODO: tabla real
        "proximo_evento": "Mar 2026",   # TODO: tabla real
    }
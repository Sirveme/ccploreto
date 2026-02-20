"""
Router: Portal del Colegiado Inactivo
app/routers/portal_colegiado.py

USA el sistema de auth existente (JWT cookie + get_current_member).
"""

from datetime import date as dt_date, datetime, timezone, timedelta
from sqlalchemy import and_

from app.models_debt_management import Debt, Fraccionamiento, EstadoFraccionamiento, FraccionamientoCuota
from app.models import Colegiado, Member, ConceptoCobro, Organization

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, text

from app.database import get_db
from app.routers.dashboard import get_current_member

from dateutil.relativedelta import relativedelta   # pip install python-dateutil
from pydantic import BaseModel, field_validator
import math


router = APIRouter(prefix="/api/portal", tags=["portal"])


# ── Schema de entrada ─────────────────────────────────────────────────────────
class FraccionamientoRequest(BaseModel):
    cuota_inicial: float
    num_cuotas: int
    notas: str = ""

    @field_validator("cuota_inicial")
    @classmethod
    def cuota_positiva(cls, v):        # ← añadir @classmethod
        if v <= 0:
            raise ValueError("La cuota inicial debe ser mayor a 0")
        return round(v, 2)

    @field_validator("num_cuotas")
    @classmethod
    def cuotas_validas(cls, v):
        if not (2 <= v <= 12):
            raise ValueError("El número de cuotas debe estar entre 2 y 12")
        return v



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


from datetime import date as dt_date
from app.models_debt_management import Debt, Fraccionamiento, EstadoFraccionamiento


@router.get("/api/portal/mi-deuda")
async def mi_deuda(
    member: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
):
    """
    Retorna las deudas pendientes del colegiado autenticado.
    El frontend agrupa por año usando el campo `periodo`.
    """
    colegiado = _get_colegiado(member, db)

    # DEBUG TEMPORAL — quitar después
    print(f"[DEBUG] colegiado.id = {colegiado.id}")

    # ── Deudas pendientes o parciales ─────────────────────────────────────
    deudas_qs = (
        db.query(Debt)
        .filter(
            Debt.colegiado_id == colegiado.id,
            Debt.status.in_(["pending", "partial"]),
            Debt.estado_gestion.in_(["vigente", "en_cobranza", "fraccionada"]),
        )
        .order_by(Debt.periodo.asc())
        .all()
    )

    # DEBUG TEMPORAL — quitar después
    print(f"[DEBUG] deudas encontradas = {len(deudas_qs)}")
    print(f"[DEBUG] total = {sum(float(d.balance or 0) for d in deudas_qs)}")

    total = sum(float(d.balance or 0) for d in deudas_qs)

    deudas_list = [
        {
            "id":             d.id,
            "concept":        d.concept,          # "Cuotas Ordinarias"
            "period_label":   d.period_label,     # "2024" / "Ene-Dic 2024"
            "periodo":        d.periodo,           # "2024" / "2024-01"
            "debt_type":      d.debt_type,
            "amount":         float(d.amount  or 0),
            "balance":        float(d.balance or 0),
            "status":         d.status,
            "estado_gestion": d.estado_gestion,
            "due_date":       d.due_date.isoformat() if d.due_date else None,
            "es_exigible":    d.es_exigible,
            "dias_mora":      d.dias_mora,
        }
        for d in deudas_qs
    ]

    # ── ¿Califica fraccionamiento? ─────────────────────────────────────────
    plan_activo = (
        db.query(Fraccionamiento)
        .filter(
            Fraccionamiento.colegiado_id == colegiado.id,
            Fraccionamiento.estado == EstadoFraccionamiento.ACTIVO,
        )
        .first()
    )
    califica_fracc = (total >= 500.0) and (plan_activo is None)

    # ── Campaña / descuento activo ─────────────────────────────────────────
    hoy = dt_date.today()
    if hoy.month <= 2:
        campana = {
            "nombre":        "Campaña Febrero",
            "descripcion":   "20% de descuento en cuotas ordinarias del año en curso.",
            "descuento_pct": 0.20,
            "fecha_fin":     f"28 Feb {hoy.year}",
        }
    elif hoy.month == 3:
        campana = {
            "nombre":        "Campaña Marzo",
            "descripcion":   "10% de descuento en cuotas ordinarias del año en curso.",
            "descuento_pct": 0.10,
            "fecha_fin":     f"31 Mar {hoy.year}",
        }
    else:
        campana = None

    return {
        "deudas":                   deudas_list,
        "total":                    total,
        "cantidad":                 len(deudas_list),
        "califica_fraccionamiento": califica_fracc,
        "plan_activo":              plan_activo is not None,
        "campana":                  campana,
    }


# ── Endpoint ──────────────────────────────────────────────────────────────────
@router.post("/api/finanzas/fraccionamiento/crear")
async def crear_fraccionamiento(
    data: FraccionamientoRequest,
    member: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
):
    """
    Crea un plan de fraccionamiento para el colegiado autenticado.

    Reglas del CCPL:
    - Deuda mínima: S/ 500
    - Cuota inicial: mínimo 20% de la deuda total
    - Cuota mensual resultante: mínimo S/ 100
    - Máximo 12 cuotas
    - Cuota 0 = inicial (pago inmediato)
    - Cuotas 1..N = mensuales, vencen el día 15 de cada mes
    - Cada cuota mensual pagada otorga habilidad hasta fin de ese mes
    """
    colegiado = _get_colegiado(member, db)
    hoy = dt_date.today()

    # ── 1. Calcular total de deuda pendiente ──────────────────────────────
    deudas_qs = (
        db.query(Debt)
        .filter(
            Debt.colegiado_id == colegiado.id,
            Debt.status.in_(["pending", "partial"]),
            Debt.estado_gestion.in_(["vigente", "en_cobranza"]),
        )
        .all()
    )

    if not deudas_qs:
        raise HTTPException(400, "No tienes deudas pendientes para fraccionar")

    total = round(sum(float(d.balance or 0) for d in deudas_qs), 2)

    # ── 2. Validaciones de negocio ────────────────────────────────────────
    if total < 500:
        raise HTTPException(400, f"La deuda total (S/ {total:.2f}) es menor al mínimo de S/ 500")

    minimo_inicial = round(total * 0.20, 2)
    if data.cuota_inicial < minimo_inicial:
        raise HTTPException(
            400,
            f"La cuota inicial mínima es S/ {minimo_inicial:.2f} (20% de S/ {total:.2f})"
        )

    if data.cuota_inicial >= total:
        raise HTTPException(400, "La cuota inicial no puede cubrir la deuda completa; usa pago directo")

    saldo = round(total - data.cuota_inicial, 2)
    monto_cuota = round(saldo / data.num_cuotas, 2)

    if monto_cuota < 100:
        raise HTTPException(
            400,
            f"La cuota mensual resultante (S/ {monto_cuota:.2f}) es menor al mínimo de S/ 100. "
            f"Reduce el número de cuotas o aumenta la cuota inicial."
        )

    # ── 3. Verificar que no haya plan activo ──────────────────────────────
    plan_existente = (
        db.query(Fraccionamiento)
        .filter(
            Fraccionamiento.colegiado_id == colegiado.id,
            Fraccionamiento.estado == "activo",
        )
        .first()
    )
    if plan_existente:
        raise HTTPException(
            409,
            f"Ya tienes un plan de fraccionamiento activo (#{plan_existente.numero_solicitud})"
        )

    # ── 4. Generar número de solicitud ────────────────────────────────────
    anio = hoy.year
    ultimo = (
        db.query(Fraccionamiento)
        .filter(Fraccionamiento.organization_id == colegiado.organization_id)
        .filter(Fraccionamiento.numero_solicitud.like(f"FRACC-{anio}-%"))
        .count()
    )
    numero_solicitud = f"FRACC-{anio}-{str(ultimo + 1).zfill(4)}"

    # ── 5. Fechas ─────────────────────────────────────────────────────────
    # Primera cuota mensual vence el 15 del mes siguiente
    primer_venc = hoy.replace(day=15) + relativedelta(months=1)
    ultima_venc  = primer_venc + relativedelta(months=data.num_cuotas - 1)

    # ── 6. Crear Fraccionamiento ──────────────────────────────────────────
    fracc = Fraccionamiento(
        organization_id       = colegiado.organization_id,
        colegiado_id          = colegiado.id,
        numero_solicitud      = numero_solicitud,
        fecha_solicitud       = hoy,
        deuda_total_original  = total,
        cuota_inicial         = data.cuota_inicial,
        cuota_inicial_pagada  = False,   # se marcará al registrar el pago
        saldo_a_fraccionar    = saldo,
        num_cuotas            = data.num_cuotas,
        monto_cuota           = monto_cuota,
        cuotas_pagadas        = 0,
        cuotas_atrasadas      = 0,
        saldo_pendiente       = total,   # baja con cada pago (inicial + mensuales)
        fecha_inicio          = hoy,
        fecha_fin_estimada    = ultima_venc,
        proxima_cuota_fecha   = hoy,     # la inicial es inmediata
        proxima_cuota_numero  = 0,
        estado                = "activo",
        created_by            = member.user_id,
        approved_by           = None,    # auto-aprobado desde el portal
    )
    db.add(fracc)
    db.flush()   # obtener fracc.id sin cerrar la transacción

    # ── 7. Crear cuotas ───────────────────────────────────────────────────
    cuotas = []

    # Cuota 0 — inicial (pago inmediato)
    cuotas.append(FraccionamientoCuota(
        fraccionamiento_id = fracc.id,
        numero_cuota       = 0,
        monto              = data.cuota_inicial,
        fecha_vencimiento  = hoy,
        habilidad_hasta    = None,  # la inicial no otorga habilidad sola
    ))

    # Cuotas 1..N — mensuales
    for i in range(1, data.num_cuotas + 1):
        venc = primer_venc + relativedelta(months=i - 1)
        # Habilidad hasta el último día de ese mes
        fin_mes = (venc.replace(day=1) + relativedelta(months=1)) - timedelta(days=1)
        cuotas.append(FraccionamientoCuota(
            fraccionamiento_id = fracc.id,
            numero_cuota       = i,
            monto              = monto_cuota,
            fecha_vencimiento  = venc,
            habilidad_hasta    = fin_mes,
        ))

    db.bulk_save_objects(cuotas)

    # ── 8. Marcar deudas como fraccionadas ────────────────────────────────
    for d in deudas_qs:
        d.estado_gestion    = "fraccionada"
        d.fraccionamiento_id = fracc.id

    db.commit()
    db.refresh(fracc)

    # ── 9. Respuesta ──────────────────────────────────────────────────────
    return {
        "success":          True,
        "numero_solicitud": fracc.numero_solicitud,
        "fraccionamiento_id": fracc.id,
        "deuda_total":      total,
        "cuota_inicial":    data.cuota_inicial,
        "num_cuotas":       data.num_cuotas,
        "monto_cuota":      monto_cuota,
        "primera_cuota":    primer_venc.isoformat(),
        "ultima_cuota":     ultima_venc.isoformat(),
        "mensaje": (
            f"Plan #{numero_solicitud} creado. "
            f"Realiza el pago inicial de S/ {data.cuota_inicial:.2f} para reactivarte."
        ),
    }

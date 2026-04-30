"""
app/services/generador_deudas.py
Generador de deudas para CCPL:
  1. Cuotas Ordinarias Mensuales
  2. Cuotas de Fraccionamiento vencidas

Diseño:
  - Idempotente: UniqueConstraint en debts evita duplicados
  - Auditable: registra lote_migracion + created_by
  - Exclusiones: vitalicios, fallecidos, retirados
  - Fraccionamiento: 2 cuotas consecutivas impagas → alerta (no pérdida automática)
"""

import logging
from datetime import date, datetime, timezone
from calendar import monthrange
from typing import Optional

from dateutil.relativedelta import relativedelta

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from sqlalchemy import func

logger = logging.getLogger(__name__)

MESES = ['', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
         'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']

# Condiciones que excluyen al colegiado de generar deuda
CONDICIONES_EXCLUIR = {'fallecido', 'retirado', 'vitalicio', 'baja', 'suspendido'}


# ═══════════════════════════════════════════════════════════════
# 1. GENERADOR — CUOTAS ORDINARIAS
# ═══════════════════════════════════════════════════════════════

def generar_cuotas_ordinarias(
    db:              Session,
    organization_id: int,
    anio:            int,
    mes:             int,
    created_by:      Optional[int] = None,
    dia_vencimiento: int = 28,
) -> dict:
    """
    Genera deudas de cuota ordinaria para todos los colegiados
    que no hayan pagado el mes indicado.

    Retorna dict con: generadas, omitidas, errores, detalle.
    """
    from app.models_debt_management import Debt
    from app.models import Colegiado, ConceptoCobro, Payment

    periodo    = f"{anio}-{mes:02d}"
    lote_id    = f"GEN-ORD-{anio}{mes:02d}-{datetime.now().strftime('%H%M%S')}"
    ultimo_dia = monthrange(anio, mes)[1]
    due_date   = datetime(anio, mes, min(dia_vencimiento, ultimo_dia),
                          23, 59, 59, tzinfo=timezone.utc)

    # Obtener concepto de cuota ordinaria
    concepto_cobro = db.query(ConceptoCobro).filter(
        ConceptoCobro.organization_id == organization_id,
        ConceptoCobro.codigo          == 'CUOT-ORD',
        ConceptoCobro.activo          == True,
    ).first()

    if not concepto_cobro:
        return {"error": "No se encontró el concepto CUOT-ORD activo"}

    monto = float(concepto_cobro.monto_base)

    # Todos los colegiados activos (no excluidos)
    colegiados = db.query(Colegiado).filter(
        Colegiado.organization_id == organization_id,
        func.lower(Colegiado.condicion).notin_(CONDICIONES_EXCLUIR),
    ).all()

    generadas = 0
    omitidas  = 0
    errores   = 0
    detalle   = []

    for col in colegiados:
        # ── Período de gracia: 3 meses desde el MES de colegiatura ─────────
        if col.fecha_colegiatura:
            fc = col.fecha_colegiatura
            if hasattr(fc, 'date'):
                fc = fc.date()
            mes_inscripcion = date(fc.year, fc.month, 1)
            primer_mes_pago = mes_inscripcion + relativedelta(months=3)
            primer_dia_mes  = date(anio, mes, 1)
            if primer_dia_mes < primer_mes_pago:
                omitidas += 1
                detalle.append({
                    "colegiado_id": col.id,
                    "matricula":    col.codigo_matricula,
                    "nombre":       col.apellidos_nombres,
                    "accion":       "omitida",
                    "motivo":       f"En período de gracia hasta {(primer_mes_pago - relativedelta(months=1)).strftime('%m/%Y')}. Paga desde {primer_mes_pago.strftime('%m/%Y')}",
                })
                continue
        # ── Fin verificación gracia ─────────────────────────────────────────

        # Verificar si ya existe deuda para este periodo
        existe = db.query(Debt).filter(
            Debt.organization_id  == organization_id,
            Debt.colegiado_id     == col.id,
            Debt.concepto_cobro_id == concepto_cobro.id,
            Debt.periodo          == periodo,
        ).first()

        if existe:
            omitidas += 1
            continue

        # Verificar si pagó el mes (payments aprobados que cubran este periodo)
        pago_existente = _verificar_pago_periodo(db, col.id, anio, mes)
        if pago_existente:
            omitidas += 1
            detalle.append({
                "matricula": col.codigo_matricula,
                "accion":    "omitida",
                "razon":     "ya_pago",
            })
            continue

        # Generar deuda
        try:
            debt = Debt(
                organization_id   = organization_id,
                colegiado_id      = col.id,
                member_id         = col.member_id,
                concepto_cobro_id = concepto_cobro.id,
                concept           = f"Cuota Ordinaria {MESES[mes]} {anio}",
                periodo           = periodo,
                period_label      = f"{MESES[mes]} {anio}",
                debt_type         = "cuota_ordinaria",
                amount            = monto,
                balance           = monto,
                status            = "pending",
                estado_gestion    = "vigente",
                fecha_generacion  = date.today(),
                due_date          = due_date,
                origen            = "generacion_auto",
                lote_migracion    = lote_id,
                created_by        = created_by,
            )
            db.add(debt)
            db.flush()
            generadas += 1
            detalle.append({
                "matricula": col.codigo_matricula,
                "accion":    "generada",
                "monto":     monto,
            })
        except IntegrityError:
            db.rollback()
            omitidas += 1  # Ya existía (race condition)
        except Exception as e:
            db.rollback()
            errores += 1
            logger.error(f"[GenDeudas] Error colegiado {col.codigo_matricula}: {e}")

    db.commit()
    logger.info(f"[GenDeudas] {periodo} → generadas={generadas} omitidas={omitidas} errores={errores}")

    # ── Sincronizar condiciones ──────────────────────────────────
    from app.services.evaluar_habilidad import sincronizar_condicion
    from app.models import Organization

    org = db.query(Organization).filter(
        Organization.id == organization_id
    ).first()
    org_dict = {"id": org.id, "config": {}} if org else {}

    colegiados_con_deuda = db.query(Colegiado).filter(
        Colegiado.organization_id == organization_id,
        Colegiado.condicion.notin_(CONDICIONES_EXCLUIR),
    ).all()

    cambios = 0
    for col in colegiados_con_deuda:
        cambio = sincronizar_condicion(db, col, org_dict)
        if cambio:
            cambios += 1

    db.commit()
    logger.info(f"[GenDeudas] Sincronización condiciones: {cambios} cambios")

    return {
        "lote_id":   lote_id,
        "periodo":   periodo,
        "generadas": generadas,
        "omitidas":  omitidas,
        "errores":   errores,
        "detalle":   detalle,
        "cambios_condicion": cambios,
    }


def _verificar_pago_periodo(db: Session, colegiado_id: int, anio: int, mes: int) -> bool:
    """Verifica si el colegiado pagó la cuota ordinaria del mes indicado."""
    from app.models_debt_management import Debt

    # Buscar deuda del periodo marcada como pagada
    deuda_pagada = db.query(Debt).filter(
        Debt.colegiado_id == colegiado_id,
        Debt.debt_type    == 'cuota_ordinaria',
        Debt.periodo      == f"{anio}-{mes:02d}",
        Debt.status       == 'paid',
    ).first()

    return deuda_pagada is not None


# ═══════════════════════════════════════════════════════════════
# 2. GENERADOR — CUOTAS DE FRACCIONAMIENTO VENCIDAS
# ═══════════════════════════════════════════════════════════════

def generar_cuotas_fraccionamiento(
    db:              Session,
    organization_id: int,
    created_by:      Optional[int] = None,
    fecha_ref:       Optional[date] = None,
) -> dict:
    """
    Revisa todos los fraccionamientos activos y para cada cuota
    vencida no pagada, genera una Debt si no existe aún.

    También actualiza cuotas_atrasadas y marca en_riesgo si >= 2 consecutivas.

    NO marca como 'perdido' automáticamente — eso requiere decisión manual/asamblea.
    """
    from app.models_debt_management import (
        Debt, Fraccionamiento, FraccionamientoCuota
    )
    from app.models import ConceptoCobro

    hoy        = fecha_ref or date.today()
    lote_id    = f"GEN-FRACC-{hoy.strftime('%Y%m%d-%H%M%S')}"
    generadas  = 0
    omitidas   = 0
    alertas    = []
    errores    = 0

    # Concepto de fraccionamiento
    concepto_fracc = db.query(ConceptoCobro).filter(
        ConceptoCobro.organization_id == organization_id,
        ConceptoCobro.codigo          == 'CUOT-FRAC',
        ConceptoCobro.activo          == True,
    ).first()

    if not concepto_fracc:
        return {"error": "No se encontró el concepto CUOT-FRAC activo"}

    # Fraccionamientos activos
    fraccionamientos = db.query(Fraccionamiento).filter(
        Fraccionamiento.organization_id == organization_id,
        Fraccionamiento.estado          == 'activo',
    ).all()

    for fracc in fraccionamientos:
        cuotas_vencidas_no_pagadas = [
            c for c in fracc.cuotas
            if not c.pagada and c.fecha_vencimiento < hoy
        ]

        # Actualizar contador de cuotas atrasadas
        fracc.cuotas_atrasadas = len(cuotas_vencidas_no_pagadas)

        # Detectar consecutivas (para alerta, no para pérdida automática)
        consecutivas = _contar_consecutivas_vencidas(fracc.cuotas, hoy)
        if consecutivas >= 2:
            alertas.append({
                "fraccionamiento": fracc.numero_solicitud,
                "colegiado":       fracc.colegiado.codigo_matricula if fracc.colegiado else "?",
                "consecutivas":    consecutivas,
                "alerta":          "EN_RIESGO" if consecutivas >= 2 else "OK",
            })
            logger.warning(
                f"[FRACC] {fracc.numero_solicitud} tiene {consecutivas} cuotas consecutivas vencidas"
            )

        # Generar Debt por cada cuota vencida sin deuda
        for cuota in cuotas_vencidas_no_pagadas:
            periodo = cuota.fecha_vencimiento.strftime('%Y-%m')

            # Verificar si ya existe deuda para esta cuota
            existe = db.query(Debt).filter(
                Debt.organization_id   == organization_id,
                Debt.colegiado_id      == fracc.colegiado_id,
                Debt.concepto_cobro_id == concepto_fracc.id,
                Debt.periodo           == periodo,
                Debt.fraccionamiento_id == fracc.id,
            ).first()

            if existe:
                omitidas += 1
                continue

            try:
                due_dt = datetime.combine(cuota.fecha_vencimiento,
                                          datetime.min.time()).replace(tzinfo=timezone.utc)
                debt = Debt(
                    organization_id    = organization_id,
                    colegiado_id       = fracc.colegiado_id,
                    member_id          = fracc.colegiado.member_id if fracc.colegiado else None,
                    concepto_cobro_id  = concepto_fracc.id,
                    concept            = f"Cuota {cuota.numero_cuota} Fraccionamiento {fracc.numero_solicitud}",
                    periodo            = periodo,
                    period_label       = f"Cuota {cuota.numero_cuota}/{fracc.num_cuotas}",
                    debt_type          = "cuota_ordinaria",  # se cobra como cuota
                    amount             = float(cuota.monto),
                    balance            = float(cuota.monto),
                    status             = "pending",
                    estado_gestion     = "vigente",
                    fecha_generacion   = hoy,
                    due_date           = due_dt,
                    fraccionamiento_id = fracc.id,
                    origen             = "generacion_auto",
                    lote_migracion     = lote_id,
                    created_by         = created_by,
                    notes              = f"Cuota fraccionamiento {fracc.numero_solicitud}",
                )
                db.add(debt)
                db.flush()
                generadas += 1
            except IntegrityError:
                db.rollback()
                omitidas += 1
            except Exception as e:
                db.rollback()
                errores += 1
                logger.error(f"[GenFracc] Error {fracc.numero_solicitud} cuota {cuota.numero_cuota}: {e}")

    db.commit()
    logger.info(f"[GenFracc] {hoy} → generadas={generadas} omitidas={omitidas} errores={errores}")

    return {
        "lote_id":   lote_id,
        "fecha":     hoy.isoformat(),
        "generadas": generadas,
        "omitidas":  omitidas,
        "errores":   errores,
        "alertas":   alertas,  # fraccionamientos en riesgo
    }


def _contar_consecutivas_vencidas(cuotas, hoy: date) -> int:
    """Cuenta cuotas consecutivas vencidas desde la más reciente hacia atrás."""
    vencidas_no_pagadas = sorted(
        [c for c in cuotas if not c.pagada and c.fecha_vencimiento < hoy],
        key=lambda c: c.numero_cuota,
        reverse=True,
    )
    if not vencidas_no_pagadas:
        return 0

    consecutivas = 0
    ultimo = None
    for cuota in vencidas_no_pagadas:
        if ultimo is None or cuota.numero_cuota == ultimo - 1:
            consecutivas += 1
            ultimo = cuota.numero_cuota
        else:
            break
    return consecutivas


# ═══════════════════════════════════════════════════════════════
# 3. RESUMEN PARA CAJA / DASHBOARD FINANZAS
# ═══════════════════════════════════════════════════════════════

def resumen_fraccionamientos(db: Session, organization_id: int) -> dict:
    """
    Devuelve resumen de fraccionamientos activos para panel de Caja.
    """
    from app.models_debt_management import Fraccionamiento

    hoy = date.today()

    fraccionamientos = db.query(Fraccionamiento).filter(
        Fraccionamiento.organization_id == organization_id,
        Fraccionamiento.estado          == 'activo',
    ).all()

    en_riesgo   = []
    al_dia      = []
    total_cuotas_vencidas = 0
    total_monto_vencido   = 0.0

    for fracc in fraccionamientos:
        cuotas_vencidas = [
            c for c in fracc.cuotas
            if not c.pagada and c.fecha_vencimiento < hoy
        ]
        consecutivas = _contar_consecutivas_vencidas(fracc.cuotas, hoy)
        monto_vencido = sum(float(c.monto) for c in cuotas_vencidas)

        total_cuotas_vencidas += len(cuotas_vencidas)
        total_monto_vencido   += monto_vencido

        item = {
            "numero_solicitud":  fracc.numero_solicitud,
            "colegiado":         fracc.colegiado.codigo_matricula if fracc.colegiado else "?",
            "nombre":            fracc.colegiado.apellidos_nombres if fracc.colegiado else "?",
            "cuotas_vencidas":   len(cuotas_vencidas),
            "monto_vencido":     monto_vencido,
            "consecutivas":      consecutivas,
        }

        if consecutivas >= 2:
            en_riesgo.append(item)
        elif cuotas_vencidas:
            en_riesgo.append(item)  # cualquier vencida es riesgo
        else:
            al_dia.append(item)

    return {
        "total_activos":          len(fraccionamientos),
        "en_riesgo":              len(en_riesgo),
        "al_dia":                 len(al_dia),
        "total_cuotas_vencidas":  total_cuotas_vencidas,
        "total_monto_vencido":    total_monto_vencido,
        "detalle_riesgo":         en_riesgo,
        "fecha":                  hoy.isoformat(),
    }
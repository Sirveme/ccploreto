"""
Router: Admin del Portal de Colegiados
app/routers/portal_admin.py

Endpoints:
  POST /api/portal/admin/generar-cuotas-ordinarias
  GET  /api/portal/admin/pagos-pendientes
  POST /api/portal/admin/pagos/{id}/aprobar
  POST /api/portal/admin/pagos/{id}/rechazar
  GET  /api/portal/mis-reportes
"""

import calendar
import json
import logging
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, Form
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Colegiado, Member, Payment, Comprobante, ConceptoCobro, NotificacionBancaria
from app.models_debt_management import Debt
from app.routers.dashboard import get_current_member

# _get_colegiado definido en portal_colegiado.py — importar para reusar
from app.routers.portal_colegiado import _get_colegiado

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/portal", tags=["portal-admin"])

# ── Helper: qué meses del año Y cubre un periodo ──────────────────────────────
def _meses_cubiertos(periodo: str, anio: int) -> set[int]:
    """
    Retorna set de meses (1-12) que cubre el periodo dado para el año anio.

    Ejemplos:
      "2026"       → {1,2,...,12}
      "2026-03"    → {3}
      "2026-01:02" → {1, 2}
      "2025-11:12" → {} (año diferente)
      "2025"       → {} (año diferente)
    """
    if not periodo:
        return set()

    # Periodo de año completo: "2026"
    if periodo == str(anio):
        return set(range(1, 13))

    # No es del año que buscamos
    if not periodo.startswith(f"{anio}-"):
        return set()

    # Quitar el prefijo del año
    resto = periodo[len(f"{anio}-"):]

    # Rango: "01:02" → meses 1 al 2
    if ":" in resto:
        partes = resto.split(":")
        try:
            m_ini = int(partes[0])
            m_fin = int(partes[1])
            return set(range(m_ini, m_fin + 1))
        except (ValueError, IndexError):
            return set()

    # Mes simple: "03" → {3}
    try:
        return {int(resto)}
    except ValueError:
        return set()


# ── Helper: construir periodo y labels para un mes ────────────────────────────
def _periodo_mes(anio: int, mes: int) -> tuple[str, str, str]:
    """
    Retorna (periodo, period_label, concept) para un mes dado.

    Ejemplo: (2026, 3) → ("2026-03", "Marzo 2026", "Cuota Ordinaria Marzo 2026")
    """
    MESES_ES = [
        "", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
        "Julio", "Agosto", "Setiembre", "Octubre", "Noviembre", "Diciembre"
    ]
    nombre_mes   = MESES_ES[mes]
    periodo      = f"{anio}-{mes:02d}"
    period_label = f"{nombre_mes} {anio}"
    concept      = f"Cuota Ordinaria {nombre_mes} {anio}"
    return periodo, period_label, concept


# ── Endpoint admin ─────────────────────────────────────────────────────────────
@router.post("/admin/generar-cuotas-ordinarias")
async def generar_cuotas_ordinarias(
    anio:     int     = None,     # default: año actual
    mes_hasta: int    = None,     # default: mes actual
    org_id:   int     = None,     # default: org del admin
    dry_run:  bool    = False,    # True = solo simula, no inserta
    member:   Member  = Depends(get_current_member),
    db:       Session = Depends(get_db),
):
    """
    Genera cuotas ordinarias mensuales faltantes para colegiados inhábiles.

    Parámetros:
    - anio:      Año a procesar (default: año actual)
    - mes_hasta: Hasta qué mes generar (default: mes actual)
    - org_id:    Organización (default: la del admin)
    - dry_run:   Si True, solo reporta qué generaría sin insertar
    """
    if member.role not in ("admin", "superadmin"):
        return JSONResponse({"error": "Solo administradores"}, status_code=403)

    hoy        = date.today()
    anio       = anio       or hoy.year
    mes_hasta  = mes_hasta  or hoy.month
    org_id     = org_id     or member.organization_id

    if not (1 <= mes_hasta <= 12):
        return JSONResponse({"error": "mes_hasta debe estar entre 1 y 12"}, status_code=400)

    # Monto de la cuota ordinaria
    concepto_ord = db.query(ConceptoCobro).filter(
        ConceptoCobro.organization_id == org_id,
        ConceptoCobro.codigo          == "CUOT-ORD",
        ConceptoCobro.activo          == True,
    ).first()

    if not concepto_ord:
        return JSONResponse(
            {"error": "No se encontró el concepto CUOT-ORD en conceptos_cobro"},
            status_code=404
        )

    monto_mes = float(concepto_ord.monto_base or 20.0)

    # Colegiados inhábiles activos de la organización
    colegiados = db.query(Colegiado).filter(
        Colegiado.organization_id == org_id,
        Colegiado.condicion.in_(["inhabil", "retirado"]),
    ).all()

    generados   = []
    omitidos    = 0
    meses_range = list(range(1, mes_hasta + 1))

    for col in colegiados:
        # Deudas de cuota_ordinaria que ya tiene este colegiado en el año
        deudas_anio = db.query(Debt).filter(
            Debt.colegiado_id == col.id,
            Debt.debt_type    == "cuota_ordinaria",
            Debt.periodo.like(f"{anio}%"),
        ).all()

        # Calcular qué meses ya están cubiertos
        meses_cubiertos: set[int] = set()
        for d in deudas_anio:
            meses_cubiertos.update(_meses_cubiertos(d.periodo or "", anio))

        # Generar los meses faltantes
        for mes in meses_range:
            if mes in meses_cubiertos:
                omitidos += 1
                continue

            periodo, period_label, concept = _periodo_mes(anio, mes)

            # Fecha de vencimiento: día 15 del mes
            ultimo_dia = calendar.monthrange(anio, mes)[1]
            due_date   = date(anio, mes, min(15, ultimo_dia))

            if not dry_run:
                nueva_deuda = Debt(
                    organization_id = org_id,
                    colegiado_id    = col.id,
                    concept         = concept,
                    period_label    = period_label,
                    periodo         = periodo,
                    debt_type       = "cuota_ordinaria",
                    amount          = monto_mes,
                    balance         = monto_mes,
                    status          = "pending",
                    estado_gestion  = "vigente",
                    due_date        = due_date,
                    es_exigible     = (due_date <= hoy),
                    dias_mora       = max(0, (hoy - due_date).days) if due_date < hoy else 0,
                )
                db.add(nueva_deuda)

            generados.append({
                "colegiado_id": col.id,
                "matricula":    col.codigo_matricula,
                "periodo":      periodo,
                "monto":        monto_mes,
            })

    if not dry_run and generados:
        db.commit()

    return JSONResponse({
        "ok":           True,
        "dry_run":      dry_run,
        "anio":         anio,
        "mes_hasta":    mes_hasta,
        "generados":    len(generados),
        "omitidos":     omitidos,
        "monto_mes":    monto_mes,
        "detalle":      generados if dry_run else [],
        "mensaje":      (
            f"{'[DRY RUN] ' if dry_run else ''}"
            f"Se {'generarían' if dry_run else 'generaron'} "
            f"{len(generados)} cuotas ordinarias de S/ {monto_mes} "
            f"para {anio} (meses 1-{mes_hasta})."
        ),
    })



# ══════════════════════════════════════════════════════════════════════════════
# PEGAR AL FINAL DE app/routers/portal_colegiado.py
#
# Endpoints:
#   GET  /api/portal/mis-reportes          → colegiado: sus propios reportes
#   GET  /api/portal/admin/pagos-pendientes → caja/admin/finanzas/decano
#   POST /api/portal/admin/pagos/{id}/aprobar
#   POST /api/portal/admin/pagos/{id}/rechazar
#
# No requiere imports adicionales — usa los ya existentes en portal_colegiado.py
# ══════════════════════════════════════════════════════════════════════════════


# ── Vista del colegiado: sus propios reportes ──────────────────────────────────
@router.get("/mis-reportes")
async def mis_reportes(
    member: Member  = Depends(get_current_member),
    db:     Session = Depends(get_db),
):
    """
    El colegiado consulta sus propios reportes de pago.
    Muestra estado, monto, método, fecha y si hay comprobante disponible.
    """
    colegiado = _get_colegiado(member, db)

    pagos = db.query(Payment).filter(
        Payment.colegiado_id    == colegiado.id,
        Payment.organization_id == member.organization_id,
    ).order_by(Payment.created_at.desc()).limit(50).all()

    resultado = []
    for p in pagos:
        # Buscar comprobante vinculado
        comp = db.query(Comprobante).filter(
            Comprobante.payment_id == p.id
        ).first() if _tiene_comprobante_model(db) else None

        # Parsear notas
        notas = {}
        try:
            if p.notes and p.notes.strip().startswith("{"):
                import json as _j
                notas = _j.loads(p.notes)
        except Exception:
            pass

        resultado.append({
            "id":              p.id,
            "monto":           float(p.amount or 0),
            "metodo":          p.payment_method,
            "nro_operacion":   p.operation_code,
            "estado":          p.status,
            "fecha":           p.created_at.isoformat() if p.created_at else None,
            "voucher_url":     p.voucher_url,
            "tipo_comprobante": notas.get("tipo_comprobante"),
            "comprobante": {
                "numero":  f"{comp.serie}-{str(comp.numero).zfill(8)}" if comp else None,
                "pdf_url": comp.pdf_url if comp else None,
                "estado":  comp.status  if comp else None,
            } if comp else None,
            # Mensaje de estado legible para el colegiado
            "estado_label": _estado_label(p.status),
        })

    return JSONResponse({
        "ok":    True,
        "total": len(resultado),
        "pagos": resultado,
    })


# ── Vista admin/caja: todos los pagos pendientes ───────────────────────────────
@router.get("/admin/pagos-pendientes")
async def pagos_pendientes_admin(
    estado:   str = "review",   # review | approved | rejected | all
    limite:   int = 50,
    offset:   int = 0,
    member:   Member  = Depends(get_current_member),
    db:       Session = Depends(get_db),
):
    """
    Lista pagos para revisión. Acceso según rol:
    - caja / admin / finanzas: ven todos con detalle completo
    - decano: solo resumen ejecutivo (totales)
    """
    ROL = (member.role or "").lower()
    if ROL not in ("admin", "caja", "finanzas", "decano", "superadmin"):
        return JSONResponse({"error": "Sin permisos"}, status_code=403)

    # ── Resumen ejecutivo para Decano ──────────────────────────────────────────
    if ROL == "decano":
        return await _resumen_decano(member.organization_id, db)

    # ── Lista completa para caja/admin/finanzas ────────────────────────────────
    q = db.query(Payment).filter(
        Payment.organization_id == member.organization_id,
    )

    if estado != "all":
        q = q.filter(Payment.status == estado)

    total_count = q.count()
    pagos = q.order_by(Payment.created_at.desc()).offset(offset).limit(limite).all()

    resultado = []
    for p in pagos:
        # Datos del colegiado
        col = db.query(Colegiado).filter(
            Colegiado.id == p.colegiado_id
        ).first() if p.colegiado_id else None

        # Comprobante
        comp = db.query(Comprobante).filter(
            Comprobante.payment_id == p.id
        ).first() if _tiene_comprobante_model(db) else None

        # Notificación bancaria vinculada (matching)
        from app.models import NotificacionBancaria
        notif = db.query(NotificacionBancaria).filter(
            NotificacionBancaria.payment_id == p.id
        ).first() if p.id else None

        # Parsear notas
        notas = {}
        try:
            if p.notes and p.notes.strip().startswith("{"):
                import json as _j
                notas = _j.loads(p.notes)
        except Exception:
            pass

        resultado.append({
            "id":            p.id,
            "monto":         float(p.amount or 0),
            "metodo":        p.payment_method,
            "nro_operacion": p.operation_code,
            "estado":        p.status,
            "estado_label":  _estado_label(p.status),
            "fecha":         p.created_at.isoformat() if p.created_at else None,
            "voucher_url":   p.voucher_url,

            # Datos del colegiado
            "colegiado": {
                "id":        col.id              if col else None,
                "nombre":    col.apellidos_nombres if col else "—",
                "matricula": col.codigo_matricula  if col else "—",
                "dni":       col.dni               if col else "—",
                "condicion": col.condicion         if col else "—",
            } if col else None,

            # Comprobante
            "comprobante": {
                "numero":  f"{comp.serie}-{str(comp.numero).zfill(8)}" if comp else None,
                "tipo":    "Factura" if comp and comp.tipo == "01" else "Boleta" if comp else None,
                "pdf_url": comp.pdf_url if comp else None,
                "estado":  comp.status  if comp else None,
            } if comp else None,

            # Matching bancario
            "matching": {
                "notificacion_id": notif.id            if notif else None,
                "banco":           notif.banco          if notif else None,
                "cod_operacion":   notif.codigo_operacion if notif else None,
                "conciliado_por":  notif.conciliado_por if notif else None,
                "conciliado_at":   notif.conciliado_at.isoformat() if notif and notif.conciliado_at else None,
            } if notif else None,

            # Info para facturación manual (si aún no tiene comprobante)
            "solicita_comprobante": notas.get("tipo_comprobante"),
            "factura_ruc":          notas.get("factura_ruc"),
            "factura_razon_social": notas.get("factura_razon_social"),

            # Flags de acción
            "puede_aprobar":   p.status == "review",
            "puede_rechazar":  p.status == "review",
            "puede_emitir_comprobante": (
                p.status == "approved" and
                comp is None and
                notas.get("tipo_comprobante") in ("boleta", "factura")
            ),
        })

    return JSONResponse({
        "ok":     True,
        "total":  total_count,
        "offset": offset,
        "limite": limite,
        "pagos":  resultado,
    })


# ── Aprobar pago (caja/admin) ──────────────────────────────────────────────────
@router.post("/admin/pagos/{payment_id}/aprobar")
async def aprobar_pago(
    payment_id: int,
    member:     Member  = Depends(get_current_member),
    db:         Session = Depends(get_db),
):
    ROL = (member.role or "").lower()
    if ROL not in ("admin", "caja", "finanzas", "superadmin"):
        return JSONResponse({"error": "Sin permisos"}, status_code=403)

    payment = db.query(Payment).filter(
        Payment.id              == payment_id,
        Payment.organization_id == member.organization_id,
    ).first()

    if not payment:
        return JSONResponse({"error": "Pago no encontrado"}, status_code=404)
    if payment.status != "review":
        return JSONResponse({"error": f"El pago ya está en estado '{payment.status}'"}, status_code=400)

    # Aprobar
    payment.status      = "approved"
    payment.reviewed_by = member.id
    payment.reviewed_at = datetime.utcnow()
    db.flush()

    # Imputar deudas (FIFO)
    _imputar_deudas(payment, db)

    # Emitir comprobante si lo solicitó
    comprobante_info = await _emitir_comprobante_si_corresponde(payment, db)

    db.commit()

    return JSONResponse({
        "ok":          True,
        "payment_id":  payment_id,
        "estado":      payment.status,
        "comprobante": {
            "emitido":  comprobante_info.get("success", False) if comprobante_info else False,
            "numero":   comprobante_info.get("numero_formato") if comprobante_info else None,
            "pdf_url":  comprobante_info.get("pdf_url")        if comprobante_info else None,
        },
    })


# ── Rechazar pago (caja/admin) ─────────────────────────────────────────────────
@router.post("/admin/pagos/{payment_id}/rechazar")
async def rechazar_pago(
    payment_id: int,
    motivo:     str     = Form(...),
    member:     Member  = Depends(get_current_member),
    db:         Session = Depends(get_db),
):
    ROL = (member.role or "").lower()
    if ROL not in ("admin", "caja", "finanzas", "superadmin"):
        return JSONResponse({"error": "Sin permisos"}, status_code=403)

    payment = db.query(Payment).filter(
        Payment.id              == payment_id,
        Payment.organization_id == member.organization_id,
    ).first()

    if not payment:
        return JSONResponse({"error": "Pago no encontrado"}, status_code=404)
    if payment.status != "review":
        return JSONResponse({"error": f"El pago ya está en estado '{payment.status}'"}, status_code=400)

    payment.status           = "rejected"
    payment.rejection_reason = motivo
    payment.reviewed_by      = member.id
    payment.reviewed_at      = datetime.utcnow()
    db.commit()

    return JSONResponse({
        "ok":         True,
        "payment_id": payment_id,
        "estado":     payment.status,
    })


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS PRIVADOS
# ══════════════════════════════════════════════════════════════════════════════

def _estado_label(status: str) -> str:
    return {
        "review":    "⏳ Pendiente de validación",
        "approved":  "✅ Aprobado",
        "rejected":  "❌ Rechazado",
        "pagado":    "✅ Pagado (OpenPay)",
        "completado":"✅ Completado",
    }.get(status or "", status or "—")


def _tiene_comprobante_model(db: Session) -> bool:
    """Verifica que el modelo Comprobante esté disponible."""
    try:
        from app.models import Comprobante as _C
        return True
    except ImportError:
        return False


def _imputar_deudas(payment: Payment, db: Session):
    """Imputa el pago a deudas pendientes del colegiado (FIFO por fecha)."""
    if not payment.colegiado_id:
        return
    deudas = db.query(Debt).filter(
        Debt.colegiado_id == payment.colegiado_id,
        Debt.status.in_(["pending", "partial"]),
    ).order_by(Debt.due_date.asc()).all()

    restante = float(payment.amount or 0)
    for d in deudas:
        if restante <= 0:
            break
        bal = float(d.balance or 0)
        if restante >= bal:
            restante -= bal
            d.balance = 0
            d.status  = "paid"
        else:
            d.balance = bal - restante
            d.status  = "partial"
            restante  = 0


async def _emitir_comprobante_si_corresponde(
    payment: Payment, db: Session
) -> Optional[dict]:
    """Emite comprobante si el pago lo solicita y aún no tiene uno."""
    import json as _j
    try:
        from app.models import Comprobante as _C
        existe = db.query(_C).filter(_C.payment_id == payment.id).first()
        if existe:
            return None

        notas = {}
        if payment.notes and payment.notes.strip().startswith("{"):
            notas = _j.loads(payment.notes)

        tipo_comp = notas.get("tipo_comprobante")
        if tipo_comp not in ("boleta", "factura"):
            return None

        from app.services.facturacion import FacturacionService
        svc = FacturacionService(db, payment.organization_id)
        if not svc.esta_configurado():
            return None

        tipo_doc     = "01" if tipo_comp == "factura" else "03"
        forzar_datos = None
        if tipo_comp == "factura" and notas.get("factura_ruc"):
            forzar_datos = {
                "tipo_doc":  "6",
                "num_doc":   notas["factura_ruc"],
                "nombre":    notas.get("factura_razon_social") or "CLIENTE",
                "direccion": notas.get("factura_direccion") or "",
                "email":     None,
            }

        return await svc.emitir_comprobante_por_pago(
            payment.id,
            tipo                 = tipo_doc,
            forzar_datos_cliente = forzar_datos,
        )
    except Exception as e:
        logger.error(f"[_emitir_comprobante_si_corresponde] {e}", exc_info=True)
        return None


async def _resumen_decano(org_id: int, db: Session) -> JSONResponse:
    """Vista ejecutiva para el Decano — solo totales."""
    from sqlalchemy import func as sa_func
    stats = db.query(
        Payment.status,
        sa_func.count(Payment.id).label("cantidad"),
        sa_func.sum(Payment.amount).label("total"),
    ).filter(
        Payment.organization_id == org_id,
    ).group_by(Payment.status).all()

    resumen = {
        row.status: {
            "cantidad": row.cantidad,
            "total":    float(row.total or 0),
        }
        for row in stats
    }

    return JSONResponse({
        "ok":     True,
        "rol":    "decano",
        "resumen": resumen,
        "pendiente_validacion": resumen.get("review", {}).get("cantidad", 0),
        "monto_pendiente":      resumen.get("review", {}).get("total", 0),
        "aprobados_hoy":        0,  # TODO: filtrar por fecha
    })
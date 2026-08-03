"""
app/services/anulacion_service.py
Flujo de dos pasos de anulación (cajera solicita / admin emite) + historial NC.

⚠️ DUPLICACIÓN CONTROLADA (decisión institucional):
`ejecutar_anulacion` contiene la MISMA orquestación fiscal que `caja.py::anular_cobro`
(emitir NC → marcar anulado → restaurar deudas → revertir stock). Se decidió NO
refactorizar `anular_cobro` (código probado con el caso Bingazo, cero riesgo). Por
tanto AMBOS caminos deben mantenerse EN PARALELO: si cambias la orquestación aquí,
replícala en `anular_cobro`, y viceversa. NUNCA se toca `emitir_nota_credito`.
"""

import logging
from datetime import datetime, timezone, date

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════
# ORQUESTACIÓN (espejo de caja.py::anular_cobro, líneas ~2272-2426)
# ════════════════════════════════════════════════════════════════
async def ejecutar_anulacion(db: Session, payment, motivo_codigo: str, motivo_texto: str,
                             monto_anular: float, es_parcial: bool, actor,
                             observaciones: str = "") -> dict:
    """Emite la NC y revierte deudas/stock para un pago ya validado a nivel permisos.

    ESPEJO de anular_cobro (mantener en paralelo). NO reimplementa emitir_nota_credito.
    Devuelve el mismo shape de dict que anular_cobro.
    """
    from app.services.facturacion import FacturacionService
    from app.services.comprobante_anulacion_service import restaurar_deudas_por_anulacion
    from app.models import Comprobante, ConceptoCobro
    from app.models_debt_management import Debt

    # ── Emitir Nota de Crédito si hay comprobante ──
    nota_credito_info = None
    nc_pdf_url = None
    comp = db.query(Comprobante).filter(
        Comprobante.payment_id == payment.id,
        Comprobante.status == "accepted",
        Comprobante.tipo.in_(["01", "03"]),  # Solo boletas/facturas, no NC sobre NC
    ).first()

    if comp:
        try:
            facturacion = FacturacionService(db, payment.organization_id)
            if facturacion.esta_configurado():
                resultado_nc = await facturacion.emitir_nota_credito(
                    comprobante_original_id=comp.id,
                    motivo_codigo=motivo_codigo,
                    motivo_texto=motivo_texto,
                    monto=monto_anular,
                )
                if resultado_nc["success"]:
                    nota_credito_info = resultado_nc["numero_formato"]
                    nc_pdf_url = resultado_nc.get("pdf_url")
                    logger.info(f"NC emitida: {nota_credito_info} para pago #{payment.id}")
                else:
                    logger.error(f"NC falló para pago #{payment.id}: {resultado_nc.get('error')}")
                    nota_credito_info = f"Error NC: {resultado_nc.get('error', 'desconocido')}"
            else:
                nota_credito_info = "Facturación no configurada, comprobante anulado solo localmente"
            comp.status = "anulado"
            comp.observaciones = (comp.observaciones or "") + f"\n[ANULADO] {motivo_texto}"
        except Exception as e:
            logger.error(f"Error emitiendo NC para pago #{payment.id}: {e}", exc_info=True)
            nota_credito_info = f"Error NC: {str(e)}"

    # ── Revertir deudas ──
    deudas_revertidas = 0
    deudas_restauradas_ids: list = []
    deudas_omitidas_ids: list = []
    mensajes_restauracion: list = []
    if payment.colegiado_id:
        if es_parcial:
            notas = payment.notes or ""
            deudas = db.query(Debt).filter(
                Debt.colegiado_id == payment.colegiado_id,
                Debt.status == "paid",
            ).order_by(Debt.periodo.desc()).all()
            monto_pendiente = monto_anular
            for deuda in deudas:
                if monto_pendiente <= 0:
                    break
                if deuda.concept and deuda.concept in notas:
                    deuda.status = "pending"
                    deuda.balance = deuda.amount
                    monto_pendiente -= float(deuda.amount)
                    deudas_revertidas += 1
        else:
            comp_sn = (f"{comp.serie}-{comp.numero}" if comp else f"PAY-{payment.id}")
            (deudas_restauradas_ids, deudas_omitidas_ids, mensajes_restauracion) = \
                restaurar_deudas_por_anulacion(
                    db=db, payment_id=payment.id, user_id=actor.id,
                    comprobante_serie_numero=comp_sn,
                )
            deudas_revertidas = len(deudas_restauradas_ids)
            if mensajes_restauracion:
                logger.info("Anulación pago=%s comp=%s: restauradas=%s, omitidas=%s",
                            payment.id, comp_sn, deudas_restauradas_ids, deudas_omitidas_ids)
            if comp is not None:
                comp.observaciones = (comp.observaciones or "") + (
                    f"\n[RESTAURACIÓN-AUTO] {len(deudas_restauradas_ids)} deuda(s) restaurada(s), "
                    f"{len(deudas_omitidas_ids)} omitida(s).")

    # ── Revertir stock ──
    if not es_parcial:
        try:
            for item_note in (payment.notes or "").split(";"):
                item_note = item_note.strip()
                if not item_note:
                    continue
                concepto = db.query(ConceptoCobro).filter(
                    ConceptoCobro.nombre.ilike(f"%{item_note[:30]}%"),
                    ConceptoCobro.maneja_stock == True,
                ).first()
                if concepto:
                    concepto.stock_actual += 1
        except Exception:
            pass

    # ── Marcar anulado (solo si NC fue exitosa o no había comprobante) ──
    nc_exitosa = nota_credito_info and "Error" not in str(nota_credito_info)
    sin_comprobante = comp is None
    if nc_exitosa or sin_comprobante:
        motivo_full = motivo_texto
        if observaciones:
            motivo_full += f". {observaciones}"
        if nc_exitosa:
            motivo_full += f" [NC: {nota_credito_info}]"
        if es_parcial:
            payment.notes = (payment.notes or "") + f"\n[NC PARCIAL S/{monto_anular:.2f}] {motivo_full}"
        else:
            payment.status = "anulado"
            payment.notes = (payment.notes or "") + f"\n[ANULADO] {motivo_full}"
        db.commit()
        return {
            "success": True,
            "mensaje": f"{'Anulación parcial' if es_parcial else 'Cobro anulado'}. {deudas_revertidas} deuda(s) revertida(s).",
            "nota_credito": nota_credito_info,
            "nc_pdf_url": nc_pdf_url,
            "monto_anulado": monto_anular,
            "es_parcial": es_parcial,
            "deudas_restauradas": deudas_restauradas_ids,
            "deudas_omitidas": deudas_omitidas_ids,
        }
    else:
        db.rollback()
        return {"success": False,
                "detail": f"No se pudo emitir la Nota de Crédito: {nota_credito_info}"}


# ════════════════════════════════════════════════════════════════
# HISTORIAL DE NC (reutilizable: /admin/anulaciones y /decano, solo lectura)
# ════════════════════════════════════════════════════════════════
def _to_date(v):
    """'YYYY-MM-DD' (o date/datetime) → date; None si no se puede parsear (no rompe)."""
    if v is None or v == "":
        return None
    if isinstance(v, date):
        return v
    try:
        return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


MOTIVOS_09 = {
    "01": "Anulación de la operación", "02": "Anulación por error en RUC",
    "03": "Corrección por error en descripción", "04": "Descuento global",
    "05": "Descuento por ítem", "06": "Devolución total", "07": "Devolución parcial",
}


def _motivo_desde_obs(obs):
    """Extrae el motivo limpio de comprobantes.observaciones ('NC por: {motivo}...').

    Fuente UNIVERSAL del motivo: aplica a TODA NC (histórica o nueva), no solo a las
    que pasan por solicitud_anulacion. Quita el prefijo 'NC por: ' y toma esa línea.
    """
    if not obs:
        return None
    for line in str(obs).split("\n"):
        line = line.strip()
        if line.lower().startswith("nc por:"):
            m = line.split(":", 1)[1].strip()
            return m or None
    return None


def listar_historial_nc(db: Session, org_id: int, *, fecha_desde=None, fecha_hasta=None,
                        motivo=None, q_comprobante=None, q_colegiado=None, limit=200) -> list:
    """Todas las NC (tipo 07), totales y parciales. Una NC es una NC ante SUNAT.

    Todos los parámetros son named (:nombre) con bindparams de SQLAlchemy. Las fechas
    se parsean a date en Python y se castean con CAST(:x AS date) — se evita el estilo
    :x::date, que confunde al parser de text() (error 'syntax error at or near :').
    """
    where = ["nc.organization_id = :org", "nc.tipo = '07'"]
    params = {"org": org_id, "lim": limit}
    _fd = _to_date(fecha_desde)
    if _fd:
        where.append("nc.created_at >= CAST(:fd AS date)"); params["fd"] = _fd
    _fh = _to_date(fecha_hasta)
    if _fh:
        where.append("nc.created_at < (CAST(:fh AS date) + INTERVAL '1 day')"); params["fh"] = _fh
    if motivo:
        # El <select> envía el CÓDIGO (01..07). solicitud_anulacion guarda el código;
        # las NC antiguas guardan el TEXTO en observaciones ('NC por: {label}'). Se
        # matchea por cualquiera de las dos fuentes (observaciones es la universal).
        _lbl = MOTIVOS_09.get(motivo)
        where.append("(sa.motivo_sunat = :mot OR nc.observaciones ILIKE :mot_txt)")
        params["mot"] = motivo
        params["mot_txt"] = f"%{_lbl}%" if _lbl else f"%{motivo}%"
    if q_comprobante:
        where.append("(orig.serie || '-' || orig.numero ILIKE :qc OR nc.serie || '-' || nc.numero ILIKE :qc)")
        params["qc"] = f"%{q_comprobante}%"
    if q_colegiado:
        where.append("(c.dni ILIKE :qcol OR c.apellidos_nombres ILIKE :qcol)")
        params["qcol"] = f"%{q_colegiado}%"
    w = " AND ".join(where)
    filas = db.execute(text(f"""
        SELECT nc.id, nc.serie, nc.numero, nc.total, nc.status, nc.created_at, nc.observaciones,
               orig.serie AS orig_serie, orig.numero AS orig_numero, orig.tipo AS orig_tipo,
               c.apellidos_nombres, c.dni,
               sa.motivo_sunat, sa.motivo_interno, sa.solicitante_nombre
        FROM comprobantes nc
        LEFT JOIN comprobantes orig ON orig.id = nc.comprobante_ref_id
        LEFT JOIN payments p ON p.id = nc.payment_id
        LEFT JOIN colegiados c ON c.id = p.colegiado_id
        LEFT JOIN solicitud_anulacion sa ON sa.nc_comprobante_id = nc.id
        WHERE {w}
        ORDER BY nc.created_at DESC
        LIMIT :lim
    """), params).fetchall()
    _tn = {"01": "Factura", "03": "Boleta"}
    return [{
        "id": r.id,
        "nc": f"{r.serie}-{str(r.numero).zfill(8)}" if r.numero is not None else r.serie,
        "total": float(r.total or 0),
        "status": r.status,
        "fecha": r.created_at,
        "original": (f"{_tn.get(r.orig_tipo, r.orig_tipo)} {r.orig_serie}-{r.orig_numero}"
                     if r.orig_serie else "—"),
        "colegiado": r.apellidos_nombres or "—",
        "dni": r.dni or "—",
        "motivo_sunat": r.motivo_sunat,
        # Motivo limpio para mostrar: preferente el de la solicitud (código→label);
        # si no hay (NC directa/histórica), se parsea de observaciones. Universal.
        "motivo": ((MOTIVOS_09.get(r.motivo_sunat) if r.motivo_sunat else None)
                   or _motivo_desde_obs(r.observaciones) or "—"),
        "motivo_interno": r.motivo_interno,
        "solicitante": r.solicitante_nombre,
        "observaciones": r.observaciones,
    } for r in filas]


# ════════════════════════════════════════════════════════════════
# SOLICITUDES — crear / aprobar / rechazar (+ audit_log_finanzas)
# ════════════════════════════════════════════════════════════════
async def crear_solicitud(db: Session, *, org_id, comprobante_id, payment_id, colegiado_id,
                          monto, es_parcial, motivo_sunat, motivo_interno, solicitante,
                          request=None):
    from app.models import SolicitudAnulacion
    from app.models_audit_finanzas import log_audit_finanzas
    sol = SolicitudAnulacion(
        organization_id=org_id, comprobante_id=comprobante_id, payment_id=payment_id,
        colegiado_id=colegiado_id, monto=monto, es_parcial=bool(es_parcial),
        motivo_sunat=motivo_sunat, motivo_interno=motivo_interno,
        solicitante_member_id=getattr(solicitante, "id", None),
        solicitante_nombre=_nombre(solicitante), estado="pendiente",
    )
    db.add(sol)
    db.commit()
    await log_audit_finanzas(
        db, organization_id=org_id, accion="solicitud_anulacion_creada",
        entidad_tipo="solicitud_anulacion", entidad_id=sol.id, current_user=solicitante,
        motivo=motivo_interno or "", colegiado_id=colegiado_id, monto=float(monto or 0),
        cambios={"motivo_sunat": motivo_sunat, "comprobante_id": comprobante_id},
    )
    return sol


async def aprobar_solicitud(db: Session, sol, actor, motivo_texto: str):
    from app.models import Payment, Comprobante, SolicitudAnulacion
    from app.models_audit_finanzas import log_audit_finanzas
    payment = db.query(Payment).filter(Payment.id == sol.payment_id).first()
    if not payment:
        return {"success": False, "detail": "Pago de la solicitud no encontrado"}
    monto_anular = float(sol.monto) if sol.monto is not None else float(payment.amount)

    resultado = await ejecutar_anulacion(
        db, payment, sol.motivo_sunat, motivo_texto, monto_anular, bool(sol.es_parcial), actor,
    )
    if not resultado.get("success"):
        return resultado

    nc = db.query(Comprobante).filter(
        Comprobante.payment_id == payment.id, Comprobante.tipo == "07",
    ).order_by(Comprobante.created_at.desc()).first()
    sol.estado = "aprobada"
    sol.resuelto_por_member_id = getattr(actor, "id", None)
    sol.resuelto_por_nombre = _nombre(actor)
    sol.resuelto_at = datetime.now(timezone.utc)
    sol.nc_comprobante_id = nc.id if nc else None
    db.commit()
    await log_audit_finanzas(
        db, organization_id=sol.organization_id, accion="solicitud_anulacion_aprobada",
        entidad_tipo="solicitud_anulacion", entidad_id=sol.id, current_user=actor,
        motivo=motivo_texto, colegiado_id=sol.colegiado_id, monto=monto_anular,
        cambios={"nota_credito": resultado.get("nota_credito")},
    )
    return resultado


async def rechazar_solicitud(db: Session, sol, actor, nota: str = ""):
    from app.models_audit_finanzas import log_audit_finanzas
    sol.estado = "rechazada"
    sol.resuelto_por_member_id = getattr(actor, "id", None)
    sol.resuelto_por_nombre = _nombre(actor)
    sol.resuelto_at = datetime.now(timezone.utc)
    sol.nota_resolucion = nota
    db.commit()
    await log_audit_finanzas(
        db, organization_id=sol.organization_id, accion="solicitud_anulacion_rechazada",
        entidad_tipo="solicitud_anulacion", entidad_id=sol.id, current_user=actor,
        motivo=nota or "", colegiado_id=sol.colegiado_id,
    )
    return {"success": True}


def _nombre(member):
    """Nombre legible del actor (Member → user.name / role)."""
    try:
        if getattr(member, "user", None) and member.user.name:
            return member.user.name
    except Exception:
        pass
    return getattr(member, "role", None) or "—"

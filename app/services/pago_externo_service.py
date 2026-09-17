"""
app/services/pago_externo_service.py
Módulo Pagos Externos — WORKFLOW (ciclo calcado de anulacion_service).

Fase 1 sub-paso 2 (captura): crear_solicitud → INSERT solicitud_pago_externo
  estado='pendiente'. NO crea Payment, NO imputa: solo captura la intención.
Sub-pasos 3/4 (resolución) añadirán aprobar_solicitud / rechazar_solicitud.

⚠️ Requiere la tabla `solicitud_pago_externo` corrida en PGAdmin.
"""
from datetime import datetime, timezone, date

from sqlalchemy.orm import Session

from app.models import SolicitudPagoExterno
from app.models_audit_finanzas import log_audit_finanzas
from app.services import pagos_externos_service as pex

# Códigos del candado que son de CONCILIACIÓN (Fase 2): en la CAPTURA solo advierten
# (dejan enviar, opción 3-A); en la RESOLUCIÓN del admin bloquean la aprobación simple.
# El resto de códigos son 'malformados' y frenan en ambos pasos.
CANDADO_CONCILIACION = {"DUPLICADO_PAGO_SIS", "MONTO_EXCEDE_DEUDA", "DEUDA_SIN_SALDO"}


def clasificar_candado(analisis: dict):
    """Divide los bloqueos de analizar_pago_externo en (frena, advertencias)."""
    frena, advertencias = [], []
    for b in (analisis.get("bloqueos") or []):
        if b.get("codigo") in CANDADO_CONCILIACION:
            advertencias.append(b)
        else:
            frena.append(b)
    return frena, advertencias


def _nombre(member):
    """Nombre legible del actor (Member → user.name / role). Calcado de anulacion_service."""
    try:
        if getattr(member, "user", None) and member.user.name:
            return member.user.name
    except Exception:
        pass
    return getattr(member, "role", None) or "—"


def _to_date(s):
    """Normaliza 'YYYY-MM-DD' (o date) → date; None si vacío/ inválido."""
    if not s:
        return None
    if isinstance(s, date):
        return s
    try:
        return date.fromisoformat(str(s)[:10])
    except (ValueError, TypeError):
        return None


async def crear_solicitud(db: Session, *, payload: dict, analisis: dict, solicitante,
                          organization_id: int = 1) -> dict:
    """CAPTURA: crea una solicitud pendiente. NO crea Payment, NO imputa.

    - Malformados (monto≤0, deuda ajena, sin imputación, EB01 duplicado…) → FRENAN
      (devuelve ok=False; el endpoint responde 422).
    - Conciliación (PAGO_SIS/duplicado, monto>deuda) → ADVIERTEN, deja enviar (3-A);
      se guardan en candado_snapshot para que el admin las vea en la resolución.
    """
    frena, advertencias = clasificar_candado(analisis)
    if frena:
        return {"ok": False, "frena": frena, "advertencias": advertencias}

    tipo = int(payload.get("tipo"))
    cfg = pex.TIPOS_PAGO_EXTERNO.get(tipo, {})
    prev = analisis.get("preview") or {}
    # imputaciones RESUELTAS (debt_id + monto ya calculado por analizar)
    imputaciones = [{"debt_id": i["debt_id"], "monto": i["monto_a_imputar"]}
                    for i in prev.get("imputaciones", [])]

    sol = SolicitudPagoExterno(
        organization_id=organization_id,
        colegiado_id=payload.get("colegiado_id"),
        tipo=tipo,
        origen=cfg.get("origen"),
        serie=(payload.get("serie") or None),
        numero=payload.get("numero"),
        fecha_comprobante=_to_date(payload.get("fecha_comprobante")),
        monto=round(float(payload.get("monto") or 0), 2),
        metodo_pago=payload.get("metodo_pago"),
        nro_operacion=payload.get("nro_operacion"),
        fecha_pago=_to_date(payload.get("fecha_pago")),
        imputaciones=imputaciones,
        concepto=payload.get("concepto"),
        candado_snapshot={
            "advertencias": advertencias,
            "avisos": analisis.get("avisos", []),
            "capturado_at": datetime.now(timezone.utc).isoformat(),
        },
        solicitante_member_id=getattr(solicitante, "id", None),
        solicitante_nombre=_nombre(solicitante),
        estado="pendiente",
    )
    db.add(sol)
    db.flush()  # obtener sol.id sin cerrar la transacción

    await log_audit_finanzas(
        db, organization_id=organization_id,
        accion="solicitud_pago_externo_creada",
        entidad_tipo="solicitud_pago_externo", entidad_id=sol.id,
        current_user=solicitante, motivo=payload.get("concepto") or "",
        colegiado_id=payload.get("colegiado_id"),
        monto=float(payload.get("monto") or 0),
        cambios={
            "tipo": tipo, "origen": cfg.get("origen"),
            "serie_numero": (f"{payload.get('serie')}-{payload.get('numero')}"
                             if payload.get("serie") else None),
            "imputaciones": imputaciones,
            "advertencias": [a["codigo"] for a in advertencias],
        },
    )
    db.commit()
    return {
        "ok": True,
        "solicitud_id": sol.id,
        "estado": sol.estado,
        "advertencias": advertencias,
        "avisos": analisis.get("avisos", []),
    }


# ══════════════════════════════════════════════════════════════════════════════
# RESOLUCIÓN (sub-paso 3): recomputar preview EN VIVO + rechazar. (Aprobar = sub-paso 4.)
# ══════════════════════════════════════════════════════════════════════════════
def _payload_desde_solicitud(sol) -> dict:
    """Reconstruye el payload de analizar desde la fila guardada."""
    def _iso(d):
        return d.isoformat() if hasattr(d, "isoformat") else (d or None)
    return {
        "colegiado_id": sol.colegiado_id,
        "tipo": sol.tipo,
        "serie": sol.serie,
        "numero": sol.numero,
        "fecha_comprobante": _iso(sol.fecha_comprobante),
        "monto": float(sol.monto or 0),
        "metodo_pago": sol.metodo_pago,
        "nro_operacion": sol.nro_operacion,
        "fecha_pago": _iso(sol.fecha_pago),
        "concepto": sol.concepto,
        "imputaciones": list(sol.imputaciones or []),
    }


def recalcular_preview(db: Session, sol, organization_id: int = 1) -> dict:
    """Re-ejecuta analizar EN VIVO sobre la solicitud (NO usa candado_snapshot viejo:
    el estado pudo cambiar entre captura y resolución). Read-only."""
    payload = _payload_desde_solicitud(sol)
    analisis = pex.analizar_pago_externo(db, payload, organization_id)
    frena, advertencias = clasificar_candado(analisis)
    return {
        "analisis": analisis,
        "frena": frena,               # malformados actuales
        "advertencias": advertencias, # conciliación actuales (Fase 2)
        "puede_aprobar_simple": (len(frena) == 0 and len(advertencias) == 0),
    }


async def aprobar_solicitud(db: Session, sol, actor, organization_id: int = 1,
                            commit: bool = True) -> dict:
    """APRUEBA y EJECUTA (sub-paso 4). Re-ejecuta el candado EN VIVO:
      - si puede_aprobar_simple=False → BLOQUEA ("requiere conciliación Fase 2"), no crea nada.
      - si limpio → crea Payment(origen por tipo) + imputa (payment_debts + balance) +
        comprobante EB01 (tipo 1/3, status='externo_sunat') o emite B400 (tipo 2) +
        re-evalúa habilidad + marca solicitud aprobada + audit.

    commit=False → CENTINELA: arma todo (flush) y hace ROLLBACK (BD idéntica). En centinela
    NO se emite B400 (tipo 2) porque toca SUNAT (irreversible, no roll-back-able).
    """
    from decimal import Decimal
    from datetime import datetime as _dt, timedelta as _td
    from sqlalchemy import text as _text
    from app.models import Payment, Comprobante, Colegiado
    from app.models_debt_management import Debt

    _PERU = timezone(_td(hours=-5))

    def _fecha_real_a_dt(f):
        """Fecha real del pago → datetime a mediodía Perú (evita desfase de día).
        La convención del repo guarda la fecha real del pago en payments.created_at."""
        if not f:
            return None
        if isinstance(f, _dt):
            return f
        return _dt(f.year, f.month, f.day, 12, 0, tzinfo=_PERU)

    if sol.estado != "pendiente":
        return {"success": False, "detail": f"La solicitud ya está '{sol.estado}'"}

    # 1) CANDADO EN VIVO
    rec = recalcular_preview(db, sol, organization_id)
    if not rec["puede_aprobar_simple"]:
        return {"success": False, "bloqueado": True,
                "detail": "requiere conciliación (Fase 2)",
                "frena": rec["frena"], "advertencias": rec["advertencias"]}

    cfg = pex.TIPOS_PAGO_EXTERNO.get(sol.tipo, {})
    col = db.query(Colegiado).filter(Colegiado.id == sol.colegiado_id).first()
    if not col:
        return {"success": False, "detail": "Colegiado no encontrado"}

    imps = list(sol.imputaciones or [])
    ids = [int(i["debt_id"]) for i in imps]
    marcador = f"[DEBT_IDS:{','.join(str(x) for x in ids)}]" if ids else ""
    notes = ((sol.concepto or "Pago externo").strip() +
             f"\n[PAGO_EXTERNO tipo {sol.tipo} sol#{sol.id}] {marcador}").strip()
    ahora = _dt.now(timezone.utc)
    fecha_real = _fecha_real_a_dt(sol.fecha_pago)  # → created_at (fecha real del pago)

    # 2) PAYMENT (origen por tipo). created_at = fecha real del pago (convención repo).
    payment = Payment(
        organization_id=organization_id, colegiado_id=sol.colegiado_id,
        amount=Decimal(str(sol.monto or 0)), payment_method=sol.metodo_pago,
        operation_code=sol.nro_operacion, notes=notes, status="approved",
        origen=cfg.get("origen"), reviewed_at=ahora,
    )
    if fecha_real is not None:
        payment.created_at = fecha_real
    db.add(payment); db.flush()

    # 3) IMPUTAR: payment_debts (amount_applied) + reducir balance (patrón caja).
    detalle_imp = []
    for i in imps:
        deuda = db.query(Debt).filter(Debt.id == int(i["debt_id"])).first()
        if not deuda:
            continue
        aplicar = round(float(i.get("monto") or 0), 2)
        saldo_antes = float(deuda.balance or 0)
        nuevo = round(saldo_antes - aplicar, 2)
        deuda.balance = Decimal(str(max(nuevo, 0)))
        deuda.status = "paid" if nuevo <= 0.01 else "partial"
        db.execute(_text("""
            INSERT INTO payment_debts (payment_id, debt_id, amount_applied)
            VALUES (:pid, :did, :amt)
        """), {"pid": payment.id, "did": deuda.id, "amt": aplicar})
        detalle_imp.append({"debt_id": deuda.id, "concept": deuda.concept,
                            "saldo_antes": saldo_antes, "aplicado": aplicar,
                            "saldo_despues": max(nuevo, 0), "status": deuda.status})

    # 4) COMPROBANTE
    comprobante_id = None
    comp_info = None
    if sol.tipo in (1, 3):
        # REGISTRAR el EB01 externo (ya emitido en SUNAT-SOL): solo fila en comprobantes.
        _monto = Decimal(str(sol.monto or 0))
        comp = Comprobante(
            organization_id=organization_id, payment_id=payment.id, tipo="03",
            serie=sol.serie, numero=sol.numero, fecha_emision=sol.fecha_comprobante,
            subtotal=_monto, igv=Decimal("0"), total=_monto,  # boleta exonerada (colegio)
            moneda="PEN", cliente_tipo_doc="1",
            cliente_num_doc=col.dni, cliente_nombre=col.apellidos_nombres,
            status="externo_sunat",
            observaciones=f"Registro pago externo EB01 SUNAT-SOL (sol#{sol.id})",
        )
        db.add(comp); db.flush()
        db.execute(_text("UPDATE comprobantes SET origen = :o WHERE id = :id"),
                   {"o": cfg.get("origen"), "id": comp.id})
        comprobante_id = comp.id
        comp_info = {"serie": comp.serie, "numero": comp.numero, "tipo": "03",
                     "status": "externo_sunat", "origen": cfg.get("origen"),
                     "modo": "registrado (no se emite a SUNAT)"}
    elif sol.tipo == 2:
        if commit:
            # EMITIR B400 por el flujo protegido (real SUNAT vía Facturalo). Solo se INVOCA.
            from app.services.facturacion import FacturacionService
            service = FacturacionService(db, organization_id)
            resultado = await service.emitir_comprobante_por_pago(
                payment_id=payment.id, tipo="03", sede_id="1", forma_pago="contado")
            if resultado.get("success"):
                comp = db.query(Comprobante).filter(
                    Comprobante.payment_id == payment.id).first()
                if comp:
                    db.execute(_text("UPDATE comprobantes SET origen = :o WHERE id = :id"),
                               {"o": cfg.get("origen"), "id": comp.id})
                    comprobante_id = comp.id
                comp_info = {"modo": "emitido B400 vía Facturalo", **resultado}
            else:
                comp_info = {"modo": "FALLÓ emisión B400", **resultado}
        else:
            comp_info = {"modo": "CENTINELA: emisión B400 NO simulada (toca SUNAT)"}

    # 5) RE-EVALUAR HABILIDAD (motor protegido; solo se invoca)
    from app.services.evaluar_habilidad import sincronizar_condicion
    cond_antes = getattr(col, "condicion", None)
    cambio_hab = sincronizar_condicion(db, col, {})
    cond_despues = getattr(col, "condicion", None)

    # 6) marcar solicitud aprobada + enlaces
    sol.estado = "aprobada"
    sol.resuelto_por_member_id = getattr(actor, "id", None)
    sol.resuelto_por_nombre = _nombre(actor)
    sol.resuelto_at = ahora
    sol.payment_id = payment.id
    sol.comprobante_id = comprobante_id

    await log_audit_finanzas(
        db, organization_id=organization_id,
        accion="solicitud_pago_externo_aprobada",
        entidad_tipo="solicitud_pago_externo", entidad_id=sol.id,
        current_user=actor, motivo=sol.concepto or "", colegiado_id=sol.colegiado_id,
        monto=float(sol.monto or 0),
        cambios={"payment_id": payment.id, "comprobante_id": comprobante_id,
                 "origen": cfg.get("origen"), "imputaciones": detalle_imp,
                 "habilidad": {"antes": cond_antes, "despues": cond_despues, "cambio": cambio_hab}},
    )

    reporte = {
        "success": True,
        "dry_run": (not commit),
        "payment": {"id": payment.id, "origen": cfg.get("origen"),
                    "amount": float(sol.monto or 0), "payment_method": sol.metodo_pago,
                    "fecha_real_created_at": str(fecha_real) if fecha_real else None,
                    "notes": notes},
        "imputaciones": detalle_imp,
        "comprobante": comp_info, "comprobante_id": comprobante_id,
        "habilidad": {"antes": cond_antes, "despues": cond_despues, "cambio": cambio_hab},
        "solicitud": {"id": sol.id, "estado": sol.estado,
                      "payment_id": sol.payment_id, "comprobante_id": sol.comprobante_id},
    }

    if commit:
        db.commit()
    else:
        db.rollback()  # CENTINELA: BD idéntica
    return reporte


async def rechazar_solicitud(db: Session, sol, actor, nota: str = "") -> dict:
    """Marca la solicitud como rechazada. NO toca Payments. Calcado del ciclo NC."""
    sol.estado = "rechazada"
    sol.resuelto_por_member_id = getattr(actor, "id", None)
    sol.resuelto_por_nombre = _nombre(actor)
    sol.resuelto_at = datetime.now(timezone.utc)
    sol.nota_resolucion = nota or ""
    await log_audit_finanzas(
        db, organization_id=sol.organization_id,
        accion="solicitud_pago_externo_rechazada",
        entidad_tipo="solicitud_pago_externo", entidad_id=sol.id,
        current_user=actor, motivo=nota or "", colegiado_id=sol.colegiado_id,
        monto=float(sol.monto or 0),
    )
    db.commit()
    return {"success": True, "estado": sol.estado}

"""
app/services/fraccionamiento_refinanciar_service.py
Núcleo del REFINANCIAMIENTO de un fraccionamiento (tercera salida del ciclo,
independiente de Pérdida). Hoy manual por script (Zamora, casi Fiorella).

Orquesta REUSANDO los bloques existentes (no reinventa):
  - crear_fraccionamiento (crea el nuevo con cuotas + espejo + advertencia 20%)
  - pagar_cuota_fraccionamiento (registra el pago inicial externo, patrón Zamora)
  - sincronizar_condicion (paso B, CON guard habilitante — refinanciar solo mejora)
  - refrescar_flag_fraccionamiento

Diseño aprobado (Decano):
  • Deuda PUENTE = saldo del viejo UNA sola vez (anti-doble-conteo).
  • Orden: crear NUEVO primero (permitir_con_activo) → cerrar VIEJO después,
    todo en UNA transacción atómica (un fallo revierte todo).
  • Linaje consultable: fraccionamientos.refinanciado_por_id (nuevo → viejo).
  • ALCANCE: solo fraccionamientos SANOS (distinct_venc > 1). Los del batch
    (saldo sin conciliar) se RECHAZAN con mensaje claro.
  • hoy_peru() en los sellos del orquestador.

⚠️ Requiere sql/zClaude-refinanciado-por-id.sql en PGAdmin ANTES del deploy.
"""
from datetime import datetime, timezone, timedelta
import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

PERU_TZ = timezone(timedelta(hours=-5))


def _hoy_peru():
    """Fecha de HOY en zona Perú (UTC-5). Frente timezone: no date.today()."""
    return datetime.now(PERU_TZ).date()


class RefinanciarError(Exception):
    """Error de dominio del refinanciamiento. status_code/detail para que el
    endpoint lo mapee a HTTPException sin acoplar el core a FastAPI."""
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _es_sano(fracc) -> bool:
    """Marcador de salud: vencimientos escalonados (cronograma real). Igual que
    el detector de pérdida. Excluye el batch 'Importación masiva Excel — Sandra'."""
    distinct_venc = len({
        c.fecha_vencimiento for c in fracc.cuotas if c.fecha_vencimiento is not None
    })
    return distinct_venc > 1


def _planificar_refinanciamiento(
    db: Session,
    fracc_viejo_id: int,
    deudas_adicionales_ids,
    monto_inicial: float,
    num_cuotas: int,
) -> dict:
    """FASE READ-ONLY (sin escrituras, sin locks): valida y consolida. Devuelve el
    'plan'. Lanza RefinanciarError si algo no cuadra. El dry-run centinela llama a
    ESTA función directamente para verificar doble-conteo=0, 20% y el gate de sano.
    """
    from app.models_debt_management import Debt, Fraccionamiento
    from app.services.fraccionamiento_service import _resolver_parametros_fracc
    from app.services import parametros_service

    old = db.query(Fraccionamiento).filter(Fraccionamiento.id == fracc_viejo_id).first()
    if not old:
        raise RefinanciarError(404, "Fraccionamiento a refinanciar no encontrado")
    if old.estado != "activo":
        raise RefinanciarError(409, f"El fraccionamiento está '{old.estado}', no es refinanciable")

    # GATE de alcance: solo SANOS. Batch (dv<=1) → conciliación previa.
    if not _es_sano(old):
        raise RefinanciarError(
            409,
            f"El fraccionamiento #{old.numero_solicitud} no es sano (cronograma no "
            f"escalonado; probablemente del batch de migración). REQUIERE CONCILIACIÓN "
            f"PREVIA de su saldo antes de refinanciar."
        )

    colegiado = old.colegiado
    if colegiado is None:
        raise RefinanciarError(404, "Colegiado del fraccionamiento no encontrado")

    deuda_min, cuota_mensual_min, max_cuotas, cuota_inicial_pct = \
        _resolver_parametros_fracc(db, old.organization_id)

    if not (2 <= num_cuotas <= max_cuotas):
        raise RefinanciarError(400, f"El número de cuotas debe estar entre 2 y {max_cuotas}")

    # ── Consolidación (anti-doble-conteo) ──
    old_saldo = round(float(old.saldo_pendiente or 0), 2)

    adicionales = []
    ids = list(dict.fromkeys(deudas_adicionales_ids or []))
    if ids:
        adicionales = db.query(Debt).filter(
            Debt.id.in_(ids),
            Debt.colegiado_id == colegiado.id,
        ).all()
        encontradas = {d.id for d in adicionales}
        faltantes = set(ids) - encontradas
        if faltantes:
            raise RefinanciarError(400, f"Deudas adicionales no válidas: {sorted(faltantes)}")
        for d in adicionales:
            # guard anti-doble-conteo: no puede estar ya en un fracc ni resuelta
            if d.fraccionamiento_id is not None:
                raise RefinanciarError(400, f"Deuda {d.id} ya está en un fraccionamiento")
            if d.estado_gestion not in ("vigente", "en_cobranza"):
                raise RefinanciarError(400, f"Deuda {d.id} no está vigente ({d.estado_gestion})")
            if float(d.balance or 0) <= 0:
                raise RefinanciarError(400, f"Deuda {d.id} sin saldo")

    total_adicionales = round(sum(float(d.balance or 0) for d in adicionales), 2)
    total = round(old_saldo + total_adicionales, 2)  # ← saldo viejo UNA vez

    if total < deuda_min:
        raise RefinanciarError(400, f"El consolidado (S/ {total:.2f}) es menor al mínimo S/ {deuda_min:.2f}")
    if monto_inicial >= total:
        raise RefinanciarError(400, "La cuota inicial no puede cubrir toda la deuda; usa pago directo")

    # Factibilidad de la cuota mensual (evita que crear_fraccionamiento aborte a mitad)
    saldo = round(total - monto_inicial, 2)
    mensual = round(saldo / num_cuotas, 2)
    if mensual < cuota_mensual_min:
        raise RefinanciarError(
            400,
            f"La cuota mensual resultante (S/ {mensual:.2f}) es menor al mínimo "
            f"S/ {cuota_mensual_min:.2f}. Reduce cuotas o sube el inicial."
        )

    # Predicción de la regla 20%-no-bloquea (la ENFORCEA crear_fraccionamiento)
    minimo_inicial = round(total * cuota_inicial_pct, 2)
    inicial_bajo_min = monto_inicial < minimo_inicial - 0.009
    try:
        inicial_bloquea = bool(parametros_service.get_param(
            db, "fraccionamiento", "inicial_minima_bloquea", old.organization_id, default=False))
    except Exception:
        inicial_bloquea = False

    return {
        "fracc_viejo_id": old.id,
        "numero_solicitud_viejo": old.numero_solicitud,
        "colegiado_id": colegiado.id,
        "condicion_previa": colegiado.condicion,
        "old_saldo": old_saldo,
        "adicionales_ids": [d.id for d in adicionales],
        "total_adicionales": total_adicionales,
        "total_consolidado": total,
        "num_cuotas": num_cuotas,
        "monto_inicial": round(float(monto_inicial), 2),
        "saldo_a_fraccionar": saldo,
        "monto_mensual": mensual,
        "minimo_inicial_20": minimo_inicial,
        "inicial_bajo_min": inicial_bajo_min,
        "advertencia_20": inicial_bajo_min and not inicial_bloquea,
        "bloquearia_20": inicial_bajo_min and inicial_bloquea,
        # contrato de orden (para trazabilidad/dry-run)
        "orden": "crear_nuevo -> cerrar_viejo (una transacción atómica)",
    }


def _ejecutar_refinanciamiento(
    db: Session,
    plan: dict,
    user_id,
    monto_cuota_mensual=None,
    metodo_pago_inicial: str = "efectivo",
    operacion_inicial=None,
    reevaluar_habilidad: bool = True,
) -> dict:
    """FASE DE ESCRITURA. Una sola transacción (commit al final). El dry-run
    centinela parchea ESTA función para NO ejecutar escrituras."""
    from app.models import Payment, Colegiado
    from app.models_debt_management import Debt, Fraccionamiento
    from app.services.fraccionamiento_service import (
        crear_fraccionamiento, pagar_cuota_fraccionamiento,
    )
    from app.services.politicas_financieras import refrescar_flag_fraccionamiento

    hoy = _hoy_peru()
    ahora = datetime.now(PERU_TZ)

    # 1. Re-validar viejo BAJO LOCK (FOR UPDATE)
    old = db.execute(text("""
        SELECT id, colegiado_id, organization_id, numero_solicitud, estado, saldo_pendiente
        FROM fraccionamientos WHERE id = :fid FOR UPDATE
    """), {"fid": plan["fracc_viejo_id"]}).fetchone()
    if not old or old.estado != "activo":
        raise RefinanciarError(409, "El fraccionamiento cambió de estado; reintenta")

    colegiado = db.query(Colegiado).filter(Colegiado.id == plan["colegiado_id"]).first()

    # 2. Deuda PUENTE = saldo viejo UNA vez
    puente = Debt(
        organization_id=old.organization_id,
        colegiado_id=old.colegiado_id,
        concept=f"Saldo refinanciado de {old.numero_solicitud}",
        periodo=None,
        period_label=f"Refinanciamiento de {old.numero_solicitud}",
        debt_type="cuota_ordinaria",
        amount=plan["old_saldo"],
        balance=plan["old_saldo"],
        status="pending",
        estado_gestion="vigente",
        fecha_generacion=hoy,
        origen="refinanciamiento",
        notes=f"[REFINANCIAMIENTO] puente del fracc {old.numero_solicitud} (id {old.id}) — {ahora:%d/%m/%Y %H:%M}",
        created_by=user_id,
    )
    db.add(puente)
    db.flush()

    # 3. CREAR EL NUEVO primero (viejo aún activo → permitir_con_activo=True). commit=False.
    deuda_ids_nuevo = [puente.id] + list(plan["adicionales_ids"])
    resultado = crear_fraccionamiento(
        db=db,
        colegiado=colegiado,
        deuda_ids=deuda_ids_nuevo,
        n_cuotas=plan["num_cuotas"],
        monto_cuota_inicial=plan["monto_inicial"],
        monto_cuota_mensual=monto_cuota_mensual,
        created_by_user_id=user_id,
        nota_audit=f"[REFINANCIAMIENTO] desde {old.numero_solicitud}",
        aplicar_acuerdo_007=False,   # ya pasó por condonación en su origen
        commit=False,                # una sola transacción, commit al final
        permitir_con_activo=True,    # el viejo se cierra a continuación
    )
    nuevo = resultado.fraccionamiento

    # 4. Linaje: el nuevo VIENE del viejo (columna consultable, por SQL crudo —
    #    la columna NO está mapeada en el ORM a propósito; ver models_debt_management).
    db.execute(text(
        "UPDATE fraccionamientos SET refinanciado_por_id = :old WHERE id = :new"
    ), {"old": old.id, "new": nuevo.id})

    # 5. CERRAR EL VIEJO (después): cancelar sus cuotas espejo + estado refinanciado + saldo 0.
    cuotas_viejo = db.execute(text(
        "SELECT id FROM debts WHERE fraccionamiento_id = :fid"
    ), {"fid": old.id}).fetchall()
    for cd in cuotas_viejo:
        db.execute(text("""
            UPDATE debts SET balance = 0, status = 'cancelled', estado_gestion = 'anulada',
                   updated_at = NOW(),
                   notes = COALESCE(notes,'') || E'\\n[REFINANCIADO] cuota trasladada al nuevo plan'
            WHERE id = :did
        """), {"did": cd.id})
    db.execute(text("""
        UPDATE fraccionamientos
        SET estado = 'refinanciado', saldo_pendiente = 0, updated_at = NOW()
        WHERE id = :fid
    """), {"fid": old.id})

    # 6. Registrar el PAGO INICIAL externo (patrón Zamora) sobre la cuota 0 del nuevo.
    pago = Payment(
        organization_id=old.organization_id,
        colegiado_id=old.colegiado_id,
        amount=plan["monto_inicial"],
        currency="PEN",
        payment_method=metodo_pago_inicial,
        operation_code=operacion_inicial,
        status="approved",
        notes=f"[REFINANCIAMIENTO] cuota inicial del plan {nuevo.numero_solicitud} "
              f"(refinancia {old.numero_solicitud})",
    )
    db.add(pago)
    db.flush()
    pago_res = pagar_cuota_fraccionamiento(
        db=db,
        fraccionamiento_id=nuevo.id,
        numero_cuota=0,
        monto=plan["monto_inicial"],
        metodo_pago=metodo_pago_inicial,
        operador_nota=f"[REFINANCIAMIENTO] inicial externa user{user_id}",
        payment_obj=pago,
    )

    # 7. HABILIDAD por CONCESIÓN del inicial (igual que el flujo real de pago-cuota,
    #    secretaria.py:1139-1148). NO se usa sincronizar_condicion: con fracc activo su
    #    guard NO rehabilita (evaluar_habilidad.py:310), dejaría al colegiado INHÁBIL.
    #    Refinanciar → HÁBIL (coherente con Fraccionar→Hábil). Validado en el caso
    #    manual de Fiorella.
    #    🔗 unificar-writers: el motor NO sabe "habilitar por concesión"; por eso cada
    #    flujo positivo (pago, refinanciamiento) trae su propio writer de concesión.
    #    Cuando se unifiquen los writers, esta lógica de "concesión habilita" debe vivir
    #    en UN solo lugar. Asimetría a preservar: refinanciar/pago HABILITAN por concesión;
    #    pérdida INHABILITA por re-evaluación del motor.
    reevaluacion = None
    if reevaluar_habilidad and colegiado is not None:
        cond_previa = colegiado.condicion
        fin_mes = (ahora.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        colegiado.condicion = "habil"
        colegiado.habilidad_vence = fin_mes
        colegiado.fecha_actualizacion_condicion = ahora
        reevaluacion = {
            "condicion_previa": cond_previa,
            "condicion_nueva": colegiado.condicion,
            "cambio": cond_previa != colegiado.condicion,
            "habilidad_vence": fin_mes.date().isoformat(),
        }

    # 8. Flag + commit único.
    refrescar_flag_fraccionamiento(db, old.colegiado_id)
    db.commit()

    logger.info(
        "REFINANCIADO fracc %s -> nuevo %s por user=%s: total=%s inicial=%s adic=%s",
        old.numero_solicitud, nuevo.numero_solicitud, user_id,
        plan["total_consolidado"], plan["monto_inicial"], plan["adicionales_ids"],
    )

    return {
        "ok": True,
        "fracc_viejo_id": old.id,
        "fracc_nuevo_id": nuevo.id,
        "numero_solicitud_nuevo": nuevo.numero_solicitud,
        "refinanciado_por_id": old.id,
        "total_consolidado": plan["total_consolidado"],
        "cronograma": resultado.cronograma,
        "advertencia_inicial": resultado.advertencia_inicial,
        "pago_inicial": pago_res,
        "reevaluacion_habilidad": reevaluacion,
    }


def refinanciar_core(
    db: Session,
    fracc_viejo_id: int,
    deudas_adicionales_ids,
    monto_inicial: float,
    num_cuotas: int,
    user_id,
    monto_cuota_mensual=None,
    metodo_pago_inicial: str = "efectivo",
    operacion_inicial=None,
    reevaluar_habilidad: bool = True,
) -> dict:
    """Refinancia un fraccionamiento sano: consolida (saldo viejo + adicionales),
    crea el nuevo plan, cierra el viejo (linaje), registra el inicial externo y
    re-evalúa habilidad. Atómico. Lanza RefinanciarError en los casos inválidos.
    """
    plan = _planificar_refinanciamiento(
        db, fracc_viejo_id, deudas_adicionales_ids, monto_inicial, num_cuotas)
    try:
        return _ejecutar_refinanciamiento(
            db, plan, user_id,
            monto_cuota_mensual=monto_cuota_mensual,
            metodo_pago_inicial=metodo_pago_inicial,
            operacion_inicial=operacion_inicial,
            reevaluar_habilidad=reevaluar_habilidad,
        )
    except Exception:
        db.rollback()   # atomicidad: cualquier fallo revierte TODO (viejo reabre)
        raise

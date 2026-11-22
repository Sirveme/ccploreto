"""
Servicio: Creación y pago de fraccionamientos
app/services/fraccionamiento_service.py

Helper compartido entre:
- POST /api/secretaria/registrar-fraccionamiento (secretaria.py)
- POST /api/secretaria/registrar-pago-cuota-fracc (secretaria.py)

Nota: el endpoint canónico del portal del colegiado es
POST /api/portal/fraccionamiento/crear (portal_colegiado.py), que mantiene
su propia lógica equivalente. Este helper se mantiene como entrada para
los flujos administrativos (Sandra) que requieren seleccionar deudas
explícitamente con `deuda_ids`.

Reglas CCPL:
- Deuda mínima S/ 250
- Cuota inicial >= 20% de deuda
- Cuota mensual >= S/ 100
- Máximo 12 cuotas mensuales
- Cuota 0 = inicial (vence hoy), cuotas 1..N mensuales (vencen día 15)
- Al pagar cuota inicial → colegiado queda HÁBIL hasta próxima cuota
"""

from datetime import date as dt_date, datetime, timezone, timedelta
from typing import Optional, List
from dataclasses import dataclass

from sqlalchemy.orm import Session
from fastapi import HTTPException

from dateutil.relativedelta import relativedelta

import logging

from app.models_debt_management import Debt, DebtAction, Fraccionamiento, FraccionamientoCuota
from app.services import parametros_service

logger = logging.getLogger(__name__)

PERU_TZ = timezone(timedelta(hours=-5))
# FALLBACK de seguridad. La fuente vigente son los parámetros de la tabla
# parametros_sistema (get_fraccionamiento); estas constantes solo se usan si esa
# lectura no devuelve la clave (tabla ausente/incompleta) para no romper el flujo.
DEUDA_MIN = 250.0
CUOTA_MENSUAL_MIN = 100.0
MAX_CUOTAS = 12
CUOTA_INICIAL_PCT = 0.20


def _resolver_parametros_fracc(db: Session, organization_id: int):
    """Resuelve los 4 parámetros de fraccionamiento desde parametros_sistema,
    con FALLBACK a las constantes del módulo si la tabla no responde una clave.

    Devuelve (deuda_min, cuota_mensual_min, max_cuotas, cuota_inicial_pct) donde
    cuota_inicial_pct es FRACCIÓN (0.20), convertida desde el valor humano (20)
    que guarda la tabla. Nunca lanza: ante cualquier fallo cae a las constantes.
    """
    cfg = {}
    try:
        cfg = parametros_service.get_fraccionamiento(db, organization_id) or {}
    except Exception as e:  # tabla ausente, DB, etc. -> fallback total
        logger.warning("[fracc] get_fraccionamiento falló (%s); uso constantes fallback",
                       str(e)[:160])

    def _num(clave, fallback):
        v = cfg.get(clave)
        return float(v) if v is not None else float(fallback)

    deuda_min = _num("monto_minimo", DEUDA_MIN)
    cuota_mensual_min = _num("cuota_minima", CUOTA_MENSUAL_MIN)
    max_cuotas = int(_num("max_cuotas", MAX_CUOTAS))
    pct_humano = cfg.get("cuota_inicial_pct")
    # tabla = humano (20 = 20%) -> fracción; fallback ya es fracción (0.20)
    cuota_inicial_pct = (float(pct_humano) / 100.0) if pct_humano is not None else CUOTA_INICIAL_PCT
    return deuda_min, cuota_mensual_min, max_cuotas, cuota_inicial_pct


@dataclass
class ResultadoFraccionamiento:
    fraccionamiento: Fraccionamiento
    cronograma: List[dict]   # [{n_cuota, monto, fecha_vencimiento}]
    condona_detalle: Optional[dict] = None
    # zClaude-84: filas espejo creadas en `debts` para el cronograma
    cuotas_debts_creadas: int = 0
    cuotas_debts_omitidas: int = 0
    cuota_inicial_debt_id: Optional[int] = None
    # Regla 20%-no-bloquea (Decano): si el inicial quedó bajo el mínimo de
    # referencia y NO se bloqueó, aquí va el texto de la advertencia/constancia.
    advertencia_inicial: Optional[str] = None


def _generar_numero_solicitud(db: Session, organization_id: int, anio: int) -> str:
    ultimo = (
        db.query(Fraccionamiento)
        .filter(Fraccionamiento.organization_id == organization_id)
        .filter(Fraccionamiento.numero_solicitud.like(f"FRACC-{anio}-%"))
        .count()
    )
    return f"FRACC-{anio}-{str(ultimo + 1).zfill(4)}"


def crear_fraccionamiento(
    db: Session,
    colegiado,
    deuda_ids: List[int],
    n_cuotas: int,
    monto_cuota_inicial: float,
    monto_cuota_mensual: Optional[float],
    created_by_user_id: int,
    nota_audit: Optional[str] = None,
    aplicar_acuerdo_007: bool = True,
    commit: bool = True,
    permitir_con_activo: bool = False,
) -> ResultadoFraccionamiento:
    """
    Crea un plan de fraccionamiento. Valida reglas, crea Fraccionamiento,
    FraccionamientoCuota[], marca las deudas como 'fraccionada' y
    (opcionalmente) aplica condonación del Acuerdo 007-2026.

    Raises HTTPException con detalles si la validación falla.
    """
    if not deuda_ids:
        raise HTTPException(400, "Debe seleccionar al menos una deuda para fraccionar")

    # Parámetros vigentes (parametros_sistema) con fallback a las constantes.
    deuda_min, cuota_mensual_min, max_cuotas, cuota_inicial_pct = \
        _resolver_parametros_fracc(db, colegiado.organization_id)

    # Inicial de monto LIBRE (decisión Duilio/Decano): la inicial NUNCA bloquea.
    # El parámetro inicial_minima_bloquea quedó obsoleto como bloqueo (el % es solo
    # sugerencia); ya no se lee aquí. Ver bloque de validación de inicial más abajo.

    if not (2 <= n_cuotas <= max_cuotas):
        raise HTTPException(
            400,
            f"El número de cuotas debe estar entre 2 y {max_cuotas}"
        )

    # ── Verificar plan activo ──
    plan_existente = (
        db.query(Fraccionamiento)
        .filter(
            Fraccionamiento.colegiado_id == colegiado.id,
            Fraccionamiento.estado == "activo",
        )
        .first()
    )
    if plan_existente and not permitir_con_activo:
        raise HTTPException(
            409,
            f"El colegiado ya tiene un plan activo (#{plan_existente.numero_solicitud})"
        )
    # permitir_con_activo=True: usado por refinanciar_core, que crea el nuevo plan
    # ANTES de cerrar el viejo (ambos en la MISMA transacción atómica). El estado
    # committeado nunca tiene dos activos.

    # ── Cargar deudas y validar pertenencia ──
    deudas_qs = (
        db.query(Debt)
        .filter(
            Debt.id.in_(deuda_ids),
            Debt.colegiado_id == colegiado.id,
            Debt.status.in_(["pending", "partial"]),
        )
        .all()
    )
    if len(deudas_qs) != len(set(deuda_ids)):
        encontradas = {d.id for d in deudas_qs}
        faltantes = set(deuda_ids) - encontradas
        raise HTTPException(
            400,
            f"Deudas no válidas o ya resueltas: {sorted(faltantes)}"
        )

    total = round(sum(float(d.balance or d.amount or 0) for d in deudas_qs), 2)
    if total < deuda_min:
        raise HTTPException(
            400,
            f"La deuda (S/ {total:.2f}) es menor al mínimo de S/ {deuda_min:.2f}"
        )

    # ── Cuota inicial de monto LIBRE (decisión Duilio/Decano) ──
    # El % es SOLO SUGERENCIA; la inicial NUNCA bloquea (ni por hardcode ni por el
    # parámetro inicial_minima_bloquea). Los montos son siempre distintos (cada
    # colegiado paga lo que puede). Si el inicial está bajo el sugerido, se registra
    # igual y se deja CONSTANCIA (DebtAction 'nota'), nunca se rechaza.
    from app.utils.cuotas_enteras import inicial_sugerida, repartir
    minimo_inicial = inicial_sugerida(total, cuota_inicial_pct)   # sugerido (informativo), soles enteros
    advertencia_inicial = None
    if monto_cuota_inicial < minimo_inicial - 0.009:
        advertencia_inicial = (
            f"Cuota inicial S/ {monto_cuota_inicial:.2f} por debajo del SUGERIDO "
            f"S/ {minimo_inicial:.2f} ({int(cuota_inicial_pct * 100)}%). "
            f"Inicial de monto libre: se registra igual."
        )
    if monto_cuota_inicial >= total:
        raise HTTPException(
            400,
            "La cuota inicial no puede cubrir toda la deuda; usa pago directo"
        )

    # ── Calcular cuota mensual ──
    saldo = round(total - monto_cuota_inicial, 2)
    # Sin céntimos (tanda 8): n-1 cuotas en soles enteros hacia abajo; la última absorbe la diferencia.
    montos_mensuales = repartir(saldo, n_cuotas)
    monto_mensual_calc = montos_mensuales[0]

    # Si el cliente mandó un valor, debe ser consistente (tolerancia 1 sol)
    if monto_cuota_mensual is not None:
        if abs(monto_cuota_mensual - monto_mensual_calc) > 1.0:
            raise HTTPException(
                400,
                f"La cuota mensual esperada es S/ {monto_mensual_calc:.2f} "
                f"(saldo {saldo:.2f} / {n_cuotas} cuotas)"
            )
    monto_mensual = monto_mensual_calc

    if monto_mensual < cuota_mensual_min:
        raise HTTPException(
            400,
            f"La cuota mensual resultante (S/ {monto_mensual:.2f}) es menor "
            f"al mínimo de S/ {cuota_mensual_min:.2f}. Reduce el número "
            f"de cuotas o aumenta la cuota inicial."
        )

    # ── Fechas ──
    hoy = dt_date.today()
    primer_venc = hoy.replace(day=15) + relativedelta(months=1)
    ultima_venc = primer_venc + relativedelta(months=n_cuotas - 1)

    # ── Número de solicitud ──
    numero_solicitud = _generar_numero_solicitud(db, colegiado.organization_id, hoy.year)

    # ── Crear Fraccionamiento ──
    fracc = Fraccionamiento(
        organization_id=colegiado.organization_id,
        colegiado_id=colegiado.id,
        numero_solicitud=numero_solicitud,
        fecha_solicitud=hoy,
        deuda_total_original=total,
        cuota_inicial=monto_cuota_inicial,
        cuota_inicial_pagada=False,
        saldo_a_fraccionar=saldo,
        num_cuotas=n_cuotas,
        monto_cuota=monto_mensual,
        cuotas_pagadas=0,
        cuotas_atrasadas=0,
        saldo_pendiente=total,
        fecha_inicio=hoy,
        fecha_fin_estimada=ultima_venc,
        proxima_cuota_fecha=hoy,
        proxima_cuota_numero=0,
        estado="activo",
        created_by=created_by_user_id,
        approved_by=None,
    )
    db.add(fracc)
    db.flush()

    # ── Crear cuotas ──
    cuotas_objs: List[FraccionamientoCuota] = []
    cronograma: List[dict] = []

    # Cuota 0 — inicial
    cuotas_objs.append(FraccionamientoCuota(
        fraccionamiento_id=fracc.id,
        numero_cuota=0,
        monto=monto_cuota_inicial,
        fecha_vencimiento=hoy,
        habilidad_hasta=None,
    ))
    cronograma.append({
        "n_cuota": 0,
        "monto": float(monto_cuota_inicial),
        "fecha_vencimiento": hoy.isoformat(),
        "tipo": "inicial",
    })

    # Cuotas mensuales 1..N
    for i in range(1, n_cuotas + 1):
        venc = primer_venc + relativedelta(months=i - 1)
        fin_mes = (venc.replace(day=1) + relativedelta(months=1)) - timedelta(days=1)
        cuotas_objs.append(FraccionamientoCuota(
            fraccionamiento_id=fracc.id,
            numero_cuota=i,
            monto=montos_mensuales[i - 1],
            fecha_vencimiento=venc,
            habilidad_hasta=fin_mes,
        ))
        cronograma.append({
            "n_cuota": i,
            "monto": float(montos_mensuales[i - 1]),
            "fecha_vencimiento": venc.isoformat(),
            "tipo": "mensual",
        })

    db.bulk_save_objects(cuotas_objs)

    # ── Marcar deudas como fraccionadas ──
    for d in deudas_qs:
        d.estado_gestion = "fraccionada"
        d.fraccionamiento_id = fracc.id
        if nota_audit:
            d.notes = ((d.notes or "") + f"\n{nota_audit}").strip()

    # ── zClaude-84: generar filas espejo en `debts` ──
    # Necesario para que Sandra pueda cobrar la cuota inicial el mismo
    # día y para que el modal del plan en /caja resuelva cada cuota a
    # su deuda real (evita "·sin enlace").
    db.flush()
    from app.services.fraccionamiento_cuotas_service import (
        generar_cuotas_fracc_en_debts,
        obtener_debt_id_cuota_inicial,
    )
    resultado_gen = generar_cuotas_fracc_en_debts(
        db=db,
        fraccionamiento_id=fracc.id,
        user_id=created_by_user_id,
        marcador_origen="GEN-FRACC-ON-CREATE",
    )
    if resultado_gen["errores"]:
        db.rollback()
        raise HTTPException(
            500,
            f"Error generando cuotas en debts: {resultado_gen['errores']}",
        )
    debt_id_inicial = obtener_debt_id_cuota_inicial(db, fracc.id)

    # ── Constancia de excepción 20%-no-bloquea (DebtAction tipo='nota') ──
    # Deja registro AUDITABLE de quién procedió con inicial bajo el mínimo.
    # 'nota' NO requiere doble firma. Solo si hay debt de cuota inicial al que anclar.
    if advertencia_inicial and debt_id_inicial:
        db.add(DebtAction(
            organization_id=colegiado.organization_id,
            debt_id=debt_id_inicial,
            fraccionamiento_id=fracc.id,
            tipo="nota",
            descripcion=f"[INICIAL-BAJO-20%] {advertencia_inicial}",
            created_by=created_by_user_id,
        ))
        db.flush()

    # La marca 'tiene fraccionamiento' se enciende al crear el plan (antes quedaba
    # apagada hasta el primer pago). Idempotente.
    from app.services.politicas_financieras import refrescar_flag_fraccionamiento
    db.flush()
    refrescar_flag_fraccionamiento(db, colegiado.id)

    # commit=False: el llamador (p.ej. refinanciar_core) orquesta varios pasos en
    # UNA transacción y commitea al final. Default True conserva el comportamiento.
    if commit:
        db.commit()
        db.refresh(fracc)
    else:
        db.flush()

    # ── Aplicar Acuerdo 007-2026 si corresponde ──
    condona_info = None
    if aplicar_acuerdo_007:
        try:
            from app.services.servicio_condona_007 import aplicar_condona_acuerdo_007
            resumen = aplicar_condona_acuerdo_007(
                db,
                colegiado_id=colegiado.id,
                org_id=colegiado.organization_id,
                aprobado_por_id=created_by_user_id,
            )
            if resumen.aplicado:
                condona_info = {
                    "aplicado": True,
                    "filas_condonadas": resumen.filas_condonadas,
                    "monto_condonado": float(resumen.monto_condonado),
                    "mensaje": resumen.mensaje,
                }
            else:
                condona_info = {
                    "aplicado": False,
                    "mensaje": resumen.mensaje,
                }
        except Exception as e:
            condona_info = {
                "aplicado": False,
                "mensaje": f"No se pudo evaluar Acuerdo 007-2026: {e}"
            }

    return ResultadoFraccionamiento(
        fraccionamiento=fracc,
        cronograma=cronograma,
        condona_detalle=condona_info,
        cuotas_debts_creadas=len(resultado_gen["creadas"]),
        cuotas_debts_omitidas=len(resultado_gen["omitidas"]),
        cuota_inicial_debt_id=debt_id_inicial,
        advertencia_inicial=advertencia_inicial,
    )


MARCA_PLAN_COMPLETADO = "[PLAN-COMPLETADO fracc:%d]"


def _guardar_habilidad_previa(db: Session, cuota_id: int, colegiado_id: int) -> None:
    """Guarda en la cuota la condición y el vencimiento de habilidad que el colegiado
    tenía ANTES de pagarla. Nunca lanza: si faltan las columnas, no guarda nada."""
    from sqlalchemy import text as _text
    try:
        with db.begin_nested():
            db.execute(_text("""
                UPDATE fraccionamiento_cuotas fc
                SET habilidad_vence_previa = c.habilidad_vence, condicion_previa = c.condicion
                FROM colegiados c WHERE fc.id = :cuota AND c.id = :col
            """), {"cuota": cuota_id, "col": colegiado_id})
    except Exception as exc:  # columnas aún no creadas
        logger.warning("habilidad previa no guardada (¿falta sql/zClaude-cuota-habilidad-previa.sql?): %s",
                       str(exc)[:120])


def revertir_cuotas_por_pago(db: Session, payment_id: int, etiqueta: str = "") -> List[dict]:
    """Deshace en el PLAN lo que un pago anulado (NC) o revertido había pagado.

    Por cada cuota pagada con ese pago, en un plan activo o completado:
      - la cuota vuelve a impaga; baja el contador; el saldo del plan recupera el monto;
      - si era la inicial, el plan deja de tenerla por pagada;
      - su deuda espejo vuelve a pendiente;
      - si el plan estaba 'completado', vuelve a 'activo' y se reabren las deudas
        originales que se habían cerrado al completarlo.
    NO toca la habilidad (ver aplicar_habilidad_tras_reversion) y NO hace commit.
    Devuelve una fila por cuota revertida, con la habilidad previa guardada (si existe).
    """
    from sqlalchemy import text as _text
    filas = db.execute(_text("""
        SELECT fc.id, fc.numero_cuota, fc.monto, fc.fraccionamiento_id, fc.debt_id,
               f.estado, f.colegiado_id
        FROM fraccionamiento_cuotas fc JOIN fraccionamientos f ON f.id = fc.fraccionamiento_id
        WHERE fc.payment_id = :p AND fc.pagada = TRUE AND f.estado IN ('activo', 'completado')
        ORDER BY fc.numero_cuota
        FOR UPDATE OF fc, f
    """), {"p": payment_id}).fetchall()
    revertidas = []
    for c in filas:
        previa = {"hay": False, "vence": None, "condicion": None}
        try:
            with db.begin_nested():
                r = db.execute(_text("""SELECT habilidad_vence_previa, condicion_previa
                                        FROM fraccionamiento_cuotas WHERE id = :c"""), {"c": c.id}).fetchone()
                if r and r.condicion_previa is not None:
                    previa = {"hay": True, "vence": r.habilidad_vence_previa, "condicion": r.condicion_previa}
                db.execute(_text("""UPDATE fraccionamiento_cuotas
                                    SET habilidad_vence_previa = NULL, condicion_previa = NULL WHERE id = :c"""), {"c": c.id})
        except Exception:
            pass  # sin columnas: se usará el respaldo calculado
        db.execute(_text("""UPDATE fraccionamiento_cuotas
                            SET pagada = FALSE, fecha_pago = NULL, payment_id = NULL WHERE id = :c"""), {"c": c.id})
        if c.debt_id:
            db.execute(_text("""
                UPDATE debts SET status = 'pending', balance = amount, updated_at = NOW(),
                       notes = coalesce(notes || E'\\n', '') || :n
                WHERE id = :d AND debt_type = 'fraccionamiento'
            """), {"d": c.debt_id, "n": "[CUOTA-REVERTIDA pago:%d] %s" % (payment_id, etiqueta)})
        if c.estado == "completado":
            db.execute(_text("""
                UPDATE debts SET status = 'pending', balance = amount, updated_at = NOW(),
                       notes = coalesce(notes || E'\\n', '') || '[PLAN-REABIERTO]'
                WHERE fraccionamiento_id = :f AND status = 'paid' AND notes LIKE :marca
            """), {"f": c.fraccionamiento_id, "marca": "%" + (MARCA_PLAN_COMPLETADO % c.fraccionamiento_id) + "%"})
        db.execute(_text("""
            UPDATE fraccionamientos
            SET estado = 'activo',
                cuotas_pagadas = GREATEST(coalesce(cuotas_pagadas, 0) - 1, 0),
                saldo_pendiente = coalesce(saldo_pendiente, 0) + :m,
                cuota_inicial_pagada = CASE WHEN :n = 0 THEN FALSE ELSE cuota_inicial_pagada END
            WHERE id = :f
        """), {"m": float(c.monto), "n": c.numero_cuota, "f": c.fraccionamiento_id})
        # próxima cuota = la impaga de menor número
        db.execute(_text("""
            UPDATE fraccionamientos f
            SET proxima_cuota_numero = x.numero_cuota, proxima_cuota_fecha = x.fecha_vencimiento
            FROM (SELECT numero_cuota, fecha_vencimiento FROM fraccionamiento_cuotas
                  WHERE fraccionamiento_id = :f AND pagada = FALSE ORDER BY numero_cuota LIMIT 1) x
            WHERE f.id = :f
        """), {"f": c.fraccionamiento_id})
        revertidas.append({"cuota_id": c.id, "numero_cuota": c.numero_cuota, "monto": float(c.monto),
                           "fraccionamiento_id": c.fraccionamiento_id, "colegiado_id": c.colegiado_id,
                           "previa": previa})
    if revertidas:
        db.flush()
        db.expire_all()
        from app.services.politicas_financieras import refrescar_flag_fraccionamiento
        refrescar_flag_fraccionamiento(db, revertidas[0]["colegiado_id"])
        db.flush()
        logger.info("Pago #%s: %d cuota(s) de plan revertida(s) %s", payment_id, len(revertidas),
                    [r["numero_cuota"] for r in revertidas])
    return revertidas


def aplicar_habilidad_tras_reversion(db: Session, colegiado, revertidas: List[dict], org: dict) -> str:
    """Habilidad después de revertir cuotas de un plan. NO hace commit.

    - Si se revirtió la INICIAL: se retira la habilidad (inhábil, sin vencimiento).
    - Si fue otra cuota: se restaura el vencimiento que el colegiado tenía antes de
      ese pago y luego se re-evalúa con la regla vigente (motor oficial).
    Devuelve un texto corto con lo que hizo.
    """
    if not revertidas or colegiado is None:
        return ""
    if getattr(colegiado, "condicion", "") in ("vitalicio", "fallecido", "retirado"):
        return "condición %s: no se toca" % colegiado.condicion
    ahora = datetime.now(timezone(timedelta(hours=-5)))
    if any(r["numero_cuota"] == 0 for r in revertidas):
        colegiado.condicion = "inhabil"
        colegiado.habilidad_vence = None
        colegiado.motivo_inhabilidad = "Anulación del pago de la cuota inicial del fraccionamiento"
        colegiado.fecha_actualizacion_condicion = ahora
        db.flush()
        return "inicial anulada: habilidad retirada"

    primera = min(revertidas, key=lambda r: r["numero_cuota"])
    if primera["previa"]["hay"]:
        colegiado.habilidad_vence = primera["previa"]["vence"]
        if primera["previa"]["condicion"] in ("habil", "inhabil"):
            colegiado.condicion = primera["previa"]["condicion"]
        origen = "guardado"
    else:
        # Pago anterior a la columna: se reconstruye desde lo que sigue pagado en el plan.
        from sqlalchemy import text as _text
        r = db.execute(_text("""
            SELECT max(habilidad_hasta) FILTER (WHERE numero_cuota >= 1) hh,
                   max(fecha_pago) FILTER (WHERE numero_cuota = 0) ini
            FROM fraccionamiento_cuotas WHERE fraccionamiento_id = :f AND pagada = TRUE
        """), {"f": primera["fraccionamiento_id"]}).fetchone()
        vence = r.hh if r else None
        if vence is None and r and r.ini:
            vence = (r.ini.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        from app.utils.habilidad_fecha import vence_hasta
        colegiado.habilidad_vence = vence_hasta(vence) if vence else None   # fecha sin hora (00:00 UTC)
        origen = "reconstruido"
    colegiado.fecha_actualizacion_condicion = ahora
    db.flush()
    from app.services.evaluar_habilidad import sincronizar_condicion
    sincronizar_condicion(db, colegiado, org or {})
    db.flush()
    return "vencimiento anterior restaurado (%s) y condición re-evaluada: %s" % (origen, colegiado.condicion)


def pagar_cuota_fraccionamiento(
    db: Session,
    fraccionamiento_id: int,
    numero_cuota: int,
    monto: float,
    metodo_pago: str,
    operador_nota: str,
    payment_obj=None,
) -> dict:
    """
    Marca una cuota como pagada. Retorna dict con {cuota, es_inicial, habilidad_hasta}.
    Actualiza también fracc.cuotas_pagadas, saldo_pendiente, proxima_cuota_*.
    Si cuotas_pagadas == num_cuotas + 1 (inicial + todas), estado = 'completado'.
    """
    fracc = db.query(Fraccionamiento).filter(
        Fraccionamiento.id == fraccionamiento_id
    ).first()
    if not fracc:
        raise HTTPException(404, "Fraccionamiento no encontrado")
    if fracc.estado != "activo":
        raise HTTPException(
            400,
            f"El fraccionamiento está {fracc.estado}, no permite pagos"
        )

    cuota = db.query(FraccionamientoCuota).filter(
        FraccionamientoCuota.fraccionamiento_id == fraccionamiento_id,
        FraccionamientoCuota.numero_cuota == numero_cuota,
    ).first()
    if not cuota:
        raise HTTPException(404, f"Cuota {numero_cuota} no existe en el plan")
    if cuota.pagada:
        raise HTTPException(400, f"La cuota {numero_cuota} ya está pagada")

    # Foto de la habilidad ANTES de este pago: si luego se anula (NC / reversión), se
    # restaura este vencimiento. Columnas de sql/zClaude-cuota-habilidad-previa.sql
    # (no mapeadas en el ORM). En savepoint: si el SQL aún no se corrió, el cobro sigue.
    _guardar_habilidad_previa(db, cuota.id, fracc.colegiado_id)

    hoy = dt_date.today()
    cuota.pagada = True
    cuota.fecha_pago = hoy
    if payment_obj is not None and getattr(payment_obj, "id", None):
        cuota.payment_id = payment_obj.id

    # La deuda ESPEJO de la cuota queda pagada en el mismo acto, venga el pago de
    # Caja, de Secretaría o de un refinanciamiento (debt_id no está en el ORM).
    from sqlalchemy import text as _text
    db.execute(_text("""
        UPDATE debts SET status = 'paid', balance = 0, updated_at = NOW()
        WHERE id = (SELECT debt_id FROM fraccionamiento_cuotas WHERE id = :c)
          AND status IN ('pending', 'partial')
    """), {"c": cuota.id})

    # Actualizar contadores del plan
    fracc.cuotas_pagadas = (fracc.cuotas_pagadas or 0) + 1
    fracc.saldo_pendiente = max(0.0, float(fracc.saldo_pendiente or 0) - float(monto))

    es_inicial = (numero_cuota == 0)
    if es_inicial:
        fracc.cuota_inicial_pagada = True

    # Próxima cuota pendiente. La sesión NO hace autoflush (app/database.py): sin este
    # flush la consulta aún ve impaga la cuota recién pagada, se encuentra a sí misma
    # y el plan nunca pasa a 'completado'.
    db.flush()
    proxima = db.query(FraccionamientoCuota).filter(
        FraccionamientoCuota.fraccionamiento_id == fraccionamiento_id,
        FraccionamientoCuota.pagada == False,  # noqa: E712
    ).order_by(FraccionamientoCuota.numero_cuota.asc()).first()

    if proxima:
        fracc.proxima_cuota_numero = proxima.numero_cuota
        fracc.proxima_cuota_fecha = proxima.fecha_vencimiento
    else:
        fracc.estado = "completado"
        fracc.saldo_pendiente = 0.0
        fracc.proxima_cuota_numero = None
        fracc.proxima_cuota_fecha = None
        # Las deudas ORIGINALES que absorbió el plan quedan saldadas con él (si no,
        # siguen 'pendientes' y Caja las vuelve a ofrecer). La marca permite reabrirlas
        # si se anula el pago de la última cuota.
        db.execute(_text("""
            UPDATE debts SET status = 'paid', balance = 0, updated_at = NOW(),
                   notes = coalesce(notes || E'\\n', '') || :marca
            WHERE fraccionamiento_id = :f AND debt_type <> 'fraccionamiento'
              AND estado_gestion = 'fraccionada' AND status IN ('pending', 'partial')
        """), {"f": fracc.id, "marca": MARCA_PLAN_COMPLETADO % fracc.id})

    # (b) sincronizar flag con la existencia de fracc activo (idempotente).
    from app.services.politicas_financieras import refrescar_flag_fraccionamiento
    db.flush()   # el cambio de estado debe estar en la BD: refrescar_flag consulta sin autoflush
    refrescar_flag_fraccionamiento(db, fracc.colegiado_id)

    db.flush()

    return {
        "cuota_id": cuota.id,
        "numero_cuota": numero_cuota,
        "es_inicial": es_inicial,
        "habilidad_hasta": cuota.habilidad_hasta.isoformat() if cuota.habilidad_hasta else None,
        "completado": fracc.estado == "completado",
        "proxima_cuota_numero": fracc.proxima_cuota_numero,
        "proxima_cuota_fecha": (
            fracc.proxima_cuota_fecha.isoformat()
            if fracc.proxima_cuota_fecha else None
        ),
        "notas_operador": operador_nota,
    }

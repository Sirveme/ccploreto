"""
app/services/fraccionamiento_perdida_service.py
Núcleo reutilizable de la PÉRDIDA de un fraccionamiento.

Extraído (sin cambio de comportamiento) del endpoint
POST /secretaria/fraccionamientos/{id}/marcar-perdido (secretaria.py).
Objetivo: que la MISMA lógica sea llamable desde:
  - el endpoint manual (Sandra), y
  - el futuro EJECUTOR de pérdida automática (parámetro perdida_automatica).

Pasos (idénticos al endpoint original):
  1. Bloquea el fracc (FOR UPDATE) y valida estado.
  2. Restaura deudas originales vinculadas (idempotente).
  3. Aplica pagos previos a cuotas sobre originales (orden cronológico).
  4. Cancela cuotas del fracc (status='cancelled').
  5. Cambia estado del fracc a 'perdido' con fecha y motivo.
  6. Apaga el flag tiene_fraccionamiento (si no queda otro activo).

Guards HTTP → FraccPerdidoError (dominio): el endpoint la mapea a HTTPException;
el ejecutor automático la captura y salta el caso.

Paso (B) — decisión aprobada (Decano): tras marcar perdido, RE-EVALÚA la
habilidad vía el MOTOR (sincronizar_condicion), gateado por reevaluar_habilidad
(default True). Perder puede INHABILITAR (sin el guard "solo rehabilitar" del
pago). Pérdida MANUAL únicamente: perdida_automatica queda FALSE, sin disparador.
"""
from datetime import datetime, timezone, timedelta
import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Perú = UTC-5 (mismo criterio que secretaria.py). Se usa solo para el sello de las notas.
PERU_TZ = timezone(timedelta(hours=-5))


class FraccPerdidoError(Exception):
    """Error de dominio de la pérdida. status_code/detail para que el endpoint
    lo mapee a HTTPException sin que el core dependa de FastAPI."""
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _hoy_peru():
    """Fecha de HOY en zona Perú (UTC-5). El servidor corre en UTC; date.today()
    adelanta un día cerca de medianoche. Frente timezone: fuente única de 'hoy'."""
    return datetime.now(PERU_TZ).date()


def detectar_candidatos_perdida(
    db: Session,
    organization_id: int,
    *,
    fecha_ref=None,
    ejecutar: bool = False,
    user_id=None,
    solo_sanos: bool = True,
) -> dict:
    """Detecta (read-only por defecto) los fraccionamientos ACTIVOS que cumplen la
    condición de PÉRDIDA: >= `cuotas_impagas_perdida` cuotas CONSECUTIVAS vencidas
    e impagas (umbral leído de parametros_sistema, hoy 2).

    solo_sanos (default True): filtra por el marcador de SALUD escalonado —
    COUNT(DISTINCT fecha_vencimiento) > 1 sobre las cuotas. Deja fuera el batch
    "Importación masiva Excel — Sandra" (cuotas al mismo vencimiento, saldo sin
    conciliar) e incluye sanos + reparados (Flores #132, Zamora #139). Así la vista
    "Por revisar" opera solo sobre saldos confiables. En False, barre todos.

    Modo (parámetro `perdida_automatica` de parametros_sistema, hoy FALSE):
      • MANUAL (auto=False) — o `ejecutar=False`: NO ejecuta nada. Solo devuelve la
        lista de candidatos para la vista "Fraccionamientos por revisar", donde una
        persona decide y ejecuta con marcar_fracc_perdido_core (vía el endpoint).
      • AUTOMÁTICO (auto=True Y ejecutar=True): *(rama futura, HOY APAGADA por el
        parámetro)* ejecutaría el core sobre cada candidato. Doble condición a
        propósito: el flag del param Y un opt-in explícito del llamador.

    Consecutivas: reutiliza generador_deudas._contar_consecutivas_vencidas (única
    fuente de esa matemática; NO se duplica). Usa hoy_peru(), no date.today().
    Igualdad de diseño (aprobada): candidato == EN_RIESGO (sin etapa de aviso previo).
    """
    from app.models_debt_management import Fraccionamiento
    from app.services.parametros_service import get_seccion
    from app.services.generador_deudas import _contar_consecutivas_vencidas

    hoy = fecha_ref or _hoy_peru()
    # Lector conectado al preset de Condiciones (fuente única). Fallback: la ruta
    # anterior (parametros_sistema) y, en último término, los defaults del código.
    try:
        from app.services.condiciones_service import get_condiciones
        cond = get_condiciones(db, organization_id)
        umbral = int(cond["perdida_fracc_consecutivas"])
        auto = bool(cond["perdida_automatica"])
    except Exception:
        params = get_seccion(db, "fraccionamiento", organization_id)
        umbral = int(params.get("cuotas_impagas_perdida") or 2)
        auto = bool(params.get("perdida_automatica") or False)

    fraccs = db.query(Fraccionamiento).filter(
        Fraccionamiento.organization_id == organization_id,
        Fraccionamiento.estado == "activo",
    ).all()

    candidatos = []
    total_operables = 0
    for f in fraccs:
        # marcador de salud: vencimientos escalonados (cronograma real)
        distinct_venc = len({
            c.fecha_vencimiento for c in f.cuotas if c.fecha_vencimiento is not None
        })
        es_sano = distinct_venc > 1
        if solo_sanos and not es_sano:
            continue          # deja fuera el batch sin conciliar
        total_operables += 1
        consecutivas = _contar_consecutivas_vencidas(f.cuotas, hoy)
        if consecutivas < umbral:
            continue
        col = f.colegiado
        # Marcador de CONTAMINACIÓN: cuota inicial impaga ⇒ el fracc nunca arrancó
        # (batch mal formado). La vista lo separa de los candidatos reales y le oculta
        # el botón de pérdida (requiere conciliación antes de decidir). Solo lectura.
        cuota_inicial_pagada = bool(f.cuota_inicial_pagada)
        candidatos.append({
            "distinct_venc":        distinct_venc,
            "fraccionamiento_id":   f.id,
            "numero_solicitud":     f.numero_solicitud,
            "fecha_solicitud":      f.fecha_solicitud.isoformat() if f.fecha_solicitud else None,
            "colegiado_id":         f.colegiado_id,
            "matricula":            col.codigo_matricula if col else None,
            "nombre":               col.apellidos_nombres if col else None,
            "condicion":            col.condicion if col else None,
            "consecutivas_impagas": consecutivas,
            "cuotas_atrasadas":     int(f.cuotas_atrasadas or 0),
            "num_cuotas":           f.num_cuotas,
            "cuotas_pagadas":       int(f.cuotas_pagadas or 0),
            "monto_cuota":          float(f.monto_cuota or 0),
            "saldo_pendiente":      float(f.saldo_pendiente or 0),
            "cuota_inicial_pagada": cuota_inicial_pagada,
            "contaminado":          not cuota_inicial_pagada,
        })

    candidatos.sort(key=lambda c: (-c["consecutivas_impagas"], -c["saldo_pendiente"]))

    # ── rama AUTOMÁTICA (apagada por el parámetro; hoy nunca entra) ──
    ejecutados = []
    if ejecutar and auto:
        for c in candidatos:
            try:
                res = marcar_fracc_perdido_core(
                    db, c["fraccionamiento_id"],
                    f"Pérdida automática: {c['consecutivas_impagas']} cuotas "
                    f"consecutivas impagas (umbral {umbral})",
                    user_id, reevaluar_habilidad=True,
                )
                ejecutados.append({"fraccionamiento_id": c["fraccionamiento_id"], "resultado": res})
            except FraccPerdidoError as e:
                ejecutados.append({"fraccionamiento_id": c["fraccionamiento_id"], "error": e.detail})

    total_contaminados = sum(1 for c in candidatos if c["contaminado"])
    return {
        "modo":               "AUTOMATICO" if auto else "MANUAL",
        "perdida_automatica": auto,
        "solo_sanos":         solo_sanos,
        "umbral_cuotas":      umbral,
        "fecha":              hoy.isoformat(),
        "total_activos":      len(fraccs),
        "total_operables":    total_operables,   # sanos evaluados (si solo_sanos)
        "total_candidatos":   len(candidatos),
        "total_reales":       len(candidatos) - total_contaminados,   # cuota inicial pagada
        "total_contaminados": total_contaminados,                     # cuota inicial impaga
        "candidatos":         candidatos,
        "ejecutados":         ejecutados,
    }


def marcar_fracc_perdido_core(
    db: Session,
    fracc_id: int,
    motivo: str,
    user_id,
    reevaluar_habilidad: bool = True,
) -> dict:
    """Marca un fraccionamiento como perdido. Comportamiento idéntico al endpoint
    original en los pasos 1-6. Hace commit al final (como antes). Devuelve el
    mismo dict de resultado + 'reevaluacion_habilidad'.

    reevaluar_habilidad (default True): paso (B) — tras perder, RE-EVALÚA la
    condición vía el MOTOR (sincronizar_condicion). A diferencia del contexto de
    PAGO, aquí SÍ puede inhabilitar (perder el fracc retira el "escudo" de
    habilidad): por eso se llama al motor SIN el guard "solo rehabilitar" de
    caja.py/aprobar_pago.py. Gateado para poder desactivarlo desde el endpoint
    manual durante la transición sin revertir el refactor. NO se inventa writer
    nuevo de condición.

    Lanza FraccPerdidoError(404/409) en los mismos casos que el endpoint.
    """
    fr = db.execute(text("""
        SELECT id, colegiado_id, estado, deuda_total_original
        FROM fraccionamientos
        WHERE id = :fid
        FOR UPDATE
    """), {"fid": fracc_id}).fetchone()

    if not fr:
        raise FraccPerdidoError(404, "Fraccionamiento no encontrado")

    if fr.estado == "perdido":
        raise FraccPerdidoError(409, "Este fraccionamiento ya está marcado como perdido")

    if fr.estado == "cancelado":
        raise FraccPerdidoError(
            409,
            "Este fraccionamiento está cancelado, no se puede marcar como perdido"
        )

    # Solo se pierde un plan ACTIVO (un plan completado o refinanciado ya cerró su ciclo).
    if fr.estado != "activo":
        raise FraccPerdidoError(409, f"Este fraccionamiento está {fr.estado}; solo se puede declarar pérdida de un plan activo")

    # ── ENLACE DE LAS DEUDAS (corrección del defecto) ──────────────────────────
    # Hay dos generaciones de planes:
    #   · flujo ACTUAL (crear_fraccionamiento): las deudas ORIGINALES quedan con
    #     fraccionamiento_id = plan y gestión 'fraccionada'; las deudas ESPEJO de
    #     cada cuota también llevan fraccionamiento_id = plan, con debt_type
    #     'fraccionamiento'.
    #   · flujo ANTIGUO: las originales llevaban fraccionamiento_id_origen = plan.
    # Antes solo se miraba fraccionamiento_id_origen: en un plan actual no encontraba
    # originales (no restauraba nada) y además trataba TODAS las deudas con
    # fraccionamiento_id como cuotas y las anulaba: la deuda desaparecía.
    originales = db.execute(text("""
        SELECT id, amount, balance, status, estado_gestion, periodo,
               (fraccionamiento_id_origen = :fid) AS enlace_antiguo
        FROM debts
        WHERE (fraccionamiento_id_origen = :fid)
           OR (fraccionamiento_id = :fid AND coalesce(debt_type, '') <> 'fraccionamiento'
               AND estado_gestion = 'fraccionada')
        ORDER BY periodo NULLS LAST, id
        FOR UPDATE
    """), {"fid": fracc_id}).fetchall()

    cuotas = db.execute(text("""
        SELECT id, amount, balance, status
        FROM debts
        WHERE fraccionamiento_id = :fid AND debt_type = 'fraccionamiento'
        ORDER BY id
        FOR UPDATE
    """), {"fid": fracc_id}).fetchall()

    if not originales:
        # Plan sin deudas originales enlazadas (lote migrado): no hay qué restaurar.
        # Declarar la pérdida borraría el saldo del plan sin devolver la deuda.
        raise FraccPerdidoError(
            409,
            "Este fraccionamiento no tiene sus deudas originales enlazadas (plan del lote migrado). "
            "No se puede declarar la pérdida sin antes conciliar la deuda del colegiado."
        )

    # Lo pagado al plan = cuotas marcadas pagadas (incluida la inicial) + abonos
    # parciales a deudas espejo de cuotas aún impagas. La tabla de cuotas es la fuente:
    # en planes antiguos las cuotas no tienen deuda espejo.
    pagado_cuotas = db.execute(text("""
        SELECT coalesce(sum(monto), 0) FROM fraccionamiento_cuotas
        WHERE fraccionamiento_id = :fid AND pagada = TRUE
    """), {"fid": fracc_id}).scalar() or 0
    abonos_parciales = db.execute(text("""
        SELECT coalesce(sum(d.amount - d.balance), 0)
        FROM fraccionamiento_cuotas c JOIN debts d ON d.id = c.debt_id
        WHERE c.fraccionamiento_id = :fid AND NOT coalesce(c.pagada, FALSE)
          AND d.status = 'partial' AND d.balance < d.amount
    """), {"fid": fracc_id}).scalar() or 0
    pagos_a_cuotas = round(float(pagado_cuotas) + float(abonos_parciales), 2)

    ahora = datetime.now(PERU_TZ)
    nota_restaurar = (
        f"[FRACC-PERDIDO:user{user_id}] "
        f"{ahora.strftime('%d/%m/%Y %H:%M')} — "
        f"restauración por marcar perdido fracc {fracc_id}. "
        f"Motivo: {motivo[:100]}"
    )

    # 1) Restaurar las originales: vuelven a ser deuda exigible ('vigente').
    #    · enlace antiguo: saldo completo (comportamiento histórico);
    #    · flujo actual: CONSERVAN su saldo (fraccionar no lo tocó; si una estaba
    #      a medio pagar antes del plan, sigue a medio pagar).
    #    El enlace pasa a fraccionamiento_id_origen (queda la huella de qué plan fue).
    originales_restauradas = []
    saldos = {}
    for o in originales:
        if o.enlace_antiguo:
            saldo_o = float(o.amount or 0)
        else:
            saldo_o = float(o.balance if o.balance is not None else (o.amount or 0))
        saldos[o.id] = round(saldo_o, 2)
        db.execute(text("""
            UPDATE debts
            SET balance = :saldo,
                status = CASE WHEN :saldo <= 0.005 THEN 'paid'
                              WHEN :saldo < amount - 0.005 THEN 'partial' ELSE 'pending' END,
                estado_gestion = 'vigente',
                fraccionamiento_id_origen = :fid,
                fraccionamiento_id = NULL,
                updated_at = NOW(),
                notes = COALESCE(notes,'') || E'\n' || :nota
            WHERE id = :did
        """), {"did": o.id, "saldo": saldos[o.id], "fid": fracc_id, "nota": nota_restaurar})
        originales_restauradas.append(o.id)

    # 2) Reimputar lo pagado al plan, de la deuda más antigua a la más nueva.
    aplicaciones_pago = []
    saldo = pagos_a_cuotas
    for o in originales:
        if saldo <= 0.005:
            break
        disponible = saldos[o.id]
        if disponible <= 0.005:
            continue
        a_aplicar = round(min(saldo, disponible), 2)
        nuevo_balance = round(disponible - a_aplicar, 2)
        nuevo_status = "paid" if nuevo_balance <= 0.01 else "partial"
        nota_pago = (
            f"[FRACC-PERDIDO-PAGO:user{user_id}] "
            f"{ahora.strftime('%d/%m/%Y %H:%M')} — "
            f"aplicado S/{a_aplicar:.2f} de pagos previos al "
            f"fracc {fracc_id}"
        )
        db.execute(text("""
            UPDATE debts
            SET balance = :nb,
                status = :ns,
                updated_at = NOW(),
                notes = COALESCE(notes,'') || E'\n' || :nota
            WHERE id = :did
        """), {"nb": max(nuevo_balance, 0), "ns": nuevo_status, "did": o.id, "nota": nota_pago})
        aplicaciones_pago.append({
            "debt_id": o.id,
            "aplicado": a_aplicar,
            "balance_final": max(nuevo_balance, 0),
            "status_final": nuevo_status,
        })
        saldo = round(saldo - a_aplicar, 2)
    sobrante = round(max(saldo, 0), 2)   # pagó más de lo que debía en las originales (raro): queda informado

    # 3) Anular SOLO las deudas espejo de las cuotas (no las originales).
    cuotas_canceladas = []
    for c in cuotas:
        db.execute(text("""
            UPDATE debts
            SET balance = 0,
                status = 'cancelled',
                estado_gestion = 'anulada',
                updated_at = NOW(),
                notes = COALESCE(notes,'') ||
                        E'\n[FRACC-PERDIDO-CUOTA] cuota anulada por '
                        'pérdida del fracc'
            WHERE id = :did
        """), {"did": c.id})
        cuotas_canceladas.append(c.id)

    db.execute(text("""
        UPDATE fraccionamientos
        SET estado = 'perdido',
            saldo_pendiente = 0,
            fecha_perdida = NOW(),
            motivo_perdida = :motivo,
            updated_at = NOW()
        WHERE id = :fid
    """), {"motivo": motivo, "fid": fracc_id})

    # (b) el fracc dejó de estar activo → sincronizar el flag (apaga si no queda
    # otro fracc activo del mismo colegiado). Idempotente.
    _col_fp = db.execute(text(
        "SELECT colegiado_id FROM fraccionamientos WHERE id = :fid"
    ), {"fid": fracc_id}).fetchone()
    if _col_fp:
        from app.services.politicas_financieras import refrescar_flag_fraccionamiento
        refrescar_flag_fraccionamiento(db, _col_fp.colegiado_id)

    # ── (B) RE-EVALUAR HABILIDAD tras la pérdida (decisión B) ──────────────
    # Perder un fracc re-evalúa la condición y, a diferencia del contexto de
    # PAGO, AQUÍ SÍ puede inhabilitar. Se llama al MOTOR (no se inventa writer)
    # y SIN el guard "solo rehabilitar" de caja.py/aprobar_pago.py.
    # 🔗 unificar-writers: preservar esta asimetría (pago=guarded, pérdida=unguarded).
    # refrescar_flag_fraccionamiento ya dejó tiene_fraccionamiento=False en la
    # sesión → el motor lo lee como tiene_fracc=False y evalúa sobre la deuda
    # restaurada. sincronizar_condicion NO commitea; lo cubre el db.commit() de abajo.
    reevaluacion_habilidad = None
    if reevaluar_habilidad and _col_fp:
        from app.models import Colegiado, Organization
        from app.services.evaluar_habilidad import sincronizar_condicion
        colegiado = db.query(Colegiado).filter(
            Colegiado.id == _col_fp.colegiado_id
        ).first()
        if colegiado is not None:
            _org = db.query(Organization).filter(
                Organization.id == colegiado.organization_id
            ).first()
            org_dict = {"id": _org.id, "config": {}} if _org else {}
            _cond_previa = colegiado.condicion
            cambio_cond = sincronizar_condicion(db, colegiado, org_dict)
            reevaluacion_habilidad = {
                "condicion_previa": _cond_previa,
                "condicion_nueva": colegiado.condicion,
                "cambio": bool(cambio_cond),
                "motivo": getattr(colegiado, "motivo_inhabilidad", None),
            }

    db.commit()

    logger.info(
        "Fracc %s marcado como PERDIDO por user=%s: "
        "originales_restauradas=%s, cuotas_canceladas=%s, "
        "pagos_aplicados=%s",
        fracc_id,
        user_id,
        originales_restauradas,
        cuotas_canceladas,
        len(aplicaciones_pago),
    )

    return {
        "ok": True,
        "fracc_id": fracc_id,
        "originales_restauradas": originales_restauradas,
        "cuotas_canceladas": cuotas_canceladas,
        "aplicaciones_pago": aplicaciones_pago,
        "pagos_a_cuotas_total": round(pagos_a_cuotas, 2),
        "pago_sobrante_sin_imputar": sobrante,
        "reevaluacion_habilidad": reevaluacion_habilidad,
    }

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
    incluir_lote: bool = False,
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
        if solo_sanos and not es_sano and not incluir_lote:
            continue          # deja fuera el batch sin conciliar
        # Tanda 13: con incluir_lote, el lote migrado se lista APARTE («requiere conciliación», sin pérdida)
        # y NO cuenta como operable.
        if es_sano or not solo_sanos:
            total_operables += 1
        consecutivas = _contar_consecutivas_vencidas(f.cuotas, hoy)
        if consecutivas < umbral:
            continue
        col = f.colegiado
        # Marcador de CONTAMINACIÓN: cuota inicial impaga ⇒ el fracc nunca arrancó
        # (batch mal formado). La vista lo separa de los candidatos reales y le oculta
        # el botón de pérdida (requiere conciliación antes de decidir). Solo lectura.
        cuota_inicial_pagada = bool(f.cuota_inicial_pagada)
        # Tanda 13: si el colegiado tiene OTRO plan activo (p. ej. uno del lote migrado por la misma deuda),
        # no es operable: requiere conciliación.
        otro_activo = any(g.colegiado_id == f.colegiado_id and g.id != f.id for g in fraccs)
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
            "lote_migrado":         not es_sano,
            "otro_plan_activo":     otro_activo,
            # Operable = se puede decidir la pérdida: cronograma real, cuota inicial pagada y plan único.
            "operable":             es_sano and cuota_inicial_pagada and not otro_activo,
        })

    # Tanda 13: primero los operables; después los que requieren conciliación.
    candidatos.sort(key=lambda c: (0 if c["operable"] else 1, -c["consecutivas_impagas"], -c["saldo_pendiente"]))

    # ── rama AUTOMÁTICA (apagada por el parámetro; hoy nunca entra) ──
    ejecutados = []
    if ejecutar and auto:
        for c in [x for x in candidatos if x["operable"]]:   # tanda 13: nunca el lote ni los no operables
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

    total_contaminados = sum(1 for c in candidatos if c["contaminado"] and not c["lote_migrado"])
    total_lote = sum(1 for c in candidatos if c["lote_migrado"])
    return {
        "modo":               "AUTOMATICO" if auto else "MANUAL",
        "perdida_automatica": auto,
        "solo_sanos":         solo_sanos,
        "umbral_cuotas":      umbral,
        "fecha":              hoy.isoformat(),
        "total_activos":      len(fraccs),
        "total_operables":    total_operables,   # sanos evaluados (si solo_sanos)
        "total_candidatos":   len(candidatos),
        "total_reales":       sum(1 for c in candidatos if c["operable"]),   # operables: se puede decidir
        "total_contaminados": total_contaminados,                     # cuota inicial impaga (cronograma real)
        "total_lote":         total_lote,                             # lote migrado (requiere conciliación)
        "candidatos":         candidatos,
        "ejecutados":         ejecutados,
    }


# ════════════════════════════════════════════════════════════════════════════
# PÉRDIDA — UNA SOLA DEUDA (tanda 12, decisión de Duilio)
#   · las deudas originales y las cuotas impagas del plan se CIERRAN (gestión
#     'reemplazada', saldo 0, con nota): no queda ninguna cuota por exigir;
#   · nace UNA deuda "Saldo por pérdida de fraccionamiento FRACC-AAAA-NNNN" por lo que
#     quedaba por pagar (debt_type 'saldo_perdida_fraccionamiento');
#   · lo ya pagado NO se toca (cuotas pagadas y sus pagos quedan como están);
#   · el colegiado pierde la habilidad (el motor del paquete del 2-dic trata esa deuda
#     como inhabilitante; además se deja inhábil explícitamente).
# ════════════════════════════════════════════════════════════════════════════
TIPO_DEUDA_PERDIDA = "saldo_perdida_fraccionamiento"


def _datos_perdida(db: Session, fracc_id: int, bloquear: bool = False):
    lock = " FOR UPDATE" if bloquear else ""
    fr = db.execute(text("""
        SELECT f.id, f.numero_solicitud, f.colegiado_id, f.organization_id, f.estado, f.deuda_total_original,
               f.saldo_pendiente, c.codigo_matricula mat, c.apellidos_nombres nombre, c.condicion, c.member_id,
               (SELECT count(DISTINCT q.fecha_vencimiento) FROM fraccionamiento_cuotas q
                 WHERE q.fraccionamiento_id = f.id AND q.fecha_vencimiento IS NOT NULL) distinct_venc
        FROM fraccionamientos f JOIN colegiados c ON c.id = f.colegiado_id
        WHERE f.id = :fid""" + (" FOR UPDATE OF f" if bloquear else "")), {"fid": fracc_id}).fetchone()
    if not fr:
        raise FraccPerdidoError(404, "Fraccionamiento no encontrado")
    originales = db.execute(text("""
        SELECT id, concept, periodo, amount, balance, status, estado_gestion
        FROM debts
        WHERE (fraccionamiento_id_origen = :fid)
           OR (fraccionamiento_id = :fid AND coalesce(debt_type, '') <> 'fraccionamiento' AND estado_gestion = 'fraccionada')
        ORDER BY periodo NULLS LAST, id""" + lock), {"fid": fracc_id}).fetchall()
    cuotas = db.execute(text("""
        SELECT q.id, q.numero_cuota, q.monto, q.fecha_vencimiento, coalesce(q.pagada, FALSE) pagada, q.debt_id,
               d.balance d_balance, d.status d_status
        FROM fraccionamiento_cuotas q LEFT JOIN debts d ON d.id = q.debt_id
        WHERE q.fraccionamiento_id = :fid ORDER BY q.numero_cuota"""), {"fid": fracc_id}).fetchall()
    hoy = _hoy_peru()
    pagado, impagas = 0.0, []
    for q in cuotas:
        if q.pagada:
            pagado += float(q.monto or 0)
            continue
        if q.debt_id is not None and q.d_status in ("pending", "partial"):
            pend = float(q.d_balance or 0)
            pagado += float(q.monto or 0) - pend          # abono parcial ya hecho
        elif q.debt_id is not None:
            pend = 0.0                                     # espejo ya cerrado/pagado
        else:
            pend = float(q.monto or 0)                     # plan antiguo sin espejo
        impagas.append({"cuota_id": q.id, "numero": q.numero_cuota, "vence": q.fecha_vencimiento,
                        "pendiente": round(pend, 2), "vencida": bool(q.fecha_vencimiento and q.fecha_vencimiento < hoy),
                        "debt_id": q.debt_id})
    saldo = round(sum(x["pendiente"] for x in impagas), 2)
    return fr, originales, impagas, round(pagado, 2), saldo


def _validar(fr, originales, saldo):
    if fr.estado == "perdido":
        raise FraccPerdidoError(409, "Este fraccionamiento ya está marcado como perdido")
    if fr.estado != "activo":
        raise FraccPerdidoError(409, f"Este fraccionamiento está {fr.estado}; solo se puede declarar pérdida de un plan activo")
    if not originales:
        raise FraccPerdidoError(409,
            "Este fraccionamiento no tiene sus deudas originales enlazadas (plan del lote migrado). "
            "No se puede declarar la pérdida sin antes conciliar la deuda del colegiado.")
    if saldo <= 0.005:
        raise FraccPerdidoError(409, "Este plan no tiene saldo por pagar: no hay pérdida que declarar.")
    if getattr(fr, "distinct_venc", 2) is not None and getattr(fr, "distinct_venc", 2) <= 1:
        raise FraccPerdidoError(409, "Este plan es del lote migrado (todas sus cuotas con un mismo vencimiento): "
                                     "requiere conciliación antes de decidir su pérdida.")


def previsualizar_perdida(db: Session, fracc_id: int) -> dict:
    """Solo lectura: qué pasaría al declarar la pérdida. Mismo cálculo que el core."""
    fr, originales, impagas, pagado, saldo = _datos_perdida(db, fracc_id)
    adv, puede = [], True
    try:
        _validar(fr, originales, saldo)
    except FraccPerdidoError as e:
        adv.append(e.detail)
        puede = False
    if abs(float(fr.saldo_pendiente or 0) - saldo) > 0.01:
        adv.append("El saldo del plan (S/ %.2f) no coincide con sus cuotas impagas (S/ %.2f): la deuda nueva se crea por las cuotas impagas."
                   % (float(fr.saldo_pendiente or 0), saldo))
    return {
        "fracc_id": fr.id, "numero_solicitud": fr.numero_solicitud,
        "colegiado": {"id": fr.colegiado_id, "matricula": fr.mat, "nombre": fr.nombre, "condicion": fr.condicion},
        "total_plan": round(float(fr.deuda_total_original or 0), 2),
        "ya_pagado": pagado,
        "cuotas_impagas": [{**x, "vence": x["vence"].isoformat() if x["vence"] else None} for x in impagas],
        "cuotas_vencidas": sum(1 for x in impagas if x["vencida"]),
        "originales": {"cantidad": len(originales), "monto": round(sum(float(o.amount or 0) for o in originales), 2)},
        "deuda_nueva": {"concepto": "Saldo por pérdida de fraccionamiento %s" % fr.numero_solicitud, "monto": saldo},
        "condicion_despues": "inhabil",
        "puede_declarar": puede, "advertencias": adv,
    }


def marcar_fracc_perdido_core(
    db: Session,
    fracc_id: int,
    motivo: str,
    user_id,
    reevaluar_habilidad: bool = True,
) -> dict:
    """Declara la pérdida (una sola deuda). Atómico: hace commit al final o nada."""
    fr, originales, impagas, pagado, saldo = _datos_perdida(db, fracc_id, bloquear=True)
    _validar(fr, originales, saldo)
    ahora = datetime.now(PERU_TZ)
    sello = "[FRACC-PERDIDO %s user%s %s]" % (fr.numero_solicitud, user_id, ahora.strftime("%d/%m/%Y %H:%M"))
    concepto = "Saldo por pérdida de fraccionamiento %s" % fr.numero_solicitud
    salto = chr(10)
    try:
        # 1) Cerrar las deudas originales (quedan como historial, enlazadas al plan).
        for o in originales:
            db.execute(text("""
                UPDATE debts SET balance = 0, status = 'cancelled', estado_gestion = 'reemplazada',
                       fraccionamiento_id_origen = :fid, fraccionamiento_id = NULL, updated_at = NOW(),
                       notes = COALESCE(notes,'') || :nota
                WHERE id = :did AND status IN ('pending','partial')"""), {"did": o.id, "fid": fracc_id,
                                     "nota": salto + "%s Cerrada: reemplazada por «%s»." % (sello, concepto)})
        # 2) Cerrar las cuotas impagas (sus deudas espejo). Las pagadas no se tocan.
        cerradas = []
        for x in impagas:
            if x["debt_id"]:
                db.execute(text("""
                    UPDATE debts SET balance = 0, status = 'cancelled', estado_gestion = 'reemplazada', updated_at = NOW(),
                           notes = COALESCE(notes,'') || :nota
                    WHERE id = :did AND debt_type = 'fraccionamiento' AND status IN ('pending','partial')"""),
                           {"did": x["debt_id"], "nota": salto + "%s Cuota cerrada por pérdida del plan." % sello})
            cerradas.append(x["numero"])
        # 2b) Tanda 13: planes antiguos tienen las cuotas SIN enlace a su deuda espejo (debt_id vacío);
        #     sus espejos se ubican por el plan. Sin esto quedaban pendientes y Caja los seguía
        #     ofreciendo junto a la deuda nueva (doble cobro). Las pagadas no se tocan.
        db.execute(text("""
            UPDATE debts SET balance = 0, status = 'cancelled', estado_gestion = 'reemplazada', updated_at = NOW(),
                   notes = COALESCE(notes,'') || :nota
            WHERE fraccionamiento_id = :fid AND debt_type = 'fraccionamiento' AND status IN ('pending','partial')"""),
                   {"fid": fracc_id, "nota": salto + "%s Cuota cerrada por pérdida del plan." % sello})
        # 3) Una sola deuda por lo que quedaba por pagar.
        nueva_id = db.execute(text("""
            INSERT INTO debts (organization_id, colegiado_id, member_id, concept, periodo, period_label, debt_type,
                               amount, balance, status, estado_gestion, fecha_generacion, due_date, origen,
                               fraccionamiento_id_origen, created_by, created_at, notes)
            VALUES (:o, :c, :m, :con, :per, :etq, :tipo, :s, :s, 'pending', 'vigente', :hoy, :ahora,
                    'perdida_fraccionamiento', :fid, :u, NOW(), :nota)
            RETURNING id"""), {"o": fr.organization_id, "c": fr.colegiado_id, "m": fr.member_id, "con": concepto, "etq": ("Pérdida %s" % fr.numero_solicitud)[:50],
                               "per": ahora.strftime("%Y-%m"), "tipo": TIPO_DEUDA_PERDIDA, "s": saldo, "hoy": ahora.date(),
                               "ahora": ahora, "fid": fracc_id, "u": user_id,
                               "nota": "%s Motivo: %s. Ya pagado al plan: S/ %.2f." % (sello, motivo[:200], pagado)}).scalar()
        db.execute(text("""INSERT INTO debt_actions (organization_id, debt_id, fraccionamiento_id, tipo, descripcion, monto_afectado,
                             balance_anterior, balance_nuevo, estado_gestion_nuevo, created_by, created_at)
                           VALUES (:o, :d, :f, 'perdida_fraccionamiento', :ds, :s, 0, :s, 'vigente', :u, NOW())"""),
                   {"o": fr.organization_id, "d": nueva_id, "f": fracc_id, "s": saldo, "u": user_id,
                    "ds": ("Pérdida de %s: se cierran %d deudas originales y %d cuotas impagas; nace esta deuda por S/ %.2f. "
                           "Motivo: %s" % (fr.numero_solicitud, len(originales), len(cerradas), saldo, motivo))[:500]})
        # 4) El plan queda perdido, sin saldo propio (lo debe la deuda nueva).
        db.execute(text("""UPDATE fraccionamientos SET estado = 'perdido', saldo_pendiente = 0, fecha_perdida = NOW(),
                             motivo_perdida = :motivo, updated_at = NOW() WHERE id = :fid"""), {"motivo": motivo, "fid": fracc_id})
        from app.services.politicas_financieras import refrescar_flag_fraccionamiento
        db.flush()
        refrescar_flag_fraccionamiento(db, fr.colegiado_id)
        # 5) Habilidad: el motor (paquete 2-dic) trata la deuda nueva como inhabilitante.
        reevaluacion = None
        if reevaluar_habilidad:
            from app.models import Colegiado
            from app.services.evaluar_habilidad import sincronizar_condicion
            col = db.query(Colegiado).filter(Colegiado.id == fr.colegiado_id).first()
            if col is not None and col.condicion not in ("vitalicio", "fallecido", "retirado"):
                previa = col.condicion
                sincronizar_condicion(db, col, {"id": fr.organization_id, "config": {}})
                if col.condicion != "inhabil":
                    # Motor sin la regla de pérdida (versión anterior al paquete): se deja inhábil explícitamente.
                    col.condicion = "inhabil"
                    col.motivo_inhabilidad = "Saldo por pérdida de fraccionamiento impago"
                    col.fecha_actualizacion_condicion = ahora
                reevaluacion = {"condicion_previa": previa, "condicion_nueva": col.condicion,
                                "cambio": previa != col.condicion, "motivo": col.motivo_inhabilidad}
        db.commit()
    except Exception:
        db.rollback()
        raise
    logger.info("Fracc %s PERDIDO por user=%s: %d originales y %d cuotas cerradas; deuda %s por S/ %.2f",
                fracc_id, user_id, len(originales), len(cerradas), nueva_id, saldo)
    return {"ok": True, "fracc_id": fracc_id, "numero_solicitud": fr.numero_solicitud,
            "originales_cerradas": [o.id for o in originales], "cuotas_cerradas": cerradas,
            "deuda_perdida_id": nueva_id, "monto_deuda_perdida": saldo, "ya_pagado": pagado,
            "reevaluacion_habilidad": reevaluacion}

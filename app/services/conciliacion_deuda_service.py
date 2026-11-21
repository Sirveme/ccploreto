"""
app/services/conciliacion_deuda_service.py
Conciliación de deuda por ACTA con firmas.

Un acta FIJA la deuda total de un colegiado en un monto sustentado. Nunca toca
pagos ni comprobantes: solo deudas. Todo queda escrito en el acta (quién, cuándo,
por qué, qué deudas se tocaron y cómo quedó la habilidad).

Requisito previo:
  ⚠️ sql/zClaude-conciliacion.sql (tablas actas_conciliacion y acta_firmas, y la
     sección 'conciliacion' de parametros_sistema).

═══ DEUDA TOTAL ÚNICA: por qué esta y no otra ═══════════════════════════════
En el sistema hay unas 25 consultas que calculan "la deuda" de un colegiado, en
7 familias, y pueden dar montos distintos para la misma persona (unas suman
`amount` y otras `balance`; unas incluyen lo fraccionado y otras no; unas suman
el saldo del plan y otras las cuotas espejo).

`deuda_total_colegiado` usa `deuda_cuotas_service.calcular_deuda_total` porque:
  1. Es la que alimenta al MOTOR DE HABILIDAD (evaluar_habilidad.sincronizar_condicion
     la lee a través de pagos_publicos.calcular_deuda_total). El criterio del Colegio
     es "cuánto debe y si está hábil": acta, pantalla y motor deben ver el mismo número.
  2. Usa `balance` (lo que falta pagar), no `amount` (el monto original).
  3. No cuenta doble: excluye las deudas 'fraccionada' y suma el saldo del plan
     activo una sola vez.
  4. Es la que ve el colegiado en el pago público y en el portal.
Por ahora SOLO la usa la conciliación; las demás consultas no se reemplazan.

Estilo: SQL con text() (igual que parametros_service) — las tablas nuevas no se
mapean en el ORM a propósito, para que un deploy sin el SQL no rompa otras pantallas.
"""
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

TZ_PERU = timezone(timedelta(hours=-5))
ROLES_POSIBLES = ("decano", "admin", "tesorero")      # sote NUNCA firma dinero
ROLES_POR_DEFECTO = "decano,admin,tesorero"
FIRMAS_POR_DEFECTO = 2
TOLERANCIA = 0.005


class ErrorConciliacion(Exception):
    """Error de negocio con código HTTP sugerido."""
    def __init__(self, mensaje, codigo=400):
        super().__init__(mensaje)
        self.mensaje, self.codigo = mensaje, codigo


def _r2(x):
    return round(float(x or 0) + 0.0, 2)


# ════════════════════════════════════════════════════════════════════════════
# B1. Deuda total única
# ════════════════════════════════════════════════════════════════════════════
def _detalle_deuda(db: Session, colegiado_id: int, organization_id: int = 1) -> dict:
    """Deuda total y las deudas exactas que la componen (mismo cálculo que la habilidad)."""
    from app.services.deuda_cuotas_service import calcular_deuda_total
    r = calcular_deuda_total(colegiado_id, organization_id, db)
    ids = [p["debt_id"] for p in (r.get("cuotas") or {}).get("periodos_pendientes", []) if p.get("debt_id")]
    ids += [o["id"] for o in r.get("obligaciones") or []]
    return {
        "total": _r2(r["resumen"]["deuda_total"]),
        "deuda_ids": ids,
        "plan_activo": r.get("fraccionamiento"),
    }


def deuda_total_colegiado(db: Session, colegiado_id: int, organization_id: int = 1) -> float:
    """LA deuda total de un colegiado: la misma cifra que usa el motor de habilidad."""
    return _detalle_deuda(db, colegiado_id, organization_id)["total"]


def deuda_total_padron(db: Session, organization_id: int = 1) -> dict:
    """Suma de `deuda_total_colegiado` sobre TODO el padrón, en una sola consulta.

    Aplica las mismas reglas que `deuda_cuotas_service.calcular_deuda_total`:
      - deudas 'pending'/'partial' con gestión 'vigente'/'en_cobranza', por su saldo;
      - las cuotas ordinarias solo cuentan si tienen periodo válido y si la condición
        del colegiado no es exenta (preset activo; por defecto fallecido/retirado/vitalicio);
      - más el saldo de UN plan activo por colegiado.
    Llamar a la función individual 2 500 veces tardaría decenas de segundos; esta
    consulta da el mismo total (la equivalencia se prueba en tests/escenarios).
    """
    from app.services.deuda_cuotas_service import _condiciones_sin_deuda_computable
    exentas = sorted(_condiciones_sin_deuda_computable(db, organization_id))
    r = db.execute(text("""
        WITH d AS (
            SELECT d.colegiado_id, sum(d.balance) AS s
            FROM debts d JOIN colegiados c ON c.id = d.colegiado_id
            WHERE d.organization_id = :org AND c.organization_id = :org
              AND d.status IN ('pending', 'partial') AND d.estado_gestion IN ('vigente', 'en_cobranza')
              AND (coalesce(d.debt_type, '') <> 'cuota_ordinaria'
                   OR (d.periodo ~ '^[0-9]{4}' AND NOT (coalesce(c.condicion, 'habil') = ANY(:exentas))))
            GROUP BY d.colegiado_id),
        f AS (
            SELECT DISTINCT ON (colegiado_id) colegiado_id, saldo_pendiente AS s
            FROM fraccionamientos WHERE organization_id = :org AND estado = 'activo'
            ORDER BY colegiado_id, id),
        t AS (
            SELECT c.id, coalesce(d.s, 0) + coalesce(f.s, 0) AS deuda
            FROM colegiados c LEFT JOIN d ON d.colegiado_id = c.id LEFT JOIN f ON f.colegiado_id = c.id
            WHERE c.organization_id = :org)
        SELECT coalesce(sum(deuda), 0) AS total, count(*) FILTER (WHERE deuda > 0.005) AS con_deuda FROM t
    """), {"org": organization_id, "exentas": exentas}).fetchone()
    return {"total": _r2(r.total), "colegiados_con_deuda": int(r.con_deuda or 0)}


# ════════════════════════════════════════════════════════════════════════════
# B2. Parámetros
# ════════════════════════════════════════════════════════════════════════════
def normalizar_roles(valor) -> list:
    """'decano, admin' -> ['decano','admin'] (solo roles permitidos, sin repetir, sin sote)."""
    out = []
    for r in str(valor or "").replace(";", ",").split(","):
        r = r.strip().lower()
        if r in ROLES_POSIBLES and r not in out:
            out.append(r)
    return out


def get_config(db: Session, org_id: int = 1) -> dict:
    from app.services import parametros_service as PS
    try:
        firmas = int(PS.get_param(db, "conciliacion", "firmas_requeridas", org_id=org_id, default=FIRMAS_POR_DEFECTO))
        roles = normalizar_roles(PS.get_param(db, "conciliacion", "roles_firmantes", org_id=org_id, default=ROLES_POR_DEFECTO))
    except Exception:
        firmas, roles = FIRMAS_POR_DEFECTO, normalizar_roles(ROLES_POR_DEFECTO)
    firmas = min(3, max(1, firmas))
    if not roles:
        roles = normalizar_roles(ROLES_POR_DEFECTO)
    return {"firmas_requeridas": firmas, "roles_firmantes": roles}


def validar_parametro(db: Session, clave: str, valor, org_id: int = 1):
    """Valida un cambio de la sección 'conciliacion' ANTES de guardarlo. Devuelve el valor limpio."""
    cfg = get_config(db, org_id)
    if clave == "firmas_requeridas":
        try:
            n = float(valor)
        except (TypeError, ValueError):
            raise ValueError("Las firmas requeridas deben ser 1, 2 o 3.")
        if n not in (1, 2, 3):
            raise ValueError("Las firmas requeridas deben ser 1, 2 o 3.")
        if int(n) > len(cfg["roles_firmantes"]):
            raise ValueError("No se pueden pedir %d firmas con solo %d rol(es) firmante(s): cada firma es de un rol distinto."
                             % (int(n), len(cfg["roles_firmantes"])))
        return int(n)
    if clave == "roles_firmantes":
        if "sote" in str(valor or "").lower():
            raise ValueError("El rol sote nunca firma movimientos de dinero.")
        roles = normalizar_roles(valor)
        if not roles:
            raise ValueError("Debe quedar al menos un rol firmante (decano, admin o tesorero).")
        if len(roles) < cfg["firmas_requeridas"]:
            raise ValueError("Hay %d firmas requeridas: se necesitan al menos %d roles firmantes."
                             % (cfg["firmas_requeridas"], cfg["firmas_requeridas"]))
        return ",".join(roles)
    raise ValueError("Parámetro de conciliación desconocido: %s" % clave)


# ════════════════════════════════════════════════════════════════════════════
# Núcleo: aplicar el ajuste sobre las deudas (sin commit)
# ════════════════════════════════════════════════════════════════════════════
def _deudas_ordenadas(db: Session, ids: list) -> list:
    if not ids:
        return []
    return db.execute(text("""
        SELECT id, concept, periodo, debt_type, amount, balance, status, due_date
        FROM debts WHERE id = ANY(:ids)
        -- "Más antigua" = por PERIODO (año o año-mes de la obligación). El vencimiento
        -- solo desempata: en la data migrada hay deudas viejas con vencimiento reciente.
        -- OJO: el grupo es NO capturante (?:...). Con un grupo capturante, substring()
        -- devuelve solo el grupo ('-08') y ordenaría por mes ignorando el año.
        ORDER BY coalesce(substring(periodo from '^[0-9]{4}(?:-[0-9]{2})?'), to_char(due_date, 'YYYY-MM'), '9999') ASC,
                 due_date ASC NULLS LAST, id ASC
        FOR UPDATE
    """), {"ids": ids}).fetchall()


def _aplicar(db: Session, colegiado, det: dict, monto_fijado: float, etiqueta: str, user_id=None) -> dict:
    """Lleva la deuda a `monto_fijado`. Devuelve el detalle de lo tocado. NO hace commit.

    A la baja: anula de la más antigua a la más nueva; la última puede quedar parcial.
    Al alza:   crea UNA deuda 'Ajuste por conciliación — <etiqueta>'.
    Nunca toca pagos ni comprobantes.
    """
    actual = det["total"]
    diferencia = _r2(monto_fijado - actual)
    tocadas, ajuste_id = [], None
    ahora = datetime.now(TZ_PERU)

    if diferencia < -TOLERANCIA:
        restante = _r2(-diferencia)
        for d in _deudas_ordenadas(db, det["deuda_ids"]):
            if restante <= TOLERANCIA:
                break
            saldo = _r2(d.balance)
            if saldo <= TOLERANCIA:
                continue
            fila = {"deuda_id": d.id, "concepto": d.concept, "periodo": d.periodo, "tipo": d.debt_type,
                    "saldo_antes": saldo, "estado_antes": d.status}
            if restante >= saldo - TOLERANCIA:
                db.execute(text("""
                    UPDATE debts SET balance = 0, status = 'annulled', estado_gestion = 'anulada',
                           motivo_anulacion = :mot, anulada_at = :ahora, updated_at = :ahora,
                           notes = coalesce(notes || E'\\n', '') || :nota
                    WHERE id = :id
                """), {"id": d.id, "ahora": ahora, "mot": "Conciliación de deuda — %s" % etiqueta,
                       "nota": "[%s] Anulada por conciliación (saldo %.2f)" % (etiqueta, saldo)})
                fila.update(saldo_despues=0.0, estado_despues="annulled", accion="anulada")
                restante = _r2(restante - saldo)
            else:
                nuevo = _r2(saldo - restante)
                db.execute(text("""
                    UPDATE debts SET balance = :nuevo, status = 'partial', updated_at = :ahora,
                           notes = coalesce(notes || E'\\n', '') || :nota
                    WHERE id = :id
                """), {"id": d.id, "nuevo": nuevo, "ahora": ahora,
                       "nota": "[%s] Saldo ajustado por conciliación: %.2f → %.2f" % (etiqueta, saldo, nuevo)})
                fila.update(saldo_despues=nuevo, estado_despues="partial", accion="saldo_reducido")
                restante = 0.0
            tocadas.append(fila)
        if restante > TOLERANCIA:
            raise ErrorConciliacion("No hay deudas suficientes para bajar S/ %.2f (faltó S/ %.2f)." % (-diferencia, restante), 409)

    elif diferencia > TOLERANCIA:
        concepto = "Ajuste por conciliación — %s" % etiqueta
        ajuste_id = db.execute(text("""
            INSERT INTO debts (organization_id, colegiado_id, concept, periodo, period_label, debt_type,
                               amount, balance, status, estado_gestion, fecha_generacion, due_date,
                               estado_notificacion, acuse_recibo, origen, notes, created_at, created_by)
            VALUES (:org, :col, :concepto, :periodo, :label, 'ajuste_conciliacion',
                    :monto, :monto, 'pending', 'vigente', :hoy, :ahora,
                    'no_notificada', FALSE, 'conciliacion', :nota, :ahora, :por)
            RETURNING id
        """), {"org": colegiado.organization_id, "col": colegiado.id, "concepto": concepto,
               "periodo": ahora.strftime("%Y-%m"), "label": "Ajuste %s" % etiqueta, "monto": diferencia,
               "hoy": ahora.date(), "ahora": ahora, "por": user_id,
               "nota": "[%s] Deuda creada por conciliación al alza" % etiqueta}).scalar()
        tocadas.append({"deuda_id": ajuste_id, "concepto": concepto, "periodo": ahora.strftime("%Y-%m"),
                        "tipo": "ajuste_conciliacion", "saldo_antes": 0.0, "estado_antes": None,
                        "saldo_despues": diferencia, "estado_despues": "pending", "accion": "creada"})

    db.flush()
    db.expire_all()

    # Re-evaluar la habilidad con el motor oficial (puede subir o bajar).
    from app.services.evaluar_habilidad import sincronizar_condicion
    condicion_antes = colegiado.condicion
    sincronizar_condicion(db, colegiado, {"id": colegiado.organization_id, "config": {}})
    db.flush()
    condicion_despues = colegiado.condicion

    despues = deuda_total_colegiado(db, colegiado.id, colegiado.organization_id)
    if abs(despues - _r2(monto_fijado)) > 0.011:
        raise ErrorConciliacion("El ajuste no dejó la deuda en el monto fijado (quedó S/ %.2f). No se aplicó nada." % despues, 409)

    return {"deudas": tocadas, "debt_ajuste_id": ajuste_id, "deuda_antes": actual, "deuda_despues": despues,
            "condicion_antes": condicion_antes, "condicion_despues": condicion_despues}


def _colegiado(db: Session, colegiado_id: int):
    from app.models import Colegiado
    col = db.query(Colegiado).filter(Colegiado.id == colegiado_id).first()
    if not col:
        raise ErrorConciliacion("Colegiado no encontrado.", 404)
    return col


def _validar_conciliable(det: dict, monto_fijado: float):
    if det["plan_activo"]:
        raise ErrorConciliacion(
            "Este colegiado tiene un plan de fraccionamiento activo. La conciliación con plan activo "
            "todavía no está disponible: primero complete, refinancie o cierre el plan.", 409)
    if monto_fijado is None or float(monto_fijado) < 0:
        raise ErrorConciliacion("El monto fijado no puede ser negativo.")
    if abs(_r2(monto_fijado) - det["total"]) <= TOLERANCIA:
        raise ErrorConciliacion("El monto fijado es igual a la deuda actual (S/ %.2f): no hay nada que conciliar." % det["total"])


# ════════════════════════════════════════════════════════════════════════════
# B4. Vista previa (solo lectura: aplica dentro de un savepoint y lo deshace)
# ════════════════════════════════════════════════════════════════════════════
def previsualizar(db: Session, colegiado_id: int, monto_fijado: float) -> dict:
    col = _colegiado(db, colegiado_id)
    det = _detalle_deuda(db, col.id, col.organization_id)
    base = {"colegiado_id": col.id, "nombre": col.apellidos_nombres, "matricula": col.codigo_matricula,
            "deuda_actual": det["total"], "condicion_actual": col.condicion,
            "tiene_plan_activo": bool(det["plan_activo"])}
    _validar_conciliable(det, monto_fijado)
    sp = db.begin_nested()
    try:
        r = _aplicar(db, col, det, float(monto_fijado), "vista previa")
    finally:
        sp.rollback()
        db.expire_all()
    base.update({
        "monto_fijado": _r2(monto_fijado), "diferencia": _r2(float(monto_fijado) - det["total"]),
        "sentido": "baja" if float(monto_fijado) < det["total"] else "alza",
        "deudas": r["deudas"], "deuda_despues": r["deuda_despues"],
        "condicion_antes": r["condicion_antes"], "condicion_despues": r["condicion_despues"],
        "cambia_condicion": r["condicion_antes"] != r["condicion_despues"],
    })
    return base


# ════════════════════════════════════════════════════════════════════════════
# Actas
# ════════════════════════════════════════════════════════════════════════════
def _siguiente_numero(db: Session, org_id: int) -> str:
    anio = datetime.now(TZ_PERU).year
    n = db.execute(text("""
        SELECT coalesce(max(substring(numero from '([0-9]+)$')::int), 0) + 1
        FROM actas_conciliacion WHERE organization_id = :o AND numero LIKE :p
    """), {"o": org_id, "p": "ACTA-%d-%%" % anio}).scalar()
    return "ACTA-%d-%04d" % (anio, n)


def _exigir_firmante(member, roles: list):
    rol = (member.role or "").lower()
    if rol == "sote":
        raise ErrorConciliacion("El rol sote no firma movimientos de dinero.", 403)
    if rol not in roles:
        raise ErrorConciliacion("Tu rol (%s) no está entre los firmantes de conciliación (%s)." % (rol, ", ".join(roles)), 403)
    return rol


def _ejecutar(db: Session, acta, user_id) -> dict:
    """Ejecuta un acta ya firmada. Sin commit. Si la deuda cambió, la marca desactualizada."""
    col = _colegiado(db, acta.colegiado_id)
    det = _detalle_deuda(db, col.id, col.organization_id)
    ahora = datetime.now(TZ_PERU)
    motivo_no = None
    if det["plan_activo"]:
        motivo_no = "El colegiado tiene ahora un plan de fraccionamiento activo."
    elif abs(det["total"] - _r2(acta.deuda_anterior)) > TOLERANCIA:
        motivo_no = ("La deuda cambió desde que se propuso el acta: era S/ %.2f y ahora es S/ %.2f."
                     % (float(acta.deuda_anterior), det["total"]))
    if motivo_no:
        db.execute(text("""UPDATE actas_conciliacion SET estado='desactualizada', motivo_cierre=:m,
                           deuda_al_ejecutar=:d, cerrada_at=:a WHERE id=:id"""),
                   {"m": motivo_no, "d": det["total"], "a": ahora, "id": acta.id})
        return {"estado": "desactualizada", "mensaje": motivo_no + " El acta no se ejecutó; hay que crear una nueva."}

    r = _aplicar(db, col, det, float(acta.monto_fijado), acta.numero, user_id=user_id)
    db.execute(text("""
        UPDATE actas_conciliacion SET estado='ejecutada', detalle_ejecutado=CAST(:det AS jsonb),
               condicion_despues=:cd, deuda_al_ejecutar=:dae, deuda_despues=:dd, debt_ajuste_id=:aj, cerrada_at=:a
        WHERE id=:id
    """), {"det": json.dumps(r["deudas"], ensure_ascii=False, default=str), "cd": r["condicion_despues"],
           "dae": r["deuda_antes"], "dd": r["deuda_despues"], "aj": r["debt_ajuste_id"], "a": ahora, "id": acta.id})
    return {"estado": "ejecutada", "deuda_despues": r["deuda_despues"], "condicion_despues": r["condicion_despues"],
            "mensaje": "Acta %s ejecutada: la deuda quedó en S/ %.2f." % (acta.numero, r["deuda_despues"])}


def crear_acta(db: Session, member, colegiado_id: int, monto_fijado: float, motivo: str, documento_url=None) -> dict:
    """Crea el acta (cuenta como primera firma). Si basta una firma, se ejecuta de inmediato."""
    cfg = get_config(db, member.organization_id or 1)
    rol = _exigir_firmante(member, cfg["roles_firmantes"])
    motivo = (motivo or "").strip()
    if len(motivo) < 10:
        raise ErrorConciliacion("El motivo es obligatorio (mínimo 10 caracteres).")
    try:
        col = _colegiado(db, colegiado_id)
        det = _detalle_deuda(db, col.id, col.organization_id)
        _validar_conciliable(det, monto_fijado)
        if db.execute(text("SELECT 1 FROM actas_conciliacion WHERE colegiado_id=:c AND estado='pendiente'"),
                      {"c": col.id}).fetchone():
            raise ErrorConciliacion("Este colegiado ya tiene un acta pendiente de firma.", 409)

        # Vista previa guardada en el acta (se calcula y se deshace)
        sp = db.begin_nested()
        try:
            prev = _aplicar(db, col, det, float(monto_fijado), "vista previa")
        finally:
            sp.rollback()
            db.expire_all()
        col = _colegiado(db, colegiado_id)

        numero = _siguiente_numero(db, col.organization_id)
        fijado = _r2(monto_fijado)
        acta_id = db.execute(text("""
            INSERT INTO actas_conciliacion
              (organization_id, colegiado_id, numero, deuda_anterior, monto_fijado, diferencia, sentido,
               motivo, documento_url, firmas_requeridas, roles_firmantes, detalle_previsto,
               condicion_antes, condicion_prevista, estado, creado_por)
            VALUES (:org, :col, :num, :ant, :fij, :dif, :sen, :mot, :doc, :fr, :rf, CAST(:det AS jsonb),
                    :ca, :cp, 'pendiente', :por)
            RETURNING id
        """), {"org": col.organization_id, "col": col.id, "num": numero, "ant": det["total"], "fij": fijado,
               "dif": _r2(fijado - det["total"]), "sen": "baja" if fijado < det["total"] else "alza",
               "mot": motivo, "doc": documento_url, "fr": cfg["firmas_requeridas"],
               "rf": ",".join(cfg["roles_firmantes"]),
               "det": json.dumps(prev["deudas"], ensure_ascii=False, default=str),
               "ca": prev["condicion_antes"], "cp": prev["condicion_despues"], "por": member.id}).scalar()
        db.execute(text("""INSERT INTO acta_firmas (acta_id, member_id, rol, decision, comentario)
                           VALUES (:a, :m, :r, 'aprobar', 'Crea el acta')"""), {"a": acta_id, "m": member.id, "r": rol})

        res = {"estado": "pendiente", "mensaje": "Acta %s creada. Firmas: 1 de %d." % (numero, cfg["firmas_requeridas"])}
        if cfg["firmas_requeridas"] <= 1:
            acta = db.execute(text("SELECT * FROM actas_conciliacion WHERE id=:i FOR UPDATE"), {"i": acta_id}).fetchone()
            res = _ejecutar(db, acta, getattr(member, "user_id", None))
        db.commit()
        logger.info("[conciliacion] %s creada por member %s (%s) → %s", numero, member.id, rol, res["estado"])
        return {"ok": True, "acta_id": acta_id, "numero": numero, **res}
    except Exception:
        db.rollback()
        raise


def firmar_acta(db: Session, member, acta_id: int, decision: str, comentario: str = None) -> dict:
    """Firma (aprobar/rechazar). Persona y rol distintos de las firmas previas."""
    decision = (decision or "").strip().lower()
    if decision not in ("aprobar", "rechazar"):
        raise ErrorConciliacion("La decisión debe ser 'aprobar' o 'rechazar'.")
    comentario = (comentario or "").strip() or None
    if decision == "rechazar" and not comentario:
        raise ErrorConciliacion("Para rechazar hay que escribir el motivo.")
    try:
        acta = db.execute(text("SELECT * FROM actas_conciliacion WHERE id=:i FOR UPDATE"), {"i": acta_id}).fetchone()
        if not acta or acta.organization_id != (member.organization_id or acta.organization_id):
            raise ErrorConciliacion("Acta no encontrada.", 404)
        if acta.estado != "pendiente":
            raise ErrorConciliacion("El acta %s ya está %s: no admite más firmas." % (acta.numero, acta.estado), 409)
        rol = _exigir_firmante(member, normalizar_roles(acta.roles_firmantes))
        firmas = db.execute(text("SELECT member_id, rol, decision FROM acta_firmas WHERE acta_id=:a"), {"a": acta_id}).fetchall()
        if any(f.member_id == member.id for f in firmas):
            raise ErrorConciliacion("Ya firmaste esta acta. Cada firma debe ser de una persona distinta.", 409)
        if any(f.rol == rol for f in firmas):
            raise ErrorConciliacion("Ya hay una firma del rol %s. Cada firma debe ser de un rol distinto." % rol, 409)

        db.execute(text("""INSERT INTO acta_firmas (acta_id, member_id, rol, decision, comentario)
                           VALUES (:a, :m, :r, :d, :c)"""),
                   {"a": acta_id, "m": member.id, "r": rol, "d": decision, "c": comentario})
        ahora = datetime.now(TZ_PERU)
        if decision == "rechazar":
            db.execute(text("""UPDATE actas_conciliacion SET estado='rechazada', motivo_cierre=:m, cerrada_at=:a WHERE id=:i"""),
                       {"m": "Rechazada por %s: %s" % (rol, comentario), "a": ahora, "i": acta_id})
            res = {"estado": "rechazada", "mensaje": "Acta %s rechazada. No se tocó ninguna deuda." % acta.numero}
        else:
            aprobadas = sum(1 for f in firmas if f.decision == "aprobar") + 1
            if aprobadas >= acta.firmas_requeridas:
                res = _ejecutar(db, acta, getattr(member, "user_id", None))
            else:
                res = {"estado": "pendiente", "mensaje": "Firma registrada. Firmas: %d de %d." % (aprobadas, acta.firmas_requeridas)}
        db.commit()
        logger.info("[conciliacion] %s: %s por member %s (%s) → %s", acta.numero, decision, member.id, rol, res["estado"])
        return {"ok": True, "acta_id": acta_id, "numero": acta.numero, **res}
    except Exception:
        db.rollback()
        raise


# ── Lecturas para las pantallas ─────────────────────────────────────────────
def _fila_acta(a, firmas, member=None) -> dict:
    aprobadas = [f for f in firmas if f["decision"] == "aprobar"]
    roles = normalizar_roles(a.roles_firmantes)
    puede = False
    if member is not None and a.estado == "pendiente":
        rol = (member.role or "").lower()
        puede = (rol in roles and rol != "sote"
                 and all(f["member_id"] != member.id for f in firmas)
                 and all(f["rol"] != rol for f in firmas))
    return {
        "id": a.id, "numero": a.numero, "estado": a.estado, "colegiado_id": a.colegiado_id,
        "colegiado": a.apellidos_nombres, "matricula": a.codigo_matricula,
        "deuda_anterior": float(a.deuda_anterior), "monto_fijado": float(a.monto_fijado),
        "diferencia": float(a.diferencia), "sentido": a.sentido, "motivo": a.motivo,
        "documento_url": a.documento_url, "firmas_requeridas": a.firmas_requeridas,
        "firmas_aprobadas": len(aprobadas), "roles_firmantes": roles,
        "condicion_antes": a.condicion_antes, "condicion_prevista": a.condicion_prevista,
        "condicion_despues": a.condicion_despues,
        "deuda_despues": float(a.deuda_despues) if a.deuda_despues is not None else None,
        "detalle": a.detalle_ejecutado if a.estado == "ejecutada" else a.detalle_previsto,
        "motivo_cierre": a.motivo_cierre,
        "creada": a.created_at.astimezone(TZ_PERU).strftime("%d/%m/%Y %H:%M") if a.created_at else None,
        "cerrada": a.cerrada_at.astimezone(TZ_PERU).strftime("%d/%m/%Y %H:%M") if a.cerrada_at else None,
        "firmas": [{"nombre": f["nombre"], "rol": f["rol"], "decision": f["decision"], "comentario": f["comentario"],
                    "fecha": f["created_at"].astimezone(TZ_PERU).strftime("%d/%m/%Y %H:%M") if f["created_at"] else None}
                   for f in firmas],
        "puedo_firmar": puede,
    }


def contar_pendientes_mi_firma(db: Session, member) -> int:
    """Actas pendientes que ESTE miembro puede firmar ahora (no firmó y su rol aún no firmó)."""
    rol = (member.role or "").lower()
    if rol == "sote" or rol not in ROLES_POSIBLES:
        return 0
    return int(db.execute(text("""
        SELECT count(*) FROM actas_conciliacion a
        WHERE a.organization_id = :o AND a.estado = 'pendiente'
          AND (',' || a.roles_firmantes || ',') LIKE :rol
          AND NOT EXISTS (SELECT 1 FROM acta_firmas f
                          WHERE f.acta_id = a.id AND (f.member_id = :m OR f.rol = :r))
    """), {"o": member.organization_id or 1, "rol": "%," + rol + ",%", "m": member.id, "r": rol}).scalar() or 0)


def generar_pdf_acta(db: Session, org_id: int, acta_id: int) -> tuple:
    """PDF del acta EJECUTADA. Mismo tema que los comprobantes del Colegio
    (pdf_preview_boleta: azul pizarra #1e293b, gris #f1f5f9, borde #cbd5e1).
    Devuelve (bytes, nombre_de_archivo). Lanza ErrorConciliacion si no aplica."""
    import io
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from xml.sax.saxutils import escape as _esc

    actas = [a for a in listar_actas(db, org_id, estado="todas", limite=300) if a["id"] == acta_id]
    if not actas:
        fila = db.execute(text("SELECT colegiado_id FROM actas_conciliacion WHERE id=:i AND organization_id=:o"),
                          {"i": acta_id, "o": org_id}).fetchone()
        if not fila:
            raise ErrorConciliacion("Acta no encontrada.", 404)
        actas = [a for a in listar_actas(db, org_id, estado="todas", colegiado_id=fila.colegiado_id, limite=300) if a["id"] == acta_id]
    a = actas[0]
    if a["estado"] != "ejecutada":
        raise ErrorConciliacion("El PDF solo está disponible para actas ejecutadas (esta está %s)." % a["estado"], 409)
    org = db.execute(text("SELECT name FROM organizations WHERE id=:o"), {"o": org_id}).fetchone()
    cf = db.execute(text("SELECT ruc, razon_social FROM configuracion_facturacion WHERE organization_id=:o AND activo LIMIT 1"),
                    {"o": org_id}).fetchone()
    nombre_org = (cf.razon_social if cf and cf.razon_social else (org.name if org else "Colegio")).upper()

    AZUL, AZUL_MEDIO = colors.HexColor("#1e293b"), colors.HexColor("#334155")
    GRIS, BORDE = colors.HexColor("#f1f5f9"), colors.HexColor("#cbd5e1")
    st = getSampleStyleSheet()
    H1 = ParagraphStyle("h1", parent=st["Heading1"], fontSize=14, textColor=AZUL, alignment=TA_CENTER, spaceAfter=2)
    SUB = ParagraphStyle("sub", parent=st["Normal"], fontSize=9, textColor=AZUL_MEDIO, alignment=TA_CENTER)
    TIT = ParagraphStyle("tit", parent=st["Normal"], fontSize=13, textColor=AZUL, alignment=TA_CENTER, fontName="Helvetica-Bold")
    LBL = ParagraphStyle("lbl", parent=st["Normal"], fontSize=8, textColor=AZUL_MEDIO)
    VAL = ParagraphStyle("val", parent=st["Normal"], fontSize=10, textColor=AZUL)
    IT = ParagraphStyle("it", parent=st["Normal"], fontSize=8.5, textColor=AZUL, leading=11)
    ITR = ParagraphStyle("itr", parent=IT, alignment=TA_RIGHT)
    SEC = ParagraphStyle("sec", parent=st["Normal"], fontSize=9.5, textColor=AZUL, fontName="Helvetica-Bold", spaceBefore=8, spaceAfter=4)
    PIE = ParagraphStyle("pie", parent=st["Normal"], fontSize=8, textColor=AZUL_MEDIO, alignment=TA_CENTER)
    COND = {"habil": "Hábil", "inhabil": "Inhábil", "vitalicio": "Vitalicio", "suspendido": "Suspendido",
            "fallecido": "Fallecido", "retirado": "Retirado"}

    def P(t, estilo=IT):
        return Paragraph(_esc(str(t if t is not None else "—")), estilo)

    def soles(v):
        return "S/ %s" % format(float(v or 0), ",.2f")

    def caja(filas, anchos, cabecera=True):
        t = Table(filas, colWidths=anchos, repeatRows=1 if cabecera else 0)
        est = [("GRID", (0, 0), (-1, -1), 0.5, BORDE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
               ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]
        if cabecera:
            est += [("BACKGROUND", (0, 0), (-1, 0), AZUL), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, GRIS])]
        else:
            est += [("BACKGROUND", (0, 0), (0, -1), GRIS)]
        t.setStyle(TableStyle(est))
        return t

    BL = ParagraphStyle("bl", parent=IT, textColor=colors.white, fontName="Helvetica-Bold")
    BLR = ParagraphStyle("blr", parent=BL, alignment=TA_RIGHT)
    el = [Paragraph(_esc(nombre_org), H1)]
    if cf and cf.ruc:
        el.append(Paragraph("RUC: %s" % _esc(cf.ruc), SUB))
    el += [Spacer(1, 5 * mm), Paragraph("ACTA DE CONCILIACIÓN DE DEUDA", TIT),
           Paragraph(_esc(a["numero"]), ParagraphStyle("n", parent=TIT, fontSize=11, textColor=AZUL_MEDIO)), Spacer(1, 5 * mm)]

    el.append(caja([
        [P("Colegiado", LBL), P(a["colegiado"], VAL)],
        [P("Matrícula", LBL), P(a["matricula"], VAL)],
        [P("Acta creada", LBL), P(a["creada"], VAL)],
        [P("Acta ejecutada", LBL), P(a["cerrada"], VAL)],
    ], [38 * mm, 140 * mm], cabecera=False))

    el.append(Paragraph("Deuda y condición", SEC))
    sentido = "Baja" if a["sentido"] == "baja" else "Sube"
    el.append(caja([
        [P("", BL), P("Antes", BL), P("Después", BL)],
        [P("Deuda total"), P(soles(a["deuda_anterior"]), ITR), P(soles(a["deuda_despues"] if a["deuda_despues"] is not None else a["monto_fijado"]), ITR)],
        [P("Diferencia (%s)" % sentido), P(""), P(soles(abs(a["diferencia"])), ITR)],
        [P("Condición del colegiado"), P(COND.get(a["condicion_antes"], a["condicion_antes"])), P(COND.get(a["condicion_despues"], a["condicion_despues"]))],
    ], [78 * mm, 50 * mm, 50 * mm]))

    el.append(Paragraph("Motivo", SEC))
    el.append(caja([[P(a["motivo"])]], [178 * mm], cabecera=False))

    el.append(Paragraph("Deudas tocadas (%d)" % len(a["detalle"] or []), SEC))
    ACC = {"anulada": "Anulada", "saldo_reducido": "Saldo reducido", "creada": "Creada"}
    filas = [[P("Deuda", BL), P("Periodo", BL), P("Qué se hizo", BL), P("Saldo antes", BLR), P("Saldo después", BLR)]]
    for d in a["detalle"] or []:
        filas.append([P(d.get("concepto")), P(d.get("periodo") or "—"), P(ACC.get(d.get("accion"), d.get("accion"))),
                      P(soles(d.get("saldo_antes")), ITR), P(soles(d.get("saldo_despues")), ITR)])
    if len(filas) == 1:
        filas.append([P("Sin deudas tocadas"), P(""), P(""), P(""), P("")])
    el.append(caja(filas, [70 * mm, 24 * mm, 30 * mm, 27 * mm, 27 * mm]))

    el.append(Paragraph("Firmas (%d de %d requeridas)" % (a["firmas_aprobadas"], a["firmas_requeridas"]), SEC))
    filas = [[P("Nombre", BL), P("Rol", BL), P("Decisión", BL), P("Fecha", BL), P("Comentario", BL)]]
    for f in a["firmas"]:
        filas.append([P(f["nombre"]), P((f["rol"] or "").capitalize()), P("Aprueba" if f["decision"] == "aprobar" else "Rechaza"),
                      P(f["fecha"]), P(f["comentario"] or "")])
    el.append(caja(filas, [52 * mm, 24 * mm, 22 * mm, 30 * mm, 50 * mm]))

    el += [Spacer(1, 7 * mm),
           Paragraph("Esta acta modifica únicamente deudas. No altera pagos ni comprobantes electrónicos.", PIE),
           Paragraph("Documento interno generado por el sistema. No es un comprobante de pago.", PIE)]

    def _pie(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7); canvas.setFillColor(AZUL_MEDIO)
        canvas.drawString(16 * mm, 9 * mm, "%s — %s" % (nombre_org.title(), a["numero"]))
        canvas.drawRightString(A4[0] - 16 * mm, 9 * mm, "Página %d" % doc.page)
        canvas.restoreState()

    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, topMargin=16 * mm, bottomMargin=16 * mm, leftMargin=16 * mm, rightMargin=16 * mm,
                      title="Acta de conciliación %s" % a["numero"]).build(el, onFirstPage=_pie, onLaterPages=_pie)
    return buf.getvalue(), "%s.pdf" % a["numero"]


def listar_actas(db: Session, org_id: int, estado: str = "pendiente", colegiado_id: int = None, member=None, limite: int = 100) -> list:
    cond, p = ["a.organization_id = :o"], {"o": org_id, "lim": min(max(int(limite), 1), 300)}
    if estado and estado != "todas":
        cond.append("a.estado = :e"); p["e"] = estado
    if colegiado_id:
        cond.append("a.colegiado_id = :c"); p["c"] = colegiado_id
    actas = db.execute(text("""
        SELECT a.*, c.apellidos_nombres, c.codigo_matricula
        FROM actas_conciliacion a JOIN colegiados c ON c.id = a.colegiado_id
        WHERE %s ORDER BY (a.estado='pendiente') DESC, a.created_at DESC LIMIT :lim
    """ % " AND ".join(cond)), p).fetchall()
    if not actas:
        return []
    fs = db.execute(text("""
        SELECT f.acta_id, f.member_id, f.rol, f.decision, f.comentario, f.created_at,
               coalesce(u.name, 'Miembro ' || f.member_id) AS nombre
        FROM acta_firmas f LEFT JOIN members m ON m.id = f.member_id LEFT JOIN users u ON u.id = m.user_id
        WHERE f.acta_id = ANY(:ids) ORDER BY f.created_at, f.id
    """), {"ids": [a.id for a in actas]}).fetchall()
    por_acta = {}
    for f in fs:
        por_acta.setdefault(f.acta_id, []).append(dict(f._mapping))
    return [_fila_acta(a, por_acta.get(a.id, []), member) for a in actas]

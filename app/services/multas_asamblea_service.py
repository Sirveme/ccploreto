"""
app/services/multas_asamblea_service.py — Multas por inasistencia a asamblea (tanda 10).

Parte del módulo de Asambleas existente (asambleas + asamblea_asistencia, mesa de asamblea.py).
NO crea tablas: el lote vive en las propias deudas.

  - Lote:        debts.lote_migracion = 'MULTA-ASAM-<asamblea_id>-<AAAAMMDDhhmmss>',
                 origen 'multa_asamblea', created_by = usuario, created_at = fecha.
                 Un registro de auditoría (audit finanzas) por lote generado / deshecho.
  - Multa:       debt_type 'multa', concepto MULT-INA (monto LEÍDO de conceptos_cobro, nunca fijo),
                 gestión 'vigente' → el motor de habilidad la evalúa igual que cualquier multa.
  - Obligados:   colegiados de la organización cuya condición NO está en el conjunto de exentas
                 del preset activo (condiciones_exentas_generacion: hoy vitalicio, fallecido,
                 retirado, baja, suspendido) y ya colegiados en la fecha de la asamblea.
  - Vista previa obligatoria: generar exige el `token` que devuelve la vista previa; si algo
                 cambió desde entonces (asistencia, padrón, monto), el token ya no coincide.
  - Asamblea cerrada = asistencia fija. Solo se genera con la asamblea cerrada.
  - Justificar:  anula UNA multa sin pagos (gestión 'justificada', motivo obligatorio) y
                 re-evalúa la habilidad del colegiado.
  - Deshacer:    anula TODO el lote si ninguna multa tiene pagos (motivo obligatorio) y
                 re-evalúa la habilidad de los afectados.
Roles (los aplica el router): generar, justificar y deshacer → admin y sote.
"""
import hashlib
import io
import re
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

LIMA = timezone(timedelta(hours=-5))
CODIGO_MULTA = "MULT-INA"
PREFIJO_LOTE = "MULTA-ASAM-"
ORIGEN = "multa_asamblea"
EXENTAS_FALLBACK = {"vitalicio", "fallecido", "retirado", "baja", "suspendido"}


class MultaError(Exception):
    def __init__(self, status, detalle):
        super().__init__(detalle)
        self.status, self.detalle = status, detalle


# ───────────────────────── Datos base ─────────────────────────
def asamblea(db: Session, org_id: int, asamblea_id: int):
    a = db.execute(text("SELECT id, fecha, titulo, estado FROM asambleas WHERE id=:i AND organization_id=:o"),
                   {"i": asamblea_id, "o": org_id}).fetchone()
    if not a:
        raise MultaError(404, "Asamblea no encontrada")
    return a


def condiciones_exentas(db: Session, org_id: int) -> set:
    """Del preset activo (Condiciones y Exoneraciones). Fallback: el conjunto histórico."""
    try:
        from app.services.condiciones_service import get_condiciones
        s = get_condiciones(db, org_id).get("condiciones_exentas_generacion")
        if s:
            return {str(x).lower() for x in s}
    except Exception:
        pass
    return set(EXENTAS_FALLBACK)


def umbral_multas(db: Session, org_id: int) -> int:
    try:
        from app.services.condiciones_service import get_condiciones
        return max(1, int(get_condiciones(db, org_id).get("inhab_multa") or 1))
    except Exception:
        return 1


def concepto_multa(db: Session, org_id: int):
    c = db.execute(text("""SELECT id, codigo, nombre, monto_base FROM conceptos_cobro
                           WHERE organization_id=:o AND codigo=:c AND coalesce(activo, TRUE)
                           ORDER BY id LIMIT 1"""), {"o": org_id, "c": CODIGO_MULTA}).fetchone()
    if not c or float(c.monto_base or 0) <= 0:
        raise MultaError(400, "No hay concepto %s activo con monto: configúrelo en el catálogo antes de generar." % CODIGO_MULTA)
    return c


def lote_activo(db: Session, asamblea_id: int):
    """Lote vigente (no deshecho) de la asamblea: el que tiene alguna multa no anulada."""
    r = db.execute(text("""SELECT lote_migracion lote, min(created_at) creado, min(created_by) por,
                                  count(*) n, coalesce(sum(amount),0) monto,
                                  count(*) FILTER (WHERE status IN ('paid','partial') OR balance < amount - 0.005) con_pago,
                                  count(*) FILTER (WHERE estado_gestion = 'justificada') justificadas
                           FROM debts WHERE lote_migracion LIKE :p AND coalesce(estado_gestion,'') <> 'anulada'
                           GROUP BY 1 ORDER BY 2 DESC LIMIT 1"""), {"p": "%s%d-%%" % (PREFIJO_LOTE, asamblea_id)}).fetchone()
    return r


# ───────────────────────── Asistencia ─────────────────────────
def _exigir_abierta(a):
    if a.estado != "abierta":
        raise MultaError(400, "La asamblea está cerrada: la asistencia ya no se puede cambiar.")


def marcar(db: Session, org_id: int, asamblea_id: int, colegiado_id: int, presente: bool, member_id: int):
    a = asamblea(db, org_id, asamblea_id)
    _exigir_abierta(a)
    col = db.execute(text("SELECT id FROM colegiados WHERE id=:c AND organization_id=:o"), {"c": colegiado_id, "o": org_id}).fetchone()
    if not col:
        raise MultaError(404, "Colegiado no encontrado en el padrón")
    if presente:
        db.execute(text("""INSERT INTO asamblea_asistencia (organization_id, asamblea_id, colegiado_id, registrado_por, hora_registro)
                           VALUES (:o, :a, :c, :m, now()) ON CONFLICT (asamblea_id, colegiado_id) DO NOTHING"""),
                   {"o": org_id, "a": asamblea_id, "c": colegiado_id, "m": member_id})
    else:
        db.execute(text("DELETE FROM asamblea_asistencia WHERE asamblea_id=:a AND colegiado_id=:c"), {"a": asamblea_id, "c": colegiado_id})
    db.commit()
    return total_asistencia(db, asamblea_id)


def total_asistencia(db: Session, asamblea_id: int) -> int:
    return int(db.execute(text("SELECT count(*) FROM asamblea_asistencia WHERE asamblea_id=:a"), {"a": asamblea_id}).scalar() or 0)


def lista_asistencia(db: Session, org_id: int, asamblea_id: int):
    rows = db.execute(text("""SELECT c.id, c.codigo_matricula mat, c.apellidos_nombres nombre, c.condicion, x.hora_registro
                              FROM asamblea_asistencia x JOIN colegiados c ON c.id=x.colegiado_id
                              WHERE x.asamblea_id=:a AND c.organization_id=:o ORDER BY c.apellidos_nombres"""),
                      {"a": asamblea_id, "o": org_id}).fetchall()
    return [{"id": r.id, "matricula": r.mat, "nombre": r.nombre, "condicion": r.condicion,
             "hora": r.hora_registro.strftime("%d/%m %H:%M") if r.hora_registro else None} for r in rows]


def _norm(v):
    return re.sub(r"\s+", "", str(v or "")).upper()


def importar_excel(db: Session, org_id: int, asamblea_id: int, contenido: bytes, member_id: int, aplicar: bool):
    """Importa asistentes desde Excel. Busca en cada fila una matrícula (NN-NNNN) o un DNI (8 dígitos),
    en cualquier columna. aplicar=False solo informa (vista previa de la importación)."""
    a = asamblea(db, org_id, asamblea_id)
    _exigir_abierta(a)
    from openpyxl import load_workbook
    try:
        wb = load_workbook(io.BytesIO(contenido), read_only=True, data_only=True)
    except Exception:
        raise MultaError(400, "El archivo no es un Excel válido (.xlsx).")
    ws = wb.worksheets[0]
    padron = db.execute(text("SELECT id, upper(codigo_matricula) mat, dni FROM colegiados WHERE organization_id=:o"), {"o": org_id}).fetchall()
    por_mat = {r.mat: r.id for r in padron if r.mat}
    por_dni = {}
    for r in padron:
        if r.dni:
            por_dni.setdefault(r.dni.strip(), []).append(r.id)
    ya = {r[0] for r in db.execute(text("SELECT colegiado_id FROM asamblea_asistencia WHERE asamblea_id=:a"), {"a": asamblea_id})}
    encontrados, no_encontrados, filas = [], [], 0
    for fila in ws.iter_rows(values_only=True):
        celdas = [_norm(v) for v in fila if v is not None and str(v).strip()]
        if not celdas:
            continue
        filas += 1
        cid = None
        for v in celdas:
            if re.fullmatch(r"\d{2}-\d{3,5}", v) and v in por_mat:
                cid = por_mat[v]; break
            d = re.fullmatch(r"\d{8}", v.split(".")[0])
            if d and len(por_dni.get(d.group(0), [])) == 1:
                cid = por_dni[d.group(0)][0]; break
        if cid:
            encontrados.append(cid)
        elif any(re.fullmatch(r"(\d{2}-\d{3,5}|\d{8}(\.0)?)", v) for v in celdas):
            no_encontrados.append(" ".join(celdas)[:60])
    nuevos = sorted(set(encontrados) - ya)
    if aplicar and nuevos:
        for cid in nuevos:
            db.execute(text("""INSERT INTO asamblea_asistencia (organization_id, asamblea_id, colegiado_id, registrado_por, hora_registro)
                               VALUES (:o, :a, :c, :m, now()) ON CONFLICT (asamblea_id, colegiado_id) DO NOTHING"""),
                       {"o": org_id, "a": asamblea_id, "c": cid, "m": member_id})
        db.commit()
    return {"filas_leidas": filas, "encontrados": len(set(encontrados)), "ya_estaban": len(set(encontrados) & ya),
            "nuevos": len(nuevos), "no_encontrados": no_encontrados[:200], "aplicado": bool(aplicar),
            "total_asistencia": total_asistencia(db, asamblea_id)}


# ───────────────────────── Vista previa ─────────────────────────
def _inasistentes(db: Session, org_id: int, a):
    exentas = sorted(condiciones_exentas(db, org_id))
    return db.execute(text("""
        SELECT c.id, c.codigo_matricula mat, c.apellidos_nombres nombre, c.condicion,
               EXISTS (SELECT 1 FROM fraccionamientos f WHERE f.colegiado_id=c.id AND f.estado='activo') plan_activo,
               (SELECT count(*) FROM debts d WHERE d.colegiado_id=c.id AND d.debt_type='multa' AND d.balance > 0
                  AND d.status IN ('pending','partial') AND coalesce(d.estado_gestion,'vigente') IN ('vigente','en_cobranza')) multas_pend
        FROM colegiados c
        WHERE c.organization_id = :o
          AND lower(coalesce(c.condicion,'')) <> ALL(:ex)
          AND (c.fecha_colegiatura IS NULL OR c.fecha_colegiatura::date <= :f)
          AND NOT EXISTS (SELECT 1 FROM asamblea_asistencia x WHERE x.asamblea_id = :a AND x.colegiado_id = c.id)
        ORDER BY c.apellidos_nombres"""), {"o": org_id, "ex": exentas, "f": a.fecha, "a": a.id}).fetchall(), exentas


def _token(asamblea_id, monto, ids):
    h = hashlib.sha256(("%d|%.2f|%s" % (asamblea_id, float(monto), ",".join(map(str, sorted(ids))))).encode()).hexdigest()
    return h[:24]


def previsualizar(db: Session, org_id: int, asamblea_id: int):
    a = asamblea(db, org_id, asamblea_id)
    conc = concepto_multa(db, org_id)
    monto = round(float(conc.monto_base), 2)
    filas, exentas = _inasistentes(db, org_id, a)
    umbral = umbral_multas(db, org_id)
    asist = total_asistencia(db, asamblea_id)
    obligados = int(db.execute(text("""SELECT count(*) FROM colegiados c WHERE c.organization_id=:o
             AND lower(coalesce(c.condicion,'')) <> ALL(:ex) AND (c.fecha_colegiatura IS NULL OR c.fecha_colegiatura::date <= :f)"""),
                               {"o": org_id, "ex": exentas, "f": a.fecha}).scalar() or 0)
    lista, cambian = [], 0
    for r in filas:
        # Misma regla que el motor (evaluar_habilidad): un hábil sin plan activo pasa a inhábil
        # cuando sus multas impagas alcanzan el umbral del preset (inhab_multa).
        cambia = (r.condicion == "habil") and not r.plan_activo and (r.multas_pend + 1) >= umbral
        cambian += int(cambia)
        lista.append({"colegiado_id": r.id, "matricula": r.mat, "nombre": r.nombre, "condicion": r.condicion,
                      "pasaria_a_inhabil": bool(cambia), "plan_activo": bool(r.plan_activo)})
    # Efecto REAL con el motor oficial: se insertan las multas dentro de un SAVEPOINT, se
    # sincroniza la condición de los hábiles (los únicos que pueden cambiar) y se deshace todo.
    # Así la vista previa dice exactamente lo que hará la generación, sea cual sea el motor.
    candidatos = [x["colegiado_id"] for x in lista if x["condicion"] == "habil"]
    real = set()
    if lista and candidatos:
        sp = db.begin_nested()
        try:
            for x in lista:
                db.execute(text("""INSERT INTO debts (organization_id, colegiado_id, concepto_cobro_id, concept, debt_type, amount, balance,
                                     status, estado_gestion, origen, created_at)
                                   VALUES (:o, :c, :cc, 'vista previa', 'multa', :m, :m, 'pending', 'vigente', :orig, now())"""),
                           {"o": org_id, "c": x["colegiado_id"], "cc": conc.id, "m": monto, "orig": ORIGEN})
            db.flush()
            real = {c["colegiado_id"] for c in _reevaluar(db, org_id, candidatos)}
        finally:
            sp.rollback()
            db.expire_all()
    for x in lista:
        x["pasaria_a_inhabil"] = x["colegiado_id"] in real
    segun_regla = cambian
    cambian = len(real)
    adv = []
    if segun_regla != cambian:
        adv.append("Con la regla del preset (%d multa impaga inhabilita) pasarían a inhábil %d; con el motor de habilidad actual cambian %d. "
                   "El motor, al sincronizar, hoy no evalúa multas (ver informe): la generación hará lo que dice el motor." % (umbral, segun_regla, cambian))
    if asist == 0:
        adv.append("No hay asistencia cargada: TODOS los obligados (%d) recibirían multa. Cargue la asistencia antes de generar." % len(lista))
    if a.estado == "abierta":
        adv.append("La asamblea sigue abierta: ciérrela (la asistencia queda fija) para poder generar.")
    lote = lote_activo(db, asamblea_id)
    if lote:
        adv.append("Esta asamblea ya tiene un lote de multas vigente (%s). Para regenerar, primero deshágalo." % lote.lote)
    return {
        "asamblea": {"id": a.id, "fecha": a.fecha.isoformat(), "titulo": a.titulo, "estado": a.estado},
        "concepto": {"codigo": conc.codigo, "nombre": conc.nombre, "monto": monto},
        "condiciones_exentas": exentas, "umbral_multas_preset": umbral,
        "obligados": obligados, "asistentes": asist, "multas": len(lista), "monto_total": round(monto * len(lista), 2),
        "cambiarian_a_inhabil": cambian, "segun_regla_preset": segun_regla, "colegiados": lista, "advertencias": adv,
        "puede_generar": a.estado == "cerrada" and not lote and len(lista) > 0,
        "token": _token(a.id, monto, [x["colegiado_id"] for x in lista]),
    }


# ───────────────────────── Generar / justificar / deshacer ─────────────────────────
def _org(db, org_id):
    r = db.execute(text("SELECT id, config FROM organizations WHERE id=:o"), {"o": org_id}).fetchone()
    return {"id": r.id, "config": r.config or {}} if r else {"id": org_id, "config": {}}


def _reevaluar(db: Session, org_id: int, colegiado_ids):
    from app.models import Colegiado
    from app.services.evaluar_habilidad import sincronizar_condicion
    org = _org(db, org_id)
    cambios = []
    for col in db.query(Colegiado).filter(Colegiado.id.in_(list(colegiado_ids))).all():
        antes = col.condicion
        if sincronizar_condicion(db, col, org):
            cambios.append({"colegiado_id": col.id, "antes": antes, "despues": col.condicion})
    db.flush()
    return cambios


def _accion(db, org_id, debt_id, tipo, descripcion, monto, bal_antes, bal_nuevo, gest_antes, gest_nuevo, user_id):
    db.execute(text("""INSERT INTO debt_actions (organization_id, debt_id, tipo, descripcion, monto_afectado,
                         balance_anterior, balance_nuevo, estado_gestion_anterior, estado_gestion_nuevo, created_by, created_at)
                       VALUES (:o, :d, :t, :ds, :m, :ba, :bn, :ga, :gn, :u, now())"""),
               {"o": org_id, "d": debt_id, "t": tipo, "ds": descripcion[:500], "m": monto, "ba": bal_antes, "bn": bal_nuevo,
                "ga": gest_antes, "gn": gest_nuevo, "u": user_id})


def generar(db: Session, org_id: int, asamblea_id: int, token: str, user_id: int, member_id: int):
    """Un solo lote atómico. Exige asamblea cerrada, sin lote vigente y el token de la vista previa."""
    prev = previsualizar(db, org_id, asamblea_id)
    a = prev["asamblea"]
    if a["estado"] != "cerrada":
        raise MultaError(400, "Cierre la asamblea antes de generar: la asistencia debe quedar fija.")
    if lote_activo(db, asamblea_id):
        raise MultaError(409, "Esta asamblea ya tiene un lote de multas vigente.")
    if not prev["multas"]:
        raise MultaError(400, "No hay a quién multar.")
    if not token or token != prev["token"]:
        raise MultaError(409, "La vista previa cambió (asistencia, padrón o monto). Vuelva a ver la vista previa y confirme.")
    conc = concepto_multa(db, org_id)
    ahora = datetime.now(LIMA)
    lote = "%s%d-%s" % (PREFIJO_LOTE, asamblea_id, ahora.strftime("%Y%m%d%H%M%S"))
    fecha_txt = date.fromisoformat(a["fecha"]).strftime("%d/%m/%Y")
    concepto = "Multa Inasistencia Asamblea %s" % fecha_txt
    monto = prev["concepto"]["monto"]
    ids = [x["colegiado_id"] for x in prev["colegiados"]]
    try:
        miembros = {r.id: r.member_id for r in db.execute(text("SELECT id, member_id FROM colegiados WHERE id = ANY(:i)"), {"i": ids})}
        for cid in ids:
            db.execute(text("""INSERT INTO debts (organization_id, colegiado_id, member_id, concepto_cobro_id, concept, periodo, period_label,
                                 debt_type, amount, balance, status, estado_gestion, fecha_generacion, due_date, origen, lote_migracion,
                                 created_by, created_at, notes)
                               VALUES (:o, :c, :m, :cc, :con, :per, :pl, 'multa', :monto, :monto, 'pending', 'vigente', :hoy, :due,
                                       :orig, :lote, :u, now(), :nota)"""),
                       {"o": org_id, "c": cid, "m": miembros.get(cid), "cc": conc.id, "con": concepto,
                        "per": a["fecha"][:7], "pl": "Asamblea %s" % fecha_txt, "monto": monto, "hoy": ahora.date(),
                        "due": ahora, "orig": ORIGEN, "lote": lote, "u": user_id,
                        "nota": "[%s] Inasistencia a «%s» (%s). Lote %s." % (ORIGEN, a["titulo"], fecha_txt, lote)})
        db.flush()
        # Solo pueden cambiar los HÁBILES (agregar una deuda nunca vuelve hábil a un inhábil):
        # se re-evalúa solo a ellos, con el motor oficial.
        cambios = _reevaluar(db, org_id, [x["colegiado_id"] for x in prev["colegiados"] if x["condicion"] == "habil"])
        _auditar(db, org_id, "generar_multas_asamblea", asamblea_id, member_id,
                 {"lote": lote, "multas": len(ids), "monto_unitario": monto, "monto_total": round(monto * len(ids), 2),
                  "cambios_condicion": len(cambios)})
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"lote": lote, "multas": len(ids), "monto_total": round(monto * len(ids), 2),
            "cambiaron_de_condicion": len(cambios), "estimado_en_vista_previa": prev["cambiarian_a_inhabil"], "cambios": cambios}


def justificar(db: Session, org_id: int, asamblea_id: int, colegiado_id: int, motivo: str, user_id: int, member_id: int):
    motivo = (motivo or "").strip()
    if len(motivo) < 10:
        raise MultaError(400, "El motivo es obligatorio (mínimo 10 caracteres).")
    asamblea(db, org_id, asamblea_id)
    d = db.execute(text("""SELECT id, amount, balance, status, estado_gestion FROM debts
                           WHERE colegiado_id=:c AND lote_migracion LIKE :p AND coalesce(estado_gestion,'') NOT IN ('anulada','justificada')
                           ORDER BY id DESC LIMIT 1"""), {"c": colegiado_id, "p": "%s%d-%%" % (PREFIJO_LOTE, asamblea_id)}).fetchone()
    if not d:
        raise MultaError(404, "Ese colegiado no tiene una multa vigente de esta asamblea.")
    if d.status in ("paid", "partial") or float(d.balance) < float(d.amount) - 0.005:
        raise MultaError(409, "La multa ya tiene pagos: no se justifica, se devuelve con nota de crédito.")
    try:
        db.execute(text("""UPDATE debts SET status='cancelled', balance=0, estado_gestion='justificada', updated_at=now(), updated_by=:u,
                             notes = coalesce(notes || E'\\n', '') || :n WHERE id=:i"""),
                   {"u": user_id, "i": d.id, "n": "[JUSTIFICADA] %s" % motivo})
        _accion(db, org_id, d.id, "justificacion", "Inasistencia justificada: %s" % motivo, float(d.balance),
                float(d.balance), 0, d.estado_gestion or "vigente", "justificada", user_id)
        cambios = _reevaluar(db, org_id, [colegiado_id])
        _auditar(db, org_id, "justificar_multa_asamblea", asamblea_id, member_id, {"debt_id": d.id, "colegiado_id": colegiado_id}, motivo)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"debt_id": d.id, "cambios": cambios}


def deshacer(db: Session, org_id: int, asamblea_id: int, motivo: str, user_id: int, member_id: int):
    motivo = (motivo or "").strip()
    if len(motivo) < 10:
        raise MultaError(400, "El motivo es obligatorio (mínimo 10 caracteres).")
    asamblea(db, org_id, asamblea_id)
    lote = lote_activo(db, asamblea_id)
    if not lote:
        raise MultaError(404, "Esta asamblea no tiene un lote de multas vigente.")
    if lote.con_pago:
        raise MultaError(409, "No se puede deshacer: %d multa(s) del lote ya tienen pagos. Devuélvalas primero con nota de crédito." % lote.con_pago)
    filas = db.execute(text("""SELECT id, colegiado_id, amount, balance, estado_gestion FROM debts
                               WHERE lote_migracion=:l AND coalesce(estado_gestion,'') <> 'anulada'"""), {"l": lote.lote}).fetchall()
    try:
        for d in filas:
            db.execute(text("""UPDATE debts SET status='cancelled', balance=0, estado_gestion='anulada', updated_at=now(), updated_by=:u,
                                 notes = coalesce(notes || E'\\n', '') || :n WHERE id=:i"""),
                       {"u": user_id, "i": d.id, "n": "[LOTE DESHECHO] %s" % motivo})
            _accion(db, org_id, d.id, "anulacion", "Lote %s deshecho: %s" % (lote.lote, motivo), float(d.balance),
                    float(d.balance), 0, d.estado_gestion or "vigente", "anulada", user_id)
        cambios = _reevaluar(db, org_id, {d.colegiado_id for d in filas})
        _auditar(db, org_id, "deshacer_lote_multas_asamblea", asamblea_id, member_id,
                 {"lote": lote.lote, "multas": len(filas), "cambios_condicion": len(cambios)}, motivo)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"lote": lote.lote, "anuladas": len(filas), "cambios": cambios}


def estado_lote(db: Session, org_id: int, asamblea_id: int):
    asamblea(db, org_id, asamblea_id)
    l = lote_activo(db, asamblea_id)
    if not l:
        return None
    return {"lote": l.lote, "creado": l.creado.isoformat() if l.creado else None, "multas": int(l.n),
            "monto": float(l.monto), "con_pago": int(l.con_pago), "justificadas": int(l.justificadas),
            "se_puede_deshacer": int(l.con_pago) == 0}


def _auditar(db, org_id, accion, asamblea_id, member_id, cambios, motivo=""):
    """Registro de auditoría de finanzas (misma transacción). Tolerante: si la tabla no existe, sigue."""
    try:
        db.execute(text("SAVEPOINT aud_multas"))
        import json as _json
        rol = db.execute(text("SELECT role FROM members WHERE id=:m"), {"m": member_id}).scalar()
        db.execute(text("""INSERT INTO audit_log_finanzas (organization_id, accion, actor_id, actor_rol, entidad_tipo, entidad_id, monto, detalle, created_at)
                           VALUES (:o, :a, :u, :r, 'asambleas', :e, :mt, CAST(:d AS jsonb), now())"""),
                   {"o": org_id, "a": accion, "u": member_id, "r": rol, "e": asamblea_id, "mt": cambios.get("monto_total"),
                    "d": _json.dumps({"cambios": cambios, "motivo": motivo}, default=str)})
        db.execute(text("RELEASE SAVEPOINT aud_multas"))
    except Exception:
        db.execute(text("ROLLBACK TO SAVEPOINT aud_multas"))

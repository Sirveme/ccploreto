"""
app/services/pagos_externos_service.py
Módulo Pagos Externos — Fase 1, sub-paso 1a: HELPERS READ-ONLY.

Ninguna función escribe. Alimentan el formulario de regularización y el CANDADO
anti-duplicado (buscar_pagos_por_debt es la base del candado y del motor de Fase 2).
Se apoyan en Fase 0 (payments.origen ya desplegado).
"""
import re
from sqlalchemy import text
from sqlalchemy.orm import Session

_RE_DEBT_IDS = re.compile(r"\[DEBT_IDS:([\d,\s]+)\]")
_ESTADOS_PAGO_VALIDOS = ("approved", "pagado", "completado")


def _debt_ids_de_notes(notes) -> set:
    """Extrae los debt_id embebidos como [DEBT_IDS:1,2,3] en payment.notes."""
    out = set()
    if not notes:
        return out
    for m in _RE_DEBT_IDS.finditer(notes):
        for x in m.group(1).split(","):
            x = x.strip()
            if x.isdigit():
                out.add(int(x))
    return out


def buscar_pagos_por_debt(db: Session, debt_ids, organization_id: int = 1) -> list:
    """PAGO_SIS: pagos del sistema YA imputados a esas deudas. Read-only.

    Une tres vías de imputación que conviven en el código:
      (1) payment_debts.debt_id  (imputación estructurada, con amount_applied)
      (2) payments.related_debt_id
      (3) marcador [DEBT_IDS:...] en payments.notes
    Devuelve por pago: id, monto, monto_aplicado(si hay), paid_at, created_at, origen,
    metodo, y su comprobante (serie-numero, tipo, origen, status) si existe.
    """
    ids = sorted({int(x) for x in (debt_ids or [])})
    if not ids:
        return []

    # (1)+(2): candidatos por vía estructurada, con amount_applied agregado a esas deudas.
    estructurados = db.execute(text("""
        SELECT p.id AS payment_id,
               COALESCE(SUM(pd.amount_applied) FILTER (WHERE pd.debt_id = ANY(:ids)), 0) AS aplicado
        FROM payments p
        LEFT JOIN payment_debts pd ON pd.payment_id = p.id
        WHERE p.organization_id = :org
          AND p.status = ANY(:estados)
          AND ( EXISTS (SELECT 1 FROM payment_debts x WHERE x.payment_id = p.id AND x.debt_id = ANY(:ids))
                OR p.related_debt_id = ANY(:ids) )
        GROUP BY p.id
    """), {"ids": ids, "org": organization_id, "estados": list(_ESTADOS_PAGO_VALIDOS)}).fetchall()
    aplicado_por_pago = {r.payment_id: float(r.aplicado or 0) for r in estructurados}

    # (3): pagos con [DEBT_IDS:...] que intersecten los ids (parseo en Python; robusto).
    con_marcador = db.execute(text("""
        SELECT id, notes FROM payments
        WHERE organization_id = :org AND status = ANY(:estados)
          AND notes LIKE '%[DEBT_IDS:%'
    """), {"org": organization_id, "estados": list(_ESTADOS_PAGO_VALIDOS)}).fetchall()
    for r in con_marcador:
        if _debt_ids_de_notes(r.notes) & set(ids):
            aplicado_por_pago.setdefault(r.id, 0.0)

    if not aplicado_por_pago:
        return []

    # Detalle de cada pago + su comprobante.
    filas = db.execute(text("""
        SELECT p.id, p.amount, p.paid_at, p.created_at, p.origen, p.payment_method,
               c.serie, c.numero, c.tipo, c.status AS comp_status
        FROM payments p
        LEFT JOIN comprobantes c ON c.payment_id = p.id
        WHERE p.id = ANY(:pids)
        ORDER BY COALESCE(p.paid_at, p.created_at)
    """), {"pids": list(aplicado_por_pago.keys())}).fetchall()

    out = []
    for r in filas:
        comp = f"{r.serie}-{r.numero}" if r.serie else None
        out.append({
            "payment_id": r.id,
            "monto": float(r.amount or 0),
            "monto_aplicado": round(aplicado_por_pago.get(r.id, 0.0), 2),
            "paid_at": r.paid_at.date().isoformat() if r.paid_at else None,
            "created_at": r.created_at.date().isoformat() if r.created_at else None,
            "origen": r.origen,
            "metodo": r.payment_method,
            "comprobante": comp,
            "comp_tipo": r.tipo,
            "comp_status": r.comp_status,   # comp_origen se añade en 1c (tras DDL comprobantes.origen)
        })
    return out


# Orígenes que marcan un pago como EXTERNO (no de caja/portal).
_ORIGENES_EXTERNOS = ("externo_eb01", "externo_comunicado", "contingencia")


def _fmt_fecha(dt):
    try:
        return dt.strftime("%d/%m/%Y") if dt else "?"
    except Exception:
        return "?"


def _iso_a_ddmmyyyy(s):
    """'2026-09-19' → '19/09/2026'. Tolera None/formatos raros."""
    try:
        y, m, d = str(s)[:10].split("-")
        return f"{d}/{m}/{y}"
    except Exception:
        return str(s) if s else "?"


def avisos_pago_externo(db: Session, debt_ids, organization_id: int = 1) -> dict:
    """Fase 3 — AVISO AL COBRAR (read-only). Para las deudas que Anggie va a cobrar,
    cruza contra pagos externos para prevenir el doble cobro. Devuelve
    {debt_id: {tipo, corto, mensaje, fecha}} SOLO para las deudas con aviso.

      tipo='pendiente'  → hay solicitud_pago_externo pendiente que imputa esa deuda.
      tipo='registrado' → ya existe un Payment externo aplicado a esa deuda.
    Precedencia: 'registrado' pisa a 'pendiente'. NO bloquea nada; solo informa.
    """
    ids = sorted({int(x) for x in (debt_ids or [])})
    if not ids:
        return {}
    ids_set = set(ids)
    out = {}

    # (1) Solicitudes PENDIENTES cuyas imputaciones toquen estas deudas.
    pend = db.execute(text("""
        SELECT id, created_at, imputaciones
        FROM solicitud_pago_externo
        WHERE organization_id = :org AND estado = 'pendiente'
    """), {"org": organization_id}).fetchall()
    for s in pend:
        for imp in (s.imputaciones or []):
            try:
                did = int(imp.get("debt_id"))
            except (TypeError, ValueError, AttributeError):
                continue
            if did in ids_set and did not in out:
                f = _fmt_fecha(s.created_at)
                out[did] = {
                    "tipo": "pendiente",
                    "corto": f"Pago externo pendiente (sol. #{s.id} del {f})",
                    "mensaje": (f"Hay una solicitud de pago externo (#{s.id}) del {f} sobre "
                                f"esta deuda, pendiente de resolver. Verifica antes de cobrar."),
                    "fecha": f,
                }

    # (2) Pagos externos YA REGISTRADOS (reusa buscar_pagos_por_debt, filtra origen).
    #     'registrado' tiene prioridad → sobrescribe a 'pendiente'.
    for did in ids:
        pagos = [p for p in buscar_pagos_por_debt(db, [did], organization_id)
                 if (p.get("origen") or "") in _ORIGENES_EXTERNOS]
        if pagos:
            p0 = pagos[0]
            f = _iso_a_ddmmyyyy(p0.get("paid_at") or p0.get("created_at"))
            comp = p0.get("comprobante") or "sin comprobante"
            out[did] = {
                "tipo": "registrado",
                "corto": f"Ya tiene pago externo aplicado ({f})",
                "mensaje": (f"Esta deuda ya tiene un pago externo aplicado del {f} "
                            f"({comp}). Verifica antes de volver a cobrar."),
                "fecha": f,
            }
    return out


def series_conocidas(db: Session, organization_id: int = 1) -> set:
    """Series ya usadas (para avisar 'serie nueva'). Read-only."""
    rows = db.execute(text("""
        SELECT DISTINCT serie FROM comprobantes
        WHERE organization_id = :org AND serie IS NOT NULL
    """), {"org": organization_id}).fetchall()
    return {r.serie for r in rows}


def ultimo_numero_serie(db: Session, serie: str, organization_id: int = 1):
    """Último correlativo conocido de una serie (para avisar número menor). Read-only.
    Devuelve int o None si la serie no tiene comprobantes."""
    r = db.execute(text("""
        SELECT MAX(numero) AS ult FROM comprobantes
        WHERE organization_id = :org AND serie = :serie
    """), {"org": organization_id, "serie": serie}).fetchone()
    return int(r.ult) if r and r.ult is not None else None


def unicidad_eb01(db: Session, serie: str, numero: int, organization_id: int = 1):
    """¿Ya existe un comprobante con esa serie+número? (bloquea doble registro EB01).
    Read-only. Devuelve el comprobante existente (dict) o None si está libre."""
    r = db.execute(text("""
        SELECT id, serie, numero, tipo, payment_id, status
        FROM comprobantes
        WHERE organization_id = :org AND serie = :serie AND numero = :numero
        LIMIT 1
    """), {"org": organization_id, "serie": serie, "numero": int(numero)}).fetchone()
    if not r:
        return None
    return {"comprobante_id": r.id, "serie": r.serie, "numero": r.numero, "tipo": r.tipo,
            "payment_id": r.payment_id, "status": r.status}


# ══════════════════════════════════════════════════════════════════════════════
# Fase 1 sub-paso 1b: ANÁLISIS / PREVIEW (READ-ONLY, sin commit)
# ══════════════════════════════════════════════════════════════════════════════
# Mapeo tipo → comportamiento. Alineado con el enum payments.origen (Fase 0) y con
# el filtro de arqueo (caja.py): SOLO caja_fisica + contingencia entran al arqueo.
TIPOS_PAGO_EXTERNO = {
    1: {"nombre": "EB01 SUNAT-SOL (fecha pasada)",            "origen": "externo_eb01",
        "emite_comprobante": True,  "en_arqueo": False, "requiere_serie": True,
        "comp_status": "externo_sunat"},
    2: {"nombre": "Pago externo comunicado (sin comprobante)", "origen": "externo_comunicado",
        "emite_comprobante": False, "en_arqueo": False, "requiere_serie": False,
        "comp_status": None},
    3: {"nombre": "EB01 contingencia SUNAT-SOL (hoy)",         "origen": "contingencia",
        "emite_comprobante": True,  "en_arqueo": True,  "requiere_serie": True,
        "comp_status": "externo_sunat"},
}


def _saldo_debts(db: Session, debt_ids, organization_id: int = 1) -> dict:
    """Read-only: devuelve {debt_id: {...}} con saldo y metadatos de cada deuda."""
    if not debt_ids:
        return {}
    rows = db.execute(text("""
        SELECT id, colegiado_id, concept, period_label, periodo, amount, balance,
               status, estado_gestion, estado_notificacion, debt_type
        FROM debts WHERE id = ANY(:ids) AND organization_id = :org
    """), {"ids": sorted({int(x) for x in debt_ids}), "org": organization_id}).fetchall()
    out = {}
    for d in rows:
        out[d.id] = {
            "debt_id": d.id, "colegiado_id": d.colegiado_id, "concept": d.concept,
            "period_label": d.period_label, "periodo": d.periodo,
            "amount": float(d.amount or 0), "saldo": float(d.balance or 0),
            "status": d.status, "estado_gestion": d.estado_gestion,
            "estado_notificacion": d.estado_notificacion, "debt_type": d.debt_type,
        }
    return out


def analizar_pago_externo(db: Session, payload: dict, organization_id: int = 1) -> dict:
    """PREVIEW READ-ONLY de un pago externo. NO escribe nada.

    Devuelve qué se CREARÍA (Payment con origen, comprobante, imputación, arqueo,
    re-eval habilidad) y aplica el CANDADO anti-duplicado:
      - si buscar_pagos_por_debt encuentra un PAGO_SIS ya imputado → BLOQUEO
      - si el monto a imputar en una deuda supera su saldo → BLOQUEO
    (ambos → 'requiere conciliación (Fase 2)'). También valida serie/número EB01.
    Estructura: {ok, bloqueos[], avisos[], colegiado, preview{...}}.
    """
    bloqueos, avisos = [], []

    def _bloq(codigo, msg):
        bloqueos.append({"codigo": codigo, "mensaje": msg})

    def _aviso(codigo, msg):
        avisos.append({"codigo": codigo, "mensaje": msg})

    # ── tipo ──────────────────────────────────────────────────────────────────
    try:
        tipo = int(payload.get("tipo"))
    except (TypeError, ValueError):
        tipo = None
    cfg = TIPOS_PAGO_EXTERNO.get(tipo)
    if not cfg:
        return {"ok": False, "bloqueos": [{"codigo": "TIPO_INVALIDO",
                "mensaje": "Tipo de pago externo inválido (usar 1, 2 o 3)."}],
                "avisos": [], "colegiado": None, "preview": None}

    # ── colegiado ───────────────────────────────────────────────────────────────
    col = db.execute(text("""
        SELECT id, dni, codigo_matricula, apellidos_nombres, condicion
        FROM colegiados WHERE id = :id AND organization_id = :org LIMIT 1
    """), {"id": payload.get("colegiado_id"), "org": organization_id}).fetchone()
    if not col:
        return {"ok": False, "bloqueos": [{"codigo": "COLEGIADO_NO_EXISTE",
                "mensaje": "Colegiado no encontrado."}],
                "avisos": [], "colegiado": None, "preview": None}
    colegiado = {"id": col.id, "dni": col.dni, "codigo_matricula": col.codigo_matricula,
                 "apellidos_nombres": col.apellidos_nombres, "condicion": col.condicion}

    # ── monto total del pago ────────────────────────────────────────────────────
    try:
        monto_pago = round(float(payload.get("monto") or 0), 2)
    except (TypeError, ValueError):
        monto_pago = 0.0
    if monto_pago <= 0:
        _bloq("MONTO_INVALIDO", "El monto del pago debe ser mayor a 0.")

    # ── imputaciones (por debt_id) ──────────────────────────────────────────────
    imps_in = payload.get("imputaciones") or []
    debt_ids = []
    for it in imps_in:
        try:
            debt_ids.append(int(it.get("debt_id")))
        except (TypeError, ValueError):
            pass
    saldos = _saldo_debts(db, debt_ids, organization_id)

    imputaciones, total_imputado = [], 0.0
    for it in imps_in:
        try:
            did = int(it.get("debt_id"))
        except (TypeError, ValueError):
            continue
        info = saldos.get(did)
        if not info:
            _bloq("DEUDA_NO_EXISTE", f"La deuda #{did} no existe.")
            continue
        if info["colegiado_id"] != col.id:
            _bloq("DEUDA_AJENA", f"La deuda #{did} no pertenece a este colegiado.")
            continue
        # monto a imputar: el indicado, o el saldo completo si no se especifica
        m_in = it.get("monto")
        try:
            m = round(float(m_in), 2) if m_in is not None else round(info["saldo"], 2)
        except (TypeError, ValueError):
            m = round(info["saldo"], 2)
        total_imputado = round(total_imputado + m, 2)
        excede = m > info["saldo"] + 0.001
        if excede:
            _bloq("MONTO_EXCEDE_DEUDA",
                  f"Deuda #{did} ({info['concept']}): imputar S/{m:.2f} supera el "
                  f"saldo S/{info['saldo']:.2f} → requiere conciliación (Fase 2).")
        if info["saldo"] <= 0.001:
            _bloq("DEUDA_SIN_SALDO",
                  f"Deuda #{did} ({info['concept']}) ya está saldada (S/0) → "
                  f"posible duplicado, requiere conciliación (Fase 2).")
        if (info["estado_notificacion"] or "no_notificada") == "no_notificada":
            _aviso("DEUDA_NO_NOTIFICADA",
                   f"Deuda #{did} ({info['concept']}) está 'no_notificada' (no exigible).")
        imputaciones.append({
            "debt_id": did, "concept": info["concept"], "period_label": info["period_label"],
            "saldo": info["saldo"], "monto_a_imputar": m,
            "saldo_resultante": round(info["saldo"] - m, 2),
            "debt_type": info["debt_type"], "estado_notificacion": info["estado_notificacion"],
        })

    if not imputaciones:
        _bloq("SIN_IMPUTACION", "Debe indicar al menos una deuda a imputar (por debt_id).")

    # coherencia monto pago vs total imputado (solo aviso; el remanente iría a favor)
    if imputaciones and abs(total_imputado - monto_pago) > 0.01:
        if total_imputado > monto_pago + 0.01:
            _bloq("IMPUTA_MAYOR_QUE_PAGO",
                  f"El total a imputar (S/{total_imputado:.2f}) supera el monto del "
                  f"pago (S/{monto_pago:.2f}).")
        else:
            _aviso("REMANENTE_A_FAVOR",
                   f"El pago (S/{monto_pago:.2f}) supera lo imputado "
                   f"(S/{total_imputado:.2f}); remanente S/{monto_pago - total_imputado:.2f}.")

    # ── CANDADO anti-duplicado: ¿ya hay un PAGO_SIS sobre estas deudas? ──────────
    pago_sis = buscar_pagos_por_debt(db, debt_ids, organization_id) if debt_ids else []
    if pago_sis:
        detalle = "; ".join(
            f"pago#{p['payment_id']} S/{p['monto']:.2f} ({p['comprobante'] or 'sin comp.'})"
            for p in pago_sis)
        _bloq("DUPLICADO_PAGO_SIS",
              f"El sistema YA tiene {len(pago_sis)} pago(s) imputado(s) a esa(s) deuda(s): "
              f"{detalle}. Requiere conciliación (Fase 2). NO se registra.")

    # ── validación serie/número (tipo 1 y 3, que emiten EB01) ───────────────────
    serie = (payload.get("serie") or "").strip().upper() or None
    numero_raw = payload.get("numero")
    numero = None
    comprobante_prev = None
    if cfg["emite_comprobante"]:
        if not serie or numero_raw in (None, ""):
            _bloq("FALTA_SERIE_NUMERO",
                  "Este tipo requiere serie y número del comprobante SUNAT.")
        else:
            try:
                numero = int(numero_raw)
            except (TypeError, ValueError):
                _bloq("NUMERO_INVALIDO", "El número de comprobante debe ser entero.")
            if numero is not None:
                existente = unicidad_eb01(db, serie, numero, organization_id)
                if existente:
                    _bloq("COMPROBANTE_DUPLICADO",
                          f"Ya existe {serie}-{numero} (comprobante #{existente['comprobante_id']}, "
                          f"status {existente['status']}). NO se registra.")
                if serie not in series_conocidas(db, organization_id):
                    _aviso("SERIE_NUEVA", f"La serie '{serie}' es nueva (primer comprobante).")
                else:
                    ult = ultimo_numero_serie(db, serie, organization_id)
                    if ult is not None and numero <= ult:
                        _aviso("CORRELATIVO_MENOR",
                               f"El número {numero} no es mayor al último conocido de "
                               f"'{serie}' ({ult}).")
                comprobante_prev = {
                    "serie": serie, "numero": numero,
                    "tipo": "03", "status": cfg["comp_status"],
                    "origen": cfg["origen"],  # se persiste en comprobantes.origen (DDL en 1c)
                }

    # ── re-evaluación de habilidad (descriptivo; el motor real corre en 1c) ──────
    ordinarias = [i for i in imputaciones
                  if (i["debt_type"] or "").startswith("cuota_ordinaria")
                  and i["saldo_resultante"] <= 0.001]
    reeval = {
        "condicion_actual": col.condicion,
        "impacta_habilidad": bool(ordinarias),
        "detalle": (f"Salda {len(ordinarias)} cuota(s) ordinaria(s) → se re-evaluaría "
                    f"habilidad en el registro." if ordinarias
                    else "No salda cuotas ordinarias → sin efecto en habilidad."),
    }

    # ── preview del Payment que se crearía ──────────────────────────────────────
    payment_prev = {
        "origen": cfg["origen"],
        "amount": monto_pago,
        "payment_method": payload.get("metodo_pago"),
        "operation_code": payload.get("nro_operacion"),
        "paid_at": payload.get("fecha_pago"),
        "status": "approved",
        "notes_marcador": f"[DEBT_IDS:{','.join(str(i['debt_id']) for i in imputaciones)}]"
                          if imputaciones else None,
    }

    ok = len(bloqueos) == 0
    return {
        "ok": ok,
        "bloqueos": bloqueos,
        "avisos": avisos,
        "colegiado": colegiado,
        "preview": {
            "tipo": tipo,
            "tipo_nombre": cfg["nombre"],
            "payment": payment_prev,
            "comprobante": comprobante_prev,
            "imputaciones": imputaciones,
            "total_imputado": total_imputado,
            "en_arqueo": cfg["en_arqueo"],
            "requiere_sesion_abierta": cfg["en_arqueo"],  # tipo 3: guard en 1c
            "reeval_habilidad": reeval,
        },
    }

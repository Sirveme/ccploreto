# -*- coding: utf-8 -*-
"""
reporte_ventas_service.py — Reporte de Ventas por Rango de Fechas (CCPL).

Módulo PILOTO de Consultas/Reportes. Fuente de verdad ÚNICA: una función
`generar_reporte_ventas(desde, hasta, filtros)` devuelve un objeto; pantalla,
Excel y PDF consumen el MISMO objeto (tres presentaciones, una verdad).

100% LECTURA. Ningún INSERT/UPDATE/commit. Ningún efecto secundario.

⚠️ VISTA A ES DELIBERADAMENTE BRUTA — NO NETEA NC NI ANULACIONES. (No es un bug.)
   Vista A = dinero que ENTRÓ (recaudación). El neteo de Notas de Crédito / anulaciones
   vive EXCLUSIVAMENTE en Vista B (Paso 3). Por eso Vista A (caja física) == el total
   BRUTO del cierre de caja (total_cobros_*), que también es bruto. Si alguien "corrige"
   Vista A para que reste NC, ROMPE el cuadre contra el cierre. NO tocar.

Paso 2 (este): VISTA A — RECAUDACIÓN REAL (payments por fecha de pago).
  - Filtra payments approved por created_at (fecha en que entró el dinero).
  - Normaliza casing de payment_method (Yape/yape, etc.).
  - Mixtos: reparte por payment_splits (metodo, monto).
  - Dos ejes independientes que suman al total: por_metodo y por_concepto.
  - Puente de conciliación (D2): total − externos − portal_openpay −
    sin_comprobante = recaudación caja física (== suma de cierres).

Decisiones (confirmadas por Duilio):
  D2 puente explícito · D3 solo approved · D4 reparto completo por concepto · D5 admin+secretaría.
"""
from __future__ import annotations
from datetime import date, datetime, timedelta, timezone
from collections import defaultdict
import base64
import json
import re

from sqlalchemy import text
from sqlalchemy.orm import Session

PERU_TZ = timezone(timedelta(hours=-5))
ORG_DEFAULT = 1

# Igual que el cierre de caja (caja.py:_METODOS_EFECTIVO) — para clasificar ef/digital.
METODOS_EFECTIVO = {"efectivo", "cash", "en efectivo"}
# Orígenes que NO son caja física (se separan en el puente de conciliación).
ORIGEN_EXTERNO = "externo_comunicado"
ORIGEN_PORTAL = "portal_openpay"

_RE_B64 = re.compile(r"\[CONCEPTOS_B64:([A-Za-z0-9+/=]+)\]")

# Mapa debt_type -> categoría de reporte (cuando no hay concepto_cobro_id).
_DEBTTYPE_CAT = {
    "cuota_ordinaria": "cuotas",
    "cuota_extraordinaria": "extraordinarias",
    "multa": "multas",
    "fraccionamiento": "fraccionamiento",
    "evento": "eventos",
}


def _norm_metodo(m: str | None) -> str:
    """Normaliza el método (casing sucio: 'Yape'->'yape', etc.)."""
    return (m or "efectivo").strip().lower()


def _dia_peru_a_utc(d: date) -> datetime:
    """Inicio del día (00:00 hora Perú) de la fecha d, en UTC."""
    return datetime(d.year, d.month, d.day, tzinfo=PERU_TZ).astimezone(timezone.utc)


def _es_efectivo(metodo: str) -> bool:
    return _norm_metodo(metodo) in METODOS_EFECTIVO


# ──────────────────────────────────────────────────────────────────────────
# CLASIFICACIÓN POR CONCEPTO (reparto completo por amount_applied + B64)
# ──────────────────────────────────────────────────────────────────────────
def _categoria_por_concepto_id(db: Session, concepto_ids: set[int]) -> dict[int, str]:
    if not concepto_ids:
        return {}
    rows = db.execute(text(
        "SELECT id, categoria FROM conceptos_cobro WHERE id = ANY(:ids)"
    ), {"ids": list(concepto_ids)}).fetchall()
    return {r.id: (r.categoria or "otros") for r in rows}


def _categoria_por_codigo(db: Session, codigos: set[str]) -> dict[str, str]:
    if not codigos:
        return {}
    rows = db.execute(text(
        "SELECT codigo, categoria FROM conceptos_cobro WHERE codigo = ANY(:cods)"
    ), {"cods": list(codigos)}).fetchall()
    return {r.codigo: (r.categoria or "otros") for r in rows}


def _reparto_concepto_de_pago(db, pago_id, monto_total, notes,
                              cache_cat_id, cache_cat_cod) -> list[tuple[str, float]]:
    """Reparte el monto de UN pago entre categorías.
    1) por payment_debts -> debts (amount_applied, debt_type/concepto_cobro_id);
    2) el remanente no cubierto por deudas -> parse [CONCEPTOS_B64] (constancias);
    3) lo que quede sin clasificar -> 'otros'. La suma SIEMPRE == monto_total."""
    filas = db.execute(text("""
        SELECT pd.amount_applied amt, d.debt_type, d.concepto_cobro_id
        FROM payment_debts pd JOIN debts d ON d.id = pd.debt_id
        WHERE pd.payment_id = :p
    """), {"p": pago_id}).fetchall()

    acc = defaultdict(float)
    cubierto = 0.0
    for f in filas:
        amt = float(f.amt or 0)
        if amt <= 0:
            continue
        cat = None
        if f.concepto_cobro_id and f.concepto_cobro_id in cache_cat_id:
            cat = cache_cat_id[f.concepto_cobro_id]
        if not cat:
            cat = _DEBTTYPE_CAT.get(f.debt_type, "otros")
        acc[cat] += amt
        cubierto += amt

    resto = round(float(monto_total) - cubierto, 2)
    if resto > 0.009:
        # conceptos sin deuda (constancias genera_deuda=False) via [CONCEPTOS_B64]
        clasificado_b64 = 0.0
        m = _RE_B64.search(notes or "")
        if m:
            try:
                data = json.loads(base64.b64decode(m.group(1)).decode("utf-8"))
                for it in data:
                    mt = float(it.get("monto_total") or 0)
                    cod = (it.get("codigo") or "").strip()
                    cat = cache_cat_cod.get(cod, "constancias" if cod.startswith("CONST") else "otros")
                    if mt > 0:
                        acc[cat] += mt
                        clasificado_b64 += mt
            except Exception:
                pass
        sobrante = round(resto - clasificado_b64, 2)
        if sobrante > 0.009:
            acc["otros"] += sobrante
    return [(c, round(v, 2)) for c, v in acc.items()]


# ──────────────────────────────────────────────────────────────────────────
# FUNCIÓN PRINCIPAL (Vista A)
# ──────────────────────────────────────────────────────────────────────────
def generar_reporte_ventas(db: Session, desde: date, hasta: date,
                           filtros: dict | None = None,
                           organization_id: int = ORG_DEFAULT) -> dict:
    """Vista A — recaudación real. 100% lectura.
    filtros opcionales: {'metodo','concepto','origen'} (None/'todos' = sin filtro)."""
    filtros = filtros or {}
    f_metodo = (filtros.get("metodo") or "todos").strip().lower()
    f_origen = (filtros.get("origen") or "todos").strip().lower()
    f_concepto = (filtros.get("concepto") or "todos").strip().lower()

    ini_utc = _dia_peru_a_utc(desde)
    fin_utc = _dia_peru_a_utc(hasta + timedelta(days=1))  # exclusivo

    pagos = db.execute(text("""
        SELECT p.id, p.amount, p.payment_method, p.operation_code, p.origen,
               p.colegiado_id, p.notes, p.created_at,
               c.codigo_matricula, c.apellidos_nombres, c.dni,
               (cmp.serie IS NOT NULL) tiene_comprobante,
               cmp.serie cmp_serie, cmp.numero cmp_numero,
               cmp.status cmp_status, cmp.sunat_response_code cmp_code
        FROM payments p
        LEFT JOIN colegiados c ON c.id = p.colegiado_id
        LEFT JOIN LATERAL (
            SELECT cp.serie, cp.numero, cp.status, cp.sunat_response_code, cp.created_at
            FROM comprobantes cp
            WHERE cp.payment_id = p.id AND cp.tipo IN ('01','03')
            ORDER BY cp.created_at DESC LIMIT 1
        ) cmp ON TRUE
        WHERE p.organization_id = :org
          AND p.status = 'approved'
          AND p.created_at >= :ini AND p.created_at < :fin
        ORDER BY p.created_at
    """), {"org": organization_id, "ini": ini_utc, "fin": fin_utc}).fetchall()

    # splits de los mixtos del rango (una sola query)
    ids = [p.id for p in pagos]
    splits = defaultdict(list)
    if ids:
        for s in db.execute(text("""
            SELECT payment_id, metodo, monto FROM payment_splits WHERE payment_id = ANY(:ids)
        """), {"ids": ids}).fetchall():
            splits[s.payment_id].append((s.metodo, float(s.monto or 0)))

    # caches de categoría
    cids = set()
    for pid in ids:
        pass
    cids = {r.concepto_cobro_id for r in db.execute(text("""
        SELECT DISTINCT d.concepto_cobro_id FROM payment_debts pd JOIN debts d ON d.id=pd.debt_id
        WHERE pd.payment_id = ANY(:ids) AND d.concepto_cobro_id IS NOT NULL
    """), {"ids": ids or [0]}).fetchall()}
    cache_cat_id = _categoria_por_concepto_id(db, cids)
    # códigos B64 posibles (constancias)
    cods = set()
    for p in pagos:
        m = _RE_B64.search(p.notes or "")
        if m:
            try:
                for it in json.loads(base64.b64decode(m.group(1)).decode("utf-8")):
                    cod = (it.get("codigo") or "").strip()
                    if cod:
                        cods.add(cod)
            except Exception:
                pass
    cache_cat_cod = _categoria_por_codigo(db, cods)

    # Acumuladores
    por_metodo = defaultdict(lambda: {"cantidad": 0, "total": 0.0})
    por_concepto = defaultdict(lambda: {"total": 0.0})
    por_dia = defaultdict(lambda: {"ops": 0, "recaudado": 0.0})
    detalle = []
    total = 0.0
    # Ajuste 1: el mixto reparte su dinero a los métodos del desglose, así que su fila
    # en por_metodo queda en total=0. Para que no confunda a quien lee, se lleva aparte
    # su monto real como REFERENCIA (no suma de nuevo; es informativo).
    mixto_ops = 0
    mixto_monto = 0.0
    # puente de conciliación
    tot_externo = tot_portal = tot_sin_comp = 0.0

    for p in pagos:
        monto = float(p.amount or 0)
        origen = (p.origen or "caja_fisica")
        metodo_raw = _norm_metodo(p.payment_method)

        # filtro origen
        if f_origen not in ("todos", ""):
            # mapear etiqueta de filtro a valor real
            mapa = {"caja-arqueo": "caja_fisica", "caja_fisica": "caja_fisica",
                    "externo-comunicado": ORIGEN_EXTERNO, "externo_comunicado": ORIGEN_EXTERNO,
                    "contingencia": "contingencia", "portal": ORIGEN_PORTAL, "portal_openpay": ORIGEN_PORTAL}
            if origen != mapa.get(f_origen, f_origen):
                continue

        # ── eje MÉTODO (mixto -> splits; simple -> método) ──
        if metodo_raw == "mixto" and splits.get(p.id):
            medios = [(_norm_metodo(m), mo) for m, mo in splits[p.id]]
        else:
            medios = [(metodo_raw, monto)]
        # filtro método (sobre el método simple; para mixto, si alguno coincide se incluye entero)
        if f_metodo not in ("todos", ""):
            met_set = {m for m, _ in medios}
            if f_metodo not in met_set and not (f_metodo == "mixto" and metodo_raw == "mixto"):
                continue

        # ── eje CONCEPTO (reparto completo) ──
        reparto = _reparto_concepto_de_pago(db, p.id, monto, p.notes, cache_cat_id, cache_cat_cod)
        if f_concepto not in ("todos", ""):
            cats = {c for c, _ in reparto}
            if f_concepto not in cats:
                continue

        # acumular (pasó todos los filtros)
        total += monto
        for met, mo in medios:
            por_metodo[met]["total"] += mo
        por_metodo[medios[0][0] if metodo_raw != "mixto" else "mixto"]["cantidad"] += 1
        if metodo_raw == "mixto":
            mixto_ops += 1
            mixto_monto += monto
        for cat, mo in reparto:
            por_concepto[cat]["total"] += mo
        dkey = p.created_at.astimezone(PERU_TZ).strftime("%Y-%m-%d")
        por_dia[dkey]["ops"] += 1
        por_dia[dkey]["recaudado"] += monto

        # puente de conciliación
        if origen == ORIGEN_EXTERNO:
            tot_externo += monto
        elif origen == ORIGEN_PORTAL:
            tot_portal += monto
        elif not p.tiene_comprobante:
            tot_sin_comp += monto

        if p.cmp_serie:
            comp_sn = f"{p.cmp_serie}-{p.cmp_numero}"
            sin_cdr = (p.cmp_code is None or str(p.cmp_code).strip() == "")
            estado_sunat = (p.cmp_status or "?") + (" (sin CDR confirmado)"
                            if sin_cdr and p.cmp_status != "anulado" else "")
        else:
            comp_sn, estado_sunat = "—", "sin comprobante"
        detalle.append({
            "fecha": dkey, "hora": p.created_at.astimezone(PERU_TZ).strftime("%H:%M"),
            "matricula": p.codigo_matricula, "colegiado": p.apellidos_nombres or "Público general",
            "dni": p.dni, "metodo": metodo_raw, "origen": origen,
            "tiene_comprobante": bool(p.tiene_comprobante),
            "comprobante": comp_sn, "estado_sunat": estado_sunat,
            "conceptos": ", ".join(sorted({c for c, _ in reparto})),
            "monto": round(monto, 2), "payment_id": p.id,
        })

    recaudacion_caja_fisica = round(total - tot_externo - tot_portal - tot_sin_comp, 2)

    # ── VISTA B + DETECTOR (Paso 3) ──
    vista_b = _generar_vista_b(db, ini_utc, fin_utc, organization_id)
    detector = _detectar_descuadres(db, ini_utc, fin_utc, organization_id,
                                    total_vista_a=round(total, 2),
                                    vista_b_neto=vista_b["neto"])

    return {
        "rango": {"desde": desde.isoformat(), "hasta": hasta.isoformat()},
        "generado": datetime.now(PERU_TZ).isoformat(),
        "totales": {
            "total_recaudado": round(total, 2),
            "n_operaciones": len(detalle),
        },
        "puente_conciliacion": {
            "total_vista_a": round(total, 2),
            "menos_externo_comunicado": round(tot_externo, 2),
            "menos_portal_openpay": round(tot_portal, 2),
            "menos_sin_comprobante": round(tot_sin_comp, 2),
            "recaudacion_caja_fisica": recaudacion_caja_fisica,
        },
        "por_metodo": {k: {"cantidad": v["cantidad"], "total": round(v["total"], 2)}
                       for k, v in sorted(por_metodo.items())},
        # Referencia del mixto (su dinero YA está repartido en los métodos de arriba;
        # esto es informativo para la pantalla, NO se vuelve a sumar).
        "mixto_referencia": {
            "operaciones": mixto_ops,
            "monto_total": round(mixto_monto, 2),
            "nota": (f"{mixto_ops} operación(es) mixta(s) por S/ {round(mixto_monto,2):.2f} — "
                     f"repartida(s) en los métodos de arriba (su fila 'mixto' muestra total 0 a propósito)."
                     if mixto_ops else "sin operaciones mixtas en el rango"),
        },
        "por_concepto": {k: round(v["total"], 2) for k, v in sorted(por_concepto.items())},
        "por_dia": {k: {"ops": v["ops"], "recaudado": round(v["recaudado"], 2)}
                    for k, v in sorted(por_dia.items())},
        "detalle": detalle,
        "vista_b": vista_b,
        "detector": detector,
    }


# ──────────────────────────────────────────────────────────────────────────
# VISTA B — COMPROBANTES EMITIDOS (Paso 3)
# ──────────────────────────────────────────────────────────────────────────
def _generar_vista_b(db: Session, ini_utc, fin_utc, organization_id: int) -> dict:
    """Comprobantes emitidos por fecha de EMISIÓN en el rango. Boletas/facturas suman,
    NC (tipo 07) restan. Estado = status local + marca 'sin CDR confirmado' cuando
    sunat_response_code es NULL (D1 — no afirmar aceptado sin respaldo real)."""
    rows = db.execute(text("""
        SELECT id, serie, numero, tipo, total, status, sunat_response_code,
               payment_id, comprobante_ref_id, cliente_num_doc, cliente_nombre,
               created_at
        FROM comprobantes
        WHERE organization_id = :org AND created_at >= :ini AND created_at < :fin
        ORDER BY created_at
    """), {"org": organization_id, "ini": ini_utc, "fin": fin_utc}).fetchall()

    boletas, notas = [], []
    tot_boletas = tot_nc = 0.0
    for r in rows:
        est = r.status or "?"
        sin_cdr = (r.sunat_response_code is None or str(r.sunat_response_code).strip() == "")
        estado_sunat = est + (" (sin CDR confirmado)" if sin_cdr and est != "anulado" else "")
        item = {"id": r.id, "serie_numero": f"{r.serie}-{r.numero}", "tipo": r.tipo,
                "total": round(float(r.total or 0), 2), "estado_sunat": estado_sunat,
                "sin_cdr_confirmado": bool(sin_cdr), "payment_id": r.payment_id,
                "afecta_id": r.comprobante_ref_id,
                "cliente": r.cliente_nombre or r.cliente_num_doc}
        if r.tipo == "07":
            notas.append(item); tot_nc += float(r.total or 0)
        else:
            boletas.append(item); tot_boletas += float(r.total or 0)

    return {
        "boletas": boletas, "notas_credito": notas,
        "total_boletas": round(tot_boletas, 2),
        "total_nc": round(tot_nc, 2),
        "neto": round(tot_boletas - tot_nc, 2),
        "n_boletas": len(boletas), "n_nc": len(notas),
    }


# ──────────────────────────────────────────────────────────────────────────
# DETECTOR DE DESCUADRES (Paso 3) — lista, no solo totaliza
# ──────────────────────────────────────────────────────────────────────────
def _detectar_descuadres(db: Session, ini_utc, fin_utc, organization_id: int,
                         total_vista_a: float, vista_b_neto: float) -> dict:
    """Dos causas, LISTADAS:
    (1) Pagos sin comprobante: entró dinero (payment approved) sin boleta tipo 01/03.
    (2) Comprobantes sin pago vigente: boleta tipo 01/03 cuyo pago está NULL o ANULADO
        (incluye el patrón Sosa/Ríos: rechazada+reemitida → la vieja queda con pago anulado).
    """
    # (1) pagos approved sin comprobante
    pagos_sc = db.execute(text("""
        SELECT p.id, p.amount, p.payment_method, p.origen, p.created_at,
               c.codigo_matricula, c.apellidos_nombres, c.dni
        FROM payments p LEFT JOIN colegiados c ON c.id = p.colegiado_id
        WHERE p.organization_id = :org AND p.status = 'approved'
          AND p.created_at >= :ini AND p.created_at < :fin
          AND NOT EXISTS (SELECT 1 FROM comprobantes cp WHERE cp.payment_id = p.id AND cp.tipo IN ('01','03'))
        ORDER BY p.created_at
    """), {"org": organization_id, "ini": ini_utc, "fin": fin_utc}).fetchall()

    # (2) boletas con pago NULL o no-approved
    comp_sp = db.execute(text("""
        SELECT cp.id, cp.serie, cp.numero, cp.total, cp.status, cp.sunat_response_code,
               cp.payment_id, cp.cliente_num_doc, cp.cliente_nombre, p.status pay_status
        FROM comprobantes cp LEFT JOIN payments p ON p.id = cp.payment_id
        WHERE cp.organization_id = :org AND cp.tipo IN ('01','03')
          AND cp.created_at >= :ini AND cp.created_at < :fin
          AND (cp.payment_id IS NULL OR p.status <> 'approved')
        ORDER BY cp.created_at
    """), {"org": organization_id, "ini": ini_utc, "fin": fin_utc}).fetchall()

    def _estado(r):
        sin = (r.sunat_response_code is None or str(r.sunat_response_code).strip() == "")
        return (r.status or "?") + (" (sin CDR confirmado)" if sin and r.status != "anulado" else "")

    l_pagos = [{"payment_id": r.id, "fecha": r.created_at.astimezone(PERU_TZ).strftime("%Y-%m-%d %H:%M"),
                "colegiado": r.apellidos_nombres or "Público general", "matricula": r.codigo_matricula,
                "dni": r.dni, "metodo": _norm_metodo(r.payment_method), "origen": r.origen,
                "monto": round(float(r.amount or 0), 2)} for r in pagos_sc]
    l_comp = [{"comprobante_id": r.id, "serie_numero": f"{r.serie}-{r.numero}",
               "monto": round(float(r.total or 0), 2), "estado_sunat": _estado(r),
               "payment_id": r.payment_id, "pago_status": (r.pay_status or "SIN PAGO"),
               "cliente": r.cliente_nombre or r.cliente_num_doc} for r in comp_sp]

    diferencia = round(total_vista_a - vista_b_neto, 2)
    return {
        "diferencia_A_menos_Bneto": diferencia,
        "cuadra": abs(diferencia) < 0.01 and not l_pagos and not l_comp,
        "pagos_sin_comprobante": {"cantidad": len(l_pagos),
                                  "monto": round(sum(x["monto"] for x in l_pagos), 2),
                                  "lista": l_pagos},
        "comprobantes_sin_pago": {"cantidad": len(l_comp),
                                  "monto": round(sum(x["monto"] for x in l_comp), 2),
                                  "lista": l_comp},
    }


# ──────────────────────────────────────────────────────────────────────────
# EXPORTACIÓN EXCEL (Paso 5) — reusa el estilo del Excel de aportes JDCCPP.
# Hojas: Resumen · Por método · Por concepto · Por día · Detalle · Anomalías · Metadata.
# 100% lectura (consume el objeto del servicio; no escribe nada).
# ──────────────────────────────────────────────────────────────────────────
def generar_excel_ventas(db: Session, desde: date, hasta: date,
                         filtros: dict | None = None, organization_id: int = ORG_DEFAULT) -> bytes:
    import io
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment

    rep = generar_reporte_ventas(db, desde, hasta, filtros, organization_id)
    AZUL = PatternFill("solid", fgColor="1E3A5F")
    ROJO = PatternFill("solid", fgColor="7F1D1D")
    VERDE = PatternFill("solid", fgColor="1E7A46")
    WB_ = Font(color="FFFFFF", bold=True)
    BOLD = Font(bold=True)

    def _hdr(ws, fila, cols, fill=AZUL):
        for j, c in enumerate(cols, start=1):
            cell = ws.cell(row=fila, column=j, value=c)
            cell.fill = fill; cell.font = WB_
            cell.alignment = Alignment(horizontal="left")

    wb = Workbook()

    # ── Resumen ──
    ws = wb.active; ws.title = "Resumen"
    ws["A1"] = f"Reporte de Ventas · {rep['rango']['desde']} a {rep['rango']['hasta']}"
    ws["A1"].font = Font(bold=True, size=14)
    t = rep["totales"]; vb = rep["vista_b"]; det = rep["detector"]; b = rep["puente_conciliacion"]
    kpis = [
        ("Total recaudado (Vista A)", t["total_recaudado"]),
        ("Total facturado neto (Vista B = boletas − NC)", vb["neto"]),
        ("Diferencia A − B", det["diferencia_A_menos_Bneto"]),
        ("N° operaciones", t["n_operaciones"]),
        ("N° boletas / N° NC", f"{vb['n_boletas']} / {vb['n_nc']}"),
        ("¿Cuadra (sin anomalías)?", "Sí" if det["cuadra"] else "NO — ver hoja Anomalías"),
    ]
    for i, (k, v) in enumerate(kpis, start=3):
        ws[f"A{i}"] = k; ws[f"B{i}"] = v; ws[f"A{i}"].font = BOLD
    if not det["cuadra"]:
        ws["B5"].fill = ROJO; ws["B5"].font = WB_
        ws["B8"].fill = ROJO; ws["B8"].font = WB_
    r0 = 11
    ws[f"A{r0}"] = "PUENTE DE CONCILIACIÓN"; ws[f"A{r0}"].font = BOLD
    puente = [
        ("Total Vista A (todo)", b["total_vista_a"]),
        ("(−) Externo comunicado", b["menos_externo_comunicado"]),
        ("(−) Portal OpenPay", b["menos_portal_openpay"]),
        ("(−) Pagos sin comprobante", b["menos_sin_comprobante"]),
        ("= Recaudación caja física (== suma de cierres)", b["recaudacion_caja_fisica"]),
    ]
    for i, (k, v) in enumerate(puente, start=r0 + 1):
        ws[f"A{i}"] = k; ws[f"B{i}"] = v
    ws[f"A{r0+5}"].font = BOLD; ws[f"B{r0+5}"].font = BOLD
    ws.column_dimensions["A"].width = 48; ws.column_dimensions["B"].width = 20

    # ── Por método ──
    ws = wb.create_sheet("Por método")
    _hdr(ws, 1, ["Método", "Cantidad", "Total S/"])
    i = 2
    for k, v in rep["por_metodo"].items():
        ws.cell(i, 1, k); ws.cell(i, 2, v["cantidad"]); ws.cell(i, 3, v["total"]); i += 1
    mr = rep.get("mixto_referencia") or {}
    if mr.get("operaciones"):
        ws.cell(i + 1, 1, "Nota mixto:").font = BOLD
        ws.merge_cells(start_row=i + 1, start_column=2, end_row=i + 1, end_column=3)
        ws.cell(i + 1, 2, mr["nota"])
    ws.column_dimensions["A"].width = 18; ws.column_dimensions["B"].width = 12; ws.column_dimensions["C"].width = 16

    # ── Por concepto ──
    ws = wb.create_sheet("Por concepto")
    _hdr(ws, 1, ["Concepto", "Total S/"])
    for i, (k, v) in enumerate(rep["por_concepto"].items(), start=2):
        ws.cell(i, 1, k); ws.cell(i, 2, v)
    ws.column_dimensions["A"].width = 22; ws.column_dimensions["B"].width = 16

    # ── Por día ──
    ws = wb.create_sheet("Por día")
    _hdr(ws, 1, ["Día", "Operaciones", "Recaudado S/"])
    for i, (k, v) in enumerate(rep["por_dia"].items(), start=2):
        ws.cell(i, 1, k); ws.cell(i, 2, v["ops"]); ws.cell(i, 3, v["recaudado"])
    ws.column_dimensions["A"].width = 14; ws.column_dimensions["B"].width = 14; ws.column_dimensions["C"].width = 16

    # ── Detalle ──
    ws = wb.create_sheet("Detalle")
    _hdr(ws, 1, ["Fecha", "Hora", "Matrícula", "Colegiado", "DNI", "Concepto(s)",
                 "Método", "Comprobante", "Estado SUNAT", "Origen", "Monto S/"])
    for i, r in enumerate(rep["detalle"], start=2):
        ws.cell(i, 1, r["fecha"]); ws.cell(i, 2, r["hora"]); ws.cell(i, 3, r["matricula"])
        ws.cell(i, 4, r["colegiado"]); ws.cell(i, 5, r["dni"]); ws.cell(i, 6, r["conceptos"])
        ws.cell(i, 7, r["metodo"]); ws.cell(i, 8, r["comprobante"]); ws.cell(i, 9, r["estado_sunat"])
        ws.cell(i, 10, r["origen"]); ws.cell(i, 11, r["monto"])
    for col, w in zip("ABCDEFGHIJK", [11, 7, 11, 30, 11, 26, 13, 12, 26, 18, 12]):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"

    # ── Anomalías (HOJA DEDICADA — lo más valioso para auditoría) ──
    ws = wb.create_sheet("Anomalías")
    ws["A1"] = "DETECTOR DE DESCUADRES"; ws["A1"].font = Font(bold=True, size=13)
    ws["A2"] = f"Diferencia Vista A − Vista B neto: S/ {det['diferencia_A_menos_Bneto']:.2f}"
    ws["A2"].font = BOLD
    psc = det["pagos_sin_comprobante"]; csp = det["comprobantes_sin_pago"]
    r = 4
    ws.cell(r, 1, f"PAGOS SIN COMPROBANTE — {psc['cantidad']} (S/ {psc['monto']:.2f}): entró dinero, no hay boleta").font = BOLD
    r += 1
    _hdr(ws, r, ["Fecha", "Matrícula", "Colegiado", "DNI", "Método", "Origen", "Monto S/"], ROJO)
    r += 1
    for x in psc["lista"]:
        ws.cell(r, 1, x["fecha"]); ws.cell(r, 2, x["matricula"]); ws.cell(r, 3, x["colegiado"])
        ws.cell(r, 4, x["dni"]); ws.cell(r, 5, x["metodo"]); ws.cell(r, 6, x["origen"]); ws.cell(r, 7, x["monto"]); r += 1
    r += 1
    ws.cell(r, 1, f"COMPROBANTES SIN PAGO VIGENTE — {csp['cantidad']} (S/ {csp['monto']:.2f}): boleta sin pago approved (rechazadas/reemitidas, patrón Sosa/Ríos)").font = BOLD
    r += 1
    _hdr(ws, r, ["Comprobante", "Cliente", "Estado SUNAT", "Pago", "Monto S/"], ROJO)
    r += 1
    for x in csp["lista"]:
        ws.cell(r, 1, x["serie_numero"]); ws.cell(r, 2, x["cliente"]); ws.cell(r, 3, x["estado_sunat"])
        ws.cell(r, 4, x["pago_status"]); ws.cell(r, 5, x["monto"]); r += 1
    for col, w in zip("ABCDEFG", [22, 30, 28, 14, 14, 18, 12]):
        ws.column_dimensions[col].width = w

    # ── Metadata ──
    ws = wb.create_sheet("Metadata")
    meta = [
        ("Reporte", "Ventas por Rango de Fechas"),
        ("Rango", f"{rep['rango']['desde']} a {rep['rango']['hasta']}"),
        ("Generado", rep["generado"]),
        ("Filtros", str(filtros or {"metodo": "todos", "concepto": "todos", "origen": "todos"})),
        ("Total recaudado (Vista A)", t["total_recaudado"]),
        ("Facturado neto (Vista B)", vb["neto"]),
        ("Operaciones / Boletas / NC", f"{t['n_operaciones']} / {vb['n_boletas']} / {vb['n_nc']}"),
        ("Alcance", "100% lectura — sin efectos secundarios"),
        ("Sistema", "CCPL · Perú Sistemas Pro"),
    ]
    for i, (k, v) in enumerate(meta, start=1):
        ws.cell(i, 1, k).font = BOLD; ws.cell(i, 2, v)
    ws.column_dimensions["A"].width = 30; ws.column_dimensions["B"].width = 48

    out = io.BytesIO(); wb.save(out)
    return out.getvalue()


# ──────────────────────────────────────────────────────────────────────────
# EXPORTACIÓN PDF (Paso 6) — reusa el estilo del PDF de aportes (reportlab).
# Encabezado CCPL + totales + puente + 3 resúmenes + detector (resumido) + pie PSP.
# El detalle op-por-op NO va en PDF (nota: ver Excel). 100% lectura.
# ──────────────────────────────────────────────────────────────────────────
def generar_pdf_ventas(db: Session, desde: date, hasta: date,
                       filtros: dict | None = None, organization_id: int = ORG_DEFAULT,
                       usuario: str = "-") -> bytes:
    import io
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

    rep = generar_reporte_ventas(db, desde, hasta, filtros, organization_id)
    t = rep["totales"]; vb = rep["vista_b"]; det = rep["detector"]; b = rep["puente_conciliacion"]
    AZUL = colors.HexColor("#1e3a5f"); ROJO = colors.HexColor("#b91c1c"); VERDE = colors.HexColor("#15803d")
    GRIS = colors.HexColor("#f1f5f9")
    _S = lambda n: f"S/ {float(n or 0):,.2f}"

    def _footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7); canvas.setFillColor(colors.grey)
        canvas.drawString(16 * mm, 9 * mm, "Generado por el sistema del CCPL - Peru Sistemas Pro")
        canvas.drawRightString(A4[0] - 16 * mm, 9 * mm, f"Pagina {doc.page}")
        canvas.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=16 * mm, bottomMargin=16 * mm,
                            leftMargin=16 * mm, rightMargin=16 * mm)
    st = getSampleStyleSheet()
    H = ParagraphStyle("H", parent=st["Title"], fontSize=14)
    SUB = ParagraphStyle("SUB", parent=st["Normal"], fontSize=10.5, alignment=1)
    SMALL = ParagraphStyle("SMALL", parent=st["Normal"], fontSize=8, textColor=colors.grey, alignment=1)
    HD = ParagraphStyle("HD", parent=st["Heading4"], textColor=AZUL)

    def _tbl(data, widths, header=True):
        tb = Table(data, colWidths=widths, repeatRows=1 if header else 0)
        style = [("FONTSIZE", (0, 0), (-1, -1), 8.5),
                 ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
                 ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, GRIS]),
                 ("ALIGN", (-1, 0), (-1, -1), "RIGHT"),
                 ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
        if header:
            style += [("BACKGROUND", (0, 0), (-1, 0), AZUL), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                      ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold")]
        tb.setStyle(TableStyle(style))
        return tb

    el = []
    el.append(Paragraph("COLEGIO DE CONTADORES PUBLICOS DE LORETO", H))
    el.append(Paragraph("Reporte de Ventas por Rango de Fechas", SUB))
    _now = datetime.now(PERU_TZ)
    el.append(Paragraph(
        f"Rango: {rep['rango']['desde']} a {rep['rango']['hasta']} &middot; "
        f"Generado: {_now.strftime('%d/%m/%Y %H:%M')} &middot; Usuario: {usuario}", SMALL))
    el.append(Spacer(1, 7 * mm))

    difcolor = ROJO if (abs(det["diferencia_A_menos_Bneto"]) >= 0.01 or not det["cuadra"]) else VERDE
    tot = [["Total recaudado (Vista A)", _S(t["total_recaudado"])],
           ["Total facturado neto (Vista B = boletas - NC)", _S(vb["neto"])],
           ["Diferencia A - B", _S(det["diferencia_A_menos_Bneto"])],
           [f"Operaciones: {t['n_operaciones']}   Boletas: {vb['n_boletas']}   NC: {vb['n_nc']}", ""]]
    tt = Table(tot, colWidths=[120 * mm, 50 * mm])
    tt.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 10), ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTNAME", (0, 0), (0, 0), "Helvetica-Bold"),
        ("TEXTCOLOR", (1, 2), (1, 2), difcolor), ("FONTNAME", (1, 2), (1, 2), "Helvetica-Bold"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#cbd5e1")),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    el.append(tt); el.append(Spacer(1, 6 * mm))

    el.append(Paragraph("PUENTE DE CONCILIACION", HD))
    pu = [["Total Vista A (todo)", _S(b["total_vista_a"])],
          ["(-) Externo comunicado", _S(b["menos_externo_comunicado"])],
          ["(-) Portal OpenPay", _S(b["menos_portal_openpay"])],
          ["(-) Pagos sin comprobante", _S(b["menos_sin_comprobante"])],
          ["= Recaudacion caja fisica (== suma de cierres)", _S(b["recaudacion_caja_fisica"])]]
    pt = Table(pu, colWidths=[120 * mm, 50 * mm])
    pt.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 9), ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LINEABOVE", (0, -1), (-1, -1), 1, colors.black), ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    el.append(pt); el.append(Spacer(1, 6 * mm))

    el.append(Paragraph("POR METODO DE PAGO", HD))
    dm = [["Metodo", "Cantidad", "Total"]] + [[k, str(v["cantidad"]), _S(v["total"])]
                                             for k, v in rep["por_metodo"].items()]
    el.append(_tbl(dm, [60 * mm, 30 * mm, 40 * mm]))
    mr = rep.get("mixto_referencia") or {}
    if mr.get("operaciones"):
        el.append(Paragraph(f"Nota: {mr['nota']}", SMALL))
    el.append(Spacer(1, 5 * mm))

    el.append(Paragraph("POR CONCEPTO", HD))
    dc = [["Concepto", "Total"]] + [[k, _S(v)] for k, v in rep["por_concepto"].items()]
    el.append(_tbl(dc, [90 * mm, 40 * mm])); el.append(Spacer(1, 5 * mm))

    el.append(Paragraph("POR DIA", HD))
    dd = [["Dia", "Operaciones", "Recaudado"]] + [[k, str(v["ops"]), _S(v["recaudado"])]
                                                 for k, v in rep["por_dia"].items()]
    el.append(_tbl(dd, [50 * mm, 40 * mm, 40 * mm])); el.append(Spacer(1, 6 * mm))

    el.append(Paragraph("DETECTOR DE DESCUADRES", HD))
    if det["cuadra"]:
        el.append(Paragraph("<b>Sin anomalias</b> - cada pago tiene su comprobante y cada comprobante su pago vigente. Diferencia 0.",
                            ParagraphStyle("ok", parent=st["Normal"], textColor=VERDE, fontSize=10)))
    else:
        psc = det["pagos_sin_comprobante"]; csp = det["comprobantes_sin_pago"]
        el.append(Paragraph(f"<b>Pagos sin comprobante: {psc['cantidad']} ({_S(psc['monto'])})</b> - entro dinero, no hay boleta",
                            ParagraphStyle("a1", parent=st["Normal"], textColor=ROJO, fontSize=9.5)))
        if psc["cantidad"]:
            lim = psc["lista"][:40]
            d1 = [["Fecha", "Colegiado", "Metodo", "Origen", "Monto"]] + \
                 [[x["fecha"], (x["colegiado"] or "")[:34], x["metodo"], x["origen"], _S(x["monto"])] for x in lim]
            el.append(_tbl(d1, [32 * mm, 58 * mm, 24 * mm, 32 * mm, 24 * mm]))
            if len(psc["lista"]) > 40:
                el.append(Paragraph(f"...y {len(psc['lista'])-40} mas - ver Excel.", SMALL))
        el.append(Spacer(1, 3 * mm))
        el.append(Paragraph(f"<b>Comprobantes sin pago vigente: {csp['cantidad']} ({_S(csp['monto'])})</b> - boleta rechazada/reemitida (patron Sosa/Rios)",
                            ParagraphStyle("a2", parent=st["Normal"], textColor=ROJO, fontSize=9.5)))
        if csp["cantidad"]:
            lim = csp["lista"][:40]
            _cell = ParagraphStyle("cell", parent=st["Normal"], fontSize=8, leading=9.5)
            d2 = [["Comprobante", "Cliente", "Estado SUNAT", "Pago", "Monto"]] + \
                 [[x["serie_numero"], Paragraph((x["cliente"] or "")[:34], _cell),
                   Paragraph(x["estado_sunat"], _cell), x["pago_status"], _S(x["monto"])] for x in lim]
            el.append(_tbl(d2, [26 * mm, 44 * mm, 42 * mm, 20 * mm, 24 * mm]))
            if len(csp["lista"]) > 40:
                el.append(Paragraph(f"...y {len(csp['lista'])-40} mas - ver Excel.", SMALL))
    el.append(Spacer(1, 6 * mm))
    el.append(Paragraph("El detalle operacion por operacion no se incluye en el PDF. Ver el Excel para el detalle completo.",
                        ParagraphStyle("nota", parent=st["Normal"], fontSize=9, textColor=colors.grey)))

    doc.build(el, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()

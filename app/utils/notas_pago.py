"""
app/utils/notas_pago.py
Formateo LEGIBLE de payment.notes para mostrar al humano (cajera/admin).

El dato crudo tiene marcadores internos ([CAJA]/[SECRETARIA]/[DEBT_IDS]/[CONCEPTOS_B64]/
[ANULADO]/[PARCIAL]) que NO deben verse. Esta función los oculta y arma un resumen
legible y COMPLETO (sin "(+N más)"), colapsando periodos en rangos ("Ene–Oct 2026").

NO modifica notes: los marcadores siguen en la BD (los usan anulación/conciliación);
esto solo formatea para la vista. Fuente única — usada por caja, secretaría,
pagos externos y conciliación.
"""
import re
import base64
import json

_RE_DEBT_IDS = re.compile(r"\[DEBT_IDS:([0-9,\s]+)\]")
_RE_B64 = re.compile(r"\[CONCEPTOS_B64:([A-Za-z0-9+/=]+)\]")
# marcadores/etiquetas a quitar del texto humano
_RE_MARCADORES = re.compile(
    r"\[CAJA\]\s*|\[SECRETARIA\][^\-]*-\s*|\[DEBT_IDS:[0-9,\s]*\]|"
    r"\[CONCEPTOS_B64:[A-Za-z0-9+/=]*\]|\[ANULADO\][^\[]*|\[NC PARCIAL[^\]]*\]|\[PARCIAL\]|\[REFIN\][^\[]*",
    re.IGNORECASE,
)
_RE_YEAR = re.compile(r"\s*20\d\d\s*$")
# "Bingazo 2026 2026" → "Bingazo 2026" ; "Enero 2026 2026-01" → "Enero 2026"
_RE_DUP_PERIODO = re.compile(r"(20\d\d)\s+20\d\d(?:-\d\d)?\b")

_MESES = {1: "Ene", 2: "Feb", 3: "Mar", 4: "Abr", 5: "May", 6: "Jun",
          7: "Jul", 8: "Ago", 9: "Set", 10: "Oct", 11: "Nov", 12: "Dic"}
_MES_NOMBRE = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}


def mapa_deudas_para_notas(db, notes_list, organization_id=1):
    """Query BATCH: junta los DEBT_IDS de varias notas y trae {id: {cc, periodo, period_label}}
    (cc = nombre corto del concepto_cobro). Se pasa a descripcion_legible() para el resumen."""
    from sqlalchemy import text as _text
    ids = set()
    for n in (notes_list or []):
        ids.update(debt_ids_de_notes(n))
    if not ids:
        return {}
    rows = db.execute(_text("""
        SELECT d.id, d.concept, d.periodo, d.period_label, d.amount,
               COALESCE(cc.nombre_corto, cc.nombre) AS cc
        FROM debts d LEFT JOIN conceptos_cobro cc ON cc.id = d.concepto_cobro_id
        WHERE d.id = ANY(:ids)
    """), {"ids": list(ids)}).fetchall()
    return {r.id: {"cc": r.cc or r.concept, "periodo": r.periodo,
                   "period_label": r.period_label, "concept": r.concept,
                   "monto": float(r.amount or 0)} for r in rows}


def conceptos_detalle(notes, debts_por_id=None):
    """DETALLE COMPLETO (para expandir): [{concepto, period_label, monto}] por cada deuda
    del pago. NUNCA oculta conceptos — la lista completa siempre disponible."""
    out = []
    if not debts_por_id:
        return out
    for did in debt_ids_de_notes(notes):
        info = debts_por_id.get(did) or debts_por_id.get(str(did))
        if not info:
            continue
        out.append({"concepto": info.get("concept") or info.get("cc") or "Concepto",
                    "period_label": info.get("period_label") or "",
                    "monto": float(info.get("monto") or 0)})
    return out


def debt_ids_de_notes(notes):
    """Extrae los debt_id embebidos en [DEBT_IDS:...]."""
    out = []
    m = _RE_DEBT_IDS.search(notes or "")
    if m:
        for x in m.group(1).split(","):
            x = x.strip()
            if x.isdigit():
                out.append(int(x))
    return out


def _ym(periodo, period_label):
    """(año, mes|None) desde periodo 'YYYY-MM'/'YYYY' o period_label 'Enero 2026'."""
    p = (periodo or "").strip()
    m = re.match(r"^(20\d\d)-(\d{2})$", p)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.match(r"^(20\d\d)$", p)
    if m:
        return int(m.group(1)), None
    pl = (period_label or "").lower()
    my = re.search(r"(20\d\d)", pl)
    year = int(my.group(1)) if my else None
    mes = None
    for nombre, num in _MES_NOMBRE.items():
        if nombre in pl:
            mes = num
            break
    return year, mes


def _base_concepto(cc):
    """Nombre base del concepto sin el año final ('… Bingazo 2026' → '… Bingazo')."""
    return _RE_YEAR.sub("", (cc or "").strip()).strip() or (cc or "").strip()


def _resumen_grupo(base, items):
    """items = lista de (año, mes, period_label). Devuelve 'Base Ene–Oct 2026'."""
    yms = [(y, m) for (y, m, _pl) in items if y]
    if not yms:
        # sin año parseable → usa el period_label del primero
        pl = items[0][2] if items else ""
        return (base + " " + pl).strip() if pl else base
    years = sorted({y for (y, _m) in yms})
    meses = sorted({m for (_y, m) in yms if m})
    if len(years) == 1:
        y = years[0]
        if len(meses) >= 2:
            return f"{base} {_MESES.get(meses[0], '?')}–{_MESES.get(meses[-1], '?')} {y}"
        if len(meses) == 1:
            return f"{base} {_MESES.get(meses[0], '?')} {y}"
        return f"{base} {y}"
    return f"{base} {years[0]}–{years[-1]}"


def _pelar(notes):
    """Fallback: quita marcadores + colapsa periodo duplicado."""
    txt = _RE_MARCADORES.sub("", notes or "")
    txt = _RE_DUP_PERIODO.sub(r"\1", txt)
    txt = re.sub(r"\s{2,}", " ", txt).strip(" ;·-")
    return txt.strip() or "Pago"


def descripcion_legible(notes, debts_por_id=None):
    """Texto legible y completo de un pago. `debts_por_id` = {id: {cc, periodo, period_label}}
    (lo arma el caller con una query batch). Prioridad: DEBT_IDS→resumen por concepto con
    rangos · CONCEPTOS_B64 · fallback pelado."""
    notes = notes or ""

    # 1) DEBT_IDS → resumen por concepto con rangos (lista completa)
    ids = debt_ids_de_notes(notes)
    if ids and debts_por_id:
        grupos = {}  # base → [(año, mes, period_label)]
        total = 0
        for did in ids:
            info = debts_por_id.get(did) or debts_por_id.get(str(did))
            if not info:
                continue
            total += 1
            base = _base_concepto(info.get("cc") or info.get("concept") or "Concepto")
            y, m = _ym(info.get("periodo"), info.get("period_label"))
            grupos.setdefault(base, []).append((y, m, info.get("period_label") or ""))
        if grupos:
            partes = [_resumen_grupo(b, its) for b, its in grupos.items()]
            resumen = " + ".join(partes)
            if total > 1:
                resumen += f" ({total} conceptos)"
            return resumen

    # 2) CONCEPTOS_B64 (conceptos sin deuda: constancias, etc.)
    m = _RE_B64.search(notes)
    if m:
        try:
            data = json.loads(base64.b64decode(m.group(1)).decode("utf-8"))
            partes = []
            for it in (data if isinstance(data, list) else []):
                nombre = (it.get("nombre") or "Concepto").strip()
                try:
                    cant = int(it.get("cantidad") or 1)
                except Exception:
                    cant = 1
                partes.append(f"{nombre} (x{cant})" if cant > 1 else nombre)
            if partes:
                return " · ".join(partes)
        except Exception:
            pass

    # 3) fallback pelado
    return _pelar(notes)

# -*- coding: utf-8 -*-
"""
colegiados_padron_service.py — Dominio COLEGIADOS (padrón vivo) del Mega Módulo.

Pedido del Consejo Directivo (vía Limber): exportar la lista de hábiles/inhábiles
del padrón. INDEPENDIENTE de Aportes Junta: aquí se consulta/exporta el padrón VIVO
de hoy (campo colegiados.condicion), sin relación con el corte/congelado de la Junta.

Fuente de verdad ÚNICA: una función por salida que consume el MISMO padrón.
100% LECTURA. Ningún INSERT/UPDATE/commit. NO toca la condición de nadie.

── Composición (Paso 0, verificado 2026-10-29) ──
El padrón parte LIMPIO: habil 1332 · inhabil 889 · vitalicio 143 · fallecido 133 ·
retirado 4 · suspendido 4 = 2505 (= total, 0 sin clasificar, 0 NULL).
'Past Decano' NO es una condición real: es VIRTUAL (se guarda como condicion='habil'
+ aporta_jdccpp=FALSE + aporta_jdccpp_motivo='Past Decano'). Se deriva del motivo y se
muestra como SUBCONJUNTO de los hábiles (no se suma al total — no doble-contar).
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

PERU_TZ = timezone(timedelta(hours=-5))
ORG_DEFAULT = 1

# Buckets que PARTICIONAN el padrón (su suma == total). Orden de presentación.
_BUCKETS = [
    ("habil",      "Hábiles"),
    ("inhabil",    "Inhábiles"),
    ("vitalicio",  "Vitalicios"),
    ("fallecido",  "Fallecidos"),
    ("retirado",   "Retirados"),
    ("suspendido", "Suspendidos"),
]
_LABELS = dict(_BUCKETS)
_LABELS["candidato_retiro"] = "Candidato a retiro"
_LABELS["past_decano"] = "Past Decano"

_SINGULAR = {
    "habil": "Hábil", "inhabil": "Inhábil", "vitalicio": "Vitalicio",
    "fallecido": "Fallecido", "retirado": "Retirado", "suspendido": "Suspendido",
    "candidato_retiro": "Candidato a retiro",
}

# Filtros de condición aceptados por la pantalla/export (incluye el virtual past_decano).
_FILTROS_VALIDOS = {"habil", "inhabil", "vitalicio", "fallecido", "retirado",
                    "suspendido", "candidato_retiro", "past_decano"}

_PAST_DECANO_SQL = ("condicion = 'habil' AND COALESCE(aporta_jdccpp, TRUE) = FALSE "
                    "AND aporta_jdccpp_motivo = 'Past Decano'")


def _where_filtros(filtros: dict | None):
    """Construye el WHERE (org + condición + búsqueda). Devuelve (sql, params, filtro_norm)."""
    filtros = filtros or {}
    cond = (filtros.get("condicion") or "todos").strip().lower()
    q = (filtros.get("q") or "").strip()
    where = ["organization_id = :org"]
    params = {"org": filtros.get("org", ORG_DEFAULT)}
    if cond in _FILTROS_VALIDOS:
        if cond == "past_decano":
            where.append(f"({_PAST_DECANO_SQL})")
        else:
            where.append("condicion = :cond")
            params["cond"] = cond
    else:
        cond = "todos"
    if q:
        where.append("(codigo_matricula ILIKE :q OR dni ILIKE :q OR apellidos_nombres ILIKE :q)")
        params["q"] = f"%{q}%"
    return " AND ".join(where), params, {"condicion": cond, "q": q}


def composicion_padron(db: Session, organization_id: int = ORG_DEFAULT) -> dict:
    """Conteo por estado (detector de composición). Suma de buckets debe == total."""
    org = {"org": organization_id}
    total = db.execute(text("SELECT COUNT(*) FROM colegiados WHERE organization_id = :org"),
                       org).scalar() or 0
    crudo = {row.condicion: row.n for row in db.execute(text(
        "SELECT condicion, COUNT(*) AS n FROM colegiados WHERE organization_id = :org "
        "GROUP BY condicion"), org)}
    buckets, suma = [], 0
    for key, label in _BUCKETS:
        n = int(crudo.get(key, 0))
        suma += n
        buckets.append({"key": key, "label": label, "n": n})
    # Cualquier condición fuera de la partición esperada = "sin clasificar / rara".
    otros = [{"condicion": k, "n": int(v)} for k, v in crudo.items()
             if k not in _LABELS]
    suma += sum(o["n"] for o in otros)
    sin_clasificar = int(total) - suma
    past_decano = db.execute(text(
        f"SELECT COUNT(*) FROM colegiados WHERE organization_id = :org AND ({_PAST_DECANO_SQL})"),
        org).scalar() or 0
    return {
        "total": int(total),
        "buckets": buckets,                      # particionan el padrón
        "past_decano": int(past_decano),         # SUBCONJUNTO de Hábiles (no se suma)
        "otros": otros,                          # condiciones inesperadas (deberían ser [])
        "sin_clasificar": int(sin_clasificar),   # total - suma; esperado 0
        "cuadra": sin_clasificar == 0 and not otros,
    }


def _fmt_fecha(v):
    if not v:
        return ""
    try:
        return v.strftime("%d/%m/%Y")
    except Exception:
        return str(v)[:10]


def _filas(db: Session, w: str, params: dict, limit: int | None = None, offset: int = 0):
    lo = ""
    p = dict(params)
    if limit is not None:
        lo = " LIMIT :lim OFFSET :off"
        p["lim"] = limit
        p["off"] = offset
    rows = db.execute(text(f"""
        SELECT codigo_matricula, apellidos_nombres, dni, condicion, fecha_colegiatura,
               COALESCE(aporta_jdccpp, TRUE) AS aporta, aporta_jdccpp_motivo AS motivo
        FROM colegiados WHERE {w}
        ORDER BY apellidos_nombres{lo}
    """), p).fetchall()
    out = []
    for r in rows:
        es_pd = (r.condicion == "habil" and not r.aporta and (r.motivo or "") == "Past Decano")
        out.append({
            "matricula": r.codigo_matricula or "",
            "apellidos_nombres": r.apellidos_nombres or "",
            "dni": r.dni or "",
            "condicion": r.condicion or "",
            "condicion_label": _SINGULAR.get(r.condicion, (r.condicion or "").capitalize()),
            "fecha_colegiatura": _fmt_fecha(r.fecha_colegiatura),
            "past_decano": es_pd,
        })
    return out


def generar_padron(db: Session, filtros: dict | None = None,
                   organization_id: int = ORG_DEFAULT, page: int = 1, per_page: int = 50) -> dict:
    """Objeto para la PANTALLA: composición + página del listado filtrado."""
    filtros = dict(filtros or {})
    filtros["org"] = organization_id
    w, params, fnorm = _where_filtros(filtros)
    page = max(1, int(page or 1))
    total_filtrado = db.execute(text(f"SELECT COUNT(*) FROM colegiados WHERE {w}"), params).scalar() or 0
    rows = _filas(db, w, params, limit=per_page, offset=(page - 1) * per_page)
    return {
        "composicion": composicion_padron(db, organization_id),
        "filtro": fnorm,
        "pagina": {
            "page": page,
            "per_page": per_page,
            "total": int(total_filtrado),
            "pages": (int(total_filtrado) + per_page - 1) // per_page if total_filtrado else 1,
        },
        "rows": rows,
        "generado": datetime.now(PERU_TZ).strftime("%d/%m/%Y %H:%M"),
    }


# ──────────────────────────────────────────────────────────────────────────
# EXCEL — estilo "Excel de la casa" (encabezado #1E3A5F). Lista filtrada COMPLETA.
# ──────────────────────────────────────────────────────────────────────────
def generar_excel_padron(db: Session, filtros: dict | None = None,
                         organization_id: int = ORG_DEFAULT) -> bytes:
    import io
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment

    filtros = dict(filtros or {})
    filtros["org"] = organization_id
    w, params, fnorm = _where_filtros(filtros)
    comp = composicion_padron(db, organization_id)
    rows = _filas(db, w, params)  # sin límite: toda la lista filtrada

    AZUL = PatternFill("solid", fgColor="1E3A5F")
    WB_ = Font(color="FFFFFF", bold=True)
    BOLD = Font(bold=True)

    def _hdr(ws, fila, cols):
        for j, c in enumerate(cols, start=1):
            cell = ws.cell(row=fila, column=j, value=c)
            cell.fill = AZUL; cell.font = WB_
            cell.alignment = Alignment(horizontal="left")

    etiqueta = "Todos" if fnorm["condicion"] == "todos" else _LABELS.get(
        fnorm["condicion"], fnorm["condicion"])

    wb = Workbook()

    # ── Composición ──
    ws = wb.active; ws.title = "Composición"
    ws["A1"] = "Composición del Padrón"; ws["A1"].font = Font(bold=True, size=14)
    _hdr(ws, 3, ["Estado", "Cantidad"])
    i = 4
    for b in comp["buckets"]:
        ws.cell(i, 1, b["label"]); ws.cell(i, 2, b["n"]); i += 1
    ws.cell(i, 1, "TOTAL PADRÓN").font = BOLD
    ws.cell(i, 2, comp["total"]).font = BOLD
    i += 2
    ws.cell(i, 1, "de los cuales Past Decano (⊂ Hábiles)"); ws.cell(i, 2, comp["past_decano"]); i += 1
    if not comp["cuadra"]:
        ws.cell(i, 1, "SIN CLASIFICAR").font = Font(bold=True, color="B91C1C")
        ws.cell(i, 2, comp["sin_clasificar"]).font = Font(bold=True, color="B91C1C")
    ws.column_dimensions["A"].width = 40; ws.column_dimensions["B"].width = 14

    # ── Padrón (lista filtrada) ──
    ws = wb.create_sheet("Padrón")
    _hdr(ws, 1, ["Matrícula", "Apellidos y Nombres", "DNI", "Condición", "Fecha colegiatura"])
    for idx, r in enumerate(rows, start=2):
        cond = r["condicion_label"] + (" (Past Decano)" if r["past_decano"] else "")
        ws.cell(idx, 1, r["matricula"]); ws.cell(idx, 2, r["apellidos_nombres"])
        ws.cell(idx, 3, r["dni"]); ws.cell(idx, 4, cond); ws.cell(idx, 5, r["fecha_colegiatura"])
    for col, width in zip("ABCDE", [14, 40, 14, 22, 18]):
        ws.column_dimensions[col].width = width
    ws.freeze_panes = "A2"

    # ── Metadata ──
    ws = wb.create_sheet("Metadata")
    meta = [
        ("Reporte", "Padrón de Colegiados"),
        ("Filtro condición", etiqueta),
        ("Búsqueda", fnorm["q"] or "—"),
        ("Registros exportados", len(rows)),
        ("Total padrón", comp["total"]),
        ("Generado", datetime.now(PERU_TZ).strftime("%d/%m/%Y %H:%M")),
        ("Alcance", "100% lectura — padrón vivo (independiente de Aportes Junta)"),
        ("Sistema", "Colegio de Contadores Públicos de Loreto"),
    ]
    for idx, (k, v) in enumerate(meta, start=1):
        ws.cell(idx, 1, k).font = BOLD; ws.cell(idx, 2, v)
    ws.column_dimensions["A"].width = 26; ws.column_dimensions["B"].width = 52

    out = io.BytesIO(); wb.save(out)
    return out.getvalue()


# ──────────────────────────────────────────────────────────────────────────
# PDF — encabezado CCPL (sin "Perú Sistemas Pro") + composición + padrón filtrado.
# ──────────────────────────────────────────────────────────────────────────
def generar_pdf_padron(db: Session, filtros: dict | None = None,
                       organization_id: int = ORG_DEFAULT, usuario: str = "-") -> bytes:
    import io
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

    filtros = dict(filtros or {})
    filtros["org"] = organization_id
    w, params, fnorm = _where_filtros(filtros)
    comp = composicion_padron(db, organization_id)
    rows = _filas(db, w, params)

    AZUL = colors.HexColor("#1e3a5f"); GRIS = colors.HexColor("#f1f5f9")
    ROJO = colors.HexColor("#b91c1c")
    etiqueta = "Todos" if fnorm["condicion"] == "todos" else _LABELS.get(
        fnorm["condicion"], fnorm["condicion"])

    def _footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7); canvas.setFillColor(colors.grey)
        canvas.drawString(16 * mm, 9 * mm, "Colegio de Contadores Publicos de Loreto")
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
                 ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
        if header:
            style += [("BACKGROUND", (0, 0), (-1, 0), AZUL), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                      ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold")]
        tb.setStyle(TableStyle(style))
        return tb

    _now = datetime.now(PERU_TZ)
    el = []
    el.append(Paragraph("COLEGIO DE CONTADORES PUBLICOS DE LORETO", H))
    el.append(Paragraph("Padrón de Colegiados", SUB))
    el.append(Paragraph(
        f"Filtro: {etiqueta} &middot; Registros: {len(rows)} &middot; "
        f"Generado: {_now.strftime('%d/%m/%Y %H:%M')} &middot; Usuario: {usuario}", SMALL))
    el.append(Spacer(1, 7 * mm))

    # Composición
    el.append(Paragraph("COMPOSICION DEL PADRON", HD))
    comp_rows = [["Estado", "Cantidad"]] + [[b["label"], str(b["n"])] for b in comp["buckets"]]
    comp_rows.append(["TOTAL PADRON", str(comp["total"])])
    comp_rows.append([f"(de los cuales Past Decano, subconjunto de Habiles)", str(comp["past_decano"])])
    if not comp["cuadra"]:
        comp_rows.append(["SIN CLASIFICAR", str(comp["sin_clasificar"])])
    ct = _tbl(comp_rows, [110 * mm, 40 * mm])
    el.append(ct); el.append(Spacer(1, 6 * mm))

    # Padrón — el detalle nominal SOLO cuando el filtro está acotado (una condición
    # o una búsqueda). Con "Todos" el PDF se queda en la composición (presentable para
    # el Consejo) y remite al Excel; el detalle completo de 2 505 saldría ~130 páginas.
    NOTA = ParagraphStyle("NOTA", parent=st["Normal"], fontSize=9, textColor=colors.grey)
    TOPE = 500
    con_detalle = (fnorm["condicion"] != "todos") or bool(fnorm["q"])

    if not con_detalle:
        el.append(Paragraph(
            f"El detalle nominal del padrón completo ({comp['total']:,} colegiados) no se "
            f"incluye en este PDF para mantenerlo presentable. Este reporte resume la "
            f"composición por estado; para el listado nominal completo, descargue el Excel "
            f"o filtre por una condición.", NOTA))
    else:
        el.append(Paragraph(f"PADRON ({etiqueta})", HD))
        data = [["Matricula", "Apellidos y Nombres", "DNI", "Condicion", "F. colegiatura"]]
        for r in rows[:TOPE]:
            cond = r["condicion_label"] + (" (Past Decano)" if r["past_decano"] else "")
            data.append([r["matricula"], r["apellidos_nombres"], r["dni"], cond, r["fecha_colegiatura"]])
        if len(data) == 1:
            data.append(["—", "Sin resultados para el filtro", "—", "—", "—"])
        el.append(_tbl(data, [24 * mm, 66 * mm, 24 * mm, 30 * mm, 24 * mm]))
        if len(rows) > TOPE:
            el.append(Spacer(1, 3 * mm))
            el.append(Paragraph(
                f"Se muestran {TOPE} de {len(rows):,} registros. Descargue el Excel para "
                f"el listado completo del filtro.", NOTA))

    doc.build(el, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()

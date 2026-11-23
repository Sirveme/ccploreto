"""
app/services/reporte_fraccionamientos_service.py — Dominio «Fraccionamientos» del Centro de Reportes.
100 % lectura. Mismo patrón que colegiados_padron_service (pantalla JSON, Excel y PDF de la casa).

Secciones:
  1. fraccionables  — colegiados SIN plan activo cuya deuda única (la misma de la ficha y la
                      habilidad) alcanza el mínimo para fraccionar de Parámetros.
  2. perdidos       — planes perdidos a la fecha, con su deuda de saldo por pérdida.
  3. refinanciar    — candidatos a refinanciar: planes activos SANOS (escalonados) con atraso.
  4. atrasados      — planes activos con atraso, por días desde la cuota impaga más antigua:
                      1–30, 31–60, 61–90 y más de 90.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

PERU_TZ = timezone(timedelta(hours=-5))
TRAMOS = (("1-30", 1, 30), ("31-60", 31, 60), ("61-90", 61, 90), ("mas-90", 91, 100000))
ETIQUETA_TRAMO = {"1-30": "1 a 30 días", "31-60": "31 a 60 días", "61-90": "61 a 90 días", "mas-90": "Más de 90 días"}
SECCIONES = {
    "fraccionables": "Deudas fraccionables hoy",
    "perdidos": "Planes perdidos",
    "refinanciar": "Candidatos a refinanciar",
    "atrasados": "Planes atrasados por días de atraso",
}


def _hoy():
    return datetime.now(PERU_TZ).date()


def _monto_minimo(db: Session, org: int) -> float:
    try:
        from app.services.fraccionamiento_service import _resolver_parametros_fracc
        return float(_resolver_parametros_fracc(db, org)[0])
    except Exception:
        return 250.0


def fraccionables(db: Session, org: int = 1):
    from app.services.deuda_cuotas_service import _condiciones_sin_deuda_computable
    exentas = sorted(_condiciones_sin_deuda_computable(db, org))
    minimo = _monto_minimo(db, org)
    rows = db.execute(text("""
        WITH d AS (
            SELECT d.colegiado_id, sum(d.balance) s, count(*) n
            FROM debts d JOIN colegiados c ON c.id = d.colegiado_id
            WHERE d.organization_id = :org AND c.organization_id = :org
              AND d.status IN ('pending','partial') AND d.estado_gestion IN ('vigente','en_cobranza')
              AND (coalesce(d.debt_type,'') <> 'cuota_ordinaria'
                   OR (d.periodo ~ '^[0-9]{4}' AND NOT (coalesce(c.condicion,'habil') = ANY(:ex))))
            GROUP BY 1)
        SELECT c.id, c.codigo_matricula mat, c.apellidos_nombres nombre, c.condicion, round(d.s::numeric, 2) deuda, d.n
        FROM colegiados c JOIN d ON d.colegiado_id = c.id
        WHERE c.organization_id = :org AND d.s >= :min
          AND NOT EXISTS (SELECT 1 FROM fraccionamientos f WHERE f.colegiado_id = c.id AND f.estado = 'activo')
          AND NOT (coalesce(c.condicion,'habil') = ANY(:ex))
        ORDER BY d.s DESC, c.apellidos_nombres"""), {"org": org, "ex": exentas, "min": minimo}).fetchall()
    return [{"matricula": r.mat, "nombre": r.nombre, "condicion": r.condicion, "deuda": float(r.deuda), "deudas": int(r.n)} for r in rows], minimo


def perdidos(db: Session, org: int = 1):
    rows = db.execute(text("""
        SELECT f.numero_solicitud, f.fecha_perdida, f.deuda_total_original, c.codigo_matricula mat, c.apellidos_nombres nombre, c.condicion,
               (SELECT coalesce(sum(d.amount),0) FROM debts d WHERE d.fraccionamiento_id_origen = f.id AND d.debt_type = 'saldo_perdida_fraccionamiento') monto_perdida,
               (SELECT coalesce(sum(d.balance),0) FROM debts d WHERE d.fraccionamiento_id_origen = f.id AND d.debt_type = 'saldo_perdida_fraccionamiento'
                       AND d.status IN ('pending','partial')) saldo_perdida,
               left(coalesce(f.motivo_perdida,''), 120) motivo
        FROM fraccionamientos f JOIN colegiados c ON c.id = f.colegiado_id
        WHERE f.organization_id = :org AND f.estado = 'perdido'
        ORDER BY f.fecha_perdida DESC NULLS LAST, f.id DESC"""), {"org": org}).fetchall()
    return [{"plan": r.numero_solicitud, "fecha_perdida": r.fecha_perdida.astimezone(PERU_TZ).strftime("%d/%m/%Y") if r.fecha_perdida and getattr(r.fecha_perdida, "tzinfo", None)
             else (r.fecha_perdida.strftime("%d/%m/%Y") if r.fecha_perdida else ""), "matricula": r.mat, "nombre": r.nombre,
             "condicion": r.condicion, "total_plan": float(r.deuda_total_original or 0), "deuda_perdida": float(r.monto_perdida or 0),
             "saldo_por_cobrar": float(r.saldo_perdida or 0), "motivo": r.motivo} for r in rows]


def _activos_con_atraso(db: Session, org: int = 1):
    hoy = _hoy()
    rows = db.execute(text("""
        SELECT f.id, f.numero_solicitud, f.saldo_pendiente, c.codigo_matricula mat, c.apellidos_nombres nombre, c.condicion,
               (SELECT count(DISTINCT q.fecha_vencimiento) FROM fraccionamiento_cuotas q WHERE q.fraccionamiento_id = f.id) > 1 AS escalonado,
               (SELECT min(q.fecha_vencimiento) FROM fraccionamiento_cuotas q WHERE q.fraccionamiento_id = f.id
                       AND NOT coalesce(q.pagada,false) AND q.fecha_vencimiento < :hoy) mas_antigua,
               (SELECT count(*) FROM fraccionamiento_cuotas q WHERE q.fraccionamiento_id = f.id
                       AND NOT coalesce(q.pagada,false) AND q.fecha_vencimiento < :hoy) vencidas,
               (SELECT coalesce(sum(q.monto),0) FROM fraccionamiento_cuotas q WHERE q.fraccionamiento_id = f.id
                       AND NOT coalesce(q.pagada,false) AND q.fecha_vencimiento < :hoy) monto_vencido
        FROM fraccionamientos f JOIN colegiados c ON c.id = f.colegiado_id
        WHERE f.organization_id = :org AND f.estado = 'activo'"""), {"org": org, "hoy": hoy}).fetchall()
    out = []
    for r in rows:
        if not r.mas_antigua:
            continue
        dias = (hoy - r.mas_antigua).days
        tramo = next(k for k, a, b in TRAMOS if a <= dias <= b)
        out.append({"plan": r.numero_solicitud, "matricula": r.mat, "nombre": r.nombre, "condicion": r.condicion,
                    "saldo_plan": float(r.saldo_pendiente or 0), "cuotas_vencidas": int(r.vencidas), "monto_vencido": float(r.monto_vencido or 0),
                    "dias_atraso": dias, "tramo": tramo, "escalonado": bool(r.escalonado)})
    out.sort(key=lambda x: -x["dias_atraso"])
    return out


def generar(db: Session, org: int = 1) -> dict:
    fr, minimo = fraccionables(db, org)
    pe = perdidos(db, org)
    at = _activos_con_atraso(db, org)
    re_ = [x for x in at if x["escalonado"]]
    tramos = []
    for k, _, _ in TRAMOS:
        xs = [x for x in at if x["tramo"] == k]
        tramos.append({"tramo": k, "etiqueta": ETIQUETA_TRAMO[k], "planes": len(xs),
                       "saldo": round(sum(x["saldo_plan"] for x in xs), 2), "vencido": round(sum(x["monto_vencido"] for x in xs), 2)})
    return {
        "generado": datetime.now(PERU_TZ).strftime("%d/%m/%Y %H:%M"),
        "monto_minimo": minimo,
        "resumen": {
            "fraccionables": {"colegiados": len(fr), "deuda": round(sum(x["deuda"] for x in fr), 2)},
            "perdidos": {"planes": len(pe), "saldo_por_cobrar": round(sum(x["saldo_por_cobrar"] for x in pe), 2)},
            "refinanciar": {"planes": len(re_), "saldo": round(sum(x["saldo_plan"] for x in re_), 2)},
            "atrasados": {"planes": len(at), "saldo": round(sum(x["saldo_plan"] for x in at), 2), "tramos": tramos},
        },
        "fraccionables": fr, "perdidos": pe, "refinanciar": re_, "atrasados": at,
    }


# ─────────────────────────── EXCEL (estilo de la casa) ───────────────────────────
COLUMNAS = {
    "fraccionables": [("Matrícula", "matricula", 12), ("Apellidos y nombres", "nombre", 40), ("Condición", "condicion", 12),
                      ("Deudas", "deudas", 9), ("Deuda total (S/)", "deuda", 16)],
    "perdidos": [("Plan", "plan", 16), ("Fecha de pérdida", "fecha_perdida", 14), ("Matrícula", "matricula", 12),
                 ("Apellidos y nombres", "nombre", 36), ("Condición", "condicion", 11), ("Total del plan (S/)", "total_plan", 16),
                 ("Deuda por pérdida (S/)", "deuda_perdida", 18), ("Saldo por cobrar (S/)", "saldo_por_cobrar", 18), ("Motivo", "motivo", 40)],
    "refinanciar": [("Plan", "plan", 16), ("Matrícula", "matricula", 12), ("Apellidos y nombres", "nombre", 36),
                    ("Condición", "condicion", 11), ("Cuotas vencidas", "cuotas_vencidas", 14), ("Monto vencido (S/)", "monto_vencido", 16),
                    ("Días de atraso", "dias_atraso", 13), ("Saldo del plan (S/)", "saldo_plan", 16)],
    "atrasados": [("Tramo", "tramo_txt", 16), ("Plan", "plan", 16), ("Matrícula", "matricula", 12), ("Apellidos y nombres", "nombre", 36),
                  ("Días de atraso", "dias_atraso", 13), ("Cuotas vencidas", "cuotas_vencidas", 14), ("Monto vencido (S/)", "monto_vencido", 16),
                  ("Saldo del plan (S/)", "saldo_plan", 16), ("Tipo de plan", "tipo_txt", 18)],
}


def _filas_seccion(d, sec):
    xs = d[sec]
    if sec == "atrasados":
        xs = [dict(x, tramo_txt=ETIQUETA_TRAMO[x["tramo"]], tipo_txt="escalonado" if x["escalonado"] else "lote migrado") for x in xs]
    return xs


def generar_excel(db: Session, org: int = 1) -> bytes:
    import io
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    d = generar(db, org)
    AZUL = PatternFill("solid", fgColor="1E3A5F"); BL = Font(color="FFFFFF", bold=True); B = Font(bold=True)
    wb = Workbook()
    ws = wb.active; ws.title = "Resumen"
    ws["A1"] = "Fraccionamientos — resumen"; ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = "Generado: %s · Mínimo para fraccionar: S/ %.2f" % (d["generado"], d["monto_minimo"])
    for j, h in enumerate(["Consulta", "Cantidad", "Monto (S/)"], 1):
        c = ws.cell(4, j, h); c.fill = AZUL; c.font = BL
    r = d["resumen"]; filas = [("Deudas fraccionables hoy (colegiados)", r["fraccionables"]["colegiados"], r["fraccionables"]["deuda"]),
                               ("Planes perdidos (saldo por cobrar)", r["perdidos"]["planes"], r["perdidos"]["saldo_por_cobrar"]),
                               ("Candidatos a refinanciar (saldo)", r["refinanciar"]["planes"], r["refinanciar"]["saldo"]),
                               ("Planes atrasados (saldo)", r["atrasados"]["planes"], r["atrasados"]["saldo"])]
    filas += [("   " + t["etiqueta"], t["planes"], t["saldo"]) for t in r["atrasados"]["tramos"]]
    for i, (a, b, c) in enumerate(filas, 5):
        ws.cell(i, 1, a); ws.cell(i, 2, b); ws.cell(i, 3, c).number_format = "#,##0.00"
    ws.column_dimensions["A"].width = 44; ws.column_dimensions["B"].width = 12; ws.column_dimensions["C"].width = 16
    for sec, titulo in SECCIONES.items():
        w = wb.create_sheet(titulo[:31])
        cols = COLUMNAS[sec]
        for j, (h, _, ancho) in enumerate(cols, 1):
            c = w.cell(1, j, h); c.fill = AZUL; c.font = BL; c.alignment = Alignment(wrap_text=True)
            w.column_dimensions[c.column_letter].width = ancho
        for i, x in enumerate(_filas_seccion(d, sec), 2):
            for j, (_, k, _) in enumerate(cols, 1):
                v = x.get(k); cell = w.cell(i, j, v)
                if isinstance(v, float):
                    cell.number_format = "#,##0.00"
        w.freeze_panes = "A2"
    out = io.BytesIO(); wb.save(out)
    return out.getvalue()


# ─────────────────────────── PDF (encabezado CCPL) ───────────────────────────
def generar_pdf(db: Session, org: int = 1, usuario: str = "-") -> bytes:
    import io
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    d = generar(db, org)
    AZUL = colors.HexColor("#1e3a5f"); GRIS = colors.HexColor("#f1f5f9")
    st = getSampleStyleSheet()
    H = ParagraphStyle("H", parent=st["Title"], fontSize=14)
    SUB = ParagraphStyle("SUB", parent=st["Normal"], fontSize=10.5, alignment=1)
    SMALL = ParagraphStyle("SMALL", parent=st["Normal"], fontSize=8, textColor=colors.grey, alignment=1)
    HD = ParagraphStyle("HD", parent=st["Heading4"], textColor=AZUL)
    NOTA = ParagraphStyle("NOTA", parent=st["Normal"], fontSize=8.5, textColor=colors.grey)
    TOPE = 300

    def _tbl(data, widths):
        t = Table(data, colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 8), ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
                               ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, GRIS]), ("BACKGROUND", (0, 0), (-1, 0), AZUL),
                               ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                               ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5)]))
        return t

    def _footer(canvas, doc):
        canvas.saveState(); canvas.setFont("Helvetica", 7); canvas.setFillColor(colors.grey)
        canvas.drawString(14 * mm, 8 * mm, "Colegio de Contadores Publicos de Loreto")
        canvas.drawRightString(landscape(A4)[0] - 14 * mm, 8 * mm, "Pagina %d" % doc.page); canvas.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), topMargin=14 * mm, bottomMargin=14 * mm, leftMargin=14 * mm, rightMargin=14 * mm)
    el = [Paragraph("COLEGIO DE CONTADORES PUBLICOS DE LORETO", H), Paragraph("Fraccionamientos", SUB),
          Paragraph("Generado: %s &middot; Usuario: %s &middot; Mínimo para fraccionar: S/ %.2f" % (d["generado"], usuario, d["monto_minimo"]), SMALL),
          Spacer(1, 5 * mm), Paragraph("RESUMEN", HD)]
    r = d["resumen"]
    res = [["Consulta", "Cantidad", "Monto (S/)"],
           ["Deudas fraccionables hoy", r["fraccionables"]["colegiados"], "%.2f" % r["fraccionables"]["deuda"]],
           ["Planes perdidos (saldo por cobrar)", r["perdidos"]["planes"], "%.2f" % r["perdidos"]["saldo_por_cobrar"]],
           ["Candidatos a refinanciar", r["refinanciar"]["planes"], "%.2f" % r["refinanciar"]["saldo"]],
           ["Planes atrasados", r["atrasados"]["planes"], "%.2f" % r["atrasados"]["saldo"]]]
    res += [["   " + t["etiqueta"], t["planes"], "%.2f" % t["saldo"]] for t in r["atrasados"]["tramos"]]
    el += [_tbl(res, [110 * mm, 30 * mm, 40 * mm]), Spacer(1, 5 * mm)]
    for sec, titulo in SECCIONES.items():
        cols = COLUMNAS[sec]; xs = _filas_seccion(d, sec)
        el.append(Paragraph(titulo.upper(), HD))
        data = [[h for h, _, _ in cols]]
        for x in xs[:TOPE]:
            data.append([("%.2f" % x[k]) if isinstance(x.get(k), float) else str(x.get(k) if x.get(k) is not None else "") for _, k, _ in cols])
        if len(data) == 1:
            data.append(["—"] + [""] * (len(cols) - 1))
        tot = sum(a for _, _, a in cols)
        el.append(_tbl(data, [a / tot * 265 * mm for _, _, a in cols]))
        if len(xs) > TOPE:
            el.append(Paragraph("Se muestran %d de %d. Descargue el Excel para la lista completa." % (TOPE, len(xs)), NOTA))
        el.append(Spacer(1, 5 * mm))
    doc.build(el, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()

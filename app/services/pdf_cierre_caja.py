"""
Servicio: Generador PDF de Cierre de Caja
app/services/pdf_cierre_caja.py

Genera un reporte PDF profesional con:
- Encabezado institucional
- Resumen de sesión (apertura, cierre, cajero)
- Cuadre de caja (efectivo esperado vs declarado)
- Detalle de cobros por método de pago
- Comprobantes emitidos (boletas, facturas, NC)
- Egresos autorizados
- Firma del cajero

Requiere: pip install reportlab
"""

import io
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, cm
from reportlab.lib.colors import HexColor, black, white
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether
)
from reportlab.pdfgen import canvas

TZ_PERU = timezone(timedelta(hours=-5))

# ── Colores ──
AZUL_OSCURO = HexColor("#1e293b")
AZUL_MEDIO = HexColor("#334155")
GRIS_CLARO = HexColor("#f1f5f9")
GRIS_BORDE = HexColor("#cbd5e1")
VERDE = HexColor("#16a34a")
ROJO = HexColor("#dc2626")
AMARILLO = HexColor("#d97706")
ACCENT = HexColor("#4f46e5")


def _f(val):
    """Formatea número a 2 decimales."""
    return f"{float(val or 0):,.2f}"


def _fecha_peru(dt):
    """Convierte datetime a string en hora Perú."""
    if not dt:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    peru = dt.astimezone(TZ_PERU)
    return peru.strftime("%d/%m/%Y %H:%M")


def _solo_fecha(dt):
    if not dt:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    peru = dt.astimezone(TZ_PERU)
    return peru.strftime("%d/%m/%Y")


def _solo_hora(dt):
    if not dt:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    peru = dt.astimezone(TZ_PERU)
    return peru.strftime("%H:%M")


class _HeaderFooter:
    """Agrega encabezado y pie a cada página."""

    def __init__(self, org_nombre, sede_nombre, sesion_id, fecha_str):
        self.org_nombre = org_nombre
        self.sede_nombre = sede_nombre
        self.sesion_id = sesion_id
        self.fecha_str = fecha_str

    def __call__(self, canvas_obj, doc):
        canvas_obj.saveState()
        w, h = A4

        # ── Header ──
        canvas_obj.setFillColor(AZUL_OSCURO)
        canvas_obj.rect(0, h - 28 * mm, w, 28 * mm, fill=True, stroke=False)

        canvas_obj.setFillColor(white)
        canvas_obj.setFont("Helvetica-Bold", 14)
        canvas_obj.drawString(15 * mm, h - 12 * mm, self.org_nombre)

        canvas_obj.setFont("Helvetica", 9)
        canvas_obj.drawString(15 * mm, h - 18 * mm, f"Sede: {self.sede_nombre}")
        canvas_obj.drawString(15 * mm, h - 23 * mm, f"CIERRE DE CAJA — Sesión #{self.sesion_id}")

        canvas_obj.drawRightString(w - 15 * mm, h - 12 * mm, self.fecha_str)
        canvas_obj.drawRightString(w - 15 * mm, h - 18 * mm, f"Generado: {datetime.now(TZ_PERU).strftime('%d/%m/%Y %H:%M')}")

        # Línea accent
        canvas_obj.setStrokeColor(ACCENT)
        canvas_obj.setLineWidth(2)
        canvas_obj.line(0, h - 28 * mm, w, h - 28 * mm)

        # ── Footer ──
        canvas_obj.setFillColor(GRIS_BORDE)
        canvas_obj.setFont("Helvetica", 7)
        canvas_obj.drawString(15 * mm, 8 * mm, f"Sesión #{self.sesion_id} — Documento generado automáticamente")
        canvas_obj.drawRightString(w - 15 * mm, 8 * mm, f"Pág. {doc.page}")

        canvas_obj.restoreState()


def generar_pdf_cierre(
    sesion,
    org_nombre: str,
    sede_nombre: str,
    cajero_nombre: str,
    pagos: list,
    egresos: list,
    comprobantes: list,
) -> bytes:
    """
    Genera el PDF de cierre de caja.

    Args:
        sesion: SesionCaja object
        org_nombre: Nombre de la organización
        sede_nombre: Nombre del centro de costo/sede
        cajero_nombre: Nombre del cajero
        pagos: Lista de Payment objects de la sesión
        egresos: Lista de EgresoCaja objects
        comprobantes: Lista de Comprobante objects emitidos en la sesión

    Returns:
        bytes del PDF generado
    """
    buffer = io.BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=35 * mm,
        bottomMargin=18 * mm,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
    )

    # ── Estilos ──
    styles = getSampleStyleSheet()

    s_titulo = ParagraphStyle(
        "Titulo", parent=styles["Heading2"],
        fontSize=13, textColor=AZUL_OSCURO, spaceAfter=6,
        fontName="Helvetica-Bold",
    )
    s_subtitulo = ParagraphStyle(
        "Subtitulo", parent=styles["Normal"],
        fontSize=10, textColor=AZUL_MEDIO, spaceAfter=4,
        fontName="Helvetica-Bold",
    )
    s_normal = ParagraphStyle(
        "Normal2", parent=styles["Normal"],
        fontSize=9, textColor=black, leading=13,
    )
    s_small = ParagraphStyle(
        "Small", parent=styles["Normal"],
        fontSize=8, textColor=AZUL_MEDIO, leading=11,
    )
    s_center = ParagraphStyle(
        "Center", parent=s_normal,
        alignment=TA_CENTER,
    )
    s_right = ParagraphStyle(
        "Right", parent=s_normal,
        alignment=TA_RIGHT,
    )

    story = []
    fecha_str = _solo_fecha(sesion.hora_apertura or sesion.fecha)

    # ══════════════════════════════════════
    # SECCIÓN 1: RESUMEN DE SESIÓN
    # ══════════════════════════════════════
    story.append(Paragraph("RESUMEN DE SESIÓN", s_titulo))

    info_data = [
        ["Cajero(a):", cajero_nombre, "Fecha:", fecha_str],
        ["Apertura:", _solo_hora(sesion.hora_apertura), "Cierre:", _solo_hora(sesion.hora_cierre)],
        ["Monto apertura:", f"S/ {_f(sesion.monto_apertura)}", "Estado:", sesion.estado.upper()],
    ]

    t_info = Table(info_data, colWidths=[75, 175, 50, 120])
    t_info.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 0), (0, -1), AZUL_MEDIO),
        ("TEXTCOLOR", (2, 0), (2, -1), AZUL_MEDIO),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(t_info)
    story.append(Spacer(1, 10))

    # ══════════════════════════════════════
    # SECCIÓN 2: CUADRE DE CAJA
    # ══════════════════════════════════════
    story.append(Paragraph("CUADRE DE CAJA", s_titulo))

    monto_apertura = float(sesion.monto_apertura or 0)
    # Recalcular desde pagos reales (no confiar en totales guardados por posible bug timezone)
    total_efectivo = sum(float(p.amount or 0) for p in pagos if p.payment_method in ("efectivo",))
    total_digital = sum(float(p.amount or 0) for p in pagos if p.payment_method not in ("efectivo",))
    total_egresos_val = sum(float(e.monto or 0) for e in egresos)
    total_esperado = monto_apertura + total_efectivo - total_egresos_val
    monto_cierre = float(sesion.monto_cierre or 0)
    diferencia = monto_cierre - total_esperado
    cant_ops = len(pagos)

    cuadre_data = [
        ["CONCEPTO", "MONTO"],
        ["Monto de apertura", f"S/ {_f(monto_apertura)}"],
        ["(+) Cobros en efectivo", f"S/ {_f(total_efectivo)}"],
        ["(-) Egresos en efectivo", f"S/ {_f(total_egresos_val)}"],
        ["", ""],
        ["EFECTIVO ESPERADO", f"S/ {_f(total_esperado)}"],
        ["Efectivo declarado (cajero)", f"S/ {_f(monto_cierre)}"],
        ["", ""],
        ["DIFERENCIA", f"S/ {diferencia:+,.2f}"],
    ]

    # Color de la diferencia
    dif_color = VERDE if abs(diferencia) < 0.01 else (ROJO if diferencia < 0 else AMARILLO)

    t_cuadre = Table(cuadre_data, colWidths=[310, 110])
    t_cuadre.setStyle(TableStyle([
        # Header
        ("BACKGROUND", (0, 0), (-1, 0), AZUL_OSCURO),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("ALIGNMENT", (1, 0), (1, -1), "RIGHT"),
        # Body
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        # Separadores
        ("LINEBELOW", (0, 3), (-1, 3), 0.5, GRIS_BORDE),
        ("LINEBELOW", (0, 6), (-1, 6), 0.5, GRIS_BORDE),
        # Fila esperado
        ("FONTNAME", (0, 5), (-1, 5), "Helvetica-Bold"),
        ("BACKGROUND", (0, 5), (-1, 5), GRIS_CLARO),
        # Fila diferencia
        ("FONTNAME", (0, 8), (-1, 8), "Helvetica-Bold"),
        ("FONTSIZE", (0, 8), (-1, 8), 11),
        ("TEXTCOLOR", (0, 8), (-1, 8), dif_color),
        ("BACKGROUND", (0, 8), (-1, 8), GRIS_CLARO),
        # Bordes generales
        ("GRID", (0, 0), (-1, 0), 0.5, AZUL_OSCURO),
        ("LINEBELOW", (0, -1), (-1, -1), 1, AZUL_OSCURO),
    ]))
    story.append(t_cuadre)

    # Resumen adicional
    story.append(Spacer(1, 6))
    resumen_extra = f"Total operaciones: {cant_ops} &nbsp;|&nbsp; Cobros digitales: S/ {_f(total_digital)} &nbsp;|&nbsp; Total recaudado: S/ {_f(total_efectivo + total_digital)}"
    story.append(Paragraph(resumen_extra, s_small))
    story.append(Spacer(1, 12))

    # ══════════════════════════════════════
    # SECCIÓN 3: DETALLE DE COBROS
    # ══════════════════════════════════════
    story.append(Paragraph("DETALLE DE COBROS", s_titulo))

    if pagos:
        # Agrupar por método de pago
        metodos = {}
        for p in pagos:
            met = p.payment_method or "otro"
            if met not in metodos:
                metodos[met] = {"cantidad": 0, "total": 0}
            metodos[met]["cantidad"] += 1
            metodos[met]["total"] += float(p.amount or 0)

        met_data = [["MÉTODO DE PAGO", "CANT.", "TOTAL"]]
        for met, vals in sorted(metodos.items()):
            met_data.append([
                met.upper(),
                str(vals["cantidad"]),
                f"S/ {_f(vals['total'])}",
            ])
        met_data.append([
            "TOTAL",
            str(sum(v["cantidad"] for v in metodos.values())),
            f"S/ {_f(sum(v['total'] for v in metodos.values()))}",
        ])

        t_met = Table(met_data, colWidths=[250, 60, 110])
        t_met.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), AZUL_OSCURO),
            ("TEXTCOLOR", (0, 0), (-1, 0), white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ALIGNMENT", (1, 0), (1, -1), "CENTER"),
            ("ALIGNMENT", (2, 0), (2, -1), "RIGHT"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("BACKGROUND", (0, -1), (-1, -1), GRIS_CLARO),
            ("LINEABOVE", (0, -1), (-1, -1), 1, AZUL_OSCURO),
            ("GRID", (0, 0), (-1, 0), 0.5, AZUL_OSCURO),
        ]))
        story.append(t_met)

        # Detalle individual
        story.append(Spacer(1, 8))
        story.append(Paragraph("Detalle individual:", s_subtitulo))

        det_data = [["#", "HORA", "COLEGIADO / DESCRIPCIÓN", "MÉTODO", "MONTO"]]
        for i, p in enumerate(pagos, 1):
            hora = ""
            if p.reviewed_at:
                h = p.reviewed_at
                if h.tzinfo is None:
                    h = h.replace(tzinfo=timezone.utc)
                hora = h.astimezone(TZ_PERU).strftime("%H:%M")

            desc = (p.notes or "Cobro").replace("[CAJA] ", "")
            if len(desc) > 55:
                desc = desc[:52] + "..."

            det_data.append([
                str(i),
                hora,
                Paragraph(desc, s_small),
                (p.payment_method or "").upper(),
                f"S/ {_f(p.amount)}",
            ])

        t_det = Table(det_data, colWidths=[25, 40, 230, 65, 60])
        style_det = [
            ("BACKGROUND", (0, 0), (-1, 0), AZUL_MEDIO),
            ("TEXTCOLOR", (0, 0), (-1, 0), white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ALIGNMENT", (0, 0), (0, -1), "CENTER"),
            ("ALIGNMENT", (1, 0), (1, -1), "CENTER"),
            ("ALIGNMENT", (3, 0), (3, -1), "CENTER"),
            ("ALIGNMENT", (4, 0), (4, -1), "RIGHT"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, 0), 0.5, AZUL_MEDIO),
        ]
        # Zebra stripes
        for row in range(1, len(det_data)):
            if row % 2 == 0:
                style_det.append(("BACKGROUND", (0, row), (-1, row), GRIS_CLARO))

        t_det.setStyle(TableStyle(style_det))
        story.append(t_det)
    else:
        story.append(Paragraph("No se registraron cobros en esta sesión.", s_normal))

    story.append(Spacer(1, 12))

    # ══════════════════════════════════════
    # SECCIÓN 4: COMPROBANTES EMITIDOS
    # ══════════════════════════════════════
    story.append(Paragraph("COMPROBANTES EMITIDOS", s_titulo))

    if comprobantes:
        tipo_map = {"01": "FAC", "03": "BOL", "07": "NC", "08": "ND"}
        status_map = {"accepted": "OK", "pending": "PEND", "rejected": "RECH", "anulado": "ANUL", "encolado": "COLA", "error": "ERR"}

        comp_data = [["TIPO", "NÚMERO", "CLIENTE", "MONTO", "ESTADO"]]
        for c in comprobantes:
            comp_data.append([
                tipo_map.get(c.tipo, c.tipo),
                f"{c.serie}-{str(c.numero).zfill(8)}",
                Paragraph(f"{c.cliente_nombre or '-'}<br/><font size=7>{c.cliente_num_doc or ''}</font>", s_small),
                f"S/ {_f(c.total)}",
                status_map.get(c.status, c.status),
            ])

        # Totales por tipo
        total_bol = sum(float(c.total or 0) for c in comprobantes if c.tipo == "03" and c.status == "accepted")
        total_fac = sum(float(c.total or 0) for c in comprobantes if c.tipo == "01" and c.status == "accepted")
        total_nc = sum(float(c.total or 0) for c in comprobantes if c.tipo == "07" and c.status == "accepted")

        comp_data.append(["", "", Paragraph(f"<b>Boletas: S/ {_f(total_bol)} | Facturas: S/ {_f(total_fac)} | NC: S/ {_f(total_nc)}</b>", s_small), "", ""])

        t_comp = Table(comp_data, colWidths=[35, 100, 155, 70, 50])
        t_comp.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), AZUL_OSCURO),
            ("TEXTCOLOR", (0, 0), (-1, 0), white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ALIGNMENT", (0, 0), (0, -1), "CENTER"),
            ("ALIGNMENT", (3, 0), (3, -1), "RIGHT"),
            ("ALIGNMENT", (4, 0), (4, -1), "CENTER"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, 0), 0.5, AZUL_OSCURO),
            ("BACKGROUND", (0, -1), (-1, -1), GRIS_CLARO),
            ("LINEABOVE", (0, -1), (-1, -1), 0.5, GRIS_BORDE),
        ]))
        story.append(t_comp)
    else:
        story.append(Paragraph("No se emitieron comprobantes en esta sesión.", s_normal))

    story.append(Spacer(1, 12))

    # ══════════════════════════════════════
    # SECCIÓN 5: EGRESOS
    # ══════════════════════════════════════
    story.append(Paragraph("EGRESOS DE CAJA", s_titulo))

    if egresos:
        eg_data = [["#", "CONCEPTO", "AUTORIZADO POR", "MONTO"]]
        for i, e in enumerate(egresos, 1):
            eg_data.append([
                str(i),
                Paragraph(e.concepto or "Egreso", s_small),
                e.autorizado_por or "-",
                f"S/ {_f(e.monto)}",
            ])
        eg_data.append(["", "", "TOTAL EGRESOS", f"S/ {_f(total_egresos_val)}"])

        t_eg = Table(eg_data, colWidths=[25, 200, 110, 80])
        t_eg.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), AZUL_OSCURO),
            ("TEXTCOLOR", (0, 0), (-1, 0), white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ALIGNMENT", (0, 0), (0, -1), "CENTER"),
            ("ALIGNMENT", (3, 0), (3, -1), "RIGHT"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, 0), 0.5, AZUL_OSCURO),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("BACKGROUND", (0, -1), (-1, -1), GRIS_CLARO),
            ("LINEABOVE", (0, -1), (-1, -1), 1, AZUL_OSCURO),
        ]))
        story.append(t_eg)
    else:
        story.append(Paragraph("No se registraron egresos en esta sesión.", s_normal))

    story.append(Spacer(1, 16))

    # ══════════════════════════════════════
    # SECCIÓN 6: OBSERVACIONES Y FIRMA
    # ══════════════════════════════════════
    if sesion.observaciones_cierre:
        story.append(Paragraph("OBSERVACIONES", s_titulo))
        story.append(Paragraph(sesion.observaciones_cierre, s_normal))
        story.append(Spacer(1, 12))

    # Firma
    story.append(Spacer(1, 20))
    firma_data = [
        ["", ""],
        ["_" * 35, "_" * 35],
        [cajero_nombre, "Supervisor / Tesorero"],
        ["Cajero(a)", "V°B°"],
    ]
    t_firma = Table(firma_data, colWidths=[210, 210])
    t_firma.setStyle(TableStyle([
        ("ALIGNMENT", (0, 0), (-1, -1), "CENTER"),
        ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("FONTSIZE", (0, 3), (-1, 3), 8),
        ("TEXTCOLOR", (0, 3), (-1, 3), AZUL_MEDIO),
        ("TOPPADDING", (0, 1), (-1, 1), 30),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 4),
    ]))
    story.append(t_firma)

    # ── Build ──
    header_footer = _HeaderFooter(
        org_nombre=org_nombre,
        sede_nombre=sede_nombre,
        sesion_id=sesion.id,
        fecha_str=fecha_str,
    )

    doc.build(story, onFirstPage=header_footer, onLaterPages=header_footer)

    buffer.seek(0)
    return buffer.getvalue()
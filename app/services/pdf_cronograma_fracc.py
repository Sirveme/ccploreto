"""
Servicio: Generador PDF de Cronograma de Fraccionamiento
app/services/pdf_cronograma_fracc.py

Genera un PDF simple con:
- Datos del colegiado
- Datos del plan (número, fecha, total, cuota inicial, saldo)
- Tabla de cuotas (N°, Monto, Vencimiento, Estado)
- Compromiso de pago + pie institucional
"""

import io
from datetime import date as dt_date
from typing import List

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, black, white
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
)

AZUL_OSCURO = HexColor("#1e293b")
GRIS_CLARO = HexColor("#f1f5f9")
GRIS_BORDE = HexColor("#cbd5e1")
VERDE = HexColor("#16a34a")
AMBAR = HexColor("#d97706")
ROJO = HexColor("#dc2626")


def _fecha(d):
    return d.strftime("%d/%m/%Y") if d else "—"


def _money(v):
    return f"S/ {float(v or 0):,.2f}"


def generar_cronograma_pdf(fracc, colegiado, cuotas: List) -> bytes:
    """
    Retorna bytes del PDF del cronograma del fraccionamiento.

    :param fracc: instancia Fraccionamiento
    :param colegiado: instancia Colegiado
    :param cuotas: lista de FraccionamientoCuota ordenadas por numero_cuota asc
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"Cronograma {fracc.numero_solicitud}",
    )

    styles = getSampleStyleSheet()
    estilo_titulo = ParagraphStyle(
        "Titulo",
        parent=styles["Heading1"],
        fontSize=16,
        alignment=TA_CENTER,
        textColor=AZUL_OSCURO,
        spaceAfter=6,
    )
    estilo_sub = ParagraphStyle(
        "Sub",
        parent=styles["Normal"],
        fontSize=11,
        alignment=TA_CENTER,
        textColor=AZUL_OSCURO,
        spaceAfter=14,
    )
    estilo_label = ParagraphStyle(
        "Label",
        parent=styles["Normal"],
        fontSize=10,
        textColor=AZUL_OSCURO,
    )
    estilo_body = ParagraphStyle(
        "Body",
        parent=styles["Normal"],
        fontSize=9,
        textColor=black,
        alignment=TA_LEFT,
    )
    estilo_pie = ParagraphStyle(
        "Pie",
        parent=styles["Normal"],
        fontSize=8,
        textColor=AZUL_OSCURO,
        alignment=TA_CENTER,
    )

    story = []

    # ── Título ──
    story.append(Paragraph("COLEGIO DE CONTADORES PÚBLICOS DE LORETO", estilo_titulo))
    story.append(Paragraph("Cronograma de Fraccionamiento de Deuda", estilo_sub))

    # ── Datos del colegiado y plan ──
    datos_tabla = [
        [
            Paragraph("<b>N° de solicitud:</b>", estilo_label),
            Paragraph(str(fracc.numero_solicitud or "—"), estilo_body),
            Paragraph("<b>Fecha:</b>", estilo_label),
            Paragraph(_fecha(fracc.fecha_solicitud), estilo_body),
        ],
        [
            Paragraph("<b>Colegiado:</b>", estilo_label),
            Paragraph(str(colegiado.apellidos_nombres or "—"), estilo_body),
            Paragraph("<b>Matrícula:</b>", estilo_label),
            Paragraph(str(colegiado.codigo_matricula or "—"), estilo_body),
        ],
        [
            Paragraph("<b>DNI:</b>", estilo_label),
            Paragraph(str(colegiado.dni or "—"), estilo_body),
            Paragraph("<b>Estado:</b>", estilo_label),
            Paragraph(str(fracc.estado or "—").upper(), estilo_body),
        ],
        [
            Paragraph("<b>Deuda total:</b>", estilo_label),
            Paragraph(_money(fracc.deuda_total_original), estilo_body),
            Paragraph("<b>Cuota inicial:</b>", estilo_label),
            Paragraph(_money(fracc.cuota_inicial), estilo_body),
        ],
        [
            Paragraph("<b>Saldo a fraccionar:</b>", estilo_label),
            Paragraph(_money(fracc.saldo_a_fraccionar), estilo_body),
            Paragraph("<b>Cuotas x monto:</b>", estilo_label),
            Paragraph(f"{fracc.num_cuotas} × {_money(fracc.monto_cuota)}", estilo_body),
        ],
    ]
    tabla_datos = Table(
        datos_tabla,
        colWidths=[38 * mm, 52 * mm, 34 * mm, 50 * mm],
    )
    tabla_datos.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), GRIS_CLARO),
        ("BOX", (0, 0), (-1, -1), 0.5, GRIS_BORDE),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, GRIS_BORDE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(tabla_datos)
    story.append(Spacer(1, 10 * mm))

    # ── Tabla de cuotas ──
    encabezado = [
        Paragraph("<b>N°</b>", estilo_body),
        Paragraph("<b>Tipo</b>", estilo_body),
        Paragraph("<b>Monto</b>", estilo_body),
        Paragraph("<b>Vencimiento</b>", estilo_body),
        Paragraph("<b>Estado</b>", estilo_body),
        Paragraph("<b>Habilidad hasta</b>", estilo_body),
    ]
    filas = [encabezado]
    hoy = dt_date.today()
    for c in cuotas:
        tipo = "Inicial" if c.numero_cuota == 0 else "Mensual"
        if c.pagada:
            estado_txt = "Pagada"
            color_estado = VERDE
        elif c.fecha_vencimiento and c.fecha_vencimiento < hoy:
            estado_txt = "Vencida"
            color_estado = ROJO
        else:
            estado_txt = "Pendiente"
            color_estado = AMBAR
        filas.append([
            Paragraph(str(c.numero_cuota), estilo_body),
            Paragraph(tipo, estilo_body),
            Paragraph(_money(c.monto), estilo_body),
            Paragraph(_fecha(c.fecha_vencimiento), estilo_body),
            Paragraph(
                f'<font color="{color_estado.hexval()}">{estado_txt}</font>',
                estilo_body,
            ),
            Paragraph(_fecha(c.habilidad_hasta), estilo_body),
        ])

    tabla_cuotas = Table(
        filas,
        colWidths=[12 * mm, 22 * mm, 28 * mm, 32 * mm, 28 * mm, 32 * mm],
        repeatRows=1,
    )
    tabla_cuotas.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), AZUL_OSCURO),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 0.5, GRIS_BORDE),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, GRIS_BORDE),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, GRIS_CLARO]),
    ]))
    story.append(tabla_cuotas)
    story.append(Spacer(1, 12 * mm))

    # ── Compromiso de pago ──
    story.append(Paragraph(
        "<b>Documento de compromiso de pago</b>",
        estilo_label,
    ))
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph(
        "El colegiado identificado en este documento reconoce la deuda "
        "y se compromete a cumplir el cronograma de pagos arriba detallado. "
        "El incumplimiento de dos cuotas consecutivas dejará sin efecto el "
        "plan, restableciendo la exigibilidad total de la deuda original.",
        estilo_body,
    ))
    story.append(Spacer(1, 16 * mm))

    # ── Firmas ──
    firmas_tabla = Table(
        [
            ["_________________________", "_________________________"],
            ["Colegiado", "Secretaría CCPL"],
        ],
        colWidths=[80 * mm, 80 * mm],
    )
    firmas_tabla.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 2),
        ("TOPPADDING", (0, 1), (-1, 1), 2),
    ]))
    story.append(firmas_tabla)
    story.append(Spacer(1, 10 * mm))

    story.append(Paragraph(
        "Emitido por CCPL — Sistema ColegiosPro",
        estilo_pie,
    ))

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes

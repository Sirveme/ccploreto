"""
app/services/comprobante_simulado.py — Comprobante SIMULADO (tanda 19, corregido).

Se usa cuando `app/utils/modo_comprobante.modo_comprobante()` dice que NO se emite de verdad (sandbox, demo,
local, o producción sin MODO_DEMO=false explícito).

- CERO llamadas a Facturalo o SUNAT: este módulo no importa ni llama a nada de facturación.
- Numeración claramente ficticia: DEMO-000001, DEMO-000002… con correlativo propio por organización.
  Nunca una serie con forma real (B…/F…).
- Se guarda en su PROPIA tabla `comprobantes_simulados` (sql/zClaude-tanda19-comprobantes-simulados.sql),
  nunca en `comprobantes`: ningún reporte, cierre de caja, arqueo ni exportación la lee.
- PDF con la marca «DEMOSTRACIÓN — SIN VALOR TRIBUTARIO».
"""
import io
from datetime import datetime
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.utils.modo_comprobante import PREFIJO_DEMO, ROTULO_DEMO

TABLA = "comprobantes_simulados"


def tabla_disponible(db: Session) -> bool:
    return bool(db.execute(text("SELECT to_regclass('public.%s') IS NOT NULL" % TABLA)).scalar())


def formato(numero: int) -> str:
    return "%s-%06d" % (PREFIJO_DEMO, int(numero))


def emitir_simulado(db: Session, payment, tipo: str, cliente: dict, descripcion: str) -> dict:
    """Crea el comprobante simulado del pago. `cliente` = {tipo_doc ('1' DNI / '6' RUC), num_doc, nombre}."""
    if tipo not in ("03", "01"):
        return {"success": False, "error": "Tipo de comprobante no válido"}
    if not tabla_disponible(db):
        return {"success": False, "error": "falta la tabla de comprobantes simulados (SQL de la tanda 19)"}
    existe = db.execute(text("SELECT id, numero_formato FROM %s WHERE payment_id = :p" % TABLA), {"p": payment.id}).fetchone()
    if existe:
        return {"success": False, "error": "Ya existe un comprobante simulado para este pago", "comprobante_id": existe.id}
    monto = Decimal(str(payment.amount or 0)).quantize(Decimal("0.01"))
    org = payment.organization_id or 1
    for _ in range(3):      # correlativo propio; si dos pagos chocan en el mismo número, se reintenta
        numero = int(db.execute(text("SELECT coalesce(max(numero), 0) + 1 FROM %s WHERE organization_id = :o" % TABLA),
                                {"o": org}).scalar())
        try:
            fila = db.execute(text("""
                INSERT INTO comprobantes_simulados (organization_id, payment_id, tipo, numero, numero_formato,
                                                    cliente_tipo_doc, cliente_num_doc, cliente_nombre, descripcion, total)
                VALUES (:o, :p, :t, :n, :f, :td, :nd, :nom, :d, :tot) RETURNING id"""), {
                "o": org, "p": payment.id, "t": tipo, "n": numero, "f": formato(numero),
                "td": str(cliente.get("tipo_doc") or "1")[:1], "nd": (cliente.get("num_doc") or "")[:15],
                "nom": (cliente.get("nombre") or "")[:255], "d": descripcion, "tot": monto}).fetchone()
            db.commit()
            return {"success": True, "simulado": True, "comprobante_id": fila.id, "numero_formato": formato(numero),
                    "pdf_url": None, "error": None}
        except IntegrityError:
            db.rollback()
    return {"success": False, "error": "no se pudo asignar el número simulado"}


def obtener(db: Session, comprobante_id: int):
    if not tabla_disponible(db):
        return None
    return db.execute(text("SELECT * FROM %s WHERE id = :i" % TABLA), {"i": comprobante_id}).fetchone()


def por_pagos(db: Session, payment_ids) -> dict:
    """{payment_id: {id, numero_formato, tipo}} de los pagos dados (para mostrarlos con la marca en pantalla)."""
    if not payment_ids or not tabla_disponible(db):
        return {}
    filas = db.execute(text("SELECT id, payment_id, numero_formato, tipo FROM %s WHERE payment_id = ANY(:ids)" % TABLA),
                       {"ids": list(payment_ids)}).fetchall()
    return {f.payment_id: {"id": f.id, "numero_formato": f.numero_formato, "tipo": f.tipo, "rotulo": ROTULO_DEMO} for f in filas}


def pdf_simulado(comp, institucion: str = "") -> bytes:
    """PDF A5 del comprobante simulado (fila de comprobantes_simulados), con la marca «DEMOSTRACIÓN»."""
    from reportlab.lib.pagesizes import A5
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    w, h = A5
    cv = canvas.Canvas(buf, pagesize=A5)
    cv.setTitle("%s (DEMOSTRACIÓN)" % comp.numero_formato)
    cv.saveState()                                   # marca de agua primero: el texto queda encima
    cv.setFont("Helvetica-Bold", 40)
    cv.setFillColorRGB(0.90, 0.90, 0.90)
    cv.translate(w / 2, h / 2 - 40)
    cv.rotate(35)
    cv.drawCentredString(0, 0, "DEMOSTRACIÓN")
    cv.restoreState()
    y = h - 40
    cv.setFont("Helvetica-Bold", 12)
    cv.drawString(36, y, (institucion or "")[:60])
    y -= 22
    cv.setFont("Helvetica-Bold", 13)
    cv.setFillColorRGB(0.6, 0.1, 0.1)
    cv.drawString(36, y, ROTULO_DEMO)
    cv.setFillColorRGB(0, 0, 0)
    y -= 22
    cv.setFont("Helvetica-Bold", 12)
    titulo = "FACTURA (SIMULADA)" if comp.tipo == "01" else "BOLETA (SIMULADA)"
    cv.drawString(36, y, "%s  %s" % (titulo, comp.numero_formato))
    y -= 18
    cv.setFont("Helvetica", 10)
    fecha = comp.created_at or datetime.now()
    cv.drawString(36, y, "Fecha: %s" % fecha.strftime("%d/%m/%Y"))
    y -= 14
    doc = "RUC" if comp.cliente_tipo_doc == "6" else "DNI"
    cv.drawString(36, y, "Cliente: %s" % (comp.cliente_nombre or "")[:70])
    y -= 14
    cv.drawString(36, y, "%s: %s" % (doc, comp.cliente_num_doc or ""))
    y -= 24
    cv.setFont("Helvetica-Bold", 10)
    cv.drawString(36, y, "Descripción")
    cv.drawRightString(w - 36, y, "Importe")
    y -= 6
    cv.line(36, y, w - 36, y)
    cv.setFont("Helvetica", 10)
    y -= 14
    cv.drawString(36, y, str(comp.descripcion or "")[:60])
    cv.drawRightString(w - 36, y, "S/ %.2f" % float(comp.total or 0))
    y -= 10
    cv.line(36, y, w - 36, y)
    y -= 16
    cv.setFont("Helvetica-Bold", 11)
    cv.drawString(36, y, "TOTAL")
    cv.drawRightString(w - 36, y, "S/ %.2f" % float(comp.total or 0))
    y -= 26
    cv.setFont("Helvetica", 9)
    cv.drawString(36, y, "Comprobante simulado: no es válido ni fue enviado a SUNAT.")
    cv.showPage()
    cv.save()
    return buf.getvalue()

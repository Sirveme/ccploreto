"""
app/services/credencial_reportlab.py
=====================================
Generador de carné CR80 (85.60 × 53.98 mm) del CCPL con reportlab.

Modelo A (fondo pelado):
  - El FONDO (imagen) trae SOLO adornos: holograma, microtexto, ilustración, bandas.
  - El GENERADOR superpone: logos + firmas + labels + datos + foto + QR.

Todo es LAYOUT-DRIVEN (DEFAULT_LAYOUT abajo; o template.layout JSONB si existe),
pensado para un editor visual futuro (ColegiosPro). Cada elemento se dibuja solo si
tiene archivo/dato; si falta, se omite (firma sin PNG → queda la línea para firmar
a mano; F. Nacimiento/Grupo sin dato → en blanco).

Convención de coordenadas del layout: milímetros desde la esquina SUPERIOR-IZQUIERDA
(intuitivo para el editor). El generador las convierte a coords PDF (origen inferior).

Reglas de negocio horneadas:
  - Split de nombre peruano: 2 primeros bloques = apellidos, resto = nombres
    (partículas DE / DE LA / DEL se pegan al apellido siguiente).
  - RUC persona natural = "10" + DNI(8) + dígito verificador (mód-11).
  - QR único → https://ccploreto.org.pe/colegiado/{codigo_matricula} (host fijo, SEO).

No usa create_all ni toca BD. Devuelve bytes del PDF (2 páginas: frente + reverso).
"""
import os
import math
import logging
from io import BytesIO

import requests
import qrcode
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, white, black
from reportlab.lib.utils import ImageReader

logger = logging.getLogger(__name__)

# ── Constantes CR80 ─────────────────────────────────────────────
CARD_W = 85.60 * mm
CARD_H = 53.98 * mm
QR_BASE_URL = "https://ccploreto.org.pe/colegiado/"   # host fijo (regla SEO CCPL)
FETCH_TIMEOUT = 4                                     # segundos (corto)

# Rutas en disco (assets se sirven desde static/ en la raíz, no app/static/)
_HERE       = os.path.dirname(os.path.abspath(__file__))
_STATIC     = os.path.abspath(os.path.join(_HERE, "..", "..", "static"))
_DIR_LOGOS  = os.path.join(_STATIC, "img", "credenciales", "logos")
_DIR_FIRMAS = os.path.join(_STATIC, "img", "credenciales", "firmas")
_DIR_FONDOS = os.path.join(_STATIC, "img", "credenciales", "fondos")

# Paleta por defecto
AZUL_CCPL   = HexColor("#0E3A6D")
DORADO_CCPL = HexColor("#C7A347")
GRIS_FOTO   = HexColor("#E2E6EA")
GRIS_TXT    = HexColor("#555555")
ROJO_CARGO  = HexColor("#B00020")
FONDO_PLANO = HexColor("#FCFCFD")

FONT      = "Helvetica"
FONT_BOLD = "Helvetica-Bold"

_MESES = ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
          "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

_PARTICULAS = {"DE", "DEL", "LA", "LAS", "LOS", "DELA", "SAN", "SANTA", "Y", "DA", "DI", "VDA"}


# ════════════════════════════════════════════════════════════════
#  LAYOUT POR DEFECTO  (mm desde arriba-izquierda; se puede overridear
#  con template.layout JSONB cuando exista el editor visual)
# ════════════════════════════════════════════════════════════════
DEFAULT_LAYOUT = {
    "frente": {
        "fondo":       {"tipo": "fondo", "src": "frente_prod.png"},
        "microtexto_seg": {"tipo": "microtexto",
                        "text": "COLEGIO DE CONTADORES PUBLICOS DE LORETO • CCPL • JDCCPP • ",
                        "font": "Helvetica", "size": 2.0, "color": "#0E3A6D", "alpha": 0.10,
                        "x": 2, "y": 2, "w": 81.6, "h": 50, "forma": "recta",
                        "angulo": -28, "sep_lineas": 2.4},
        "logo":        {"tipo": "logo", "src": "logo_ccpl.png", "x": 4, "y": 4, "w": 12, "h": 12},
        "org_titulo":  {"tipo": "texto", "text": "COLEGIO DE CONTADORES PÚBLICOS DE LORETO",
                        "x": 18, "y": 4, "w": 46, "size": 8.5, "bold": True, "color": "#0E3A6D"},
        "foto":        {"tipo": "foto", "x": 11, "y": 15, "w": 17, "h": 24},
        "lbl_nombres":   {"tipo": "texto", "text": "NOMBRES:", "x": 31, "y": 14, "size": 6, "bold": True, "color": "#444444"},
        "val_nombres":   {"tipo": "valor", "campo": "nombres", "x": 31, "y": 16.5, "w": 52, "size": 8.5, "bold": True, "color": "#0E3A6D"},
        "lbl_apellidos": {"tipo": "texto", "text": "APELLIDOS:", "x": 31, "y": 22, "size": 6, "bold": True, "color": "#444444"},
        "val_apellidos": {"tipo": "valor", "campo": "apellidos", "x": 31, "y": 24.5, "w": 52, "size": 8.5, "bold": True, "color": "#0E3A6D"},
        "lbl_matricula": {"tipo": "texto", "text": "N° MATRÍCULA:", "x": 31, "y": 30, "size": 6, "bold": True, "color": "#444444"},
        "val_matricula": {"tipo": "valor", "campo": "codigo_matricula", "x": 31, "y": 32.5, "size": 9, "bold": True, "color": "#0E3A6D"},
        "titulo":        {"tipo": "texto", "text": "CONTADOR PÚBLICO COLEGIADO", "x": 31, "y": 38.5, "size": 8, "bold": True, "color": "#0E3A6D"},
        "firma_decano":     {"tipo": "firma", "src": "firma_decano.png", "x": 6, "y": 43, "w": 26, "h": 4.5,
                             "nombre": "CPCC. JORGE LUIS SANTANA SIFUENTES", "cargo": "DECANO",
                             "size_nombre": 5, "size_cargo": 5, "color_nombre": "#333333", "color_cargo": "#B00020"},
        "firma_secretaria": {"tipo": "firma", "src": "firma_secretaria.png", "x": 53, "y": 43, "w": 26, "h": 4.5,
                             "nombre": "CPC. LYA ESTHER GARCIA RAMIREZ", "cargo": "DIRECTORA SECRETARIA",
                             "size_nombre": 5, "size_cargo": 5, "color_nombre": "#333333", "color_cargo": "#B00020"},
    },
    "reverso": {
        "fondo":      {"tipo": "fondo", "src": "reverso_prod.png"},
        "logo":       {"tipo": "logo", "src": "logo_junta.png", "x": 68, "y": 4, "w": 14, "h": 14},
        "lbl_incorp": {"tipo": "texto", "text": "FECHA DE INCORPORACIÓN:", "x": 4, "y": 6, "size": 5.5, "bold": True, "color": "#444444"},
        "val_incorp": {"tipo": "valor", "campo": "fecha_colegiatura", "formato": "larga", "x": 4, "y": 8.7, "size": 8, "bold": True, "color": "#0E3A6D"},
        "lbl_dni":    {"tipo": "texto", "text": "D.N.I.:", "x": 4, "y": 15, "size": 5.5, "bold": True, "color": "#444444"},
        "val_dni":    {"tipo": "valor", "campo": "dni", "x": 4, "y": 17.7, "size": 8, "bold": True, "color": "#0E3A6D"},
        "lbl_ruc":    {"tipo": "texto", "text": "R.U.C.:", "x": 4, "y": 23, "size": 5.5, "bold": True, "color": "#444444"},
        "val_ruc":    {"tipo": "valor", "campo": "ruc", "x": 4, "y": 25.7, "size": 8, "bold": True, "color": "#0E3A6D"},
        "lbl_fnac":   {"tipo": "texto", "text": "F. NACIMIENTO:", "x": 4, "y": 31, "size": 5.5, "bold": True, "color": "#444444"},
        "val_fnac":   {"tipo": "valor", "campo": "fecha_nacimiento", "formato": "corta", "x": 4, "y": 33.7, "size": 8, "bold": True, "color": "#0E3A6D"},
        "lbl_grupo":  {"tipo": "texto", "text": "GRUPO SANGUÍNEO:", "x": 4, "y": 39, "size": 5.5, "bold": True, "color": "#444444"},
        "val_grupo":  {"tipo": "valor", "campo": "tipo_sangre", "x": 4, "y": 41.7, "size": 8, "bold": True, "color": "#0E3A6D"},
        "qr":         {"tipo": "qr", "x": 66, "y": 32, "size": 16, "label": "VERIFICAR COLEGIADO",
                       "size_label": 4.6, "color": "#0E3A6D"},
    },
}


# ── Helpers de negocio ──────────────────────────────────────────
def _color(value, default):
    if not value:
        return default
    try:
        v = str(value).strip()
        if not v.startswith("#"):
            v = "#" + v
        return HexColor(v)
    except Exception:
        return default


def split_nombre(apellidos_nombres):
    """2 primeros bloques = apellidos, resto = nombres. Partículas (DE, DE LA, DEL)
    se pegan al apellido siguiente.
    'PANAIFO MACEDO LORETTE ANNEL'  -> ('PANAIFO MACEDO', 'LORETTE ANNEL')
    'DE LA CRUZ RAMOS MARIA JOSE'   -> ('DE LA CRUZ RAMOS', 'MARIA JOSE')
    """
    toks = (apellidos_nombres or "").split()
    bloques, cur, i = [], [], 0
    while i < len(toks) and len(bloques) < 2:
        cur.append(toks[i])
        if toks[i].upper() not in _PARTICULAS:   # palabra real → cierra el bloque
            bloques.append(" ".join(cur))
            cur = []
        i += 1
    apellidos = " ".join(bloques)
    nombres = " ".join(toks[i:])
    return apellidos, nombres


def ruc_persona_natural(dni):
    """RUC = '10' + DNI(8) + dígito verificador (mód-11).
    72814623 -> 10728146236. DNI inválido -> '' (en blanco)."""
    d = str(dni or "").strip()
    if not d.isdigit() or len(d) != 8:
        return ""
    base = "10" + d
    pesos = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
    s = sum(int(c) * p for c, p in zip(base, pesos))
    dv = 11 - (s % 11)
    dv = 0 if dv == 10 else (1 if dv == 11 else dv)
    return base + str(dv)


def _fmt_fecha(dt, formato="corta"):
    if not dt:
        return ""
    try:
        if formato == "larga":
            return "%d de %s del %d" % (dt.day, _MESES[dt.month], dt.year)
        return dt.strftime("%d/%m/%Y")
    except Exception:
        return ""


def _resolver_valor(campo, cole, el):
    if campo == "nombres":
        return split_nombre(getattr(cole, "apellidos_nombres", None))[1]
    if campo == "apellidos":
        return split_nombre(getattr(cole, "apellidos_nombres", None))[0]
    if campo == "ruc":
        return ruc_persona_natural(getattr(cole, "dni", None))
    if campo in ("fecha_colegiatura", "fecha_nacimiento"):
        return _fmt_fecha(getattr(cole, campo, None), el.get("formato", "corta"))
    v = getattr(cole, campo, None)
    return "" if v is None else str(v)


# ── Helpers de imagen ───────────────────────────────────────────
def _fetch_image(url):
    """ImageReader desde URL remota (GCS foto) o None si falla/tarda/no hay url."""
    if not url:
        return None
    try:
        if str(url).startswith("http"):
            r = requests.get(url, timeout=FETCH_TIMEOUT)
            if r.status_code == 200 and r.content:
                return ImageReader(BytesIO(r.content))
    except Exception as e:
        logger.warning("Credencial: no se pudo bajar imagen %s (%s)", url, e)
    return None


def _disk_image(base_dir, src):
    if not src:
        return None
    ruta = os.path.join(base_dir, src)
    return ImageReader(ruta) if os.path.exists(ruta) else None


def _qr_reader(data):
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,
                       box_size=10, border=0)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return ImageReader(buf)


def _fit_size(c, text, font, max_size, min_size, max_width):
    size = max_size
    while size > min_size and c.stringWidth(text, font, size) > max_width:
        size -= 0.5
    return size


# ── Renderers por tipo de elemento ──────────────────────────────
def _draw_fondo(c, el, tpl, cara):
    """Fondo a sangre. Prioridad: PNG en disco (layout.src) → GCS del template → plano."""
    img = _disk_image(_DIR_FONDOS, el.get("src")) if el else None
    if img is None:
        img = _fetch_image(getattr(tpl, "fondo_%s_url" % cara, None))
    if img is not None:
        c.drawImage(img, 0, 0, CARD_W, CARD_H, preserveAspectRatio=False, mask="auto")
        return
    # Fondo plano temporal (para revisar posiciones antes de tener el fondo real)
    c.setFillColor(FONDO_PLANO)
    c.rect(0, 0, CARD_W, CARD_H, fill=1, stroke=0)
    c.setStrokeColor(HexColor("#CCCCCC"))
    c.setLineWidth(0.2 * mm)
    c.rect(0.3 * mm, 0.3 * mm, CARD_W - 0.6 * mm, CARD_H - 0.6 * mm, fill=0, stroke=1)


def _draw_logo(c, el):
    img = _disk_image(_DIR_LOGOS, el.get("src"))
    if img is None:
        return
    x, y, w, h = el["x"] * mm, el["y"] * mm, el["w"] * mm, el["h"] * mm
    c.drawImage(img, x, CARD_H - y - h, w, h,
                preserveAspectRatio=True, anchor="c", mask="auto")


def _draw_foto(c, el, cole):
    x, y, w, h = el["x"] * mm, el["y"] * mm, el["w"] * mm, el["h"] * mm
    yb = CARD_H - y - h
    c.setFillColor(GRIS_FOTO)
    c.roundRect(x, yb, w, h, 1.2 * mm, fill=1, stroke=0)
    foto = _fetch_image(getattr(cole, "foto_url", None))
    if foto:
        c.saveState()
        p = c.beginPath()
        p.roundRect(x, yb, w, h, 1.2 * mm)
        c.clipPath(p, stroke=0, fill=0)
        c.drawImage(foto, x, yb, w, h, preserveAspectRatio=True, anchor="c", mask="auto")
        c.restoreState()
    else:
        c.setFillColor(GRIS_TXT)
        c.setFont(FONT, 6)
        c.drawCentredString(x + w / 2, yb + h / 2 - 2, "SIN FOTO")
    c.setStrokeColor(_color(el.get("color_borde"), DORADO_CCPL))
    c.setLineWidth(0.4 * mm)
    c.roundRect(x, yb, w, h, 1.2 * mm, fill=0, stroke=1)


def _draw_text_element(c, el, text):
    if not text:
        return
    font = FONT_BOLD if el.get("bold") else FONT
    size = el.get("size", 8)
    max_w = el.get("w")
    if max_w:
        size = _fit_size(c, text, font, size, 4.5, max_w * mm)
    base = CARD_H - el["y"] * mm - size
    x = el["x"] * mm
    align = el.get("align", "left")
    c.setFont(font, size)
    c.setFillColor(_color(el.get("color"), AZUL_CCPL))
    if align == "center":
        c.drawCentredString(x, base, text)
    elif align == "right":
        c.drawRightString(x, base, text)
    else:
        c.drawString(x, base, text)


def _draw_firma(c, el):
    x, y, w, h = el["x"] * mm, el["y"] * mm, el["w"] * mm, el["h"] * mm
    yb = CARD_H - y - h          # línea base de la firma (borde inferior de la caja)
    cx = x + w / 2

    # (a) PNG de firma SOLO si existe (transparente, asentado sobre la línea)
    img = _disk_image(_DIR_FIRMAS, el.get("src"))
    if img is not None:
        c.drawImage(img, x, yb, w, h, preserveAspectRatio=True, anchor="s", mask="auto")

    # (b) Línea de firma SIEMPRE (para firmar a mano si no hay PNG)
    c.setStrokeColor(HexColor("#777777"))
    c.setLineWidth(0.2 * mm)
    c.line(x, yb, x + w, yb)

    # (c) Nombre y cargo SIEMPRE, centrados bajo la línea (desde el layout)
    c.setFillColor(_color(el.get("color_nombre"), GRIS_TXT))
    c.setFont(FONT_BOLD, el.get("size_nombre", 5))
    c.drawCentredString(cx, yb - 2.4 * mm, el.get("nombre", ""))
    c.setFillColor(_color(el.get("color_cargo"), ROJO_CARGO))
    c.setFont(FONT_BOLD, el.get("size_cargo", 5))
    c.drawCentredString(cx, yb - 4.4 * mm, el.get("cargo", ""))


def _draw_qr(c, el, cole):
    mat = (getattr(cole, "codigo_matricula", None) or "").strip()
    if not mat:
        return
    x, y, s = el["x"] * mm, el["y"] * mm, el["size"] * mm
    yb = CARD_H - y - s
    # Panel blanco (quiet zone) para que el QR escanee sobre cualquier fondo
    c.setFillColor(white)
    c.roundRect(x - 1 * mm, yb - 1 * mm, s + 2 * mm, s + 2 * mm, 1 * mm, fill=1, stroke=0)
    c.drawImage(_qr_reader(QR_BASE_URL + mat), x, yb, s, s, mask="auto")
    label = el.get("label")
    if label:
        c.setFillColor(_color(el.get("color"), AZUL_CCPL))
        c.setFont(FONT_BOLD, el.get("size_label", 4.6))
        c.drawCentredString(x + s / 2, yb - 3 * mm, label)


# ── Microtexto de seguridad (configurable por software, NO horneado) ─────
def _draw_microtexto(c, el):
    """Elemento de seguridad configurable desde el layout/plantilla.
    Parámetros: text, font, size, color, alpha, x, y, w, h, forma, angulo,
    sep_lineas, repeticiones (recta) | amplitud, periodo (onda) | radio (arco).
    """
    text = el.get("text", "")
    if not text:
        return
    font = el.get("font", FONT)
    size = float(el.get("size", 2.0))
    x = el["x"] * mm
    y = el["y"] * mm
    w = float(el.get("w", 0)) * mm
    h = float(el.get("h", 0)) * mm
    yb = CARD_H - y - h
    forma = el.get("forma", "recta")

    c.saveState()
    try:
        c.setFillAlpha(float(el.get("alpha", 0.12)))
        c.setFillColor(_color(el.get("color"), AZUL_CCPL))
        c.setFont(font, size)
        if forma == "onda":
            _micro_onda(c, el, text, font, size, x, yb, w, h)
        elif forma == "arco":
            _micro_arco(c, el, text, font, size, x, yb, w, h)
        else:  # "recta" (por defecto): rellena el área con líneas diagonales
            _micro_recta(c, el, text, font, size, x, yb, w, h)
    finally:
        c.restoreState()


def _micro_recta(c, el, text, font, size, x, yb, w, h):
    p = c.beginPath()
    p.rect(x, yb, w, h)
    c.clipPath(p, stroke=0, fill=0)                 # recorta al área
    ang = float(el.get("angulo", 0))
    sep = float(el.get("sep_lineas", 2.2)) * mm
    diag = math.hypot(w, h) or 1
    unit = c.stringWidth(text, font, size) or 1
    linea = text * (int(diag / unit) + 2)           # línea larga para cruzar la diagonal
    c.translate(x + w / 2, yb + h / 2)
    c.rotate(ang)
    reps = el.get("repeticiones")
    n = int(reps) if reps else int(diag / sep) + 2
    for i in range(-(n // 2), n // 2 + 1):
        c.drawCentredString(0, i * sep, linea)


def _micro_onda(c, el, text, font, size, x, yb, w, h):
    amp = float(el.get("amplitud", 1.2)) * mm
    per = (float(el.get("periodo", 18)) * mm) or 1
    unit = c.stringWidth(text, font, size) or 1
    s = text * (int(w / unit) + 2)                  # repetir para cubrir el ancho
    y0 = yb + h / 2
    penx = 0.0
    for ch in s:
        if penx > w:
            break
        yy = amp * math.sin(2 * math.pi * penx / per)
        slope = amp * (2 * math.pi / per) * math.cos(2 * math.pi * penx / per)
        c.saveState()
        c.translate(x + penx, y0 + yy)
        c.rotate(math.degrees(math.atan(slope)))    # inclina el glifo con la tangente
        c.drawString(0, 0, ch)
        c.restoreState()
        penx += c.stringWidth(ch, font, size)


def _micro_arco(c, el, text, font, size, x, yb, w, h):
    R = (float(el.get("radio", 40)) * mm) or 1
    cx = x + w / 2
    cy = yb + h / 2 - R                             # centro debajo → arco convexo arriba
    total = c.stringWidth(text, font, size)
    a = math.pi / 2 + (total / R) / 2               # centra el texto en el tope
    for ch in text:
        gx = cx + R * math.cos(a)
        gy = cy + R * math.sin(a)
        c.saveState()
        c.translate(gx, gy)
        c.rotate(math.degrees(a) - 90)              # tangente al arco
        c.drawCentredString(0, 0, ch)
        c.restoreState()
        a -= c.stringWidth(ch, font, size) / R


_RENDERERS = {
    "logo":       lambda c, el, cole: _draw_logo(c, el),
    "foto":       lambda c, el, cole: _draw_foto(c, el, cole),
    "texto":      lambda c, el, cole: _draw_text_element(c, el, el.get("text", "")),
    "valor":      lambda c, el, cole: _draw_text_element(c, el, _resolver_valor(el.get("campo"), cole, el)),
    "firma":      lambda c, el, cole: _draw_firma(c, el),
    "qr":         lambda c, el, cole: _draw_qr(c, el, cole),
    "microtexto": lambda c, el, cole: _draw_microtexto(c, el),
}


# ── API pública ─────────────────────────────────────────────────
def generar_credencial_pdf(cole, org, tpl):
    """
    Genera el PDF (bytes) del carné CR80 de un colegiado.
    cole = ORM Colegiado ; org = ORM Organization ; tpl = ORM CredentialTemplate.
    Usa tpl.layout (JSONB) si existe; si no, DEFAULT_LAYOUT.
    """
    layout = getattr(tpl, "layout", None) or DEFAULT_LAYOUT

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=(CARD_W, CARD_H))
    c.setTitle("Credencial %s" % (getattr(cole, "codigo_matricula", "") or ""))

    for cara in ("frente", "reverso"):
        capa = layout.get(cara, {})
        _draw_fondo(c, capa.get("fondo"), tpl, cara)
        for nombre_el, el in capa.items():
            if nombre_el == "fondo":
                continue
            render = _RENDERERS.get(el.get("tipo"))
            if render:
                render(c, el, cole)
        c.showPage()

    c.save()
    return buf.getvalue()

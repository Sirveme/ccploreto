"""
Generador de Certificados de Habilitación Digital
==================================================
CCPL - Colegio de Contadores Públicos de Loreto
"""

import io
import os
import qrcode
from datetime import date, datetime
from typing import Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, cm
from reportlab.lib.colors import Color, black, white, HexColor
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.utils import ImageReader
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# Colores institucionales
VERDE_CCPL = HexColor('#2E7D32')
DORADO = HexColor('#C5A028')
GRIS_OSCURO = HexColor('#333333')

# Rutas de assets (ajustar según deployment)
ASSETS_PATH = os.path.join(os.path.dirname(__file__), 'assets')


class CertificadoHabilidad:
    """Genera el PDF del Certificado de Habilitación Digital"""
    
    def __init__(
        self,
        codigo_verificacion: str,
        nombres: str,
        apellidos: str,
        matricula: str,
        fecha_vigencia: date,
        fecha_emision: Optional[datetime] = None,
        en_fraccionamiento: bool = False,
        url_verificacion: str = "https://habilidadccploreto.org.pe/verificacion"
    ):
        self.codigo = codigo_verificacion
        self.nombres = nombres
        self.apellidos = apellidos
        self.nombre_completo = f"CPC. {nombres.upper()} {apellidos.upper()}"
        self.matricula = matricula
        self.fecha_vigencia = fecha_vigencia
        self.fecha_emision = fecha_emision or datetime.now()
        self.en_fraccionamiento = en_fraccionamiento
        self.url_verificacion = url_verificacion
        
        # Autoridades (podrían venir de BD)
        self.decano_nombre = "CPC. Jorge Luis Santana Sifuentes"
        self.secretaria_nombre = "CPC. Lya Esther García Ramírez"
    
    def _generar_qr(self) -> io.BytesIO:
        """Genera QR code con la URL de verificación"""
        url = f"{self.url_verificacion}?codigo={self.codigo}"
        
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=2,
        )
        qr.add_data(url)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)
        return buffer
    
    def _formato_fecha_vigencia(self) -> str:
        """Formatea la fecha de vigencia en español"""
        meses = [
            '', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
            'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre'
        ]
        return f"{self.fecha_vigencia.day} de {meses[self.fecha_vigencia.month]} del {self.fecha_vigencia.year}"
    
    def _formato_fecha_emision(self) -> str:
        """Formatea la fecha de emisión en español"""
        meses = [
            '', 'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
            'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'
        ]
        return f"Iquitos, {self.fecha_emision.day} de {meses[self.fecha_emision.month]} {self.fecha_emision.year}"
    
    def generar(self) -> io.BytesIO:
        """Genera el PDF completo y retorna como BytesIO"""
        buffer = io.BytesIO()
        
        # Crear canvas
        c = canvas.Canvas(buffer, pagesize=A4)
        width, height = A4  # 595.27, 841.89 points
        
        # ============================================
        # MARCA DE AGUA (escudo de fondo)
        # ============================================
        # Si tienes la imagen del escudo como marca de agua
        watermark_path = os.path.join(ASSETS_PATH, 'escudo_watermark.png')
        if os.path.exists(watermark_path):
            c.saveState()
            c.setFillAlpha(0.08)  # Muy transparente
            c.drawImage(watermark_path, 100, 200, width=400, height=400, preserveAspectRatio=True, mask='auto')
            c.restoreState()
        
        # ============================================
        # ENCABEZADO
        # ============================================
        
        # Logo CCPL (arriba izquierda)
        logo_path = os.path.join(ASSETS_PATH, 'logo_ccpl.png')
        if os.path.exists(logo_path):
            c.drawImage(logo_path, 40, height - 100, width=70, height=70, preserveAspectRatio=True, mask='auto')
        
        # Texto del encabezado (junto al logo)
        c.setFont("Helvetica-Bold", 14)
        c.setFillColor(VERDE_CCPL)
        c.drawString(120, height - 50, "COLEGIO DE CONTADORES")
        c.setFont("Helvetica-Bold", 16)
        c.drawString(120, height - 68, "PÚBLICOS DE LORETO")
        
        c.setFont("Helvetica-Oblique", 8)
        c.setFillColor(GRIS_OSCURO)
        c.drawString(120, height - 82, "Gestión con transparencia en beneficio del colega")
        
        c.setFont("Helvetica-Bold", 9)
        c.setFillColor(DORADO)
        c.drawString(120, height - 95, "2026-2027")
        
        # Código de verificación (arriba derecha)
        c.setFont("Helvetica-Bold", 14)
        c.setFillColor(VERDE_CCPL)
        c.drawRightString(width - 40, height - 60, self.codigo)
        
        # Línea separadora
        c.setStrokeColor(VERDE_CCPL)
        c.setLineWidth(2)
        c.line(40, height - 110, width - 40, height - 110)
        
        # Logo IFAC (debajo de la línea)
        ifac_path = os.path.join(ASSETS_PATH, 'logo_ifac.png')
        if os.path.exists(ifac_path):
            c.drawImage(ifac_path, 40, height - 165, width=50, height=40, preserveAspectRatio=True, mask='auto')
        
        # ============================================
        # TÍTULO
        # ============================================
        c.setFont("Helvetica-Bold", 24)
        c.setFillColor(VERDE_CCPL)
        c.drawCentredString(width/2, height - 155, "CERTIFICADO DE HABILITACIÓN")
        c.drawCentredString(width/2, height - 185, "DIGITAL")
        
        # ============================================
        # CUERPO DEL TEXTO
        # ============================================
        y_pos = height - 230
        
        # Párrafo introductorio
        c.setFont("Helvetica", 11)
        c.setFillColor(black)
        
        intro = "El Decano y la Directora Secretaria del Colegio de Contadores Públicos de"
        c.drawCentredString(width/2, y_pos, intro)
        y_pos -= 16
        
        intro2 = "Loreto, que suscriben, declaran que, en base a los registros de la institución,"
        c.drawCentredString(width/2, y_pos, intro2)
        y_pos -= 16
        
        intro3 = "se ha verificado que:"
        c.drawCentredString(width/2, y_pos, intro3)
        y_pos -= 40
        
        # Nombre del colegiado (destacado)
        c.setFont("Helvetica-Bold", 16)
        c.setFillColor(VERDE_CCPL)
        c.drawCentredString(width/2, y_pos, self.nombre_completo)
        y_pos -= 25
        
        # Matrícula
        c.setFont("Helvetica-Bold", 14)
        c.drawCentredString(width/2, y_pos, f"MATRÍCULA: {self.matricula}")
        y_pos -= 40
        
        # Estado HÁBIL
        c.setFont("Helvetica", 11)
        c.setFillColor(black)
        
        # Texto con HÁBIL destacado
        texto1 = "Se encuentra "
        c.drawString(70, y_pos, texto1)
        
        x_habil = 70 + c.stringWidth(texto1, "Helvetica", 11)
        c.setFont("Helvetica-Bold", 11)
        c.setFillColor(VERDE_CCPL)
        c.drawString(x_habil, y_pos, "HÁBIL")
        
        x_after = x_habil + c.stringWidth("HÁBIL", "Helvetica-Bold", 11)
        c.setFont("Helvetica", 11)
        c.setFillColor(black)
        c.drawString(x_after, y_pos, ", para el ejercicio de las funciones profesionales que le")
        y_pos -= 16
        
        c.drawString(70, y_pos, "faculta la Ley N° 13253 y normas modificatorias, conforme al Estatuto y")
        y_pos -= 16
        
        c.drawString(70, y_pos, "Reglamento interno de este Colegio; en fe de lo cual y a solicitud de parte, se")
        y_pos -= 16
        
        c.drawString(70, y_pos, "le extiende la presente constancia para los efectos y usos que estime")
        y_pos -= 16
        
        # Vigencia destacada
        texto_vigencia = f"conveniente. Esta constancia tiene vigencia hasta el "
        c.drawString(70, y_pos, texto_vigencia)
        
        x_fecha = 70 + c.stringWidth(texto_vigencia, "Helvetica", 11)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(x_fecha, y_pos, self._formato_fecha_vigencia())
        y_pos -= 30
        
        # Advertencia
        c.setFont("Helvetica", 10)
        c.setFillColor(GRIS_OSCURO)
        c.drawString(70, y_pos, "En caso de incumplimiento del inciso \"b\" y \"g\" del artículo 15 del Estatuto")
        y_pos -= 14
        c.drawString(70, y_pos, "vigente quedará inhabilitado.")
        y_pos -= 40
        
        # Fecha de emisión (derecha)
        c.setFont("Helvetica", 11)
        c.setFillColor(black)
        c.drawRightString(width - 70, y_pos, self._formato_fecha_emision())
        y_pos -= 80
        
        # ============================================
        # FIRMAS
        # ============================================
        
        # Firma del Decano (izquierda)
        firma_decano_path = os.path.join(ASSETS_PATH, 'firma_decano.png')
        if os.path.exists(firma_decano_path):
            c.drawImage(firma_decano_path, 80, y_pos, width=120, height=60, preserveAspectRatio=True, mask='auto')
        
        # Firma de Secretaria (derecha)
        firma_secretaria_path = os.path.join(ASSETS_PATH, 'firma_secretaria.png')
        if os.path.exists(firma_secretaria_path):
            c.drawImage(firma_secretaria_path, width - 200, y_pos, width=120, height=60, preserveAspectRatio=True, mask='auto')
        
        y_pos -= 15
        
        # Líneas de firma
        c.setStrokeColor(DORADO)
        c.setLineWidth(1)
        c.line(60, y_pos, 230, y_pos)  # Línea izquierda
        c.line(width - 230, y_pos, width - 60, y_pos)  # Línea derecha
        
        y_pos -= 15
        
        # Nombres bajo las firmas
        c.setFont("Helvetica-Bold", 10)
        c.setFillColor(black)
        c.drawCentredString(145, y_pos, self.decano_nombre)
        c.drawCentredString(width - 145, y_pos, self.secretaria_nombre)
        y_pos -= 12
        
        c.setFont("Helvetica", 9)
        c.drawCentredString(145, y_pos, "DECANO")
        c.drawCentredString(width - 145, y_pos, "DIRECTORA SECRETARIA")
        
        # ============================================
        # PIE DE PÁGINA - QR y datos de verificación
        # ============================================
        y_pie = 120
        
        # QR Code (derecha)
        qr_buffer = self._generar_qr()
        c.drawImage(
            ImageReader(qr_buffer),
            width - 130,
            y_pie - 20,
            width=70,
            height=70,
            preserveAspectRatio=True
        )
        
        # Texto de verificación (centro-izquierda del QR)
        c.setFont("Helvetica", 8)
        c.setFillColor(GRIS_OSCURO)
        c.drawCentredString(width/2 - 30, y_pie + 40, f"Código de verificación: {self.codigo}")
        c.drawCentredString(width/2 - 30, y_pie + 28, f"Fecha de impresión: {self.fecha_emision.strftime('%d/%m/%Y %H:%M:%S')}")
        c.drawCentredString(width/2 - 30, y_pie + 16, "Verificar en:")
        c.setFillColor(VERDE_CCPL)
        c.drawCentredString(width/2 - 30, y_pie + 4, self.url_verificacion)
        
        # ============================================
        # PIE DE PÁGINA - Contacto
        # ============================================
        y_contacto = 45
        
        # Línea separadora
        c.setStrokeColor(HexColor('#CCCCCC'))
        c.setLineWidth(0.5)
        c.line(40, y_contacto + 15, width - 40, y_contacto + 15)
        
        c.setFont("Helvetica", 7)
        c.setFillColor(GRIS_OSCURO)
        
        # Iconos + texto de contacto
        contactos = [
            ("📍", "Calle Echenique 451, Iquitos"),
            ("📧", "colegiocontadoresp.loreto@gmail.com"),
            ("📞", "979169813 / 997 226 828"),
            ("🌐", "https://ccploreto.org.pe/")
        ]
        
        x_pos = 60
        for icono, texto in contactos:
            c.drawString(x_pos, y_contacto, f"{icono} {texto}")
            x_pos += 135
        
        # ============================================
        # FINALIZAR
        # ============================================
        c.showPage()
        c.save()
        
        buffer.seek(0)
        return buffer


def generar_certificado_pdf(
    codigo: str,
    nombres: str,
    apellidos: str,
    matricula: str,
    fecha_vigencia: date,
    fecha_emision: datetime = None,
    en_fraccionamiento: bool = False
) -> io.BytesIO:
    """
    Función helper para generar un certificado.
    
    Args:
        codigo: Código de verificación (YYYY-NNNNNNN)
        nombres: Nombres del colegiado
        apellidos: Apellidos del colegiado
        matricula: Número de matrícula (ej: 10-1367)
        fecha_vigencia: Fecha hasta la cual es válido
        fecha_emision: Fecha/hora de emisión (default: ahora)
        en_fraccionamiento: Si está en plan de pagos
    
    Returns:
        BytesIO con el PDF generado
    """
    cert = CertificadoHabilidad(
        codigo_verificacion=codigo,
        nombres=nombres,
        apellidos=apellidos,
        matricula=matricula,
        fecha_vigencia=fecha_vigencia,
        fecha_emision=fecha_emision,
        en_fraccionamiento=en_fraccionamiento
    )
    return cert.generar()


# ============================================
# EJEMPLO DE USO
# ============================================
if __name__ == "__main__":
    from datetime import date, datetime
    
    # Generar certificado de ejemplo
    pdf_buffer = generar_certificado_pdf(
        codigo="2026-0000001",
        nombres="Juan Alberto",
        apellidos="Grandez Flores",
        matricula="10-1367",
        fecha_vigencia=date(2027, 3, 31),
        fecha_emision=datetime.now()
    )
    
    # Guardar a archivo
    with open("certificado_ejemplo.pdf", "wb") as f:
        f.write(pdf_buffer.read())
    
    print("✅ Certificado generado: certificado_ejemplo.pdf")

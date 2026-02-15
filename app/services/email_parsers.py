"""
Servicio: Parsers de Notificaciones Bancarias
app/services/email_parsers.py

Parsea emails de notificación de Yape/Plin/transferencias
para extraer: monto, fecha, código operación, remitente.

Bancos soportados:
- Scotiabank (Plin): bancadigital@scotiabank.com.pe
- Interbank (Plin/Yape): servicioalcliente@netinterbank.com.pe
- BCP (Yape): [por agregar cuando tengamos muestra]
- BBVA (transferencia): [por agregar cuando tengamos muestra]
"""

import re
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

TZ_PERU = timezone(timedelta(hours=-5))

# Meses en español
MESES = {
    'ene': 1, 'feb': 2, 'mar': 3, 'abr': 4, 'may': 5, 'jun': 6,
    'jul': 7, 'ago': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dic': 12,
    'enero': 1, 'febrero': 2, 'marzo': 3, 'abril': 4, 'mayo': 5,
    'junio': 6, 'julio': 7, 'agosto': 8, 'septiembre': 9,
    'octubre': 10, 'noviembre': 11, 'diciembre': 12,
}


class ParseResult:
    """Resultado estandarizado del parseo de un email bancario."""

    def __init__(self):
        self.banco: str = ""                    # scotiabank, interbank, bcp, bbva
        self.tipo_operacion: str = ""           # plin_recibido, yape_recibido, transferencia
        self.monto: float = 0.0
        self.moneda: str = "PEN"
        self.fecha_operacion: Optional[datetime] = None
        self.codigo_operacion: Optional[str] = None
        self.remitente_nombre: Optional[str] = None
        self.cuenta_destino: Optional[str] = None
        self.destino_tipo: Optional[str] = None  # Yape, Plin, Cuenta
        self.parsed: bool = False
        self.error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "banco": self.banco,
            "tipo_operacion": self.tipo_operacion,
            "monto": self.monto,
            "moneda": self.moneda,
            "fecha_operacion": self.fecha_operacion.isoformat() if self.fecha_operacion else None,
            "codigo_operacion": self.codigo_operacion,
            "remitente_nombre": self.remitente_nombre,
            "cuenta_destino": self.cuenta_destino,
            "destino_tipo": self.destino_tipo,
            "parsed": self.parsed,
        }


def _limpiar_texto(text: str) -> str:
    """Limpia el texto del email: normaliza espacios, elimina HTML."""
    # Quitar tags HTML básicos
    text = re.sub(r'<[^>]+>', ' ', text)
    # Normalizar espacios
    text = re.sub(r'\s+', ' ', text)
    # Quitar &nbsp; y similares
    text = re.sub(r'&\w+;', ' ', text)
    return text.strip()


def _extraer_monto(text: str, patron: str) -> Optional[float]:
    """Extrae monto de un patrón como 'S/ 20.00' o 'S/ 1,500.00'."""
    match = re.search(patron, text, re.IGNORECASE)
    if match:
        monto_str = match.group(1).replace(',', '').strip()
        try:
            return float(monto_str)
        except ValueError:
            pass
    return None


# ═══════════════════════════════════════════════════════════
# PARSER: SCOTIABANK (Plin)
# ═══════════════════════════════════════════════════════════

def parse_scotiabank_plin(body: str, subject: str = "") -> ParseResult:
    """
    Parsea email de Scotiabank para transferencia Plin recibida.

    Ejemplo de body:
    "Hola MARTLET, Esta es la constancia de la transferencia Plin que has recibido:
     Monto recibido: S/ 27.00
     Destino: Cuenta Digital Scotiabank *** ***3797
     Fecha y hora: 09/01/2026 a las 17:59:27"
    """
    result = ParseResult()
    result.banco = "scotiabank"
    result.tipo_operacion = "plin_recibido"

    text = _limpiar_texto(body)

    # Monto
    monto = _extraer_monto(text, r'Monto\s+recibido:\s*S/\s*([\d,]+\.?\d*)')
    if monto is None:
        result.error = "No se encontró monto"
        return result
    result.monto = monto

    # Cuenta destino
    cuenta_match = re.search(r'Destino:\s*(.*?)(?:Fecha|$)', text, re.IGNORECASE)
    if cuenta_match:
        result.cuenta_destino = cuenta_match.group(1).strip()
    result.destino_tipo = "Plin"

    # Fecha y hora
    fecha_match = re.search(
        r'Fecha\s+y\s+hora:\s*(\d{2})/(\d{2})/(\d{4})\s+a\s+las\s+(\d{2}):(\d{2}):(\d{2})',
        text, re.IGNORECASE
    )
    if fecha_match:
        d, m, y, hh, mm, ss = [int(x) for x in fecha_match.groups()]
        result.fecha_operacion = datetime(y, m, d, hh, mm, ss, tzinfo=TZ_PERU)

    result.parsed = True
    return result


# ═══════════════════════════════════════════════════════════
# PARSER: INTERBANK (Plin / Yape)
# ═══════════════════════════════════════════════════════════

def parse_interbank(body: str, subject: str = "") -> ParseResult:
    """
    Parsea email de Interbank para Plin o Yape.

    Ejemplo de body:
    "Hola DUILIO, A continuación te enviamos el detalle de tu operación
     Constancia de Pago Plin 08 Feb 2026 12:26 PM
     Código de operación: 56807381
     Cuenta cargo: Cuenta Simple Soles 740 3135422716
     Destinatario: Andrea G Del-aguila Z
     Destino: Yape
     Moneda y monto: S/ 15.00"
    """
    result = ParseResult()
    result.banco = "interbank"

    text = _limpiar_texto(body)

    # Monto
    monto = _extraer_monto(text, r'Moneda\s+y\s+monto:\s*S/\s*([\d,]+\.?\d*)')
    if monto is None:
        result.error = "No se encontró monto"
        return result
    result.monto = monto

    # Código de operación
    cod_match = re.search(r'[Cc][oó]digo\s+de\s+operaci[oó]n:\s*(\d+)', text)
    if cod_match:
        result.codigo_operacion = cod_match.group(1)

    # Destinatario (a quien se envió / de quien se recibió)
    dest_match = re.search(r'Destinatario:\s*(.*?)(?:Destino|Moneda|$)', text, re.IGNORECASE)
    if dest_match:
        result.remitente_nombre = dest_match.group(1).strip()

    # Destino: Yape o Plin
    destino_match = re.search(r'Destino:\s*(.*?)(?:Moneda|$)', text, re.IGNORECASE)
    if destino_match:
        destino = destino_match.group(1).strip().lower()
        result.destino_tipo = destino.capitalize()
        if "yape" in destino:
            result.tipo_operacion = "yape_enviado"  # Interbank envía a Yape
        elif "plin" in destino:
            result.tipo_operacion = "plin_enviado"
        else:
            result.tipo_operacion = "transferencia"
    else:
        result.tipo_operacion = "plin_recibido"

    # Cuenta cargo
    cuenta_match = re.search(r'Cuenta\s+cargo:\s*(.*?)(?:Destinatario|$)', text, re.IGNORECASE)
    if cuenta_match:
        result.cuenta_destino = cuenta_match.group(1).strip()

    # Fecha - formato: "08 Feb 2026 12:26 PM"
    fecha_match = re.search(
        r'(\d{1,2})\s+(\w{3,})\s+(\d{4})\s+(\d{1,2}):(\d{2})\s*(AM|PM)',
        text, re.IGNORECASE
    )
    if fecha_match:
        d = int(fecha_match.group(1))
        mes_str = fecha_match.group(2).lower()[:3]
        y = int(fecha_match.group(3))
        hh = int(fecha_match.group(4))
        mm = int(fecha_match.group(5))
        ampm = fecha_match.group(6).upper()

        m = MESES.get(mes_str, 0)
        if m == 0:
            # Try English months
            eng_months = {'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
                          'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12}
            m = eng_months.get(mes_str, 1)

        if ampm == "PM" and hh != 12:
            hh += 12
        elif ampm == "AM" and hh == 12:
            hh = 0

        result.fecha_operacion = datetime(y, m, d, hh, mm, 0, tzinfo=TZ_PERU)

    result.parsed = True
    return result


# ═══════════════════════════════════════════════════════════
# PARSER: BCP (Yape)
# ═══════════════════════════════════════════════════════════

def parse_bcp_yape(body: str, subject: str = "") -> ParseResult:
    """
    Parsea email de BCP para notificación Yape.
    TODO: Completar cuando tengamos muestra del email real.

    Patrones esperados (estimados):
    - "Te han enviado S/ XX.XX por Yape"
    - "Recibiste S/ XX.XX de NOMBRE"
    """
    result = ParseResult()
    result.banco = "bcp"
    result.tipo_operacion = "yape_recibido"

    text = _limpiar_texto(body)

    # Intentar patrones comunes de BCP
    monto = _extraer_monto(text, r'S/\s*([\d,]+\.?\d*)')
    if monto is None:
        result.error = "No se encontró monto (parser BCP pendiente de calibrar)"
        return result
    result.monto = monto
    result.destino_tipo = "Yape"

    # Nombre del remitente
    remitente_match = re.search(r'(?:de|desde)\s+([A-ZÁÉÍÓÚÑ][A-Za-záéíóúñ\s]+)', text)
    if remitente_match:
        result.remitente_nombre = remitente_match.group(1).strip()

    result.parsed = True
    result.error = "Parser BCP en modo estimado - verificar manualmente"
    return result


# ═══════════════════════════════════════════════════════════
# PARSER: BBVA (Transferencia)
# ═══════════════════════════════════════════════════════════

def parse_bbva(body: str, subject: str = "") -> ParseResult:
    """
    Parsea email de BBVA para notificación de transferencia.
    TODO: Completar cuando tengamos muestra del email real.
    """
    result = ParseResult()
    result.banco = "bbva"
    result.tipo_operacion = "transferencia"

    text = _limpiar_texto(body)

    monto = _extraer_monto(text, r'S/\s*([\d,]+\.?\d*)')
    if monto is None:
        monto = _extraer_monto(text, r'PEN\s*([\d,]+\.?\d*)')
    if monto is None:
        result.error = "No se encontró monto (parser BBVA pendiente de calibrar)"
        return result
    result.monto = monto
    result.destino_tipo = "Cuenta"

    result.parsed = True
    result.error = "Parser BBVA en modo estimado - verificar manualmente"
    return result


# ═══════════════════════════════════════════════════════════
# DISPATCHER: Detecta banco y aplica parser correcto
# ═══════════════════════════════════════════════════════════

# Mapeo de remitentes a parsers
PARSER_MAP = {
    "bancadigital@scotiabank.com.pe": parse_scotiabank_plin,
    "scotiabank.com.pe": parse_scotiabank_plin,
    "servicioalcliente@netinterbank.com.pe": parse_interbank,
    "netinterbank.com.pe": parse_interbank,
    "interbank.pe": parse_interbank,
    # BCP / Yape
    "notificaciones@bcp.com.pe": parse_bcp_yape,
    "bcp.com.pe": parse_bcp_yape,
    "yapeperu": parse_bcp_yape,
    # BBVA
    "bbva.pe": parse_bbva,
    "bbvacontinental.pe": parse_bbva,
}


def detectar_y_parsear(email_from: str, body: str, subject: str = "") -> ParseResult:
    """
    Detecta el banco a partir del remitente y aplica el parser correcto.

    Args:
        email_from: Dirección email del remitente
        body: Cuerpo del email (texto o HTML)
        subject: Asunto del email

    Returns:
        ParseResult con los datos extraídos
    """
    email_lower = email_from.lower().strip()

    # Buscar parser por email exacto o dominio
    parser_fn = None
    for key, fn in PARSER_MAP.items():
        if key in email_lower:
            parser_fn = fn
            break

    if parser_fn is None:
        result = ParseResult()
        result.error = f"No hay parser para: {email_from}"
        return result

    try:
        return parser_fn(body, subject)
    except Exception as e:
        result = ParseResult()
        result.error = f"Error parseando: {str(e)}"
        logger.error(f"Error en parser para {email_from}: {e}", exc_info=True)
        return result


# ═══════════════════════════════════════════════════════════
# TESTS
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Test Scotiabank
    print("=== SCOTIABANK ===")
    body_sb = """Hola MARTLET, Esta es la constancia de la transferencia Plin que has recibido:
    Monto recibido: S/ 27.00
    Destino: Cuenta Digital Scotiabank *** ***3797
    Fecha y hora: 09/01/2026 a las 17:59:27"""
    r = parse_scotiabank_plin(body_sb)
    print(r.to_dict())

    print("\n=== INTERBANK ===")
    body_ib = """Hola DUILIO, A continuación te enviamos el detalle de tu operación
    Constancia de Pago Plin 08 Feb 2026 12:26 PM
    Código de operación: 56807381
    Cuenta cargo: Cuenta Simple Soles 740 3135422716
    Destinatario: Andrea G Del-aguila Z
    Destino: Yape
    Moneda y monto: S/ 15.00"""
    r = parse_interbank(body_ib)
    print(r.to_dict())

    print("\n=== DISPATCHER ===")
    r = detectar_y_parsear("bancadigital@scotiabank.com.pe", body_sb)
    print(f"Scotiabank: {r.to_dict()}")
    r = detectar_y_parsear("servicioalcliente@netinterbank.com.pe", body_ib)
    print(f"Interbank: {r.to_dict()}")
    r = detectar_y_parsear("random@gmail.com", "hola")
    print(f"Desconocido: {r.error}")
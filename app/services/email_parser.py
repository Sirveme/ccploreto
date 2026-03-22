"""
email_parser.py — ColegiosPro
Parser de emails de notificación bancaria (BBVA, BCP, Interbank, Yape, Plin)
Extrae: banco, monto, nro_operacion, fecha, remitente_nombre, concepto
"""

import re
import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime
from email import message_from_bytes
from email.header import decode_header
from email.utils import parsedate_to_datetime
from typing import Optional

logger = logging.getLogger(__name__)


# ── Modelo de resultado ────────────────────────────────────────────────────────
@dataclass
class PagoParseado:
    banco:             str              # 'bbva' | 'bcp' | 'interbank' | 'yape' | 'plin' | 'generico'
    monto:             Optional[float]  = None
    nro_operacion:     Optional[str]    = None
    fecha_operacion:   Optional[datetime] = None
    remitente_nombre:  Optional[str]    = None
    concepto:          Optional[str]    = None
    cuenta_destino:    Optional[str]    = None   # últimos dígitos cuenta destino
    tipo_operacion:    str              = 'transferencia'  # 'transferencia'|'yape'|'plin'|'cajero'
    raw_subject:       str              = ''
    raw_body_hash:     str              = ''
    email_message_id:  str              = ''
    confianza:         int              = 0   # 0-100: qué tan seguros estamos del parse

    @property
    def es_valido(self) -> bool:
        """Mínimo necesario para hacer matching."""
        return self.monto is not None and self.monto > 0

    @property
    def es_pago_recibido(self) -> bool:
        """True si el email es de un pago RECIBIDO (no enviado por la cuenta notificada)."""
        return self.tipo_operacion != 'cajero'


# ── Identificadores de banco por remitente ─────────────────────────────────────
REMITENTES_BANCO = {
    'procesos@bbva.com.pe':              'bbva',
    'notificaciones@bbva.com.pe':        'bbva',
    'notificaciones@notificacionesbcp.com.pe': 'bcp',
    'notificacionescrm@bcp.com.pe':      'bcp',
    'alertas@interbank.com.pe':          'interbank',
    'notificaciones@interbank.com.pe':   'interbank',
    'notificaciones@scotiabank.com.pe':  'scotiabank',
    'info@pagos.yape.com.pe':            'yape',
    'notificaciones@plin.pe':            'plin',
}

# Dominios bancarios permitidos — Capa 2 de seguridad
# Solo se procesan emails cuyo dominio From este en esta lista.
DOMINIOS_BANCARIOS_VALIDOS = {
    'bbva.com.pe',
    'notificacionesbcp.com.pe',
    'bcp.com.pe',
    'interbank.com.pe',
    'scotiabank.com.pe',
    'pagos.yape.com.pe',
    'yape.com.pe',
    'plin.pe',
    'banbif.com.pe',
    'pichincha.com.pe',
    'mibanco.com.pe',
}


def _extraer_dominio_from(from_header):
    """
    Extrae el dominio del campo From.
    'BBVA <procesos@bbva.com.pe>' -> 'bbva.com.pe'
    """
    import re as _re
    match = _re.search(r'<([^>]+)>', from_header)
    email = match.group(1) if match else from_header.strip()
    if '@' in email:
        return email.split('@')[1].lower().strip()
    return ''


def validar_dominio_bancario(from_header):
    """
    Verifica que el remitente pertenece a un dominio bancario conocido.
    Retorna True si es valido, False si debe descartarse.
    """
    dominio = _extraer_dominio_from(from_header)
    if not dominio:
        return False
    for valido in DOMINIOS_BANCARIOS_VALIDOS:
        if dominio == valido or dominio.endswith('.' + valido):
            return True
    return False


# Subjects que indican PAGO RECIBIDO (no enviado/cajero)
SUBJECTS_RECIBIDO = [
    'transferencia recibida',
    'depósito recibido',
    'abono recibido',
    'pago recibido',
    'se ha acreditado',
    'acreditación',
    'te enviaron',
    'recibiste',
    'ingreso de dinero',
]

# Subjects que indican operación PROPIA (cajero, pago hecho por el titular)
SUBJECTS_PROPIO = [
    'cajero automático',
    'cajeros automáticos',
    'yapeo a celular',
    'realizaste',
    'efectuaste',
    'tu operación',
    'compra con tarjeta',
]


# ── Patrones por banco ─────────────────────────────────────────────────────────
class PatronesBBVA:
    monto = [
        r'[Ii]mporte[\s:]+S/\s*([\d,]+\.?\d*)',
        r'[Ii]mporte[\s:\n\r]+([\d,]+\.\d{2})',
        r'Monto[\s:]+S/\s*([\d,]+\.?\d*)',
        r'Monto[\s:\n\r]+([\d,]+\.\d{2})',
        r'S/\s*([\d,]+\.\d{2})',
    ]
    nro_operacion = [
        r'[Nn][°º]?\s*[Oo]peraci[oó]n[\s:]*([A-Z0-9\-]+)',
        r'[Nn][úu]mero\s+de\s+operaci[oó]n[\s:]*([A-Z0-9\-]+)',
        r'[Cc][oó]digo\s+de\s+operaci[oó]n[\s:]*([A-Z0-9\-]+)',
        r'[Nn]ro\.?\s+[Oo]p\.?[\s:]*([A-Z0-9\-]+)',
    ]
    fecha = [
        r'(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2})',
        r'(\d{2}/\d{2}/\d{4})',
    ]
    remitente = [
        r'[Oo]rdenante[\s:]+([A-ZÁÉÍÓÚÑ][^\n\r]{2,60})',
        r'[Ee]nviado\s+por[\s:]+([A-ZÁÉÍÓÚÑ][^\n\r]{2,60})',
        r'[Dd]e[\s:]+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑA-Za-záéíóúñ\s]{4,60})',
    ]
    concepto = [
        r'[Cc]oncepto[\s:]+([^\n\r]{2,100})',
        r'[Gg]losa[\s:]+([^\n\r]{2,100})',
    ]
    cuenta_destino = [
        r'\*{2,}(\d{3,6})',
        r'cuenta\s+\*+(\d{3,6})',
    ]


class PatronesBCP:
    monto = [
        r'[Mm]onto\s+(?:enviado|recibido)[\s:]*S/\s*([\d,]+\.?\d*)',
        r'S/\s*([\d,]+\.?\d*)',
        r'[\$S][/\s]+([\d,]+\.\d{2})',
    ]
    nro_operacion = [
        r'[Nn][úu]mero\s+de\s+operaci[oó]n[\s:]*(\d{6,12})',
        r'[Nn]ro\.?\s+de\s+operaci[oó]n[\s:]*(\d{6,12})',
        r'[Oo]peraci[oó]n\s+realizada[\s\S]{0,30}(\d{6,12})',
    ]
    fecha = [
        r'(\d{1,2}\s+de\s+\w+\s+de\s+\d{4}\s*[-–]\s*\d{2}:\d{2}\s*(?:AM|PM)?)',
        r'(\d{1,2}\s+de\s+\w+\s+de\s+\d{4})',
        r'(\d{2}/\d{2}/\d{4})',
    ]
    remitente = [
        r'[Ee]nviado\s+[aA][\s:]+([A-ZÁÉÍÓÚÑ][^\n\r]{2,60})',
        r'[Rr]emitente[\s:]+([A-ZÁÉÍÓÚÑ][^\n\r]{2,60})',
    ]
    concepto = [
        r'[Mm]ensaje[\s:]+([^\n\r]{2,100})',
        r'[Cc]oncepto[\s:]+([^\n\r]{2,100})',
    ]
    cuenta_destino = [
        r'[Cc]uenta\s+de\s+\w+\s+\*{2,}(\d{3,6})',
        r'\*{3,}(\d{3,6})',
    ]


class PatronesGenericos:
    """Fallback para cualquier banco no identificado."""
    monto = [
        r'[Ii]mporte[\s:]+S/\.?\s*([\d,]+\.?\d*)',
        r'[Mm]onto[\s:]+S/\.?\s*([\d,]+\.?\d*)',
        r'[Ss]aldo[\s:]+S/\.?\s*([\d,]+\.?\d*)',
        r'S/\.?\s*([\d,]+\.\d{2})',
        r'PEN\s+([\d,]+\.?\d*)',
    ]
    nro_operacion = [
        r'[Nn][°º]?\.?\s*[Oo]peraci[oó]n[\s:]+([A-Z0-9\-]{4,20})',
        r'[Nn][°º]?\.?\s*[Tt]ransacci[oó]n[\s:]+([A-Z0-9\-]{4,20})',
        r'[Cc][oó]digo[\s:]+([A-Z0-9\-]{6,20})',
        r'[Rr]eferencia[\s:]+([A-Z0-9\-]{4,20})',
        r'[Nn][úu]mero\s+de\s+operaci[oó]n[\s:]+([A-Z0-9\-]{4,20})',
    ]
    fecha = [
        r'(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}(?::\d{2})?)',
        r'(\d{2}/\d{2}/\d{4})',
        r'(\d{1,2}\s+de\s+\w+\s+de\s+\d{4})',
    ]
    remitente = [
        r'[Oo]rdenante[\s:]+([A-ZÁÉÍÓÚÑ][^\n\r]{2,80})',
        r'[Rr]emitente[\s:]+([A-ZÁÉÍÓÚÑ][^\n\r]{2,80})',
        r'[Dd]e[\s:]+([A-ZÁÉÍÓÚÑ][A-Za-záéíóúñÁÉÍÓÚÑ\s\.]{4,80})',
    ]
    concepto = [
        r'[Cc]oncepto[\s:]+([^\n\r]{2,150})',
        r'[Gg]losa[\s:]+([^\n\r]{2,150})',
        r'[Mm]ensaje[\s:]+([^\n\r]{2,150})',
        r'[Dd]etalle[\s:]+([^\n\r]{2,150})',
    ]


PATRONES_POR_BANCO = {
    'bbva':       PatronesBBVA,
    'bcp':        PatronesBCP,
    'interbank':  PatronesGenericos,
    'scotiabank': PatronesGenericos,
    'yape':       PatronesBCP,    # BCP Yape usa formato BCP
    'plin':       PatronesGenericos,
    'generico':   PatronesGenericos,
}


# ── Helpers ───────────────────────────────────────────────────────────────────
def _limpiar_monto(raw: str) -> Optional[float]:
    """'1,234.50' → 1234.50 | '1234' → 1234.0"""
    try:
        limpio = raw.replace(',', '').strip()
        return float(limpio)
    except (ValueError, TypeError):
        return None


def _parsear_fecha(raw: str) -> Optional[datetime]:
    """Intenta parsear fechas en múltiples formatos peruanos."""
    raw = raw.strip()
    formatos = [
        '%d/%m/%Y %H:%M:%S',
        '%d/%m/%Y %H:%M',
        '%d/%m/%Y',
    ]
    for fmt in formatos:
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            pass

    # "16 de marzo de 2026 - 06:27 PM"
    MESES = {
        'enero':1,'febrero':2,'marzo':3,'abril':4,'mayo':5,'junio':6,
        'julio':7,'agosto':8,'septiembre':9,'octubre':10,'noviembre':11,'diciembre':12,
    }
    m = re.search(r'(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})(?:\s*[-–]\s*(\d{2}):(\d{2})(?:\s*(AM|PM))?)?', raw, re.IGNORECASE)
    if m:
        dia, mes_str, anio = int(m.group(1)), m.group(2).lower(), int(m.group(3))
        mes = MESES.get(mes_str)
        if mes:
            h = int(m.group(4) or 0)
            mi = int(m.group(5) or 0)
            if m.group(6) == 'PM' and h < 12:
                h += 12
            try:
                return datetime(anio, mes, dia, h, mi)
            except ValueError:
                pass
    return None


def _primer_match(texto: str, patrones: list[str]) -> Optional[str]:
    """Devuelve el primer grupo capturado que matchee, limpiando espacios."""
    for patron in patrones:
        m = re.search(patron, texto, re.IGNORECASE | re.MULTILINE)
        if m:
            return m.group(1).strip()
    return None


def _decodificar_header(valor: str) -> str:
    partes = decode_header(valor)
    resultado = []
    for contenido, charset in partes:
        if isinstance(contenido, bytes):
            resultado.append(contenido.decode(charset or 'utf-8', errors='replace'))
        else:
            resultado.append(contenido)
    return ' '.join(resultado)


def _extraer_texto(msg) -> str:
    """Extrae texto plano del email (prefiere text/plain, fallback text/html sin tags)."""
    texto = ''
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == 'text/plain':
                charset = part.get_content_charset() or 'utf-8'
                texto += part.get_payload(decode=True).decode(charset, errors='replace') + '\n'
            elif ct == 'text/html' and not texto:
                charset = part.get_content_charset() or 'utf-8'
                html = part.get_payload(decode=True).decode(charset, errors='replace')
                # Quitar tags HTML básico
                texto += re.sub(r'<[^>]+>', ' ', html) + '\n'
    else:
        charset = msg.get_content_charset() or 'utf-8'
        raw = msg.get_payload(decode=True)
        if raw:
            texto = raw.decode(charset, errors='replace')
            if msg.get_content_type() == 'text/html':
                texto = re.sub(r'<[^>]+>', ' ', texto)
    # Normalizar espacios múltiples
    return re.sub(r'[ \t]{2,}', ' ', texto)


def _detectar_tipo_operacion(subject: str, body: str) -> str:
    """Detecta si es cajero, yape, plin, o transferencia."""
    texto = (subject + ' ' + body).lower()
    if 'cajero' in texto:
        return 'cajero'
    if 'yape' in texto or 'yapeo' in texto:
        return 'yape'
    if 'plin' in texto:
        return 'plin'
    return 'transferencia'


def _es_pago_recibido(subject: str, body: str) -> bool:
    """
    True  = nos llegó dinero (interesa guardar)
    False = el titular hizo un pago/retiro (no interesa para matching)
    """
    s = subject.lower()
    b = body.lower()[:500]  # solo primeros 500 chars del body
    texto = s + ' ' + b

    for kw in SUBJECTS_PROPIO:
        if kw in texto:
            return False
    return True  # por defecto asumir recibido si no hay señal contraria


# ── Parser principal ───────────────────────────────────────────────────────────
def parsear_email(raw_bytes: bytes, organization_id: int = None) -> Optional[PagoParseado]:
    """
    Recibe el email crudo en bytes.
    Retorna PagoParseado o None si no es un email bancario relevante.
    """
    try:
        msg = message_from_bytes(raw_bytes)
    except Exception as e:
        logger.error(f'[Parser] Error parseando bytes del email: {e}')
        return None

    # ── Metadatos básicos ──────────────────────────────────────────────────────
    from_header  = msg.get('From', '')
    subject_raw  = msg.get('Subject', '')
    message_id   = msg.get('Message-ID', '')
    subject      = _decodificar_header(subject_raw)
    body         = _extraer_texto(msg)
    body_hash    = hashlib.sha256(body.encode()).hexdigest()

    # Email completo para análisis
    texto_completo = f"{subject}\n{body}"

    # ── Capa 2: Validar dominio remitente ─────────────────────────────────────
    if not validar_dominio_bancario(from_header):
        logger.warning(
            f'[Parser] SEGURIDAD — dominio no autorizado: '
            f'{from_header[:80]} | {subject[:60]}'
        )
        return None

    # ── Identificar banco ──────────────────────────────────────────────────────
    banco = 'generico'
    from_lower = from_header.lower()
    for remitente_conocido, nombre_banco in REMITENTES_BANCO.items():
        if remitente_conocido in from_lower:
            banco = nombre_banco
            break

    # Si no es de un banco conocido, verificar que al menos mencione banco/operación
    if banco == 'generico':
        keywords_banco = ['bbva', 'bcp', 'interbank', 'scotiabank', 'yape', 'plin',
                         'operaci', 'transferencia', 'depósito', 'abono']
        if not any(kw in texto_completo.lower() for kw in keywords_banco):
            logger.debug(f'[Parser] Email ignorado — no parece bancario: {subject[:60]}')
            return None

    # ── Detectar tipo de operación ─────────────────────────────────────────────
    tipo_op = _detectar_tipo_operacion(subject, body)

    # ── Descartar operaciones propias (cajero, pagos hechos por el titular) ────
    if not _es_pago_recibido(subject, body):
        logger.info(f'[Parser] Descartado — operación propia: {subject[:60]}')
        return None

    # ── Extraer campos con patrones del banco ──────────────────────────────────
    P = PATRONES_POR_BANCO.get(banco, PatronesGenericos)

    monto_raw      = _primer_match(texto_completo, P.monto)
    nro_op_raw     = _primer_match(texto_completo, P.nro_operacion)
    fecha_raw      = _primer_match(texto_completo, P.fecha)
    remitente_raw  = _primer_match(texto_completo, P.remitente)
    concepto_raw   = _primer_match(texto_completo, P.concepto)
    cuenta_raw     = _primer_match(texto_completo, P.cuenta_destino)

    monto  = _limpiar_monto(monto_raw) if monto_raw else None
    fecha  = _parsear_fecha(fecha_raw) if fecha_raw else None

    # ── Calcular nivel de confianza ────────────────────────────────────────────
    confianza = 0
    if monto:         confianza += 40
    if nro_op_raw:    confianza += 30
    if fecha:         confianza += 20
    if remitente_raw: confianza += 10

    resultado = PagoParseado(
        banco            = banco,
        monto            = monto,
        nro_operacion    = nro_op_raw.upper() if nro_op_raw else None,
        fecha_operacion  = fecha,
        remitente_nombre = remitente_raw,
        concepto         = concepto_raw,
        cuenta_destino   = cuenta_raw,
        tipo_operacion   = tipo_op,
        raw_subject      = subject[:300],
        raw_body_hash    = body_hash,
        email_message_id = message_id[:200],
        confianza        = confianza,
    )

    logger.info(
        f'[Parser] banco={banco} monto={monto} nro_op={nro_op_raw} '
        f'fecha={fecha} confianza={confianza}%'
    )
    return resultado


# ── Tests rápidos (ejecutar con python email_parser.py) ──────────────────────
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)

    # Simular email BBVA tipo cajero (debe ser DESCARTADO)
    email_cajero = b"""From: BBVA <procesos@bbva.com.pe>
Subject: Tu operacion en nuestros cajeros automaticos ha sido aprobada
Message-ID: <test-cajero-001>
Content-Type: text/plain; charset=utf-8

Hola, WALTER
OPERACION APROBADA
DETALLES DE OPERACION
Fecha y hora 15/03/2026 09:51:30
Numero de cajero 2921
Moneda PEN
Importe 50.00
Ultimos digitos de tarjeta *8920
"""

    # Simular email BBVA de transferencia RECIBIDA (debe ser PROCESADO)
    email_recibido = b"""From: BBVA <procesos@bbva.com.pe>
Subject: Transferencia recibida en tu cuenta
Message-ID: <test-recibido-001>
Content-Type: text/plain; charset=utf-8

Hola, CCPL
TRANSFERENCIA RECIBIDA
DETALLES DE OPERACION
Fecha y hora 16/03/2026 14:32:10
Numero de operacion OP-2026031600123
Moneda PEN
Importe 500.00
Ordenante JUAN CARLOS PEREZ LOPEZ
Concepto Cuota ordinaria mat 10-0274
Cuenta destino ****3456
"""

    # Simular email BCP Yape (debe ser DESCARTADO — es yapeo enviado)
    email_yape_enviado = b"""From: BCP Notificaciones <notificaciones@notificacionesbcp.com.pe>
Subject: Constancia de Yapeo a Celular - Servicio de Notificaciones BCP
Message-ID: <test-yape-001>
Content-Type: text/plain; charset=utf-8

Hola Loreto Global Inversioneseirl,
Realizaste un yapeo a celular de S/ 130.00 desde tu Cuenta de ahorro Soles.
Monto enviado S/ 130.00
Operacion realizada Yapear a celular
Fecha y hora 16 de marzo de 2026 - 06:27 PM
Enviado a Darvin J Rios M.
Numero de operacion 05072938
"""

    print("=== TEST 1: Cajero BBVA (debe ser None) ===")
    r1 = parsear_email(email_cajero)
    print(f"Resultado: {r1}")

    print("\n=== TEST 2: Transferencia BBVA recibida ===")
    r2 = parsear_email(email_recibido)
    if r2:
        print(f"  banco:           {r2.banco}")
        print(f"  monto:           {r2.monto}")
        print(f"  nro_operacion:   {r2.nro_operacion}")
        print(f"  fecha:           {r2.fecha_operacion}")
        print(f"  remitente:       {r2.remitente_nombre}")
        print(f"  concepto:        {r2.concepto}")
        print(f"  tipo:            {r2.tipo_operacion}")
        print(f"  confianza:       {r2.confianza}%")
        print(f"  es_valido:       {r2.es_valido}")

    print("\n=== TEST 3: Yape enviado BCP (debe ser None) ===")
    r3 = parsear_email(email_yape_enviado)
    print(f"Resultado: {r3}")
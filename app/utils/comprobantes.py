"""
Helpers para mostrar comprobantes en el dashboard.

El campo `comprobantes.numero` es un contador interno del CCPL y puede divergir
del número real emitido por SUNAT (que vive dentro de `facturalo_response`).

Asimismo, `comprobantes.status = 'accepted'` solo indica que facturalo.pro
encoló el comprobante; el estado real de SUNAT vive en `codigo_sunat` /
`estado` dentro de `facturalo_response`.
"""
from typing import Tuple


def _fr_comprobante(comprobante) -> dict:
    fr = getattr(comprobante, "facturalo_response", None) or {}
    if not isinstance(fr, dict):
        return {}
    comp = fr.get("comprobante")
    return comp if isinstance(comp, dict) else {}


def get_numero_display(comprobante) -> str:
    """Número formateado a mostrar: prioriza `numero_formato` de facturalo_response."""
    comp = _fr_comprobante(comprobante)
    numero_formato = comp.get("numero_formato")
    if numero_formato:
        return numero_formato
    serie = comprobante.serie or ""
    numero = comprobante.numero or 0
    return f"{serie}-{str(numero).zfill(8)}"


def get_estado_display(comprobante) -> Tuple[str, str]:
    """
    Etiqueta y color del estado real ante SUNAT.

    Retorna (etiqueta, color):
      - ACEPTADO SUNAT  / verde
      - OBSERVADO SUNAT / naranja
      - ENVIADO A SUNAT / azul
      - ANULADO         / rojo
      - PENDIENTE       / gris
    """
    comp = _fr_comprobante(comprobante)
    codigo_sunat = comp.get("codigo_sunat")
    if codigo_sunat is not None:
        codigo_sunat = str(codigo_sunat)

    if codigo_sunat == "0":
        return ("ACEPTADO SUNAT", "verde")
    if codigo_sunat and codigo_sunat != "0":
        return ("OBSERVADO SUNAT", "naranja")
    if comprobante.status == "accepted":
        return ("ENVIADO A SUNAT", "azul")
    if comprobante.status == "anulado":
        return ("ANULADO", "rojo")
    return ("PENDIENTE", "gris")

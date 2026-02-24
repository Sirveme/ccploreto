"""
Parser de textos de periodos de cuotas ordinarias.

Maneja formatos como:
  - "enero a diciembre 2017"
  - "noviembre y diciembre 2018"
  - "enero a marzo, setiembre a diciembre 2020"
  - "ene, marz-dic 2009"
  - "agosto a diciembre 2013"
  - "2025-01-01 00:00:00"
"""
import re
from datetime import date
from typing import List, Optional

MESES = {
    # Nombres completos
    'enero': 1, 'febrero': 2, 'marzo': 3, 'abril': 4,
    'mayo': 5, 'junio': 6, 'julio': 7, 'agosto': 8,
    'setiembre': 9, 'septiembre': 9, 'octubre': 10,
    'noviembre': 11, 'diciembre': 12,
    # Abreviaciones
    'ene': 1, 'feb': 2, 'mar': 3, 'marz': 3, 'abr': 4,
    'may': 5, 'jun': 6, 'jul': 7, 'ago': 8, 'agos': 8,
    'set': 9, 'sep': 9, 'oct': 10, 'nov': 11, 'dic': 12, 'dici': 12,
}

def _nombre_a_mes(texto: str) -> Optional[int]:
    """Convierte nombre de mes a número. Ej: 'enero' → 1, 'ene' → 1"""
    return MESES.get(texto.strip().lower())

def _rango_meses(desde: int, hasta: int, anio: int) -> List[str]:
    """Genera lista de periodos YYYY-MM para un rango de meses en un año."""
    return [f"{anio}-{m:02d}" for m in range(desde, hasta + 1)]

def _extraer_anio(texto: str) -> Optional[int]:
    """Extrae el año de un texto. Retorna el último número de 4 dígitos encontrado."""
    matches = re.findall(r'\b(20\d{2}|19\d{2})\b', texto)
    return int(matches[-1]) if matches else None

def parsear_periodos(texto: str) -> List[str]:
    """
    Convierte un texto de periodo a lista de strings 'YYYY-MM'.

    Ejemplos:
      "enero a diciembre 2017"              → ['2017-01', ..., '2017-12']
      "noviembre y diciembre 2018"          → ['2018-11', '2018-12']
      "enero a marzo, setiembre a dic 2020" → ['2020-01','2020-02','2020-03',
                                               '2020-09','2020-10','2020-11','2020-12']
      "ene, marz-dic 2009"                  → ['2009-01','2009-03',...,'2009-12']
      "2025-01-01 00:00:00"                 → ['2025-01']
    """
    if not texto or not texto.strip():
        return []

    texto = texto.strip()

    # Caso: formato datetime "YYYY-MM-DD HH:MM:SS" o "YYYY-MM-DD"
    m = re.match(r'^(\d{4})-(\d{2})-\d{2}', texto)
    if m:
        return [f"{m.group(1)}-{m.group(2)}"]

    # Caso: formato directo "YYYY-MM"
    m = re.match(r'^(\d{4})-(\d{2})$', texto)
    if m:
        return [texto]

    # Extraer año del texto completo (siempre al final)
    anio = _extraer_anio(texto)
    if not anio:
        return []

    # Eliminar el año del texto para procesar solo los meses
    texto_sin_anio = re.sub(r'\b(20\d{2}|19\d{2})\b', '', texto).strip().rstrip(',').strip()

    periodos = []

    # Dividir por comas para manejar segmentos múltiples
    # Ej: "enero a marzo, setiembre a diciembre" → 2 segmentos
    segmentos = [s.strip() for s in texto_sin_anio.split(',') if s.strip()]

    for segmento in segmentos:
        segmento = segmento.strip()

        # Patrón: "mes a mes" (rango con "a")
        m = re.match(
            r'^([a-záéíóúñ]+)\s+a\s+([a-záéíóúñ]+)$',
            segmento, re.IGNORECASE
        )
        if m:
            desde = _nombre_a_mes(m.group(1))
            hasta = _nombre_a_mes(m.group(2))
            if desde and hasta:
                periodos.extend(_rango_meses(desde, hasta, anio))
            continue

        # Patrón: "mes-mes" (rango con guión)
        m = re.match(
            r'^([a-záéíóúñ]+)-([a-záéíóúñ]+)$',
            segmento, re.IGNORECASE
        )
        if m:
            desde = _nombre_a_mes(m.group(1))
            hasta = _nombre_a_mes(m.group(2))
            if desde and hasta:
                periodos.extend(_rango_meses(desde, hasta, anio))
            continue

        # Patrón: "mes y mes" (dos meses específicos)
        m = re.match(
            r'^([a-záéíóúñ]+)\s+y\s+([a-záéíóúñ]+)$',
            segmento, re.IGNORECASE
        )
        if m:
            m1 = _nombre_a_mes(m.group(1))
            m2 = _nombre_a_mes(m.group(2))
            if m1:
                periodos.append(f"{anio}-{m1:02d}")
            if m2:
                periodos.append(f"{anio}-{m2:02d}")
            continue

        # Patrón: mes simple
        mes = _nombre_a_mes(segmento)
        if mes:
            periodos.append(f"{anio}-{mes:02d}")

    # Deduplicar y ordenar
    return sorted(set(periodos))


def es_cuota_ordinaria(concepto: str) -> bool:
    """
    Detecta si un concepto del Excel corresponde a cuota ordinaria.
    """
    if not concepto:
        return False
    c = concepto.lower().strip()

    # Fecha datetime directa
    if re.match(r'^\d{4}-\d{2}-\d{2}', c):
        return True

    # Patrones textuales
    indicadores = [
        r'enero\s+a\s+diciembre',
        r'cuota.*ordinaria',
        r'cuota.*mensual',
        r'^(ene|enero|feb|febrero|mar|marzo)',  # empieza con mes
        r'\b(ene|feb|mar|abr|may|jun|jul|ago|set|oct|nov|dic)\b.*\d{4}',
    ]
    return any(re.search(p, c, re.IGNORECASE) for p in indicadores)
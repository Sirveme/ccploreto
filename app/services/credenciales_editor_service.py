"""
app/services/credenciales_editor_service.py
============================================
Parte 7A — Editor visual de layout de credenciales.

Fuente de verdad ÚNICA = el layout JSONB de credential_templates. El editor HTML y
el generador reportlab leen el MISMO layout (mm desde arriba-izquierda). Aquí van las
validaciones del guardado: límites CR80 + test-render ("si guarda, imprime").
"""
from types import SimpleNamespace
from datetime import datetime

from app.services.credencial_reportlab import generar_credencial_pdf

# CR80 (mismas medidas que el generador). mm desde arriba-izquierda.
CARD_W_MM = 85.60
CARD_H_MM = 53.98
TOL_MM = 0.5   # tolerancia de borde (redondeos)

# pt→mm para estimar el alto del texto (reportlab usa 'size' en puntos).
_PT_A_MM = 25.4 / 72.0   # ≈ 0.3528


def colegiado_demo():
    """Colegiado de EJEMPLO para el modelo del editor (no toca la BD). Cubre todos los
    campos que el generador lee vía _resolver_valor / _draw_foto."""
    return SimpleNamespace(
        apellidos_nombres="APELLIDO PATERNO MATERNO NOMBRE",
        codigo_matricula="10-0000",
        dni="00000000",
        fecha_colegiatura=datetime(2015, 3, 12),
        fecha_nacimiento=datetime(1985, 6, 20),
        tipo_sangre="O+",
        condicion="habil",
        especialidad="",
        foto_url=None,
    )


def _bbox_mm(nombre, el):
    """(w, h) aproximados en mm del elemento, para el chequeo de límites."""
    tipo = el.get("tipo")
    if tipo in ("logo", "foto", "firma", "microtexto"):
        return (el.get("w") or 0.0), (el.get("h") or 0.0)
    if tipo == "qr":
        s = el.get("size") or 0.0
        return s, s
    if tipo in ("texto", "valor"):
        w = el.get("w") or 0.0                       # ancho máximo si está definido
        h = (el.get("size") or 8) * _PT_A_MM         # alto ≈ tamaño de fuente
        return w, h
    return 0.0, 0.0


def validar_bounds(layout):
    """Devuelve lista de errores: elementos que se salen de 85.60×53.98 mm.
    Lista vacía = todo dentro de la CR80."""
    errores = []
    for cara, capa in (layout or {}).items():
        if not isinstance(capa, dict):
            continue
        for nombre, el in capa.items():
            if nombre == "fondo" or not isinstance(el, dict):
                continue
            x = el.get("x")
            y = el.get("y")
            if x is None or y is None:
                continue
            w, h = _bbox_mm(nombre, el)
            if x < -TOL_MM or y < -TOL_MM:
                errores.append("%s/%s: posición negativa (x=%s, y=%s)" % (cara, nombre, x, y))
            if x + w > CARD_W_MM + TOL_MM:
                errores.append("%s/%s: se sale por la derecha (x+w=%.1f > %.2f)" % (cara, nombre, x + w, CARD_W_MM))
            if y + h > CARD_H_MM + TOL_MM:
                errores.append("%s/%s: se sale por abajo (y+alto=%.1f > %.2f)" % (cara, nombre, y + h, CARD_H_MM))
    return errores


def test_render_layout(org, tpl, nuevo_layout):
    """Genera un PDF de prueba con el layout nuevo (modelo demo, marca MUESTRA).
    Devuelve (ok, error). Si reventó, ok=False y error con el detalle → NO guardar."""
    shim = SimpleNamespace(
        layout=nuevo_layout,
        fondo_frente_url=getattr(tpl, "fondo_frente_url", None),
        fondo_reverso_url=getattr(tpl, "fondo_reverso_url", None),
        nombre=getattr(tpl, "nombre", "modelo"),
    )
    try:
        pdf = generar_credencial_pdf(colegiado_demo(), org, shim, token=None, muestra=True)
    except Exception as e:
        return (False, "El PDF falló al generarse: %s" % e)
    if not pdf or len(pdf) < 500:
        return (False, "El PDF generado quedó vacío o corrupto")
    return (True, None)

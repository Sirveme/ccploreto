"""
app/services/parametros_service.py
Módulo de Parámetros del Sistema — lectura/escritura versionada por vigencia.

Generaliza el patrón probado en producción de junta_config_aporte:
tabla ÚNICA versionada (historial = filas), una sola fila VIGENTE por
(ámbito, seccion, clave), resolución override-org -> global.

Requisitos previos:
  ⚠️ Correr sql/zClaude-parametros.sql en PGAdmin (crea parametros_sistema +
     parametros_secciones + precarga la sección 'fraccionamiento'). La app NO
     corre create_all: sin ese SQL las tablas no existen.

Convenciones (coherentes con el diseño aprobado):
  • Porcentaje en formato HUMANO: 20 = 20% (compatibilidad con politicas_financieras).
  • Ámbito: organizacion_id NULL = global; un entero = override de esa organización.
    La lectura prefiere el override de la org; si no hay, cae al global.
  • Versionado sin solape: set_param cierra la fila vigente (vigencia_hasta = hoy-1)
    e inserta la nueva (vigencia_desde = hoy, origen='admin', reemplaza_id = anterior).
  • NO reescribe ninguna fórmula congelada. get_fraccionamiento() solo ENTREGA el
    dict de configuración; el cálculo sigue en fraccionamiento_service.py.

Estilo: raw SQL con text(), igual que aportes_junta_service. Ningún commit parcial:
set_param confirma al final; los lectores no escriben.
"""

from datetime import date, timedelta
import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# tipo -> columna física donde vive el valor
_COLUMNA_POR_TIPO = {
    "moneda": "valor_numerico",
    "numero": "valor_numerico",
    "porcentaje": "valor_numerico",
    "entero": "valor_numerico",
    "booleano": "valor_booleano",
    "json": "valor_json",
    "texto": "valor_texto",
}

# Claves de la sección fraccionamiento en el ORDEN/forma de CONFIG_DEFECTO
# (politicas_financieras.py). get_fraccionamiento debe devolverlas TODAS para ser
# drop-in real de CONFIG_DEFECTO['fraccionamiento'] (sin fallbacks parciales).
_CLAVES_FRACCIONAMIENTO = (
    "monto_minimo",
    "cuota_inicial_pct",
    "cuota_minima",
    "max_cuotas",
    "interes_mensual_pct",
    "dia_vencimiento",
    "requiere_autorizacion",
    "documentar_acuerdo",
    "habilidad_temporal",
    "dias_gracia",
    # extras operativos (alerta de pérdida) — no vienen de CONFIG_DEFECTO pero
    # pertenecen a la sección; incluirlos hace a la tabla la única fuente.
    "cuotas_impagas_perdida",
    "perdida_automatica",
)


def _coerce(tipo, num, txt, boo, js):
    """Devuelve el valor nativo Python según el tipo, tomando la columna correcta."""
    if tipo == "booleano":
        return bool(boo) if boo is not None else None
    if tipo == "texto":
        return txt
    if tipo == "json":
        return js
    if num is None:
        return None
    f = float(num)
    if tipo == "entero":
        return int(round(f))
    if tipo == "porcentaje":
        # humano: 20 = 20%. Entero si es entero, si no float.
        return int(round(f)) if f == int(f) else f
    # moneda / numero
    return f


def get_param(db: Session, seccion, clave, org_id=1, en_fecha=None, default=None):
    """Valor vigente de un parámetro, resolviendo override org -> global.

    Prefiere la fila de la organización sobre la global; dentro del mismo ámbito
    toma la de vigencia más reciente. Devuelve `default` si no existe.
    """
    hoy = en_fecha or date.today()
    row = db.execute(text("""
        SELECT tipo, valor_numerico, valor_texto, valor_booleano, valor_json
        FROM parametros_sistema
        WHERE seccion = :sec AND clave = :cla
          AND (organizacion_id = :org OR organizacion_id IS NULL)
          AND vigencia_desde <= :hoy
          AND (vigencia_hasta IS NULL OR vigencia_hasta >= :hoy)
        ORDER BY (organizacion_id IS NULL), vigencia_desde DESC
        LIMIT 1
    """), {"sec": seccion, "cla": clave, "org": org_id, "hoy": hoy}).fetchone()
    if not row:
        return default
    return _coerce(row.tipo, row.valor_numerico, row.valor_texto,
                   row.valor_booleano, row.valor_json)


def get_seccion(db: Session, seccion, org_id=1, en_fecha=None):
    """Todos los parámetros vigentes de una sección como dict {clave: valor}.

    Por clave gana el override de la org sobre el global, y dentro del ámbito la
    vigencia más reciente (DISTINCT ON).
    """
    hoy = en_fecha or date.today()
    rows = db.execute(text("""
        SELECT DISTINCT ON (clave)
               clave, tipo, valor_numerico, valor_texto, valor_booleano, valor_json
        FROM parametros_sistema
        WHERE seccion = :sec
          AND (organizacion_id = :org OR organizacion_id IS NULL)
          AND vigencia_desde <= :hoy
          AND (vigencia_hasta IS NULL OR vigencia_hasta >= :hoy)
        ORDER BY clave, (organizacion_id IS NULL), vigencia_desde DESC
    """), {"sec": seccion, "org": org_id, "hoy": hoy}).fetchall()
    return {r.clave: _coerce(r.tipo, r.valor_numerico, r.valor_texto,
                             r.valor_booleano, r.valor_json) for r in rows}


def get_fraccionamiento(db: Session, org_id=1, en_fecha=None):
    """Drop-in de CONFIG_DEFECTO['fraccionamiento']: dict COMPLETO desde la tabla.

    Devuelve las mismas claves y tipos que el literal de politicas_financieras
    (cuota_inicial_pct en humano: 20). Si la tabla aún no tiene una clave (p.ej.
    antes de correr el SQL), esa clave sale como None — señal de que falta precarga,
    no un fallback silencioso a otro valor.
    """
    sec = get_seccion(db, "fraccionamiento", org_id=org_id, en_fecha=en_fecha)
    faltantes = [k for k in _CLAVES_FRACCIONAMIENTO if k not in sec]
    if faltantes:
        logger.warning(
            "[parametros] sección fraccionamiento incompleta, faltan claves: %s "
            "(¿corriste sql/zClaude-parametros.sql?)", faltantes)
    return {k: sec.get(k) for k in _CLAVES_FRACCIONAMIENTO}


def get_secciones(db: Session, solo_activas=True):
    """Catálogo de secciones para el panel del Administrador (parametros_secciones)."""
    where = "WHERE activo = TRUE" if solo_activas else ""
    rows = db.execute(text(
        "SELECT seccion, etiqueta, descripcion, orden, activo "
        "FROM parametros_secciones " + where + " ORDER BY orden, seccion"
    )).fetchall()
    return [dict(r._mapping) for r in rows]


def historial(db: Session, seccion, clave, org_id=None):
    """Todas las versiones de un parámetro (registro de cambios), más reciente primero.

    org_id=None -> historial del ámbito GLOBAL. Un entero -> historial de esa org.
    La versión anterior de cada fila es su `reemplaza_id`.
    """
    rows = db.execute(text("""
        SELECT id, organizacion_id, tipo, valor_numerico, valor_texto,
               valor_booleano, valor_json, vigencia_desde, vigencia_hasta,
               origen, reemplaza_id, motivo, created_by, created_at
        FROM parametros_sistema
        WHERE seccion = :sec AND clave = :cla
          AND organizacion_id IS NOT DISTINCT FROM :org
        ORDER BY vigencia_desde DESC, id DESC
    """), {"sec": seccion, "cla": clave, "org": org_id}).fetchall()
    out = []
    for r in rows:
        d = dict(r._mapping)
        d["valor"] = _coerce(r.tipo, r.valor_numerico, r.valor_texto,
                             r.valor_booleano, r.valor_json)
        out.append(d)
    return out


def set_param(db: Session, seccion, clave, nuevo_valor, *,
              org_id=None, usuario_id=None, motivo=None, en_fecha=None):
    """Versiona un parámetro: cierra la fila vigente e inserta la nueva.

    Hereda tipo/unidad/etiqueta/descripcion/valor_min/max/editable/orden de la fila
    vigente (misma clave, mismo ámbito). El ámbito se casa con IS NOT DISTINCT FROM
    para tratar NULL (global) como un valor. Hace commit al final.

    Reglas:
      • No permite editar una clave marcada editable=FALSE (lanza ValueError).
      • Si no hay fila vigente previa en el ámbito -> ValueError (usar crear_override
        / precarga primero; set_param solo VERSIONA lo existente).
      • Rango: si hay valor_min/valor_max y el tipo es numérico, valida.
    """
    hoy = en_fecha or date.today()
    actual = db.execute(text("""
        SELECT id, tipo, unidad, etiqueta, descripcion, valor_min, valor_max,
               editable, orden
        FROM parametros_sistema
        WHERE seccion = :sec AND clave = :cla
          AND organizacion_id IS NOT DISTINCT FROM :org
          AND vigencia_hasta IS NULL
        LIMIT 1
    """), {"sec": seccion, "cla": clave, "org": org_id}).fetchone()

    if not actual:
        raise ValueError(
            "No existe versión vigente de %s.%s en el ámbito org=%r; "
            "set_param solo versiona parámetros existentes." % (seccion, clave, org_id))
    if not actual.editable:
        raise ValueError("El parámetro %s.%s no es editable." % (seccion, clave))

    tipo = actual.tipo
    columna = _COLUMNA_POR_TIPO.get(tipo)
    if not columna:
        raise ValueError("Tipo desconocido para %s.%s: %r" % (seccion, clave, tipo))

    # Validación de rango para numéricos
    if columna == "valor_numerico" and nuevo_valor is not None:
        v = float(nuevo_valor)
        if actual.valor_min is not None and v < float(actual.valor_min):
            raise ValueError("%s.%s = %s por debajo del mínimo %s" %
                             (seccion, clave, v, actual.valor_min))
        if actual.valor_max is not None and v > float(actual.valor_max):
            raise ValueError("%s.%s = %s por encima del máximo %s" %
                             (seccion, clave, v, actual.valor_max))

    # 1) Cerrar la vigente en hoy-1 (evita solape con la nueva que abre hoy)
    db.execute(text("""
        UPDATE parametros_sistema
        SET vigencia_hasta = :ayer
        WHERE id = :id
    """), {"ayer": hoy - timedelta(days=1), "id": actual.id})

    # 2) Insertar la nueva versión, heredando metadatos y poniendo el valor en su columna
    params = {
        "org": org_id, "sec": seccion, "cla": clave, "tipo": tipo,
        "unidad": actual.unidad, "etiqueta": actual.etiqueta,
        "descripcion": actual.descripcion, "vmin": actual.valor_min,
        "vmax": actual.valor_max, "editable": actual.editable, "orden": actual.orden,
        "desde": hoy, "reemplaza": actual.id, "motivo": motivo,
        "por": usuario_id, "valnum": None, "valtxt": None, "valboo": None, "valjson": None,
    }
    if columna == "valor_numerico":
        params["valnum"] = nuevo_valor
    elif columna == "valor_booleano":
        params["valboo"] = bool(nuevo_valor)
    elif columna == "valor_json":
        params["valjson"] = nuevo_valor
    else:
        params["valtxt"] = nuevo_valor

    new_id = db.execute(text("""
        INSERT INTO parametros_sistema
          (organizacion_id, seccion, clave, tipo,
           valor_numerico, valor_texto, valor_booleano, valor_json,
           unidad, etiqueta, descripcion, valor_min, valor_max, editable, orden,
           vigencia_desde, vigencia_hasta, origen, reemplaza_id, motivo, created_by)
        VALUES
          (:org, :sec, :cla, :tipo,
           :valnum, :valtxt, :valboo, :valjson,
           :unidad, :etiqueta, :descripcion, :vmin, :vmax, :editable, :orden,
           :desde, NULL, 'admin', :reemplaza, :motivo, :por)
        RETURNING id
    """), params).scalar()

    db.commit()
    logger.info("[parametros] %s.%s (org=%r) versionado: fila %s -> %s por usuario %r",
                seccion, clave, org_id, actual.id, new_id, usuario_id)
    return new_id

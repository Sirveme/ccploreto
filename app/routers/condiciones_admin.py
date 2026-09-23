"""
app/routers/condiciones_admin.py
API de LECTURA del módulo Presets de Condiciones y Exoneraciones (Paso 4 · UI).

Solo lectura por ahora: devuelve el preset activo, sus valores agrupados (con
color, etiqueta y artículo + texto literal del Estatuto para el tooltip), la lista
de presets y la vista de diferencias contra el preset "Estatuto CCPL RD 013-2020".

La activación / preview de impacto es el PASO 5 (no está aquí).
Roles: admin + sote (sote mantenedor durante el desarrollo, igual que /admin/parametros).
"""
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.models import Member
from app.routers.dashboard import get_current_member

router = APIRouter(prefix="/api/admin/condiciones", tags=["condiciones"])

ORG_CCPL = 1


class ActivarIn(BaseModel):
    preset_id: int
    motivo: str = ""


class CrearIn(BaseModel):
    nombre: str


class EditarValorIn(BaseModel):
    clave: str
    valor: object   # int | bool | str | list, según el tipo de la clave


class ReEvaluarIn(BaseModel):
    dry_run: bool = True
    confirmacion: str = ""    # para EJECUTAR debe ser exactamente "RE-EVALUAR"
    entiendo: bool = False     # checkbox "entiendo que cambia condiciones reales"

# ── Textos LITERALES del Estatuto/Reglamento (para el tooltip) ────────────────
LITERALES = {
    "Art. 8": "Son miembros Vitalicios los miembros ordinarios que cumplan 30 años "
              "de colegiatura y cotización efectiva.",
    "Art. 15-g": "Pagar obligatoria y puntualmente las cuotas ordinarias, extraordinarias "
                 "y las multas, excepto los miembros vitalicios, para lo cual el Consejo "
                 "Directivo emitirá de oficio la respectiva resolución.",
    "Art. 18-g": "Por adeudar tres (03) cuotas ordinarias y/o una (1) cuota extraordinaria "
                 "y/o una (1) multa.",
    "Art. 114-d Regl.": "Por adeudar al Colegio departamental veinticuatro (24) cuotas ordinarias. "
                        "(Causal de pérdida de la calidad de miembro; suspende la colegiatura de "
                        "forma automática previa gestión de cobranza.)",
    "Acuerdo fracc.": "Acuerdo interno de fraccionamiento (sin artículo de Estatuto).",
    "Acuerdo interno": "Acuerdo interno del Consejo Directivo (sin artículo de Estatuto).",
}

# ── Metadatos de presentación por clave: grupo, etiqueta, artículo, orden ──────
# color por GRUPO (acento distinto, alto contraste sobre slate). El artículo aquí
# es el de DISPLAY (curado); el valor sale de preset_valores.
GRUPOS = [
    ("Inhabilidad",     "#fb7185"),   # rose
    ("Retiro",          "#fbbf24"),   # amber
    ("Fraccionamiento", "#38bdf8"),   # sky
    ("Vitalicio",       "#a78bfa"),   # violet
    ("Exoneraciones",   "#34d399"),   # emerald
]
CLAVES_META = {
    "inhab_cuotas_ordinarias":          ("Inhabilidad",     "Cuotas ordinarias impagas",        "Art. 18-g",      1),
    "inhab_extraordinaria":             ("Inhabilidad",     "Cuota extraordinaria (Bingazo)",   "Art. 18-g",      2),
    "inhab_multa":                      ("Inhabilidad",     "Multa",                            "Art. 18-g",      3),
    "inhab_fracc_cuotas":               ("Inhabilidad",     "Cuotas de fraccionamiento atrasadas", "Acuerdo fracc.", 4),
    "retiro_auto_meses":                ("Retiro",          "Meses de cuota impaga",            "Art. 114-d Regl.", 5),
    "perdida_fracc_consecutivas":       ("Fraccionamiento", "Cuotas consecutivas → pérdida",    "Acuerdo interno", 6),
    "perdida_automatica":               ("Fraccionamiento", "Pérdida automática",               "",               7),
    "vitalicio_declaracion":            ("Vitalicio",       "Declaración",                      "Art. 8",         8),
    "vitalicio_anios":                  ("Vitalicio",       "Años de colegiatura",              "Art. 8",         9),
    "vitalicio_exige_cotizacion":       ("Vitalicio",       "Exige cotización efectiva",        "Art. 8",         10),
    "vitalicio_exento_cuotas":          ("Vitalicio",       "Exento de cuotas nuevas",          "Art. 15-g",      11),
    "condiciones_exentas_generacion":   ("Exoneraciones",   "Exentas de generación de cuota",   "",               12),
    "condiciones_sin_deuda_computable": ("Exoneraciones",   "Sin deuda computable",             "",               13),
}


def require_admin(member: Member = Depends(get_current_member)) -> Member:
    if member.role not in ("admin", "sote"):
        raise HTTPException(403, detail="Acceso restringido a administración")
    return member


def _nativo(tipo, num, boo, txt, js):
    if tipo == "int":
        return int(round(float(num))) if num is not None else None
    if tipo == "bool":
        return bool(boo) if boo is not None else None
    if tipo == "enum":
        return txt
    if tipo == "set":
        return list(js) if js is not None else []
    return None


def _display(clave, tipo, val):
    if tipo == "int":
        return str(val)
    if tipo == "bool":
        if clave == "perdida_automatica":
            return "Activada" if val else "Desactivada"
        return "Sí" if val else "No"
    if tipo == "enum":
        return {"manual": "Manual", "automatico": "Automática"}.get(val, val or "—")
    if tipo == "set":
        return ", ".join(val) if val else "—"
    return "—"


def _valores_de(db, preset_id):
    filas = db.execute(text(
        "SELECT clave, tipo, valor_numerico, valor_booleano, valor_texto, valor_json "
        "FROM preset_valores WHERE preset_id = :p"
    ), {"p": preset_id}).fetchall()
    out = {}
    for f in filas:
        out[f.clave] = (f.tipo, _nativo(f.tipo, f.valor_numerico, f.valor_booleano,
                                        f.valor_texto, f.valor_json))
    return out


# ── PREVIEW DE ACTIVACIÓN (5a) — read-only, no escribe ────────────────────────
_UMBRALES = ("inhab_cuotas_ordinarias", "inhab_extraordinaria", "inhab_multa",
             "inhab_fracc_cuotas", "retiro_auto_meses")
# canónica → clave legacy de org.config.finanzas.habilidad (que lee evaluar_habilidad)
_A_LEGACY = {
    "inhab_cuotas_ordinarias": "cuotas_para_inhabilitar",
    "inhab_extraordinaria":    "extraordinarias_para_inhabilitar",
    "inhab_multa":             "multas_para_inhabilitar",
    "inhab_fracc_cuotas":      "fracc_cuotas_para_inhabilitar",
    "retiro_auto_meses":       "cuotas_para_retiro",
}


def _umbrales_de(valores):
    """Extrae los 5 umbrales (int) de un dict {clave:(tipo,val)}."""
    return {k: int(valores[k][1]) for k in _UMBRALES if k in valores}


def _org_con_umbrales(umbrales):
    """org dict con los umbrales inyectados en config.finanzas.habilidad, para
    evaluar_habilidad(db=None) — usa esos umbrales SIN tocar el preset activo."""
    hab = {_A_LEGACY[k]: v for k, v in umbrales.items()}
    return {"id": ORG_CCPL, "config": {"finanzas": {"habilidad": hab}}}


def _cond_resultante(condicion, r):
    """Réplica de la decisión de sincronizar_condicion: qué condición daría este
    resultado. Vitalicio nunca cambia; fracc protege; solo hábil↔inhábil."""
    if condicion == "vitalicio":
        return "vitalicio"
    if r.debe_inhabilitar and condicion == "habil" and not r.tiene_fracc:
        return "inhabil"
    if not r.debe_inhabilitar and condicion == "inhabil" and not r.tiene_fracc:
        return "habil"
    return condicion


def _band_ids(db, actual_um, cand_um):
    """IDs de colegiados que PODRÍAN cambiar de condición por el cambio de umbrales
    (optimización de banda). Vacío si ningún umbral cambió → 0 flips instantáneo."""
    ids = set()
    # cuotas ordinarias / retiro → banda por conteo de cuotas ordinarias pendientes
    rangos = []
    for k in ("inhab_cuotas_ordinarias", "retiro_auto_meses"):
        a, c = actual_um.get(k), cand_um.get(k)
        if a is not None and c is not None and a != c:
            rangos.append((min(a, c) - 1, max(a, c) + 1))
    if rangos:
        lo = min(r[0] for r in rangos)
        rows = db.execute(text(
            "SELECT colegiado_id FROM debts WHERE organization_id=:o AND debt_type='cuota_ordinaria' "
            "AND status IN ('pending','partial') AND estado_gestion IN ('vigente','en_cobranza') "
            "GROUP BY colegiado_id HAVING COUNT(*) >= :lo"
        ), {"o": ORG_CCPL, "lo": max(lo, 0)}).fetchall()
        ids.update(r[0] for r in rows)
    # extraordinaria / multa → banda = quienes tienen ese concepto pendiente
    conceptos = []
    if actual_um.get("inhab_extraordinaria") != cand_um.get("inhab_extraordinaria"):
        conceptos.append("%extraordinaria%"); conceptos.append("%bingazo%")
    if actual_um.get("inhab_multa") != cand_um.get("inhab_multa"):
        conceptos.append("%multa%")
    for patt in conceptos:
        rows = db.execute(text(
            "SELECT DISTINCT colegiado_id FROM debts WHERE organization_id=:o "
            "AND status IN ('pending','partial') AND estado_gestion IN ('vigente','en_cobranza') "
            "AND concept ILIKE :p AND colegiado_id IS NOT NULL"
        ), {"o": ORG_CCPL, "p": patt}).fetchall()
        ids.update(r[0] for r in rows)
    # fracc → banda = fracc activos
    if actual_um.get("inhab_fracc_cuotas") != cand_um.get("inhab_fracc_cuotas"):
        rows = db.execute(text(
            "SELECT DISTINCT colegiado_id FROM fraccionamientos WHERE organization_id=:o AND estado='activo'"
        ), {"o": ORG_CCPL}).fetchall()
        ids.update(r[0] for r in rows)
    return ids


@router.get("/preview-activacion/{preset_id}")
async def preview_activacion(
    preset_id: int,
    db: Session = Depends(get_db),
    member: Member = Depends(require_admin),
):
    """Simula (SIN escribir) el impacto de activar `preset_id`. Distingue FLIP de
    condición (por cambio de umbrales, sobre la banda afectada) de 'a revisar'
    (vitalicios que dejarían de cumplir cotización efectiva)."""
    from app.models import Colegiado
    from app.services.evaluar_habilidad import evaluar_habilidad
    from app.routers.pagos_publicos import calcular_deuda_total

    activo = db.execute(text(
        "SELECT id, nombre FROM presets_condiciones WHERE organizacion_id=:o AND activo=TRUE LIMIT 1"
    ), {"o": ORG_CCPL}).first()
    target = db.execute(text(
        "SELECT id, nombre FROM presets_condiciones WHERE id=:p AND organizacion_id=:o"
    ), {"p": preset_id, "o": ORG_CCPL}).first()
    if not target:
        raise HTTPException(404, detail="Preset no encontrado")
    if activo and activo.id == target.id:
        return JSONResponse({"es_activo": True, "mensaje": "Ese preset ya está activo."})

    val_act = _valores_de(db, activo.id) if activo else {}
    val_cand = _valores_de(db, target.id)
    um_act = _umbrales_de(val_act)
    um_cand = _umbrales_de(val_cand)

    # ── Rama FLIP (cambio de umbrales) — solo sobre la banda afectada ──────────
    flips = []
    band = _band_ids(db, um_act, um_cand)
    if band:
        org_cur = _org_con_umbrales(um_act)
        org_cand = _org_con_umbrales(um_cand)
        cols = db.query(Colegiado).filter(Colegiado.id.in_(list(band))).all()
        for col in cols:
            if (col.condicion or "") == "vitalicio":
                continue
            try:
                deuda = calcular_deuda_total(db, col.id)
                r_cur = evaluar_habilidad(deuda, org_cur, col)
                r_cand = evaluar_habilidad(deuda, org_cand, col)
                c_cur = _cond_resultante(col.condicion, r_cur)
                c_cand = _cond_resultante(col.condicion, r_cand)
                if c_cur != c_cand:
                    flips.append({"matricula": col.codigo_matricula, "nombre": col.apellidos_nombres,
                                  "de": c_cur, "a": c_cand,
                                  "motivo": r_cand.motivo or ""})
            except Exception:
                db.rollback()

    n_inhab = sum(1 for f in flips if f["a"] == "inhabil")
    n_habil = sum(1 for f in flips if f["a"] == "habil")

    # ── Rama 'A REVISAR' (vitalicio_exige_cotizacion False→True) ──────────────
    a_revisar = []
    cot_act = val_act.get("vitalicio_exige_cotizacion", (None, None))[1]
    cot_cand = val_cand.get("vitalicio_exige_cotizacion", (None, None))[1]
    if (not cot_act) and cot_cand:
        rows = db.execute(text(
            "SELECT c.codigo_matricula, c.apellidos_nombres, COALESCE(SUM(d.balance),0) AS deuda "
            "FROM colegiados c JOIN debts d ON d.colegiado_id=c.id "
            "WHERE c.organization_id=:o AND lower(c.condicion)='vitalicio' "
            "AND d.status IN ('pending','partial') AND d.balance>0 "
            "GROUP BY c.id, c.codigo_matricula, c.apellidos_nombres ORDER BY deuda DESC"
        ), {"o": ORG_CCPL}).fetchall()
        a_revisar = [{"matricula": r.codigo_matricula, "nombre": r.apellidos_nombres,
                      "deuda": float(r.deuda), "motivo": "Vitalicio con deuda: no cumpliría cotización efectiva"}
                     for r in rows]

    # otros cambios (informativo, sin impacto directo en condición)
    otros = []
    for clave in ("perdida_fracc_consecutivas", "perdida_automatica",
                  "condiciones_exentas_generacion", "condiciones_sin_deuda_computable",
                  "vitalicio_declaracion", "vitalicio_anios", "vitalicio_exento_cuotas"):
        a = val_act.get(clave); c = val_cand.get(clave)
        if a and c and a[1] != c[1]:
            otros.append({"clave": clave,
                          "de": _display(clave, a[0], a[1]), "a": _display(clave, c[0], c[1])})

    total = db.query(Colegiado).filter(Colegiado.organization_id == ORG_CCPL).count()
    return JSONResponse({
        "preset": {"id": target.id, "nombre": target.nombre},
        "preset_activo": (activo.nombre if activo else None),
        "kpis": {"a_inhabil": n_inhab, "a_habil": n_habil,
                 "sin_cambio": total - n_inhab - n_habil,
                 "a_revisar": len(a_revisar), "total": total},
        "flips": flips,
        "a_revisar": a_revisar,
        "otros_cambios": otros,
        "banda_evaluada": len(band),
    })


# ── ACTIVAR PRESET (5b) — cambia SOLO el puntero activo; NO toca colegiados ────
def _activar_core(db, preset_id, motivo, actor_id, commit=True):
    """Núcleo de la activación (testeable con commit=False).
    Transacción solo sobre tablas de presets:
      1. valida el destino y que el motivo no esté vacío
      2. activo=FALSE al actual, activo=TRUE al destino (índice parcial → 1 solo)
      3. registra en preset_activaciones (quién/cuándo/motivo)
      4. actualiza activated_by/at del destino
    NO escribe en colegiados. Devuelve dict de resultado.
    """
    if not (motivo or "").strip():
        raise HTTPException(400, detail="El motivo de la activación es obligatorio.")

    target = db.execute(text(
        "SELECT id, nombre, activo FROM presets_condiciones WHERE id=:p AND organizacion_id=:o"
    ), {"p": preset_id, "o": ORG_CCPL}).first()
    if not target:
        raise HTTPException(404, detail="Preset no encontrado")
    if target.activo:
        raise HTTPException(400, detail="Ese preset ya está activo.")

    anterior = db.execute(text(
        "SELECT id FROM presets_condiciones WHERE organizacion_id=:o AND activo=TRUE LIMIT 1"
    ), {"o": ORG_CCPL}).first()
    anterior_id = anterior.id if anterior else None

    # 1) apaga el activo actual  2) enciende el destino
    db.execute(text("UPDATE presets_condiciones SET activo=FALSE WHERE organizacion_id=:o AND activo=TRUE"),
               {"o": ORG_CCPL})
    db.execute(text(
        "UPDATE presets_condiciones SET activo=TRUE, activated_by=:u, activated_at=NOW() WHERE id=:p"
    ), {"u": actor_id, "p": preset_id})

    # 3) log de trazabilidad
    db.execute(text(
        "INSERT INTO preset_activaciones (organizacion_id, preset_id, preset_anterior_id, activado_por, motivo) "
        "VALUES (:o, :p, :ant, :u, :m)"
    ), {"o": ORG_CCPL, "p": preset_id, "ant": anterior_id, "u": actor_id, "m": motivo.strip()})

    if commit:
        db.commit()
        try:
            from app.services.condiciones_service import invalidar_cache
            invalidar_cache(ORG_CCPL)   # los lectores toman el nuevo preset de aquí en adelante
        except Exception:
            pass

    return {"success": True, "preset_id": preset_id, "nombre": target.nombre,
            "preset_anterior_id": anterior_id}


@router.post("/activar")
async def activar_preset(
    datos: ActivarIn,
    db: Session = Depends(get_db),
    member: Member = Depends(require_admin),
):
    """Activa un preset: cambia el puntero activo y lo registra. NO re-evalúa el
    padrón (eso es un acto separado). Reversible reactivando el anterior."""
    actor_id = getattr(member, "user_id", None) or getattr(member, "id", None)
    res = _activar_core(db, datos.preset_id, datos.motivo, actor_id, commit=True)
    return JSONResponse(res)


# ── CREAR / EDITAR PRESET PROPIO (5c) ─────────────────────────────────────────
# Validación por clave: tipo + límites. Los 'set' solo admiten condiciones conocidas.
_CONDICIONES_VOCAB = ["vitalicio", "fallecido", "retirado", "baja", "suspendido", "habil", "inhabil"]
VALIDACION = {
    "inhab_cuotas_ordinarias":          {"tipo": "int", "min": 1, "max": 60},
    "inhab_extraordinaria":             {"tipo": "int", "min": 1, "max": 20},
    "inhab_multa":                      {"tipo": "int", "min": 1, "max": 20},
    "inhab_fracc_cuotas":               {"tipo": "int", "min": 1, "max": 60},
    "retiro_auto_meses":                {"tipo": "int", "min": 1, "max": 120},
    "perdida_fracc_consecutivas":       {"tipo": "int", "min": 1, "max": 60},
    "vitalicio_anios":                  {"tipo": "int", "min": 0, "max": 100},
    "perdida_automatica":               {"tipo": "bool"},
    "vitalicio_exige_cotizacion":       {"tipo": "bool"},
    "vitalicio_exento_cuotas":          {"tipo": "bool"},
    "vitalicio_declaracion":            {"tipo": "enum", "allowed": ["manual", "automatico"]},
    "condiciones_exentas_generacion":   {"tipo": "set", "allowed": _CONDICIONES_VOCAB},
    "condiciones_sin_deuda_computable": {"tipo": "set", "allowed": _CONDICIONES_VOCAB},
}


def _validar_valor(clave, valor):
    """Devuelve (tipo, valor_coercionado) o lanza HTTPException(400)."""
    spec = VALIDACION.get(clave)
    if not spec:
        raise HTTPException(400, detail=f"Clave desconocida: {clave}")
    tipo = spec["tipo"]
    if tipo == "int":
        try:
            v = int(valor)
        except (TypeError, ValueError):
            raise HTTPException(400, detail=f"{clave}: se esperaba un número entero.")
        if v < spec["min"] or v > spec["max"]:
            raise HTTPException(400, detail=f"{clave}: fuera de rango [{spec['min']}, {spec['max']}].")
        return tipo, v
    if tipo == "bool":
        if isinstance(valor, bool):
            return tipo, valor
        s = str(valor).strip().lower()
        if s in ("true", "1", "sí", "si"):
            return tipo, True
        if s in ("false", "0", "no"):
            return tipo, False
        raise HTTPException(400, detail=f"{clave}: se esperaba booleano.")
    if tipo == "enum":
        if valor not in spec["allowed"]:
            raise HTTPException(400, detail=f"{clave}: valor inválido (permitidos: {spec['allowed']}).")
        return tipo, valor
    if tipo == "set":
        if not isinstance(valor, (list, tuple)):
            raise HTTPException(400, detail=f"{clave}: se esperaba una lista.")
        vals = [str(x).strip().lower() for x in valor]
        malos = [x for x in vals if x not in spec["allowed"]]
        if malos:
            raise HTTPException(400, detail=f"{clave}: condiciones inválidas {malos}.")
        return tipo, sorted(set(vals))
    raise HTTPException(400, detail=f"{clave}: tipo no soportado.")


def _crear_core(db, nombre, actor_id, commit=True):
    from sqlalchemy.exc import IntegrityError
    nombre = (nombre or "").strip()
    if not nombre:
        raise HTTPException(400, detail="El nombre del preset es obligatorio.")
    activo = db.execute(text(
        "SELECT id FROM presets_condiciones WHERE organizacion_id=:o AND activo=TRUE LIMIT 1"
    ), {"o": ORG_CCPL}).first()
    if not activo:
        raise HTTPException(400, detail="No hay preset activo desde el cual clonar.")
    try:
        new_id = db.execute(text(
            "INSERT INTO presets_condiciones (organizacion_id, nombre, descripcion, es_sistema, "
            "base_estatuto, activo, created_by) "
            "VALUES (:o, :n, :d, FALSE, NULL, FALSE, :u) RETURNING id"
        ), {"o": ORG_CCPL, "n": nombre, "d": f"Preset propio (clonado de activo).", "u": actor_id}).scalar()
        db.execute(text(
            "INSERT INTO preset_valores (preset_id, clave, tipo, valor_numerico, valor_booleano, "
            "valor_texto, valor_json, articulo_ref) "
            "SELECT :new, clave, tipo, valor_numerico, valor_booleano, valor_texto, valor_json, articulo_ref "
            "FROM preset_valores WHERE preset_id=:src"
        ), {"new": new_id, "src": activo.id})
    except IntegrityError:
        db.rollback()
        raise HTTPException(400, detail="Ya existe un preset con ese nombre.")
    if commit:
        db.commit()
    n_val = db.execute(text("SELECT COUNT(*) FROM preset_valores WHERE preset_id=:p"), {"p": new_id}).scalar()
    return {"success": True, "preset_id": new_id, "nombre": nombre, "valores_clonados": n_val,
            "es_sistema": False, "activo": False}


def _editar_valor_core(db, preset_id, clave, valor, commit=True):
    preset = db.execute(text(
        "SELECT id, es_sistema FROM presets_condiciones WHERE id=:p AND organizacion_id=:o"
    ), {"p": preset_id, "o": ORG_CCPL}).first()
    if not preset:
        raise HTTPException(404, detail="Preset no encontrado")
    if preset.es_sistema:
        raise HTTPException(403, detail="Los presets del sistema son de solo lectura. Creá un preset propio.")
    tipo, v = _validar_valor(clave, valor)
    num = v if tipo == "int" else None
    boo = v if tipo == "bool" else None
    txt = v if tipo == "enum" else None
    vj = json.dumps(v) if tipo == "set" else None
    r = db.execute(text(
        "UPDATE preset_valores SET tipo=:t, valor_numerico=:num, valor_booleano=:boo, "
        "valor_texto=:txt, valor_json=CAST(:vj AS jsonb) WHERE preset_id=:p AND clave=:c"
    ), {"t": tipo, "num": num, "boo": boo, "txt": txt, "vj": vj, "p": preset_id, "c": clave})
    if r.rowcount == 0:
        db.execute(text(
            "INSERT INTO preset_valores (preset_id, clave, tipo, valor_numerico, valor_booleano, valor_texto, valor_json) "
            "VALUES (:p, :c, :t, :num, :boo, :txt, CAST(:vj AS jsonb))"
        ), {"p": preset_id, "c": clave, "t": tipo, "num": num, "boo": boo, "txt": txt, "vj": vj})
    if commit:
        db.commit()
    return {"success": True, "preset_id": preset_id, "clave": clave, "valor": v}


@router.post("/crear")
async def crear_preset(datos: CrearIn, db: Session = Depends(get_db), member: Member = Depends(require_admin)):
    """Crea un preset propio clonando el activo (es_sistema=FALSE, activo=FALSE)."""
    actor_id = getattr(member, "user_id", None) or getattr(member, "id", None)
    return JSONResponse(_crear_core(db, datos.nombre, actor_id, commit=True))


@router.post("/{preset_id}/valor")
async def editar_valor(preset_id: int, datos: EditarValorIn, db: Session = Depends(get_db),
                       member: Member = Depends(require_admin)):
    """Edita un valor de un preset PROPIO (rechaza los de sistema con 403)."""
    return JSONResponse(_editar_valor_core(db, preset_id, datos.clave, datos.valor, commit=True))


# ── RE-EVALUAR EL PADRÓN (5d) — el ÚNICO que mueve condiciones reales ──────────
# Job en background (registro en memoria de proceso). dry_run NO escribe; ejecutar
# exige doble confirmación. Reusa sincronizar_condicion (guards del motor intactos:
# vitalicio nunca auto-inhabilita, fracc protegido). NUNCA acoplado a activar.
import threading, uuid as _uuid

_REEVAL_JOBS = {}   # job_id -> {tipo, estado, total, hechos, kpis, cambios, error}


def _reevaluar_core(db, dry_run, job=None):
    """Itera el padrón con el preset ACTIVO. dry_run → rollback (no escribe);
    ejecutar → commit. Devuelve {kpis, cambios}. Guards del motor respetados."""
    from app.models import Colegiado
    from app.services.evaluar_habilidad import sincronizar_condicion
    org = {"id": ORG_CCPL, "config": {}}   # config vacío → umbrales salen del preset activo (db)
    cols = db.query(Colegiado).filter(Colegiado.organization_id == ORG_CCPL).all()
    total = len(cols)
    if job is not None:
        job["total"] = total
    cambios = []
    for i, col in enumerate(cols, 1):
        prev = col.condicion
        try:
            with db.begin_nested():                    # savepoint: aísla fallos por colegiado
                changed = sincronizar_condicion(db, col, org)
            if changed:
                cambios.append({"matricula": col.codigo_matricula, "nombre": col.apellidos_nombres,
                                "de": prev, "a": col.condicion})
        except Exception:
            pass
        if job is not None:
            job["hechos"] = i
    a_inhabil = sum(1 for c in cambios if c["a"] == "inhabil")
    a_habil = sum(1 for c in cambios if c["a"] == "habil")
    kpis = {"a_inhabil": a_inhabil, "a_habil": a_habil,
            "otros": len(cambios) - a_inhabil - a_habil,
            "sin_cambio": total - len(cambios), "total": total, "cambian": len(cambios)}
    if dry_run:
        db.rollback()      # descarta TODO — nada se persiste
    else:
        db.commit()
        try:
            from app.services.condiciones_service import invalidar_cache
            invalidar_cache(ORG_CCPL)
        except Exception:
            pass
    return {"kpis": kpis, "cambios": cambios}


def _run_reeval_job(job_id, dry_run, actor_id, actor_nombre):
    """Corre en un thread con su propia sesión (no comparte la del request)."""
    from app.database import SessionLocal
    job = _REEVAL_JOBS[job_id]
    db = SessionLocal()
    try:
        res = _reevaluar_core(db, dry_run, job)
        job["kpis"] = res["kpis"]
        job["cambios"] = res["cambios"][:500]   # cap para la respuesta
        job["estado"] = "completado"
        if not dry_run:
            # AUDIT (best-effort): quién / cuándo / cuántos cambió
            try:
                db.execute(text(
                    "INSERT INTO audit_log_finanzas (organization_id, accion, actor_id, actor_nombre, "
                    "entidad_tipo, entidad_id, detalle) "
                    "VALUES (:o, 'reevaluacion_padron', :aid, :an, 'preset_condiciones', :eid, CAST(:det AS jsonb))"
                ), {"o": ORG_CCPL, "aid": actor_id or 0, "an": actor_nombre,
                    "eid": None, "det": json.dumps(res["kpis"])})
                db.commit()
            except Exception:
                db.rollback()
    except Exception as e:
        job["estado"] = "error"; job["error"] = str(e)
        db.rollback()
    finally:
        db.close()


@router.post("/re-evaluar")
async def re_evaluar(datos: ReEvaluarIn, db: Session = Depends(get_db),
                     member: Member = Depends(require_admin)):
    """Inicia un job de re-evaluación. dry_run (default) NO escribe; ejecutar exige
    doble confirmación. Devuelve job_id; el progreso se consulta en /estado/{job_id}."""
    if not datos.dry_run:
        # EJECUTAR: doble confirmación obligatoria
        if datos.confirmacion.strip() != "RE-EVALUAR" or not datos.entiendo:
            raise HTTPException(400, detail="Ejecutar requiere escribir 'RE-EVALUAR' y marcar la casilla.")
    actor_id = getattr(member, "user_id", None) or getattr(member, "id", None)
    actor_nombre = (member.user.name if getattr(member, "user", None) else None) or getattr(member, "role", "admin")
    job_id = _uuid.uuid4().hex[:12]
    _REEVAL_JOBS[job_id] = {"tipo": ("dry_run" if datos.dry_run else "ejecutar"),
                            "estado": "corriendo", "total": 0, "hechos": 0,
                            "kpis": None, "cambios": [], "error": None}
    threading.Thread(target=_run_reeval_job, args=(job_id, datos.dry_run, actor_id, actor_nombre),
                     daemon=True).start()
    return JSONResponse({"job_id": job_id, "tipo": _REEVAL_JOBS[job_id]["tipo"], "estado": "corriendo"})


@router.get("/re-evaluar/estado/{job_id}")
async def re_evaluar_estado(job_id: str, member: Member = Depends(require_admin)):
    job = _REEVAL_JOBS.get(job_id)
    if not job:
        raise HTTPException(404, detail="Job no encontrado")
    return JSONResponse({"tipo": job["tipo"], "estado": job["estado"],
                         "total": job["total"], "hechos": job["hechos"],
                         "kpis": job["kpis"], "cambios": job["cambios"], "error": job["error"]})


@router.get("")
async def get_condiciones_ui(
    db: Session = Depends(get_db),
    member: Member = Depends(require_admin),
):
    """Datos para la sección 'Condiciones y Exoneraciones' (solo lectura)."""
    presets = db.execute(text(
        "SELECT id, nombre, es_sistema, activo, base_estatuto, "
        "       created_by, created_at, activated_by, activated_at "
        "FROM presets_condiciones WHERE organizacion_id = :o ORDER BY id"
    ), {"o": ORG_CCPL}).fetchall()
    if not presets:
        return JSONResponse({"presets": [], "activo": None, "grupos": [], "diff": [],
                             "aviso": "No hay presets cargados (falta el seed)."})

    activo = next((p for p in presets if p.activo), presets[0])
    estatuto = next((p for p in presets if (p.base_estatuto or "") == "RD 013-2020"), None)

    val_activo = _valores_de(db, activo.id)
    val_estatuto = _valores_de(db, estatuto.id) if estatuto else {}

    # armar grupos con color, en orden
    color_por_grupo = dict(GRUPOS)
    grupos_dict = {g: {"grupo": g, "color": c, "items": []} for g, c in GRUPOS}
    for clave, (grupo, etiqueta, art, orden) in sorted(CLAVES_META.items(), key=lambda x: x[1][3]):
        tv = val_activo.get(clave)
        if tv is None:
            continue
        tipo, val = tv
        difiere = bool(estatuto and clave in val_estatuto and val_estatuto[clave][1] != val)
        grupos_dict[grupo]["items"].append({
            "clave": clave,
            "etiqueta": etiqueta,
            "valor": _display(clave, tipo, val),
            "articulo_ref": art or None,
            "literal": LITERALES.get(art) or None,
            "difiere": difiere,
        })

    # diff vs Estatuto (solo las que difieren)
    diff = []
    if estatuto:
        for clave, (grupo, etiqueta, art, orden) in sorted(CLAVES_META.items(), key=lambda x: x[1][3]):
            a = val_activo.get(clave)
            e = val_estatuto.get(clave)
            if a and e and a[1] != e[1]:
                diff.append({
                    "clave": clave, "etiqueta": etiqueta, "articulo_ref": art or None,
                    "vigente": _display(clave, a[0], a[1]),
                    "estatuto": _display(clave, e[0], e[1]),
                })

    return JSONResponse({
        "presets": [{"id": p.id, "nombre": p.nombre, "es_sistema": p.es_sistema,
                     "activo": p.activo, "base_estatuto": p.base_estatuto} for p in presets],
        "activo": {"id": activo.id, "nombre": activo.nombre, "es_sistema": activo.es_sistema,
                   "base_estatuto": activo.base_estatuto,
                   "created_by": activo.created_by,
                   "created_at": (activo.created_at.isoformat() if activo.created_at else None),
                   "activated_by": activo.activated_by,
                   "activated_at": (activo.activated_at.isoformat() if activo.activated_at else None)},
        "grupos": [g for g in grupos_dict.values() if g["items"]],
        "diff": diff,
        "estatuto_ref": (estatuto.nombre if estatuto else None),
    })

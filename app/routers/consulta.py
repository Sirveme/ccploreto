# Agregar estos endpoints al router existente:
# app/routers/consulta.py  (donde ya está /habilidad y /habilidad/verificar)
#
# También agregar la ruta del perfil a este mismo router o a uno nuevo.
# Se muestra separado para claridad.

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import or_, func
from app.database import get_db
from app.models import Colegiado
from fastapi.templating import Jinja2Templates          # ← reemplaza la línea mala

templates = Jinja2Templates(directory="app/templates")  # ← agregar esta

router = APIRouter(prefix="/consulta", tags=["Público"])



# ─────────────────────────────────────────────────────────────
# NUEVO: Autocomplete — búsqueda en vivo
# GET /consulta/habilidad/buscar?q=flo
# Activa con DNI desde 5 dígitos, apellidos desde 3 caracteres
# Devuelve máx. 10 resultados (solo datos mínimos para la lista)
# ─────────────────────────────────────────────────────────────
# ── Agregar en app/routers/consulta.py ─────────────────────────────────
# Justo después del endpoint /habilidad/verificar que ya tienes
#
# IMPORTANTE: verifica que el nombre del campo sea correcto en tu modelo:
#   Colegiado.apellidos_nombres  ← así está en tu proyecto
#   Colegiado.dni
#   Colegiado.codigo_matricula
#   Colegiado.condicion
#   Colegiado.organization_id


@router.get("/habilidad/buscar")
async def buscar_colegiado_autocomplete(
    request: Request,
    q: str = "",
    db: Session = Depends(get_db)
):
    org = request.state.org
    if not org:
        return {"resultados": [], "total": 0}

    q = q.strip()
    es_dni = q.isdigit()

    if es_dni and len(q) < 5:
        return {"resultados": [], "total": 0, "tipo": "dni"}
    if not es_dni and len(q) < 3:
        return {"resultados": [], "total": 0, "tipo": "apellidos"}

    try:
        if es_dni:
            rows = (
                db.query(Colegiado)
                .filter(
                    Colegiado.organization_id == org["id"],
                    Colegiado.dni.ilike(f"{q}%")
                )
                .order_by(Colegiado.apellidos_nombres)
                .limit(10)
                .all()
            )
        else:
            rows = (
                db.query(Colegiado)
                .filter(
                    Colegiado.organization_id == org["id"],
                    Colegiado.apellidos_nombres.isnot(None),
                    Colegiado.apellidos_nombres.ilike(f"%{q}%")
                )
                .order_by(Colegiado.apellidos_nombres)
                .limit(10)
                .all()
            )
    except Exception as e:
        print(f"ERROR /buscar: {e}")
        return {"resultados": [], "total": 0, "error": str(e)}

    condicion_map = {
        "habil":      ("HÁBIL",    True),
        "vitalicio":  ("HÁBIL",    True),
        "inhabil":    ("NO HÁBIL", False),
        "suspendido": ("NO HÁBIL", False),
        "fallecido":  ("NO HÁBIL", False),
    }

    resultados = []
    for c in rows:
        cond = (c.condicion or "inhabil").lower()
        texto, es_habil = condicion_map.get(cond, ("NO HÁBIL", False))
        resultados.append({
            "codigo_matricula":  c.codigo_matricula,
            "apellidos_nombres": c.apellidos_nombres,
            "dni":               c.dni,
            "condicion_texto":   texto,
            "es_habil":          es_habil,
        })

    return {"resultados": resultados, "total": len(resultados)}


# ─────────────────────────────────────────────────────────────
# NUEVO: Perfil público del colegiado
# GET /colegiado/{matricula}
# Solo visible si condicion es HÁBIL o VITALICIO
# Solo si el colegiado autorizó publicar (campo: autoriza_perfil_publico)
# ─────────────────────────────────────────────────────────────
# Este endpoint va en un router separado, p.ej. app/routers/perfil_publico.py
# prefix="/colegiado"

from fastapi import APIRouter as _APIRouter
router_perfil = _APIRouter(prefix="/colegiado", tags=["Perfil Público"])


@router_perfil.get("/{matricula}", response_class=HTMLResponse)
async def perfil_colegiado_publico(
    matricula: str,
    request: Request,
    db: Session = Depends(get_db)
):
    org = request.state.org
    if not org:
        raise HTTPException(status_code=404)

    colegiado = db.query(Colegiado).filter(
        Colegiado.organization_id == org["id"],
        Colegiado.codigo_matricula == matricula
    ).first()

    # No existe
    if not colegiado:
        raise HTTPException(status_code=404, detail="Colegiado no encontrado")

    # Solo hábiles/vitalicios
    condicion = (colegiado.condicion or "").lower()
    if condicion not in ("habil", "vitalicio"):
        raise HTTPException(status_code=403, detail="Perfil no disponible")

    # Solo si autorizó publicación
    # Asegúrate de tener el campo: autoriza_perfil_publico BOOLEAN DEFAULT FALSE
    # Si aún no existe, comenta este bloque y créalo después
    if not getattr(colegiado, "autoriza_perfil_publico", False):
        raise HTTPException(status_code=403, detail="Perfil no autorizado para publicación")

    return templates.TemplateResponse("pages/perfil_colegiado.html", {
        "request": request,
        "org": org,
        "theme": request.state.theme,
        "c": colegiado,
        "condicion_texto": "HÁBIL",
    })
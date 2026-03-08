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
from app.templates import templates   # ajusta según tu proyecto

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
        return {"resultados": [], "total": 0, "tipo": "error"}

    q = q.strip()
    if not q:
        return {"resultados": [], "total": 0, "tipo": "vacio"}

    es_dni = q.isdigit()

    if es_dni and len(q) < 5:
        return {"resultados": [], "total": 0, "tipo": "dni", "mensaje": "Ingrese al menos 5 dígitos"}
    if not es_dni and len(q) < 3:
        return {"resultados": [], "total": 0, "tipo": "apellidos", "mensaje": "Ingrese al menos 3 letras"}

    try:
        if es_dni:
            rows = (
                db.query(Colegiado)
                .filter(
                    Colegiado.organization_id == org["id"],
                    Colegiado.dni.ilike(f"{q}%")          # empieza con los dígitos
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
                    Colegiado.apellidos_nombres.ilike(f"%{q}%")   # contiene el texto
                )
                .order_by(Colegiado.apellidos_nombres)
                .limit(10)
                .all()
            )
    except Exception as e:
        # Log para debug — quitar en producción
        print(f"ERROR buscar_colegiado: {e}")
        return {"resultados": [], "total": 0, "tipo": "error", "mensaje": str(e)}

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

    return {
        "resultados": resultados,
        "total": len(resultados),
        "tipo": "dni" if es_dni else "apellidos",
    }



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
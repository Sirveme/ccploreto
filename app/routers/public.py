"""
Rutas públicas - No requieren autenticación
"""
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import or_

from ..database import get_db
from ..models import Colegiado, Organization

router = APIRouter(prefix="/consulta", tags=["Público"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/habilidad", response_class=HTMLResponse)
async def pagina_consulta_habilidad(request: Request):
    """Página pública para consultar habilidad"""
    return templates.TemplateResponse("pages/consulta_habilidad.html", {
        "request": request,
        "theme": request.state.theme,
        "org": request.state.org
    })


@router.get("/habilidad/verificar")
async def verificar_habilidad(
    request: Request,
    q: str,
    db: Session = Depends(get_db)
):
    """
    API para verificar habilidad de un colegiado.
    Busca por DNI o por Código de Matrícula.
    """
    org = request.state.org
    if not org:
        raise HTTPException(status_code=400, detail="Organización no identificada")
    
    # Limpiar query
    q = q.strip()
    if len(q) < 3:
        raise HTTPException(status_code=400, detail="Ingrese al menos 3 caracteres")
    
    # Buscar por DNI o por Matrícula
    colegiado = db.query(Colegiado).filter(
        Colegiado.organization_id == org["id"],
        or_(
            Colegiado.dni == q,
            Colegiado.codigo_matricula == q
        )
    ).first()
    
    if not colegiado:
        return {
            "encontrado": False,
            "mensaje": "No se encontró ningún colegiado con ese DNI o matrícula"
        }
    
    # Determinar texto de condición
    condicion = colegiado.condicion.lower() if colegiado.condicion else "inhabil"
    
    # Mapeo de condiciones a texto visible
    condicion_map = {
        "habil": ("HÁBIL", True),
        "vitalicio": ("HÁBIL", True),  # Vitalicios son hábiles
        "inhabil": ("NO HÁBIL", False),
        "suspendido": ("NO HÁBIL", False),
        "fallecido": ("NO HÁBIL", False),
    }
    
    condicion_texto, es_habil = condicion_map.get(condicion, ("NO HÁBIL", False))
    
    # Respuesta exitosa
    return {
        "encontrado": True,
        "datos": {
            "codigo_matricula": colegiado.codigo_matricula,
            "apellidos_nombres": colegiado.apellidos_nombres,
            "condicion": condicion,  # Valor real para lógica en frontend
            "condicion_texto": condicion_texto,  # Texto visible
            "es_habil": es_habil,
            "fecha_actualizacion": colegiado.fecha_actualizacion_condicion.strftime("%d/%m/%Y") if colegiado.fecha_actualizacion_condicion else None
        }
    }


# LANDING PAGE COLEGIADO

# ============================================================
# AGREGAR ESTA RUTA EN app/routers/public.py
# ============================================================
# Asegúrate de tener estos imports al inicio del archivo:
# from app.models import Colegiado, Organization

# Router sin prefix para landing pages
router_landing = APIRouter(tags=["Landing"])

@router_landing.get("/colegiado/{matricula}", response_class=HTMLResponse)
async def landing_colegiado(
    matricula: str,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Landing page pública del colegiado
    Acceso: /colegiado/01-1234 o /colegiado/10201
    """
    
    # Buscar colegiado por matrícula
    colegiado = db.query(Colegiado).filter(
        Colegiado.codigo_matricula == matricula
    ).first()
    
    # Si no encuentra, intentar variantes (con/sin guión)
    if not colegiado:
        if '-' not in matricula and len(matricula) >= 3:
            # Probar: 10201 -> 10-201
            matricula_con_guion = f"{matricula[:2]}-{matricula[2:]}"
            colegiado = db.query(Colegiado).filter(
                Colegiado.codigo_matricula == matricula_con_guion
            ).first()
        elif '-' in matricula:
            # Probar: 10-201 -> 10201
            matricula_sin_guion = matricula.replace('-', '')
            colegiado = db.query(Colegiado).filter(
                Colegiado.codigo_matricula == matricula_sin_guion
            ).first()
    
    if not colegiado:
        raise HTTPException(status_code=404, detail="Colegiado no encontrado")
    
    # Obtener organización
    organization = db.query(Organization).filter(
        Organization.id == colegiado.organization_id
    ).first()
    
    return templates.TemplateResponse(
        "pages/landing_profesional.html",
        {
            "request": request,
            "colegiado": colegiado,
            "organization": organization,
            "es_habil": colegiado.es_habil
        }
    )

# ==============================================================
# Agregar RUTAS PARA TERMINOS Y POLITICAS DE PRIVACIDAD PÚBLICAS
# ==============================================================
# ============================================================
# AGREGAR a app/routers/public.py (o app/main.py)
# Rutas para páginas legales
# ============================================================

@router.get("/politica-privacidad/", response_class=HTMLResponse)
@router.get("/politica-privacidad", response_class=HTMLResponse)
async def politica_privacidad(request: Request):
    """Política de Privacidad - Ley 29733"""
    return templates.TemplateResponse("pages/politica_privacidad.html", {
        "request": request,
        "org": request.state.org if hasattr(request.state, 'org') else None,
    })


@router.get("/terminos/", response_class=HTMLResponse)
@router.get("/terminos", response_class=HTMLResponse)
async def terminos_condiciones(request: Request):
    """Términos y Condiciones de Uso"""
    return templates.TemplateResponse("pages/terminos.html", {
        "request": request,
        "org": request.state.org if hasattr(request.state, 'org') else None,
    })


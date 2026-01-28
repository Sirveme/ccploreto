from fastapi import APIRouter, Request, Depends, Query
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import or_
from app.database import get_db
from app.models import Member, User, Organization
from fastapi import HTTPException

router = APIRouter(tags=["directory"])
templates = Jinja2Templates(directory="app/templates")

@router.get("/directory/accountants")
async def public_directory(
    request: Request,
    q: str = Query(None, min_length=3), # Búsqueda
    db: Session = Depends(get_db)
):
    # Buscar Organización (Por slug o ID fijo para la demo)
    # Asumimos que el Colegio es la org con type='colegio_prof'
    # En producción filtrarías por subdominio o ID
    
    query = db.query(Member).join(User).join(Organization).filter(
        Organization.type == "colegio_prof",
        Member.is_active == True # <--- EL FILTRO DE ORO: Solo los que pagan
    )

    if q:
        query = query.filter(
            or_(
                User.name.ilike(f"%{q}%"),
                # CORRECCIÓN: Usar User.public_id en lugar de Member.public_id
                User.public_id.ilike(f"%{q}%") 
            )
        )

    # Limitar resultados para no mostrar toda la base
    results = query.limit(20).all()

    return templates.TemplateResponse("pages/public/directory.html", {
        "request": request,
        "results": results,
        "query": q
    })




@router.get("/cpc/{public_id}")
async def public_profile(
    request: Request,
    public_id: str,
    db: Session = Depends(get_db)
):
    # Buscar miembro por ID Público (Matrícula) dentro de Colegios Profesionales
    member = db.query(Member).join(User).join(Organization).filter(
        Organization.type == "colegio_prof",
        User.public_id == public_id
    ).first()

    if not member:
        # Podríamos mostrar una página de "No encontrado o No Habilitado"
        return templates.TemplateResponse("pages/errors/404_profile.html", {"request": request})

    # Calcular estado financiero real para mostrar la insignia
    # (Si está inactivo en BD, mostramos advertencia roja)
    
    return templates.TemplateResponse("pages/public/profile_cv.html", {
        "request": request,
        "profile": member,
        "theme": {"primary_color": member.organization.theme_color}
    })


# ... imports ...

# RUTA 1: PERFIL DE SERVICIOS (Estudio Contable / Independiente)
@router.get("/cpc/service/{public_id}")
async def profile_service(request: Request, public_id: str, db: Session = Depends(get_db)):
    member = db.query(Member).join(User).filter(User.public_id == public_id).first()
    if not member: return "No encontrado"
    
    return templates.TemplateResponse("pages/public/profile_service.html", {
        "request": request,
        "profile": member,
        # Datos simulados para la demo (luego vendrán de BD)
        "testimonials": [
            {"name": "Empresa SAC", "text": "Excelente gestión tributaria, nos ahorraron multas.", "stars": 5},
            {"name": "Jorge L.", "text": "Muy ordenados y puntuales con las declaraciones.", "stars": 5}
        ]
    })

# RUTA 2: PERFIL DE TALENTO (Curriculum Vitae)
@router.get("/cpc/cv/{public_id}")
async def profile_cv(request: Request, public_id: str, db: Session = Depends(get_db)):
    member = db.query(Member).join(User).filter(User.public_id == public_id).first()
    if not member: return "No encontrado"
    
    return templates.TemplateResponse("pages/public/profile_cv.html", {
        "request": request,
        "profile": member,
        # Datos simulados CV
        "skills": ["NIIF Completas", "Auditoría Financiera", "SAP", "Concar", "Inglés Intermedio"],
        "experience": [
            {"role": "Contador Senior", "company": "Mina de Oro SAC", "years": "2020 - Presente"},
            {"role": "Analista Tributario", "company": "Consultores Asociados", "years": "2018 - 2020"}
        ]
    })

# En app/routers/directory.py

@router.get("/cpc/{public_id}")
async def profile_dispatcher(public_id: str):
    # Por defecto, redirigir al perfil de Servicios (Web Vendedora)
    # Podrías cambiar esto a "/cpc/cv/" si prefieres el CV
    return RedirectResponse(url=f"/cpc/service/{public_id}")
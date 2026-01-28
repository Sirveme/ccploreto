from fastapi import APIRouter, Form, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, Member, Organization
from app.utils.security import verify_password, create_access_token
from app.routers.dashboard import get_current_member

templates = Jinja2Templates(directory="app/templates")

router = APIRouter(prefix="/auth", tags=["auth"])

# --- LOGIN ---
@router.post("/login")
async def login(
    request: Request,
    dni: str = Form(...), 
    code: str = Form(...), 
    db: Session = Depends(get_db)
):
    # 1. Obtener organización del contexto (Middleware)
    current_org = getattr(request.state, "org", None)
    
    # Validación de seguridad: Login debe ser siempre dentro de un dominio conocido
    if not current_org:
        # Si entran por IP directa o dominio no configurado
        return templates.TemplateResponse("pages/errors/403.html", {"request": request})

    # 2. Buscar Usuario Global
    user = db.query(User).filter(User.public_id == dni).first()
    
    # 3. Validar Credenciales
    if not user or not verify_password(code, user.access_code):
        # Retornamos HTML de error para que HTMX lo pinte en el formulario
        return JSONResponse(
            status_code=200, 
            content="""<div class="p-3 mb-4 text-sm text-red-200 bg-red-900/50 border border-red-500/50 rounded-lg text-center animate-pulse">Error: Credenciales incorrectas</div>""", 
            media_type="text/html"
        )
    
    # 4. Buscar Membresía EN ESTA ORGANIZACIÓN
    # Usamos current_org['id'] porque viene del Redis/Middleware como diccionario
    membership = db.query(Member).filter(
        Member.user_id == user.id,
        Member.organization_id == current_org['id'], 
        Member.is_active == True
    ).first()

    if not membership:
        return JSONResponse(
            status_code=200, 
            content=f"""<div class="p-3 text-sm text-yellow-200 bg-yellow-900/50 rounded text-center">No tiene acceso a {current_org['name']}.</div>""", 
            media_type="text/html"
        )

    # 5. Éxito: Crear Sesión
    return create_session_response(user, membership)

# --- SWITCH PROFILE ---
@router.get("/switch/{target_member_id}")
async def switch_profile(
    target_member_id: int, 
    current_member: Member = Depends(get_current_member),
    db: Session = Depends(get_db)
):
    target_membership = db.query(Member).filter(
        Member.id == target_member_id,
        Member.user_id == current_member.user_id,
        Member.is_active == True
    ).first()
    
    if not target_membership:
        raise HTTPException(status_code=403, detail="Acceso denegado")
    
    return create_session_response(target_membership.user, target_membership)

# --- HELPER: CREAR COOKIE Y REDIRIGIR ---
def create_session_response(user, member):
    # Generar Token
    access_token = create_access_token(data={
        "sub": str(member.id),
        "user_id": str(user.id),
        "name": user.name,
        "role": member.role,
        "org_name": member.organization.name
    })
    
    # Decidir destino
    target_url = "/dashboard"
    if member.role == "admin": target_url = "/admin"
    elif member.role in ["staff", "security"]: target_url = "/centinela"
    
    # ESTRATEGIA DE REDIRECCIÓN ROBUSTA (Fix para el JSON en pantalla)
    # Usamos RedirectResponse (303) que los navegadores siguen automáticamente.
    # Además, agregamos el header HX-Redirect para que HTMX fuerce el cambio de URL completo.
    
    response = RedirectResponse(url=target_url, status_code=status.HTTP_303_SEE_OTHER)
    response.headers["HX-Redirect"] = target_url # Esto fuerza a HTMX a navegar
    
    # Set Cookie
    response.set_cookie(
        key="access_token", 
        value=f"Bearer {access_token}", 
        httponly=True,
        max_age=2592000,
        samesite="lax",
        secure=True
    )
    return response
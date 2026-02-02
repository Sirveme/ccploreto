from fastapi import APIRouter, Request, Depends, Cookie, HTTPException, status
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Member, Bulletin, Organization, User
from jose import jwt, JWTError
from app.config import SECRET_KEY 
from app.utils.security import ALGORITHM
import os

router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory="app/templates")

# Dependencia para proteger rutas (CON FIX DE BUCLE)
def get_current_member(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("access_token")
    
    # Función de escape para romper el bucle
    def logout():
        response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
        response.delete_cookie("access_token")
        # Lanzamos la redirección limpiando la cookie
        raise HTTPException(status_code=302, headers={"Location": "/", "Set-Cookie": 'access_token=""; Max-Age=0; Path=/; HttpOnly'})

    if not token:
        raise HTTPException(status_code=302, headers={"Location": "/"}) # Sin token, solo ir al home

    try:
        scheme, token_value = token.split()
        if scheme.lower() != 'bearer': logout()
            
        payload = jwt.decode(token_value, SECRET_KEY, algorithms=[ALGORITHM])
        member_id = payload.get("sub")
        
        if member_id is None: logout()
        
        member = db.query(Member).filter(Member.id == member_id).first()
        if member is None: logout()
        
        return member

    except Exception as e:
        print(f"⚠️ Error de sesión: {e}")
        logout()

@router.get("/dashboard")
async def dashboard_home(request: Request, member: Member = Depends(get_current_member), db: Session = Depends(get_db)):
    current_theme = getattr(request.state, "theme", None)
    current_org = getattr(request.state, "org", {})
    org_config = current_org.get("config", {})

    # BUSCAR ÚLTIMO BOLETÍN ACTIVO
    latest_bulletin = db.query(Bulletin).filter(
        Bulletin.organization_id == member.organization_id
    ).order_by(Bulletin.created_at.desc()).first()

    # BUSCAR OTRAS MEMBRESÍAS
    my_profiles = db.query(Member).join(Organization).filter(
        Member.user_id == member.user_id,
        Member.is_active == True
    ).all()

    # ========================================
    # BUSCAR DATOS DEL COLEGIADO (CÓDIGO NUEVO)
    # ========================================
    from app.models import Colegiado
    
    user_input = member.user.public_id if member.user else None
    colegiado = None
    
    if user_input:
        user_input = user_input.strip().upper()
        
        if len(user_input) == 8 and user_input.isdigit():
            colegiado = db.query(Colegiado).filter(
                Colegiado.organization_id == member.organization_id,
                Colegiado.dni == user_input
            ).first()
        
        elif '-' in user_input:
            colegiado = db.query(Colegiado).filter(
                Colegiado.organization_id == member.organization_id,
                Colegiado.codigo_matricula == user_input
            ).first()
        
        elif user_input.startswith('10'):
            resto = user_input[2:]
            numero = ''
            letra = ''
            for i, char in enumerate(resto):
                if char.isdigit():
                    numero += char
                else:
                    letra = resto[i:].upper()
                    break
            
            numero_formateado = numero.zfill(4)
            matricula = f"10-{numero_formateado}{letra}"
            
            colegiado = db.query(Colegiado).filter(
                Colegiado.organization_id == member.organization_id,
                Colegiado.codigo_matricula == matricula
            ).first()
    
    if not colegiado:
        colegiado = db.query(Colegiado).filter(
            Colegiado.member_id == member.id
        ).first()
    
    if not colegiado and user_input and len(user_input) == 8 and user_input.isdigit():
        colegiado = db.query(Colegiado).filter(
            Colegiado.dni == user_input
        ).first()
    
    print(f"DEBUG COLEGIADO: input='{user_input}' -> encontrado={colegiado.codigo_matricula if colegiado else 'NINGUNO'}")
    # ========================================
    
    return templates.TemplateResponse("pages/dashboard_colegiado.html", {
        "request": request,
        "user": member,
        "colegiado": colegiado,
        "profiles": my_profiles,
        "theme": current_theme,
        "config": org_config,
        "vapid_public_key": os.getenv("VAPID_PUBLIC_KEY"),
        "latest_bulletin": latest_bulletin
    })
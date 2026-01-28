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

    # BUSCAR ÚLTIMO BOLETÍN ACTIVO
    latest_bulletin = db.query(Bulletin).filter(
        Bulletin.organization_id == member.organization_id
    ).order_by(Bulletin.created_at.desc()).first()

    # BUSCAR OTRAS MEMBRESÍAS (Multi-propiedad)
    my_profiles = db.query(Member).join(Organization).filter(
        Member.user_id == member.user_id,
        Member.is_active == True,
        Member.id != member.id # Excluir la actual
    ).all()
    
    return templates.TemplateResponse("pages/dashboard.html", {
        "request": request,
        "user": member,
        "profiles": my_profiles,
        "deuda": "S/ 150.00", # Esto deberías conectarlo a la tabla Debts real
        "vencimiento": "15 Ene 2024",
        "theme": current_theme,
        "vapid_public_key": os.getenv("VAPID_PUBLIC_KEY"),
        "latest_bulletin": latest_bulletin 
    })
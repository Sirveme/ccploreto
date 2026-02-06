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


# ============================================================
# AGREGAR AL FINAL DE app/routers/dashboard.py
# ============================================================

# ============================================================
# AGREGAR AL FINAL DE app/routers/dashboard.py
# ============================================================

# Helper para APIs (no redirige, lanza excepción)
async def get_current_member_api(request: Request, db: Session):
    """Versión para APIs - NO redirige"""
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="No autenticado")
    
    try:
        # IMPORTANTE: Quitar "Bearer " del token
        parts = token.split()
        if len(parts) == 2 and parts[0].lower() == 'bearer':
            token_value = parts[1]
        else:
            token_value = token
        
        payload = jwt.decode(token_value, SECRET_KEY, algorithms=[ALGORITHM])
        member_id = payload.get("sub")
        
        if not member_id:
            raise HTTPException(status_code=401, detail="Token inválido")
        
        member = db.query(Member).filter(Member.id == member_id).first()
        if not member:
            raise HTTPException(status_code=401, detail="Usuario no encontrado")
        
        return member
        
    except JWTError as e:
        print(f"⚠️ JWT Error: {e}")
        raise HTTPException(status_code=401, detail="Token inválido o expirado")
    except Exception as e:
        print(f"⚠️ Error auth: {e}")
        raise HTTPException(status_code=401, detail="Error de autenticación")





@router.get("/api/ai/stats")
async def get_ai_stats(request: Request, db: Session = Depends(get_db)):
    """Estadísticas de IA"""
    # No requiere auth estricta
    return {
        "consultasMes": 127,
        "costoMes": 3.50,
        "limiteMes": 10.00,
        "disponible": True
    }


@router.post("/api/ai/chat")
async def ai_chat(request: Request, db: Session = Depends(get_db)):
    """Chat con IA - Respuestas RAG"""
    try:
        body = await request.json()
        message = body.get("message", "").lower()
    except:
        message = ""
    
    # RAG básico
    if any(w in message for w in ["pago", "pagar", "cuota", "deuda"]):
        response = {
            "type": "steps",
            "category": "Pagos",
            "title": "¿Cómo pagar mis cuotas?",
            "description": "Tienes varias opciones:",
            "steps": [
                {"title": "Yape o Plin", "description": "Escanea el QR o transfiere al 987-654-321"},
                {"title": "Transferencia", "description": "BCP Cta. Cte. 123-456789-0-12"},
                {"title": "Presencial", "description": "Lunes a Viernes, 8am-6pm"}
            ],
            "tip": {"label": "Tip", "text": "Yape se valida en menos de 24 horas."},
            "source": {"name": "Tesorería CCPL", "verified": True}
        }
    elif any(w in message for w in ["certificado", "constancia", "habil"]):
        response = {
            "type": "article",
            "category": "Trámites",
            "title": "Constancia de Habilidad",
            "description": "Se genera automáticamente cuando estás al día en tus cuotas.",
            "icon": "certificate",
            "citation": {"text": "Todo colegiado deberá mantener su condición de hábil.", "source": "Estatuto Art. 45"},
            "tip": "Descárgala desde Dashboard → Certificados",
            "source": {"name": "Reglamento CCPL", "verified": True}
        }
    elif any(w in message for w in ["horario", "atencion", "oficina"]):
        response = {
            "type": "featured",
            "category": "Información",
            "title": "Horarios de Atención",
            "description": "Jr. Putumayo 123, Iquitos",
            "icon": "map-pin",
            "steps": [
                {"title": "Lunes a Viernes", "description": "8am-1pm y 3pm-6pm"},
                {"title": "Sábados", "description": "9am-12pm (urgentes)"}
            ],
            "tip": "La mayoría de trámites puedes hacerlos online."
        }
    elif any(w in message for w in ["descuento", "beneficio", "aniversario"]):
        response = {
            "type": "featured",
            "category": "🎉 Beneficio",
            "title": "60 Aniversario - 50% Descuento",
            "description": "Regulariza con 50% de descuento. ¡Hasta el 28 de febrero!",
            "icon": "confetti",
            "warning": "Solo cuotas anteriores al 2024.",
            "tip": {"label": "Cómo aprovecharlo", "text": "Se aplica automáticamente."},
            "source": {"name": "Junta Directiva", "verified": True}
        }
    else:
        response = {
            "type": "article",
            "category": "Asistente IA",
            "title": "¿En qué puedo ayudarte?",
            "description": "Pregúntame sobre pagos, certificados, trámites o cursos.",
            "icon": "robot",
            "related": [
                {"title": "¿Cómo pago?", "icon": "credit-card"},
                {"title": "Mi constancia", "icon": "certificate"},
                {"title": "Horarios", "icon": "clock"}
            ]
        }
    
    return {"response": response, "cost": 0.001}
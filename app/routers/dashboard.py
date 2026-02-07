from fastapi import APIRouter, Request, Depends, Cookie, HTTPException, status
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Member, Bulletin, Organization, User, Colegiado, Debt, Payment
from sqlalchemy import func
from jose import jwt, JWTError
from app.config import SECRET_KEY 
from app.utils.security import ALGORITHM
import os

router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory="app/templates")

SECRET_KEY = os.getenv("SECRET_KEY", "tu-clave-secreta")
ALGORITHM = "HS256"

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


def get_colegiado_silently(request: Request, db: Session):
    """
    Intenta obtener el colegiado de la sesión actual.
    Retorna None si no hay sesión o está expirada (NO lanza excepción).
    """
    try:
        token = request.cookies.get("access_token")
        if not token:
            return None
        
        # Parsear "Bearer token_value"
        parts = token.split()
        if len(parts) == 2 and parts[0].lower() == 'bearer':
            token_value = parts[1]
        else:
            token_value = token
        
        # Decodificar JWT
        payload = jwt.decode(token_value, SECRET_KEY, algorithms=[ALGORITHM])
        member_id = payload.get("sub")
        
        if not member_id:
            return None
        
        # Buscar member y colegiado
        member = db.query(Member).filter(Member.id == member_id).first()
        if not member:
            return None
        
        colegiado = db.query(Colegiado).filter(Colegiado.member_id == member.id).first()
        return colegiado
        
    except (JWTError, Exception) as e:
        # Silencioso - sesión inválida o expirada
        return None


def calcular_resumen_deuda(db: Session, colegiado_id: int) -> dict:
    """Calcula resumen de deuda del colegiado"""
    deuda_total = db.query(func.coalesce(func.sum(Debt.balance), 0)).filter(
        Debt.colegiado_id == colegiado_id,
        Debt.status.in_(['pending', 'partial'])
    ).scalar() or 0
    
    cantidad_cuotas = db.query(func.count(Debt.id)).filter(
        Debt.colegiado_id == colegiado_id,
        Debt.status.in_(['pending', 'partial'])
    ).scalar() or 0
    
    en_revision = db.query(func.coalesce(func.sum(Payment.amount), 0)).filter(
        Payment.colegiado_id == colegiado_id,
        Payment.status == 'review'
    ).scalar() or 0
    
    return {
        "total": float(deuda_total),
        "cantidad_cuotas": cantidad_cuotas,
        "en_revision": float(en_revision)
    }


"""
Endpoint: AI Chat con Acciones Inteligentes
============================================
Reemplazar la función ai_chat en dashboard.py

Detecta si hay sesión válida y retorna datos del colegiado
para pre-llenar formularios cuando sea posible.
"""


# ============================================
# ENDPOINT PRINCIPAL
# ============================================

@router.post("/api/ai/chat")
async def ai_chat(request: Request, db: Session = Depends(get_db)):
    """
    Chat con IA - Respuestas RAG con acciones inteligentes.
    Detecta sesión y pre-llena datos cuando es posible.
    """
    try:
        body = await request.json()
        message = body.get("message", "").lower()
    except:
        message = ""
    
    # ========================================
    # Intentar obtener datos del colegiado
    # ========================================
    colegiado = get_colegiado_silently(request, db)
    colegiado_data = None
    
    if colegiado:
        deuda = calcular_resumen_deuda(db, colegiado.id)
        colegiado_data = {
            "id": colegiado.id,
            "nombre": colegiado.apellidos_nombres,
            "dni": colegiado.dni,
            "matricula": colegiado.codigo_matricula,
            "condicion": colegiado.condicion,
            "deuda": deuda
        }
    
    # ========================================
    # ACCIONES: Detectar intención de acción
    # ========================================
    
    # ACCIÓN: Quiero pagar
    if any(phrase in message for phrase in [
        "quiero pagar", "deseo pagar", "voy a pagar", 
        "realizar pago", "hacer pago", "registrar pago",
        "pagar ahora", "pagar mi deuda", "pagar cuota"
    ]):
        if colegiado_data and colegiado_data["deuda"]["total"] > 0:
            # Con sesión y tiene deuda
            response = {
                "type": "article",
                "category": "Acción",
                "title": f"¡Listo! Abriendo formulario de pago...",
                "description": f"Tienes S/ {colegiado_data['deuda']['total']:.2f} pendiente en {colegiado_data['deuda']['cantidad_cuotas']} cuota(s).",
                "icon": "credit-card",
                "tip": {"label": "Recuerda", "text": "Ten a la mano tu voucher o captura del pago."}
            }
        elif colegiado_data and colegiado_data["deuda"]["total"] == 0:
            # Con sesión pero sin deuda
            response = {
                "type": "article",
                "category": "✅ Al día",
                "title": "¡No tienes deudas pendientes!",
                "description": "Estás al día con tus cuotas. ¡Gracias por tu puntualidad!",
                "icon": "check-circle",
            }
            return {"response": response, "action": None, "colegiado": colegiado_data, "cost": 0.001}
        else:
            # Sin sesión válida
            response = {
                "type": "article",
                "category": "Acción",
                "title": "Abriendo formulario de pago...",
                "description": "Ingresa tu DNI o matrícula para consultar tu deuda y registrar tu pago.",
                "icon": "credit-card",
                "tip": {"label": "Tip", "text": "Los pagos por Yape/Plin se validan en menos de 24 horas."}
            }
        
        return {
            "response": response, 
            "action": "open_pago_form", 
            "colegiado": colegiado_data,
            "cost": 0.001
        }
    
    # ACCIÓN: Ver mi deuda / estado de cuenta
    if any(phrase in message for phrase in [
        "ver mi deuda", "cuanto debo", "cuánto debo", 
        "mi deuda", "estado de cuenta", "mis cuotas",
        "que debo", "qué debo"
    ]):
        if colegiado_data:
            deuda = colegiado_data["deuda"]
            if deuda["total"] > 0:
                response = {
                    "type": "featured",
                    "category": "Estado de Cuenta",
                    "title": f"Deuda pendiente: S/ {deuda['total']:.2f}",
                    "description": f"Tienes {deuda['cantidad_cuotas']} cuota(s) pendiente(s).",
                    "icon": "receipt",
                    "tip": {"label": "Acción rápida", "text": "Di 'quiero pagar' para registrar tu pago."}
                }
                if deuda["en_revision"] > 0:
                    response["warning"] = f"Tienes S/ {deuda['en_revision']:.2f} en revisión."
            else:
                response = {
                    "type": "article",
                    "category": "✅ Al día",
                    "title": "¡Estás al día!",
                    "description": "No tienes cuotas pendientes. ¡Felicitaciones!",
                    "icon": "check-circle",
                }
        else:
            response = {
                "type": "article",
                "category": "Consulta",
                "title": "Consulta tu deuda",
                "description": "Abriendo el formulario para que ingreses tu DNI o matrícula.",
                "icon": "search",
            }
        
        return {
            "response": response, 
            "action": "open_estado_cuenta", 
            "colegiado": colegiado_data,
            "cost": 0.001
        }
    
    # ACCIÓN: Ver certificado / constancia
    if any(phrase in message for phrase in [
        "ver certificado", "descargar certificado", "mi certificado",
        "constancia", "obtener constancia", "descargar constancia",
        "certificado de habilidad", "estoy habil", "estoy hábil"
    ]):
        if colegiado_data:
            es_habil = colegiado_data["condicion"] in ["habil", "vitalicio", "Hábil", "Vitalicio"]
            if es_habil:
                response = {
                    "type": "article",
                    "category": "✅ Certificado",
                    "title": "Abriendo certificados...",
                    "description": "Estás HÁBIL. Puedes descargar tu constancia de habilidad.",
                    "icon": "certificate",
                }
                return {
                    "response": response, 
                    "action": "open_certificados", 
                    "colegiado": colegiado_data,
                    "cost": 0.001
                }
            else:
                response = {
                    "type": "article",
                    "category": "⚠️ Atención",
                    "title": "Actualmente estás INHÁBIL",
                    "description": f"Tienes S/ {colegiado_data['deuda']['total']:.2f} pendiente. Regulariza para obtener tu certificado.",
                    "icon": "alert-triangle",
                    "tip": {"label": "Siguiente paso", "text": "Di 'quiero pagar' para regularizarte."}
                }
                return {"response": response, "action": None, "colegiado": colegiado_data, "cost": 0.001}
        else:
            response = {
                "type": "article",
                "category": "Certificados",
                "title": "Consulta tu habilidad",
                "description": "Ingresa tu DNI o matrícula para verificar tu estado y descargar tu certificado.",
                "icon": "certificate",
            }
        
        return {
            "response": response, 
            "action": "open_consulta_habilidad", 
            "colegiado": colegiado_data,
            "cost": 0.001
        }
    
    # ACCIÓN: Ayuda / qué puedes hacer
    if any(phrase in message for phrase in [
        "ayuda", "que puedes hacer", "qué puedes hacer",
        "opciones", "comandos", "funciones"
    ]):
        response = {
            "type": "steps",
            "category": "Ayuda",
            "title": "¿Cómo puedo ayudarte?",
            "description": "Puedo realizar estas acciones por ti:",
            "steps": [
                {"title": "💳 'Quiero pagar'", "description": "Abre el formulario de pago directo"},
                {"title": "📊 'Ver mi deuda'", "description": "Consulta tu estado de cuenta"},
                {"title": "📜 'Mi certificado'", "description": "Descarga tu constancia de habilidad"},
                {"title": "🕐 'Horarios'", "description": "Info de atención en oficina"},
            ],
            "tip": {"label": "Tip", "text": "También puedes usar comandos de voz. ¡Solo habla!"}
        }
        return {"response": response, "action": None, "colegiado": colegiado_data, "cost": 0.001}
    
    # ========================================
    # RAG INFORMATIVO (sin acción, solo info)
    # ========================================
    
    # INFO: Cómo pagar (sin intención de pagar ahora)
    if any(w in message for w in ["como pago", "cómo pago", "formas de pago", "metodos de pago", "métodos de pago"]):
        response = {
            "type": "steps",
            "category": "Pagos",
            "title": "Formas de pago disponibles",
            "description": "Puedes pagar por cualquiera de estos medios:",
            "steps": [
                {"title": "Yape / Plin", "description": "Al número que aparece en el formulario de pago"},
                {"title": "Transferencia bancaria", "description": "A la cuenta BCP del colegio"},
                {"title": "Presencial", "description": "En oficinas, Lunes a Viernes 8am-6pm"}
            ],
            "tip": {"label": "¿Listo para pagar?", "text": "Di 'quiero pagar' y te abro el formulario."},
            "source": {"name": "Tesorería CCPL", "verified": True}
        }
        return {"response": response, "action": None, "colegiado": colegiado_data, "cost": 0.001}
    
    # INFO: Horarios
    if any(w in message for w in ["horario", "atencion", "atención", "oficina", "direccion", "dirección"]):
        response = {
            "type": "featured",
            "category": "Información",
            "title": "Horarios de Atención",
            "description": "Jr. Putumayo 484, Iquitos",
            "icon": "map-pin",
            "steps": [
                {"title": "Lunes a Viernes", "description": "8:00am - 1:00pm y 3:00pm - 6:00pm"},
                {"title": "Sábados", "description": "9:00am - 12:00pm (solo urgentes)"}
            ],
            "tip": "La mayoría de trámites puedes hacerlos online desde aquí."
        }
        return {"response": response, "action": None, "colegiado": colegiado_data, "cost": 0.001}
    
    # INFO: Beneficios / descuentos
    if any(w in message for w in ["descuento", "beneficio", "aniversario", "promocion", "promoción"]):
        response = {
            "type": "featured",
            "category": "🎉 Beneficio Vigente",
            "title": "60 Aniversario - 50% Descuento",
            "description": "Regulariza tus cuotas atrasadas con 50% de descuento. ¡Hasta el 28 de febrero!",
            "icon": "gift",
            "warning": "Aplica solo a cuotas anteriores al 2024.",
            "tip": {"label": "Aprovéchalo", "text": "El descuento se aplica automáticamente al pagar."},
            "source": {"name": "Junta Directiva CCPL", "verified": True}
        }
        return {"response": response, "action": None, "colegiado": colegiado_data, "cost": 0.001}
    
    # INFO: Requisitos para colegiarse
    if any(w in message for w in ["colegiar", "requisito", "inscripcion", "inscripción", "nuevo colegiado"]):
        response = {
            "type": "steps",
            "category": "Colegiatura",
            "title": "Requisitos para Colegiarse",
            "description": "Documentos necesarios para la colegiatura:",
            "steps": [
                {"title": "Título profesional", "description": "Original y copia legalizada"},
                {"title": "DNI", "description": "Copia simple"},
                {"title": "Fotos", "description": "2 fotos tamaño carnet fondo blanco"},
                {"title": "Pago", "description": "Derecho de colegiatura"}
            ],
            "tip": "Consulta montos actualizados en Secretaría."
        }
        return {"response": response, "action": None, "colegiado": colegiado_data, "cost": 0.001}
    
    # DEFAULT: Respuesta genérica
    response = {
        "type": "article",
        "category": "Asistente CCPL",
        "title": "¿En qué puedo ayudarte?",
        "description": "Soy el asistente virtual del CCPL. Puedo ayudarte con pagos, certificados, consultas y más.",
        "icon": "robot",
        "related": [
            {"title": "Quiero pagar", "icon": "credit-card"},
            {"title": "Ver mi deuda", "icon": "receipt"},
            {"title": "Mi certificado", "icon": "certificate"},
            {"title": "Horarios", "icon": "clock"}
        ]
    }
    
    return {"response": response, "action": None, "colegiado": colegiado_data, "cost": 0.001}

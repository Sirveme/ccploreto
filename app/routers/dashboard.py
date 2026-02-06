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

@router.get("/api/colegiado/mis-pagos")
async def get_mis_pagos(request: Request, db: Session = Depends(get_db)):
    """
    Endpoint para el Modal Mis Pagos
    Retorna resumen, historial y deudas del colegiado
    """
    # Obtener member autenticado
    member = await get_current_member(request, db)
    if not member:
        raise HTTPException(status_code=401, detail="No autenticado")
    
    # Por ahora retornar datos de demo
    # TODO: Conectar con tablas reales de pagos/deudas
    
    return {
        "resumen": {
            "deuda_total": 240.00,
            "total_pagado": 960.00,
            "en_revision": 80.00
        },
        "pagos": [
            {
                "id": 1,
                "fecha": "15/01/2025",
                "concepto": "Cuotas Oct-Dic 2024",
                "metodo": "Yape",
                "operacion": "OP-78451236",
                "monto": 240.00,
                "estado": "approved"
            },
            {
                "id": 2,
                "fecha": "05/02/2025",
                "concepto": "Cuota Enero 2025",
                "metodo": "Yape",
                "operacion": "OP-89562147",
                "monto": 80.00,
                "estado": "review"
            },
            {
                "id": 3,
                "fecha": "20/12/2024",
                "concepto": "Cuotas Jul-Sep 2024",
                "metodo": "Transferencia",
                "operacion": "TRF-456123",
                "monto": 240.00,
                "estado": "approved"
            },
            {
                "id": 4,
                "fecha": "15/09/2024",
                "concepto": "Cuotas Abr-Jun 2024",
                "metodo": "Efectivo",
                "operacion": None,
                "monto": 240.00,
                "estado": "approved"
            },
            {
                "id": 5,
                "fecha": "01/02/2025",
                "concepto": "Cuota Febrero 2025",
                "metodo": "Plin",
                "operacion": "PLN-123456",
                "monto": 80.00,
                "estado": "rejected"
            }
        ],
        "deudas": [
            {
                "id": 101,
                "concepto": "Cuota mensual",
                "periodo": "Febrero 2025",
                "vencimiento": "2025-02-28",
                "balance": 80.00
            },
            {
                "id": 102,
                "concepto": "Cuota mensual",
                "periodo": "Marzo 2025",
                "vencimiento": "2025-03-31",
                "balance": 80.00
            },
            {
                "id": 103,
                "concepto": "Cuota mensual",
                "periodo": "Abril 2025",
                "vencimiento": "2025-04-30",
                "balance": 80.00
            }
        ]
    }


# ============================================================
# ENDPOINTS DE IA (para el FAB chatbot)
# ============================================================

@router.get("/api/ai/stats")
async def get_ai_stats(request: Request):
    """
    Estadísticas de uso de IA para mostrar en el FAB
    Por ahora datos de demo
    """
    return {
        "consultasMes": 127,
        "costoMes": 3.50,
        "limiteMes": 10.00,
        "ahorroEstimado": 850.00,
        "disponible": True
    }


@router.post("/api/ai/chat")
async def ai_chat(request: Request, db: Session = Depends(get_db)):
    """
    Endpoint para el chat con IA
    Por ahora retorna respuestas pre-definidas (RAG básico)
    """
    try:
        body = await request.json()
        message = body.get("message", "").lower()
        model = body.get("model", "claude")
    except:
        message = ""
        model = "claude"
    
    # Respuestas RAG básicas
    if any(word in message for word in ["pago", "pagar", "cuota", "deuda"]):
        response = {
            "type": "steps",
            "category": "Pagos",
            "title": "¿Cómo pagar mis cuotas?",
            "description": "Tienes varias opciones para ponerte al día:",
            "steps": [
                {"title": "Yape o Plin", "description": "Escanea el QR o transfiere al 987-654-321"},
                {"title": "Transferencia Bancaria", "description": "BCP Cta. Cte. 123-456789-0-12"},
                {"title": "Presencial", "description": "En oficinas de Lunes a Viernes, 8am-6pm"}
            ],
            "tip": {"label": "Tip rápido", "text": "Los pagos por Yape se validan en menos de 24 horas."},
            "source": {"name": "Tesorería CCPL", "verified": True}
        }
    elif any(word in message for word in ["certificado", "constancia", "habil"]):
        response = {
            "type": "article",
            "category": "Trámites",
            "title": "Constancia de Habilidad",
            "description": "La constancia certifica que estás habilitado para ejercer. Se genera automáticamente cuando estás al día.",
            "icon": "certificate",
            "citation": {"text": "Todo colegiado deberá mantener su condición de hábil.", "source": "Estatuto Art. 45"},
            "tip": "Descárgala desde Dashboard → Certificados",
            "source": {"name": "Reglamento CCPL", "verified": True}
        }
    elif any(word in message for word in ["horario", "atencion", "oficina", "donde"]):
        response = {
            "type": "featured",
            "category": "Información",
            "title": "Horarios de Atención",
            "description": "Jr. Putumayo 123, Iquitos",
            "icon": "map-pin",
            "steps": [
                {"title": "Lunes a Viernes", "description": "8:00 AM - 1:00 PM y 3:00 PM - 6:00 PM"},
                {"title": "Sábados", "description": "9:00 AM - 12:00 PM (solo urgentes)"}
            ],
            "tip": "La mayoría de trámites puedes hacerlos desde esta plataforma."
        }
    elif any(word in message for word in ["descuento", "beneficio", "promocion", "aniversario"]):
        response = {
            "type": "featured",
            "category": "🎉 Beneficio Activo",
            "title": "60 Aniversario CCPL - 50% Descuento",
            "description": "Regulariza tu deuda con 50% de descuento en cuotas atrasadas. ¡Válido hasta el 28 de febrero!",
            "icon": "confetti",
            "warning": "Solo para cuotas generadas antes del 2024.",
            "tip": {"label": "¿Cómo aprovecharlo?", "text": "El descuento se aplica automáticamente."},
            "source": {"name": "Junta Directiva", "verified": True}
        }
    elif any(word in message for word in ["curso", "capacitacion", "seminario"]):
        response = {
            "type": "featured",
            "category": "Capacitación",
            "title": "Próximos Cursos",
            "description": "Mantente actualizado con nuestra oferta de capacitación.",
            "icon": "graduation-cap",
            "steps": [
                {"title": "Actualización NIIF 2025", "description": "20 horas. Inicio: 15 de febrero"},
                {"title": "Cierre Contable 2024", "description": "Taller práctico. 10 de febrero"}
            ],
            "tip": {"label": "Beneficio", "text": "Colegiados hábiles tienen 30% de descuento."}
        }
    else:
        response = {
            "type": "article",
            "category": "Asistente IA",
            "title": "¿En qué puedo ayudarte?",
            "description": "Puedo asistirte con pagos, certificados, trámites, cursos y más. Intenta ser específico.",
            "icon": "robot",
            "related": [
                {"title": "¿Cómo pago mis cuotas?", "icon": "credit-card"},
                {"title": "Obtener constancia", "icon": "certificate"},
                {"title": "Horarios de atención", "icon": "clock"}
            ],
            "tip": "También puedes navegar por el Dashboard."
        }
    
    return {
        "response": response,
        "model": model,
        "cost": 0.001  # Costo simulado
    }
# app/routers/api.py
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, Body, Request
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Device, Member, AccessLog, MemberRole, PanicLog, Debt, Payment, Bulletin, AuditLog, User
from app.routers.dashboard import get_current_member
from app.core.actions import get_allowed_actions, get_action_ui
from openai import OpenAI
from datetime import datetime, timedelta, timezone
from pywebpush import webpush
import os
import json

from sqlalchemy import func

from app.routers.ws import manager # Para avisar al websocket

load_dotenv(override=True)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

router = APIRouter(prefix="/api", tags=["api"])

@router.post("/push/subscribe")
async def subscribe_push(
    request: Request, # <-- Necesario para leer headers
    payload: dict = Body(...), # Recibimos todo el objeto JSON
    member: Member = Depends(get_current_member),
    db: Session = Depends(get_db)
):
    # Estructura recibida: { subscription: {...}, details: {...} }
    sub_data = payload.get("subscription", {})
    details = payload.get("details", {})
    
    endpoint = sub_data.get("endpoint")
    if not endpoint:
        return {"status": "error", "msg": "Endpoint no válido"}

    # Buscar si existe
    device = db.query(Device).filter(Device.push_endpoint == endpoint).first()
    
    # Datos técnicos
    keys = sub_data.get("keys", {})
    user_agent_raw = request.headers.get('user-agent', 'Desconocido')
    
    if not device:
        # CREAR NUEVO
        new_device = Device(
            member_id=member.id,
            push_endpoint=endpoint,
            push_p256dh=keys.get("p256dh"),
            push_auth=keys.get("auth"),
            
            # Huella Digital
            user_agent=user_agent_raw,
            platform=details.get("platform"),
            timezone=details.get("timezone"),
            is_pwa=details.get("is_pwa", False)
        )
        db.add(new_device)
        msg = "Dispositivo registrado con éxito"
    else:
        # ACTUALIZAR EXISTENTE (Importante por si cambió de PWA a Browser o actualizó OS)
        device.push_p256dh = keys.get("p256dh")
        device.push_auth = keys.get("auth")
        device.user_agent = user_agent_raw
        device.is_pwa = details.get("is_pwa", False)
        device.last_seen = func.now() # Actualizamos la última vez visto
        msg = "Datos de dispositivo actualizados"
        
    db.commit()
    return {"status": "success", "msg": msg}


@router.post("/proximity/check-in")
async def check_in_proximity(
    request: Request,
    member: Member = Depends(get_current_member),
    db: Session = Depends(get_db)
):
    # Crear Log de Acceso
    new_log = AccessLog(
        organization_id=member.organization_id,
        member_id=member.id,
        direction="IN",
        method="APP_CHECKIN", # Marcamos que fue voluntario desde la App
        target_unit=member.unit_info,
        visitor_name="Residente (Confirmado)"
    )
    db.add(new_log)
    db.commit()

    # Avisar al Guardia (Monitor Centinela) vía WebSocket
    # Usamos un tipo nuevo "INFO_ACCESS" para que sea verde, no rojo
    # Avisar al Guardia (Monitor Centinela) vía WebSocket
    await manager.broadcast({
        "type": "INFO_ACCESS", 
        "user": member.user.name, # <--- CAMBIO AQUÍ (Agregamos .user)
        "user_id": member.user.id, # <--- Asegúrate de usar member.user.id aquí también
        "msg": f"📍 {member.user.name} ha marcado su ingreso (Check-in).", # <--- Y AQUÍ
        "unit": member.unit_info,
        "method": "WiFi/App"
    })
    
    return {"status": "ok", "msg": "Ingreso registrado correctamente"}


#================================================================
# CEREBRO IA: PROCESAR COMANDO DE VOZ
# LA CENTRAL NEURAL (Integración OpenAI) 🧠✨
#================================================================
# ... imports (Asegúrate de tener Bulletin, Device, webpush, etc.) ...
from app.models import Bulletin, Device, Payment
from pywebpush import webpush
import json

@router.post("/brain/process-command")
async def process_voice_command(
    request: Request, # Para obtener la IP
    payload: dict = Body(...),
    member: Member = Depends(get_current_member),
    db: Session = Depends(get_db)
):
    command_text = payload.get("command")
    print(f"🧠 Cerebro: '{command_text}' ({member.role})")

    # 1. Obtener Whitelist (Acciones permitidas para este usuario)
    allowed_actions = get_allowed_actions(member.role, member.organization.type)
    
    # 2. Generar descripción para el Prompt
    if not allowed_actions:
        return {"status": "ok", "action": {"type": "speak", "message": "No tienes permisos para ejecutar acciones."}}

    actions_desc = "\n".join([f"- {key}: {val['desc']}" for key, val in allowed_actions.items()])
    
    # 3. Prompt del Sistema
    system_prompt = f"""
    Eres el SO de {member.organization.name}. Usuario: {member.user.name} ({member.role}).
    
    ACCIONES PERMITIDAS:
    {actions_desc}
    
    INSTRUCCIONES:
    1. Analiza la intención del usuario.
    2. Selecciona el 'action_id' de la lista anterior.
    3. Extrae datos relevantes en 'data' (ej: amount, title, content).
    4. Si no entiendes o la acción no está en la lista -> "action_id": "UNKNOWN"
    
    Responde SOLO JSON: {{ "action_id": "...", "data": {{ ... }} }}
    """

    final_action = None
    audit_status = "ERROR"

    try:
        # Llamada a OpenAI
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": command_text}
            ],
            temperature=0.0,
            response_format={"type": "json_object"}
        )
        
        ai_resp = json.loads(completion.choices[0].message.content)
        action_id = ai_resp.get("action_id")
        
        # 4. Validación y Construcción de Respuesta UI
        if action_id == "UNKNOWN" or action_id not in allowed_actions:
            final_action = {"type": "speak", "message": "No entendí o no tienes permiso."}
            audit_status = "DENIED"
        else:
            # Recuperar configuración visual estática
            ui_config = get_action_ui(action_id).copy()
            
            # Mezclar con datos dinámicos de la IA
            ui_config["payload"] = {
                "data": ai_resp.get("data", {}),
                "submit": ui_config.get("submit", False)
            }
            
            # Mensaje de voz por defecto si no existe
            if "message" not in ui_config:
                ui_config["message"] = "Procesando orden."
                
            final_action = ui_config
            audit_status = "SUCCESS"

    except Exception as e:
        print(f"❌ Error Brain: {e}")
        final_action = {"type": "speak", "message": "Error de conexión cerebral."}
        audit_status = "ERROR_TECH"

    # 5. AUDITORÍA (Guardar en Base de Datos)
    try:
        log = AuditLog(
            organization_id=member.organization_id,
            user_id=member.user_id,
            action_type="VOICE_COMMAND",
            command_text=command_text,
            ai_response=final_action, # Guardamos lo que se ejecutó
            status=audit_status,
            ip_address=request.client.host
        )
        db.add(log)
        db.commit()
    except Exception as e:
        print(f"⚠️ Fallo al auditar: {e}")

    return {"status": "ok", "action": final_action}

# --- PROMPTS ESPECIALIZADOS ---

def get_admin_prompt(name):
    return f"""
    Eres el asistente ejecutivo de {name}.
    Tu objetivo: Ejecutar acciones administrativas RÁPIDAS.
    
    ACCIONES:
    1. COMUNICADOS:
       - Si dice "Redacta..." o "Prepara...": Llena el form pero NO envía. ("submit": false)
       - Si dice "Envía..." o "Comunica...": Llena el form Y LO ENVÍA. ("submit": true)
       JSON: {{ "type": "fill_form", "target": "form-boletin", "payload": {{ "data": {{ "title": "...", "content": "...", "priority": "info" }}, "submit": true }}, "message": "Enviando comunicado." }}

    2. FINANZAS:
       - "Generar cuotas": {{ "type": "click", "target": "btn-generar-cuotas", "message": "Generando cobros." }}
    """

def get_security_prompt(name):
    return f"""
    Eres el asistente de seguridad {name}.
    Tu prioridad: Velocidad y Registro.
    
    ACCIONES:
    1. REGISTRO VISITA/INGRESO:
       - Extrae el nombre y la unidad.
       - JSON: {{ "type": "api_call", "endpoint": "/centinela/log", "data": {{ "tipo": "VISITA", "detalle": "NOMBRE_DETECTADO", "unidad": "UNIDAD_DETECTADA" }}, "message": "Visita registrada." }}
       
    2. ALERTA ROJA:
       - JSON: {{ "type": "click", "target": "btn-panico-centinela", "message": "Activando alerta." }}
    """

def get_neighbor_prompt(name):
    return f"""
    Eres el asistente del vecino {name}.
    ACCIONES:
    1. PAGOS: {{ "type": "open_modal", "target": "modal-payment", "message": "Abriendo pagos." }}
    2. PÁNICO: {{ "type": "click", "target": "btn-panico", "message": "Alerta activada." }}
    """
    

#================================================================
#Endpoint: RESUMEN DE SEGURIDAD (Briefing IA)
# La Central Neural (Integración OpenAI) 🧠✨
#================================================================
@router.get("/brain/briefing")
async def get_security_briefing(
    db: Session = Depends(get_db), 
    member: Member = Depends(get_current_member)
):
    # 1. Obtener eventos recientes (últimas 12h) usando la forma moderna
    since = datetime.now(timezone.utc) - timedelta(hours=12)
    
    panics = db.query(PanicLog).filter(
        PanicLog.organization_id == member.organization_id,
        PanicLog.created_at >= since
    ).all()
    
    access = db.query(AccessLog).filter(
        AccessLog.organization_id == member.organization_id,
        AccessLog.created_at >= since,
        AccessLog.method.in_(["MANUAL", "MANUAL_GUARDIA", "APP_CHECKIN"])
    ).order_by(AccessLog.created_at.desc()).limit(10).all()

    # 2. Si no hay nada, responder rápido
    if not panics and not access:
        return {"status": "ok", "text": "Sin novedades en el turno. Todo tranquilo."}

    # 3. Preparar datos para GPT
    data_text = f"ALERTAS ROJAS: {len(panics)}. "
    if panics:
        data_text += "Última alerta de pánico hace poco. "
        
    data_text += f"INGRESOS RECIENTES ({len(access)}): "
    for a in access:
        # Convertir a hora local simple para el texto (aprox)
        # Nota: En producción, idealmente se ajusta al timezone de la org
        hora = a.created_at.strftime("%H:%M")
        data_text += f"- {a.visitor_name} a las {hora}. "

    # 4. Consultar a OpenAI
    try:
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Eres un jefe de seguridad. Resume estos eventos en 2 frases cortas y formales para ser leídas por radio al guardia."},
                {"role": "user", "content": data_text}
            ],
            max_tokens=100
        )
        summary = completion.choices[0].message.content
        return {"status": "ok", "text": summary}
        
    except Exception as e:
        print(f"Error IA: {e}")
        return {"status": "ok", "text": f"Resumen manual: {len(panics)} alertas y {len(access)} ingresos recientes."}
    

@router.post("/health/report")
async def report_health(
    payload: dict = Body(...),
    member: Member = Depends(get_current_member),
    db: Session = Depends(get_db)
):
    # payload = { online: true, permission: 'granted', ... }
    
    # 1. Buscar el dispositivo actual del usuario (basado en user_agent aproximado o sesión)
    # Por simplicidad, actualizamos el último dispositivo activo o todos los de este usuario
    # Idealmente, el frontend debería mandar un device_id si lo tuviera guardado.
    
    devices = db.query(Device).filter(Device.member_id == member.id).all()
    
    status_perm = payload.get("permission", "unknown")
    
    # Actualizamos el estado de permiso en la BD
    for dev in devices:
        dev.permission_status = status_perm
        dev.last_seen = func.now()
        dev.is_active = (status_perm == 'granted')
    
    db.commit()
    
    return {"status": "received"}
import json
import os
from fastapi import APIRouter, Request, Depends, Form, BackgroundTasks
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from app.database import get_db, SessionLocal
from app.models import Member, Bulletin, Device # Importamos modelos nuevos
from app.routers.dashboard import get_current_member
from app.routers.ws import manager # Para avisar al websocket
from pywebpush import webpush, WebPushException

router = APIRouter(tags=["admin"])
templates = Jinja2Templates(directory="app/templates")

from app.models import Member, Bulletin, Device, Organization # <--- Agrega Organization

@router.get("/admin")
async def admin_home(request: Request, member: Member = Depends(get_current_member), db: Session = Depends(get_db)):
    if member.role != "admin":
        return templates.TemplateResponse("pages/errors/403.html", {"request": request})
    
    current_theme = getattr(request.state, "theme", None)
    
    # 1. LOGICA DE SWITCHER: Buscar otros perfiles
    my_profiles = db.query(Member).join(Organization).filter(
        Member.user_id == member.user_id,
        Member.is_active == True
    ).all()

    # ... (lógica de estadísticas existente) ...
    total_members = db.query(Member).filter(Member.organization_id == member.organization_id).count()
    recent_bulletins = db.query(Bulletin).filter(Bulletin.organization_id == member.organization_id).order_by(Bulletin.created_at.desc()).limit(5).all()

    return templates.TemplateResponse("pages/admin/home_admin.html", {
        "request": request,
        "user": member,
        "profiles": my_profiles, # <--- ENVIAR ESTO
        "theme": current_theme,
        "stats": {
            "vecinos": total_members,
            "morosidad": "15%",
            "caja": "S/ 12,400"
        },
        "bulletins": recent_bulletins
    })

@router.post("/admin/bulletin/create")
async def create_bulletin(
    background_tasks: BackgroundTasks,
    title: str = Form(...),
    content: str = Form(...),
    priority: str = Form(...),
    db: Session = Depends(get_db),
    admin: Member = Depends(get_current_member)
):
    # 1. Guardar en BD (Igual que antes)
    new_bulletin = Bulletin(
        organization_id=admin.organization_id,
        author_id=admin.id,
        title=title,
        content=content,
        priority=priority,
        target_criteria={"all": True}
    )
    db.add(new_bulletin)
    db.commit()
    
    # ---------------------------------------------------------
    # 2. NUEVO: AVISO EN TIEMPO REAL (WebSocket)
    # Esto hace que aparezca el "Globo" en la pantalla de Juan al instante
    await manager.broadcast({
        "type": "BULLETIN",
        "title": title,
        "body": content, # Resumen
        "priority": priority,
        "org_id": admin.organization_id # Para filtrar en el futuro si hay varios
    })
    # ---------------------------------------------------------

    # 3. Calcular destinatarios (Igual que antes)
    total_targets = db.query(Device).join(Member).filter(
        Member.organization_id == admin.organization_id,
        Device.is_active == True
    ).count()

    # 4. Encolar Push (Background)
    background_tasks.add_task(
        send_bulletin_push_background, 
        f"📢 {title}", 
        content[:100], 
        admin.organization_id
    )

    # 5. Respuesta Visual (Igual que antes)
    color = "blue"
    if priority == 'alert': color = "red"
    elif priority == 'warning': color = "yellow"

    return HTMLResponse(content=f"""
    <div class="p-4 mb-3 bg-slate-800 rounded-lg border-l-4 border-{color}-500 fade-me-in shadow-md">
        <div class="flex justify-between items-center">
            <h3 class="font-bold text-white">{title}</h3>
            <span class="text-[10px] text-slate-400 bg-black/30 px-2 py-1 rounded flex items-center gap-1">
                <i class="ph ph-check text-green-500"></i> Enviando a {total_targets}...
            </span>
        </div>
        <p class="text-sm text-slate-300 mt-2">{content}</p>
        <div class="mt-2 text-[10px] text-slate-500 text-right">Hace un instante</div>
    </div>
    """)

def getColor(priority):
    if priority == 'alert': return 'red'
    if priority == 'warning': return 'yellow'
    return 'blue'


#==================================================================
# VERSIÓN CON TAREAS EN SEGUNDO PLANO (BackgroundTasks)
#==================================================================

# 1. Extraer la lógica de envío a una función independiente
def send_bulletin_push_background(title: str, body: str, org_id: int):
    # 1. CREAR NUEVA SESIÓN (Vital para background tasks)
    db = SessionLocal() 
    
    try:
        print(f"🔄 Background: Iniciando envío Push...")
        
        # Obtener credenciales
        private_key = os.getenv("VAPID_PRIVATE_KEY")
        email = os.getenv("VAPID_CLAIMS_EMAIL")
        
        if not private_key:
            print("❌ Background Error: Falta VAPID_PRIVATE_KEY")
            return

        # Buscar dispositivos
        devices = db.query(Device).join(Member).filter(
            Member.organization_id == org_id,
            Device.is_active == True
        ).all()
        
        count = 0
        for dev in devices:
            try:
                webpush(
                    subscription_info={
                        "endpoint": dev.push_endpoint,
                        "keys": {"p256dh": dev.push_p256dh, "auth": dev.push_auth}
                    },
                    data=json.dumps({
                        "title": title,
                        "body": body,
                        "url": "/dashboard",
                        "icon": "/static/images/icon-192.png"
                    }),
                    vapid_private_key=private_key,
                    vapid_claims={"sub": email},
                    ttl=60
                )
                count += 1
            except WebPushException as ex:
                if ex.response and ex.response.status_code == 410:
                    dev.is_active = False # Marcar inactivo
                    db.commit() # Guardar cambio de estado
            except Exception:
                pass 
                
        print(f"✅ Background: Push enviado a {count} dispositivos.")
        
    except Exception as e:
        print(f"❌ Background Error General: {e}")
    finally:
        db.close() # CERRAR LA SESIÓN MANUALMENTE

# 2. Modificar el endpoint para usar BackgroundTasks
# --- ENDPOINT CREAR BOLETÍN ---
@router.post("/admin/bulletin/create")
async def create_bulletin(
    background_tasks: BackgroundTasks, # <--- Inyección de tareas
    title: str = Form(...),
    content: str = Form(...),
    priority: str = Form(...),
    db: Session = Depends(get_db), # Sesión del Request (corta vida)
    admin: Member = Depends(get_current_member)
):
    # 1. Guardar en Base de Datos (Usando sesión del request)
    new_bulletin = Bulletin(
        organization_id=admin.organization_id,
        author_id=admin.id,
        title=title,
        content=content,
        priority=priority,
        target_criteria={"all": True}
    )
    db.add(new_bulletin)
    db.commit()
    
    # 2. Calcular destinatarios (Solo para mostrar el número al Admin)
    total_targets = db.query(Device).join(Member).filter(
        Member.organization_id == admin.organization_id,
        Device.is_active == True
    ).count()

    # 3. ENCOLAR LA TAREA 
    # Pasamos datos primitivos (strings/ints), NO pasamos la sesión 'db'
    background_tasks.add_task(
        send_bulletin_push_background, 
        f"📢 {title}", 
        content[:100], 
        admin.organization_id
    )

    # 4. RESPUESTA INMEDIATA
    color = "blue"
    if priority == 'alert': color = "red"
    elif priority == 'warning': color = "yellow"

    # Nota: Usamos "Hace un instante" porque acaba de ocurrir
    return HTMLResponse(content=f"""
    <div class="p-4 mb-3 bg-slate-800 rounded-lg border-l-4 border-{color}-500 fade-me-in shadow-md">
        <div class="flex justify-between items-center">
            <h3 class="font-bold text-white">{title}</h3>
            <span class="text-[10px] text-slate-400 bg-black/30 px-2 py-1 rounded flex items-center gap-1">
                <i class="ph ph-check text-green-500"></i> Enviando a {total_targets}...
            </span>
        </div>
        <p class="text-sm text-slate-300 mt-2 whitespace-pre-wrap">{content}</p>
        <div class="mt-2 text-[10px] text-slate-500 text-right">Hace un instante</div>
    </div>
    """)


#==================================================================
# API: OBTENER ÚLTIMO BOLETÍN (Para el Dashboard)
#==================================================================

@router.get("/api/bulletins/latest")
async def get_latest_bulletin(db: Session = Depends(get_db), member: Member = Depends(get_current_member)):
    # Buscar el último boletín de su organización
    bulletin = db.query(Bulletin).filter(
        Bulletin.organization_id == member.organization_id
    ).order_by(Bulletin.created_at.desc()).first()
    
    if not bulletin:
        return {"status": "empty"}
        
    return {
        "status": "ok",
        "title": bulletin.title,
        "content": bulletin.content,
        "priority": bulletin.priority,
        "date": bulletin.created_at.isoformat()
    }
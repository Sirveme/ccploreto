import json
import os
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.utils.ws_manager import manager
from app.models import Device, Member
from pywebpush import webpush, WebPushException

router = APIRouter(tags=["websockets"])

# --- FUNCIÓN DE ENVÍO PUSH ---
def trigger_push_notifications(db: Session, title: str, body: str):
    """
    Busca todos los dispositivos activos y les envía la alerta Push.
    """
    devices = db.query(Device).filter(Device.is_active == True).all()
    
    # Leer credenciales del .env / Railway Variables
    private_key = os.getenv("VAPID_PRIVATE_KEY")
    email = os.getenv("VAPID_CLAIMS_EMAIL")

    if not private_key:
        print("❌ Error Crítico: No hay VAPID_PRIVATE_KEY configurada.")
        return

    print(f"🚀 Iniciando envío Push a {len(devices)} dispositivos...")

    for dev in devices:
        try:
            webpush(
                subscription_info={
                    "endpoint": dev.push_endpoint,
                    "keys": {
                        "p256dh": dev.push_p256dh,
                        "auth": dev.push_auth
                    }
                },
                data=json.dumps({
                    "title": title, 
                    "body": body,
                    "icon": "/static/images/icon-192.png", # Asegúrate de tener este ícono
                    "url": "/dashboard"
                }),
                vapid_private_key=private_key,
                vapid_claims={"sub": email}
            )
        except WebPushException as ex:
            print(f"⚠️ Error Push con dispositivo {dev.id}: {ex}")
            # Si Google dice "410 Gone", significa que el usuario borró la app o revocó permiso
            if ex.response and ex.response.status_code == 410:
                print(f"🗑️ Desactivando dispositivo {dev.id} por inactivo.")
                dev.is_active = False
                db.commit()
        except Exception as e:
            print(f"❌ Error genérico Push: {e}")


# NUEVA FUNCIÓN: Notificar solo a la Unidad Familiar + Seguridad
def notify_family_and_security(db: Session, unit: str, title: str, body: str, exclude_user_id: int):
    # 1. Buscar familiares (Misma unidad, excluyendo al que envía)
    family_devices = db.query(Device).join(Member).filter(
        Member.unit_info == unit,
        Member.id != exclude_user_id,
        Device.is_active == True
    ).all()
    
    # 2. Buscar Seguridad (Staff/Admin)
    security_devices = db.query(Device).join(Member).filter(
        Member.role.in_(["staff", "security", "admin"]),
        Device.is_active == True
    ).all()

    targets = family_devices + security_devices
    
    # ... Lógica de envío Push (usando pywebpush) idéntica a trigger_push_notifications ...
    # Por brevedad, aquí reutilizamos la lógica de envío iterando sobre 'targets'
    private_key = os.getenv("VAPID_PRIVATE_KEY")
    email = os.getenv("VAPID_CLAIMS_EMAIL")
    
    if not targets or not private_key: return

    for dev in targets:
        try:
            webpush(
                subscription_info={
                    "endpoint": dev.push_endpoint,
                    "keys": {"p256dh": dev.push_p256dh, "auth": dev.push_auth}
                },
                data=json.dumps({"title": title, "body": body, "url": "/dashboard"}),
                vapid_private_key=private_key,
                vapid_claims={"sub": email}
            )
        except: pass


# --- WEBSOCKET ENDPOINT ---
@router.websocket("/ws/alerta")
async def websocket_endpoint(
    websocket: WebSocket, 
    db: Session = Depends(get_db)
):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            
            # --- CASO 1: LLEGADA ANTICIPADA (Botón Amarillo) ---
            if data.get("type") == "PRE_ARRIVAL":
                usuario = data.get("user", "Vecino")
                unidad = data.get("unit", "")
                user_id = data.get("user_id") 

                # A. WebSocket (Para el Guardia - Visual Inmediato)
                await manager.broadcast({
                    "type": "PRE_ARRIVAL",
                    "user": usuario,
                    "user_id": user_id, 
                    "unit": unidad,
                    "msg": "Llegando en aprox. 5 min"
                })

                # B. Push a Familiares (Secundario)
                # Nota: Asegúrate de tener definida la función 'notify_family_and_security' arriba
                try:
                    notify_family_and_security(
                        db, unit=unidad, 
                        title="🟡 LLEGADA SEGURA", 
                        body=f"{usuario} está llegando a casa.",
                        exclude_user_id=user_id
                    )
                except Exception as e:
                    print(f"Error Push Familia: {e}")

            # --- CASO 2: PÁNICO (Botón Rojo) ---
            elif data.get("type") == "PANIC_BUTTON":
                usuario = data.get("user", "Vecino")
                ubicacion = data.get("location", "")
                
                # 1. PRIORIDAD TOTAL: WebSocket (Pantalla Roja Inmediata)
                # Enviamos esto ANTES de intentar el Push para evitar lag
                await manager.broadcast({
                    "type": "ALERTA_CRITICA",
                    "user": usuario,
                    "msg": "¡ALERTA DE SEGURIDAD!",
                    "coords": data.get("coords")
                })

                # 2. SECUNDARIO: Push Notification Global
                try:
                    trigger_push_notifications(
                        db,
                        title="🚨 ALERTA VECINAL 🚨",
                        body=f"{usuario} ha activado el botón de pánico. {ubicacion}"
                    )
                except Exception as e:
                    print(f"Error Push Pánico (No bloqueante): {e}")

            # --- CASO 3: ACTUALIZACIÓN GPS (Tracking) ---
            elif data.get("type") == "GPS_UPDATE":
                await manager.broadcast({
                    "type": "GPS_UPDATE",
                    "coords": data.get("coords")
                })
                
    except WebSocketDisconnect:
        manager.disconnect(websocket)
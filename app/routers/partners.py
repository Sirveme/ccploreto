from fastapi import APIRouter, Request, Depends, Form, UploadFile, File
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Member, Partner, Organization
from app.routers.dashboard import get_current_member
import base64

router = APIRouter(tags=["partners"])
templates = Jinja2Templates(directory="app/templates")

# --- ADMIN: GUARDAR NUEVO PARTNER ---
@router.post("/partners/create")
async def create_partner(
    name: str = Form(...),
    category: str = Form(...),
    description: str = Form(...),
    phone: str = Form(None),
    whatsapp: str = Form(None),
    logo: UploadFile = File(None),
    db: Session = Depends(get_db),
    admin: Member = Depends(get_current_member)
):
    if admin.role != "admin": return "Acceso denegado"

    # Procesar Logo (Base64 simple para MVP)
    logo_url = None
    if logo and logo.filename:
        contents = await logo.read()
        img_str = base64.b64encode(contents).decode("utf-8")
        logo_url = f"data:{logo.content_type};base64,{img_str}"
    
    # Crear Partner vinculado a ESTA organización
    new_partner = Partner(
        organization_id=admin.organization_id, # Es un proveedor "Local" de este edificio
        name=name,
        category=category,
        description=description,
        phone=phone,
        whatsapp=whatsapp,
        logo_url=logo_url,
        is_verified=True, # Si lo sube el Admin, nace verificado
        is_promoted=True  # Y destacado en su edificio
    )
    
    db.add(new_partner)
    db.commit()
    
    # Retornar mensaje de éxito
    return HTMLResponse(f"""
    <div class="bg-green-900/30 border-l-4 border-green-500 p-4 rounded mb-4 fade-me-in">
        <h3 class="font-bold text-green-400">✅ Proveedor Agregado</h3>
        <p class="text-sm text-slate-300">{name} ahora es visible para los vecinos.</p>
    </div>
    """)
from fastapi import APIRouter, Request, Depends, Form, File, UploadFile
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Member, Pet
from app.routers.dashboard import get_current_member
from app.routers.ws import manager # Para avisar si se pierde

import base64

router = APIRouter(tags=["pets"])
templates = Jinja2Templates(directory="app/templates")

@router.get("/pets")
async def pets_home(request: Request, member: Member = Depends(get_current_member), db: Session = Depends(get_db)):
    # Ver mascotas de MI organización (Vecinos)
    pets = db.query(Pet).filter(Pet.organization_id == member.organization_id).all()
    current_theme = getattr(request.state, "theme", None)
    
    return templates.TemplateResponse("pages/pets/home_pets.html", {
        "request": request,
        "user": member,
        "pets": pets,
        "theme": current_theme
    })

@router.post("/pets/register")
async def register_pet(
    request: Request,
    name: str = Form(...),
    species: str = Form(...),
    notes: str = Form(None), # Esto es lo que escribe el usuario
    db: Session = Depends(get_db),
    member: Member = Depends(get_current_member)
):
    # Lógica de Avatar por Especie
    base_url = "https://loremflickr.com/320/240"
    if species == 'dog': photo = f"{base_url}/dog"
    elif species == 'cat': photo = f"{base_url}/cat"
    elif species == 'pig': photo = f"{base_url}/pig" # ¡Para el chanchito!
    elif species == 'rabbit': photo = f"{base_url}/rabbit"
    else: photo = f"{base_url}/animal"

    new_pet = Pet(
        organization_id=member.organization_id,
        owner_id=member.id,
        name=name,
        species=species,
        breed="No especificado", 
        habits=notes, # <--- MAPEO CRÍTICO: Lo que escribe en notas va a Habits
        photos=[photo], 
        is_lost=False
    )
    db.add(new_pet)
    db.commit()
    
    return templates.TemplateResponse("components/pet_card.html", {
        "pet": new_pet, 
        "request": request,
        "user": member
    })

@router.post("/pets/{pet_id}/lost")
async def report_lost_pet(pet_id: int, db: Session = Depends(get_db)):

    pet = db.query(Pet).filter(Pet.id == pet_id).first()
    pet.is_lost = not pet.is_lost # Toggle estado
    db.commit()
    
    if pet.is_lost:
        # ALERTA DE VOZ A TODOS
        await manager.broadcast({
            "type": "PRE_ARRIVAL", # Usamos amarillo (Advertencia)
            "user": "ALERTA VECINAL",
            "msg": f"Se perdió {pet.name}. Revisen la sección Mascotas."
        })
        
    return "OK" # HTMX manejará el cambio de estado visual

@router.post("/pets/register")
async def register_pet(
    request: Request,
    name: str = Form(...),
    species: str = Form(...),
    breed: str = Form(None), # Nuevo campo
    notes: str = Form(None),
    photo: UploadFile = File(None), # Campo de archivo
    db: Session = Depends(get_db),
    member: Member = Depends(get_current_member)
):
    # 1. Procesar la Foto
    if photo and photo.filename:
        contents = await photo.read()
        # Convertir a Base64 para guardar en BD (Formato: data:image/jpeg;base64,...)
        img_str = base64.b64encode(contents).decode("utf-8")
        content_type = photo.content_type
        final_photo = f"data:{content_type};base64,{img_str}"
    else:
        # Avatar por defecto si no sube nada
        base_url = "https://loremflickr.com/320/240"
        final_photo = f"{base_url}/{species}" if species in ['dog', 'cat'] else f"{base_url}/animal"

    # 2. Guardar
    new_pet = Pet(
        organization_id=member.organization_id,
        owner_id=member.id,
        name=name,
        species=species,
        breed=breed or "No especificado", # Usar el dato del form
        habits=notes, 
        photos=[final_photo], # Guardamos la cadena base64 o url
        is_lost=False
    )
    db.add(new_pet)
    db.commit()
    
    return templates.TemplateResponse("components/pet_card.html", {
        "pet": new_pet, 
        "request": request,
        "user": member
    })
from fastapi import APIRouter, Request, Depends, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import or_
from app.database import get_db
from app.models import Member, AccessLog, Organization, User
from app.routers.dashboard import get_current_member
from itertools import groupby
import os

from zoneinfo import ZoneInfo

router = APIRouter(tags=["security"])
templates = Jinja2Templates(directory="app/templates")

# 1. VISTA PRINCIPAL
@router.get("/centinela")
async def centinela_home(
    request: Request, 
    member: Member = Depends(get_current_member),
    db: Session = Depends(get_db) # <--- Agrega db
):
    if member.role not in ["staff", "admin", "security"]:
         return templates.TemplateResponse("pages/errors/403.html", {"request": request})

    current_theme = getattr(request.state, "theme", None)

    # 1. LOGICA DE SWITCHER
    my_profiles = db.query(Member).join(Organization).filter(
        Member.user_id == member.user_id,
        Member.is_active == True
    ).all()

    return templates.TemplateResponse("pages/security/home_security.html", {
        "request": request,
        "user": member,
        "profiles": my_profiles, # <--- ENVIAR ESTO
        "theme": current_theme,
        "vapid_public_key": os.getenv("VAPID_PUBLIC_KEY")
    })

# 2. BUSCADOR (Devuelve HTML con fotos)
from itertools import groupby # Asegúrate de importar esto arriba

@router.post("/centinela/search")
async def search_neighbors(
    query: str = Form(...), 
    db: Session = Depends(get_db),
    member: Member = Depends(get_current_member)
):
    # 1. Buscar coincidencias con JOIN y ORDENADO (Vital para groupby)
    results = db.query(Member).join(User).filter(
        Member.organization_id == member.organization_id,
        or_(
            User.name.ilike(f"%{query}%"), 
            Member.unit_info.ilike(f"%{query}%")
        )
    ).order_by(Member.unit_info).all() # <--- ORDENAR ES OBLIGATORIO

    if not results:
        return HTMLResponse("<div class='text-slate-500 p-4 text-center italic'>No se encontraron coincidencias.</div>")

    html_content = ""

    # 1. Cabecera con Botón Cerrar (NUEVO)
    html_content = """
    <div class="flex justify-between items-center mb-4 border-b border-slate-700 pb-2 sticky top-0 bg-slate-900 z-10">
        <span class="text-xs text-slate-400 uppercase font-bold">Resultados encontrados</span>
        <button onclick="document.getElementById('search-results').innerHTML = ''; document.querySelector('input[name=query]').value = '';" 
                class="text-slate-400 hover:text-white bg-slate-800 p-1 rounded-full px-3 text-xs transition-colors">
            ✕ Cerrar
        </button>
    </div>
    """
    
    for unit, members_iter in groupby(results, key=lambda x: x.unit_info):
        members = list(members_iter)
        
        # Inicio del Bloque de Unidad
        html_content += f"""
        <div class="mb-6 bg-slate-800/50 rounded-xl border border-slate-700 p-4 fade-me-in">
            <div class="flex justify-between items-center mb-3">
                <h3 class="text-indigo-400 font-bold text-lg border-l-4 border-indigo-500 pl-3">{unit}</h3>
                <span class="text-xs text-slate-500">{len(members)} Residentes</span>
            </div>

            <div class="flex gap-4 overflow-x-auto pb-2 px-1 scrollbar-thin scrollbar-thumb-slate-600">
        """
        
        # Tarjetas
        for res in members:
            # FIX: Asegurar que position tenga un valor
            cargo = res.position if res.position else 'Residente'
            nombre_real = res.user.name
            avatar = f"https://ui-avatars.com/api/?name={nombre_real}&background=random&color=fff&size=128"
            
            # FIX: Pasamos 'cargo' como 4to argumento a toggleSelection
            html_content += f"""
            <div id="card-{res.id}" 
                 class="member-card cursor-pointer min-w-[140px] w-[140px] bg-slate-900 rounded-lg border border-slate-600 p-3 flex flex-col items-center text-center transition-all hover:border-indigo-400 relative group"
                 onclick="toggleSelection('{res.id}', '{nombre_real}', '{unit}', '{cargo}')">
                
                <div id="check-{res.id}" class="hidden absolute top-2 right-2 bg-green-500 text-white rounded-full w-6 h-6 flex items-center justify-center shadow-lg z-10">
                    <i class="ph ph-check text-xs font-bold"></i>
                </div>

                <img src="{avatar}" class="w-16 h-16 rounded-full mb-2 border-2 border-slate-700 group-hover:border-indigo-500 transition-colors object-cover">
                
                <p class="text-slate-200 font-bold text-sm leading-tight line-clamp-2">{nombre_real}</p>
                
                <!-- Mostrar Cargo Visualmente -->
                <span class="text-[10px] mt-1 px-2 py-0.5 rounded bg-slate-800 text-indigo-300 border border-slate-700 uppercase tracking-wide">
                    {cargo}
                </span>
            </div>
            """
        
        html_content += "</div></div>"

    # Botón Flotante (Igual que tu código)
    # Botón Flotante de Confirmación (Barra inferior)
    html_content += """
    <div id="action-bar" class="hidden sticky bottom-0 bg-slate-900/95 backdrop-blur border-t border-slate-700 p-4 mt-4 flex justify-between items-center animate-slide-up z-20">
        <span class="text-slate-300 text-sm"><strong id="count-selected" class="text-white">0</strong> seleccionados</span>
        <div class="flex gap-2">
            <!-- BOTÓN CERRAR NUEVO -->
            <button onclick="document.getElementById('search-results').innerHTML = ''; document.querySelector('input[name=query]').value = '';" 
                    class="bg-slate-700 hover:bg-slate-600 text-white px-4 py-2 rounded-full font-bold text-xs">
                X
            </button>
            
            <button type="button" 
                    onclick="registrarSeleccionados()" 
                    class="bg-green-600 hover:bg-green-500 text-white font-bold py-2 px-6 rounded-full shadow-lg flex items-center gap-2 text-xs transition-transform active:scale-95">
                <i class="ph ph-sign-in text-lg"></i> REGISTRAR
            </button>
        </div>
    </div>
    """

    return HTMLResponse(content=html_content)

# 3. REGISTRAR LOG (Este era el 404)
@router.post("/centinela/log")
async def log_access(
    tipo: str = Form(...),      
    detalle: str = Form(...),   # <--- AQUI LLEGARÁ EL NOMBRE REAL AHORA
    unidad: str = Form(None),   
    member_id: int = Form(None),
    db: Session = Depends(get_db),
    guardia: Member = Depends(get_current_member)
):
    target_unit = unidad
    
    # Si viene ID, buscamos la unidad para el log, PERO RESPETAMOS EL NOMBRE QUE VIENE EN 'detalle'
    if member_id:
        residente = db.query(Member).filter(Member.id == member_id).first()
        if residente:
            target_unit = residente.unit_info
            # NO sobrescribimos 'visitor_name' con residente.user.name aquí, 
            # confiamos en lo que mandó el frontend (que ya es el nombre correcto).
    
    new_log = AccessLog(
        organization_id=guardia.organization_id,
        member_id=member_id, 
        target_unit=target_unit or "Portería",
        direction="IN",
        method="MANUAL_GUARDIA",
        visitor_name=f"[{tipo}] {detalle}" # Quedará: "[RESIDENTE] Juan Pérez"
    )
    db.add(new_log)
    db.commit()

    # --- CORRECCIÓN DE HORA (UTC -> Lima) ---
    # Convertimos la hora guardada a la zona horaria de Perú
    lima_time = new_log.created_at.astimezone(ZoneInfo("America/Lima"))
    time_str = lima_time.strftime("%H:%M") # Ahora será 00:05
    
    # Devolver el HTML del Log Verde
    return HTMLResponse(content=f"""
    <div class="bg-green-900/20 border-l-4 border-green-500 p-2 text-green-300 mb-2 fade-me-in text-[10px]">
        <span class="text-slate-500">[{time_str}]</span> 
        <strong>{tipo}:</strong> {detalle} <span class="text-slate-400">({target_unit})</span>
    </div>
    """)
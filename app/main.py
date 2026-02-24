import json
import os
from fastapi import FastAPI, Request, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import FileResponse, RedirectResponse, HTMLResponse
from sqlalchemy.orm import Session
from app.database import get_db

from jose import jwt
from .utils.security import ALGORITHM # <--- Importar ALGO

from .database import engine, SessionLocal
from .models import Organization
from .config import redis_client, DEFAULT_THEME, THEMES, SECRET_KEY
# Importamos todos los routers
from .routers import auth, dashboard, ws, api, admin, security, pets, finanzas, services, partners, directory, public, pagos_publicos, colegiado, avisos, verificacion

from app.routers import pagos_colegiado

from app.routers.public import router, router_landing
#from app.routers.api_colegiado import router as api_colegiado_router
from app.routers.admin_config_router import router as admin_config_router
from app.routers.admin_views import router as admin_views_router
from app.routers import router_certificados
from app.routers import api_publico
from app.routers.caja import router as caja_router, page_router as caja_page_router

from app.routers.reportes import router as reportes_router
from app.routers.conciliacion import router as conciliacion_router
from app.routers.finanzas import router as finanzas_router, ws_finanzas
from app.routers.finanzas import router_views as finanzas_views
from app.routers.portal_colegiado import router as portal_router
from app.routers.fragments import router as fragments_router
from app.routers.api_colegiado_pagos import router as api_colegiado_pagos_router

app = FastAPI(title="Multi-Tenant SaaS")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# --- MIDDLEWARE INTELIGENTE (Redis + DB) ---
@app.middleware("http")
async def tenant_middleware(request: Request, call_next):
    # 1. Normalizar el Hostname (Quitar puerto y www)
    raw_host = request.headers.get("host", "").lower()
    hostname = raw_host.split(":")[0] # Quita el :8000 si existe
    if hostname.startswith("www."):
        hostname = hostname[4:] # Quita el www.

    org_data = None
    
    # 2. INTENTO A: Consultar Caché (Redis) - Velocidad Extrema
    if redis_client:
        try:
            # Usamos el hostname limpio como llave
            cached_org = redis_client.get(f"tenant:{hostname}")
            if cached_org:
                org_data = json.loads(cached_org)
        except Exception as e:
            print(f"⚠️ Redis Error (Skipping): {e}")

    # 3. INTENTO B: Consultar Base de Datos (Si no estaba en caché)
    if not org_data:
        db = SessionLocal()
        try:
            slug_to_search = None
            
            # --- REGLAS DE ENRUTAMIENTO (Mapping) ---
            # Aquí defines qué dominio apunta a qué cliente
            
            # Caso 1: Colegio de Contadores (Producción y Demo)
            if hostname == "ccploreto.org.pe" or hostname.endswith("duilio.store"):
                slug_to_search = "ccp-loreto"
            
            # Caso 2: Condominios (Tu SaaS)
            elif "leavisamos" in hostname:
                slug_to_search = "las-palmeras"
            
            # Caso 3: Condominios (Tu SaaS)
            elif "metraes.com" in hostname: 
                slug_to_search = "ccp-loreto" # <--- Apuntamos al mismo cliente/BD
            
            # Caso 4: Desarrollo Local
            elif hostname in ["localhost", "127.0.0.1"]:
                # CAMBIA ESTO SEGÚN LO QUE QUIERAS PROBAR HOY:
                slug_to_search = "ccp-loreto" 
                # slug_to_search = "las-palmeras"
            
            # Consulta SQL
            if slug_to_search:
                org = db.query(Organization).filter(Organization.slug == slug_to_search).first()
                if org:
                    # Serializar para guardar en Redis y en el Request
                    # Convertimos el objeto SQLAlchemy a un diccionario puro
                    org_data = {
                        "id": org.id,
                        "name": org.name,
                        "type": org.type,
                        "slug": org.slug,
                        "theme_color": org.theme_color,
                        "logo_url": org.logo_url,
                        "config": org.config or {} # Asegurar que no sea None
                    }
                    
                    # Guardar en Redis (TTL 10 minutos = 600 segundos)
                    if redis_client:
                        try:
                            redis_client.setex(f"tenant:{hostname}", 600, json.dumps(org_data))
                        except Exception as e:
                            print(f"⚠️ No se pudo guardar en Redis: {e}")
                        
        except Exception as e:
            print(f"❌ Error Crítico DB Middleware: {e}")
        finally:
            db.close()

    # 4. Inyectar Contexto en el Request (Vital para que no fallen los templates)
    if org_data:
        request.state.org = org_data
        
        # Construir el tema dinámico
        request.state.theme = {
            "site_name": org_data["name"],
            "primary_color": org_data["theme_color"],
            "logo": org_data["logo_url"],
            "tone": "formal" if org_data["type"] == "colegio_prof" else "friendly",
            "modules": org_data["config"].get("modules", {})
        }
    else:
        # Fallback: Si el dominio no existe en BD, cargamos default para mostrar Landing
        request.state.org = None
        request.state.theme = DEFAULT_THEME

    response = await call_next(request)
    return response

# --- RUTAS ---
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(ws.router)
app.include_router(api.router)
app.include_router(admin.router)
app.include_router(security.router)
app.include_router(pets.router)
app.include_router(services.router)
app.include_router(partners.router)
app.include_router(directory.router)
app.include_router(public.router)
app.include_router(pagos_publicos.router)
app.include_router(colegiado.router)
app.include_router(router)
#app.include_router(api_colegiado_router)
app.include_router(router_landing)
app.include_router(avisos.router)
app.include_router(avisos.router_sunat)  # Para consulta de RUC
app.include_router(verificacion.router)  # Público, sin prefijo de API
app.include_router(admin_config_router)
app.include_router(admin_views_router)
app.include_router(pagos_colegiado.router)
app.include_router(router_certificados.router)
app.include_router(api_publico.router)
app.include_router(caja_router)
app.include_router(caja_page_router)
app.include_router(reportes_router)
app.include_router(conciliacion_router)
app.include_router(finanzas_router)
app.include_router(finanzas_views) 
app.websocket("/ws/finanzas")(ws_finanzas)
app.include_router(portal_router)
app.include_router(fragments_router)
app.include_router(api_colegiado_pagos_router)


# --- RUTAS BASE ---
@app.get("/service-worker.js")
async def get_service_worker():
    return FileResponse("static/service-worker.js", media_type="application/javascript")

@app.get("/manifest.json")
async def get_manifest():
    return FileResponse("static/manifest.json", media_type="application/json")

@app.get("/")
async def home(request: Request):
    # 1. Obtener cookie
    token = request.cookies.get("access_token")
    current_org = getattr(request.state, "org", None)

    # 2. VALIDAR SI EL TOKEN ES DE ESTA ORGANIZACIÓN
    should_redirect = False
    
    if token and current_org:
        try:
            # Limpiar "Bearer " si existe
            token_clean = token.replace("Bearer ", "")
            # Decodificar sin verificar firma a fondo (solo lectura rápida)
            payload = jwt.decode(token_clean, SECRET_KEY, algorithms=[ALGORITHM])
            
            # ¿El token tiene el nombre de esta organización?
            token_org = payload.get("org_name")
            
            if token_org == current_org['name']:
                should_redirect = True
            else:
                print(f"🚫 Token de '{token_org}' no sirve en '{current_org['name']}'")
        except Exception as e:
            print(f"⚠️ Token inválido en Home: {e}")
            pass # Si falla, asumimos no logueado

    if should_redirect:
        return RedirectResponse(url="/dashboard")
    
    # 3. Si no redirige, mostramos contenido público
    
    # Caso A: Landing Page de Venta (Dominio desconocido)
    if not current_org:
        return templates.TemplateResponse("landing/resumen.html", {"request": request})

    # Caso B: Portal del Cliente (Ej: ccp-loreto.html)
    template_path = f"sites/{current_org['slug']}.html"
    if os.path.exists(os.path.join("app", "templates", template_path)):
        return templates.TemplateResponse(template_path, {
            "request": request, "org": current_org, "theme": request.state.theme
        })

    # Caso C: Login por defecto
    return templates.TemplateResponse("pages/login.html", {
        "request": request, "theme": request.state.theme
    })


# RUTA EXPLÍCITA PARA EL LOGIN (Para enlazar desde el Portal)
@app.get("/login")
async def login_page(request: Request):
    # Si ya está logueado, al dashboard
    if request.cookies.get("access_token"):
        return RedirectResponse(url="/dashboard")

    #return templates.TemplateResponse("/dashboard", {
    return templates.TemplateResponse("pages/login.html", {
        "request": request,
        "theme": request.state.theme
    })

@app.get("/resumen")
async def resumen(request: Request):
    return templates.TemplateResponse("landing/resumen.html", {"request": request})

@app.get("/demo/ads")
async def demo_ads(request: Request):
    return templates.TemplateResponse("landing/demo_ads.html", {"request": request})



# ==============================================================
# Agregar RUTAS PARA TERMINOS Y POLITICAS DE PRIVACIDAD PÚBLICAS
# ==============================================================
# ============================================================
# AGREGAR a app/routers/public.py (o app/main.py)
# Rutas para páginas legales
# ============================================================

# Línea 244 - cambiar router → app
@app.get("/politica-privacidad/", response_class=HTMLResponse)
@app.get("/politica-privacidad", response_class=HTMLResponse)
async def politica_privacidad(request: Request):
    return templates.TemplateResponse("pages/politica_privacidad.html", {
        "request": request,
        "org": getattr(request.state, 'org', None),
    })

# Línea 254 - cambiar router → app
@app.get("/terminos/", response_class=HTMLResponse)
@app.get("/terminos", response_class=HTMLResponse)
async def terminos_condiciones(request: Request):
    return templates.TemplateResponse("pages/terminos.html", {
        "request": request,
        "org": getattr(request.state, 'org', None),
    })

@app.get("/admin/comprobantes")
async def admin_comprobantes(request: Request, db: Session = Depends(get_db)):
    org = db.query(Organization).filter(Organization.id == 1).first()
    return templates.TemplateResponse("admin_comprobantes.html", {"request": request, "org": org})

# Ruta del template
@app.get("/admin/reportes")
async def admin_reportes(request: Request):
    return templates.TemplateResponse("pages/reportes.html", {"request": request})


@app.get("/tesoreria")
async def tesoreria_page(request: Request):
    return templates.TemplateResponse("dashboard_finanzas.html", {"request": request})

@app.get("/portal/inactivo")
async def portal_inactivo_page(request: Request):
     token = request.cookies.get("access_token")
     if not token:
         return RedirectResponse(url="/")
     return templates.TemplateResponse("portal_inactivo.html", {"request": request})
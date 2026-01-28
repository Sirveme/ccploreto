import json
import os
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.orm import Session

from jose import jwt
from .utils.security import ALGORITHM # <--- Importar ALGO

from .database import engine, SessionLocal
from .models import Organization
from .config import redis_client, DEFAULT_THEME, THEMES, SECRET_KEY
# Importamos todos los routers
from .routers import auth, dashboard, ws, api, admin, security, pets, finance, services, partners, directory

app = FastAPI(title="Multi-Tenant SaaS")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# --- MIDDLEWARE INTELIGENTE (Redis + DB) ---
@app.middleware("http")
async def tenant_middleware(request: Request, call_next):
    host = request.headers.get("host", "").lower()
    hostname = host.split(":")[0]
    org_data = None
    
    # 1. Consultar Caché (Redis)
    if redis_client:
        try:
            cached_org = redis_client.get(f"tenant:{hostname}")
            if cached_org:
                org_data = json.loads(cached_org)
        except Exception:
            pass

    # 2. Consultar BD (Si no hay caché)
    if not org_data:
        db = SessionLocal()
        try:
            slug_to_search = None
            
            # --- REGLAS DE ENRUTAMIENTO ---
            if "ccploreto" in hostname or "duilio.store" in hostname:
                slug_to_search = "ccp-loreto"
            elif "leavisamos" in hostname:
                slug_to_search = "las-palmeras"
            elif "localhost" in hostname or "127.0.0.1" in hostname:
                slug_to_search = "las-palmeras" # Default Local (Cámbialo si quieres probar el otro)
            
            if slug_to_search:
                org = db.query(Organization).filter(Organization.slug == slug_to_search).first()
                if org:
                    org_data = {
                        "id": org.id,
                        "name": org.name,
                        "type": org.type,
                        "slug": org.slug,
                        "theme_color": org.theme_color,
                        "logo_url": org.logo_url,
                        "config": org.config
                    }
                    if redis_client:
                        redis_client.setex(f"tenant:{hostname}", 600, json.dumps(org_data))
        finally:
            db.close()

    # 3. Inyectar en Request
    if org_data:
        request.state.org = org_data
        request.state.theme = {
            "site_name": org_data["name"],
            "primary_color": org_data["theme_color"],
            "logo": org_data["logo_url"],
            "tone": "formal" if org_data["type"] == "colegio_prof" else "friendly",
            "modules": org_data["config"].get("modules", {})
        }
    else:
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
app.include_router(finance.router)
app.include_router(services.router)
app.include_router(partners.router)
app.include_router(directory.router)

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

    #return templates.TemplateResponse("pages/login.html", {
    return templates.TemplateResponse("/dashboard", {
        "request": request,
        "theme": request.state.theme
    })

@app.get("/resumen")
async def resumen(request: Request):
    return templates.TemplateResponse("landing/resumen.html", {"request": request})

@app.get("/demo/ads")
async def demo_ads(request: Request):
    return templates.TemplateResponse("landing/demo_ads.html", {"request": request})
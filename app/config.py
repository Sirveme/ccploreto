import os
from dotenv import load_dotenv
import redis

load_dotenv(override=True)

DATABASE_URL = os.getenv("DATABASE_URL")
SECRET_KEY = os.getenv("SECRET_KEY", "secret_dev_key")
REDIS_URL = os.getenv("REDIS_URL")

# Cliente Redis (Singleton con manejo de errores)
redis_client = None
if REDIS_URL:
    try:
        redis_client = redis.from_url(REDIS_URL, decode_responses=True)
        print("✅ Redis conectado.")
    except Exception as e:
        print(f"⚠️ Redis no disponible: {e}")

# Temas por defecto
DEFAULT_THEME = {
    "site_name": "LeAvisamos",
    "primary_color": "#6366f1",
    "logo_icon": "ph-buildings",
    "tone": "friendly",
    "hero_text": "Tu Comunidad Conectada"
}

# Temas estáticos (Legacy)
THEMES = {
    "leavisamos": DEFAULT_THEME,
    "notificado": {
        "site_name": "Notificado",
        "primary_color": "#ef4444",
        "logo_icon": "ph-gavel",
        "tone": "formal",
        "hero_text": "Gestión Oficial"
    }
}
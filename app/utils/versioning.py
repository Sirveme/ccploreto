"""
Versionado dinámico de assets estáticos para cache-busting automático.
Reemplaza el ?v=N manual por ?v={hash_md5_corto} calculado en runtime.

Uso en templates Jinja2:
    <script src="/static/js/x.js?v={{ asset_v('js/x.js') }}"></script>
"""
import hashlib
from pathlib import Path
from functools import lru_cache

# /static está en la raíz del proyecto (junto a app/)
STATIC_ROOT = Path(__file__).resolve().parent.parent.parent / "static"


@lru_cache(maxsize=256)
def asset_v(rel_path: str) -> str:
    """
    Devuelve los primeros 8 chars del hash MD5 del archivo.
    rel_path es relativo a /static (ej. 'js/pages/caja.js').
    Cache LRU: solo se calcula una vez por archivo por proceso.
    Cada deploy reinicia el proceso → cache se renueva.
    """
    if rel_path.startswith("/static/"):
        rel_path = rel_path[len("/static/"):]
    elif rel_path.startswith("static/"):
        rel_path = rel_path[len("static/"):]
    
    full = STATIC_ROOT / rel_path
    if not full.exists() or not full.is_file():
        return "0"
    
    try:
        return hashlib.md5(full.read_bytes()).hexdigest()[:8]
    except Exception:
        return "0"
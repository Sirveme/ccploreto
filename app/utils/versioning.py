"""
zClaude-97e — Versionado dinámico de assets estáticos.

Reemplaza el ?v=N manual por ?v=<hash_md5_8chars> calculado en runtime.
Si el archivo cambia, el hash cambia, el navegador recarga automáticamente.

Uso en templates Jinja2:
    <script src="/static/js/x.js?v={{ asset_v('js/x.js') }}"></script>
    <link rel="stylesheet" href="/static/css/x.css?v={{ asset_v('css/x.css') }}">

Inicialización (ya hecha en app/main.py):
    from .utils.versioning import asset_v
    templates.env.globals["asset_v"] = asset_v

Cache LRU: el hash se calcula una vez por archivo por proceso.
Cada deploy reinicia el proceso → cache se renueva automáticamente.
"""
import hashlib
from pathlib import Path
from functools import lru_cache

# El proyecto tiene /static en la raíz (junto a app/).
# Este archivo vive en app/utils/versioning.py, raíz son 2 niveles arriba.
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
STATIC_ROOT = PROJECT_ROOT / "static"


@lru_cache(maxsize=256)
def asset_v(rel_path: str) -> str:
    """
    Devuelve los primeros 8 caracteres del hash MD5 del archivo.

    Args:
        rel_path: ruta relativa a /static. Acepta:
            - 'js/pages/caja.js'         (recomendado)
            - 'static/js/pages/caja.js'  (también funciona)
            - '/static/js/pages/caja.js' (también funciona)

    Returns:
        - String de 8 caracteres si el archivo existe
        - "0" si el archivo no existe (evita 500 errors si hay un typo)
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
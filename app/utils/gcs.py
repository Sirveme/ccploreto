"""
Google Cloud Storage — ColegiosPro
====================================
Bucket:  colegiospro-assets (fine-grained access control)
SA:      colegiospro-sa

Estructura de carpetas:
  {org_id}/miembros/{colegiado_id}/foto_perfil.webp     → público
  {org_id}/miembros/{colegiado_id}/constancia_*.pdf      → signed URL
  {org_id}/eventos/{año}/{nombre}/foto_01.webp           → público
  {org_id}/documentos/...                                 → signed URL

Variables de entorno en Railway:
  GCS_BUCKET_NAME          = colegiospro-assets
  GCS_CREDENTIALS_JSON     = {"type":"service_account",...}  (JSON completo de colegiospro-sa)
"""

import os
import json
import datetime
from typing import Optional

_client = None
_credentials = None

BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "colegiospro-assets")


def _get_credentials():
    """Parsea credenciales una sola vez"""
    global _credentials
    if _credentials is not None:
        return _credentials

    creds_json = os.getenv("GCS_CREDENTIALS_JSON")
    if not creds_json:
        return None

    try:
        from google.oauth2 import service_account
        creds_info = json.loads(creds_json)
        _credentials = service_account.Credentials.from_service_account_info(creds_info)
        return _credentials
    except Exception as e:
        print(f"⚠️ GCS: Error parseando credenciales: {e}")
        return None


def _get_client():
    """Inicializa cliente GCS (lazy, singleton)"""
    global _client
    if _client is not None:
        return _client

    credentials = _get_credentials()
    if not credentials:
        return None

    try:
        from google.cloud import storage
        _client = storage.Client(credentials=credentials)
        return _client
    except Exception as e:
        print(f"⚠️ GCS: Error inicializando cliente: {e}")
        return None


# ─── FOTOS DE PERFIL (Públicas) ─────────────────────────────────

def upload_foto_perfil(
    file_bytes: bytes,
    content_type: str,
    organization_id: int,
    colegiado_id: int,
) -> Optional[str]:
    """
    Sube foto de perfil a GCS y la hace pública.
    Retorna URL pública permanente, o None si GCS no está configurado.
    
    Siempre sobrescribe el archivo anterior (mismo path).
    """
    client = _get_client()
    if not client:
        print("⚠️ GCS no configurado — foto no guardada")
        return None

    ext_map = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
    ext = ext_map.get(content_type, "jpg")

    # Path fijo por colegiado: sobrescribe la anterior automáticamente
    blob_path = f"{organization_id}/miembros/{colegiado_id}/foto_perfil.{ext}"

    try:
        bucket = client.bucket(BUCKET_NAME)
        blob = bucket.blob(blob_path)

        blob.upload_from_string(file_bytes, content_type=content_type)
        blob.cache_control = "public, max-age=3600"
        blob.patch()

        # Hacer público este objeto específico (fine-grained)
        #blob.make_public()

        return blob.public_url

    except Exception as e:
        print(f"⚠️ GCS: Error subiendo foto: {e}")
        return None


def delete_foto_perfil(url: str) -> bool:
    """Elimina foto anterior de GCS."""
    client = _get_client()
    if not client or not url:
        return False

    try:
        prefix = f"https://storage.googleapis.com/{BUCKET_NAME}/"
        if url.startswith(prefix):
            blob_path = url[len(prefix):]
        elif url.startswith("http"):
            return False  # URL de otro origen, no tocar
        else:
            blob_path = url

        bucket = client.bucket(BUCKET_NAME)
        blob = bucket.blob(blob_path)
        blob.delete()
        return True

    except Exception as e:
        print(f"⚠️ GCS: Error eliminando foto: {e}")
        return False


# ─── DOCUMENTOS PRIVADOS (Signed URLs) ──────────────────────────

def upload_documento(
    file_bytes: bytes,
    content_type: str,
    blob_path: str,
) -> Optional[str]:
    """
    Sube documento privado a GCS.
    Retorna el blob_path (NO una URL) para guardar en BD.
    Para descarga, usar generar_signed_url().
    
    Ejemplo blob_path:
      "1/miembros/42/constancia_habilidad_20260201.pdf"
    """
    client = _get_client()
    if not client:
        print("⚠️ GCS no configurado — documento no guardado")
        return None

    try:
        bucket = client.bucket(BUCKET_NAME)
        blob = bucket.blob(blob_path)
        blob.upload_from_string(file_bytes, content_type=content_type)
        return blob_path

    except Exception as e:
        print(f"⚠️ GCS: Error subiendo documento: {e}")
        return None


def generar_signed_url(blob_path: str, minutos: int = 5) -> Optional[str]:
    """
    Genera URL temporal para descargar documento privado.
    Constancias: 5 min.  Previews: 15 min.
    """
    credentials = _get_credentials()
    client = _get_client()
    if not client or not credentials:
        return None

    try:
        bucket = client.bucket(BUCKET_NAME)
        blob = bucket.blob(blob_path)

        url = blob.generate_signed_url(
            expiration=datetime.timedelta(minutes=minutos),
            method="GET",
            credentials=credentials,
        )
        return url

    except Exception as e:
        print(f"⚠️ GCS: Error generando signed URL: {e}")
        return None
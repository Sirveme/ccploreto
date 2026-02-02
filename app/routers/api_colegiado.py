"""
API Colegiado — Actualización de perfil
========================================
Endpoint: POST /api/colegiado/actualizar
Recibe:   FormData (campos de texto + foto opcional)
Retorna:  JSON { ok, message, completitud, datos_completos }
"""

import asyncio
from fastapi import APIRouter, Request, Depends, HTTPException, UploadFile
from sqlalchemy.orm import Session
from datetime import datetime, date

from app.database import get_db
from app.models import Colegiado, Member
from app.routers.dashboard import get_current_member
from app.utils.gcs import upload_foto_perfil, delete_foto_perfil

router = APIRouter(prefix="/api/colegiado", tags=["API Colegiado"])

# --- Constantes ---

MAX_FOTO_SIZE = 5 * 1024 * 1024  # 5 MB
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}

TEXT_FIELDS = [
    "email", "telefono", "direccion", "lugar_nacimiento",
    "estado_civil", "tipo_sangre", "universidad", "grado_academico",
    "especialidad", "situacion_laboral", "centro_trabajo", "cargo",
    "ruc_empleador", "direccion_trabajo", "telefono_trabajo",
    "nombre_conyuge", "contacto_emergencia_nombre",
    "contacto_emergencia_telefono", "contacto_emergencia_parentesco",
    "sitio_web", "linkedin", "facebook", "instagram", "tiktok",
]

DATE_FIELDS = ["fecha_nacimiento", "fecha_titulo"]

# Campos que cuentan para el % de completitud
REQUIRED_FIELDS = [
    "email", "telefono", "direccion", "fecha_nacimiento",
    "universidad", "situacion_laboral",
    "contacto_emergencia_nombre", "contacto_emergencia_telefono",
]

SCORED_FIELDS = REQUIRED_FIELDS + [
    "lugar_nacimiento", "estado_civil", "tipo_sangre",
    "fecha_titulo", "grado_academico", "especialidad",
    "centro_trabajo", "cargo",
    "nombre_conyuge", "contacto_emergencia_parentesco",
    "sitio_web", "linkedin", "foto_url",
]


# --- Helpers ---

def find_colegiado(member: Member, db: Session) -> Colegiado | None:
    """
    Busca el colegiado vinculado al member autenticado.
    Misma lógica que dashboard.py — TODO: refactorizar a utils compartido.
    """
    user_input = member.user.public_id if member.user else None
    colegiado = None

    if user_input:
        user_input = user_input.strip().upper()

        # Por DNI (8 dígitos)
        if len(user_input) == 8 and user_input.isdigit():
            colegiado = db.query(Colegiado).filter(
                Colegiado.organization_id == member.organization_id,
                Colegiado.dni == user_input,
            ).first()

        # Por matrícula con guión
        elif "-" in user_input:
            colegiado = db.query(Colegiado).filter(
                Colegiado.organization_id == member.organization_id,
                Colegiado.codigo_matricula == user_input,
            ).first()

        # Por código tipo 10XXXX
        elif user_input.startswith("10"):
            resto = user_input[2:]
            numero, letra = "", ""
            for i, char in enumerate(resto):
                if char.isdigit():
                    numero += char
                else:
                    letra = resto[i:].upper()
                    break
            matricula = f"10-{numero.zfill(4)}{letra}"
            colegiado = db.query(Colegiado).filter(
                Colegiado.organization_id == member.organization_id,
                Colegiado.codigo_matricula == matricula,
            ).first()

    # Fallback: por member_id
    if not colegiado:
        colegiado = db.query(Colegiado).filter(
            Colegiado.member_id == member.id
        ).first()

    # Fallback: DNI sin filtro de organización
    if not colegiado and user_input and len(user_input) == 8 and user_input.isdigit():
        colegiado = db.query(Colegiado).filter(
            Colegiado.dni == user_input
        ).first()

    return colegiado


def calcular_completitud(colegiado: Colegiado) -> tuple[int, bool]:
    """
    Retorna (porcentaje, todos_requeridos_completos).
    El porcentaje se basa en SCORED_FIELDS.
    """
    filled = sum(
        1 for f in SCORED_FIELDS
        if getattr(colegiado, f, None) not in (None, "", 0)
    )
    porcentaje = round((filled / len(SCORED_FIELDS)) * 100)

    es_completo = all(
        getattr(colegiado, f, None) not in (None, "", 0)
        for f in REQUIRED_FIELDS
    )

    return porcentaje, es_completo


# --- Endpoint ---

@router.post("/actualizar")
async def actualizar_perfil(
    request: Request,
    member: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
):
    """Actualiza perfil del colegiado desde el formulario del dashboard."""

    colegiado = find_colegiado(member, db)
    if not colegiado:
        raise HTTPException(404, "No se encontró tu registro de colegiado")

    form = await request.form()

    # ── Campos de texto ──────────────────────────────────────
    for field in TEXT_FIELDS:
        value = form.get(field, "")
        if isinstance(value, str):
            value = value.strip()
            setattr(colegiado, field, value or None)

    # ── Campos de fecha ──────────────────────────────────────
    for field in DATE_FIELDS:
        value = form.get(field, "")
        if isinstance(value, str):
            value = value.strip()
        if value:
            try:
                setattr(colegiado, field, date.fromisoformat(value))
            except ValueError:
                pass  # Fecha inválida → ignorar
        else:
            setattr(colegiado, field, None)

    # ── Campos numéricos ─────────────────────────────────────
    cantidad = form.get("cantidad_hijos", "0")
    if isinstance(cantidad, str):
        cantidad = cantidad.strip()
    colegiado.cantidad_hijos = int(cantidad) if cantidad and cantidad.isdigit() else 0

    # ── Foto (opcional) ──────────────────────────────────────
    foto = form.get("foto")
    if foto and hasattr(foto, "read"):
        content_type = getattr(foto, "content_type", "image/jpeg") or "image/jpeg"

        if content_type not in ALLOWED_IMAGE_TYPES:
            raise HTTPException(400, "Formato no soportado. Usa JPG, PNG o WebP.")

        foto_bytes = await foto.read()

        if len(foto_bytes) > MAX_FOTO_SIZE:
            raise HTTPException(400, "La foto excede 5 MB.")

        if len(foto_bytes) > 0:
            # Subir en thread para no bloquear el event loop
            old_url = colegiado.foto_url
            new_url = await asyncio.to_thread(
                upload_foto_perfil,
                foto_bytes, content_type,
                colegiado.organization_id, colegiado.id,
            )
            if new_url:
                colegiado.foto_url = new_url
                # Limpiar foto anterior (si era de otro path/origen)
                if old_url and old_url != new_url:
                    await asyncio.to_thread(delete_foto_perfil, old_url)

    # ── Vincular member si no estaba ─────────────────────────
    if not colegiado.member_id:
        colegiado.member_id = member.id

    # ── Metadata ─────────────────────────────────────────────
    colegiado.datos_actualizados_at = datetime.now()
    porcentaje, es_completo = calcular_completitud(colegiado)
    colegiado.datos_completos = es_completo

    # ── Guardar ──────────────────────────────────────────────
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"⚠️ Error guardando perfil: {e}")
        raise HTTPException(500, "Error al guardar los datos")

    return {
        "ok": True,
        "message": "Datos actualizados correctamente",
        "completitud": porcentaje,
        "datos_completos": es_completo,
    }


async def guardar_foto(foto: UploadFile, organization_id: int, colegiado_id: int) -> str:
    """Guarda la foto del colegiado en GCS"""
    try:
        ext = foto.filename.split('.')[-1].lower()
        if ext not in ['jpg', 'jpeg', 'png', 'webp']:
            return None

        content_type_map = {
            'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
            'png': 'image/png', 'webp': 'image/webp'
        }
        content = await foto.read()
        if len(content) > 5 * 1024 * 1024:
            return None

        return upload_foto_perfil(
            content,
            content_type_map.get(ext, 'image/jpeg'),
            organization_id,
            colegiado_id
        )
    except Exception as e:
        print(f"⚠️ Error guardando foto: {e}")
        return None
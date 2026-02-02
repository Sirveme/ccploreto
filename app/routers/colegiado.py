"""
Router: Colegiado
Gestión de datos personales, estudios, laborales, familiares
"""

import os
import uuid
from datetime import datetime
from fastapi import APIRouter, Request, Depends, Form, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Member, Colegiado
from app.routers.dashboard import get_current_member
from datetime import timezone

router = APIRouter(prefix="/api/colegiado", tags=["colegiado"])

def buscar_colegiado_de_member(member: Member, db: Session) -> Colegiado | None:
    """Busca colegiado vinculado al member (misma lógica que dashboard)"""
    user_input = member.user.public_id if member.user else None
    if not user_input:
        return None
    
    user_input = user_input.strip().upper()
    org_id = member.organization_id
    
    # Por DNI (8 dígitos)
    if len(user_input) == 8 and user_input.isdigit():
        c = db.query(Colegiado).filter(
            Colegiado.organization_id == org_id,
            Colegiado.dni == user_input
        ).first()
        if c:
            return c
    
    # Por matrícula con guión
    if '-' in user_input:
        c = db.query(Colegiado).filter(
            Colegiado.organization_id == org_id,
            Colegiado.codigo_matricula == user_input
        ).first()
        if c:
            return c
    
    # Por código tipo 10XXXX
    if user_input.startswith('10'):
        resto = user_input[2:]
        numero, letra = '', ''
        for i, char in enumerate(resto):
            if char.isdigit():
                numero += char
            else:
                letra = resto[i:].upper()
                break
        matricula = f"10-{numero.zfill(4)}{letra}"
        c = db.query(Colegiado).filter(
            Colegiado.organization_id == org_id,
            Colegiado.codigo_matricula == matricula
        ).first()
        if c:
            return c
    
    # Fallback: por member_id
    return db.query(Colegiado).filter(
        Colegiado.member_id == member.id
    ).first()


# ============================================================
# OBTENER DATOS DEL COLEGIADO
# ============================================================
@router.get("/mis-datos")
async def obtener_mis_datos(
    member: Member = Depends(get_current_member),
    db: Session = Depends(get_db)
):
    """Obtiene todos los datos del colegiado logueado"""
    colegiado = buscar_colegiado_de_member(member, db)
    
    if not colegiado:
        raise HTTPException(404, "Colegiado no encontrado")
    
    return {
        "id": colegiado.id,
        "personal": {
            "dni": colegiado.dni,
            "tipo_documento": getattr(colegiado, 'tipo_documento', 'DNI'),
            "apellidos_nombres": colegiado.apellidos_nombres,
            "sexo": colegiado.sexo,
            "fecha_nacimiento": colegiado.fecha_nacimiento.isoformat() if hasattr(colegiado, 'fecha_nacimiento') and colegiado.fecha_nacimiento else None,
            "lugar_nacimiento": getattr(colegiado, 'lugar_nacimiento', None),
            "estado_civil": getattr(colegiado, 'estado_civil', None),
            "tipo_sangre": getattr(colegiado, 'tipo_sangre', None),
            "email": colegiado.email,
            "telefono": colegiado.telefono,
            "direccion": colegiado.direccion,
            "foto_url": colegiado.foto_url
        },
        "estudios": {
            "universidad": getattr(colegiado, 'universidad', None),
            "fecha_titulo": colegiado.fecha_titulo.isoformat() if hasattr(colegiado, 'fecha_titulo') and colegiado.fecha_titulo else None,
            "grado_academico": getattr(colegiado, 'grado_academico', None),
            "especialidad": colegiado.especialidad,
            "fecha_colegiatura": colegiado.fecha_colegiatura.isoformat() if colegiado.fecha_colegiatura else None,
            "codigo_matricula": colegiado.codigo_matricula,
            "otros_estudios": getattr(colegiado, 'otros_estudios', []) or []
        },
        "laboral": {
            "situacion_laboral": getattr(colegiado, 'situacion_laboral', None),
            "centro_trabajo": getattr(colegiado, 'centro_trabajo', None),
            "cargo": getattr(colegiado, 'cargo', None),
            "ruc_empleador": getattr(colegiado, 'ruc_empleador', None),
            "direccion_trabajo": getattr(colegiado, 'direccion_trabajo', None),
            "telefono_trabajo": getattr(colegiado, 'telefono_trabajo', None)
        },
        "familiar": {
            "nombre_conyuge": getattr(colegiado, 'nombre_conyuge', None),
            "cantidad_hijos": getattr(colegiado, 'cantidad_hijos', 0),
            "contacto_emergencia_nombre": getattr(colegiado, 'contacto_emergencia_nombre', None),
            "contacto_emergencia_telefono": getattr(colegiado, 'contacto_emergencia_telefono', None),
            "contacto_emergencia_parentesco": getattr(colegiado, 'contacto_emergencia_parentesco', None)
        },
        "redes": {
            "sitio_web": getattr(colegiado, 'sitio_web', None),
            "linkedin": getattr(colegiado, 'linkedin', None),
            "facebook": getattr(colegiado, 'facebook', None),
            "instagram": getattr(colegiado, 'instagram', None)
        },
        "meta": {
            "condicion": colegiado.condicion,
            "datos_actualizados_at": colegiado.datos_actualizados_at.isoformat() if hasattr(colegiado, 'datos_actualizados_at') and colegiado.datos_actualizados_at else None,
            "datos_completos": getattr(colegiado, 'datos_completos', False)
        }
    }


# ============================================================
# ACTUALIZAR DATOS PERSONALES
# ============================================================
@router.post("/actualizar/personal")
async def actualizar_datos_personales(
    request: Request,
    email: str = Form(None),
    telefono: str = Form(None),
    direccion: str = Form(None),
    fecha_nacimiento: str = Form(None),
    lugar_nacimiento: str = Form(None),
    estado_civil: str = Form(None),
    tipo_sangre: str = Form(None),
    foto: UploadFile = File(None),
    member: Member = Depends(get_current_member),
    db: Session = Depends(get_db)
):
    """Actualiza datos personales del colegiado"""
    colegiado = buscar_colegiado_de_member(member, db)
    
    if not colegiado:
        raise HTTPException(404, "Colegiado no encontrado")
    
    if email is not None:
        colegiado.email = email.strip() if email else None
    if telefono is not None:
        colegiado.telefono = telefono.strip() if telefono else None
    if direccion is not None:
        colegiado.direccion = direccion.strip() if direccion else None
    if fecha_nacimiento:
        try:
            colegiado.fecha_nacimiento = datetime.strptime(fecha_nacimiento, "%Y-%m-%d").date()
        except:
            pass
    if lugar_nacimiento is not None:
        colegiado.lugar_nacimiento = lugar_nacimiento.strip() if lugar_nacimiento else None
    if estado_civil is not None:
        colegiado.estado_civil = estado_civil if estado_civil else None
    if tipo_sangre is not None:
        colegiado.tipo_sangre = tipo_sangre if tipo_sangre else None
    
    if foto and foto.filename:
        foto_url = await guardar_foto(foto, colegiado.organization_id, colegiado.id)
        if foto_url:
            colegiado.foto_url = foto_url
    
    colegiado.datos_actualizados_at = datetime.now(timezone.utc)
    verificar_datos_completos(colegiado)
    
    db.commit()
    
    return {"status": "ok", "message": "Datos personales actualizados"}


# ============================================================
# ACTUALIZAR DATOS DE ESTUDIOS
# ============================================================
@router.post("/actualizar/estudios")
async def actualizar_datos_estudios(
    universidad: str = Form(None),
    fecha_titulo: str = Form(None),
    grado_academico: str = Form(None),
    especialidad: str = Form(None),
    member: Member = Depends(get_current_member),
    db: Session = Depends(get_db)
):
    """Actualiza datos de estudios del colegiado"""
    colegiado = buscar_colegiado_de_member(member, db)
    
    if not colegiado:
        raise HTTPException(404, "Colegiado no encontrado")
    
    if universidad is not None:
        colegiado.universidad = universidad.strip() if universidad else None
    if fecha_titulo:
        try:
            colegiado.fecha_titulo = datetime.strptime(fecha_titulo, "%Y-%m-%d").date()
        except:
            pass
    if grado_academico is not None:
        colegiado.grado_academico = grado_academico if grado_academico else None
    if especialidad is not None:
        colegiado.especialidad = especialidad.strip() if especialidad else None
    
    colegiado.datos_actualizados_at = datetime.now(timezone.utc)
    verificar_datos_completos(colegiado)
    
    db.commit()
    
    return {"status": "ok", "message": "Datos de estudios actualizados"}


# ============================================================
# ACTUALIZAR DATOS LABORALES
# ============================================================
@router.post("/actualizar/laboral")
async def actualizar_datos_laborales(
    situacion_laboral: str = Form(None),
    centro_trabajo: str = Form(None),
    cargo: str = Form(None),
    ruc_empleador: str = Form(None),
    direccion_trabajo: str = Form(None),
    telefono_trabajo: str = Form(None),
    member: Member = Depends(get_current_member),
    db: Session = Depends(get_db)
):
    """Actualiza datos laborales del colegiado"""
    colegiado = buscar_colegiado_de_member(member, db)
    
    if not colegiado:
        raise HTTPException(404, "Colegiado no encontrado")
    
    if situacion_laboral is not None:
        colegiado.situacion_laboral = situacion_laboral if situacion_laboral else None
    if centro_trabajo is not None:
        colegiado.centro_trabajo = centro_trabajo.strip() if centro_trabajo else None
    if cargo is not None:
        colegiado.cargo = cargo.strip() if cargo else None
    if ruc_empleador is not None:
        colegiado.ruc_empleador = ruc_empleador.strip() if ruc_empleador else None
    if direccion_trabajo is not None:
        colegiado.direccion_trabajo = direccion_trabajo.strip() if direccion_trabajo else None
    if telefono_trabajo is not None:
        colegiado.telefono_trabajo = telefono_trabajo.strip() if telefono_trabajo else None
    
    colegiado.datos_actualizados_at = datetime.now(timezone.utc)
    verificar_datos_completos(colegiado)
    
    db.commit()
    
    return {"status": "ok", "message": "Datos laborales actualizados"}


# ============================================================
# ACTUALIZAR DATOS FAMILIARES
# ============================================================
@router.post("/actualizar/familiar")
async def actualizar_datos_familiares(
    nombre_conyuge: str = Form(None),
    cantidad_hijos: int = Form(None),
    contacto_emergencia_nombre: str = Form(None),
    contacto_emergencia_telefono: str = Form(None),
    contacto_emergencia_parentesco: str = Form(None),
    member: Member = Depends(get_current_member),
    db: Session = Depends(get_db)
):
    """Actualiza datos familiares del colegiado"""
    colegiado = buscar_colegiado_de_member(member, db)
    
    if not colegiado:
        raise HTTPException(404, "Colegiado no encontrado")
    
    if nombre_conyuge is not None:
        colegiado.nombre_conyuge = nombre_conyuge.strip() if nombre_conyuge else None
    if cantidad_hijos is not None:
        colegiado.cantidad_hijos = cantidad_hijos
    if contacto_emergencia_nombre is not None:
        colegiado.contacto_emergencia_nombre = contacto_emergencia_nombre.strip() if contacto_emergencia_nombre else None
    if contacto_emergencia_telefono is not None:
        colegiado.contacto_emergencia_telefono = contacto_emergencia_telefono.strip() if contacto_emergencia_telefono else None
    if contacto_emergencia_parentesco is not None:
        colegiado.contacto_emergencia_parentesco = contacto_emergencia_parentesco.strip() if contacto_emergencia_parentesco else None
    
    colegiado.datos_actualizados_at = datetime.now(timezone.utc)
    verificar_datos_completos(colegiado)
    
    db.commit()
    
    return {"status": "ok", "message": "Datos familiares actualizados"}


# ============================================================
# ACTUALIZAR REDES SOCIALES
# ============================================================
@router.post("/actualizar/redes")
async def actualizar_redes_sociales(
    sitio_web: str = Form(None),
    linkedin: str = Form(None),
    facebook: str = Form(None),
    instagram: str = Form(None),
    member: Member = Depends(get_current_member),
    db: Session = Depends(get_db)
):
    """Actualiza redes sociales del colegiado"""
    colegiado = buscar_colegiado_de_member(member, db)
    
    if not colegiado:
        raise HTTPException(404, "Colegiado no encontrado")
    
    if sitio_web is not None:
        colegiado.sitio_web = sitio_web.strip() if sitio_web else None
    if linkedin is not None:
        colegiado.linkedin = linkedin.strip() if linkedin else None
    if facebook is not None:
        colegiado.facebook = facebook.strip() if facebook else None
    if instagram is not None:
        colegiado.instagram = instagram.strip() if instagram else None
    
    colegiado.datos_actualizados_at = datetime.now(timezone.utc)
    
    db.commit()
    
    return {"status": "ok", "message": "Redes sociales actualizadas"}


# ============================================================
# ACTUALIZAR TODO (Para formulario completo)
# ============================================================
@router.post("/actualizar")
async def actualizar_todos_los_datos(
    request: Request,
    # Personales
    email: str = Form(None),
    telefono: str = Form(None),
    direccion: str = Form(None),
    fecha_nacimiento: str = Form(None),
    lugar_nacimiento: str = Form(None),
    estado_civil: str = Form(None),
    tipo_sangre: str = Form(None),
    # Estudios
    universidad: str = Form(None),
    fecha_titulo: str = Form(None),
    grado_academico: str = Form(None),
    especialidad: str = Form(None),
    # Laborales
    situacion_laboral: str = Form(None),
    centro_trabajo: str = Form(None),
    cargo: str = Form(None),
    ruc_empleador: str = Form(None),
    direccion_trabajo: str = Form(None),
    telefono_trabajo: str = Form(None),
    # Familiares
    nombre_conyuge: str = Form(None),
    cantidad_hijos: int = Form(0),
    contacto_emergencia_nombre: str = Form(None),
    contacto_emergencia_telefono: str = Form(None),
    contacto_emergencia_parentesco: str = Form(None),
    # Redes
    sitio_web: str = Form(None),
    linkedin: str = Form(None),
    facebook: str = Form(None),
    instagram: str = Form(None),
    tiktok: str = Form(None),
    # Foto
    foto: UploadFile = File(None),
    member: Member = Depends(get_current_member),
    db: Session = Depends(get_db)
):
    """Actualiza todos los datos del colegiado de una vez"""
    colegiado = buscar_colegiado_de_member(member, db)
    
    if not colegiado:
        raise HTTPException(404, "Colegiado no encontrado")
    
    # === PERSONALES ===
    if email is not None:
        colegiado.email = email.strip() if email else None
    if telefono is not None:
        colegiado.telefono = telefono.strip() if telefono else None
    if direccion is not None:
        colegiado.direccion = direccion.strip() if direccion else None
    if fecha_nacimiento:
        try:
            colegiado.fecha_nacimiento = datetime.strptime(fecha_nacimiento, "%Y-%m-%d").date()
        except:
            pass
    if lugar_nacimiento is not None:
        colegiado.lugar_nacimiento = lugar_nacimiento.strip() if lugar_nacimiento else None
    if estado_civil is not None:
        colegiado.estado_civil = estado_civil if estado_civil else None
    if tipo_sangre is not None:
        colegiado.tipo_sangre = tipo_sangre if tipo_sangre else None
    
    # === ESTUDIOS ===
    if universidad is not None:
        colegiado.universidad = universidad.strip() if universidad else None
    if fecha_titulo:
        try:
            colegiado.fecha_titulo = datetime.strptime(fecha_titulo, "%Y-%m-%d").date()
        except:
            pass
    if grado_academico is not None:
        colegiado.grado_academico = grado_academico if grado_academico else None
    if especialidad is not None:
        colegiado.especialidad = especialidad.strip() if especialidad else None
    
    # === LABORALES ===
    if situacion_laboral is not None:
        colegiado.situacion_laboral = situacion_laboral if situacion_laboral else None
    if centro_trabajo is not None:
        colegiado.centro_trabajo = centro_trabajo.strip() if centro_trabajo else None
    if cargo is not None:
        colegiado.cargo = cargo.strip() if cargo else None
    if ruc_empleador is not None:
        colegiado.ruc_empleador = ruc_empleador.strip() if ruc_empleador else None
    if direccion_trabajo is not None:
        colegiado.direccion_trabajo = direccion_trabajo.strip() if direccion_trabajo else None
    if telefono_trabajo is not None:
        colegiado.telefono_trabajo = telefono_trabajo.strip() if telefono_trabajo else None
    
    # === FAMILIARES ===
    if nombre_conyuge is not None:
        colegiado.nombre_conyuge = nombre_conyuge.strip() if nombre_conyuge else None
    if cantidad_hijos is not None:
        colegiado.cantidad_hijos = cantidad_hijos
    if contacto_emergencia_nombre is not None:
        colegiado.contacto_emergencia_nombre = contacto_emergencia_nombre.strip() if contacto_emergencia_nombre else None
    if contacto_emergencia_telefono is not None:
        colegiado.contacto_emergencia_telefono = contacto_emergencia_telefono.strip() if contacto_emergencia_telefono else None
    if contacto_emergencia_parentesco is not None:
        colegiado.contacto_emergencia_parentesco = contacto_emergencia_parentesco.strip() if contacto_emergencia_parentesco else None
    
    # === REDES ===
    if sitio_web is not None:
        colegiado.sitio_web = sitio_web.strip() if sitio_web else None
    if linkedin is not None:
        colegiado.linkedin = linkedin.strip() if linkedin else None
    if facebook is not None:
        colegiado.facebook = facebook.strip() if facebook else None
    if instagram is not None:
        colegiado.instagram = instagram.strip() if instagram else None
    if tiktok is not None:
        colegiado.tiktok = tiktok.strip() if tiktok else None    
    
    # === FOTO ===
    if foto and foto.filename:
        foto_url = await guardar_foto(foto, colegiado.organization_id, colegiado.id)
        if foto_url:
            colegiado.foto_url = foto_url
    
    # === META ===
    colegiado.datos_actualizados_at = datetime.now(timezone.utc)
    verificar_datos_completos(colegiado)
    
    db.commit()
    
    return {"status": "ok", "message": "Datos actualizados correctamente", "datos_completos": colegiado.datos_completos}


# ============================================================
# FUNCIONES AUXILIARES
# ============================================================

from app.utils.gcs import upload_foto_perfil

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
        
        return upload_foto_perfil(content, content_type_map.get(ext, 'image/jpeg'), organization_id, colegiado_id)
    except Exception as e:
        print(f"⚠️ Error guardando foto: {e}")
        return None


def verificar_datos_completos(colegiado) -> bool:
    """Verifica si el colegiado tiene todos los datos mínimos requeridos"""
    campos_requeridos = [
        colegiado.email,
        colegiado.telefono,
        colegiado.direccion,
        getattr(colegiado, 'fecha_nacimiento', None),
        getattr(colegiado, 'universidad', None),
        getattr(colegiado, 'situacion_laboral', None),
        getattr(colegiado, 'contacto_emergencia_nombre', None),
        getattr(colegiado, 'contacto_emergencia_telefono', None)
    ]
    
    es_completo = all(campo is not None and str(campo).strip() != '' for campo in campos_requeridos)
    colegiado.datos_completos = es_completo
    return es_completo


# ============================================================
# ESTADÍSTICAS DE ACTUALIZACIÓN (Para Admin)
# ============================================================
@router.get("/admin/estadisticas-actualizacion")
async def estadisticas_actualizacion(
    member: Member = Depends(get_current_member),
    db: Session = Depends(get_db)
):
    """Estadísticas de actualización de fichas (solo admin)"""
    # Verificar si es admin
    if member.role not in ['admin', 'superadmin']:
        raise HTTPException(403, "No autorizado")
    
    total = db.query(Colegiado).filter(
        Colegiado.organization_id == member.organization_id
    ).count()
    
    completos = db.query(Colegiado).filter(
        Colegiado.organization_id == member.organization_id,
        Colegiado.datos_completos == True
    ).count()
    
    con_email = db.query(Colegiado).filter(
        Colegiado.organization_id == member.organization_id,
        Colegiado.email.isnot(None),
        Colegiado.email != ''
    ).count()
    
    con_telefono = db.query(Colegiado).filter(
        Colegiado.organization_id == member.organization_id,
        Colegiado.telefono.isnot(None),
        Colegiado.telefono != ''
    ).count()
    
    return {
        "total_colegiados": total,
        "fichas_completas": completos,
        "porcentaje_completo": round((completos / total * 100), 1) if total > 0 else 0,
        "con_email": con_email,
        "con_telefono": con_telefono,
        "sin_actualizar": total - completos
    }
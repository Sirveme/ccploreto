"""
Router: Configuración Admin
===========================
Endpoints para el panel de configuración del colegio
y métricas para el Agente Consejero
"""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import text, func
from datetime import datetime, timezone, date
from typing import Optional
import json

from app.database import get_db
from app.models import Organization, Member, Colegiado, Payment, Debt
# from app.utils.gcs import upload_to_gcs  # Si usas Google Cloud Storage

router = APIRouter(prefix="/api/admin", tags=["admin-config"])


# ============================================================
# HELPER: Obtener admin actual
# ============================================================

async def get_current_admin(request, db: Session):
    """Verifica que el usuario sea admin y retorna su info"""
    # Implementar según tu sistema de auth
    # Por ahora, ejemplo básico
    member = getattr(request.state, 'member', None)
    if not member:
        raise HTTPException(status_code=401, detail="No autenticado")
    
    # Verificar rol admin
    # if member.role not in ['admin', 'superadmin']:
    #     raise HTTPException(status_code=403, detail="No autorizado")
    
    return member


# ============================================================
# ENDPOINT: Obtener Métricas (para Agente Consejero)
# ============================================================

@router.get("/metricas")
async def get_metricas(
    db: Session = Depends(get_db)
):
    """
    Retorna métricas del colegio para el Agente Consejero.
    Analiza datos reales y permite generar insights.
    """
    
    # Por ahora, obtenemos org_id del primer colegio (ajustar según tu multi-tenant)
    org_id = 1  # TODO: obtener de la sesión
    
    # Total colegiados
    total_colegiados = db.query(func.count(Colegiado.id)).filter(
        Colegiado.organization_id == org_id
    ).scalar() or 0
    
    # Colegiados hábiles
    habiles = db.query(func.count(Colegiado.id)).filter(
        Colegiado.organization_id == org_id,
        Colegiado.condicion == 'habil'
    ).scalar() or 0
    
    # Colegiados con deuda (morosos)
    morosos = db.query(func.count(func.distinct(Debt.colegiado_id))).filter(
        Debt.status.in_(['pending', 'partial'])
    ).scalar() or 0
    
    # Porcentaje de habilidad
    porcentaje_habiles = round((habiles / total_colegiados * 100), 1) if total_colegiados > 0 else 0
    
    # Recaudado este mes
    primer_dia_mes = date.today().replace(day=1)
    recaudado_mes = db.query(func.coalesce(func.sum(Payment.amount), 0)).filter(
        Payment.organization_id == org_id,
        Payment.status == 'approved',
        Payment.created_at >= primer_dia_mes
    ).scalar() or 0
    
    # Pagos pendientes de validar
    pagos_pendientes = db.query(func.count(Payment.id)).filter(
        Payment.organization_id == org_id,
        Payment.status == 'review'
    ).scalar() or 0
    
    # Certificados emitidos este mes (si tienes tabla de constancias)
    certificados_emitidos = db.execute(
        text("""
            SELECT COUNT(*) FROM constancias 
            WHERE organization_id = :org_id 
            AND fecha_emision >= :fecha
        """),
        {"org_id": org_id, "fecha": primer_dia_mes}
    ).scalar() or 0
    
    # Nuevos colegiados este mes
    nuevos_colegiados = db.query(func.count(Colegiado.id)).filter(
        Colegiado.organization_id == org_id,
        Colegiado.created_at >= primer_dia_mes
    ).scalar() or 0
    
    # Meta del mes (desde config o valor por defecto)
    # meta_mes = get_org_config(db, org_id, 'meta_recaudacion_mensual', 24000)
    meta_mes = 24000  # Por ahora fijo, después desde config
    
    return JSONResponse({
        "total_colegiados": total_colegiados,
        "habiles": habiles,
        "morosos": morosos,
        "porcentaje_habiles": porcentaje_habiles,
        "porcentaje_morosos": round(100 - porcentaje_habiles, 1),
        "recaudado_mes": float(recaudado_mes),
        "meta_mes": meta_mes,
        "pagos_pendientes": pagos_pendientes,
        "certificados_emitidos": certificados_emitidos,
        "nuevos_colegiados": nuevos_colegiados,
        "fecha_actualizacion": datetime.now(timezone.utc).isoformat()
    })


# ============================================================
# ENDPOINT: Obtener Configuración
# ============================================================

@router.get("/config")
async def get_config(
    db: Session = Depends(get_db)
):
    """Obtiene toda la configuración del colegio"""
    
    org_id = 1  # TODO: obtener de la sesión
    
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organización no encontrada")
    
    # La config está en el campo JSON 'config' de organizations
    config = org.config if hasattr(org, 'config') and org.config else {}
    
    return JSONResponse({
        "organization": {
            "id": org.id,
            "name": org.name,
            "slug": org.slug
        },
        "config": config
    })


# ============================================================
# ENDPOINT: Guardar Configuración
# ============================================================

@router.post("/config")
async def save_config(
    data: dict,
    db: Session = Depends(get_db)
):
    """
    Guarda configuración de una sección específica.
    Merge con la configuración existente.
    """
    
    org_id = 1  # TODO: obtener de la sesión
    
    seccion = data.get('seccion')
    new_config = data.get('config', {})
    
    if not seccion:
        raise HTTPException(status_code=400, detail="Sección requerida")
    
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organización no encontrada")
    
    # Obtener config actual o inicializar
    current_config = org.config if hasattr(org, 'config') and org.config else {}
    
    # Merge: actualizar solo la sección específica
    if seccion not in current_config:
        current_config[seccion] = {}
    
    current_config[seccion].update(new_config)
    current_config['_updated_at'] = datetime.now(timezone.utc).isoformat()
    current_config['_updated_section'] = seccion
    
    # Guardar
    org.config = current_config
    db.commit()
    
    return JSONResponse({
        "success": True,
        "seccion": seccion,
        "mensaje": f"Configuración de {seccion} guardada correctamente"
    })


# ============================================================
# ENDPOINT: Subir Archivo (logo, firma)
# ============================================================

@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    tipo: str = Form(...),
    db: Session = Depends(get_db)
):
    """
    Sube archivos de configuración (logos, firmas).
    Almacena en GCS o sistema de archivos local.
    """
    
    org_id = 1  # TODO: obtener de la sesión
    
    # Validar tipo de archivo
    allowed_types = ['image/png', 'image/jpeg', 'image/webp', 'image/gif']
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="Tipo de archivo no permitido")
    
    # Validar tamaño (max 2MB)
    contents = await file.read()
    if len(contents) > 2 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Archivo muy grande (max 2MB)")
    
    # Generar nombre único
    extension = file.filename.split('.')[-1] if '.' in file.filename else 'png'
    filename = f"org_{org_id}/{tipo}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{extension}"
    
    # Subir a GCS (o guardar localmente)
    try:
        # Si usas GCS:
        # url = await upload_to_gcs(contents, filename, file.content_type)
        
        # Versión local (para desarrollo):
        import os
        upload_dir = f"app/static/uploads/org_{org_id}"
        os.makedirs(upload_dir, exist_ok=True)
        
        filepath = f"{upload_dir}/{tipo}.{extension}"
        with open(filepath, 'wb') as f:
            f.write(contents)
        
        url = f"/static/uploads/org_{org_id}/{tipo}.{extension}"
        
        # Actualizar config con la URL
        org = db.query(Organization).filter(Organization.id == org_id).first()
        if org:
            config = org.config or {}
            config[f'{tipo}_url'] = url
            org.config = config
            db.commit()
        
        return JSONResponse({
            "success": True,
            "url": url,
            "tipo": tipo
        })
        
    except Exception as e:
        print(f"[Upload Error] {e}")
        raise HTTPException(status_code=500, detail="Error al subir archivo")


# ============================================================
# ENDPOINT: Obtener Estadísticas del Dashboard
# ============================================================

@router.get("/stats")
async def get_stats(
    db: Session = Depends(get_db)
):
    """
    Estadísticas rápidas para las métricas del header.
    Optimizado para carga rápida.
    """
    
    org_id = 1
    
    # Query optimizada
    stats = db.execute(
        text("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN condicion = 'habil' THEN 1 ELSE 0 END) as habiles
            FROM colegiados 
            WHERE organization_id = :org_id
        """),
        {"org_id": org_id}
    ).fetchone()
    
    total = stats[0] or 0
    habiles = stats[1] or 0
    morosos = total - habiles
    
    # Recaudación del mes
    primer_dia = date.today().replace(day=1)
    recaudado = db.query(func.coalesce(func.sum(Payment.amount), 0)).filter(
        Payment.organization_id == org_id,
        Payment.status == 'approved',
        Payment.created_at >= primer_dia
    ).scalar() or 0
    
    # Pagos pendientes
    pendientes = db.query(func.count(Payment.id)).filter(
        Payment.organization_id == org_id,
        Payment.status == 'review'
    ).scalar() or 0
    
    return {
        "total_colegiados": total,
        "habiles": habiles,
        "morosos": morosos,
        "porcentaje_habiles": round(habiles / total * 100, 1) if total > 0 else 0,
        "porcentaje_morosos": round(morosos / total * 100, 1) if total > 0 else 0,
        "recaudado_mes": float(recaudado),
        "pagos_pendientes": pendientes
    }


# ============================================================
# HELPER: Obtener config específica de organización
# ============================================================

def get_org_config(db: Session, org_id: int, key: str, default=None):
    """Helper para obtener un valor específico de la config"""
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org or not org.config:
        return default
    
    # Soporta keys anidadas como "finanzas.cuota_mensual"
    parts = key.split('.')
    value = org.config
    
    for part in parts:
        if isinstance(value, dict) and part in value:
            value = value[part]
        else:
            return default
    
    return value
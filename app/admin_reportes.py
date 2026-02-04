"""
Router: Reportes de Verificaciones (Solo Admin)
===============================================
"""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.database import get_db
from app.routers.dashboard import get_current_member

router = APIRouter(prefix="/api/admin/reportes", tags=["admin_reportes"])


@router.get("/verificaciones/por-certificado")
async def verificaciones_por_certificado(
    member = Depends(get_current_member),
    db: Session = Depends(get_db)
):
    """¿Cuántas veces se ha verificado cada certificado?"""
    
    if not member.is_admin:
        return JSONResponse({"error": "No autorizado"}, status_code=403)
    
    resultados = db.execute(text("""
        SELECT 
            c.codigo_verificacion,
            c.nombres || ' ' || c.apellidos AS colegiado,
            COUNT(v.id) as total_verificaciones,
            MAX(v.fecha_verificacion) as ultima_verificacion
        FROM certificados_emitidos c
        LEFT JOIN verificaciones_log v ON v.certificado_id = c.id
        GROUP BY c.id, c.codigo_verificacion, c.nombres, c.apellidos
        ORDER BY total_verificaciones DESC
        LIMIT 50
    """)).fetchall()
    
    return JSONResponse({
        "data": [
            {
                "codigo": r.codigo_verificacion,
                "colegiado": r.colegiado,
                "verificaciones": r.total_verificaciones,
                "ultima": r.ultima_verificacion.isoformat() if r.ultima_verificacion else None
            }
            for r in resultados
        ]
    })


@router.get("/verificaciones/intentos-fallidos")
async def intentos_fallidos(
    member = Depends(get_current_member),
    db: Session = Depends(get_db)
):
    """Intentos fallidos (posibles fraudes)"""
    
    if not member.is_admin:
        return JSONResponse({"error": "No autorizado"}, status_code=403)
    
    resultados = db.execute(text("""
        SELECT 
            codigo_ingresado,
            codigo_seguridad_ingresado,
            motivo_fallo,
            ip_origen,
            fecha_verificacion
        FROM verificaciones_log 
        WHERE verificacion_exitosa = FALSE
        ORDER BY fecha_verificacion DESC
        LIMIT 100
    """)).fetchall()
    
    return JSONResponse({
        "data": [
            {
                "codigo": r.codigo_ingresado,
                "seguridad_ingresado": r.codigo_seguridad_ingresado,
                "motivo": r.motivo_fallo,
                "ip": r.ip_origen,
                "fecha": r.fecha_verificacion.isoformat()
            }
            for r in resultados
        ]
    })


@router.get("/verificaciones/por-dia")
async def verificaciones_por_dia(
    dias: int = 30,
    member = Depends(get_current_member),
    db: Session = Depends(get_db)
):
    """Verificaciones por día"""
    
    if not member.is_admin:
        return JSONResponse({"error": "No autorizado"}, status_code=403)
    
    resultados = db.execute(text("""
        SELECT 
            DATE(fecha_verificacion) as fecha,
            COUNT(*) as total,
            SUM(CASE WHEN verificacion_exitosa THEN 1 ELSE 0 END) as exitosas
        FROM verificaciones_log 
        WHERE fecha_verificacion > NOW() - INTERVAL :dias
        GROUP BY DATE(fecha_verificacion)
        ORDER BY fecha DESC
    """), {"dias": f"{dias} days"}).fetchall()
    
    return JSONResponse({
        "data": [
            {
                "fecha": r.fecha.isoformat(),
                "total": r.total,
                "exitosas": r.exitosas
            }
            for r in resultados
        ]
    })


@router.get("/verificaciones/ips-sospechosas")
async def ips_sospechosas(
    member = Depends(get_current_member),
    db: Session = Depends(get_db)
):
    """IPs con muchos intentos fallidos (posible fraude)"""
    
    if not member.is_admin:
        return JSONResponse({"error": "No autorizado"}, status_code=403)
    
    resultados = db.execute(text("""
        SELECT 
            ip_origen,
            COUNT(*) as total_intentos,
            SUM(CASE WHEN NOT verificacion_exitosa THEN 1 ELSE 0 END) as fallidos,
            MAX(fecha_verificacion) as ultimo_intento
        FROM verificaciones_log
        WHERE fecha_verificacion > NOW() - INTERVAL '7 days'
        GROUP BY ip_origen
        HAVING SUM(CASE WHEN NOT verificacion_exitosa THEN 1 ELSE 0 END) > 5
        ORDER BY fallidos DESC
    """)).fetchall()
    
    return JSONResponse({
        "alerta": "IPs con más de 5 intentos fallidos en 7 días",
        "data": [
            {
                "ip": r.ip_origen,
                "total_intentos": r.total_intentos,
                "fallidos": r.fallidos,
                "ultimo": r.ultimo_intento.isoformat()
            }
            for r in resultados
        ]
    })
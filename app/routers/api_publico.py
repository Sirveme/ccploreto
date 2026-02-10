"""
API Pública - Endpoints sin autenticación
Para integración con colegiospro.org.pe y otros servicios
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import date

from app.database import get_db

router = APIRouter(prefix="/api/publico", tags=["API Pública"])


@router.get("/certificado/{codigo}")
async def verificar_certificado_publico(codigo: str, db: Session = Depends(get_db)):
    """
    Verifica un certificado de habilidad.
    Endpoint público para colegiospro.org.pe
    """
    
    result = db.execute(
        text("""
            SELECT 
                c.codigo_verificacion,
                c.nombres,
                c.apellidos,
                c.matricula,
                c.fecha_emision,
                c.fecha_vigencia_hasta,
                c.en_fraccionamiento,
                c.estado,
                o.name as colegio_nombre,
                o.slug as colegio_slug,
                CASE 
                    WHEN c.estado = 'anulado' THEN 'ANULADO'
                    WHEN c.fecha_vigencia_hasta < CURRENT_DATE THEN 'VENCIDO'
                    ELSE 'VIGENTE'
                END AS estado_actual
            FROM certificados_emitidos c
            JOIN colegiados col ON c.colegiado_id = col.id
            JOIN organizations o ON col.organization_id = o.id
            WHERE c.codigo_verificacion = :codigo
        """),
        {"codigo": codigo}
    ).fetchone()
    
    if not result:
        return JSONResponse({
            "encontrado": False,
            "mensaje": "Certificado no encontrado en el sistema"
        }, status_code=404)
    
    es_vigente = result.estado_actual == 'VIGENTE'
    
    return JSONResponse({
        "encontrado": True,
        "vigente": es_vigente,
        "certificado": {
            "codigo": result.codigo_verificacion,
            "profesional": f"CPC. {result.nombres} {result.apellidos}",
            "matricula": result.matricula,
            "colegio": result.colegio_nombre,
            "colegio_slug": result.colegio_slug,
            "fecha_emision": result.fecha_emision.isoformat() if result.fecha_emision else None,
            "vigencia_hasta": result.fecha_vigencia_hasta.isoformat() if result.fecha_vigencia_hasta else None,
            "estado": result.estado_actual,
            "en_fraccionamiento": result.en_fraccionamiento or False
        },
        "mensaje": "Certificado válido y vigente" if es_vigente else f"Certificado {result.estado_actual}"
    })


@router.get("/colegiado/habilidad/{matricula}")
async def verificar_habilidad_colegiado(matricula: str, db: Session = Depends(get_db)):
    """
    Verifica si un colegiado está hábil por su matrícula.
    Endpoint público.
    """
    
    result = db.execute(
        text("""
            SELECT 
                c.codigo_matricula,
                c.apellidos_nombres,
                c.condicion,
                o.name as colegio_nombre
            FROM colegiados c
            JOIN organizations o ON c.organization_id = o.id
            WHERE c.codigo_matricula = :matricula
              AND c.estado = 'activo'
        """),
        {"matricula": matricula}
    ).fetchone()
    
    if not result:
        return JSONResponse({
            "encontrado": False,
            "mensaje": "Colegiado no encontrado"
        }, status_code=404)
    
    es_habil = result.condicion == 'habil'
    
    return JSONResponse({
        "encontrado": True,
        "habil": es_habil,
        "colegiado": {
            "matricula": result.codigo_matricula,
            "nombre": result.apellidos_nombres,
            "condicion": result.condicion,
            "colegio": result.colegio_nombre
        },
        "mensaje": "Colegiado HÁBIL" if es_habil else f"Colegiado {result.condicion.upper()}"
    })
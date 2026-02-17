"""
Router: Verificación Pública de Certificados
=============================================
NO requiere autenticación
Registra cada intento de verificación
"""

from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse, HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import date

from app.database import get_db

router = APIRouter(prefix="/verificar", tags=["verificacion_publica"])


@router.get("/ccpl")
async def verificar_certificado_ccpl(
    codigo: str = None,
    seguridad: str = None,
    request: Request = None,
    db: Session = Depends(get_db)
):
    """
    Verificación pública de certificado CCPL.
    """
    
    # Capturar datos del visitante
    ip_origen = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent", "")
    referer = request.headers.get("referer", "")
    
    # Validar que vengan los parámetros
    if not codigo or not seguridad:
        return JSONResponse({
            "valido": False,
            "mensaje": "Debe proporcionar código y código de seguridad",
            "instrucciones": "Use: /verificar/ccpl?codigo=XXXX-XXXXXXX&seguridad=XXXX-XXXX-XXXX"
        }, status_code=400)
    
    # Buscar certificado por código correlativo
    cert = db.execute(
        text("""
            SELECT 
                id, codigo_verificacion, codigo_seguridad,
                nombres, apellidos, matricula,
                fecha_emision, fecha_vigencia_hasta,
                estado
            FROM certificados_emitidos 
            WHERE codigo_verificacion = :codigo
        """),
        {"codigo": codigo}
    ).fetchone()
    
    # Determinar resultado
    if not cert:
        exito = False
        motivo = "codigo_no_existe"
        mensaje = "Constancia no encontrada. Verifique el código ingresado."
        datos_certificado = None
        
    elif cert.codigo_seguridad is None:
        # Certificado antiguo (antes del sistema de seguridad)
        if cert.estado == "anulado":
            exito = False
            motivo = "certificado_anulado"
            mensaje = "Esta constancia ha sido ANULADA."
            datos_certificado = None
        elif cert.fecha_vigencia_hasta < date.today():
            exito = True
            motivo = "certificado_vencido"
            mensaje = "Constancia auténtica pero VENCIDA (emitida antes del sistema de seguridad)."
            datos_certificado = {
                "nombre": f"CPC. {cert.nombres} {cert.apellidos}",
                "matricula": cert.matricula,
                "estado": "VENCIDO",
                "vigente_hasta": cert.fecha_vigencia_hasta.isoformat(),
                "fecha_emision": cert.fecha_emision.isoformat()
            }
        else:
            exito = True
            motivo = None
            mensaje = "Constancia válida (emitida antes del sistema de seguridad)."
            datos_certificado = {
                "nombre": f"CPC. {cert.nombres} {cert.apellidos}",
                "matricula": cert.matricula,
                "estado": "HÁBIL",
                "vigente_hasta": cert.fecha_vigencia_hasta.isoformat(),
                "fecha_emision": cert.fecha_emision.isoformat()
            }
    
    else:
        # Certificado con código de seguridad - normalizar y comparar
        db_code = cert.codigo_seguridad.upper().replace("-", "").replace(" ", "")
        input_code = seguridad.upper().replace("-", "").replace(" ", "")
        
        # DEBUG - eliminar después
        #print(f"DEBUG: BD=[{db_code}] INPUT=[{input_code}] IGUALES={db_code == input_code}")
        
        if db_code != input_code:
            exito = False
            motivo = "seguridad_incorrecta"
            mensaje = "Código de seguridad incorrecto."
            datos_certificado = None
            
        elif cert.estado == "anulado":
            exito = False
            motivo = "certificado_anulado"
            mensaje = "Esta constancia ha sido ANULADA."
            datos_certificado = None
            
        elif cert.fecha_vigencia_hasta < date.today():
            exito = True
            motivo = "certificado_vencido"
            mensaje = "Constancia auténtica pero VENCIDA."
            datos_certificado = {
                "nombre": f"CPC. {cert.nombres} {cert.apellidos}",
                "matricula": cert.matricula,
                "estado": "VENCIDO",
                "vigente_hasta": cert.fecha_vigencia_hasta.isoformat(),
                "fecha_emision": cert.fecha_emision.isoformat()
            }
        else:
            exito = True
            motivo = None
            mensaje = "Constancia VÁLIDA y VIGENTE."
            datos_certificado = {
                "nombre": f"CPC. {cert.nombres} {cert.apellidos}",
                "matricula": cert.matricula,
                "estado": "HÁBIL",
                "vigente_hasta": cert.fecha_vigencia_hasta.isoformat(),
                "fecha_emision": cert.fecha_emision.isoformat()
            }
    
    # REGISTRAR VERIFICACIÓN
    db.execute(
        text("""
            INSERT INTO verificaciones_log (
                certificado_id, 
                codigo_ingresado, 
                codigo_seguridad_ingresado,
                verificacion_exitosa, 
                motivo_fallo,
                ip_origen, 
                user_agent, 
                referer
            ) VALUES (
                :cert_id, :codigo, :seguridad,
                :exito, :motivo,
                :ip, :ua, :ref
            )
        """),
        {
            "cert_id": cert.id if cert else None,
            "codigo": codigo,
            "seguridad": seguridad,
            "exito": exito,
            "motivo": motivo,
            "ip": ip_origen,
            "ua": user_agent[:500] if user_agent else None,
            "ref": referer[:500] if referer else None
        }
    )
    db.commit()
    
    # Respuesta JSON
    respuesta = {
        "valido": exito and motivo is None,
        "autentico": exito,
        "mensaje": mensaje,
        "codigo": codigo
    }
    
    if datos_certificado:
        respuesta["certificado"] = datos_certificado
    
    return JSONResponse(respuesta)


@router.get("/ccpl/estadisticas")
async def estadisticas_verificaciones(
    db: Session = Depends(get_db)
):
    """
    Estadísticas públicas (sin datos sensibles).
    """
    stats = db.execute(text("""
        SELECT 
            COUNT(*) as total_verificaciones,
            SUM(CASE WHEN verificacion_exitosa THEN 1 ELSE 0 END) as exitosas,
            SUM(CASE WHEN NOT verificacion_exitosa THEN 1 ELSE 0 END) as fallidas,
            COUNT(DISTINCT certificado_id) as certificados_unicos_verificados
        FROM verificaciones_log
        WHERE fecha_verificacion > NOW() - INTERVAL '30 days'
    """)).fetchone()
    
    return JSONResponse({
        "periodo": "últimos 30 días",
        "total_verificaciones": stats.total_verificaciones or 0,
        "exitosas": stats.exitosas or 0,
        "fallidas": stats.fallidas or 0,
        "certificados_verificados": stats.certificados_unicos_verificados or 0
    })
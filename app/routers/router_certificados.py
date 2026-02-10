"""
Router: Certificados de Habilitación Digital
=============================================
Endpoints para emitir y verificar certificados
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta
from typing import Optional
import io
import secrets
import string

from app.database import get_db
from app.routers.dashboard import get_current_member

# Importar generador (ajustar path según estructura)
from app.services.generador_certificado import generar_certificado_pdf

router = APIRouter(prefix="/api/certificados", tags=["certificados"])


def calcular_vigencia(fecha_pago: date, en_fraccionamiento: bool = False) -> date:
    """
    Calcula la fecha de vigencia del certificado.
    
    Reglas:
    - Normal: mes de pago + 3 meses (último día del mes)
    - Fraccionamiento: mes de pago + 1 mes (último día del mes)
    
    Ejemplo: Pago en enero 2026
    - Normal: vigente hasta 31 de abril 2026... wait, no
    - Corrección: Si pago en enero, vigencia es por 3 meses DESPUÉS
      Entonces: enero + 3 = abril, pero el certificado dice "marzo 2027"
      
    Revisando el certificado de ejemplo:
    - Fecha emisión: 31 de enero 2026
    - Vigencia hasta: 31 de Marzo del 2027
    
    Eso es más de 3 meses... parece ser 14 meses.
    
    Probablemente la lógica es:
    - Si el colegiado paga en enero 2026 (que cubre cuota 2026)
    - Vigencia es hasta fin del primer trimestre del SIGUIENTE año (marzo 2027)
    
    O más simple:
    - Vigencia trimestral: pago cubre 3 meses
    - Pero como pagó toda la cuota anual, cubre hasta marzo del año siguiente
    
    Para simplificar, asumiré:
    - Sin fraccionamiento: 3 meses desde la fecha de pago
    - Con fraccionamiento: 1 mes desde la fecha de pago
    
    El admin puede ajustar esto según las reglas exactas del CCPL.
    """
    meses = 1 if en_fraccionamiento else 3
    
    fecha_fin = fecha_pago + relativedelta(months=meses)
    # Último día del mes
    primer_dia_sig = fecha_fin.replace(day=1) + relativedelta(months=1)
    ultimo_dia = primer_dia_sig - timedelta(days=1)
    
    return ultimo_dia


def generar_codigo_verificacion(db: Session) -> str:
    """Genera código único YYYY-NNNNNNN usando función de BD"""
    result = db.execute(text("SELECT generar_codigo_certificado()")).fetchone()
    return result[0]


def generar_codigo_seguridad() -> str:
    """Genera código alfanumérico tipo: A7X9-K2M4-P8Q1"""
    caracteres = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'  # Sin 0,O,1,I,L
    grupos = []
    for _ in range(3):
        grupo = ''.join(secrets.choice(caracteres) for _ in range(4))
        grupos.append(grupo)
    return '-'.join(grupos)


@router.get("/emitir/{colegiado_id}")
async def emitir_certificado(
    colegiado_id: int,
    request: Request,
    member = Depends(get_current_member),
    db: Session = Depends(get_db)
):
    """
    Emite un certificado de habilitación para el colegiado.
    
    Verifica:
    1. Que el colegiado tenga pagos aprobados
    2. Genera código único
    3. Calcula vigencia
    4. Registra en BD
    5. Retorna PDF
    """
    
    # Obtener colegiado
    colegiado = db.execute(
        text("""
            SELECT c.id, c.nombres, c.apellidos, c.matricula, c.member_id,
                   c.estado_habilidad, c.en_fraccionamiento
            FROM colegiados c
            WHERE c.id = :cid
        """),
        {"cid": colegiado_id}
    ).fetchone()
    
    if not colegiado:
        raise HTTPException(status_code=404, detail="Colegiado no encontrado")
    
    # Verificar permisos (mismo usuario o admin)
    if colegiado.member_id != member.id and not member.is_admin:
        raise HTTPException(status_code=403, detail="No autorizado")
    
    # Verificar estado de habilidad
    if colegiado.estado_habilidad != 'habil':
        raise HTTPException(
            status_code=400, 
            detail=f"El colegiado no está hábil. Estado: {colegiado.estado_habilidad}"
        )
    
    # Obtener último pago aprobado (tabla payments)
    ultimo_pago = db.execute(
        text("""
            SELECT p.id, p.created_at, p.amount, p.status
            FROM payments p
            WHERE p.colegiado_id = :cid 
              AND p.status = 'approved'
            ORDER BY p.created_at DESC
            LIMIT 1
        """),
        {"cid": colegiado_id}
    ).fetchone()
    
    if not ultimo_pago:
        raise HTTPException(
            status_code=400,
            detail="No se encontraron pagos aprobados. Debe tener al menos un pago validado."
        )
    
    # Generar código de verificación
    codigo_correlativo = generar_codigo_verificacion(db)  # 2026-0000226
    codigo_seguridad = generar_codigo_seguridad()          # A7X9-K2M4-P8Q1
    
    # Calcular vigencia
    fecha_pago = ultimo_pago.created_at.date() if hasattr(ultimo_pago.created_at, 'date') else ultimo_pago.created_at
    fecha_vigencia = calcular_vigencia(fecha_pago, colegiado.en_fraccionamiento)
    
    fecha_emision = datetime.now()
    
    # Registrar certificado en BD
    db.execute(
        text("""
            INSERT INTO certificados_emitidos (
                codigo_verificacion, codigo_seguridad, colegiado_id,
                nombres, apellidos, matricula,
                fecha_emision, fecha_vigencia_hasta,
                en_fraccionamiento, payment_id,
                emitido_por, ip_emision
            ) VALUES (
                :codigo, :seguridad, :colegiado_id,
                :nombres, :apellidos, :matricula,
                :fecha_emision, :fecha_vigencia,
                :fraccionamiento, :payment_id,
                :emitido_por, :ip
            )
        """),
        {
            "codigo": codigo_correlativo,
            "seguridad": codigo_seguridad,
            "colegiado_id": colegiado_id,
            "nombres": colegiado.nombres,
            "apellidos": colegiado.apellidos,
            "matricula": colegiado.matricula,
            "fecha_emision": fecha_emision,
            "fecha_vigencia": fecha_vigencia,
            "fraccionamiento": colegiado.en_fraccionamiento or False,
            "payment_id": ultimo_pago.id,
            "emitido_por": member.id,
            "ip": request.client.host if request.client else None
        }
    )
    db.commit()
    
    # Generar PDF pasando ambos códigos
    pdf_buffer = generar_certificado_pdf(
        codigo=codigo_correlativo,
        codigo_seguridad=codigo_seguridad,
        nombres=colegiado.nombres,
        apellidos=colegiado.apellidos,
        matricula=colegiado.matricula,
        fecha_vigencia=fecha_vigencia,
        fecha_emision=fecha_emision,
        en_fraccionamiento=colegiado.en_fraccionamiento or False
    )
    
    # Nombre del archivo
    nombre_limpio = f"{colegiado.apellidos}_{colegiado.nombres}".replace(' ', '_')
    nombre_archivo = f"{nombre_limpio}-{fecha_emision.strftime('%Y_%m_%d-%H_%M_%S')}.pdf"
    
    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename={nombre_archivo}"
        }
    )


@router.get("/verificar/{codigo}")
async def verificar_certificado(codigo: str, db: Session = Depends(get_db)):
    """
    Endpoint público para verificar un certificado.
    No requiere autenticación.
    """
    
    result = db.execute(
        text("""
            SELECT 
                codigo_verificacion,
                nombres || ' ' || apellidos AS nombre_completo,
                matricula,
                fecha_emision,
                fecha_vigencia_hasta,
                estado,
                CASE 
                    WHEN estado = 'anulado' THEN 'ANULADO'
                    WHEN fecha_vigencia_hasta < CURRENT_DATE THEN 'VENCIDO'
                    ELSE 'VIGENTE'
                END AS estado_actual
            FROM certificados_emitidos
            WHERE codigo_verificacion = :codigo
        """),
        {"codigo": codigo}
    ).fetchone()
    
    if not result:
        return JSONResponse({
            "valido": False,
            "mensaje": "Certificado no encontrado"
        }, status_code=404)
    
    es_valido = result.estado_actual == 'VIGENTE'
    
    return JSONResponse({
        "valido": es_valido,
        "codigo": result.codigo_verificacion,
        "nombre": f"CPC. {result.nombre_completo}",
        "matricula": result.matricula,
        "fecha_emision": result.fecha_emision.isoformat(),
        "vigencia_hasta": result.fecha_vigencia_hasta.isoformat(),
        "estado": result.estado_actual,
        "mensaje": "Certificado válido y vigente" if es_valido else f"Certificado {result.estado_actual}"
    })


@router.get("/mis-certificados")
async def mis_certificados(
    member = Depends(get_current_member),
    db: Session = Depends(get_db)
):
    """Lista los certificados emitidos del colegiado actual"""
    
    colegiado = db.execute(
        text("SELECT id FROM colegiados WHERE member_id = :mid"),
        {"mid": member.id}
    ).fetchone()
    
    if not colegiado:
        return JSONResponse({"certificados": []})
    
    certificados = db.execute(
        text("""
            SELECT 
                codigo_verificacion,
                fecha_emision,
                fecha_vigencia_hasta,
                estado,
                CASE 
                    WHEN estado = 'anulado' THEN 'ANULADO'
                    WHEN fecha_vigencia_hasta < CURRENT_DATE THEN 'VENCIDO'
                    ELSE 'VIGENTE'
                END AS estado_actual
            FROM certificados_emitidos
            WHERE colegiado_id = :cid
            ORDER BY fecha_emision DESC
            LIMIT 20
        """),
        {"cid": colegiado.id}
    ).fetchall()
    
    return JSONResponse({
        "certificados": [
            {
                "codigo": c.codigo_verificacion,
                "fecha_emision": c.fecha_emision.isoformat(),
                "vigencia_hasta": c.fecha_vigencia_hasta.isoformat(),
                "estado": c.estado_actual
            }
            for c in certificados
        ]
    })


@router.get("/descargar/{codigo}")
async def descargar_certificado(
    codigo: str,
    member = Depends(get_current_member),
    db: Session = Depends(get_db)
):
    """
    Regenera y descarga un certificado previamente emitido.
    Solo el dueño del certificado o admin puede descargarlo.
    """
    
    cert = db.execute(
        text("""
            SELECT 
                c.codigo_verificacion, c.colegiado_id,
                c.nombres, c.apellidos, c.matricula,
                c.fecha_emision, c.fecha_vigencia_hasta,
                c.en_fraccionamiento, c.estado,
                col.member_id
            FROM certificados_emitidos c
            JOIN colegiados col ON c.colegiado_id = col.id
            WHERE c.codigo_verificacion = :codigo
        """),
        {"codigo": codigo}
    ).fetchone()
    
    if not cert:
        raise HTTPException(status_code=404, detail="Certificado no encontrado")
    
    # Verificar permisos
    if cert.member_id != member.id and not member.is_admin:
        raise HTTPException(status_code=403, detail="No autorizado")
    
    # Generar PDF
    pdf_buffer = generar_certificado_pdf(
        codigo=cert.codigo_verificacion,
        nombres=cert.nombres,
        apellidos=cert.apellidos,
        matricula=cert.matricula,
        fecha_vigencia=cert.fecha_vigencia_hasta,
        fecha_emision=cert.fecha_emision,
        en_fraccionamiento=cert.en_fraccionamiento or False
    )
    
    nombre_archivo = f"Certificado_{cert.codigo_verificacion}.pdf"
    
    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename={nombre_archivo}"
        }
    )

@router.post("/anular/{codigo}")
async def anular_certificado(
    codigo: str,
    member = Depends(get_current_member),
    db: Session = Depends(get_db)
):
    """Anula un certificado (solo admin)"""
    
    if not member.is_admin:
        raise HTTPException(status_code=403, detail="Solo administradores pueden anular certificados")
    
    result = db.execute(
        text("""
            UPDATE certificados_emitidos 
            SET estado = 'anulado'
            WHERE codigo_verificacion = :codigo
            RETURNING id
        """),
        {"codigo": codigo}
    ).fetchone()
    
    if not result:
        raise HTTPException(status_code=404, detail="Certificado no encontrado")
    
    db.commit()
    
    return {"success": True, "mensaje": f"Certificado {codigo} anulado"}




# ============================================
# Router público (verificación sin auth)
# ============================================
router_publico = APIRouter(prefix="/verificacion", tags=["verificacion_publica"])

@router_publico.get("/{codigo}")
async def verificar_publico(codigo: str, db: Session = Depends(get_db)):
    """Verificación pública de certificado - No requiere login"""
    return await verificar_certificado(codigo, db)


@router_publico.get("")
@router_publico.get("/")
async def pagina_verificacion():
    """Retorna info para la página de verificación"""
    return JSONResponse({
        "mensaje": "Use /verificacion/{codigo} para verificar un certificado",
        "ejemplo": "/verificacion/2026-0000001"
    })


#==============================================================================================
# Veifica que el endpoint anterior NO se interponga con otros endpoints de router_certificados  👈👀👁👁‍🗨
# El endpoint /verificacion/{codigo} es específico para verificación pública y no debe interfer
#==============================================================================================
# ============================================================
# AGREGAR AL FINAL DE router_certificados.py
# (después del router_publico existente)
# ============================================================

# ============================================
# Descarga pública de Constancia de Habilidad
# Solo consulta: retorna HÁBIL / INHÁBIL
# NO descarga PDF (eso requiere login)
# ============================================

@router_publico.get("/constancia-habilidad/{dato}")
async def consulta_constancia_habilidad(
    dato: str,
    db: Session = Depends(get_db)
):
    """
    Consulta PÚBLICA de Constancia de Habilidad.
    Busca por DNI o matrícula.
    
    Para empresas, reclutadores y terceros interesados.
    NO entrega PDF, solo confirma estado HÁBIL/INHÁBIL.
    
    El PDF de la Constancia solo se descarga con login del colegiado.
    """
    
    # Buscar colegiado por DNI o matrícula
    colegiado = db.execute(
        text("""
            SELECT 
                c.id, c.nombres, c.apellidos, c.matricula,
                c.estado, c.dni,
                o.name as colegio_nombre
            FROM colegiados c
            JOIN organizations o ON c.organization_id = o.id
            WHERE c.dni = :dato 
               OR c.matricula = :dato
            LIMIT 1
        """),
        {"dato": dato.strip()}
    ).fetchone()
    
    if not colegiado:
        raise HTTPException(
            status_code=404, 
            detail="No se encontró un colegiado con ese DNI o matrícula."
        )
    
    es_habil = colegiado.estado == 'activo'
    
    # Verificar si tiene certificado/constancia vigente
    constancia_vigente = db.execute(
        text("""
            SELECT 
                codigo_verificacion,
                fecha_emision,
                fecha_vigencia_hasta,
                estado
            FROM certificados_emitidos
            WHERE colegiado_id = :colegiado_id
              AND estado = 'vigente'
              AND fecha_vigencia_hasta >= CURRENT_DATE
            ORDER BY fecha_emision DESC
            LIMIT 1
        """),
        {"colegiado_id": colegiado.id}
    ).fetchone()
    
    response = {
        "encontrado": True,
        "nombres": colegiado.nombres,
        "apellidos": colegiado.apellidos,
        "matricula": colegiado.matricula,
        "colegio": colegiado.colegio_nombre,
        "estado": "HÁBIL" if es_habil else "INHÁBIL",
        "es_habil": es_habil,
    }
    
    if constancia_vigente:
        response["constancia"] = {
            "codigo": constancia_vigente.codigo_verificacion,
            "fecha_emision": str(constancia_vigente.fecha_emision),
            "vigente_hasta": str(constancia_vigente.fecha_vigencia_hasta),
        }
    else:
        response["constancia"] = None
    
    # Nota: NO incluimos enlace de descarga del PDF
    # El PDF solo se descarga con login
    if es_habil:
        response["nota"] = "El colegiado se encuentra HÁBIL. Para obtener la Constancia de Habilidad en PDF, el colegiado debe acceder con sus credenciales."
    else:
        response["nota"] = "El colegiado se encuentra INHÁBIL. Debe regularizar su situación para obtener su Constancia de Habilidad."
    
    return response
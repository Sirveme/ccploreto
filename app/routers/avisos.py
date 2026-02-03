"""
Router: Sistema de Alertas Tributarias
=======================================
Endpoints para gestionar RUCs y configuración de alertas de vencimientos
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import date, datetime, timedelta
from typing import Optional, List
import httpx

from app.database import get_db
from app.routers.dashboard import get_current_member

router = APIRouter(prefix="/api/avisos", tags=["avisos"])


# ============================================================
# CRONOGRAMA SUNAT 2026 - Obligaciones Mensuales
# Vencimientos según último dígito del RUC
# ============================================================
CRONOGRAMA_2026 = {
    # Periodo: { ultimo_digito: dia_vencimiento }
    "2026-01": {0: 14, 1: 17, 2: 18, 3: 19, 4: 20, 5: 21, 6: 22, 7: 23, 8: 24, 9: 11, "buenos": 25},
    "2026-02": {0: 14, 1: 17, 2: 18, 3: 19, 4: 20, 5: 21, 6: 22, 7: 23, 8: 24, 9: 11, "buenos": 25},
    "2026-03": {0: 16, 1: 17, 2: 20, 3: 21, 4: 22, 5: 23, 6: 24, 7: 25, 8: 26, 9: 13, "buenos": 27},
    "2026-04": {0: 15, 1: 16, 2: 17, 3: 20, 4: 21, 5: 22, 6: 23, 7: 24, 8: 25, 9: 12, "buenos": 26},
    "2026-05": {0: 15, 1: 18, 2: 19, 3: 20, 4: 21, 5: 22, 6: 23, 7: 24, 8: 25, 9: 12, "buenos": 26},
    "2026-06": {0: 15, 1: 16, 2: 17, 3: 18, 4: 19, 5: 22, 6: 23, 7: 24, 8: 25, 9: 12, "buenos": 26},
    "2026-07": {0: 15, 1: 16, 2: 17, 3: 20, 4: 21, 5: 22, 6: 23, 7: 24, 8: 25, 9: 12, "buenos": 26},
    "2026-08": {0: 14, 1: 17, 2: 18, 3: 19, 4: 20, 5: 21, 6: 22, 7: 23, 8: 24, 9: 11, "buenos": 25},
    "2026-09": {0: 15, 1: 16, 2: 17, 3: 18, 4: 21, 5: 22, 6: 23, 7: 24, 8: 25, 9: 12, "buenos": 26},
    "2026-10": {0: 15, 1: 16, 2: 19, 3: 20, 4: 21, 5: 22, 6: 23, 7: 24, 8: 25, 9: 12, "buenos": 26},
    "2026-11": {0: 14, 1: 17, 2: 18, 3: 19, 4: 20, 5: 21, 6: 22, 7: 23, 8: 24, 9: 11, "buenos": 25},
    "2026-12": {0: 15, 1: 16, 2: 17, 3: 18, 4: 19, 5: 22, 6: 23, 7: 24, 8: 25, 9: 12, "buenos": 26},
}

# Fechas fijas 2026
FECHAS_FIJAS_2026 = {
    "cts_mayo": date(2026, 5, 15),
    "cts_noviembre": date(2026, 11, 16),  # 15 cae domingo
    "gratificacion_julio": date(2026, 7, 15),
    "gratificacion_diciembre": date(2026, 12, 15),
}

# AFP: Primeros 5 días hábiles del mes siguiente
# Simplificado: usamos día 5 como referencia
AFP_DIA_VENCIMIENTO = 5


# ============================================================
# FUNCIONES AUXILIARES
# ============================================================

def get_fecha_vencimiento_mensual(ruc: str, periodo: str) -> Optional[date]:
    """
    Calcula la fecha de vencimiento para obligaciones mensuales (PDT621, PLAME)
    según el último dígito del RUC y el periodo.
    """
    if periodo not in CRONOGRAMA_2026:
        return None
    
    ultimo_digito = int(ruc[-1])
    dia = CRONOGRAMA_2026[periodo].get(ultimo_digito)
    
    if not dia:
        return None
    
    # El vencimiento es en el mes SIGUIENTE al periodo
    year, month = map(int, periodo.split('-'))
    if month == 12:
        year += 1
        month = 1
    else:
        month += 1
    
    return date(year, month, dia)


def get_fecha_vencimiento_afp(periodo: str) -> date:
    """
    AFP vence los primeros 5 días hábiles del mes siguiente.
    Simplificamos usando día 5.
    """
    year, month = map(int, periodo.split('-'))
    if month == 12:
        year += 1
        month = 1
    else:
        month += 1
    
    return date(year, month, AFP_DIA_VENCIMIENTO)


def get_proximos_vencimientos(rucs: List[dict], dias_adelante: int = 30) -> List[dict]:
    """
    Genera lista de próximos vencimientos para los RUCs dados.
    """
    hoy = date.today()
    limite = hoy + timedelta(days=dias_adelante)
    vencimientos = []
    
    # Determinar periodos relevantes
    periodo_actual = f"{hoy.year}-{hoy.month:02d}"
    periodo_anterior = f"{hoy.year}-{(hoy.month - 1):02d}" if hoy.month > 1 else f"{hoy.year - 1}-12"
    
    for ruc_info in rucs:
        ruc = ruc_info['ruc']
        nombre = ruc_info['nombre']
        ultimo_digito = ruc[-1]
        
        # PDT 621 - Periodo anterior (declaración mensual)
        fecha_pdt = get_fecha_vencimiento_mensual(ruc, periodo_anterior)
        if fecha_pdt and hoy <= fecha_pdt <= limite:
            dias_restantes = (fecha_pdt - hoy).days
            vencimientos.append({
                'tipo': f'PDT 621 - {periodo_anterior}',
                'empresa': nombre,
                'ruc': ruc,
                'fecha': fecha_pdt.isoformat(),
                'dias_restantes': dias_restantes,
                'obligacion': 'pdt621'
            })
        
        # PLAME - Mismo vencimiento que PDT
        if fecha_pdt and hoy <= fecha_pdt <= limite:
            dias_restantes = (fecha_pdt - hoy).days
            vencimientos.append({
                'tipo': f'PLAME - {periodo_anterior}',
                'empresa': nombre,
                'ruc': ruc,
                'fecha': fecha_pdt.isoformat(),
                'dias_restantes': dias_restantes,
                'obligacion': 'plame'
            })
        
        # AFP - Vence ANTES que PDT/PLAME
        fecha_afp = get_fecha_vencimiento_afp(periodo_anterior)
        if hoy <= fecha_afp <= limite:
            dias_restantes = (fecha_afp - hoy).days
            vencimientos.append({
                'tipo': f'AFP/ONP - {periodo_anterior}',
                'empresa': nombre,
                'ruc': ruc,
                'fecha': fecha_afp.isoformat(),
                'dias_restantes': dias_restantes,
                'obligacion': 'afp'
            })
    
    # Fechas fijas (CTS, Gratificaciones) - Una sola vez, no por RUC
    if rucs:  # Solo si tiene al menos un RUC
        for key, fecha in FECHAS_FIJAS_2026.items():
            if hoy <= fecha <= limite:
                dias_restantes = (fecha - hoy).days
                tipo_nombre = {
                    'cts_mayo': 'CTS Mayo',
                    'cts_noviembre': 'CTS Noviembre', 
                    'gratificacion_julio': 'Gratificación Julio',
                    'gratificacion_diciembre': 'Gratificación Diciembre'
                }.get(key, key)
                
                obligacion = 'cts' if 'cts' in key else 'gratificacion'
                
                vencimientos.append({
                    'tipo': tipo_nombre,
                    'empresa': 'Todas las empresas',
                    'ruc': '-',
                    'fecha': fecha.isoformat(),
                    'dias_restantes': dias_restantes,
                    'obligacion': obligacion
                })
    
    # Ordenar por fecha
    vencimientos.sort(key=lambda x: x['fecha'])
    
    return vencimientos


# ============================================================
# ENDPOINTS
# ============================================================

@router.get("/config")
async def get_config(
    member = Depends(get_current_member),
    db: Session = Depends(get_db)
):
    """
    Obtiene la configuración de alertas y RUCs del colegiado.
    """
    # Obtener colegiado_id del member
    colegiado = db.execute(
        text("SELECT id FROM colegiados WHERE member_id = :member_id"),
        {"member_id": member.id}
    ).fetchone()
    
    if not colegiado:
        return JSONResponse({"rucs": [], "config": {}})
    
    colegiado_id = colegiado[0]
    
    # Obtener RUCs
    rucs_result = db.execute(
        text("""
            SELECT ruc, razon_social 
            FROM colegiado_ruc 
            WHERE colegiado_id = :cid
            ORDER BY razon_social
        """),
        {"cid": colegiado_id}
    ).fetchall()
    
    rucs = [{"numero": r[0], "nombre": r[1]} for r in rucs_result]
    
    # Obtener configuración
    config_result = db.execute(
        text("""
            SELECT obligacion, activo, dias_antes, horas
            FROM alerta_config
            WHERE colegiado_id = :cid
        """),
        {"cid": colegiado_id}
    ).fetchall()
    
    config = {}
    for c in config_result:
        config[c[0]] = {
            "activo": c[1],
            "dias_antes": c[2] or [],
            "horas": c[3] or []
        }
    
    return JSONResponse({"rucs": rucs, "config": config})


@router.post("/config")
async def save_config(
    data: dict,
    member = Depends(get_current_member),
    db: Session = Depends(get_db)
):
    """
    Guarda la configuración de alertas y RUCs del colegiado.
    """
    # Obtener colegiado_id
    colegiado = db.execute(
        text("SELECT id FROM colegiados WHERE member_id = :member_id"),
        {"member_id": member.id}
    ).fetchone()
    
    if not colegiado:
        raise HTTPException(status_code=404, detail="Colegiado no encontrado")
    
    colegiado_id = colegiado[0]
    
    # Guardar RUCs
    rucs = data.get("rucs", [])
    
    # Eliminar RUCs que ya no están
    rucs_numeros = [r["numero"] for r in rucs]
    if rucs_numeros:
        db.execute(
            text("""
                DELETE FROM colegiado_ruc 
                WHERE colegiado_id = :cid AND ruc NOT IN :rucs
            """),
            {"cid": colegiado_id, "rucs": tuple(rucs_numeros)}
        )
    else:
        db.execute(
            text("DELETE FROM colegiado_ruc WHERE colegiado_id = :cid"),
            {"cid": colegiado_id}
        )
    
    # Insertar/actualizar RUCs
    for ruc in rucs:
        db.execute(
            text("""
                INSERT INTO colegiado_ruc (colegiado_id, ruc, razon_social)
                VALUES (:cid, :ruc, :nombre)
                ON CONFLICT (colegiado_id, ruc) 
                DO UPDATE SET razon_social = EXCLUDED.razon_social
            """),
            {"cid": colegiado_id, "ruc": ruc["numero"], "nombre": ruc["nombre"]}
        )
    
    # Guardar configuración de alertas
    config = data.get("config", {})
    for obligacion, settings in config.items():
        db.execute(
            text("""
                INSERT INTO alerta_config (colegiado_id, obligacion, activo, dias_antes, horas, updated_at)
                VALUES (:cid, :ob, :activo, :dias, :horas, NOW())
                ON CONFLICT (colegiado_id, obligacion) 
                DO UPDATE SET 
                    activo = EXCLUDED.activo,
                    dias_antes = EXCLUDED.dias_antes,
                    horas = EXCLUDED.horas,
                    updated_at = NOW()
            """),
            {
                "cid": colegiado_id,
                "ob": obligacion,
                "activo": settings.get("activo", True),
                "dias": settings.get("dias_antes", [3, 5]),
                "horas": settings.get("horas", [8, 14])
            }
        )
    
    db.commit()
    
    return {"success": True}


@router.get("/proximos")
async def get_proximos(
    member = Depends(get_current_member),
    db: Session = Depends(get_db)
):
    """
    Obtiene los próximos vencimientos para los RUCs del colegiado.
    """
    # Obtener colegiado_id
    colegiado = db.execute(
        text("SELECT id FROM colegiados WHERE member_id = :member_id"),
        {"member_id": member.id}
    ).fetchone()
    
    if not colegiado:
        return JSONResponse({"vencimientos": []})
    
    colegiado_id = colegiado[0]
    
    # Obtener RUCs
    rucs_result = db.execute(
        text("""
            SELECT ruc, razon_social 
            FROM colegiado_ruc 
            WHERE colegiado_id = :cid
        """),
        {"cid": colegiado_id}
    ).fetchall()
    
    rucs = [{"ruc": r[0], "nombre": r[1]} for r in rucs_result]
    
    # Calcular vencimientos
    vencimientos = get_proximos_vencimientos(rucs, dias_adelante=30)
    
    return JSONResponse({"vencimientos": vencimientos})


# ============================================================
# CONSULTA RUC SUNAT
# ============================================================

@router.get("/sunat/ruc/{ruc}")
async def consultar_ruc(ruc: str):
    """
    Consulta un RUC en SUNAT.
    Por ahora usamos un servicio gratuito de consulta.
    En producción, usar API oficial o servicio autorizado.
    """
    if len(ruc) != 11 or not ruc.isdigit():
        return JSONResponse({"error": "RUC inválido"}, status_code=400)
    
    try:
        # Usar API gratuita de consulta RUC
        # NOTA: En producción, usar servicio oficial o de pago
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"https://api.apis.net.pe/v1/ruc?numero={ruc}",
                headers={"Accept": "application/json"}
            )
            
            if response.status_code == 200:
                data = response.json()
                return JSONResponse({
                    "nombre": data.get("nombre", data.get("razonSocial", "No encontrado")),
                    "estado": data.get("estado", "ACTIVO"),
                    "condicion": data.get("condicion", "HABIDO"),
                    "direccion": data.get("direccion", "")
                })
            else:
                # Fallback: generar nombre genérico
                return JSONResponse({
                    "nombre": f"CONTRIBUYENTE RUC {ruc}",
                    "estado": "ACTIVO",
                    "condicion": "HABIDO",
                    "direccion": ""
                })
                
    except Exception as e:
        # En caso de error, permitir agregar con nombre genérico
        return JSONResponse({
            "nombre": f"RUC {ruc}",
            "estado": "NO VERIFICADO",
            "condicion": "-",
            "direccion": ""
        })


# Ruta alternativa sin prefijo /api/avisos
router_sunat = APIRouter(prefix="/api/sunat", tags=["sunat"])

@router_sunat.get("/ruc/{ruc}")
async def consultar_ruc_alt(ruc: str):
    return await consultar_ruc(ruc)

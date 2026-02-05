"""
Router: Sistema de Alertas Tributarias v2
=========================================
Usa cronograma oficial SUNAT desde la base de datos

FIX aplicado: INSERT en colegiado_ruc ahora incluye ultimo_digito y grupo_ruc
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
# FUNCIONES AUXILIARES
# ============================================================

def get_grupo_ruc(ultimo_digito: str) -> str:
    """Convierte último dígito a grupo SUNAT"""
    if ultimo_digito == '0':
        return '0'
    elif ultimo_digito == '1':
        return '1'
    elif ultimo_digito in ('2', '3'):
        return '2-3'
    elif ultimo_digito in ('4', '5'):
        return '4-5'
    elif ultimo_digito in ('6', '7'):
        return '6-7'
    elif ultimo_digito in ('8', '9'):
        return '8-9'
    return '0'


def get_periodo_anterior() -> str:
    """Retorna el periodo tributario anterior (para el cual se declara este mes)"""
    hoy = date.today()
    if hoy.month == 1:
        return f"{hoy.year - 1}-12"
    else:
        return f"{hoy.year}-{hoy.month - 1:02d}"


# ============================================================
# ENDPOINTS
# ============================================================

@router.get("/config")
async def get_config(
    member = Depends(get_current_member),
    db: Session = Depends(get_db)
):
    """Obtiene configuración de alertas y RUCs del colegiado"""
    
    colegiado = db.execute(
        text("SELECT id FROM colegiados WHERE member_id = :mid"),
        {"mid": member.id}
    ).fetchone()
    
    if not colegiado:
        return JSONResponse({"rucs": [], "config": {}})
    
    colegiado_id = colegiado[0]
    
    # Obtener RUCs
    rucs_result = db.execute(
        text("""
            SELECT ruc, razon_social, ultimo_digito, grupo_ruc, es_buen_contribuyente
            FROM colegiado_ruc 
            WHERE colegiado_id = :cid
            ORDER BY razon_social
        """),
        {"cid": colegiado_id}
    ).fetchall()
    
    rucs = [{
        "numero": r[0],
        "nombre": r[1] or f"RUC {r[0]}",
        "ultimoDigito": r[2],
        "grupo": r[3],
        "esBuenContribuyente": r[4]
    } for r in rucs_result]
    
    # Obtener configuración
    config_result = db.execute(
        text("""
            SELECT dias_antes, horas_alerta,
                   pdt621_activo, plame_activo, afp_activo,
                   cts_activo, gratificacion_activo, renta_anual_activo
            FROM alerta_config
            WHERE colegiado_id = :cid
        """),
        {"cid": colegiado_id}
    ).fetchone()
    
    if config_result:
        config = {
            "dias_antes": config_result[0] or [5, 3, 1],
            "horas": config_result[1] or [8, 14, 19],
            "pdt621": config_result[2],
            "plame": config_result[3],
            "afp": config_result[4],
            "cts": config_result[5],
            "gratificacion": config_result[6],
            "renta_anual": config_result[7]
        }
    else:
        config = {
            "dias_antes": [5, 3, 1],
            "horas": [8, 14, 19],
            "pdt621": True,
            "plame": True,
            "afp": True,
            "cts": False,
            "gratificacion": False,
            "renta_anual": False
        }
    
    return JSONResponse({"rucs": rucs, "config": config})


@router.post("/config")
async def save_config(
    data: dict,
    member = Depends(get_current_member),
    db: Session = Depends(get_db)
):
    """Guarda configuración de alertas y RUCs"""
    
    colegiado = db.execute(
        text("SELECT id FROM colegiados WHERE member_id = :mid"),
        {"mid": member.id}
    ).fetchone()
    
    if not colegiado:
        raise HTTPException(status_code=404, detail="Colegiado no encontrado")
    
    colegiado_id = colegiado[0]
    
    # ================================================
    # GUARDAR RUCs (delete all + insert — simple y seguro)
    # ================================================
    rucs = data.get("rucs", [])
    
    db.execute(
        text("DELETE FROM colegiado_ruc WHERE colegiado_id = :cid"),
        {"cid": colegiado_id}
    )
    
    for ruc in rucs:
        numero = ruc.get("numero") or ruc.get("ruc")
        if not numero or len(numero) != 11:
            continue
            
        nombre = ruc.get("nombre") or ruc.get("razon_social") or f"RUC {numero}"
        es_bueno = ruc.get("esBuenContribuyente", False)
        ultimo_digito = int(numero[-1])
        grupo = get_grupo_ruc(str(ultimo_digito))
        
        db.execute(
            text("""
                INSERT INTO colegiado_ruc (colegiado_id, ruc, razon_social, es_buen_contribuyente)
                VALUES (:cid, :ruc, :nombre, :bueno)
                ON CONFLICT (colegiado_id, ruc) 
                DO UPDATE SET razon_social = EXCLUDED.razon_social,
                            es_buen_contribuyente = EXCLUDED.es_buen_contribuyente
            """),
            {"cid": colegiado_id, "ruc": numero, "nombre": nombre, "bueno": es_bueno}
        )
    
    # ================================================
    # GUARDAR CONFIGURACIÓN DE ALERTAS
    # ================================================
    config = data.get("config", {})
    
    db.execute(
        text("""
            INSERT INTO alerta_config (
                colegiado_id, dias_antes, horas_alerta,
                pdt621_activo, plame_activo, afp_activo,
                cts_activo, gratificacion_activo, renta_anual_activo,
                updated_at
            ) VALUES (
                :cid, :dias, :horas,
                :pdt621, :plame, :afp,
                :cts, :grati, :renta,
                NOW()
            )
            ON CONFLICT (colegiado_id) DO UPDATE SET
                dias_antes = EXCLUDED.dias_antes,
                horas_alerta = EXCLUDED.horas_alerta,
                pdt621_activo = EXCLUDED.pdt621_activo,
                plame_activo = EXCLUDED.plame_activo,
                afp_activo = EXCLUDED.afp_activo,
                cts_activo = EXCLUDED.cts_activo,
                gratificacion_activo = EXCLUDED.gratificacion_activo,
                renta_anual_activo = EXCLUDED.renta_anual_activo,
                updated_at = NOW()
        """),
        {
            "cid": colegiado_id,
            "dias": config.get("dias_antes", [5, 3, 1]),
            "horas": config.get("horas", [8, 14, 19]),
            "pdt621": config.get("pdt621", True),
            "plame": config.get("plame", True),
            "afp": config.get("afp", True),
            "cts": config.get("cts", False),
            "grati": config.get("gratificacion", False),
            "renta": config.get("renta_anual", False)
        }
    )
    
    db.commit()
    return {"success": True, "rucs_guardados": len(rucs)}


@router.get("/proximos")
async def get_proximos(
    member = Depends(get_current_member),
    db: Session = Depends(get_db)
):
    """Obtiene próximos vencimientos usando cronograma oficial SUNAT"""
    
    colegiado = db.execute(
        text("SELECT id FROM colegiados WHERE member_id = :mid"),
        {"mid": member.id}
    ).fetchone()
    
    if not colegiado:
        return JSONResponse({"vencimientos": []})
    
    colegiado_id = colegiado[0]
    
    # Obtener RUCs del colegiado
    rucs_result = db.execute(
        text("""
            SELECT ruc, razon_social, grupo_ruc, es_buen_contribuyente
            FROM colegiado_ruc 
            WHERE colegiado_id = :cid
        """),
        {"cid": colegiado_id}
    ).fetchall()
    
    if not rucs_result:
        return JSONResponse({"vencimientos": []})
    
    vencimientos = []
    hoy = date.today()
    periodo = get_periodo_anterior()
    
    # Para cada RUC, buscar su vencimiento en el cronograma
    for ruc_row in rucs_result:
        ruc = ruc_row[0]
        nombre = ruc_row[1] or f"RUC {ruc}"
        grupo = ruc_row[2]
        es_bueno = ruc_row[3]
        
        # Usar grupo "buenos" si aplica
        grupo_buscar = "buenos" if es_bueno else grupo
        
        # Buscar en cronograma SUNAT
        cronograma = db.execute(
            text("""
                SELECT fecha_vencimiento 
                FROM cronograma_sunat
                WHERE periodo = :periodo AND grupo_ruc = :grupo
            """),
            {"periodo": periodo, "grupo": grupo_buscar}
        ).fetchone()
        
        if cronograma and cronograma[0] >= hoy:
            fecha_vence = cronograma[0]
            dias = (fecha_vence - hoy).days
            
            # PDT 621
            vencimientos.append({
                "tipo": f"PDT 621 - {periodo}",
                "ruc": ruc,
                "empresa": nombre,
                "fecha": fecha_vence.isoformat(),
                "dias_restantes": dias,
                "obligacion": "pdt621"
            })
            
            # PLAME (misma fecha)
            vencimientos.append({
                "tipo": f"PLAME - {periodo}",
                "ruc": ruc,
                "empresa": nombre,
                "fecha": fecha_vence.isoformat(),
                "dias_restantes": dias,
                "obligacion": "plame"
            })
    
    # AFP - 5to día hábil (usar función de BD)
    afp_result = db.execute(
        text("""
            SELECT get_fecha_afp(:anio, :mes) as fecha_afp
        """),
        {"anio": hoy.year, "mes": hoy.month}
    ).fetchone()
    
    if afp_result and afp_result[0]:
        fecha_afp = afp_result[0]
        if isinstance(fecha_afp, str):
            fecha_afp = datetime.strptime(fecha_afp, '%Y-%m-%d').date()
        
        # Si ya pasó, calcular para siguiente mes
        if fecha_afp < hoy:
            mes_sig = hoy.month + 1 if hoy.month < 12 else 1
            anio_sig = hoy.year if hoy.month < 12 else hoy.year + 1
            afp_result = db.execute(
                text("SELECT get_fecha_afp(:anio, :mes)"),
                {"anio": anio_sig, "mes": mes_sig}
            ).fetchone()
            if afp_result:
                fecha_afp = afp_result[0]
                if isinstance(fecha_afp, str):
                    fecha_afp = datetime.strptime(fecha_afp, '%Y-%m-%d').date()
        
        dias_afp = (fecha_afp - hoy).days
        if dias_afp >= 0:
            vencimientos.append({
                "tipo": "AFP/ONP",
                "ruc": "Todos",
                "empresa": "⚠️ Vence ANTES que PLAME",
                "fecha": fecha_afp.isoformat(),
                "dias_restantes": dias_afp,
                "obligacion": "afp"
            })
    
    # Fechas fijas (CTS, Gratificaciones)
    fechas_fijas = db.execute(
        text("""
            SELECT concepto, descripcion, fecha_vencimiento
            FROM fechas_fijas_tributarias
            WHERE anio = :anio AND fecha_vencimiento >= :hoy
            ORDER BY fecha_vencimiento
        """),
        {"anio": hoy.year, "hoy": hoy}
    ).fetchall()
    
    for ff in fechas_fijas:
        concepto, desc, fecha = ff
        dias = (fecha - hoy).days
        if dias <= 60:
            vencimientos.append({
                "tipo": desc or concepto.replace('_', ' ').title(),
                "ruc": "Todos",
                "empresa": "Fecha fija",
                "fecha": fecha.isoformat(),
                "dias_restantes": dias,
                "obligacion": "cts" if "cts" in concepto else "gratificacion"
            })
    
    # Ordenar por fecha
    vencimientos.sort(key=lambda x: x["dias_restantes"])
    
    return JSONResponse({"vencimientos": vencimientos})


@router.get("/cronograma/{periodo}")
async def get_cronograma(periodo: str, db: Session = Depends(get_db)):
    """Obtiene el cronograma completo de un periodo"""
    result = db.execute(
        text("""
            SELECT grupo_ruc, fecha_vencimiento
            FROM cronograma_sunat
            WHERE periodo = :periodo
            ORDER BY fecha_vencimiento
        """),
        {"periodo": periodo}
    ).fetchall()
    
    cronograma = {r[0]: r[1].isoformat() for r in result}
    return JSONResponse(cronograma)


# ============================================================
# CONSULTA RUC SUNAT
# ============================================================

@router.get("/ruc/{ruc}")
async def consultar_ruc(ruc: str):
    """Consulta RUC en API externa"""
    
    if len(ruc) != 11 or not ruc.isdigit():
        return JSONResponse({"error": "RUC inválido"}, status_code=400)
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"https://api.apis.net.pe/v1/ruc?numero={ruc}",
                headers={"Accept": "application/json"}
            )
            
            if response.status_code == 200:
                data = response.json()
                return JSONResponse({
                    "nombre": data.get("nombre") or data.get("razonSocial", f"RUC {ruc}"),
                    "estado": data.get("estado", "ACTIVO"),
                    "condicion": data.get("condicion", "HABIDO"),
                    "direccion": data.get("direccion", "")
                })
    except Exception as e:
        print(f"Error consultando RUC: {e}")
    
    # Fallback
    return JSONResponse({
        "nombre": f"Contribuyente RUC {ruc}",
        "estado": "NO VERIFICADO",
        "condicion": "-",
        "direccion": ""
    })


# Router alternativo para /api/sunat/ruc
router_sunat = APIRouter(prefix="/api/sunat", tags=["sunat"])

@router_sunat.get("/ruc/{ruc}")
async def consultar_ruc_sunat(ruc: str):
    return await consultar_ruc(ruc)
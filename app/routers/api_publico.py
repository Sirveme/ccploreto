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
    Verifica un constancia de habilidad.
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
            "mensaje": "Constancia no encontrada en el sistema"
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
        "mensaje": "Constancia válida y vigente" if es_vigente else f"Constancia {result.estado_actual}"
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



# ══════════════════════════════════════════════════════════════════════════════
# AGREGAR AL FINAL DE app/routers/api_publico.py
# Endpoint público para página /reactivarse
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/reactivarse/consulta")
async def consulta_reactivarse(
    q: str,
    db: Session = Depends(get_db)
):
    """
    Consulta pública por DNI, matrícula o nombre.
    Devuelve: nombre, condicion, deuda_total, deuda_condonable, deuda_fraccionable.
    No requiere autenticación.
    """
    from sqlalchemy import or_, func as _func
    from app.models import Colegiado as _Col
    from app.models_debt_management import Debt as _Debt

    q = q.strip()
    if len(q) < 6:
        return JSONResponse({"encontrado": False, "mensaje": "Ingresa al menos 6 caracteres"})

    # Buscar colegiado por DNI, matrícula o nombre
    col = db.query(_Col).filter(
        or_(
            _Col.dni == q,
            _Col.codigo_matricula == q,
            _Col.codigo_matricula == f"10-{q.zfill(4)}",
            _Col.apellidos_nombres.ilike(f"%{q}%"),
        )
    ).first()

    if not col:
        return JSONResponse({
            "encontrado": False,
            "mensaje": "No encontramos un colegiado con ese dato. Prueba con tu número de DNI."
        })

    # Calcular deudas
    deudas = db.query(_Debt).filter(
        _Debt.colegiado_id == col.id,
        _Debt.status.in_(["pending", "partial"]),
        _Debt.estado_gestion.in_(["vigente", "en_cobranza"]),
    ).all()

    deuda_total       = sum(float(d.balance) for d in deudas)
    deuda_condonable  = sum(
        float(d.balance) for d in deudas
        if d.debt_type == "multa" or
           (d.debt_type == "cuota_ordinaria" and d.periodo and
            str(d.periodo)[:4].isdigit() and int(str(d.periodo)[:4]) <= 2019)
    )
    deuda_fraccionable = deuda_total - deuda_condonable

    return JSONResponse({
        "encontrado":       True,
        "nombre":           col.apellidos_nombres or "—",
        "dni":              col.dni or "—",
        "matricula":        col.codigo_matricula,
        "condicion":        col.condicion or "inhabil",
        "deuda_total":      round(deuda_total, 2),
        "deuda_condonable": round(deuda_condonable, 2),
        "deuda_fraccionable": round(deuda_fraccionable, 2),
    })


# ══════════════════════════════════════════════════════════════════════════════
# AGREGAR EN app/routers/public.py (al final, en router_landing)
# ══════════════════════════════════════════════════════════════════════════════

# @router_landing.get("/reactivarse", response_class=HTMLResponse)
# async def pagina_reactivarse(request: Request):
#     return templates.TemplateResponse("pages/public/reactivarse.html", {
#         "request": request
#     })
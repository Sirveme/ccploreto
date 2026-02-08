"""
Endpoint: Mis Pagos del Colegiado
Rutas para el modal de pagos en el dashboard

REEMPLAZAR app/routers/pagos_colegiado.py CON ESTE CONTENIDO
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import func
from jose import jwt, JWTError
import os

from app.database import get_db
from app.models import Payment, Debt, Colegiado, Member

router = APIRouter(prefix="/api/colegiado", tags=["colegiado"])

# Configuración JWT
SECRET_KEY = os.getenv("SECRET_KEY", "tu-clave-secreta")
ALGORITHM = "HS256"


def get_member_from_token(request: Request, db: Session):
    """
    Extrae el member del token JWT - Versión para APIs
    Lanza HTTPException en vez de redirigir
    """
    token = request.cookies.get("access_token")
    
    if not token:
        raise HTTPException(status_code=401, detail="No autenticado")
    
    try:
        # Parsear "Bearer token_value"
        parts = token.split()
        if len(parts) == 2 and parts[0].lower() == 'bearer':
            token_value = parts[1]
        else:
            token_value = token
        
        # Decodificar JWT - usa "sub" como get_current_member
        payload = jwt.decode(token_value, SECRET_KEY, algorithms=[ALGORITHM])
        member_id = payload.get("sub")
        
        if not member_id:
            raise HTTPException(status_code=401, detail="Token inválido")
        
        member = db.query(Member).filter(Member.id == member_id).first()
        if not member:
            raise HTTPException(status_code=401, detail="Usuario no encontrado")
        
        return member
        
    except JWTError:
        raise HTTPException(status_code=401, detail="Token inválido o expirado")
    
    except Exception as e:
        print(f"⚠️ Error auth API: {e}")
        raise HTTPException(status_code=401, detail="Error de autenticación")


@router.get("/mis-pagos")
async def mis_pagos(request: Request, db: Session = Depends(get_db)):
    """
    Obtiene historial de pagos y estado de cuenta del colegiado logueado.
    """
    member = get_member_from_token(request, db)
    
    colegiado = db.query(Colegiado).filter(
        Colegiado.member_id == member.id
    ).first()
    
    if not colegiado:
        raise HTTPException(status_code=404, detail="Colegiado no encontrado")
    
    # RESUMEN
    deuda_total = db.query(func.coalesce(func.sum(Debt.balance), 0)).filter(
        Debt.colegiado_id == colegiado.id,
        Debt.status.in_(['pending', 'partial'])
    ).scalar() or 0
    
    total_pagado = db.query(func.coalesce(func.sum(Payment.amount), 0)).filter(
        Payment.colegiado_id == colegiado.id,
        Payment.status == 'approved'
    ).scalar() or 0
    
    en_revision = db.query(func.coalesce(func.sum(Payment.amount), 0)).filter(
        Payment.colegiado_id == colegiado.id,
        Payment.status == 'review'
    ).scalar() or 0
    
    # HISTORIAL DE PAGOS
    pagos_db = db.query(Payment).filter(
        Payment.colegiado_id == colegiado.id
    ).order_by(Payment.created_at.desc()).limit(50).all()
    
    pagos = [{
        "id": p.id,
        "fecha": p.created_at.strftime("%d/%m/%Y") if p.created_at else "-",
        "monto": float(p.amount) if p.amount else 0,
        "metodo": p.payment_method or "-",
        "operacion": p.operation_code,
        "estado": p.status,
        "concepto": p.notes or "Pago de cuotas",
        "rechazo_motivo": p.rejection_reason
    } for p in pagos_db]
    
    # DEUDAS PENDIENTES
    deudas_db = db.query(Debt).filter(
        Debt.colegiado_id == colegiado.id,
        Debt.status.in_(['pending', 'partial'])
    ).order_by(Debt.due_date.asc()).all()
    
    deudas = [{
        "id": d.id,
        "concepto": d.concept or "Cuota mensual",
        "periodo": d.periodo or "-",
        "monto_original": float(d.amount) if d.amount else 0,
        "balance": float(d.balance) if d.balance else 0,
        "vencimiento": d.due_date.isoformat() if d.due_date else None,
        "estado": d.status
    } for d in deudas_db]
    
    return {
        "resumen": {
            "deuda_total": float(deuda_total),
            "total_pagado": float(total_pagado),
            "en_revision": float(en_revision)
        },
        "pagos": pagos,
        "deudas": deudas,
        "colegiado": {
            "id": colegiado.id,
            "nombre": colegiado.apellidos_nombres,
            "dni": colegiado.dni,
            "matricula": colegiado.codigo_matricula,
            "condicion": colegiado.condicion
        }
    }


@router.get("/pago/{pago_id}")
async def detalle_pago(request: Request, pago_id: int, db: Session = Depends(get_db)):
    """Obtiene detalle de un pago específico"""
    member = get_member_from_token(request, db)
    
    colegiado = db.query(Colegiado).filter(
        Colegiado.member_id == member.id
    ).first()
    
    if not colegiado:
        raise HTTPException(status_code=404, detail="Colegiado no encontrado")
    
    pago = db.query(Payment).filter(
        Payment.id == pago_id,
        Payment.colegiado_id == colegiado.id
    ).first()
    
    if not pago:
        raise HTTPException(status_code=404, detail="Pago no encontrado")
    
    return {
        "id": pago.id,
        "fecha": pago.created_at.strftime("%d/%m/%Y %H:%M") if pago.created_at else "-",
        "monto": float(pago.amount) if pago.amount else 0,
        "metodo": pago.payment_method,
        "operacion": pago.operation_code,
        "estado": pago.status,
        "concepto": pago.notes or "Pago de cuotas",
        "voucher_url": pago.voucher_url,
        "rechazo_motivo": pago.rejection_reason,
        "revisado_en": pago.reviewed_at.strftime("%d/%m/%Y %H:%M") if pago.reviewed_at else None
    }
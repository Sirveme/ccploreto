"""
Endpoint: Mis Pagos del Colegiado
=================================
Agregar este código al router de dashboard.py o crear un nuevo archivo pagos_colegiado.py

Este endpoint retorna:
- Resumen de cuenta (deuda total, pagado, en revisión)
- Historial de pagos
- Deudas pendientes
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import text, func
from datetime import datetime, timezone

from app.database import get_db
from app.models import Payment, Debt, Colegiado
from app.routers.dashboard import get_current_member  # Reutilizar la autenticación existente

# Si es archivo nuevo:
router = APIRouter(prefix="/api/colegiado", tags=["colegiado"])

# Si agregas a dashboard.py, usar el router existente


@router.get("/api/colegiado/mis-pagos")
async def mis_pagos(
    member = Depends(get_current_member),
    db: Session = Depends(get_db)
):
    """
    Obtiene el historial de pagos y estado de cuenta del colegiado logueado.
    
    Retorna:
    - resumen: {deuda_total, total_pagado, en_revision}
    - pagos: lista de pagos con fecha, monto, estado, método
    - deudas: lista de deudas pendientes con concepto, periodo, balance, vencimiento
    """
    
    # Obtener colegiado del member logueado
    colegiado = db.query(Colegiado).filter(
        Colegiado.member_id == member.id
    ).first()
    
    if not colegiado:
        raise HTTPException(status_code=404, detail="Colegiado no encontrado")
    
    # ========================================
    # RESUMEN DE CUENTA
    # ========================================
    
    # Deuda total (deudas pending + partial)
    deuda_total = db.query(func.coalesce(func.sum(Debt.balance), 0)).filter(
        Debt.colegiado_id == colegiado.id,
        Debt.status.in_(['pending', 'partial'])
    ).scalar() or 0
    
    # Total pagado (pagos approved)
    total_pagado = db.query(func.coalesce(func.sum(Payment.amount), 0)).filter(
        Payment.colegiado_id == colegiado.id,
        Payment.status == 'approved'
    ).scalar() or 0
    
    # En revisión (pagos review)
    en_revision = db.query(func.coalesce(func.sum(Payment.amount), 0)).filter(
        Payment.colegiado_id == colegiado.id,
        Payment.status == 'review'
    ).scalar() or 0
    
    # ========================================
    # HISTORIAL DE PAGOS
    # ========================================
    
    pagos_db = db.query(Payment).filter(
        Payment.colegiado_id == colegiado.id
    ).order_by(Payment.created_at.desc()).limit(50).all()
    
    pagos = []
    for p in pagos_db:
        pagos.append({
            "id": p.id,
            "fecha": p.created_at.strftime("%d/%m/%Y %H:%M") if p.created_at else "-",
            "monto": float(p.amount) if p.amount else 0,
            "metodo": p.payment_method or "-",
            "operacion": p.operation_code,
            "estado": p.status,
            "concepto": p.notes or "Pago de cuotas",
            "rechazo_motivo": p.rejection_reason
        })
    
    # ========================================
    # DEUDAS PENDIENTES
    # ========================================
    
    deudas_db = db.query(Debt).filter(
        Debt.colegiado_id == colegiado.id,
        Debt.status.in_(['pending', 'partial'])
    ).order_by(Debt.due_date.asc()).all()
    
    deudas = []
    for d in deudas_db:
        deudas.append({
            "id": d.id,
            "concepto": d.concept or "Cuota",
            "periodo": d.periodo or "-",
            "monto_original": float(d.amount) if d.amount else 0,
            "balance": float(d.balance) if d.balance else 0,
            "vencimiento": d.due_date.isoformat() if d.due_date else None,
            "estado": d.status
        })
    
    # ========================================
    # RESPUESTA
    # ========================================
    
    return JSONResponse({
        "resumen": {
            "deuda_total": float(deuda_total),
            "total_pagado": float(total_pagado),
            "en_revision": float(en_revision)
        },
        "pagos": pagos,
        "deudas": deudas,
        "colegiado": {
            "nombre": colegiado.apellidos_nombres,
            "matricula": colegiado.codigo_matricula,
            "condicion": colegiado.condicion
        }
    })


# ========================================
# ENDPOINT PARA OBTENER DETALLE DE UN PAGO
# ========================================

@router.get("/api/colegiado/pago/{pago_id}")
async def detalle_pago(
    pago_id: int,
    member = Depends(get_current_member),
    db: Session = Depends(get_db)
):
    """Obtiene el detalle de un pago específico del colegiado"""
    
    # Obtener colegiado
    colegiado = db.query(Colegiado).filter(
        Colegiado.member_id == member.id
    ).first()
    
    if not colegiado:
        raise HTTPException(status_code=404, detail="Colegiado no encontrado")
    
    # Obtener pago (verificando que pertenece al colegiado)
    pago = db.query(Payment).filter(
        Payment.id == pago_id,
        Payment.colegiado_id == colegiado.id
    ).first()
    
    if not pago:
        raise HTTPException(status_code=404, detail="Pago no encontrado")
    
    return JSONResponse({
        "id": pago.id,
        "fecha": pago.created_at.strftime("%d/%m/%Y %H:%M") if pago.created_at else "-",
        "monto": float(pago.amount) if pago.amount else 0,
        "metodo": pago.payment_method,
        "operacion": pago.operation_code,
        "estado": pago.status,
        "concepto": pago.notes or "Pago de cuotas",
        "voucher_url": pago.voucher_url,
        "rechazo_motivo": pago.rejection_reason,
        "revisado_en": pago.reviewed_at.strftime("%d/%m/%Y %H:%M") if pago.reviewed_at else None,
        "pagador": {
            "tipo": pago.pagador_tipo,
            "nombre": pago.pagador_nombre,
            "documento": pago.pagador_documento
        } if pago.pagador_tipo != 'titular' else None
    })
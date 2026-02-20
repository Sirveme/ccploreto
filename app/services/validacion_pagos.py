"""
Flujo: Validación de Pagos
app/services/validacion_pagos.py

Al aprobar un pago:
1. Actualizar estado del pago
2. Actualizar balance de deudas
3. Emitir Certificado de Habilidad (si aplica)
4. Emitir Comprobante Electrónico (Boleta/Factura)
"""

from datetime import datetime, timezone
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models import Payment, Colegiado, Member, Comprobante
from app.models_debt_management import Debt
# from app.services.facturacion import emitir_comprobante_automatico
# from app.services.certificados import generar_certificado_habilidad


class ValidacionPagosService:
    """
    Servicio para validar (aprobar/rechazar) pagos
    y ejecutar las acciones posteriores
    """
    
    def __init__(self, db: Session, org_id: int, admin_id: int):
        self.db = db
        self.org_id = org_id
        self.admin_id = admin_id
    
    async def aprobar_pago(
        self, 
        pago_id: int,
        notas: str = None,
        emitir_comprobante: bool = True,
        generar_certificado: bool = True
    ) -> Dict[str, Any]:
        """
        Aprueba un pago y ejecuta las acciones posteriores
        
        Returns:
            {
                "success": True/False,
                "pago": {...},
                "deudas_actualizadas": [...],
                "certificado": {...} or None,
                "comprobante": {...} or None,
                "error": "..." if failed
            }
        """
        resultado = {
            "success": False,
            "pago": None,
            "deudas_actualizadas": [],
            "certificado": None,
            "comprobante": None
        }
        
        # 1. Obtener y validar el pago
        pago = self.db.query(Payment).filter(
            Payment.id == pago_id,
            Payment.organization_id == self.org_id
        ).first()
        
        if not pago:
            resultado["error"] = "Pago no encontrado"
            return resultado
        
        if pago.status != "review":
            resultado["error"] = f"El pago ya fue procesado (estado: {pago.status})"
            return resultado
        
        try:
            # 2. Aprobar el pago
            pago.status = "approved"
            pago.reviewed_by = self.admin_id
            pago.reviewed_at = datetime.now(timezone.utc)
            if notas:
                pago.notes = (pago.notes or "") + f"\n[APROBADO] {notas}"
            
            self.db.flush()
            
            # 3. Aplicar pago a deudas
            deudas_actualizadas = self._aplicar_pago_a_deudas(pago)
            resultado["deudas_actualizadas"] = deudas_actualizadas
            
            # 4. Verificar si el colegiado queda hábil
            colegiado = self.db.query(Colegiado).filter(
                Colegiado.id == pago.colegiado_id
            ).first()
            
            if colegiado:
                queda_habil = self._verificar_habilidad(colegiado.id)
                
                # Actualizar condición del colegiado
                if queda_habil:
                    colegiado.condicion = "Hábil"
                    
                    # 5. Generar certificado si aplica
                    if generar_certificado:
                        certificado = await self._generar_certificado(colegiado)
                        resultado["certificado"] = certificado
            
            # 6. Emitir comprobante electrónico
            if emitir_comprobante:
                comprobante = await self._emitir_comprobante(pago)
                resultado["comprobante"] = comprobante
            
            # Commit de todo
            self.db.commit()
            
            resultado["success"] = True
            resultado["pago"] = {
                "id": pago.id,
                "monto": pago.amount,
                "metodo": pago.payment_method,
                "status": pago.status
            }
            
        except Exception as e:
            self.db.rollback()
            resultado["error"] = str(e)
            print(f"❌ Error aprobando pago {pago_id}: {e}")
        
        return resultado
    
    def rechazar_pago(self, pago_id: int, motivo: str) -> Dict[str, Any]:
        """Rechaza un pago con un motivo"""
        pago = self.db.query(Payment).filter(
            Payment.id == pago_id,
            Payment.organization_id == self.org_id
        ).first()
        
        if not pago:
            return {"success": False, "error": "Pago no encontrado"}
        
        if pago.status != "review":
            return {"success": False, "error": f"El pago ya fue procesado (estado: {pago.status})"}
        
        pago.status = "rejected"
        pago.rejection_reason = motivo
        pago.reviewed_by = self.admin_id
        pago.reviewed_at = datetime.now(timezone.utc)
        
        self.db.commit()
        
        return {
            "success": True,
            "pago": {
                "id": pago.id,
                "status": pago.status,
                "rejection_reason": pago.rejection_reason
            }
        }
    
    def _aplicar_pago_a_deudas(self, pago: Payment) -> list:
        """
        Aplica el monto del pago a las deudas pendientes
        Orden: por fecha de vencimiento (más antiguas primero)
        """
        monto_disponible = pago.amount
        deudas_actualizadas = []
        
        # Si hay deuda específica relacionada
        if pago.related_debt_id:
            deuda = self.db.query(Debt).filter(Debt.id == pago.related_debt_id).first()
            if deuda and deuda.balance > 0:
                aplicar = min(monto_disponible, deuda.balance)
                deuda.balance -= aplicar
                deuda.status = "paid" if deuda.balance == 0 else "partial"
                monto_disponible -= aplicar
                deudas_actualizadas.append({
                    "id": deuda.id,
                    "periodo": deuda.periodo,
                    "aplicado": aplicar,
                    "balance": deuda.balance
                })
        
        # Si queda monto, aplicar a deudas pendientes en orden
        if monto_disponible > 0:
            deudas_pendientes = self.db.query(Debt).filter(
                Debt.colegiado_id == pago.colegiado_id,
                Debt.status.in_(["pending", "partial"]),
                Debt.balance > 0
            ).order_by(Debt.due_date.asc(), Debt.created_at.asc()).all()
            
            for deuda in deudas_pendientes:
                if monto_disponible <= 0:
                    break
                
                aplicar = min(monto_disponible, deuda.balance)
                deuda.balance -= aplicar
                deuda.status = "paid" if deuda.balance == 0 else "partial"
                monto_disponible -= aplicar
                
                deudas_actualizadas.append({
                    "id": deuda.id,
                    "periodo": deuda.periodo,
                    "aplicado": aplicar,
                    "balance": deuda.balance
                })
        
        return deudas_actualizadas
    
    def _verificar_habilidad(self, colegiado_id: int) -> bool:
        """
        Verifica si el colegiado queda hábil después del pago
        Criterio: No debe tener deudas pendientes mayores a X meses
        """
        # Contar deudas pendientes
        deudas_pendientes = self.db.query(func.count(Debt.id)).filter(
            Debt.colegiado_id == colegiado_id,
            Debt.status.in_(["pending", "partial"]),
            Debt.balance > 0
        ).scalar()
        
        # Si no hay deudas pendientes, está hábil
        return deudas_pendientes == 0
    
    async def _generar_certificado(self, colegiado: Colegiado) -> Optional[Dict]:
        """
        Genera certificado de habilidad para el colegiado
        TODO: Implementar generación de PDF con QR
        """
        # Por ahora retornamos un placeholder
        # Aquí se integraría con el servicio de certificados
        return {
            "generado": True,
            "colegiado_id": colegiado.id,
            "tipo": "habilidad",
            "vigencia_hasta": "2025-12-31",  # TODO: calcular según config
            "url": f"/certificados/habilidad/{colegiado.id}"  # TODO: generar PDF
        }
    
    async def _emitir_comprobante(self, pago: Payment) -> Optional[Dict]:
        """
        Emite comprobante electrónico vía facturalo.pro
        """
        try:
            # Importar aquí para evitar circular imports
            from app.services.facturacion import FacturacionService
            
            service = FacturacionService(self.db, self.org_id)
            
            if not service.esta_configurado():
                return {"emitido": False, "error": "Facturación no configurada"}
            
            # Determinar tipo: Factura si es empresa, Boleta si es persona
            tipo = "01" if pago.pagador_tipo == "empresa" else "03"
            
            resultado = await service.emitir_comprobante_por_pago(pago.id, tipo)
            
            return {
                "emitido": resultado["success"],
                "tipo": "Factura" if tipo == "01" else "Boleta",
                "serie": resultado.get("serie"),
                "numero": resultado.get("numero"),
                "pdf_url": resultado.get("pdf_url"),
                "error": resultado.get("error")
            }
            
        except Exception as e:
            print(f"⚠️ Error emitiendo comprobante: {e}")
            return {"emitido": False, "error": str(e)}


# ============================================================
# Endpoint para integrar en el router
# ============================================================
"""
Agregar a app/routers/pagos_admin.py o similar:

from app.services.validacion_pagos import ValidacionPagosService

@router.post("/admin/pagos/{pago_id}/aprobar")
async def aprobar_pago(
    pago_id: int,
    notas: str = Form(None),
    emitir_comprobante: bool = Form(True),
    generar_certificado: bool = Form(True),
    request: Request,
    db: Session = Depends(get_db)
):
    # Verificar que es admin
    admin = get_current_admin(request, db)
    
    service = ValidacionPagosService(db, admin.organization_id, admin.id)
    resultado = await service.aprobar_pago(
        pago_id,
        notas=notas,
        emitir_comprobante=emitir_comprobante,
        generar_certificado=generar_certificado
    )
    
    if resultado["success"]:
        return JSONResponse(resultado)
    else:
        raise HTTPException(status_code=400, detail=resultado["error"])


@router.post("/admin/pagos/{pago_id}/rechazar")
async def rechazar_pago(
    pago_id: int,
    motivo: str = Form(...),
    request: Request,
    db: Session = Depends(get_db)
):
    admin = get_current_admin(request, db)
    
    service = ValidacionPagosService(db, admin.organization_id, admin.id)
    resultado = service.rechazar_pago(pago_id, motivo)
    
    if resultado["success"]:
        return JSONResponse(resultado)
    else:
        raise HTTPException(status_code=400, detail=resultado["error"])
"""
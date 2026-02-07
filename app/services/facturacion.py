"""
Servicio: Facturación Electrónica
app/services/facturacion.py

Integración con facturalo.pro para emisión de comprobantes
"""

import httpx
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models import (
    Comprobante, 
    ConfiguracionFacturacion, 
    Payment, 
    Colegiado,
    Organization
)


class FacturacionService:
    """
    Servicio para emitir comprobantes electrónicos vía facturalo.pro
    """
    
    def __init__(self, db: Session, org_id: int):
        self.db = db
        self.org_id = org_id
        self.config = self._get_config()
    
    def _get_config(self) -> Optional[ConfiguracionFacturacion]:
        """Obtiene la configuración de facturación de la organización"""
        return self.db.query(ConfiguracionFacturacion).filter(
            ConfiguracionFacturacion.organization_id == self.org_id,
            ConfiguracionFacturacion.activo == True
        ).first()
    
    def esta_configurado(self) -> bool:
        """Verifica si la facturación está configurada"""
        return self.config is not None and self.config.facturalo_token is not None
    
    async def emitir_comprobante_por_pago(
        self, 
        payment_id: int,
        tipo: str = "03",  # '03' = Boleta por defecto
        forzar_datos_cliente: Dict = None
    ) -> Dict[str, Any]:
        """
        Emite un comprobante electrónico a partir de un pago aprobado
        
        Args:
            payment_id: ID del pago
            tipo: '01' = Factura, '03' = Boleta
            forzar_datos_cliente: Dict con {tipo_doc, num_doc, nombre, direccion} si el cliente es diferente al colegiado
        
        Returns:
            Dict con el resultado de la operación
        """
        if not self.esta_configurado():
            return {"success": False, "error": "Facturación no configurada"}
        
        # Verificar que no exista comprobante para este pago
        existe = self.db.query(Comprobante).filter(
            Comprobante.payment_id == payment_id
        ).first()
        
        if existe:
            return {"success": False, "error": "Ya existe comprobante para este pago", "comprobante_id": existe.id}
        
        # Obtener el pago
        payment = self.db.query(Payment).filter(Payment.id == payment_id).first()
        if not payment:
            return {"success": False, "error": "Pago no encontrado"}
        
        if payment.status != "approved":
            return {"success": False, "error": "El pago no está aprobado"}
        
        # Obtener datos del cliente
        cliente = self._obtener_datos_cliente(payment, forzar_datos_cliente)
        
        # Determinar serie y número
        if tipo == "01":  # Factura
            serie = self.config.serie_factura
            numero = self.config.ultimo_numero_factura + 1
        else:  # Boleta
            serie = self.config.serie_boleta
            numero = self.config.ultimo_numero_boleta + 1
        
        # Construir items
        items = self._construir_items(payment)
        
        # Calcular totales
        subtotal = payment.amount
        igv = subtotal * (self.config.porcentaje_igv / 100) if self.config.porcentaje_igv > 0 else 0
        total = subtotal + igv
        
        # Crear comprobante en BD (estado pending)
        comprobante = Comprobante(
            organization_id=self.org_id,
            payment_id=payment_id,
            tipo=tipo,
            serie=serie,
            numero=numero,
            subtotal=subtotal,
            igv=igv,
            total=total,
            cliente_tipo_doc=cliente["tipo_doc"],
            cliente_num_doc=cliente["num_doc"],
            cliente_nombre=cliente["nombre"],
            cliente_direccion=cliente.get("direccion"),
            cliente_email=cliente.get("email"),
            items=items,
            status="pending"
        )
        self.db.add(comprobante)
        self.db.flush()  # Para obtener el ID
        
        # Enviar a facturalo.pro
        resultado = await self._enviar_a_facturalo(comprobante)
        
        if resultado["success"]:
            # Actualizar comprobante con respuesta
            comprobante.status = "accepted"
            comprobante.facturalo_id = resultado.get("facturalo_id")
            comprobante.facturalo_response = resultado.get("response")
            comprobante.sunat_response_code = resultado.get("sunat_code", "0")
            comprobante.sunat_response_description = resultado.get("sunat_description")
            comprobante.sunat_hash = resultado.get("hash")
            comprobante.pdf_url = resultado.get("pdf_url")
            comprobante.xml_url = resultado.get("xml_url")
            comprobante.cdr_url = resultado.get("cdr_url")
            
            # Actualizar correlativo
            if tipo == "01":
                self.config.ultimo_numero_factura = numero
            else:
                self.config.ultimo_numero_boleta = numero
        else:
            comprobante.status = "rejected"
            comprobante.facturalo_response = resultado.get("response")
            comprobante.observaciones = resultado.get("error")
        
        self.db.commit()
        
        return {
            "success": resultado["success"],
            "comprobante_id": comprobante.id,
            "serie": serie,
            "numero": numero,
            "pdf_url": comprobante.pdf_url,
            "error": resultado.get("error")
        }
    
    def _obtener_datos_cliente(self, payment: Payment, forzar: Dict = None) -> Dict:
        """Obtiene los datos del cliente para el comprobante"""
        
        # Si se fuerzan datos (ej: empresa con RUC)
        if forzar:
            return {
                "tipo_doc": forzar.get("tipo_doc", "1"),
                "num_doc": forzar.get("num_doc"),
                "nombre": forzar.get("nombre"),
                "direccion": forzar.get("direccion"),
                "email": forzar.get("email")
            }
        
        # Si el pagador es tercero/empresa
        if payment.pagador_tipo == "empresa" and payment.pagador_documento:
            return {
                "tipo_doc": "6",  # RUC
                "num_doc": payment.pagador_documento,
                "nombre": payment.pagador_nombre,
                "direccion": None,
                "email": None
            }
        
        # Si el pagador es tercero con DNI
        if payment.pagador_tipo == "tercero" and payment.pagador_documento:
            return {
                "tipo_doc": "1",  # DNI
                "num_doc": payment.pagador_documento,
                "nombre": payment.pagador_nombre,
                "direccion": None,
                "email": None
            }
        
        # Por defecto: datos del colegiado
        colegiado = self.db.query(Colegiado).filter(
            Colegiado.id == payment.colegiado_id
        ).first()
        
        if colegiado:
            return {
                "tipo_doc": "1",  # DNI
                "num_doc": colegiado.dni,
                "nombre": colegiado.apellidos_nombres,
                "direccion": colegiado.direccion,
                "email": colegiado.email
            }
        
        # Fallback
        return {
            "tipo_doc": "0",  # Sin documento
            "num_doc": "00000000",
            "nombre": "CLIENTE VARIOS",
            "direccion": None,
            "email": None
        }
    
    def _construir_items(self, payment: Payment) -> list:
        """Construye los items del comprobante a partir del pago"""
        items = []
        
        # Si hay deudas relacionadas, crear un item por cada una
        # Por ahora, un solo item con el concepto del pago
        items.append({
            "codigo": "SRV001",
            "descripcion": payment.notes or "Cuotas de colegiatura",
            "unidad": "ZZ",  # Unidad de medida: servicio
            "cantidad": 1,
            "precio_unitario": payment.amount,
            "valor_venta": payment.amount,
            "tipo_afectacion_igv": self.config.tipo_afectacion_igv,  # '20' = Exonerado
            "igv": 0 if self.config.tipo_afectacion_igv == "20" else payment.amount * 0.18
        })
        
        return items
    
    async def _enviar_a_facturalo(self, comprobante: Comprobante) -> Dict:
        """
        Envía el comprobante a facturalo.pro
        
        Estructura esperada por facturalo.pro (a confirmar cuando esté la API):
        POST /api/v1/documents
        {
            "serie": "B001",
            "numero": 1,
            "tipo_documento": "03",
            "fecha_emision": "2025-02-07",
            "cliente": {...},
            "items": [...],
            "totales": {...}
        }
        """
        
        # Construir payload para facturalo.pro
        payload = {
            "tipo_documento": comprobante.tipo,
            "serie": comprobante.serie,
            "numero": comprobante.numero,
            "fecha_emision": comprobante.fecha_emision.strftime("%Y-%m-%d"),
            "moneda": comprobante.moneda,
            
            "cliente": {
                "tipo_documento": comprobante.cliente_tipo_doc,
                "numero_documento": comprobante.cliente_num_doc,
                "razon_social": comprobante.cliente_nombre,
                "direccion": comprobante.cliente_direccion,
                "email": comprobante.cliente_email
            },
            
            "items": comprobante.items,
            
            "totales": {
                "subtotal": comprobante.subtotal,
                "igv": comprobante.igv,
                "total": comprobante.total
            }
        }
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.config.facturalo_url}/documents",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self.config.facturalo_token}",
                        "Content-Type": "application/json",
                        "X-Empresa-ID": self.config.facturalo_empresa_id
                    }
                )
                
                data = response.json()
                
                if response.status_code == 200 or response.status_code == 201:
                    return {
                        "success": True,
                        "facturalo_id": data.get("id"),
                        "response": data,
                        "sunat_code": data.get("sunat_response", {}).get("code", "0"),
                        "sunat_description": data.get("sunat_response", {}).get("description"),
                        "hash": data.get("hash"),
                        "pdf_url": data.get("links", {}).get("pdf"),
                        "xml_url": data.get("links", {}).get("xml"),
                        "cdr_url": data.get("links", {}).get("cdr")
                    }
                else:
                    return {
                        "success": False,
                        "error": data.get("message", "Error desconocido"),
                        "response": data
                    }
                    
        except httpx.TimeoutException:
            return {"success": False, "error": "Timeout conectando a facturalo.pro"}
        except httpx.RequestError as e:
            return {"success": False, "error": f"Error de conexión: {str(e)}"}
        except Exception as e:
            return {"success": False, "error": f"Error inesperado: {str(e)}"}
    
    def obtener_comprobante(self, comprobante_id: int) -> Optional[Comprobante]:
        """Obtiene un comprobante por ID"""
        return self.db.query(Comprobante).filter(
            Comprobante.id == comprobante_id,
            Comprobante.organization_id == self.org_id
        ).first()
    
    def obtener_comprobante_por_pago(self, payment_id: int) -> Optional[Comprobante]:
        """Obtiene el comprobante asociado a un pago"""
        return self.db.query(Comprobante).filter(
            Comprobante.payment_id == payment_id
        ).first()
    
    def listar_comprobantes(
        self, 
        limit: int = 50, 
        offset: int = 0,
        tipo: str = None,
        status: str = None
    ) -> list:
        """Lista comprobantes de la organización"""
        query = self.db.query(Comprobante).filter(
            Comprobante.organization_id == self.org_id
        )
        
        if tipo:
            query = query.filter(Comprobante.tipo == tipo)
        if status:
            query = query.filter(Comprobante.status == status)
        
        return query.order_by(Comprobante.created_at.desc()).offset(offset).limit(limit).all()


# ============================================================
# Función helper para usar en validación de pagos
# ============================================================

async def emitir_comprobante_automatico(db: Session, payment_id: int) -> Dict:
    """
    Función helper para emitir comprobante automáticamente al aprobar un pago
    Se llama desde el endpoint de validación de pagos
    """
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment:
        return {"success": False, "error": "Pago no encontrado"}
    
    # Obtener configuración
    config = db.query(ConfiguracionFacturacion).filter(
        ConfiguracionFacturacion.organization_id == payment.organization_id,
        ConfiguracionFacturacion.activo == True,
        ConfiguracionFacturacion.emitir_automatico == True
    ).first()
    
    if not config:
        return {"success": False, "error": "Emisión automática no configurada"}
    
    # Determinar tipo de comprobante
    # Si el pagador es empresa con RUC → Factura, sino → Boleta
    tipo = "01" if payment.pagador_tipo == "empresa" else "03"
    
    # Emitir
    service = FacturacionService(db, payment.organization_id)
    return await service.emitir_comprobante_por_pago(payment_id, tipo)
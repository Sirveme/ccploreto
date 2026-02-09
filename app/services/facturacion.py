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
        """Construye los items del comprobante a partir del pago con descripción detallada"""
        from app.models import Debt, Colegiado
        
        items = []
        
        # Obtener las deudas pagadas con este pago
        # Opción 1: Si existe tabla de asignaciones
        # allocations = self.db.query(PaymentAllocation).filter(
        #     PaymentAllocation.payment_id == payment.id
        # ).all()
        
        # Opción 2: Buscar deudas que fueron pagadas recientemente por este colegiado
        deudas_pagadas = self.db.query(Debt).filter(
            Debt.colegiado_id == payment.colegiado_id,
            Debt.status == "paid"
        ).order_by(Debt.periodo.asc()).limit(12).all()
        
        if deudas_pagadas:
            # Agrupar por concepto
            conceptos = {}
            for deuda in deudas_pagadas:
                concepto = deuda.concept or "Cuota ordinaria"
                if concepto not in conceptos:
                    conceptos[concepto] = {
                        "periodos": [],
                        "monto_total": 0
                    }
                if deuda.periodo:
                    conceptos[concepto]["periodos"].append(deuda.periodo)
                conceptos[concepto]["monto_total"] += float(deuda.amount or 0)
            
            # Construir descripción para cada concepto
            for concepto, datos in conceptos.items():
                periodos = datos["periodos"]
                cantidad = len(periodos) if periodos else 1
                
                # Construir texto de periodos
                if periodos:
                    # Formatear: "Enero 2026, Febrero 2026, Marzo 2026" -> "Enero, Febrero, Marzo 2026"
                    periodos_formateados = self._formatear_periodos(periodos)
                    descripcion = f"{concepto} {periodos_formateados}"
                    if cantidad > 1:
                        descripcion += f" ({cantidad} meses)"
                else:
                    descripcion = concepto
                
                items.append({
                    "codigo": "SRV001",
                    "descripcion": descripcion.upper(),
                    "unidad": "ZZ",
                    "cantidad": cantidad,
                    "precio_unitario": round(payment.amount / cantidad, 2),
                    "valor_venta": payment.amount,
                    "tipo_afectacion_igv": self.config.tipo_afectacion_igv,
                    "igv": 0 if self.config.tipo_afectacion_igv == "20" else payment.amount * 0.18
                })
        
        # Si no hay deudas, usar descripción genérica mejorada
        if not items:
            # Obtener datos del colegiado para contexto
            colegiado = self.db.query(Colegiado).filter(
                Colegiado.id == payment.colegiado_id
            ).first()
            
            matricula = colegiado.codigo_matricula if colegiado else ""
            descripcion = payment.notes or "Pago de cuotas de colegiatura"
            
            # Agregar referencia al pago
            if payment.operation_code:
                descripcion += f" - {payment.payment_method or ''} Nº {payment.operation_code}"
            
            if matricula:
                descripcion = f"COD {matricula} - {descripcion}"
            
            items.append({
                "codigo": "SRV001",
                "descripcion": descripcion.upper(),
                "unidad": "ZZ",
                "cantidad": 1,
                "precio_unitario": payment.amount,
                "valor_venta": payment.amount,
                "tipo_afectacion_igv": self.config.tipo_afectacion_igv,
                "igv": 0 if self.config.tipo_afectacion_igv == "20" else payment.amount * 0.18
            })
        
        return items

    def _formatear_periodos(self, periodos: list) -> str:
        """
        Formatea lista de periodos de forma legible.
        
        Entrada: ["Enero 2026", "Febrero 2026", "Marzo 2026"]
        Salida: "Enero, Febrero, Marzo 2026"
        
        Entrada: ["2026-01", "2026-02", "2026-03"]
        Salida: "Enero, Febrero, Marzo 2026"
        """
        if not periodos:
            return ""
        
        meses_es = {
            "01": "Enero", "02": "Febrero", "03": "Marzo", "04": "Abril",
            "05": "Mayo", "06": "Junio", "07": "Julio", "08": "Agosto",
            "09": "Septiembre", "10": "Octubre", "11": "Noviembre", "12": "Diciembre",
            "1": "Enero", "2": "Febrero", "3": "Marzo", "4": "Abril",
            "5": "Mayo", "6": "Junio", "7": "Julio", "8": "Agosto",
            "9": "Septiembre", "10": "Octubre", "11": "Noviembre", "12": "Diciembre"
        }
        
        parsed = []
        years = set()
        
        for p in periodos:
            p_str = str(p).strip()
            
            # Formato "2026-01" o "2026-1"
            if "-" in p_str and len(p_str.split("-")) == 2:
                year, mes = p_str.split("-")
                mes_nombre = meses_es.get(mes.zfill(2), mes)
                parsed.append(mes_nombre)
                years.add(year)
            
            # Formato "Enero 2026"
            elif " " in p_str:
                partes = p_str.split(" ")
                mes_nombre = partes[0]
                parsed.append(mes_nombre)
                if len(partes) > 1:
                    years.add(partes[1])
            
            # Formato desconocido, usar tal cual
            else:
                parsed.append(p_str)
        
        # Construir resultado
        if parsed:
            meses_str = ", ".join(parsed)
            if years:
                year = sorted(years)[-1]  # Último año
                return f"{meses_str} {year}"
            return meses_str
        
        return ", ".join(periodos)
    
    # REEMPLAZAR el método _enviar_a_facturalo() en app/services/facturacion.py

    async def _enviar_a_facturalo(self, comprobante: Comprobante) -> Dict:
        """
        Envía el comprobante a facturalo.pro
        """
        from datetime import datetime
        import pytz
        
        # Hora de Perú
        peru_tz = pytz.timezone('America/Lima')
        ahora = datetime.now(peru_tz)
        
        # Construir payload según especificación facturalo.pro
        payload = {
            "tipo_comprobante": comprobante.tipo,  # '03' boleta, '01' factura
            "fecha_emision": ahora.strftime("%Y-%m-%d"),
            "hora_emision": ahora.strftime("%H:%M:%S"),
            "cliente": {
                "tipo_documento": comprobante.cliente_tipo_doc,
                "numero_documento": comprobante.cliente_num_doc,
                "razon_social": comprobante.cliente_nombre,
                "direccion": comprobante.cliente_direccion,
                "email": comprobante.cliente_email
            },
            "items": [{
                "descripcion": item.get("descripcion", "Cuotas de colegiatura"),
                "cantidad": item.get("cantidad", 1),
                "unidad_medida": "ZZ",
                "precio_unitario": item.get("precio_unitario", comprobante.total),
                "tipo_afectacion_igv": self.config.tipo_afectacion_igv  # '20' exonerado
            } for item in (comprobante.items or [{"descripcion": "Cuotas de colegiatura", "precio_unitario": comprobante.total}])],
            "enviar_email": bool(comprobante.cliente_email),
            "referencia_externa": f"PAGO-{comprobante.payment_id}"
        }
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.config.facturalo_url}/comprobantes",  # Endpoint correcto
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "X-API-Key": self.config.facturalo_token,
                        "X-API-Secret": self.config.facturalo_secret  # Nuevo campo
                    }
                )
                
                data = response.json()
                
                if response.status_code in [200, 201] and data.get("exito"):
                    comp_data = data.get("comprobante", {})
                    archivos = data.get("archivos", {})
                    return {
                        "success": True,
                        "facturalo_id": comp_data.get("id"),
                        "response": data,
                        "sunat_code": comp_data.get("codigo_sunat", "0"),
                        "sunat_description": comp_data.get("mensaje_sunat"),
                        "hash": comp_data.get("hash_cpe"),
                        "pdf_url": archivos.get("pdf_url"),
                        "xml_url": archivos.get("xml_url"),
                        "cdr_url": archivos.get("cdr_url"),
                        "numero_formato": comp_data.get("numero_formato")
                    }
                else:
                    return {
                        "success": False,
                        "error": data.get("mensaje", data.get("error", "Error desconocido")),
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
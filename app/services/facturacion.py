"""
Servicio: Facturación Electrónica
app/services/facturacion.py

Integración con facturalo.pro para emisión de comprobantes

v4 - Cambios:
- Descripción de items en 3 líneas:
  L1: CUOTA ORDINARIA ENERO, FEBRERO 2026 (2 MESES)
  L2: RESTUCCIA ESLAVA, DUILIO CESAR
  L3: DNI [05393776] Cód. Matr. [10-2244]
- Pasa estado_colegiado, habil_hasta, url_consulta a facturalo
- Dirección del pagador (empresa) para facturas
"""

import httpx
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models import (
    Comprobante,
    ConfiguracionFacturacion,
    Payment,
    Colegiado,
    Debt,
    Organization
)


class FacturacionService:
    """Servicio para emitir comprobantes electrónicos vía facturalo.pro"""

    def __init__(self, db: Session, org_id: int):
        self.db = db
        self.org_id = org_id
        self.config = self._get_config()

    def _get_config(self) -> Optional[ConfiguracionFacturacion]:
        return self.db.query(ConfiguracionFacturacion).filter(
            ConfiguracionFacturacion.organization_id == self.org_id,
            ConfiguracionFacturacion.activo == True
        ).first()

    def esta_configurado(self) -> bool:
        return self.config is not None and self.config.facturalo_token is not None

    async def emitir_comprobante_por_pago(
        self,
        payment_id: int,
        tipo: str = "03",
        forzar_datos_cliente: Dict = None
    ) -> Dict[str, Any]:
        """
        Emite un comprobante electrónico a partir de un pago aprobado.

        Args:
            payment_id: ID del pago
            tipo: '01' = Factura, '03' = Boleta
            forzar_datos_cliente: {tipo_doc, num_doc, nombre, direccion, email}
        """
        if not self.esta_configurado():
            return {"success": False, "error": "Facturación no configurada"}

        existe = self.db.query(Comprobante).filter(
            Comprobante.payment_id == payment_id
        ).first()
        if existe:
            return {"success": False, "error": "Ya existe comprobante para este pago",
                    "comprobante_id": existe.id}

        payment = self.db.query(Payment).filter(Payment.id == payment_id).first()
        if not payment:
            return {"success": False, "error": "Pago no encontrado"}
        if payment.status != "approved":
            return {"success": False, "error": "El pago no está aprobado"}

        # Datos del cliente según tipo de comprobante
        cliente = self._obtener_datos_cliente(payment, forzar_datos_cliente)

        # Serie y número
        if tipo == "01":
            serie = self.config.serie_factura
            numero = self.config.ultimo_numero_factura + 1
        else:
            serie = self.config.serie_boleta
            numero = self.config.ultimo_numero_boleta + 1

        # Items con descripción en 3 líneas
        items = self._construir_items(payment, tipo)

        # Totales
        subtotal = payment.amount
        igv = subtotal * (self.config.porcentaje_igv / 100) if self.config.porcentaje_igv > 0 else 0
        total = subtotal + igv

        # Obtener datos del colegiado para campos extra
        colegiado = self.db.query(Colegiado).filter(
            Colegiado.id == payment.colegiado_id
        ).first()

        # Estado de habilidad y fecha vigencia
        estado_colegiado = None
        habil_hasta = None
        matricula = None
        if colegiado:
            matricula = colegiado.codigo_matricula
            estado_colegiado = "HÁBIL" if getattr(colegiado, 'habilitado', False) else "INHÁBIL"
            # Calcular vigencia: último periodo pagado
            habil_hasta = self._calcular_vigencia(colegiado.id)

        # URL de consulta del emisor
        org = self.db.query(Organization).filter(
            Organization.id == self.org_id
        ).first()
        url_consulta = None
        if org:
            slug = getattr(org, 'slug', None) or getattr(org, 'domain', None)
            if slug:
                url_consulta = f"{slug}/consulta/habilidad"

        # Crear comprobante en BD
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
        self.db.flush()

        # Enviar a facturalo.pro con campos extra
        resultado = await self._enviar_a_facturalo(
            comprobante,
            codigo_matricula=matricula,
            estado_colegiado=estado_colegiado,
            habil_hasta=habil_hasta,
            url_consulta=url_consulta
        )

        if resultado["success"]:
            comprobante.status = "accepted"
            comprobante.facturalo_id = resultado.get("facturalo_id")
            comprobante.facturalo_response = resultado.get("response")
            comprobante.sunat_response_code = resultado.get("sunat_code", "0")
            comprobante.sunat_response_description = resultado.get("sunat_description")
            comprobante.sunat_hash = resultado.get("hash")
            comprobante.pdf_url = resultado.get("pdf_url")
            comprobante.xml_url = resultado.get("xml_url")
            comprobante.cdr_url = resultado.get("cdr_url")

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
        """
        Datos del cliente para el comprobante.
        Factura: empresa que paga (RUC + dirección obligatoria)
        Boleta: colegiado (DNI)
        """
        if forzar:
            return {
                "tipo_doc": forzar.get("tipo_doc", "1"),
                "num_doc": forzar.get("num_doc"),
                "nombre": forzar.get("nombre"),
                "direccion": forzar.get("direccion"),
                "email": forzar.get("email")
            }

        # Empresa con RUC → Factura
        if payment.pagador_tipo == "empresa" and payment.pagador_documento:
            return {
                "tipo_doc": "6",  # RUC
                "num_doc": payment.pagador_documento,
                "nombre": payment.pagador_nombre,
                "direccion": getattr(payment, 'pagador_direccion', None),
                "email": None
            }

        # Tercero con DNI
        if payment.pagador_tipo == "tercero" and payment.pagador_documento:
            return {
                "tipo_doc": "1",
                "num_doc": payment.pagador_documento,
                "nombre": payment.pagador_nombre,
                "direccion": None,
                "email": None
            }

        # Colegiado
        colegiado = self.db.query(Colegiado).filter(
            Colegiado.id == payment.colegiado_id
        ).first()

        if colegiado:
            return {
                "tipo_doc": "1",
                "num_doc": colegiado.dni,
                "nombre": colegiado.apellidos_nombres,
                "direccion": colegiado.direccion,
                "email": colegiado.email,
                "matricula": colegiado.codigo_matricula
            }

        return {
            "tipo_doc": "0",
            "num_doc": "00000000",
            "nombre": "CLIENTE VARIOS",
            "direccion": None,
            "email": None
        }

    def _construir_items(self, payment: Payment, tipo_comprobante: str = "03") -> list:
        """
        Items con descripción en 3 líneas separadas por \\n:
          L1: CUOTA ORDINARIA ENERO, FEBRERO 2026 (2 MESES)
          L2: RESTUCCIA ESLAVA, DUILIO CESAR
          L3: DNI [05393776] Cód. Matr. [10-2244]

        El \\n es renderizado por pdf_generator.py como líneas separadas.
        """
        items = []

        # Datos del colegiado para líneas 2 y 3
        colegiado = self.db.query(Colegiado).filter(
            Colegiado.id == payment.colegiado_id
        ).first()

        linea_nombre = ""
        linea_docs = ""
        if colegiado:
            linea_nombre = colegiado.apellidos_nombres or ""
            dni = colegiado.dni or ""
            matr = colegiado.codigo_matricula or ""
            linea_docs = f"DNI [{dni}] Cód. Matr. [{matr}]"

        # Buscar deudas pagadas
        deudas_pagadas = self.db.query(Debt).filter(
            Debt.colegiado_id == payment.colegiado_id,
            Debt.status == "paid"
        ).order_by(Debt.periodo.asc()).limit(12).all()

        if deudas_pagadas:
            conceptos = {}
            for deuda in deudas_pagadas:
                concepto = deuda.concept or "Cuota ordinaria"
                if concepto not in conceptos:
                    conceptos[concepto] = {"periodos": [], "monto_total": 0}
                if deuda.periodo:
                    conceptos[concepto]["periodos"].append(deuda.periodo)
                conceptos[concepto]["monto_total"] += float(deuda.amount or 0)

            for concepto, datos in conceptos.items():
                periodos = datos["periodos"]
                cantidad = len(periodos) if periodos else 1

                # Línea 1: concepto + periodos
                if periodos:
                    periodos_fmt = self._formatear_periodos(periodos)
                    linea_1 = f"{concepto} {periodos_fmt}"
                    if cantidad > 1:
                        linea_1 += f" ({cantidad} meses)"
                else:
                    linea_1 = concepto

                # 3 líneas separadas por \n
                descripcion = linea_1.upper()
                if linea_nombre:
                    descripcion += f"\n{linea_nombre}"
                if linea_docs:
                    descripcion += f"\n{linea_docs}"

                items.append({
                    "codigo": "SRV001",
                    "descripcion": descripcion,
                    "unidad": "ZZ",
                    "cantidad": cantidad,
                    "precio_unitario": round(payment.amount / cantidad, 2),
                    "valor_venta": payment.amount,
                    "tipo_afectacion_igv": self.config.tipo_afectacion_igv,
                    "igv": 0 if self.config.tipo_afectacion_igv == "20" else payment.amount * 0.18
                })

        # Fallback si no hay deudas
        if not items:
            linea_1 = payment.notes or "Pago de cuotas de colegiatura"
            if payment.operation_code:
                linea_1 += f" - {payment.payment_method or ''} Nº {payment.operation_code}"

            descripcion = linea_1.upper()
            if linea_nombre:
                descripcion += f"\n{linea_nombre}"
            if linea_docs:
                descripcion += f"\n{linea_docs}"

            items.append({
                "codigo": "SRV001",
                "descripcion": descripcion,
                "unidad": "ZZ",
                "cantidad": 1,
                "precio_unitario": payment.amount,
                "valor_venta": payment.amount,
                "tipo_afectacion_igv": self.config.tipo_afectacion_igv,
                "igv": 0 if self.config.tipo_afectacion_igv == "20" else payment.amount * 0.18
            })

        return items

    def _calcular_vigencia(self, colegiado_id: int) -> Optional[str]:
        """
        Calcula fecha de vigencia de habilidad basada en el último periodo pagado.
        Ej: Si el último periodo pagado es "2026-03", vigente hasta "31/03/2026".

        Retorna string "DD/MM/YYYY" o None si no se puede calcular.
        """
        import calendar

        ultima_deuda = self.db.query(Debt).filter(
            Debt.colegiado_id == colegiado_id,
            Debt.status == "paid"
        ).order_by(Debt.periodo.desc()).first()

        if not ultima_deuda or not ultima_deuda.periodo:
            return None

        periodo = str(ultima_deuda.periodo).strip()

        try:
            # Formato "2026-03"
            if "-" in periodo and len(periodo.split("-")) == 2:
                year, mes = periodo.split("-")
                year = int(year)
                mes = int(mes)
                ultimo_dia = calendar.monthrange(year, mes)[1]
                return f"{ultimo_dia:02d}/{mes:02d}/{year}"

            # Formato "Marzo 2026"
            meses_map = {
                "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
                "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
                "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12
            }
            partes = periodo.lower().split()
            if len(partes) == 2 and partes[0] in meses_map:
                mes = meses_map[partes[0]]
                year = int(partes[1])
                ultimo_dia = calendar.monthrange(year, mes)[1]
                return f"{ultimo_dia:02d}/{mes:02d}/{year}"
        except (ValueError, KeyError):
            pass

        return None

    def _formatear_periodos(self, periodos: list) -> str:
        """
        Formatea periodos: ["2026-01","2026-02","2026-03"] -> "Enero, Febrero, Marzo 2026"
        """
        if not periodos:
            return ""

        meses_es = {
            "01": "Enero", "02": "Febrero", "03": "Marzo", "04": "Abril",
            "05": "Mayo", "06": "Junio", "07": "Julio", "08": "Agosto",
            "09": "Septiembre", "10": "Octubre", "11": "Noviembre", "12": "Diciembre",
        }

        parsed = []
        years = set()

        for p in periodos:
            p_str = str(p).strip()
            if "-" in p_str and len(p_str.split("-")) == 2:
                year, mes = p_str.split("-")
                mes_nombre = meses_es.get(mes.zfill(2), mes)
                parsed.append(mes_nombre)
                years.add(year)
            elif " " in p_str:
                partes = p_str.split(" ")
                parsed.append(partes[0])
                if len(partes) > 1:
                    years.add(partes[1])
            else:
                parsed.append(p_str)

        if parsed:
            meses_str = ", ".join(parsed)
            if years:
                return f"{meses_str} {sorted(years)[-1]}"
            return meses_str

        return ", ".join(periodos)

    async def _enviar_a_facturalo(self, comprobante: Comprobante,
                                   codigo_matricula=None, estado_colegiado=None,
                                   habil_hasta=None, url_consulta=None) -> Dict:
        """Envía el comprobante a facturalo.pro con campos extra para el PDF"""

        payload = {
            "tipo_comprobante": comprobante.tipo,
            "codigo_matricula": codigo_matricula,
            "estado_colegiado": estado_colegiado,
            "habil_hasta": habil_hasta,
            "url_consulta": url_consulta,
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
                "tipo_afectacion_igv": self.config.tipo_afectacion_igv
            } for item in (comprobante.items or [{
                "descripcion": "Cuotas de colegiatura",
                "precio_unitario": comprobante.total
            }])],
            "enviar_email": bool(comprobante.cliente_email),
            "referencia_externa": f"PAGO-{comprobante.payment_id}"
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.config.facturalo_url}/comprobantes",
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "X-API-Key": self.config.facturalo_token,
                        "X-API-Secret": self.config.facturalo_secret
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

    def _obtener_matricula(self, payment_id: int) -> str:
        payment = self.db.query(Payment).filter(Payment.id == payment_id).first()
        if payment and payment.colegiado_id:
            colegiado = self.db.query(Colegiado).filter(
                Colegiado.id == payment.colegiado_id).first()
            if colegiado:
                return colegiado.codigo_matricula
        return None

    def obtener_comprobante(self, comprobante_id: int) -> Optional[Comprobante]:
        return self.db.query(Comprobante).filter(
            Comprobante.id == comprobante_id,
            Comprobante.organization_id == self.org_id
        ).first()

    def obtener_comprobante_por_pago(self, payment_id: int) -> Optional[Comprobante]:
        return self.db.query(Comprobante).filter(
            Comprobante.payment_id == payment_id
        ).first()

    def listar_comprobantes(self, limit=50, offset=0, tipo=None, status=None) -> list:
        query = self.db.query(Comprobante).filter(
            Comprobante.organization_id == self.org_id)
        if tipo:
            query = query.filter(Comprobante.tipo == tipo)
        if status:
            query = query.filter(Comprobante.status == status)
        return query.order_by(Comprobante.created_at.desc()).offset(offset).limit(limit).all()


# ============================================================
# Helper para emisión automática
# ============================================================

async def emitir_comprobante_automatico(db: Session, payment_id: int) -> Dict:
    """Emite comprobante al aprobar un pago (se llama desde endpoint de validación)"""
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment:
        return {"success": False, "error": "Pago no encontrado"}

    config = db.query(ConfiguracionFacturacion).filter(
        ConfiguracionFacturacion.organization_id == payment.organization_id,
        ConfiguracionFacturacion.activo == True,
        ConfiguracionFacturacion.emitir_automatico == True
    ).first()
    if not config:
        return {"success": False, "error": "Emisión automática no configurada"}

    tipo = "01" if payment.pagador_tipo == "empresa" else "03"
    service = FacturacionService(db, payment.organization_id)
    return await service.emitir_comprobante_por_pago(payment_id, tipo)
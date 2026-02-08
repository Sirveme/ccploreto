"""
Router: Pagos Públicos para Colegiados
======================================
Permite a colegiados consultar deuda y registrar pagos SIN necesidad de login.
Identificación por DNI o código de matrícula.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, text
from datetime import datetime, timezone
from typing import Optional
import json
import base64
import os

from app.database import get_db
from app.models import Colegiado, Debt, Payment, Organization
from app.routers.ws import manager
from app.services.emitir_certificado_service import emitir_certificado_automatico

import io
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/pagos", tags=["Pagos Públicos"])


# ==========================================
# HELPERS
# ==========================================

def get_org_finanzas_config(org: dict, key: str, default=None):
    """Obtiene configuración de finanzas de la organización"""
    config = org.get("config", {}) or {}
    finanzas = config.get("finanzas", {}) or {}
    return finanzas.get(key, default)


def calcular_deuda_total(db: Session, colegiado_id: int) -> dict:
    """Calcula la deuda total y detalle de un colegiado"""
    deudas = db.query(Debt).filter(
        Debt.colegiado_id == colegiado_id,
        Debt.status.in_(["pending", "partial"])
    ).order_by(Debt.due_date.asc(), Debt.created_at.asc()).all()
    
    total = sum(d.balance for d in deudas)
    
    return {
        "total": total,
        "cantidad_cuotas": len(deudas),
        "detalle": [
            {
                "id": d.id,
                "concepto": d.concept,
                "periodo": d.periodo,
                "monto_original": d.amount,
                "saldo": d.balance,
                "vencimiento": d.due_date.strftime("%d/%m/%Y") if d.due_date else None
            }
            for d in deudas
        ]
    }


def obtener_beneficio_aplicable(org: dict, deuda_total: float):
    """Verifica si hay beneficio vigente y calcula descuento"""
    beneficios = get_org_finanzas_config(org, "beneficios_activos", [])
    hoy = datetime.now().date()
    
    for b in beneficios:
        try:
            fecha_inicio = datetime.strptime(b["fecha_inicio"], "%Y-%m-%d").date()
            fecha_fin = datetime.strptime(b["fecha_fin"], "%Y-%m-%d").date()
            if fecha_inicio <= hoy <= fecha_fin:
                descuento = b.get("descuento_porcentaje", 0) / 100
                monto_con_descuento = deuda_total * (1 - descuento)
                return {
                    "aplicable": True,
                    "nombre": b["nombre"],
                    "descuento_porcentaje": b["descuento_porcentaje"],
                    "monto_con_descuento": round(monto_con_descuento, 2),
                    "ahorro": round(deuda_total - monto_con_descuento, 2)
                }
        except:
            continue
    
    return {
        "aplicable": False,
        "nombre": None,
        "descuento_porcentaje": 0,
        "monto_con_descuento": deuda_total,
        "ahorro": 0
    }


# ==========================================
# ENDPOINTS API (JSON)
# ==========================================

@router.get("/deuda/{identificador}")
async def consultar_deuda(
    request: Request,
    identificador: str,
    db: Session = Depends(get_db)
):
    """Consulta la deuda de un colegiado por DNI o matrícula."""
    org = request.state.org
    if not org:
        raise HTTPException(status_code=400, detail="Organización no identificada")
    
    identificador = identificador.strip()
    
    colegiado = db.query(Colegiado).filter(
        Colegiado.organization_id == org["id"],
        (Colegiado.dni == identificador) | (Colegiado.codigo_matricula == identificador)
    ).first()
    
    if not colegiado:
        raise HTTPException(status_code=404, detail="Colegiado no encontrado")
    
    deuda_info = calcular_deuda_total(db, colegiado.id)
    beneficio = obtener_beneficio_aplicable(org, deuda_info["total"])
    
    return {
        "encontrado": True,
        "colegiado": {
            "id": colegiado.id,
            "dni": colegiado.dni,
            "codigo_matricula": colegiado.codigo_matricula,
            "apellidos_nombres": colegiado.apellidos_nombres,
            "condicion": colegiado.condicion,
            "email": colegiado.email,
            "telefono": colegiado.telefono
        },
        "deuda": deuda_info,
        "beneficio": beneficio,
        "metodos_pago": get_org_finanzas_config(org, "metodos_pago", [])
    }


@router.post("/registrar")
async def registrar_pago(
    request: Request,
    colegiado_id: int = Form(...),
    monto: float = Form(...),
    metodo_pago: str = Form(...),
    numero_operacion: str = Form(None),
    pagador_tipo: str = Form("titular"),
    pagador_nombre: str = Form(None),
    pagador_documento: str = Form(None),
    notas: str = Form(None),
    voucher: UploadFile = File(None),
    tipo_comprobante: str = Form("recibo"),       # ← NUEVO
    ruc_factura: str = Form(None),                 # ← NUEVO
    razon_social: str = Form(None),                # ← NUEVO
    requiere_certificado: str = Form(None),        # ← NUEVO
    db: Session = Depends(get_db)
):
    """Registra un pago de colegiado (sin login)."""
    org = request.state.org
    if not org:
        raise HTTPException(status_code=400, detail="Organización no identificada")
    
    # Validar: debe tener código O voucher
    if not numero_operacion and (not voucher or not voucher.filename):
        return HTMLResponse('''
            <div class="bg-red-900/50 border border-red-500 text-red-200 p-3 rounded-lg text-sm">
                ❌ Debes ingresar el código de operación o subir el voucher.
            </div>
        ''')
    
    colegiado = db.query(Colegiado).filter(
        Colegiado.id == colegiado_id,
        Colegiado.organization_id == org["id"]
    ).first()
    
    if not colegiado:
        raise HTTPException(status_code=404, detail="Colegiado no encontrado")
    
    # Verificar duplicado de código
    if numero_operacion:
        existe = db.query(Payment).filter(
            Payment.organization_id == org["id"],
            Payment.operation_code == numero_operacion,
            Payment.status != "rejected"
        ).first()
        
        if existe:
            return HTMLResponse('''
                <div class="bg-red-900/50 border border-red-500 text-red-200 p-3 rounded-lg text-sm">
                    ❌ Este código de operación ya fue registrado anteriormente.
                </div>
            ''')
    
    # Procesar voucher
    voucher_url = None
    if voucher and voucher.filename:
        contents = await voucher.read()
        img_str = base64.b64encode(contents).decode("utf-8")
        voucher_url = f"data:{voucher.content_type};base64,{img_str}"
    
    # Crear pago
    nuevo_pago = Payment(
        organization_id=org["id"],
        colegiado_id=colegiado_id,
        member_id=colegiado.member_id,
        amount=monto,
        currency="PEN",
        payment_method=metodo_pago,
        operation_code=numero_operacion or "Por validar en voucher",
        voucher_url=voucher_url,
        pagador_tipo=pagador_tipo,
        pagador_nombre=pagador_nombre if pagador_tipo != "titular" else None,
        pagador_documento=pagador_documento if pagador_tipo != "titular" else None,
        status="review",
        notes=notas
    )
    
    db.add(nuevo_pago)
    db.flush()
    
    # Verificar si el colegio acepta pagos sin validación
    certificado_auto = False
    #print(f"DEBUG PAGO: org_id={org['id']}")
    try:
        org_config = db.execute(
            text("SELECT config FROM organizations WHERE id = :oid"),
            {"oid": org["id"]}
        ).fetchone()
        #print(f"DEBUG CONFIG: {type(org_config.config) if org_config else 'NONE'}")
        if org_config and org_config.config:
            config = org_config.config if isinstance(org_config.config, dict) else json.loads(org_config.config)
            certificado_auto = config.get("finanzas", {}).get("validacion_automatica", False)
            #print(f"DEBUG AUTO: {certificado_auto}")
    except Exception as e:
        print(f"⚠️ Error leyendo config: {e}")
    
    certificado_info = None
    
    if certificado_auto:
        # Modo automático: aprobar pago + emitir certificado de inmediato
        nuevo_pago.status = "approved"
        nuevo_pago.reviewed_at = datetime.now(timezone.utc)
        
        # Imputar a deudas (FIFO)
        deudas = db.query(Debt).filter(
            Debt.colegiado_id == colegiado_id,
            Debt.status.in_(["pending", "partial"])
        ).order_by(Debt.due_date.asc(), Debt.created_at.asc()).all()
        
        monto_restante = nuevo_pago.amount
        for deuda in deudas:
            if monto_restante <= 0:
                break
            if monto_restante >= deuda.balance:
                monto_restante -= deuda.balance
                deuda.balance = 0
                deuda.status = "paid"
            else:
                deuda.balance -= monto_restante
                deuda.status = "partial"
                monto_restante = 0
        
        # Actualizar condición si quedó al día
        deudas_pendientes = db.query(Debt).filter(
            Debt.colegiado_id == colegiado_id,
            Debt.status.in_(["pending", "partial"])
        ).count()
        
        if deudas_pendientes == 0:
            colegiado_obj = db.query(Colegiado).filter(Colegiado.id == colegiado_id).first()
            if colegiado_obj and colegiado_obj.condicion == "inhabil":
                colegiado_obj.condicion = "habil"
                colegiado_obj.fecha_actualizacion_condicion = datetime.now(timezone.utc)
        
        db.flush()
        
        # ============================================
        # CERTIFICADO: Solo si lo solicitó
        # ============================================
        certificado_info = None
        if requiere_certificado == "1":
            try:
                certificado_info = emitir_certificado_automatico(
                    db=db,
                    colegiado_id=colegiado_id,
                    payment_id=nuevo_pago.id,
                    ip_origen=request.client.host if request.client else None
                )
            except Exception as e:
                print(f"⚠️ Error emitiendo certificado automático: {e}")
        
        # ============================================
        # COMPROBANTE: Según tipo seleccionado
        # ============================================
        comprobante_info = None
        if tipo_comprobante in ["boleta", "factura"]:
            try:
                from app.services.facturacion import FacturacionService
                service = FacturacionService(db, org["id"])
                
                if service.esta_configurado():
                    tipo_doc = "01" if tipo_comprobante == "factura" else "03"
                    
                    # Si es factura, forzar datos de empresa
                    forzar_datos = None
                    if tipo_comprobante == "factura" and ruc_factura:
                        forzar_datos = {
                            "tipo_doc": "6",  # RUC
                            "num_doc": ruc_factura,
                            "nombre": razon_social or "CLIENTE",
                            "direccion": None,
                            "email": None
                        }
                    
                    resultado = await service.emitir_comprobante_por_pago(
                        nuevo_pago.id, 
                        tipo=tipo_doc,
                        forzar_datos_cliente=forzar_datos
                    )
                    
                    if resultado.get("success"):
                        comprobante_info = resultado
                        print(f"✅ Comprobante emitido: {resultado.get('pdf_url')}")
                    else:
                        print(f"⚠️ Error comprobante: {resultado.get('error')}")
            except Exception as e:
                print(f"⚠️ Error emitiendo comprobante: {e}")

    
    db.commit()
    
    # Notificar a admins via WebSocket
    try:
        await manager.broadcast({
            "type": "NEW_PAYMENT_REPORT",
            "org_id": org["id"],
            "amount": f"S/ {monto}",
            "user": colegiado.apellidos_nombres[:30]
        })
    except:
        pass
    
    # ============================================
    # RESPUESTAS SEGÚN MODO
    # ============================================
    
    if certificado_auto:
        # Construir respuesta con documentos generados
        docs_html = ""
        
        # Certificado
        if certificado_info and certificado_info.get("emitido"):
            codigo = certificado_info["codigo"]
            vigencia = certificado_info["vigencia_hasta"]
            docs_html += f'''
                <div style="background: rgba(34,197,94,0.1); border: 1px solid rgba(34,197,94,0.3); border-radius: 10px; padding: 12px; margin-bottom: 10px;">
                    <p style="color: #22c55e; font-weight: 600; margin: 0 0 5px 0;">📜 Certificado de Habilidad</p>
                    <p style="color: var(--texto-gris, #888); font-size: 12px; margin: 0;">Código: {codigo}</p>
                    <p style="color: var(--texto-gris, #888); font-size: 12px; margin: 0 0 8px 0;">Vigente hasta: {vigencia}</p>
                    <a href="/api/certificados/descargar/{codigo}" target="_blank"
                       style="display: inline-block; background: #22c55e; color: #fff; padding: 8px 15px; border-radius: 20px; font-size: 12px; font-weight: 600; text-decoration: none;">
                        📥 DESCARGAR PDF
                    </a>
                </div>
            '''
        elif requiere_certificado == "1":
            docs_html += f'''
                <div style="background: rgba(234,179,8,0.1); border: 1px solid rgba(234,179,8,0.3); border-radius: 10px; padding: 12px; margin-bottom: 10px;">
                    <p style="color: #eab308; font-weight: 600; margin: 0 0 5px 0;">⚠️ Certificado no emitido</p>
                    <p style="color: var(--texto-gris, #888); font-size: 12px; margin: 0;">
                        {certificado_info.get("error", "Aún tienes deuda pendiente") if certificado_info else "Debes estar al día para obtener certificado"}
                    </p>
                </div>
            '''
        
        #comprobante_uuid = comprobante_info.get("external_id", "")
        # Comprobante
        if comprobante_info and comprobante_info.get("success"):
            tipo_nombre = "Factura" if tipo_comprobante == "factura" else "Boleta"
            pdf_url = comprobante_info.get("pdf_url", "")
            
            # Extraer UUID de la URL
            comprobante_uuid = ""
            if pdf_url and "/comprobantes/" in pdf_url:
                import re
                match = re.search(r'/comprobantes/([^/]+)/pdf', pdf_url)
                comprobante_uuid = match.group(1) if match else ""
            
            docs_html += f'''
                <div style="background: rgba(59,130,246,0.1); border: 1px solid rgba(59,130,246,0.3); border-radius: 10px; padding: 12px; margin-bottom: 10px;">
                    <p style="color: #3b82f6; font-weight: 600; margin: 0 0 5px 0;">📄 {tipo_nombre} Electrónica</p>
                    <p style="color: var(--texto-gris, #888); font-size: 12px; margin: 0 0 8px 0;">
                        {comprobante_info.get("serie", "")}-{comprobante_info.get("numero", "")}
                    </p>
                    {f'<a href="/pagos/comprobante/{comprobante_uuid}/pdf" target="_blank" style="display: inline-block; background: #3b82f6; color: #fff; padding: 8px 15px; border-radius: 20px; font-size: 12px; font-weight: 600; text-decoration: none;">📥 DESCARGAR PDF</a>' if comprobante_uuid else '<p style="color: #888; font-size: 11px;">PDF no disponible</p>'}
                </div>
            '''

        elif tipo_comprobante == "recibo":
            docs_html += f'''
                <div style="background: rgba(107,114,128,0.1); border: 1px solid rgba(107,114,128,0.3); border-radius: 10px; padding: 12px; margin-bottom: 10px;">
                    <p style="color: var(--texto-gris, #888); font-weight: 600; margin: 0 0 5px 0;">🧾 Recibo Interno</p>
                    <p style="color: var(--texto-gris, #888); font-size: 12px; margin: 0;">
                        Se emitirá recibo de pago interno.
                    </p>
                </div>
            '''
        
        return HTMLResponse(f'''
            <div style="text-align: center; padding: 15px 0;">
                <div style="width: 50px; height: 50px; margin: 0 auto 12px; background: rgba(34, 197, 94, 0.15); border-radius: 50%; display: flex; align-items: center; justify-content: center;">
                    <svg width="25" height="25" fill="none" stroke="#22c55e" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"></path>
                    </svg>
                </div>
                <h3 style="color: #22c55e; font-size: 16px; font-weight: 700; margin-bottom: 5px;">¡Pago Aprobado!</h3>
                <p style="color: var(--texto-gris, #888); font-size: 13px; margin-bottom: 15px;">
                    S/ {monto:.2f} procesado correctamente
                </p>
                {docs_html}
                <button onclick="window.AIFab?.cerrarModal()" 
                        style="margin-top: 10px; background: rgba(255,255,255,0.1); color: #888; border: none; padding: 10px 25px; border-radius: 20px; font-size: 12px; cursor: pointer;">
                    CERRAR
                </button>
            </div>
        ''')
    
    # Modo con validación manual (default)
    return HTMLResponse(f'''
        <div style="text-align: center; padding: 15px 0;">
            <div style="width: 50px; height: 50px; margin: 0 auto 12px; background: rgba(234, 179, 8, 0.15); border-radius: 50%; display: flex; align-items: center; justify-content: center;">
                <svg width="25" height="25" fill="none" stroke="#eab308" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"></path>
                </svg>
            </div>
            <h3 style="color: #eab308; font-size: 16px; font-weight: 700; margin-bottom: 5px;">Pago en Revisión</h3>
            <p style="color: var(--texto-gris, #888); font-size: 13px;">
                Tu pago de S/ {monto:.2f} será validado en las próximas horas.
            </p>
            <p style="color: var(--texto-gris, #888); font-size: 11px; margin-top: 10px; opacity: 0.7;">
                {f"Solicitaste: {tipo_comprobante.capitalize()}" if tipo_comprobante != "recibo" else ""}
                {" + Certificado" if requiere_certificado == "1" else ""}
            </p>
        </div>
    ''')


# ==========================================
# FORMULARIO HTML PÚBLICO
# ==========================================

@router.get("/formulario", response_class=HTMLResponse)
async def formulario_pago_publico(request: Request):
    """Retorna el formulario HTML completo para pago público."""
    org = request.state.org
    if not org:
        return HTMLResponse("<p>Error: Organización no identificada</p>")
    
    metodos = get_org_finanzas_config(org, "metodos_pago", [])
    
    # Generar HTML de métodos de pago con estilos del sitio
    metodos_html = ""
    for m in metodos:
        if m["tipo"] == "yape":
            metodos_html += f'''
                <div class="metodo-card">
                    <h4>📱 Yape</h4>
                    <p class="numero-grande">{m["numero"]}</p>
                    <p class="subtexto">A nombre de {m.get("titular", "CCPL")}</p>
                </div>
            '''
        elif m["tipo"] == "plin":
            metodos_html += f'''
                <div class="metodo-card">
                    <h4>📱 Plin</h4>
                    <p class="numero-grande">{m["numero"]}</p>
                    <p class="subtexto">A nombre de {m.get("titular", "CCPL")}</p>
                </div>
            '''
        elif m["tipo"] == "transferencia":
            metodos_html += f'''
                <div class="metodo-card">
                    <h4>🏦 {m.get("banco", "Transferencia")}</h4>
                    <p class="numero-grande">{m.get("cuenta", "")}</p>
                    <p class="subtexto">CCI: {m.get("cci", "")}</p>
                </div>
            '''
    
    return HTMLResponse(f'''
    <style>
        .pago-flow-container {{
            overflow-y: visible;
        }}
        .paso-content.hidden {{
            display: none;
        }}
        .input-pago {{
            width: 100%;
            background: var(--oscuro);
            border: 1px solid rgba(212, 175, 55, 0.3);
            border-radius: 10px;
            padding: 12px 15px;
            color: var(--texto-claro);
            font-size: 16px;
            outline: none;
            transition: border-color 0.3s;
        }}
        .input-pago:focus {{
            border-color: var(--dorado);
        }}
        .input-pago::placeholder {{
            color: var(--texto-gris);
        }}
        .label-pago {{
            display: block;
            color: var(--texto-gris);
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 8px;
        }}
        .campo-grupo {{
            margin-bottom: 20px;
        }}
        .btn-buscar {{
            background: linear-gradient(135deg, var(--dorado), var(--dorado-claro));
            color: var(--oscuro);
            border: none;
            padding: 12px 25px;
            border-radius: 10px;
            font-weight: 700;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 8px;
            transition: transform 0.2s, box-shadow 0.2s;
        }}
        .btn-buscar:hover {{
            transform: translateY(-2px);
            box-shadow: 0 5px 20px rgba(212, 175, 55, 0.3);
        }}
        .btn-buscar:disabled {{
            opacity: 0.6;
            cursor: not-allowed;
            transform: none;
        }}
        .resultado-card {{
            background: var(--oscuro);
            border-radius: 15px;
            padding: 20px;
            border: 1px solid rgba(212, 175, 55, 0.2);
            margin-top: 20px;
        }}
        .resultado-card.habil {{
            border-color: rgba(34, 197, 94, 0.5);
        }}
        .resultado-card.inhabil {{
            border-color: rgba(239, 68, 68, 0.5);
        }}
        .colegiado-header {{
            display: flex;
            align-items: center;
            gap: 15px;
            margin-bottom: 15px;
        }}
        .colegiado-avatar {{
            width: 50px;
            height: 50px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 24px;
            font-weight: bold;
        }}
        .colegiado-avatar.habil {{
            background: rgba(34, 197, 94, 0.2);
            color: #22c55e;
        }}
        .colegiado-avatar.inhabil {{
            background: rgba(239, 68, 68, 0.2);
            color: #ef4444;
        }}
        .colegiado-info h3 {{
            color: var(--texto-claro);
            font-size: 16px;
            margin-bottom: 4px;
        }}
        .colegiado-info p {{
            color: var(--texto-gris);
            font-size: 13px;
        }}
        .colegiado-info .matricula {{
            color: var(--dorado);
            font-family: monospace;
        }}
        .estado-badge {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
        .estado-badge.habil {{
            background: rgba(34, 197, 94, 0.2);
            color: #22c55e;
        }}
        .estado-badge.inhabil {{
            background: rgba(239, 68, 68, 0.2);
            color: #ef4444;
        }}
        .deuda-resumen {{
            background: rgba(212, 175, 55, 0.1);
            padding: 15px 20px;
            border-radius: 10px;
            margin: 15px 0;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .deuda-resumen .monto {{
            font-size: 28px;
            font-weight: 800;
            color: var(--texto-claro);
        }}
        .beneficio-badge {{
            background: linear-gradient(135deg, rgba(212, 175, 55, 0.2), rgba(212, 175, 55, 0.1));
            border: 1px solid var(--dorado);
            padding: 15px;
            border-radius: 10px;
            margin: 15px 0;
        }}
        .beneficio-badge h4 {{
            color: var(--dorado);
            font-size: 14px;
            margin-bottom: 8px;
        }}
        .beneficio-badge .ahorro {{
            color: #22c55e;
            font-size: 13px;
        }}
        .beneficio-badge .precio-final {{
            font-size: 24px;
            font-weight: 800;
            color: #22c55e;
        }}
        .metodos-pago-mini {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 10px;
            margin: 20px 0;
        }}
        .metodos-pago-mini .metodo-card {{
            padding: 15px;
        }}
        .metodos-pago-mini .metodo-card h4 {{
            font-size: 14px;
            margin-bottom: 8px;
        }}
        .metodos-pago-mini .numero-grande {{
            font-size: 16px;
        }}
        .radio-grupo {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
        }}
        .radio-opcion {{
            position: relative;
        }}
        .radio-opcion input {{
            position: absolute;
            opacity: 0;
        }}
        .radio-opcion label {{
            display: block;
            background: var(--oscuro);
            border: 2px solid rgba(212, 175, 55, 0.2);
            padding: 12px;
            border-radius: 10px;
            text-align: center;
            cursor: pointer;
            color: var(--texto-claro);
            font-weight: 600;
            transition: all 0.3s;
        }}
        .radio-opcion input:checked + label {{
            border-color: var(--dorado);
            background: rgba(212, 175, 55, 0.1);
        }}
        .botones-grupo {{
            display: flex;
            gap: 15px;
            margin-top: 25px;
            padding-top: 20px;
            border-top: 1px solid rgba(212, 175, 55, 0.1);
        }}
        .btn-secundario {{
            flex: 1;
            padding: 15px;
            border-radius: 25px;
            font-weight: 600;
            cursor: pointer;
            background: transparent;
            border: 1px solid rgba(212, 175, 55, 0.3);
            color: var(--texto-gris);
            transition: all 0.3s;
        }}
        .btn-secundario:hover {{
            border-color: var(--dorado);
            color: var(--texto-claro);
        }}
        .input-file {{
            color: var(--texto-gris);
            font-size: 14px;
        }}
        .input-file::-webkit-file-upload-button {{
            background: var(--oscuro);
            border: 1px solid rgba(212, 175, 55, 0.3);
            padding: 8px 15px;
            border-radius: 8px;
            color: var(--texto-claro);
            cursor: pointer;
            margin-right: 10px;
        }}
        .texto-exito {{
            text-align: center;
            padding: 30px;
        }}
        .texto-error {{
            background: rgba(239, 68, 68, 0.1);
            border: 1px solid rgba(239, 68, 68, 0.3);
            color: #fca5a5;
            padding: 15px;
            border-radius: 10px;
            font-size: 14px;
        }}
        .al-dia-msg {{
            text-align: center;
            padding: 20px;
            color: #22c55e;
        }}
        .al-dia-msg p {{
            color: var(--texto-gris);
            margin-top: 5px;
        }}
        .spin {{
            animation: spin 1s linear infinite;
        }}
        @keyframes spin {{
            from {{ transform: rotate(0deg); }}
            to {{ transform: rotate(360deg); }}
        }}
    </style>
    
    <div class="pago-flow-container">
        
        <!-- PASO 1: IDENTIFICACIÓN -->
        <div id="paso-identificacion" class="paso-content">
            <div class="campo-grupo">
                <label class="label-pago">DNI o Matrícula</label>
                <div style="display: flex; gap: 10px;">
                    <input type="text" id="input-identificador" class="input-pago"
                           placeholder="Ej: 12345678 o 10-0649" maxlength="15" style="flex: 1;">
                    <button onclick="buscarColegiado()" id="btn-buscar" class="btn-buscar">
                        <svg width="20" height="20" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path>
                        </svg>
                        Buscar
                    </button>
                </div>
            </div>
            
            <div id="resultado-busqueda"></div>
        </div>
        
        <!-- PASO 2: FORMULARIO DE PAGO -->
        <div id="paso-pago" class="paso-content hidden">
            <div id="info-colegiado-pago"></div>
            <div id="resumen-deuda-pago"></div>
            
            <h4 style="color: var(--texto-gris); font-size: 12px; text-transform: uppercase; letter-spacing: 1px; margin: 20px 0 10px;">
                Realiza tu pago a:
            </h4>
            <div class="metodos-pago-mini">
                {metodos_html}
            </div>
            
            <form id="form-pago" onsubmit="enviarPago(event)" enctype="multipart/form-data">
                <input type="hidden" name="colegiado_id" id="input-colegiado-id">
                
                <div class="campo-grupo">
                    <label class="label-pago">Monto a pagar (S/)</label>
                    <input type="number" name="monto" id="input-monto" step="0.01" required class="input-pago"
                           style="font-size: 20px; font-weight: 700;">
                </div>
                
                <div class="campo-grupo">
                    <label class="label-pago">Método de pago</label>
                    <div class="radio-grupo">
                        <div class="radio-opcion">
                            <input type="radio" name="metodo_pago" value="Yape" id="metodo-yape" checked>
                            <label for="metodo-yape">📱 Yape / Plin</label>
                        </div>
                        <div class="radio-opcion">
                            <input type="radio" name="metodo_pago" value="Transferencia" id="metodo-transfer">
                            <label for="metodo-transfer">🏦 Transferencia</label>
                        </div>
                    </div>
                </div>
                
                <div class="campo-grupo">
                    <label class="label-pago">Nº de Operación</label>
                    <input type="text" name="numero_operacion" id="input-operacion" class="input-pago"
                           placeholder="Ej: 123456789" style="font-family: monospace; letter-spacing: 2px;">
                </div>
                
                <div class="campo-grupo">
                    <label class="label-pago">Voucher (Foto)</label>
                    <input type="file" name="voucher" accept="image/*" class="input-file">
                    <p style="color: var(--texto-gris); font-size: 12px; margin-top: 5px;">
                        Puedes subir foto del voucher si no tienes el código
                    </p>
                </div>
                
                <div id="resultado-pago"></div>
                
                <div class="botones-grupo" id="botones-form">
                    <button type="button" onclick="volverABuscar()" class="btn-secundario">
                        ← Volver
                    </button>
                    <button type="submit" id="btn-submit-pago" class="btn-pago-online" style="flex: 2;">
                        ✓ REGISTRAR PAGO
                    </button>
                </div>
            </form>
        </div>
    </div>
    
    <script>
    let colegiadoActual = null;
    
    async function buscarColegiado() {{
        const identificador = document.getElementById('input-identificador').value.trim();
        if (!identificador) {{
            mostrarError('Ingresa tu DNI o número de matrícula');
            return;
        }}
        
        const btn = document.getElementById('btn-buscar');
        const resultadoDiv = document.getElementById('resultado-busqueda');
        
        btn.disabled = true;
        btn.innerHTML = '<svg class="spin" width="20" height="20" fill="none" stroke="currentColor" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" stroke-width="4" stroke-dasharray="30 70"></circle></svg>';
        
        try {{
            const response = await fetch(`/pagos/deuda/${{encodeURIComponent(identificador)}}`);
            const data = await response.json();
            
            if (!response.ok) {{
                throw new Error(data.detail || 'No encontrado');
            }}
            
            colegiadoActual = data;
            mostrarResultadoBusqueda(data);
            
        }} catch (error) {{
            resultadoDiv.innerHTML = `
                <div class="texto-error">
                    ❌ ${{error.message}}<br>
                    <small>Verifica el número e intenta nuevamente.</small>
                </div>
            `;
        }} finally {{
            btn.disabled = false;
            btn.innerHTML = '<svg width="20" height="20" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path></svg> Buscar';
        }}
    }}
    
    function mostrarResultadoBusqueda(data) {{
        const c = data.colegiado;
        const d = data.deuda;
        const b = data.beneficio;
        
        const esHabil = c.condicion === 'habil' || c.condicion === 'vitalicio';
        const tieneDeuda = d.total > 0;
        const claseEstado = esHabil ? 'habil' : 'inhabil';
        
        let html = `
            <div class="resultado-card ${{claseEstado}}">
                <div class="colegiado-header">
                    <div class="colegiado-avatar ${{claseEstado}}">
                        ${{esHabil ? '✓' : '!'}}
                    </div>
                    <div class="colegiado-info">
                        <h3>${{c.apellidos_nombres}}</h3>
                        <p>Matrícula: <span class="matricula">${{c.codigo_matricula}}</span></p>
                    </div>
                </div>
                <span class="estado-badge ${{claseEstado}}">
                    ${{esHabil ? '✓ HÁBIL' : '✗ INHÁBIL'}}
                </span>
        `;
        
        if (tieneDeuda) {{
            html += `
                <div class="deuda-resumen">
                    <div>
                        <span style="color: var(--texto-gris); font-size: 13px;">Deuda pendiente</span>
                        <p style="color: var(--texto-gris); font-size: 12px;">${{d.cantidad_cuotas}} cuota(s)</p>
                    </div>
                    <span class="monto">S/ ${{d.total.toFixed(2)}}</span>
                </div>
            `;
            
            if (b.aplicable) {{
                html += `
                    <div class="beneficio-badge">
                        <h4>🎉 ${{b.nombre}}</h4>
                        <p style="color: var(--texto-gris); font-size: 13px;">Descuento del ${{b.descuento_porcentaje}}% aplicable</p>
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 10px;">
                            <span style="color: var(--texto-gris);">Paga solo:</span>
                            <span class="precio-final">S/ ${{b.monto_con_descuento.toFixed(2)}}</span>
                        </div>
                        <p class="ahorro">Ahorras S/ ${{b.ahorro.toFixed(2)}}</p>
                    </div>
                `;
            }}
            
            html += `
                <button onclick="mostrarFormularioPago()" class="btn-pago-online" style="margin-top: 20px;">
                    💳 PAGAR AHORA
                </button>
            `;
        }} else {{
            html += `
                <div class="al-dia-msg">
                    <span style="font-size: 32px;">🎉</span>
                    <h4 style="color: #22c55e; margin: 10px 0;">¡Estás al día!</h4>
                    <p>No tienes deudas pendientes.</p>
                </div>
            `;
        }}
        
        html += '</div>';
        document.getElementById('resultado-busqueda').innerHTML = html;
    }}
    
    function mostrarFormularioPago() {{
        if (!colegiadoActual) return;
        
        const c = colegiadoActual.colegiado;
        const d = colegiadoActual.deuda;
        const b = colegiadoActual.beneficio;
        
        document.getElementById('paso-identificacion').classList.add('hidden');
        document.getElementById('paso-pago').classList.remove('hidden');
        
        document.getElementById('info-colegiado-pago').innerHTML = `
            <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 15px; padding: 15px; background: var(--oscuro); border-radius: 10px;">
                <div style="width: 40px; height: 40px; background: rgba(212,175,55,0.2); border-radius: 50%; display: flex; align-items: center; justify-content: center; color: var(--dorado); font-weight: bold;">
                    ${{c.apellidos_nombres.charAt(0)}}
                </div>
                <div>
                    <p style="color: var(--texto-claro); font-weight: 600;">${{c.apellidos_nombres}}</p>
                    <p style="color: var(--texto-gris); font-size: 12px;">Matrícula: ${{c.codigo_matricula}}</p>
                </div>
            </div>
        `;
        
        const montoSugerido = b.aplicable ? b.monto_con_descuento : d.total;
        
        document.getElementById('resumen-deuda-pago').innerHTML = `
            <div class="deuda-resumen">
                <span style="color: var(--texto-gris);">Total a pagar:</span>
                <div style="text-align: right;">
                    ${{b.aplicable ? `<span style="text-decoration: line-through; color: var(--texto-gris); font-size: 14px;">S/ ${{d.total.toFixed(2)}}</span>` : ''}}
                    <span style="font-size: 24px; font-weight: 800; color: #22c55e; margin-left: 10px;">S/ ${{montoSugerido.toFixed(2)}}</span>
                </div>
            </div>
            ${{b.aplicable ? `<p style="color: var(--dorado); font-size: 12px; text-align: right;">Beneficio ${{b.nombre}} aplicado</p>` : ''}}
        `;
        
        document.getElementById('input-colegiado-id').value = c.id;
        document.getElementById('input-monto').value = montoSugerido.toFixed(2);
        
        // Resetear campos
        document.getElementById('input-operacion').value = '';
        document.getElementById('resultado-pago').innerHTML = '';
        document.getElementById('form-pago').style.display = 'block';
        document.getElementById('botones-form').style.display = 'flex';
    }}
    
    function volverABuscar() {{
        document.getElementById('paso-pago').classList.add('hidden');
        document.getElementById('paso-identificacion').classList.remove('hidden');
        document.getElementById('resultado-pago').innerHTML = '';
        document.getElementById('form-pago').style.display = 'block';
        document.getElementById('botones-form').style.display = 'flex';

        // Resetear botón submit
        const btnSubmit = document.getElementById('btn-submit-pago');
        btnSubmit.disabled = false;
        btnSubmit.innerHTML = '✓ REGISTRAR PAGO';
    }}
    
    function mostrarError(msg) {{
        document.getElementById('resultado-busqueda').innerHTML = `
            <div class="texto-error">❌ ${{msg}}</div>
        `;
    }}
    
    async function enviarPago(event) {{
        event.preventDefault();
        
        const form = document.getElementById('form-pago');
        const formData = new FormData(form);
        const resultadoDiv = document.getElementById('resultado-pago');
        const btnSubmit = document.getElementById('btn-submit-pago');
        const botonesDiv = document.getElementById('botones-form');
        
        btnSubmit.disabled = true;
        btnSubmit.innerHTML = '⏳ Enviando...';
        
        try {{
            const response = await fetch('/pagos/registrar', {{
                method: 'POST',
                body: formData
            }});
            
            const html = await response.text();
            resultadoDiv.innerHTML = html;
            
            if (response.ok && !html.includes('texto-error') && !html.includes('❌')) {{
                botonesDiv.style.display = 'none';
                resultadoDiv.innerHTML += `
                    <div style="margin-top: 20px; display: flex; gap: 10px;">
                        <button onclick="volverABuscar()" class="btn-secundario" style="flex: 1;">
                            ← Nueva consulta
                        </button>
                    </div>
                `;
            }} else {{
                btnSubmit.disabled = false;
                btnSubmit.innerHTML = '✓ REGISTRAR PAGO';
            }}
        }} catch (error) {{
            resultadoDiv.innerHTML = '<div class="texto-error">❌ Error de conexión. Intenta de nuevo.</div>';
            btnSubmit.disabled = false;
            btnSubmit.innerHTML = '✓ REGISTRAR PAGO';
        }}
    }}
    
    document.getElementById('input-identificador')?.addEventListener('keypress', (e) => {{
        if (e.key === 'Enter') buscarColegiado();
    }});
    </script>
    ''')


# ==========================================
# ADMIN: Validación de Pagos
# ==========================================

@router.post("/admin/validar/{pago_id}")
async def validar_pago_colegiado(
    request: Request,
    pago_id: int,
    accion: str = Form(...),
    motivo: str = Form(None),
    db: Session = Depends(get_db)
):
    """Valida o rechaza un pago de colegiado."""
    # TODO: Verificar que es admin
    
    pago = db.query(Payment).filter(Payment.id == pago_id).first()
    if not pago:
        raise HTTPException(status_code=404, detail="Pago no encontrado")
    
    if pago.status != "review":
        raise HTTPException(status_code=400, detail="Este pago ya fue procesado")
    
    if accion == "rechazar":
        pago.status = "rejected"
        pago.rejection_reason = motivo
        pago.reviewed_at = datetime.now(timezone.utc)
        db.commit()
        return {"success": True, "mensaje": "Pago rechazado"}
    
    elif accion == "aprobar":
        pago.status = "approved"
        pago.reviewed_at = datetime.now(timezone.utc)
        
        # Imputar a deudas (FIFO)
        deudas = db.query(Debt).filter(
            Debt.colegiado_id == pago.colegiado_id,
            Debt.status.in_(["pending", "partial"])
        ).order_by(Debt.due_date.asc(), Debt.created_at.asc()).all()
        
        monto_restante = pago.amount
        
        for deuda in deudas:
            if monto_restante <= 0:
                break
            
            if monto_restante >= deuda.balance:
                monto_restante -= deuda.balance
                deuda.balance = 0
                deuda.status = "paid"
            else:
                deuda.balance -= monto_restante
                deuda.status = "partial"
                monto_restante = 0
        
        # Verificar si quedó al día
        deudas_pendientes = db.query(Debt).filter(
            Debt.colegiado_id == pago.colegiado_id,
            Debt.status.in_(["pending", "partial"])
        ).count()
        
        if deudas_pendientes == 0:
            colegiado = db.query(Colegiado).filter(Colegiado.id == pago.colegiado_id).first()
            if colegiado and colegiado.condicion == "inhabil":
                colegiado.condicion = "habil"
                colegiado.fecha_actualizacion_condicion = datetime.now(timezone.utc)
        
        #db.commit()
        
        # Sincronizar cambios ORM antes de emitir certificado
        db.flush()
        
        # Emitir certificado automáticamente
        certificado_info = None
        try:
            certificado_info = emitir_certificado_automatico(
                db=db,
                colegiado_id=pago.colegiado_id,
                payment_id=pago.id
            )
        except Exception as e:
            print(f"⚠️ Error emitiendo certificado: {e}")
        
        db.commit()
        
        respuesta = {
            "success": True,
            "mensaje": "Pago aprobado",
            "saldo_a_favor": monto_restante if monto_restante > 0 else 0
        }
        
        if certificado_info and certificado_info.get("emitido"):
            respuesta["certificado"] = certificado_info
            respuesta["mensaje"] = f"Pago aprobado. Certificado {certificado_info['codigo']} emitido."
        
        return respuesta
    
    raise HTTPException(status_code=400, detail="Acción no válida")


# ==========================================
# PROXY PARA DESCARGA DE COMPROBANTES PDF
# ==========================================
"""Este endpoint actúa como proxy para descargar el PDF de un comprobante desde facturalo.pro, utilizando las credenciales almacenadas en la configuración de facturación de la organización."""

@router.get("/comprobante/{comprobante_id}/pdf")
async def descargar_comprobante_pdf(
    comprobante_id: str,
    request: Request,
    db: Session = Depends(get_db)
):
    """Proxy para descargar PDF de comprobante desde facturalo.pro"""
    import httpx
    
    org = request.state.org
    if not org:
        raise HTTPException(status_code=400, detail="Organización no identificada")
    
    # Obtener credenciales
    config = db.execute(
        text("""
            SELECT facturalo_token, facturalo_secret 
            FROM configuracion_facturacion 
            WHERE organization_id = :org_id AND activo = true
        """),
        {"org_id": org["id"]}
    ).fetchone()
    
    if not config:
        raise HTTPException(status_code=404, detail="Configuración de facturación no encontrada")
    
    # Descargar PDF
    url = f"https://facturalo.pro/api/v1/comprobantes/{comprobante_id}/pdf"
    
    print(f"🔍 Descargando PDF: {url}")
    print(f"🔑 Token: {config.facturalo_token[:10]}...")
    
    async with httpx.AsyncClient() as client:
        response = await client.get(
            url,
            headers={
                "x-api-key": config.facturalo_token,
                "x-api-secret": config.facturalo_secret
            }
        )
        
        print(f"📥 Status: {response.status_code}")
        print(f"📥 Content-Type: {response.headers.get('content-type', 'N/A')}")
        
        # Verificar si es PDF válido
        content_type = response.headers.get('content-type', '')
        
        if response.status_code != 200:
            print(f"❌ Error: {response.text[:500]}")
            raise HTTPException(status_code=response.status_code, detail=f"Error facturalo.pro: {response.text[:200]}")
        
        if 'application/pdf' not in content_type and 'application/octet-stream' not in content_type:
            print(f"⚠️ No es PDF, contenido: {response.text[:500]}")
            raise HTTPException(status_code=400, detail=f"Respuesta no es PDF: {content_type}")
        
        return StreamingResponse(
            io.BytesIO(response.content),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename=Boleta_{comprobante_id[:8]}.pdf"
            }
        )
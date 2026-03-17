"""
Router: Portal del Colegiado Inactivo
app/routers/portal_colegiado.py

USA el sistema de auth existente (JWT cookie + get_current_member).
"""

from datetime import date as dt_date, datetime, timezone, timedelta
from sqlalchemy import and_

from app.models_debt_management import Debt, Fraccionamiento, EstadoFraccionamiento, FraccionamientoCuota
from app.models import Colegiado, Member, ConceptoCobro, Organization

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, text

from app.database import get_db
from app.routers.dashboard import get_current_member

from dateutil.relativedelta import relativedelta   # pip install python-dateutil
from pydantic import BaseModel, field_validator
import math


router = APIRouter(prefix="/api/portal", tags=["portal"])


# ── Schema de entrada ─────────────────────────────────────────────────────────
class FraccionamientoRequest(BaseModel):
    cuota_inicial: float
    num_cuotas: int
    notas: str = ""

    @field_validator("cuota_inicial")
    @classmethod
    def cuota_positiva(cls, v):        # ← añadir @classmethod
        if v <= 0:
            raise ValueError("La cuota inicial debe ser mayor a 0")
        return round(v, 2)

    @field_validator("num_cuotas")
    @classmethod
    def cuotas_validas(cls, v):
        if not (2 <= v <= 12):
            raise ValueError("El número de cuotas debe estar entre 2 y 12")
        return v



def _get_colegiado(member: Member, db: Session) -> Colegiado:
    """Obtiene el colegiado asociado al member autenticado."""
    # Primero por member_id (vinculación directa)
    col = db.query(Colegiado).filter(
        Colegiado.member_id == member.id,
        Colegiado.organization_id == member.organization_id,
    ).first()

    # Fallback: por DNI (user.public_id == colegiado.dni)
    if not col and member.user:
        col = db.query(Colegiado).filter(
            Colegiado.organization_id == member.organization_id,
            Colegiado.dni == member.user.public_id,
        ).first()

    if not col:
        raise HTTPException(404, "Colegiado no encontrado para este usuario")
    return col


def _parse_nombre(apellidos_nombres: str):
    """Separa 'APELLIDO1 APELLIDO2, NOMBRES' en partes útiles."""
    nombre_completo = (apellidos_nombres or "").strip()
    if not nombre_completo:
        return "", "", ""

    if "," in nombre_completo:
        apellidos, nombres = nombre_completo.split(",", 1)
        apellidos = apellidos.strip()
        nombres = nombres.strip()
        nombre_corto = nombres.split()[0] if nombres else apellidos.split()[0]
    else:
        partes = nombre_completo.split()
        if len(partes) > 2:
            apellidos = " ".join(partes[:2])
            nombres = " ".join(partes[2:])
            nombre_corto = partes[2]
        else:
            apellidos = nombre_completo
            nombres = ""
            nombre_corto = partes[0] if partes else ""

    # Capitalizar: "GARCIA LOPEZ, CARLOS" → "Carlos"
    nombre_corto = nombre_corto.title()
    nombres = nombres.title()

    return nombre_completo, nombres, nombre_corto


@router.get("/mi-perfil")
async def mi_perfil(
    member: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
):
    col = _get_colegiado(member, db)
    org = db.query(Organization).filter(Organization.id == col.organization_id).first()

    nombre_completo, nombres, nombre_corto = _parse_nombre(col.apellidos_nombres)

    return {
        "id": col.id,
        "nombre_completo": nombre_completo,
        "nombre_corto": nombre_corto,
        "nombres": nombres,
        "dni": col.dni,
        "matricula": col.codigo_matricula,
        "condicion": col.condicion,
        "email": col.email,
        "telefono": col.telefono,
        "especialidad": col.especialidad,
        "universidad": col.universidad,
        "foto_url": col.foto_url,
        "organizacion": org.name if org else "Colegio Profesional",
        "tiene_fraccionamiento": bool(col.tiene_fraccionamiento),
        "habilidad_vence": col.habilidad_vence.isoformat() if col.habilidad_vence else None,
        "telefono_colegio": getattr(org, 'phone', None),
    }


@router.get("/cuentas-pago")
async def cuentas_pago(
    member: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
):
    try:
        cuentas = db.execute(text("""
            SELECT banco, numero_cuenta, tipo_cuenta, titular, moneda, cci
            FROM cuentas_receptoras
            WHERE organization_id = :org_id AND activa = true
            ORDER BY banco
        """), {"org_id": member.organization_id}).fetchall()

        return {"cuentas": [{
            "banco": c.banco,
            "numero_cuenta": c.numero_cuenta,
            "tipo_cuenta": c.tipo_cuenta,
            "titular": c.titular,
            "moneda": c.moneda or "PEN",
            "cci": c.cci,
        } for c in cuentas]}
    except Exception:
        return {"cuentas": []}


@router.get("/stats-servicios")
async def stats_servicios(
    member: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
):
    activos = db.query(func.count(Colegiado.id)).filter(
        Colegiado.organization_id == member.organization_id,
        Colegiado.condicion == "habil",
    ).scalar() or 0

    return {
        "colegiados_activos": activos,
        "rucs_monitoreados": 847,       # TODO: tabla real
        "consultas_ia_mes": 186,        # TODO: tabla real
        "proximo_evento": "Mar 2026",   # TODO: tabla real
    }


from datetime import date as dt_date
from app.models_debt_management import Debt, Fraccionamiento, EstadoFraccionamiento


@router.get("/mi-deuda")
async def mi_deuda(
    member: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
):
    """
    Retorna las deudas pendientes del colegiado autenticado.
    El frontend agrupa por año usando el campo `periodo`.
    """
    colegiado = _get_colegiado(member, db)

    # DEBUG TEMPORAL — quitar después
    print(f"[DEBUG] colegiado.id = {colegiado.id}")

    # ── Deudas pendientes o parciales ─────────────────────────────────────
    deudas_qs = (
        db.query(Debt)
        .filter(
            Debt.colegiado_id == colegiado.id,
            Debt.status.in_(["pending", "partial"]),
            Debt.estado_gestion.in_(["vigente", "en_cobranza", "fraccionada"]),
        )
        .order_by(Debt.periodo.asc())
        .all()
    )

    # DEBUG TEMPORAL — quitar después
    print(f"[DEBUG] deudas encontradas = {len(deudas_qs)}")
    print(f"[DEBUG] total = {sum(float(d.balance or 0) for d in deudas_qs)}")

    total = sum(float(d.balance or 0) for d in deudas_qs)

    deudas_list = [
        {
            "id":             d.id,
            "concept":        d.concept,          # "Cuotas Ordinarias"
            "period_label":   d.period_label,     # "2024" / "Ene-Dic 2024"
            "periodo":        d.periodo,           # "2024" / "2024-01"
            "debt_type":      d.debt_type,
            "amount":         float(d.amount  or 0),
            "balance":        float(d.balance or 0),
            "status":         d.status,
            "estado_gestion": d.estado_gestion,
            "due_date":       d.due_date.isoformat() if d.due_date else None,
            "es_exigible":    d.es_exigible,
            "dias_mora":      d.dias_mora,
        }
        for d in deudas_qs
    ]

    # ── ¿Califica fraccionamiento? ─────────────────────────────────────────
    plan_activo = (
        db.query(Fraccionamiento)
        .filter(
            Fraccionamiento.colegiado_id == colegiado.id,
            Fraccionamiento.estado == EstadoFraccionamiento.ACTIVO,
        )
        .first()
    )
    califica_fracc = (total >= 500.0) and (plan_activo is None)

    # ── Campaña / descuento activo ─────────────────────────────────────────
    hoy = dt_date.today()
    if hoy.month <= 2:
        campana = {
            "nombre":        "Campaña Febrero",
            "descripcion":   "20% de descuento en cuotas ordinarias del año en curso.",
            "descuento_pct": 0.20,
            "fecha_fin":     f"28 Feb {hoy.year}",
        }
    elif hoy.month == 3:
        campana = {
            "nombre":        "Campaña Marzo",
            "descripcion":   "10% de descuento en cuotas ordinarias del año en curso.",
            "descuento_pct": 0.10,
            "fecha_fin":     f"31 Mar {hoy.year}",
        }
    else:
        campana = None

    return {
        "deudas":                   deudas_list,
        "total":                    total,
        "cantidad":                 len(deudas_list),
        "califica_fraccionamiento": califica_fracc,
        "plan_activo":              plan_activo is not None,
        "campana":                  campana,
    }


# ── Endpoint ──────────────────────────────────────────────────────────────────
@router.post("/fraccionamiento/crear")
async def crear_fraccionamiento(
    data: FraccionamientoRequest,
    member: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
):
    """
    Crea un plan de fraccionamiento para el colegiado autenticado.

    Reglas del CCPL:
    - Deuda mínima: S/ 500
    - Cuota inicial: mínimo 20% de la deuda total
    - Cuota mensual resultante: mínimo S/ 100
    - Máximo 12 cuotas
    - Cuota 0 = inicial (pago inmediato)
    - Cuotas 1..N = mensuales, vencen el día 15 de cada mes
    - Cada cuota mensual pagada otorga habilidad hasta fin de ese mes
    """
    colegiado = _get_colegiado(member, db)
    hoy = dt_date.today()

    # ── 1. Calcular total de deuda pendiente ──────────────────────────────
    deudas_qs = (
        db.query(Debt)
        .filter(
            Debt.colegiado_id == colegiado.id,
            Debt.status.in_(["pending", "partial"]),
            Debt.estado_gestion.in_(["vigente", "en_cobranza"]),
        )
        .all()
    )

    if not deudas_qs:
        raise HTTPException(400, "No tienes deudas pendientes para fraccionar")

    total = round(sum(float(d.balance or 0) for d in deudas_qs), 2)

    # ── 2. Validaciones de negocio ────────────────────────────────────────
    if total < 500:
        raise HTTPException(400, f"La deuda total (S/ {total:.2f}) es menor al mínimo de S/ 500")

    minimo_inicial = round(total * 0.20, 2)
    if data.cuota_inicial < minimo_inicial:
        raise HTTPException(
            400,
            f"La cuota inicial mínima es S/ {minimo_inicial:.2f} (20% de S/ {total:.2f})"
        )

    if data.cuota_inicial >= total:
        raise HTTPException(400, "La cuota inicial no puede cubrir la deuda completa; usa pago directo")

    saldo = round(total - data.cuota_inicial, 2)
    monto_cuota = round(saldo / data.num_cuotas, 2)

    if monto_cuota < 100:
        raise HTTPException(
            400,
            f"La cuota mensual resultante (S/ {monto_cuota:.2f}) es menor al mínimo de S/ 100. "
            f"Reduce el número de cuotas o aumenta la cuota inicial."
        )

    # ── 3. Verificar que no haya plan activo ──────────────────────────────
    plan_existente = (
        db.query(Fraccionamiento)
        .filter(
            Fraccionamiento.colegiado_id == colegiado.id,
            Fraccionamiento.estado == "activo",
        )
        .first()
    )
    if plan_existente:
        raise HTTPException(
            409,
            f"Ya tienes un plan de fraccionamiento activo (#{plan_existente.numero_solicitud})"
        )

    # ── 4. Generar número de solicitud ────────────────────────────────────
    anio = hoy.year
    ultimo = (
        db.query(Fraccionamiento)
        .filter(Fraccionamiento.organization_id == colegiado.organization_id)
        .filter(Fraccionamiento.numero_solicitud.like(f"FRACC-{anio}-%"))
        .count()
    )
    numero_solicitud = f"FRACC-{anio}-{str(ultimo + 1).zfill(4)}"

    # ── 5. Fechas ─────────────────────────────────────────────────────────
    # Primera cuota mensual vence el 15 del mes siguiente
    primer_venc = hoy.replace(day=15) + relativedelta(months=1)
    ultima_venc  = primer_venc + relativedelta(months=data.num_cuotas - 1)

    # ── 6. Crear Fraccionamiento ──────────────────────────────────────────
    fracc = Fraccionamiento(
        organization_id       = colegiado.organization_id,
        colegiado_id          = colegiado.id,
        numero_solicitud      = numero_solicitud,
        fecha_solicitud       = hoy,
        deuda_total_original  = total,
        cuota_inicial         = data.cuota_inicial,
        cuota_inicial_pagada  = False,   # se marcará al registrar el pago
        saldo_a_fraccionar    = saldo,
        num_cuotas            = data.num_cuotas,
        monto_cuota           = monto_cuota,
        cuotas_pagadas        = 0,
        cuotas_atrasadas      = 0,
        saldo_pendiente       = total,   # baja con cada pago (inicial + mensuales)
        fecha_inicio          = hoy,
        fecha_fin_estimada    = ultima_venc,
        proxima_cuota_fecha   = hoy,     # la inicial es inmediata
        proxima_cuota_numero  = 0,
        estado                = "activo",
        created_by            = member.user_id,
        approved_by           = None,    # auto-aprobado desde el portal
    )
    db.add(fracc)
    db.flush()   # obtener fracc.id sin cerrar la transacción

    # ── 7. Crear cuotas ───────────────────────────────────────────────────
    cuotas = []

    # Cuota 0 — inicial (pago inmediato)
    cuotas.append(FraccionamientoCuota(
        fraccionamiento_id = fracc.id,
        numero_cuota       = 0,
        monto              = data.cuota_inicial,
        fecha_vencimiento  = hoy,
        habilidad_hasta    = None,  # la inicial no otorga habilidad sola
    ))

    # Cuotas 1..N — mensuales
    for i in range(1, data.num_cuotas + 1):
        venc = primer_venc + relativedelta(months=i - 1)
        # Habilidad hasta el último día de ese mes
        fin_mes = (venc.replace(day=1) + relativedelta(months=1)) - timedelta(days=1)
        cuotas.append(FraccionamientoCuota(
            fraccionamiento_id = fracc.id,
            numero_cuota       = i,
            monto              = monto_cuota,
            fecha_vencimiento  = venc,
            habilidad_hasta    = fin_mes,
        ))

    db.bulk_save_objects(cuotas)

    # ── 8. Marcar deudas como fraccionadas ────────────────────────────────
    for d in deudas_qs:
        d.estado_gestion    = "fraccionada"
        d.fraccionamiento_id = fracc.id

    db.commit()
    db.refresh(fracc)

    # ── 9. Respuesta ──────────────────────────────────────────────────────
    return {
        "success":          True,
        "numero_solicitud": fracc.numero_solicitud,
        "fraccionamiento_id": fracc.id,
        "deuda_total":      total,
        "cuota_inicial":    data.cuota_inicial,
        "num_cuotas":       data.num_cuotas,
        "monto_cuota":      monto_cuota,
        "primera_cuota":    primer_venc.isoformat(),
        "ultima_cuota":     ultima_venc.isoformat(),
        "mensaje": (
            f"Plan #{numero_solicitud} creado. "
            f"Realiza el pago inicial de S/ {data.cuota_inicial:.2f} para reactivarte."
        ),
    }




@router.get("/catalogo")
async def get_catalogo_portal(
    request: Request,
    member:  Member  = Depends(get_current_member),
    db:      Session = Depends(get_db),
):
    """Catálogo de servicios y productos para el portal inactivo."""
    from sqlalchemy import or_
    from app.models import ConceptoCobro

    items = db.query(ConceptoCobro).filter(
        ConceptoCobro.organization_id == member.organization_id,
        ConceptoCobro.activo == True,
        or_(ConceptoCobro.genera_deuda == False, ConceptoCobro.genera_deuda == None),
    ).order_by(ConceptoCobro.categoria, ConceptoCobro.orden).all()

    resultado = []
    for c in items:
        resultado.append({
            "id":               c.id,
            "codigo":           c.codigo,
            "nombre":           c.nombre,
            "descripcion":      c.descripcion or "",
            "categoria":        c.categoria,
            "monto_base":       float(c.monto_base or 0),
            "monto_colegiado":  float(c.monto_colegiado or c.monto_base or 0),
            "permite_monto_libre": bool(c.permite_monto_libre),
            "maneja_stock":     bool(c.maneja_stock),
            "stock_actual":     c.stock_actual if c.maneja_stock else None,
            "es_mercaderia":    c.categoria == "mercaderia",
        })

    return JSONResponse({"catalogo": resultado})



"""
Agregar a app/routers/portal_colegiado.py

Endpoint: POST /api/portal/reportar-pago
- Recibe: monto, nro_operacion, metodo, deuda_ids, voucher (imagen), solicitar_constancia
- Sube voucher a GCS
- Crea Payment (status='review')
- Intenta matching automático con notificaciones_bancarias
- Si nivel >= 2: auto-aprueba y notifica
- Retorna JSON con estado y mensaje para el chat del portal
"""

import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Colegiado, Member, Payment, NotificacionBancaria
from app.routers.dashboard import get_current_member
from app.utils.gcs import upload_documento
from app.services.motor_matching import matching_al_reportar, aplicar_match

logger = logging.getLogger(__name__)

# ── Constantes ─────────────────────────────────────────────────────────────────
METODOS_VALIDOS = {'yape', 'plin', 'transferencia', 'bbva', 'bcp', 'interbank', 'scotiabank'}
MAX_VOUCHER_MB  = 10


# ── Endpoint ───────────────────────────────────────────────────────────────────
@router.post("/reportar-pago")
async def reportar_pago(
    monto:                float         = Form(...),
    nro_operacion:        str           = Form(...),
    metodo:               str           = Form(...),
    deuda_ids:            str           = Form(""),
    fracc_codigo:         Optional[str] = Form(None),
    concepto:             Optional[str] = Form(None),
    solicitar_constancia: bool          = Form(False),
    voucher:              UploadFile    = File(...),
    member:               Member        = Depends(get_current_member),
    db:                   Session       = Depends(get_db),
):
    # ── Validaciones ─────────────────────────────────────────────────────────
    if monto <= 0:
        return JSONResponse(
            {"ok": False, "error": "El monto debe ser mayor a cero."},
            status_code=400
        )
 
    nro_operacion = nro_operacion.strip()
    if not nro_operacion:
        return JSONResponse(
            {"ok": False, "error": "El N° de operación es obligatorio."},
            status_code=400
        )
 
    if metodo.lower() not in METODOS_VALIDOS:
        return JSONResponse(
            {"ok": False, "error": f"Método inválido: {metodo}"},
            status_code=400
        )
 
    if not voucher or not voucher.filename:
        return JSONResponse(
            {"ok": False, "error": "El voucher es obligatorio."},
            status_code=400
        )
 
    voucher_bytes = await voucher.read()
    if len(voucher_bytes) > MAX_VOUCHER_MB * 1024 * 1024:
        return JSONResponse(
            {"ok": False, "error": f"El voucher no debe superar {MAX_VOUCHER_MB}MB."},
            status_code=400
        )
 
    # ── Obtener colegiado ─────────────────────────────────────────────────────
    colegiado = db.query(Colegiado).filter(
        Colegiado.member_id       == member.id,
        Colegiado.organization_id == member.organization_id,
    ).first()
 
    if not colegiado:
        return JSONResponse(
            {"ok": False, "error": "Colegiado no encontrado."},
            status_code=404
        )
 
    # ── Subir voucher a GCS ───────────────────────────────────────────────────
    ts           = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    ext          = _ext_segura(voucher.content_type, voucher.filename)
    blob_path    = f"{member.organization_id}/pagos/{colegiado.id}/voucher_{ts}.{ext}"
    content_type = voucher.content_type or 'image/jpeg'
 
    voucher_path = upload_documento(
        file_bytes   = voucher_bytes,
        content_type = content_type,
        blob_path    = blob_path,
    )
 
    if not voucher_path:
        logger.warning(
            f'[ReportePago] GCS no disponible — '
            f'voucher no subido para colegiado {colegiado.id}'
        )
 
    # ── Preparar notas ────────────────────────────────────────────────────────
    notas = {
        "deuda_ids":    [int(x) for x in deuda_ids.split(',') if x.strip().isdigit()],
        "fracc_codigo": fracc_codigo or None,
        "concepto":     concepto or None,
    }
 
    # ── Crear Payment ─────────────────────────────────────────────────────────
    nombre_colegiado = getattr(colegiado, 'nombre_completo', None) \
                    or getattr(colegiado, 'nombres', None)
 
    payment = Payment(
        organization_id = member.organization_id,
        colegiado_id    = colegiado.id,
        amount          = round(monto, 2),
        currency        = 'PEN',
        payment_method  = metodo.lower(),
        operation_code  = nro_operacion.upper(),
        voucher_url     = voucher_path,
        pagador_tipo    = 'titular',
        pagador_nombre  = nombre_colegiado,
        status          = 'review',
        notes           = json.dumps(notas, ensure_ascii=False),
    )
    db.add(payment)
    db.flush()  # necesitamos payment.id antes del commit
 
    # ── Matching automático con notificaciones bancarias ──────────────────────
    nivel        = 0
    notificacion = None
 
    try:
        notificacion, nivel = matching_al_reportar(
            nro_operacion   = nro_operacion,
            monto           = round(monto, 2),
            fecha_pago      = datetime.utcnow(),
            metodo          = metodo,
            organization_id = member.organization_id,
            db              = db,
        )
 
        if notificacion and nivel >= 2:
            aplicar_match(
                notificacion    = notificacion,
                reporte_pago_id = payment.id,
                nivel           = nivel,
                conciliado_por  = 'auto',
                db              = db,
            )
            # Nivel 3 = aprobación automática, nivel 2 = sigue en review para caja
            if nivel == 3:
                payment.status = 'approved'
            notificacion.payment_id = payment.id
            db.flush()
 
    except Exception as e:
        logger.error(f'[ReportePago] Error en matching: {e}', exc_info=True)
        # El pago se guarda igual aunque el matching falle
 
    db.commit()
 
    # ── Mensaje para el chat ──────────────────────────────────────────────────
    if nivel == 3:
        mensaje = (
            f'✅ ¡Pago verificado automáticamente! El N° de operación '
            f'<strong>{nro_operacion}</strong> coincide con la notificación '
            f'del banco. Tu cuenta será actualizada en breve.'
        )
    elif nivel == 2:
        mensaje = (
            f'✅ Pago reportado. El monto S/ {monto:.2f} coincide con un '
            f'registro del banco. La caja confirmará en pocas horas.'
        )
    else:
        mensaje = (
            f'📤 Pago reportado correctamente. La caja validará tu voucher '
            f'en hasta 24h y recibirás una notificación al aprobar.'
        )
 
    logger.info(
        f'[ReportePago] payment_id={payment.id} colegiado={colegiado.id} '
        f'monto={monto} nivel_match={nivel} status={payment.status}'
    )
 
    return JSONResponse({
        "ok":          True,
        "payment_id":  payment.id,
        "estado":      payment.status,
        "nivel_match": nivel,
        "mensaje":     mensaje,
    })
 
 
def _ext_segura(content_type: str, filename: str) -> str:
    ct_map = {
        'image/jpeg':      'jpg',
        'image/jpg':       'jpg',
        'image/png':       'png',
        'image/webp':      'webp',
        'image/gif':       'gif',
        'application/pdf': 'pdf',
    }
    ext = ct_map.get((content_type or '').lower())
    if ext:
        return ext
    if filename and '.' in filename:
        return filename.rsplit('.', 1)[-1].lower()[:5]
    return 'jpg'




# ══════════════════════════════════════════════════════════════════════════════
# AGREGAR A app/routers/portal_colegiado.py
#
# Imports adicionales:
#   import base64, json
#   from openai import OpenAI
#   import httpx
# ══════════════════════════════════════════════════════════════════════════════

import base64
import json
import httpx
import os
import logging

from fastapi import File, UploadFile
from fastapi.responses import JSONResponse
from openai import OpenAI

logger = logging.getLogger(__name__)

OPENAI_API_KEY  = os.getenv("OPENAI_API_KEY", "")
APIS_NET_PE_KEY = os.getenv("APIS_NET_PE_KEY", "")   # opcional — sin token igual funciona


# ── OCR del voucher ────────────────────────────────────────────────────────────
@router.post("/analizar-voucher")
async def analizar_voucher(
    voucher: UploadFile = File(...),
    member:  Member     = Depends(get_current_member),
):
    """
    Recibe imagen del voucher, devuelve JSON con datos extraídos:
    { amount, operation_code, date, bank, ok }
    """
    if not OPENAI_API_KEY:
        return JSONResponse({"ok": False, "msg": "OCR no configurado"}, status_code=503)

    try:
        contents     = await voucher.read()
        base64_image = base64.b64encode(contents).decode("utf-8")
        content_type = voucher.content_type or "image/jpeg"

        client = OpenAI(api_key=OPENAI_API_KEY)

        prompt = """
Analiza esta imagen de un comprobante de pago (Yape, Plin, Transferencia BCP/Interbank/BBVA/Scotiabank).
Extrae estrictamente en formato JSON:
- "amount": monto total (número decimal, sin símbolo de moneda, ej: 500.00)
- "operation_code": número de operación o ID de transacción (string)
- "date": fecha y hora si es visible (formato YYYY-MM-DD HH:MM), si no: null
- "bank": nombre del banco o billetera digital detectada (string corto, ej: "BBVA", "Yape", "BCP")

Si no encuentras algún dato, pon null. No inventes datos.
Responde SOLO el JSON, sin texto adicional ni markdown.
"""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {
                        "url": f"data:{content_type};base64,{base64_image}"
                    }},
                ],
            }],
            max_tokens=300,
        )

        raw     = response.choices[0].message.content
        clean   = raw.replace("```json", "").replace("```", "").strip()
        data    = json.loads(clean)

        logger.info(f"[OCR] colegiado={member.id} banco={data.get('bank')} monto={data.get('amount')}")

        return JSONResponse({
            "ok":             True,
            "amount":         data.get("amount"),
            "operation_code": data.get("operation_code"),
            "date":           data.get("date"),
            "bank":           data.get("bank"),
        })

    except json.JSONDecodeError:
        logger.warning(f"[OCR] Respuesta no parseable: {raw[:200]}")
        return JSONResponse({"ok": False, "msg": "No se pudo leer el voucher. Ingresa los datos manualmente."})
    except Exception as e:
        logger.error(f"[OCR] Error: {e}", exc_info=True)
        return JSONResponse({"ok": False, "msg": "Error al analizar el voucher."})


# ── Consulta RUC (apis.net.pe) ─────────────────────────────────────────────────
@router.get("/ruc/{ruc}")
async def consultar_ruc_portal(ruc: str):
    """
    Consulta RUC en apis.net.pe.
    Retorna: { ok, ruc, nombre, direccion, estado, tipo_ruc }
    tipo_ruc: 'natural' (RUC 10) | 'empresa' (RUC 20)
    Para RUC 10 la dirección puede venir vacía — el frontend la deja editable.
    """
    if len(ruc) != 11 or not ruc.isdigit():
        return JSONResponse({"ok": False, "error": "RUC inválido"}, status_code=400)

    tipo_ruc = "natural" if ruc.startswith("10") else "empresa"

    try:
        headers = {"Accept": "application/json"}
        if APIS_NET_PE_KEY:
            headers["Authorization"] = f"Bearer {APIS_NET_PE_KEY}"

        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(
                f"https://api.apis.net.pe/v2/sunat/ruc?numero={ruc}",
                headers=headers,
            )

        if r.status_code == 200:
            d = r.json()
            return JSONResponse({
                "ok":        True,
                "ruc":       ruc,
                "nombre":    d.get("razonSocial") or d.get("nombre") or "",
                "direccion": d.get("direccion") or "",   # vacío para RUC 10 — esperado
                "estado":    d.get("estado", "ACTIVO"),
                "tipo_ruc":  tipo_ruc,
            })

    except Exception as e:
        logger.warning(f"[RUC] Error consultando {ruc}: {e}")

    # Fallback — dejar campos editables
    return JSONResponse({
        "ok":        False,
        "ruc":       ruc,
        "nombre":    "",
        "direccion": "",
        "estado":    "NO VERIFICADO",
        "tipo_ruc":  tipo_ruc,
        "msg":       "API no disponible — ingresa los datos manualmente.",
    })
"""
app/routers/secretaria.py
Endpoints para panel de secretaria — actualización rápida de pagos.
Rutas:
  GET  /api/secretaria/buscar-colegiado  -> busca por matrícula/DNI/nombre
  GET  /api/secretaria/deudas/{id}       -> deudas pendientes del colegiado
  POST /api/secretaria/registrar-pago    -> marca deudas pagadas + actualiza condición
  GET  /secretaria                       -> página HTML del panel
"""
from datetime import datetime, timezone, timedelta, date
from typing import Optional, List
from decimal import Decimal
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import or_, func
from pydantic import BaseModel, Field

from app.database import get_db
from app.models import (
    Colegiado, Payment, Member, Organization, ConfiguracionFacturacion,
)
from app.models_debt_management import Debt
from app.routers.dashboard import get_current_member
from app.utils.templates import templates
from app.services.evaluar_habilidad import sincronizar_condicion
from app.services.facturacion import FacturacionService

logger = logging.getLogger(__name__)

PERU_TZ = timezone(timedelta(hours=-5))

ROLES_SECRETARIA = ("secretaria", "cajero", "tesorero", "admin", "sote")

# ============================================================
# ROUTER API
# ============================================================
router = APIRouter(prefix="/api/secretaria", tags=["Secretaria"])

# Router para la página HTML (sin prefix)
page_router = APIRouter(tags=["Secretaria"])


def require_secretaria(current_member: Member = Depends(get_current_member)):
    if current_member.role not in ROLES_SECRETARIA:
        raise HTTPException(status_code=403, detail="Acceso restringido")
    return current_member


# ============================================================
# SCHEMAS
# ============================================================

class BuscarColegiadoResponse(BaseModel):
    id: int
    dni: str
    codigo_matricula: Optional[str] = None
    apellidos_nombres: str
    email: Optional[str] = None
    telefono: Optional[str] = None
    condicion: Optional[str] = None
    habilidad_vence: Optional[str] = None
    total_deuda: float = 0
    deudas_pendientes: int = 0

    class Config:
        from_attributes = True


class DeudaResponse(BaseModel):
    id: int
    concepto: Optional[str] = None
    periodo: Optional[str] = None
    monto: float
    monto_pagado: float = 0
    saldo: float = 0
    fecha_vencimiento: Optional[str] = None
    estado: str
    debt_type: Optional[str] = None

    class Config:
        from_attributes = True


class RegistrarPagoRequest(BaseModel):
    colegiado_id: int
    deuda_ids: List[int]
    metodo_pago: str = "yape"
    nro_operacion: Optional[str] = None
    fecha_pago: Optional[str] = None
    nota: Optional[str] = None
    monto_pagado: Optional[float] = None  # Pago parcial (solo válido para 1 sola deuda)
    emitir_comprobante: bool = False
    tipo_comprobante: str = "03"
    forzar_condicion: Optional[str] = None  # null | "habil" | "inhabil"
    habilidad_vence: Optional[str] = None   # "2026-12-31"


class RegistrarPagoResponse(BaseModel):
    success: bool
    mensaje: str
    payment_id: Optional[int] = None
    deudas_actualizadas: int = 0
    total_pagado: float = 0
    nueva_condicion: Optional[str] = None
    habilidad_vence: Optional[str] = None
    nota_habilidad: Optional[str] = None
    comprobante_emitido: Optional[bool] = None
    comprobante_numero: Optional[str] = None
    comprobante_pdf: Optional[str] = None
    comprobante_mensaje: Optional[str] = None


# ============================================================
# PÁGINA HTML
# ============================================================

@page_router.get("/secretaria", response_class=HTMLResponse)
async def panel_secretaria(
    request: Request,
    current_member: Member = Depends(require_secretaria),
):
    return templates.TemplateResponse("pages/secretaria.html", {
        "request": request,
    })


# ============================================================
# ENDPOINTS API
# ============================================================

@router.get("/buscar-colegiado")
async def buscar_colegiado(
    q: str = Query(..., min_length=2, description="DNI, matrícula o nombre"),
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_secretaria),
):
    """Busca colegiados por DNI, código de matrícula o nombre."""
    q = q.strip()
    query = db.query(Colegiado)

    if q.isdigit() and len(q) >= 7:
        query = query.filter(Colegiado.dni == q)
    elif "-" in q:
        query = query.filter(Colegiado.codigo_matricula == q)
    else:
        query = query.filter(
            or_(
                Colegiado.apellidos_nombres.ilike(f"%{q}%"),
                Colegiado.dni.contains(q),
                Colegiado.codigo_matricula.contains(q),
            )
        )

    colegiados = query.limit(20).all()

    resultados = []
    for col in colegiados:
        deudas_info = db.query(
            func.count(Debt.id).label("cantidad"),
            func.coalesce(func.sum(Debt.amount), 0).label("total"),
        ).filter(
            Debt.colegiado_id == col.id,
            Debt.status.in_(["pending", "partial"]),
        ).first()

        resultados.append(BuscarColegiadoResponse(
            id=col.id,
            dni=col.dni or "",
            codigo_matricula=col.codigo_matricula or "",
            apellidos_nombres=col.apellidos_nombres or "",
            email=col.email,
            telefono=col.telefono,
            condicion=col.condicion,
            habilidad_vence=col.habilidad_vence.strftime("%d/%m/%Y") if col.habilidad_vence else None,
            total_deuda=float(deudas_info.total or 0),
            deudas_pendientes=int(deudas_info.cantidad or 0),
        ))

    return resultados


@router.get("/deudas/{colegiado_id}")
async def obtener_deudas(
    colegiado_id: int,
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_secretaria),
):
    """Obtiene las deudas pendientes de un colegiado."""
    colegiado = db.query(Colegiado).filter(Colegiado.id == colegiado_id).first()
    if not colegiado:
        raise HTTPException(404, detail="Colegiado no encontrado")

    deudas = db.query(Debt).filter(
        Debt.colegiado_id == colegiado_id,
        Debt.status.in_(["pending", "partial"]),
    ).order_by(Debt.periodo.asc()).all()

    resultado = []
    for d in deudas:
        monto = float(d.amount or 0)
        saldo = float(d.balance or 0)
        resultado.append(DeudaResponse(
            id=d.id,
            concepto=d.concept or "Cuota",
            periodo=str(d.periodo) if d.periodo else None,
            monto=monto,
            monto_pagado=monto - saldo,
            saldo=saldo,
            fecha_vencimiento=d.due_date.strftime("%d/%m/%Y") if d.due_date else None,
            estado=d.status,
            debt_type=d.debt_type,
        ))

    return {
        "colegiado": {
            "id": colegiado.id,
            "dni": colegiado.dni,
            "codigo_matricula": colegiado.codigo_matricula,
            "apellidos_nombres": colegiado.apellidos_nombres,
            "condicion": colegiado.condicion,
            "habilidad_vence": colegiado.habilidad_vence.strftime("%d/%m/%Y") if colegiado.habilidad_vence else None,
        },
        "deudas": resultado,
        "total_deuda": sum(d.saldo for d in resultado),
    }


MESES_NOMBRE = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
    5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
    9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre",
}


@router.get("/deudas-completas/{colegiado_id}")
async def deudas_completas(
    colegiado_id: int,
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_secretaria),
):
    """
    Retorna TODAS las deudas del colegiado separadas en dos grupos:
    - hasta_2025: deudas con periodo <= '2025-12'
    - anio_2026: deudas con periodo >= '2026-01' (incluye virtuales para meses sin deuda)
    """
    colegiado = db.query(Colegiado).filter(Colegiado.id == colegiado_id).first()
    if not colegiado:
        raise HTTPException(404, detail="Colegiado no encontrado")

    # Todas las deudas (excluir condonada/compensada ya resueltas)
    deudas = db.query(Debt).filter(
        Debt.colegiado_id == colegiado_id,
        ~Debt.estado_gestion.in_(["compensada"]),
    ).order_by(Debt.periodo.asc()).all()

    hasta_2025 = []
    anio_2026 = {}

    for d in deudas:
        item = {
            "id": d.id,
            "concept": d.concept or "Cuota",
            "period_label": d.period_label or (str(d.periodo) if d.periodo else ""),
            "periodo": str(d.periodo) if d.periodo else "",
            "amount": float(d.amount or 0),
            "balance": float(d.balance or 0),
            "status": d.status,
            "estado_gestion": d.estado_gestion or "vigente",
            "debt_type": d.debt_type or "cuota_ordinaria",
            "fraccionamiento_id": d.fraccionamiento_id,
        }

        periodo = str(d.periodo or "")
        if periodo >= "2026-01" and periodo <= "2026-12":
            anio_2026[periodo] = item
        elif periodo < "2026-01" or not periodo:
            hasta_2025.append(item)

    # Generar filas virtuales para meses 2026 sin deuda
    anio_2026_lista = []
    for mes in range(1, 13):
        periodo_key = f"2026-{mes:02d}"
        if periodo_key in anio_2026:
            anio_2026_lista.append(anio_2026[periodo_key])
        else:
            anio_2026_lista.append({
                "id": None,
                "concept": f"Cuota Ordinaria {MESES_NOMBRE[mes]} 2026",
                "period_label": f"{MESES_NOMBRE[mes]} 2026",
                "periodo": periodo_key,
                "amount": 0,
                "balance": 0,
                "status": "no_generada",
                "estado_gestion": "no_generada",
                "debt_type": "cuota_ordinaria",
            })

    return {
        "colegiado": {
            "id": colegiado.id,
            "dni": colegiado.dni,
            "codigo_matricula": colegiado.codigo_matricula,
            "apellidos_nombres": colegiado.apellidos_nombres,
            "condicion": colegiado.condicion,
            "habilidad_vence": colegiado.habilidad_vence.strftime("%d/%m/%Y") if colegiado.habilidad_vence else None,
        },
        "hasta_2025": hasta_2025,
        "anio_2026": anio_2026_lista,
    }


@router.post("/registrar-pago", response_model=RegistrarPagoResponse)
async def registrar_pago(
    pago: RegistrarPagoRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_secretaria),
):
    """
    Registra pagos reportados por WhatsApp/transferencia SIN sesión de caja.
    1. Valida que las deudas pertenecen al colegiado y están pending
    2. Crea Payment con status='approved'
    3. Marca deudas como paid, balance=0
    4. Llama sincronizar_condicion para recalcular condición
    5. Si emitir_comprobante=true: emite comprobante vía FacturacionService
    6. Retorna resumen
    """
    ahora = datetime.now(PERU_TZ)

    org = db.query(Organization).first()
    if not org:
        raise HTTPException(500, detail="Sin organización configurada")

    colegiado = db.query(Colegiado).filter(
        Colegiado.id == pago.colegiado_id
    ).first()
    if not colegiado:
        raise HTTPException(404, detail="Colegiado no encontrado")

    # ── Validar deudas ──
    if not pago.deuda_ids:
        raise HTTPException(400, detail="Debe seleccionar al menos una deuda")

    deudas = db.query(Debt).filter(
        Debt.id.in_(pago.deuda_ids),
        Debt.colegiado_id == pago.colegiado_id,
        Debt.status.in_(["pending", "partial"]),
    ).all()

    if len(deudas) != len(pago.deuda_ids):
        encontradas = {d.id for d in deudas}
        faltantes = set(pago.deuda_ids) - encontradas
        raise HTTPException(
            400,
            detail=f"Deudas no válidas o ya pagadas: {list(faltantes)}"
        )

    # ── Determinar si es pago parcial (solo aceptado para 1 sola deuda) ──
    es_pago_parcial = False
    monto_parcial = None
    if pago.monto_pagado is not None:
        if len(deudas) != 1:
            raise HTTPException(
                400,
                detail="El pago parcial solo se permite para una sola deuda a la vez"
            )
        monto_parcial = float(pago.monto_pagado)
        if monto_parcial <= 0:
            raise HTTPException(400, detail="El monto pagado debe ser mayor a 0")

        saldo_actual = float(deudas[0].balance or deudas[0].amount or 0)
        if monto_parcial > saldo_actual + 0.009:
            raise HTTPException(
                400,
                detail=f"Monto (S/ {monto_parcial:.2f}) supera el saldo pendiente (S/ {saldo_actual:.2f})"
            )
        # Si es menor al saldo → parcial; si es igual o prácticamente igual → total
        if monto_parcial < saldo_actual - 0.009:
            es_pago_parcial = True

    # ── Calcular total cobrado ──
    if es_pago_parcial:
        total = monto_parcial
    else:
        total = sum(float(d.balance or d.amount or 0) for d in deudas)

    # ── Descripción del pago ──
    descripciones = [
        f"{d.concept or 'Cuota'} {d.periodo or ''}".strip()
        for d in deudas
    ]
    descripcion_pago = "; ".join(descripciones[:5])
    if len(descripciones) > 5:
        descripcion_pago += f" (+{len(descripciones) - 5} más)"
    if es_pago_parcial:
        descripcion_pago += " [PARCIAL]"

    # ── Nota completa con identificación del operador ──
    operador_dni = ""
    if current_member and current_member.user:
        operador_dni = getattr(current_member.user, "public_id", "") or ""
    nota_payment = f"[SECRETARIA] DNI:{operador_dni} {ahora.strftime('%d/%m/%Y %H:%M')} - {descripcion_pago}"
    if pago.nro_operacion:
        nota_payment += f" | Op: {pago.nro_operacion}"
    if pago.nota:
        nota_payment += f" | {pago.nota}"

    # ── CREAR PAYMENT ──
    payment = Payment(
        organization_id=org.id,
        colegiado_id=pago.colegiado_id,
        amount=Decimal(str(total)),
        payment_method=pago.metodo_pago,
        operation_code=pago.nro_operacion,
        notes=nota_payment,
        status="approved",
        reviewed_at=ahora,
    )
    db.add(payment)
    db.flush()

    # ── MARCAR DEUDAS COMO PAGADAS (o parcial si aplica) ──
    if es_pago_parcial:
        deuda = deudas[0]
        saldo_actual = float(deuda.balance or deuda.amount or 0)
        nuevo_saldo = round(saldo_actual - monto_parcial, 2)
        deuda.status = "partial"
        deuda.balance = Decimal(str(nuevo_saldo))
        deuda.updated_by = current_member.user_id
        deuda.notes = (deuda.notes or "") + (
            f"\n[SECRETARIA:{operador_dni}] Pago parcial S/ {monto_parcial:.2f} "
            f"({ahora.strftime('%d/%m/%Y %H:%M')}) — saldo S/ {nuevo_saldo:.2f}"
        )
        deuda.notes = deuda.notes.strip()
    else:
        for deuda in deudas:
            deuda.status = "paid"
            deuda.balance = 0
            deuda.updated_by = current_member.user_id
            deuda.notes = (deuda.notes or "") + f"\n[SECRETARIA:{operador_dni}] Pagado {ahora.strftime('%d/%m/%Y %H:%M')}"
            deuda.notes = deuda.notes.strip()

    db.commit()

    # ── EVALUAR HABILIDAD ──
    org_data = getattr(request.state, "org", None) or {}
    cambio = sincronizar_condicion(db, colegiado, org_data)
    if cambio:
        db.commit()

    # ── REGLA 3 MESES: pago de Diciembre sin multas → habilidad hasta 31/03 siguiente ──
    nota_habilidad_extra = None
    meses_dic = [
        d for d in deudas
        if d.periodo and str(d.periodo).endswith("-12")
    ]
    # La regla aplica solo cuando el pago cubre completamente diciembre
    # (no aplica a pagos parciales sobre la cuota de diciembre).
    if meses_dic and not es_pago_parcial:
        multas_pendientes = db.query(Debt).filter(
            Debt.colegiado_id == pago.colegiado_id,
            Debt.debt_type == "multa",
            Debt.status.in_(["pending", "partial"]),
            ~Debt.estado_gestion.in_(["condonada", "justificada", "compensada", "exonerada"]),
        ).count()

        if multas_pendientes == 0:
            anio_dic = int(str(meses_dic[0].periodo)[:4])
            nueva_vence = datetime(anio_dic + 1, 3, 31, tzinfo=PERU_TZ)
            colegiado.habilidad_vence = nueva_vence
            colegiado.condicion = "habil"
            colegiado.fecha_actualizacion_condicion = ahora
            db.commit()
            nota_habilidad_extra = (
                f"Vigencia extendida 3 meses por pago completo del año "
                f"{anio_dic} — hábil hasta 31/03/{anio_dic + 1}"
            )
            logger.info(
                f"SECRETARIA regla +3 meses aplicada para colegiado {colegiado.id}: "
                f"habilidad_vence={nueva_vence.date()}"
            )

    # ── FORZAR CONDICIÓN (si se solicitó) ──
    if pago.forzar_condicion in ("habil", "inhabil"):
        colegiado.condicion = pago.forzar_condicion
        colegiado.fecha_actualizacion_condicion = ahora
        if pago.forzar_condicion == "habil" and pago.habilidad_vence:
            try:
                colegiado.habilidad_vence = datetime.strptime(pago.habilidad_vence, "%Y-%m-%d").replace(tzinfo=PERU_TZ)
            except ValueError:
                pass
        elif pago.forzar_condicion == "inhabil":
            colegiado.habilidad_vence = None
        db.commit()
        logger.info(f"SECRETARIA forzó condición={pago.forzar_condicion} para colegiado {colegiado.id} por operador DNI:{operador_dni}")

    db.refresh(colegiado)
    nueva_condicion = colegiado.condicion

    # ── EMITIR COMPROBANTE ──
    comprobante_info = {}
    if pago.emitir_comprobante:
        try:
            service = FacturacionService(db, org.id)
            if service.esta_configurado():
                tipo = pago.tipo_comprobante or "03"
                resultado = await service.emitir_comprobante_por_pago(
                    payment_id=payment.id,
                    tipo=tipo,
                    sede_id="1",
                    forma_pago="contado",
                )
                logger.info(f"SECRETARIA FACTURALO RESULTADO: {resultado}")
                comprobante_info = {
                    "comprobante_emitido": resultado.get("success", False),
                    "comprobante_numero": resultado.get("numero_formato"),
                    "comprobante_pdf": resultado.get("pdf_url"),
                    "comprobante_mensaje": resultado.get("error"),
                }
            else:
                comprobante_info = {
                    "comprobante_emitido": False,
                    "comprobante_mensaje": "Facturación no configurada",
                }
        except Exception as e:
            logger.error(f"Error facturación secretaria: {e}", exc_info=True)
            comprobante_info = {
                "comprobante_emitido": False,
                "comprobante_mensaje": f"Error: {str(e)[:100]}",
            }

    mensaje_pago = (
        f"Pago parcial registrado: S/ {total:.2f} ({pago.metodo_pago})"
        if es_pago_parcial
        else f"Pago registrado: S/ {total:.2f} ({pago.metodo_pago})"
    )

    habilidad_vence_str = (
        colegiado.habilidad_vence.strftime("%d/%m/%Y")
        if colegiado.habilidad_vence
        else None
    )

    return RegistrarPagoResponse(
        success=True,
        mensaje=mensaje_pago,
        payment_id=payment.id,
        deudas_actualizadas=len(deudas),
        total_pagado=total,
        nueva_condicion=nueva_condicion,
        habilidad_vence=habilidad_vence_str,
        nota_habilidad=nota_habilidad_extra,
        **comprobante_info,
    )


# ============================================================
# ACTUALIZAR CONDICIÓN (independiente de pagos)
# ============================================================

class ActualizarCondicionRequest(BaseModel):
    colegiado_id: int
    condicion: str  # "habil" | "inhabil"
    habilidad_vence: Optional[str] = None  # "2026-12-31"
    motivo: Optional[str] = None


@router.post("/actualizar-condicion")
async def actualizar_condicion(
    datos: ActualizarCondicionRequest,
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_secretaria),
):
    """
    Actualiza condición de habilidad de un colegiado.
    Independiente del registro de pagos.
    """
    ahora = datetime.now(PERU_TZ)

    if datos.condicion not in ("habil", "inhabil"):
        raise HTTPException(400, detail="Condición debe ser 'habil' o 'inhabil'")

    colegiado = db.query(Colegiado).filter(Colegiado.id == datos.colegiado_id).first()
    if not colegiado:
        raise HTTPException(404, detail="Colegiado no encontrado")

    operador_dni = ""
    if current_member and current_member.user:
        operador_dni = getattr(current_member.user, "public_id", "") or ""

    condicion_anterior = colegiado.condicion

    # ── Actualizar condición ──
    colegiado.condicion = datos.condicion
    colegiado.fecha_actualizacion_condicion = ahora

    if datos.condicion == "habil":
        if datos.habilidad_vence:
            try:
                colegiado.habilidad_vence = datetime.strptime(
                    datos.habilidad_vence, "%Y-%m-%d"
                ).replace(tzinfo=PERU_TZ)
            except ValueError:
                raise HTTPException(400, detail="Formato de fecha inválido (usar YYYY-MM-DD)")
        else:
            colegiado.habilidad_vence = datetime(2026, 12, 31, tzinfo=PERU_TZ)
        colegiado.motivo_inhabilidad = None
    else:
        colegiado.habilidad_vence = None
        colegiado.motivo_inhabilidad = datos.motivo

    # ── Auditoría ──
    vence_str = colegiado.habilidad_vence.strftime("%d/%m/%Y") if colegiado.habilidad_vence else "—"
    nota_audit = (
        f"[SECRETARIA:{operador_dni}] Condición: {condicion_anterior}→{datos.condicion}"
        f" hasta {vence_str}."
    )
    if datos.motivo:
        nota_audit += f" Motivo: {datos.motivo}"

    logger.info(nota_audit + f" | colegiado_id={colegiado.id}")

    db.commit()
    db.refresh(colegiado)

    return {
        "ok": True,
        "condicion": colegiado.condicion,
        "habilidad_vence": colegiado.habilidad_vence.strftime("%d/%m/%Y") if colegiado.habilidad_vence else None,
        "mensaje": f"Condición actualizada a {datos.condicion.upper()}"
                   + (f" hasta {vence_str}" if datos.condicion == "habil" else ""),
    }


# ============================================================
# JUSTIFICAR DEUDA (multas)
# ============================================================

class JustificarDeudaRequest(BaseModel):
    deuda_id: int
    motivo: str
    nro_documento: Optional[str] = None


@router.post("/justificar-deuda")
async def justificar_deuda(
    datos: JustificarDeudaRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_secretaria),
):
    """Justifica una deuda (multa). La marca como pagada con estado_gestion='justificada'."""
    ahora = datetime.now(PERU_TZ)

    deuda = db.query(Debt).filter(
        Debt.id == datos.deuda_id,
        Debt.status.in_(["pending", "partial"]),
    ).first()
    if not deuda:
        raise HTTPException(404, detail="Deuda no encontrada o ya pagada")

    operador_dni = ""
    if current_member and current_member.user:
        operador_dni = getattr(current_member.user, "public_id", "") or ""

    deuda.status = "paid"
    deuda.balance = 0
    deuda.estado_gestion = "justificada"
    deuda.updated_by = current_member.user_id

    nota_doc = f" Doc: {datos.nro_documento}" if datos.nro_documento else ""
    deuda.notes = (
        (deuda.notes or "")
        + f"\n[SECRETARIA:{operador_dni}] Justificada: {datos.motivo}.{nota_doc}"
    ).strip()

    db.commit()

    # Recalcular condición
    colegiado = db.query(Colegiado).filter(Colegiado.id == deuda.colegiado_id).first()
    if colegiado:
        org_data = getattr(request.state, "org", None) or {}
        cambio = sincronizar_condicion(db, colegiado, org_data)
        if cambio:
            db.commit()
        db.refresh(colegiado)

    return {
        "ok": True,
        "mensaje": f"Deuda justificada: {deuda.concept or 'Cuota'} {deuda.periodo or ''}",
        "nueva_condicion": colegiado.condicion if colegiado else None,
    }


# ============================================================
# CONDONAR DEUDA
# ============================================================

class CondonarDeudaRequest(BaseModel):
    deuda_id: int
    tipo_condona: str  # Acuerdo de Directiva, Asamblea, Resolución, Otro
    nro_acuerdo: Optional[str] = None
    observaciones: Optional[str] = None


@router.post("/condonar-deuda")
async def condonar_deuda(
    datos: CondonarDeudaRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_secretaria),
):
    """Condona una deuda. La marca como pagada con estado_gestion='condonada'."""
    ahora = datetime.now(PERU_TZ)

    deuda = db.query(Debt).filter(
        Debt.id == datos.deuda_id,
        Debt.status.in_(["pending", "partial"]),
    ).first()
    if not deuda:
        raise HTTPException(404, detail="Deuda no encontrada o ya pagada")

    operador_dni = ""
    if current_member and current_member.user:
        operador_dni = getattr(current_member.user, "public_id", "") or ""

    deuda.status = "paid"
    deuda.balance = 0
    deuda.estado_gestion = "condonada"
    deuda.updated_by = current_member.user_id

    nro = f" {datos.nro_acuerdo}" if datos.nro_acuerdo else ""
    obs = f" {datos.observaciones}" if datos.observaciones else ""
    deuda.notes = (
        (deuda.notes or "")
        + f"\n[SECRETARIA:{operador_dni}] Condonada: {datos.tipo_condona}{nro}.{obs}"
    ).strip()

    db.commit()

    # Recalcular condición
    colegiado = db.query(Colegiado).filter(Colegiado.id == deuda.colegiado_id).first()
    if colegiado:
        org_data = getattr(request.state, "org", None) or {}
        cambio = sincronizar_condicion(db, colegiado, org_data)
        if cambio:
            db.commit()
        db.refresh(colegiado)

    return {
        "ok": True,
        "mensaje": f"Deuda condonada: {deuda.concept or 'Cuota'} {deuda.periodo or ''}",
        "nueva_condicion": colegiado.condicion if colegiado else None,
    }


# ============================================================
# FRACCIONAMIENTOS
# ============================================================

from app.models_debt_management import Fraccionamiento, FraccionamientoCuota
from app.services.fraccionamiento_service import (
    crear_fraccionamiento as _crear_fraccionamiento_helper,
    pagar_cuota_fraccionamiento as _pagar_cuota_helper,
)


class RegistrarFraccionamientoRequest(BaseModel):
    colegiado_id: int
    n_cuotas: int
    monto_cuota_inicial: float
    monto_cuota_mensual: Optional[float] = None
    deuda_ids: List[int]
    nota: Optional[str] = None


class RegistrarPagoCuotaFraccRequest(BaseModel):
    fraccionamiento_id: int
    n_cuota: int
    monto: float
    metodo_pago: str = "yape"
    nro_operacion: Optional[str] = None
    nota: Optional[str] = None


@router.get("/fraccionamientos/{colegiado_id}")
async def listar_fraccionamientos_colegiado(
    colegiado_id: int,
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_secretaria),
):
    """Lista los fraccionamientos de un colegiado con sus cuotas y resumen."""
    colegiado = db.query(Colegiado).filter(Colegiado.id == colegiado_id).first()
    if not colegiado:
        raise HTTPException(404, "Colegiado no encontrado")

    planes = (
        db.query(Fraccionamiento)
        .filter(Fraccionamiento.colegiado_id == colegiado_id)
        .order_by(Fraccionamiento.fecha_solicitud.desc())
        .all()
    )

    resultado = []
    for p in planes:
        cuotas = (
            db.query(FraccionamientoCuota)
            .filter(FraccionamientoCuota.fraccionamiento_id == p.id)
            .order_by(FraccionamientoCuota.numero_cuota.asc())
            .all()
        )
        cuotas_list = []
        hoy = date.today()
        for c in cuotas:
            vencida = (
                (not c.pagada)
                and c.fecha_vencimiento
                and c.fecha_vencimiento < hoy
            )
            estado = (
                "pagada" if c.pagada
                else ("vencida" if vencida else "pendiente")
            )
            cuotas_list.append({
                "id": c.id,
                "n_cuota": c.numero_cuota,
                "es_inicial": c.numero_cuota == 0,
                "monto": float(c.monto or 0),
                "fecha_vencimiento": c.fecha_vencimiento.isoformat() if c.fecha_vencimiento else None,
                "fecha_pago": c.fecha_pago.isoformat() if c.fecha_pago else None,
                "pagada": bool(c.pagada),
                "estado": estado,
                "habilidad_hasta": c.habilidad_hasta.isoformat() if c.habilidad_hasta else None,
            })

        cuotas_pagadas = sum(1 for c in cuotas if c.pagada)
        cuotas_pendientes = len(cuotas) - cuotas_pagadas

        proxima = next(
            (c for c in cuotas if not c.pagada),
            None,
        )
        resultado.append({
            "id": p.id,
            "numero_solicitud": p.numero_solicitud,
            "estado": p.estado,
            "fecha_solicitud": p.fecha_solicitud.isoformat() if p.fecha_solicitud else None,
            "fecha_inicio": p.fecha_inicio.isoformat() if p.fecha_inicio else None,
            "fecha_fin_estimada": p.fecha_fin_estimada.isoformat() if p.fecha_fin_estimada else None,
            "deuda_total_original": float(p.deuda_total_original or 0),
            "cuota_inicial": float(p.cuota_inicial or 0),
            "cuota_inicial_pagada": bool(p.cuota_inicial_pagada),
            "saldo_a_fraccionar": float(p.saldo_a_fraccionar or 0),
            "num_cuotas": p.num_cuotas,
            "monto_cuota": float(p.monto_cuota or 0),
            "cuotas_pagadas": cuotas_pagadas,
            "cuotas_pendientes": cuotas_pendientes,
            "saldo_pendiente": float(p.saldo_pendiente or 0),
            "proxima_cuota_numero": p.proxima_cuota_numero,
            "proxima_cuota_fecha": p.proxima_cuota_fecha.isoformat() if p.proxima_cuota_fecha else None,
            "cuotas": cuotas_list,
        })

    return {
        "colegiado_id": colegiado_id,
        "fraccionamientos": resultado,
        "tiene_plan_activo": any(p["estado"] == "activo" for p in resultado),
    }


@router.post("/registrar-fraccionamiento")
async def registrar_fraccionamiento(
    datos: RegistrarFraccionamientoRequest,
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_secretaria),
):
    """Secretaria otorga un plan de fraccionamiento a un colegiado."""
    colegiado = db.query(Colegiado).filter(
        Colegiado.id == datos.colegiado_id
    ).first()
    if not colegiado:
        raise HTTPException(404, "Colegiado no encontrado")

    ahora = datetime.now(PERU_TZ)
    operador_dni = ""
    if current_member and current_member.user:
        operador_dni = getattr(current_member.user, "public_id", "") or ""

    nota_audit = (
        f"[SECRETARIA:{operador_dni}] Fraccionamiento otorgado "
        f"{ahora.strftime('%d/%m/%Y %H:%M')}"
    )
    if datos.nota:
        nota_audit += f" — {datos.nota}"

    resultado = _crear_fraccionamiento_helper(
        db=db,
        colegiado=colegiado,
        deuda_ids=datos.deuda_ids,
        n_cuotas=datos.n_cuotas,
        monto_cuota_inicial=datos.monto_cuota_inicial,
        monto_cuota_mensual=datos.monto_cuota_mensual,
        created_by_user_id=current_member.user_id,
        nota_audit=nota_audit,
        aplicar_acuerdo_007=True,
    )

    fracc = resultado.fraccionamiento
    return {
        "ok": True,
        "fraccionamiento_id": fracc.id,
        "numero_solicitud": fracc.numero_solicitud,
        "cronograma": resultado.cronograma,
        "condona_007": resultado.condona_detalle,
        "mensaje": (
            f"Plan {fracc.numero_solicitud} creado. "
            f"Cuota inicial S/ {float(fracc.cuota_inicial):.2f}, "
            f"{fracc.num_cuotas} cuotas de S/ {float(fracc.monto_cuota):.2f}."
        ),
    }


@router.post("/registrar-pago-cuota-fracc")
async def registrar_pago_cuota_fracc(
    datos: RegistrarPagoCuotaFraccRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_secretaria),
):
    """Registra el pago de una cuota puntual del fraccionamiento."""
    if datos.monto <= 0:
        raise HTTPException(400, "El monto debe ser mayor a 0")

    fracc = db.query(Fraccionamiento).filter(
        Fraccionamiento.id == datos.fraccionamiento_id
    ).first()
    if not fracc:
        raise HTTPException(404, "Fraccionamiento no encontrado")

    colegiado = db.query(Colegiado).filter(
        Colegiado.id == fracc.colegiado_id
    ).first()
    if not colegiado:
        raise HTTPException(404, "Colegiado del fraccionamiento no encontrado")

    org = db.query(Organization).first()
    if not org:
        raise HTTPException(500, "Sin organización configurada")

    ahora = datetime.now(PERU_TZ)
    operador_dni = ""
    if current_member and current_member.user:
        operador_dni = getattr(current_member.user, "public_id", "") or ""

    nota_payment = (
        f"[SECRETARIA:{operador_dni}] {ahora.strftime('%d/%m/%Y %H:%M')} "
        f"- Cuota #{datos.n_cuota} fracc {fracc.numero_solicitud}"
    )
    if datos.nro_operacion:
        nota_payment += f" | Op: {datos.nro_operacion}"
    if datos.nota:
        nota_payment += f" | {datos.nota}"

    payment = Payment(
        organization_id=org.id,
        colegiado_id=colegiado.id,
        amount=Decimal(str(datos.monto)),
        payment_method=datos.metodo_pago,
        operation_code=datos.nro_operacion,
        notes=nota_payment,
        status="approved",
        reviewed_at=ahora,
    )
    db.add(payment)
    db.flush()

    info_cuota = _pagar_cuota_helper(
        db=db,
        fraccionamiento_id=datos.fraccionamiento_id,
        numero_cuota=datos.n_cuota,
        monto=datos.monto,
        metodo_pago=datos.metodo_pago,
        operador_nota=nota_payment,
        payment_obj=payment,
    )

    # Habilidad del colegiado:
    # - Cuota inicial → hábil hasta fin de mes actual como mínimo
    # - Cuota mensual → habilidad_hasta definida en la cuota
    nota_habilidad = None
    if info_cuota["es_inicial"]:
        # Hábil hasta fin del mes en curso
        fin_mes = (ahora.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        colegiado.condicion = "habil"
        colegiado.habilidad_vence = fin_mes
        colegiado.fecha_actualizacion_condicion = ahora
        nota_habilidad = (
            f"Cuota inicial pagada — colegiado HÁBIL hasta "
            f"{fin_mes.strftime('%d/%m/%Y')}"
        )
    elif info_cuota["habilidad_hasta"]:
        nueva = datetime.strptime(info_cuota["habilidad_hasta"], "%Y-%m-%d").replace(tzinfo=PERU_TZ)
        colegiado.condicion = "habil"
        colegiado.habilidad_vence = nueva
        colegiado.fecha_actualizacion_condicion = ahora
        nota_habilidad = (
            f"Cuota {datos.n_cuota} pagada — habilidad extendida hasta "
            f"{nueva.strftime('%d/%m/%Y')}"
        )

    db.commit()
    db.refresh(colegiado)
    db.refresh(fracc)

    return {
        "ok": True,
        "mensaje": f"Cuota #{datos.n_cuota} registrada (S/ {datos.monto:.2f})",
        "payment_id": payment.id,
        "cuota": info_cuota,
        "plan_completado": info_cuota["completado"],
        "nueva_condicion": colegiado.condicion,
        "habilidad_vence": colegiado.habilidad_vence.strftime("%d/%m/%Y") if colegiado.habilidad_vence else None,
        "nota_habilidad": nota_habilidad,
    }


@router.get("/fraccionamiento/{fraccionamiento_id}/cronograma-pdf")
async def cronograma_pdf(
    fraccionamiento_id: int,
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_secretaria),
):
    """Genera un PDF con el cronograma de cuotas del fraccionamiento."""
    from fastapi.responses import Response
    from app.services.pdf_cronograma_fracc import generar_cronograma_pdf

    fracc = db.query(Fraccionamiento).filter(
        Fraccionamiento.id == fraccionamiento_id
    ).first()
    if not fracc:
        raise HTTPException(404, "Fraccionamiento no encontrado")

    colegiado = db.query(Colegiado).filter(
        Colegiado.id == fracc.colegiado_id
    ).first()
    if not colegiado:
        raise HTTPException(404, "Colegiado no encontrado")

    cuotas = (
        db.query(FraccionamientoCuota)
        .filter(FraccionamientoCuota.fraccionamiento_id == fraccionamiento_id)
        .order_by(FraccionamientoCuota.numero_cuota.asc())
        .all()
    )

    pdf_bytes = generar_cronograma_pdf(fracc, colegiado, cuotas)
    filename = f"cronograma_{fracc.numero_solicitud}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
        },
    )


# ============================================================
# REVISIÓN DE PENDIENTES
# ============================================================

from sqlalchemy import text as sa_text


class ResolverRevisionRequest(BaseModel):
    id: int
    accion: str  # 'resolver' | 'descartar'
    notas: Optional[str] = None


@router.get("/revisiones")
async def listar_revisiones(
    estado: Optional[str] = Query(None),
    motivo: Optional[str] = Query(None),
    anio_origen: Optional[str] = Query(None),
    matricula: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_secretaria),
):
    """Lista paginada de revision_pendiente con filtros."""
    where_clauses = []
    params = {}

    if estado:
        where_clauses.append("r.estado = :estado")
        params["estado"] = estado
    if motivo:
        where_clauses.append("r.motivo = :motivo")
        params["motivo"] = motivo
    if anio_origen:
        where_clauses.append("r.anio_origen = :anio_origen")
        params["anio_origen"] = anio_origen
    if matricula:
        where_clauses.append("r.matricula ILIKE :matricula")
        params["matricula"] = f"%{matricula.strip()}%"

    where_sql = (" AND ".join(where_clauses)) if where_clauses else "1=1"

    # Total
    count_row = db.execute(
        sa_text(f"SELECT COUNT(*) FROM revision_pendiente r WHERE {where_sql}"),
        params,
    ).scalar()
    total = int(count_row or 0)

    # Datos paginados
    offset = (page - 1) * per_page
    params["limit"] = per_page
    params["offset"] = offset

    rows = db.execute(sa_text(f"""
        SELECT r.*,
               c.apellidos_nombres,
               c.id AS colegiado_id
        FROM revision_pendiente r
        LEFT JOIN colegiados c
            ON c.codigo_matricula = r.matricula
           AND c.organization_id = r.organization_id
        WHERE {where_sql}
        ORDER BY r.id ASC
        LIMIT :limit OFFSET :offset
    """), params).mappings().all()

    items = []
    for row in rows:
        items.append({
            "id": row["id"],
            "matricula": row["matricula"],
            "concepto": row["concepto"],
            "periodo_raw": row["periodo_raw"],
            "importe": float(row["importe"] or 0),
            "motivo": row["motivo"],
            "forma_pago": row["forma_pago"],
            "anio_origen": row["anio_origen"],
            "estado": row["estado"],
            "notas_resolucion": row["notas_resolucion"],
            "created_at": str(row["created_at"]) if row["created_at"] else None,
            "apellidos_nombres": row.get("apellidos_nombres") or None,
            "colegiado_id": row.get("colegiado_id") or None,
        })

    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": max(1, -(-total // per_page)),
    }


@router.post("/resolver-revision")
async def resolver_revision(
    datos: ResolverRevisionRequest,
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_secretaria),
):
    """Marca una revisión pendiente como resuelta o descartada."""
    if datos.accion not in ("resolver", "descartar"):
        raise HTTPException(400, "Acción debe ser 'resolver' o 'descartar'")

    ahora = datetime.now(PERU_TZ)
    nuevo_estado = "resuelto" if datos.accion == "resolver" else "descartado"

    result = db.execute(sa_text("""
        UPDATE revision_pendiente
        SET estado = :estado,
            resuelto_por = :member_id,
            fecha_resolucion = :ahora,
            notas_resolucion = :notas
        WHERE id = :id AND estado = 'pendiente'
    """), {
        "estado": nuevo_estado,
        "member_id": current_member.user_id,
        "ahora": ahora,
        "notas": datos.notas or "",
        "id": datos.id,
    })
    db.commit()

    if result.rowcount == 0:
        raise HTTPException(404, "Revisión no encontrada o ya resuelta")

    return {
        "ok": True,
        "mensaje": f"Revisión #{datos.id} marcada como {nuevo_estado}.",
    }


@router.get("/revisiones/stats")
async def revisiones_stats(
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_secretaria),
):
    """Estadísticas de revisiones pendientes: total, por motivo y por año."""
    total_row = db.execute(sa_text(
        "SELECT COUNT(*) FROM revision_pendiente WHERE estado = 'pendiente'"
    )).scalar()
    total_pendiente = int(total_row or 0)

    por_motivo_rows = db.execute(sa_text("""
        SELECT motivo, COUNT(*) AS cant
        FROM revision_pendiente
        WHERE estado = 'pendiente'
        GROUP BY motivo
        ORDER BY cant DESC
    """)).all()
    por_motivo = {row[0]: int(row[1]) for row in por_motivo_rows}

    por_anio_rows = db.execute(sa_text("""
        SELECT anio_origen, COUNT(*) AS cant
        FROM revision_pendiente
        WHERE estado = 'pendiente'
        GROUP BY anio_origen
        ORDER BY anio_origen DESC
    """)).all()
    por_anio = {row[0]: int(row[1]) for row in por_anio_rows}

    return {
        "total_pendiente": total_pendiente,
        "por_motivo": por_motivo,
        "por_anio": por_anio,
    }

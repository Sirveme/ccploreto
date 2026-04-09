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

    class Config:
        from_attributes = True


class RegistrarPagoRequest(BaseModel):
    colegiado_id: int
    deuda_ids: List[int]
    metodo_pago: str = "yape"
    nro_operacion: Optional[str] = None
    fecha_pago: Optional[str] = None
    nota: Optional[str] = None
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

    # ── Calcular total ──
    total = sum(float(d.balance or d.amount or 0) for d in deudas)

    # ── Descripción del pago ──
    descripciones = [
        f"{d.concept or 'Cuota'} {d.periodo or ''}".strip()
        for d in deudas
    ]
    descripcion_pago = "; ".join(descripciones[:5])
    if len(descripciones) > 5:
        descripcion_pago += f" (+{len(descripciones) - 5} más)"

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

    # ── MARCAR DEUDAS COMO PAGADAS ──
    for deuda in deudas:
        deuda.status = "paid"
        deuda.balance = 0
        deuda.notes = (deuda.notes or "") + f"\n[SECRETARIA:{operador_dni}] Pagado {ahora.strftime('%d/%m/%Y %H:%M')}"
        deuda.notes = deuda.notes.strip()

    db.commit()

    # ── EVALUAR HABILIDAD ──
    org_data = getattr(request.state, "org", None) or {}
    cambio = sincronizar_condicion(db, colegiado, org_data)
    if cambio:
        db.commit()

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

    return RegistrarPagoResponse(
        success=True,
        mensaje=f"Pago registrado: S/ {total:.2f} ({pago.metodo_pago})",
        payment_id=payment.id,
        deudas_actualizadas=len(deudas),
        total_pagado=total,
        nueva_condicion=nueva_condicion,
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

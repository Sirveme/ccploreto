"""
Módulo: Caja - Cobros Presenciales
app/routes/caja.py

Pantalla de caja para el personal del CCPL.
Flujo: Buscar colegiado → Ver deudas → Cobrar → Emitir comprobante

Requiere rol: cajero, tesorero o admin
"""

from datetime import datetime, timezone, timedelta
from typing import Optional, List
from decimal import Decimal

from fastapi import Request
from fastapi.templating import Jinja2Templates

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import or_, func, and_
from pydantic import BaseModel, Field

from app.database import get_db
from app.models import (
    Colegiado, Debt, Payment, Comprobante, ConceptoCobro,
    UsuarioAdmin, CentroCosto, Organization,
    ConfiguracionFacturacion
)

templates = Jinja2Templates(directory="app/templates")
router = APIRouter(prefix="/api/caja", tags=["Caja"])

PERU_TZ = timezone(timedelta(hours=-5))

@router.get("/caja")
async def pagina_caja(request: Request):
    """Sirve la página de caja"""
    member_id = request.session.get("member_id")
    if not member_id:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("pages/caja.html", {"request": request})

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
    habilitado: bool = False
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


class ItemCobro(BaseModel):
    """Item individual a cobrar"""
    tipo: str = "deuda"                    # "deuda" o "concepto"
    deuda_id: Optional[int] = None         # Si tipo=deuda
    concepto_id: Optional[int] = None      # Si tipo=concepto
    descripcion: str = ""
    cantidad: int = 1
    monto_unitario: float = 0
    monto_total: float = 0


class RegistrarCobroRequest(BaseModel):
    """Request para registrar un cobro"""
    colegiado_id: Optional[int] = None     # Opcional para ventas al público
    items: List[ItemCobro]
    total: float
    metodo_pago: str = "efectivo"          # efectivo, tarjeta, transferencia, yape, plin
    referencia_pago: Optional[str] = None  # Nro operación, nro voucher
    observaciones: Optional[str] = None
    tipo_comprobante: str = "03"           # 03=boleta, 01=factura
    # Solo si factura (tipo=01)
    cliente_ruc: Optional[str] = None
    cliente_razon_social: Optional[str] = None
    cliente_direccion: Optional[str] = None


class CobroResponse(BaseModel):
    success: bool
    mensaje: str
    payment_id: Optional[int] = None
    comprobante_id: Optional[int] = None
    numero_comprobante: Optional[str] = None
    total: float = 0


# ============================================================
# ENDPOINTS
# ============================================================

@router.get("/buscar-colegiado")
async def buscar_colegiado(
    q: str = Query(..., min_length=2, description="DNI, matrícula o nombre"),
    db: Session = Depends(get_db),
):
    """
    Busca colegiados por DNI, código de matrícula o nombre.
    Retorna lista con resumen de deudas.
    """
    q = q.strip()
    query = db.query(Colegiado)

    # Buscar por DNI exacto
    if q.isdigit() and len(q) >= 7:
        query = query.filter(Colegiado.dni == q)
    # Buscar por código de matrícula (formato: 10-XXXX)
    elif "-" in q:
        query = query.filter(Colegiado.codigo_matricula == q)
    # Buscar por nombre (parcial)
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
        # Contar deudas pendientes
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
            habilitado=getattr(col, 'habilitado', False),
            total_deuda=float(deudas_info.total or 0),
            deudas_pendientes=int(deudas_info.cantidad or 0),
        ))

    return resultados


@router.get("/deudas/{colegiado_id}")
async def obtener_deudas(
    colegiado_id: int,
    db: Session = Depends(get_db),
):
    """
    Obtiene las deudas pendientes de un colegiado.
    Ordenadas por periodo (más antiguas primero).
    """
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
        pagado = float(getattr(d, 'amount_paid', 0) or 0)
        resultado.append(DeudaResponse(
            id=d.id,
            concepto=d.concept or "Cuota",
            periodo=str(d.periodo) if d.periodo else None,
            monto=monto,
            monto_pagado=pagado,
            saldo=monto - pagado,
            fecha_vencimiento=d.due_date.strftime("%d/%m/%Y") if getattr(d, 'due_date', None) else None,
            estado=d.status,
        ))

    return {
        "colegiado": {
            "id": colegiado.id,
            "dni": colegiado.dni,
            "codigo_matricula": colegiado.codigo_matricula,
            "apellidos_nombres": colegiado.apellidos_nombres,
            "habilitado": getattr(colegiado, 'habilitado', False),
        },
        "deudas": resultado,
        "total_deuda": sum(d.saldo for d in resultado),
    }


@router.get("/conceptos")
async def listar_conceptos(
    categoria: Optional[str] = None,
    solo_publico: bool = False,
    db: Session = Depends(get_db),
):
    """
    Lista conceptos de cobro disponibles para la caja.
    Filtrable por categoría.
    """
    query = db.query(ConceptoCobro).filter(
        ConceptoCobro.activo == True,
    )

    if categoria:
        query = query.filter(ConceptoCobro.categoria == categoria)

    if solo_publico:
        query = query.filter(ConceptoCobro.aplica_a_publico == True)

    conceptos = query.order_by(ConceptoCobro.orden, ConceptoCobro.nombre).all()

    return [{
        "id": c.id,
        "codigo": c.codigo,
        "nombre": c.nombre,
        "nombre_corto": c.nombre_corto,
        "categoria": c.categoria,
        "monto_base": c.monto_base,
        "permite_monto_libre": c.permite_monto_libre,
        "afecto_igv": c.afecto_igv,
        "requiere_colegiado": c.requiere_colegiado,
        "maneja_stock": c.maneja_stock,
        "stock_actual": c.stock_actual if c.maneja_stock else None,
    } for c in conceptos]


@router.get("/categorias")
async def listar_categorias(db: Session = Depends(get_db)):
    """Lista las categorías de conceptos que tienen conceptos activos"""
    categorias = db.query(
        ConceptoCobro.categoria,
        func.count(ConceptoCobro.id).label("total")
    ).filter(
        ConceptoCobro.activo == True
    ).group_by(
        ConceptoCobro.categoria
    ).order_by(
        ConceptoCobro.categoria
    ).all()

    NOMBRES = {
        "cuotas": "Cuotas",
        "constancias": "Constancias",
        "derechos": "Derechos",
        "capacitacion": "Capacitación",
        "alquileres": "Alquileres",
        "recreacion": "Recreación",
        "mercaderia": "Mercadería",
        "multas": "Multas",
        "eventos": "Eventos",
        "otros": "Otros",
    }

    return [{
        "codigo": cat,
        "nombre": NOMBRES.get(cat, cat.title()),
        "total": total,
    } for cat, total in categorias]


@router.post("/cobrar", response_model=CobroResponse)
async def registrar_cobro(
    cobro: RegistrarCobroRequest,
    db: Session = Depends(get_db),
):
    """
    Registra un cobro presencial.

    Flujo:
    1. Valida items (deudas existentes o conceptos del catálogo)
    2. Crea registro de Payment
    3. Marca deudas como pagadas
    4. Actualiza stock si hay mercadería
    5. Retorna datos para emisión de comprobante
    """
    ahora = datetime.now(PERU_TZ)

    # Obtener organización (primera activa - en SaaS vendrá del usuario)
    org = db.query(Organization).first()
    if not org:
        raise HTTPException(500, detail="Sin organización configurada")

    # Validar colegiado si se requiere
    colegiado = None
    if cobro.colegiado_id:
        colegiado = db.query(Colegiado).filter(
            Colegiado.id == cobro.colegiado_id
        ).first()
        if not colegiado:
            raise HTTPException(404, detail="Colegiado no encontrado")

    # Validar y procesar items
    total_calculado = 0
    items_procesados = []
    deudas_a_pagar = []

    for item in cobro.items:
        if item.tipo == "deuda" and item.deuda_id:
            # Verificar deuda
            deuda = db.query(Debt).filter(
                Debt.id == item.deuda_id,
                Debt.status.in_(["pending", "partial"]),
            ).first()
            if not deuda:
                raise HTTPException(400, detail=f"Deuda {item.deuda_id} no encontrada o ya pagada")

            monto = float(deuda.amount or 0)
            pagado = float(getattr(deuda, 'amount_paid', 0) or 0)
            saldo = monto - pagado

            items_procesados.append({
                "tipo": "deuda",
                "deuda_id": deuda.id,
                "descripcion": f"{deuda.concept or 'Cuota'} {deuda.periodo or ''}".strip(),
                "monto": saldo,
            })
            deudas_a_pagar.append(deuda)
            total_calculado += saldo

        elif item.tipo == "concepto" and item.concepto_id:
            # Verificar concepto
            concepto = db.query(ConceptoCobro).filter(
                ConceptoCobro.id == item.concepto_id,
                ConceptoCobro.activo == True,
            ).first()
            if not concepto:
                raise HTTPException(400, detail=f"Concepto {item.concepto_id} no encontrado")

            # Validar monto
            if concepto.permite_monto_libre:
                monto = item.monto_unitario if item.monto_unitario > 0 else concepto.monto_base
            else:
                monto = concepto.monto_base

            if monto <= 0:
                raise HTTPException(400, detail=f"Monto inválido para {concepto.nombre}")

            # Validar stock
            if concepto.maneja_stock:
                if concepto.stock_actual < item.cantidad:
                    raise HTTPException(400,
                        detail=f"Stock insuficiente de {concepto.nombre}: disponible {concepto.stock_actual}")

            monto_total = monto * item.cantidad
            items_procesados.append({
                "tipo": "concepto",
                "concepto_id": concepto.id,
                "codigo": concepto.codigo,
                "descripcion": concepto.nombre,
                "cantidad": item.cantidad,
                "monto_unitario": monto,
                "monto_total": monto_total,
                "afecto_igv": concepto.afecto_igv,
            })
            total_calculado += monto_total

            # Descontar stock
            if concepto.maneja_stock:
                concepto.stock_actual -= item.cantidad

        else:
            # Item libre (descripción + monto)
            if item.monto_total <= 0:
                raise HTTPException(400, detail="Item sin monto")
            items_procesados.append({
                "tipo": "libre",
                "descripcion": item.descripcion or "Otros",
                "cantidad": item.cantidad,
                "monto_total": item.monto_total,
            })
            total_calculado += item.monto_total

    if not items_procesados:
        raise HTTPException(400, detail="No hay items para cobrar")

    # Verificar total
    if abs(total_calculado - cobro.total) > 0.02:
        raise HTTPException(400,
            detail=f"Total no coincide: calculado={total_calculado:.2f}, enviado={cobro.total:.2f}")

    # ── CREAR PAYMENT ──
    # Construir descripción
    descripciones = [i["descripcion"] for i in items_procesados]
    descripcion_pago = "; ".join(descripciones[:5])
    if len(descripciones) > 5:
        descripcion_pago += f" (+{len(descripciones) - 5} más)"

    # Construir descripción con datos del colegiado para el comprobante
    descripcion_comprobante = descripcion_pago.upper()
    if colegiado:
        descripcion_comprobante += f"\n{colegiado.apellidos_nombres or ''}"
        descripcion_comprobante += f"\nDNI [{colegiado.dni or ''}] Cód. Matr. [{colegiado.codigo_matricula or ''}]"

    payment = Payment(
        organization_id=org.id,
        colegiado_id=cobro.colegiado_id,
        amount=Decimal(str(cobro.total)),
        payment_method=cobro.metodo_pago,
        operation_code=cobro.referencia_pago,
        notes=descripcion_pago,
        status="approved",           # Presencial = aprobado inmediatamente
        payment_date=ahora,
        validated_at=ahora,
        source="caja",               # Origen: caja presencial
    )

    # Datos del pagador (para facturas)
    if cobro.tipo_comprobante == "01" and cobro.cliente_ruc:
        payment.pagador_tipo = "empresa"
        payment.pagador_documento = cobro.cliente_ruc
        payment.pagador_nombre = cobro.cliente_razon_social
        if hasattr(payment, 'pagador_direccion'):
            payment.pagador_direccion = cobro.cliente_direccion

    db.add(payment)
    db.flush()

    # ── MARCAR DEUDAS COMO PAGADAS ──
    for deuda in deudas_a_pagar:
        deuda.status = "paid"
        deuda.paid_at = ahora
        if hasattr(deuda, 'payment_id'):
            deuda.payment_id = payment.id

    # ── GENERAR DEUDAS para conceptos que genera_deuda ──
    for item in items_procesados:
        if item["tipo"] == "concepto":
            concepto = db.query(ConceptoCobro).filter(
                ConceptoCobro.id == item["concepto_id"]
            ).first()
            if concepto and concepto.genera_deuda and cobro.colegiado_id:
                nueva_deuda = Debt(
                    organization_id=org.id,
                    colegiado_id=cobro.colegiado_id,
                    concept=concepto.nombre,
                    amount=Decimal(str(item["monto_total"])),
                    status="paid",
                    paid_at=ahora,
                )
                if hasattr(nueva_deuda, 'payment_id'):
                    nueva_deuda.payment_id = payment.id
                db.add(nueva_deuda)

    db.commit()

    # ── RESPUESTA ──
    return CobroResponse(
        success=True,
        mensaje=f"Cobro registrado: S/ {cobro.total:.2f} - {cobro.metodo_pago}",
        payment_id=payment.id,
        total=cobro.total,
    )


@router.get("/resumen-dia")
async def resumen_del_dia(
    db: Session = Depends(get_db),
):
    """
    Resumen de cobros del día para la pantalla de caja.
    Total cobrado, cantidad de operaciones, por método de pago.
    """
    ahora = datetime.now(PERU_TZ)
    inicio_dia = ahora.replace(hour=0, minute=0, second=0, microsecond=0)

    # Pagos del día
    pagos_dia = db.query(Payment).filter(
        Payment.status == "approved",
        Payment.payment_date >= inicio_dia,
        Payment.source == "caja",
    ).all()

    total = sum(float(p.amount or 0) for p in pagos_dia)
    cantidad = len(pagos_dia)

    # Por método
    por_metodo = {}
    for p in pagos_dia:
        metodo = p.payment_method or "efectivo"
        if metodo not in por_metodo:
            por_metodo[metodo] = {"cantidad": 0, "total": 0}
        por_metodo[metodo]["cantidad"] += 1
        por_metodo[metodo]["total"] += float(p.amount or 0)

    return {
        "fecha": ahora.strftime("%d/%m/%Y"),
        "total_cobrado": total,
        "cantidad_operaciones": cantidad,
        "por_metodo": por_metodo,
        "hora_actual": ahora.strftime("%H:%M"),
    }


@router.get("/ultimos-cobros")
async def ultimos_cobros(
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """Últimos cobros realizados en caja (para el historial)"""
    ahora = datetime.now(PERU_TZ)
    inicio_dia = ahora.replace(hour=0, minute=0, second=0, microsecond=0)

    pagos = db.query(Payment).filter(
        Payment.source == "caja",
        Payment.payment_date >= inicio_dia,
    ).order_by(Payment.payment_date.desc()).limit(limit).all()

    resultado = []
    for p in pagos:
        col = None
        if p.colegiado_id:
            col = db.query(Colegiado).filter(Colegiado.id == p.colegiado_id).first()

        resultado.append({
            "id": p.id,
            "hora": p.payment_date.strftime("%H:%M") if p.payment_date else "",
            "colegiado": col.apellidos_nombres if col else "Público general",
            "matricula": col.codigo_matricula if col else None,
            "concepto": p.notes or "",
            "monto": float(p.amount or 0),
            "metodo": p.payment_method or "efectivo",
            "referencia": p.operation_code,
            "status": p.status,
        })

    return resultado
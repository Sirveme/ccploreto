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

from app.routers.dashboard import get_current_member
from app.models import Member


templates = Jinja2Templates(directory="app/templates")
router = APIRouter(prefix="/api/caja", tags=["Caja"])

# Router para la página HTML (sin prefix)
page_router = APIRouter(tags=["Caja"])

@page_router.get("/caja")
async def pagina_caja(request: Request, member: Member = Depends(get_current_member)):
    return templates.TemplateResponse("pages/caja.html", {"request": request})


PERU_TZ = timezone(timedelta(hours=-5))


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

            saldo = float(deuda.balance or 0)

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
        notes=f"[CAJA] {descripcion_pago}",
        status="approved",
        reviewed_at=ahora,
    )

    # Datos del pagador (para facturas)
    if cobro.tipo_comprobante == "01" and cobro.cliente_ruc:
        payment.pagador_tipo = "empresa"
        payment.pagador_documento = cobro.cliente_ruc
        payment.pagador_nombre = cobro.cliente_razon_social

    db.add(payment)
    db.flush()

    # ── MARCAR DEUDAS COMO PAGADAS ──
    for deuda in deudas_a_pagar:
        deuda.status = "paid"
        deuda.balance = 0

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
                    balance=0,
                    status="paid",
                )
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
        Payment.created_at >= inicio_dia,
        Payment.notes.like("[CAJA]%"),
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
        Payment.notes.like("[CAJA]%"),
        Payment.created_at >= inicio_dia,
    ).order_by(Payment.created_at.desc()).limit(limit).all()

    resultado = []
    for p in pagos:
        col = None
        if p.colegiado_id:
            col = db.query(Colegiado).filter(Colegiado.id == p.colegiado_id).first()

        resultado.append({
            "id": p.id,
            "hora": p.created_at.strftime("%H:%M") if p.created_at else "",
            "colegiado": col.apellidos_nombres if col else "Público general",
            "matricula": col.codigo_matricula if col else None,
            "concepto": p.notes or "",
            "monto": float(p.amount or 0),
            "metodo": p.payment_method or "efectivo",
            "referencia": p.operation_code,
            "status": p.status,
        })

    return resultado


"""
Endpoints de Sesión de Caja: Apertura, Cierre, Cuadre, Egresos
AGREGAR al final de app/routers/caja.py

Estos endpoints gestionan el ciclo completo de una sesión de caja.
"""

# ============================================================
# SCHEMAS SESIÓN
# ============================================================

class AbrirCajaRequest(BaseModel):
    monto_apertura: float = 0
    centro_costo_id: int = 1

class CerrarCajaRequest(BaseModel):
    monto_cierre: float
    observaciones: Optional[str] = None

class EgresoRequest(BaseModel):
    monto: float
    concepto: str
    detalle: Optional[str] = None
    tipo: str = "gasto"   # gasto, devolucion, retiro_fondo

class SesionCajaResponse(BaseModel):
    id: int
    estado: str
    cajero: str
    centro_costo: str
    fecha: str
    monto_apertura: float
    total_cobros_efectivo: float = 0
    total_cobros_digital: float = 0
    total_egresos: float = 0
    cantidad_operaciones: int = 0
    total_esperado: float = 0
    monto_cierre: Optional[float] = None
    diferencia: Optional[float] = None
    hora_apertura: Optional[str] = None
    hora_cierre: Optional[str] = None


# ============================================================
# ABRIR CAJA
# ============================================================

@router.post("/abrir-caja")
async def abrir_caja(
    datos: AbrirCajaRequest,
    db: Session = Depends(get_db),
):
    """
    Abre una sesión de caja.
    Solo 1 caja abierta por centro de costo a la vez.
    """
    from app.models import SesionCaja, UsuarioAdmin, CentroCosto

    ahora = datetime.now(PERU_TZ)

    # Verificar que no hay caja abierta en ese centro
    caja_abierta = db.query(SesionCaja).filter(
        SesionCaja.centro_costo_id == datos.centro_costo_id,
        SesionCaja.estado == "abierta",
    ).first()

    if caja_abierta:
        cajero = db.query(UsuarioAdmin).filter(
            UsuarioAdmin.id == caja_abierta.usuario_admin_id
        ).first()
        raise HTTPException(400, detail={
            "error": f"Ya hay una caja abierta por {cajero.nombre_completo if cajero else 'otro usuario'}",
            "sesion_id": caja_abierta.id,
        })

    # Obtener centro de costo
    centro = db.query(CentroCosto).filter(
        CentroCosto.id == datos.centro_costo_id
    ).first()
    if not centro:
        raise HTTPException(404, detail="Centro de costo no encontrado")

    org = db.query(Organization).first()

    # TODO: obtener usuario_admin_id del usuario logueado
    # Por ahora usamos el primer admin
    usuario_admin = db.query(UsuarioAdmin).filter(
        UsuarioAdmin.organization_id == org.id,
        UsuarioAdmin.activo == True,
    ).first()

    sesion = SesionCaja(
        organization_id=org.id,
        centro_costo_id=datos.centro_costo_id,
        usuario_admin_id=usuario_admin.id if usuario_admin else 1,
        fecha=ahora,
        estado="abierta",
        monto_apertura=Decimal(str(datos.monto_apertura)),
        hora_apertura=ahora,
    )

    db.add(sesion)
    db.commit()
    db.refresh(sesion)

    return {
        "success": True,
        "mensaje": f"Caja abierta en {centro.nombre} con S/ {datos.monto_apertura:.2f}",
        "sesion_id": sesion.id,
    }


# ============================================================
# ESTADO DE CAJA ACTUAL
# ============================================================

@router.get("/sesion-actual")
async def sesion_actual(
    centro_costo_id: int = Query(1),
    db: Session = Depends(get_db),
):
    """
    Retorna la sesión de caja abierta del centro de costo.
    Si no hay caja abierta, retorna null.
    """
    from app.models import SesionCaja, UsuarioAdmin, CentroCosto, EgresoCaja

    sesion = db.query(SesionCaja).filter(
        SesionCaja.centro_costo_id == centro_costo_id,
        SesionCaja.estado == "abierta",
    ).first()

    if not sesion:
        return {"sesion": None, "caja_abierta": False}

    # Calcular totales en tiempo real
    ahora = datetime.now(PERU_TZ)

    # Cobros del día en esta sesión (pagos desde hora_apertura)
    pagos = db.query(Payment).filter(
        Payment.status == "approved",
        Payment.notes.like("[CAJA]%"),
        Payment.created_at >= sesion.hora_apertura,
    ).all()

    total_efectivo = sum(
        float(p.amount or 0) for p in pagos
        if p.payment_method in ("efectivo",)
    )
    total_digital = sum(
        float(p.amount or 0) for p in pagos
        if p.payment_method not in ("efectivo",)
    )
    cantidad = len(pagos)

    # Egresos
    total_egresos = float(
        db.query(func.coalesce(func.sum(EgresoCaja.monto), 0)).filter(
            EgresoCaja.sesion_caja_id == sesion.id
        ).scalar() or 0
    )

    # Total esperado en caja física = apertura + efectivo - egresos
    monto_apertura = float(sesion.monto_apertura or 0)
    total_esperado = monto_apertura + total_efectivo - total_egresos

    # Info del cajero
    cajero = db.query(UsuarioAdmin).filter(
        UsuarioAdmin.id == sesion.usuario_admin_id
    ).first()

    centro = db.query(CentroCosto).filter(
        CentroCosto.id == sesion.centro_costo_id
    ).first()

    return {
        "caja_abierta": True,
        "sesion": {
            "id": sesion.id,
            "estado": sesion.estado,
            "cajero": cajero.nombre_completo if cajero else "?",
            "centro_costo": centro.nombre if centro else "?",
            "fecha": sesion.fecha.strftime("%d/%m/%Y") if sesion.fecha else "",
            "hora_apertura": sesion.hora_apertura.strftime("%H:%M") if sesion.hora_apertura else "",
            "monto_apertura": monto_apertura,
            "total_cobros_efectivo": total_efectivo,
            "total_cobros_digital": total_digital,
            "total_egresos": total_egresos,
            "cantidad_operaciones": cantidad,
            "total_esperado": total_esperado,
            "total_general": total_efectivo + total_digital,
        }
    }


# ============================================================
# CERRAR / CUADRAR CAJA
# ============================================================

@router.post("/cerrar-caja/{sesion_id}")
async def cerrar_caja(
    sesion_id: int,
    datos: CerrarCajaRequest,
    db: Session = Depends(get_db),
):
    """
    Cierra una sesión de caja.
    El cajero declara cuánto dinero tiene físicamente.
    El sistema calcula la diferencia.
    """
    from app.models import SesionCaja, EgresoCaja

    ahora = datetime.now(PERU_TZ)

    sesion = db.query(SesionCaja).filter(
        SesionCaja.id == sesion_id,
        SesionCaja.estado == "abierta",
    ).first()

    if not sesion:
        raise HTTPException(404, detail="Sesión no encontrada o ya cerrada")

    # Calcular totales finales
    pagos = db.query(Payment).filter(
        Payment.status == "approved",
        Payment.notes.like("[CAJA]%"),
        Payment.created_at >= sesion.hora_apertura,
    ).all()

    total_efectivo = sum(
        float(p.amount or 0) for p in pagos
        if p.payment_method in ("efectivo",)
    )
    total_digital = sum(
        float(p.amount or 0) for p in pagos
        if p.payment_method not in ("efectivo",)
    )
    cantidad = len(pagos)

    total_egresos = float(
        db.query(func.coalesce(func.sum(EgresoCaja.monto), 0)).filter(
            EgresoCaja.sesion_caja_id == sesion.id
        ).scalar() or 0
    )

    monto_apertura = float(sesion.monto_apertura or 0)
    total_esperado = monto_apertura + total_efectivo - total_egresos
    diferencia = datos.monto_cierre - total_esperado

    # Actualizar sesión
    sesion.estado = "cerrada"
    sesion.total_cobros_efectivo = Decimal(str(total_efectivo))
    sesion.total_cobros_digital = Decimal(str(total_digital))
    sesion.total_egresos = Decimal(str(total_egresos))
    sesion.cantidad_operaciones = cantidad
    sesion.total_esperado = Decimal(str(total_esperado))
    sesion.monto_cierre = Decimal(str(datos.monto_cierre))
    sesion.diferencia = Decimal(str(diferencia))
    sesion.hora_cierre = ahora
    sesion.observaciones_cierre = datos.observaciones

    # Validar diferencia grande
    alerta = ""
    if abs(diferencia) > 50:
        if not datos.observaciones:
            raise HTTPException(400,
                detail="Diferencia mayor a S/ 50.00 — se requiere observación obligatoria")
        alerta = f" ⚠ Diferencia: S/ {diferencia:+.2f}"

    db.commit()

    return {
        "success": True,
        "mensaje": f"Caja cerrada.{alerta}",
        "resumen": {
            "monto_apertura": monto_apertura,
            "total_cobros_efectivo": total_efectivo,
            "total_cobros_digital": total_digital,
            "total_egresos": total_egresos,
            "cantidad_operaciones": cantidad,
            "total_esperado": total_esperado,
            "monto_cierre": datos.monto_cierre,
            "diferencia": diferencia,
        }
    }


# ============================================================
# REGISTRAR EGRESO
# ============================================================

@router.post("/egreso")
async def registrar_egreso(
    datos: EgresoRequest,
    centro_costo_id: int = Query(1),
    db: Session = Depends(get_db),
):
    """
    Registra un egreso de caja (gasto menor, devolución, retiro de fondo).
    Requiere caja abierta.
    """
    from app.models import SesionCaja, EgresoCaja

    # Verificar caja abierta
    sesion = db.query(SesionCaja).filter(
        SesionCaja.centro_costo_id == centro_costo_id,
        SesionCaja.estado == "abierta",
    ).first()

    if not sesion:
        raise HTTPException(400, detail="No hay caja abierta. Abra la caja primero.")

    if datos.monto <= 0:
        raise HTTPException(400, detail="Monto debe ser mayor a 0")

    org = db.query(Organization).first()

    egreso = EgresoCaja(
        sesion_caja_id=sesion.id,
        organization_id=org.id,
        monto=Decimal(str(datos.monto)),
        concepto=datos.concepto,
        detalle=datos.detalle,
        tipo=datos.tipo,
    )

    db.add(egreso)
    db.commit()

    return {
        "success": True,
        "mensaje": f"Egreso registrado: S/ {datos.monto:.2f} — {datos.concepto}",
        "egreso_id": egreso.id,
    }


# ============================================================
# HISTORIAL DE EGRESOS DE LA SESIÓN
# ============================================================

@router.get("/egresos/{sesion_id}")
async def listar_egresos(
    sesion_id: int,
    db: Session = Depends(get_db),
):
    """Lista los egresos de una sesión de caja"""
    from app.models import EgresoCaja

    egresos = db.query(EgresoCaja).filter(
        EgresoCaja.sesion_caja_id == sesion_id
    ).order_by(EgresoCaja.created_at.desc()).all()

    return [{
        "id": e.id,
        "monto": float(e.monto),
        "concepto": e.concepto,
        "detalle": e.detalle,
        "tipo": e.tipo,
        "hora": e.created_at.strftime("%H:%M") if e.created_at else "",
    } for e in egresos]


# ============================================================
# HISTORIAL DE SESIONES (para tesorero/admin)
# ============================================================

@router.get("/historial-sesiones")
async def historial_sesiones(
    centro_costo_id: Optional[int] = None,
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Historial de sesiones de caja. Para tesorero/admin."""
    from app.models import SesionCaja, UsuarioAdmin, CentroCosto

    query = db.query(SesionCaja)

    if centro_costo_id:
        query = query.filter(SesionCaja.centro_costo_id == centro_costo_id)

    sesiones = query.order_by(SesionCaja.fecha.desc()).limit(limit).all()

    resultado = []
    for s in sesiones:
        cajero = db.query(UsuarioAdmin).filter(UsuarioAdmin.id == s.usuario_admin_id).first()
        centro = db.query(CentroCosto).filter(CentroCosto.id == s.centro_costo_id).first()

        resultado.append({
            "id": s.id,
            "fecha": s.fecha.strftime("%d/%m/%Y") if s.fecha else "",
            "centro_costo": centro.nombre if centro else "?",
            "cajero": cajero.nombre_completo if cajero else "?",
            "estado": s.estado,
            "monto_apertura": float(s.monto_apertura or 0),
            "total_cobros": float(s.total_cobros_efectivo or 0) + float(s.total_cobros_digital or 0),
            "total_egresos": float(s.total_egresos or 0),
            "total_esperado": float(s.total_esperado or 0),
            "monto_cierre": float(s.monto_cierre) if s.monto_cierre is not None else None,
            "diferencia": float(s.diferencia) if s.diferencia is not None else None,
            "cantidad_operaciones": s.cantidad_operaciones or 0,
            "hora_apertura": s.hora_apertura.strftime("%H:%M") if s.hora_apertura else "",
            "hora_cierre": s.hora_cierre.strftime("%H:%M") if s.hora_cierre else "",
        })

    return resultado
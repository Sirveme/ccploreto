"""
Router: Finanzas
app/routers/finanzas.py

Endpoints para el dashboard de Finanzas.
Incluye: resumen, cajas, autorizaciones, fraccionamiento, config, reportes.
"""

from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models import Payment, Colegiado, Debt, Organization, Comprobante, SesionCaja

router = APIRouter(prefix="/api/finanzas", tags=["finanzas"])

TZ_PERU = timezone(timedelta(hours=-5))


# ═══════════════════════════════════════
# Helpers
# ═══════════════════════════════════════

def _org_id():
    """Placeholder: obtener org_id del contexto."""
    import os
    return int(os.getenv("DEFAULT_ORG_ID", "1"))


def _get_config(db: Session) -> dict:
    """Obtiene config financiera de la organización."""
    from app.services.politicas_financieras import CONFIG_DEFECTO
    org = db.query(Organization).filter(Organization.id == _org_id()).first()
    if org and hasattr(org, 'config_finanzas') and org.config_finanzas:
        # Merge con defaults para campos nuevos
        config = {**CONFIG_DEFECTO, **org.config_finanzas}
        return config
    return CONFIG_DEFECTO


# ═══════════════════════════════════════
# RESUMEN
# ═══════════════════════════════════════

@router.get("/resumen")
async def resumen_finanzas(db: Session = Depends(get_db)):
    """Dashboard principal: KPIs del día y mes."""
    from app.services.politicas_financieras import generar_resumen_financiero
    return generar_resumen_financiero(db, _org_id())


# ═══════════════════════════════════════
# CAJAS
# ═══════════════════════════════════════

@router.get("/cajas")
async def listar_cajas(db: Session = Depends(get_db)):
    """Estado de todas las cajas."""
    org = _org_id()
    hoy = datetime.now(TZ_PERU).date()

    sesiones = db.query(SesionCaja).filter(
        SesionCaja.organization_id == org,
    ).order_by(SesionCaja.created_at.desc()).limit(10).all()

    resultado = []
    for s in sesiones:
        fecha_sesion = s.fecha.date() if hasattr(s.fecha, 'date') else s.fecha
        es_hoy = fecha_sesion == hoy if fecha_sesion else False
        resultado.append({
            "id": s.id,
            "nombre": f"Caja #{s.id}",
            "estado": s.estado if (s.estado == "abierta" and es_hoy) else "cerrada",
            "cajera": s.cajero.nombres if s.cajero and hasattr(s.cajero, 'nombres') else f"Cajero #{s.usuario_admin_id}",
            "efectivo": float(s.total_cobros_efectivo or 0),
            "digital": float(s.total_cobros_digital or 0),
            "egresos": float(s.total_egresos or 0),
            "operaciones": s.cantidad_operaciones or 0,
            "apertura": s.hora_apertura.astimezone(TZ_PERU).strftime("%H:%M") if s.hora_apertura else None,
            "monto_apertura": float(s.monto_apertura or 0),
            "diferencia": float(s.diferencia or 0) if s.estado != "abierta" else None,
        })

    return {"cajas": resultado}


# ═══════════════════════════════════════
# AUTORIZACIONES
# ═══════════════════════════════════════

class SolicitudAutorizacion(BaseModel):
    tipo: str          # anulacion, gasto, adelanto, devolucion, fraccionamiento
    monto: float
    justificacion: str
    comprobante_id: Optional[int] = None
    payment_id: Optional[int] = None
    colegiado_id: Optional[int] = None
    documentos: list = []


@router.get("/autorizaciones")
async def listar_autorizaciones(
    estado: str = "pendiente",
    limit: int = 20,
    db: Session = Depends(get_db),
):
    """Lista solicitudes de autorización."""
    # TODO: Migrar a tabla solicitudes_autorizacion
    # Por ahora, devolver pagos en review como "autorizaciones pendientes"
    org = _org_id()

    if estado == "pendiente":
        pagos = db.query(Payment).filter(
            Payment.organization_id == org,
            Payment.status == "review",
        ).order_by(Payment.created_at.desc()).limit(limit).all()

        solicitudes = []
        for p in pagos:
            col = db.query(Colegiado).filter(Colegiado.id == p.colegiado_id).first()
            solicitudes.append({
                "id": p.id,
                "tipo": "pago",
                "monto": float(p.amount),
                "justificacion": f"Pago por {p.payment_method or 'N/D'} — {p.description or 'Sin detalle'}",
                "solicitante_nombre": col.apellidos_nombres if col else f"Colegiado #{p.colegiado_id}",
                "fecha": p.created_at.astimezone(TZ_PERU).strftime("%d/%m %H:%M") if p.created_at else "—",
                "requiere_doble_firma": float(p.amount) > _get_config(db).get("umbral_doble_firma", 1000),
            })

        return {"solicitudes": solicitudes}

    return {"solicitudes": []}


@router.post("/autorizaciones/{solicitud_id}/{accion}")
async def resolver_autorizacion(
    solicitud_id: int,
    accion: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Aprobar o rechazar una solicitud."""
    if accion not in ("aprobar", "rechazar"):
        raise HTTPException(400, "Acción debe ser 'aprobar' o 'rechazar'")

    body = await request.json()
    motivo = body.get("motivo", "")

    # TODO: Cuando exista tabla solicitudes_autorizacion, usar esa.
    # Por ahora, aprobar/rechazar pagos directamente.
    pago = db.query(Payment).filter(Payment.id == solicitud_id).first()
    if not pago:
        raise HTTPException(404, "Solicitud no encontrada")

    if accion == "aprobar":
        from app.services.aprobar_pago import aprobar_pago
        resultado = aprobar_pago(db, solicitud_id, aprobado_por="finanzas")
        return resultado
    else:
        pago.status = "rejected"
        pago.rejection_reason = motivo
        pago.reviewed_at = datetime.now(timezone.utc)
        pago.reviewed_by = "finanzas"
        db.commit()
        return {"success": True, "mensaje": "Solicitud rechazada"}


# ═══════════════════════════════════════
# FRACCIONAMIENTO
# ═══════════════════════════════════════

class FraccionamientoRequest(BaseModel):
    colegiado_id: int
    cuota_inicial: float
    num_cuotas: int
    notas: str = ""


@router.get("/fraccionamiento/simular")
async def simular_fraccion(
    colegiado_id: int,
    db: Session = Depends(get_db),
):
    """
    Calcula opciones de fraccionamiento para un colegiado.
    Muestra las alternativas disponibles según la política.
    """
    from app.services.politicas_financieras import simular_fraccionamiento

    deudas = db.query(func.coalesce(func.sum(Debt.balance), 0)).filter(
        Debt.colegiado_id == colegiado_id,
        Debt.status.in_(["pending", "partial"]),
    ).scalar()

    config = _get_config(db)
    resultado = simular_fraccionamiento(Decimal(str(deudas)), config)

    col = db.query(Colegiado).filter(Colegiado.id == colegiado_id).first()
    resultado["colegiado"] = {
        "id": colegiado_id,
        "nombre": col.apellidos_nombres if col else "—",
        "deuda_actual": float(deudas),
    }

    return resultado


@router.post("/fraccionamiento/crear")
async def crear_fraccionamiento(
    data: FraccionamientoRequest,
    db: Session = Depends(get_db),
):
    """
    Crea un fraccionamiento: valida, genera cuotas, reemplaza deuda original.
    """
    from app.services.politicas_financieras import (
        validar_fraccionamiento,
        SolicitudFraccionamiento,
    )

    col = db.query(Colegiado).filter(Colegiado.id == data.colegiado_id).first()
    if not col:
        raise HTTPException(404, "Colegiado no encontrado")

    deuda_total = db.query(func.coalesce(func.sum(Debt.balance), 0)).filter(
        Debt.colegiado_id == data.colegiado_id,
        Debt.status.in_(["pending", "partial"]),
    ).scalar()

    solicitud = SolicitudFraccionamiento(
        colegiado_id=data.colegiado_id,
        colegiado_nombre=col.apellidos_nombres or "—",
        deuda_total=Decimal(str(deuda_total)),
        cuota_inicial=Decimal(str(data.cuota_inicial)),
        num_cuotas=data.num_cuotas,
        notas=data.notas,
    )

    config = _get_config(db)
    resultado = validar_fraccionamiento(solicitud, config)

    if not resultado.valido:
        raise HTTPException(400, resultado.mensaje)

    # ── Ejecutar fraccionamiento ──

    # 1. Marcar deudas originales como "fraccionadas"
    deudas_originales = db.query(Debt).filter(
        Debt.colegiado_id == data.colegiado_id,
        Debt.status.in_(["pending", "partial"]),
    ).all()

    for d in deudas_originales:
        d.status = "fractioned"
        d.notes = f"Fraccionado el {datetime.now(TZ_PERU).strftime('%d/%m/%Y')}"

    # 2. Registrar pago de cuota inicial (si > 0)
    if resultado.cuota_inicial > 0:
        pago_inicial = Payment(
            organization_id=col.organization_id,
            colegiado_id=data.colegiado_id,
            amount=resultado.cuota_inicial,
            payment_method="Efectivo",
            description=f"Cuota inicial fraccionamiento",
            status="approved",
            reviewed_at=datetime.now(timezone.utc),
            reviewed_by="fraccionamiento",
        )
        db.add(pago_inicial)

    # 3. Crear nuevas deudas fraccionadas
    for cuota in resultado.cuotas:
        nueva_deuda = Debt(
            organization_id=col.organization_id,
            colegiado_id=data.colegiado_id,
            concept=cuota.concepto,
            amount=cuota.monto,
            balance=cuota.monto,
            due_date=cuota.fecha_vencimiento,
            status="pending",
            debt_type="fraccionamiento",
        )
        db.add(nueva_deuda)

    db.flush()

    # 4. Habilitar temporalmente (hasta primera cuota + gracia)
    from app.services.politicas_financieras import habilitar_por_fraccionamiento
    primera_cuota = resultado.cuotas[0].fecha_vencimiento if resultado.cuotas else None
    if primera_cuota:
        habilitar_por_fraccionamiento(db, data.colegiado_id, primera_cuota, config)

    db.commit()

    return {
        "success": True,
        "mensaje": resultado.mensaje,
        "cronograma": [
            {
                "numero": c.numero,
                "monto": float(c.monto),
                "vencimiento": c.fecha_vencimiento.strftime("%d/%m/%Y"),
            }
            for c in resultado.cuotas
        ],
        "cuota_inicial": float(resultado.cuota_inicial),
        "total": float(resultado.total_a_pagar),
    }


# ═══════════════════════════════════════
# CONFIGURACIÓN
# ═══════════════════════════════════════

@router.get("/config")
async def obtener_config(db: Session = Depends(get_db)):
    """Obtiene configuración financiera actual."""
    return _get_config(db)


@router.post("/config")
async def guardar_config(request: Request, db: Session = Depends(get_db)):
    """Guarda configuración financiera."""
    body = await request.json()
    org = db.query(Organization).filter(Organization.id == _org_id()).first()

    if not org:
        raise HTTPException(404, "Organización no encontrada")

    if hasattr(org, 'config_finanzas'):
        if org.config_finanzas:
            org.config_finanzas = {**org.config_finanzas, **body}
        else:
            org.config_finanzas = body
    else:
        # Si no existe el campo, podemos usar otro campo JSONB o crear tabla
        pass

    db.commit()
    return {"success": True, "mensaje": "Configuración actualizada"}


# ═══════════════════════════════════════
# REPORTES
# ═══════════════════════════════════════

@router.get("/reportes/{tipo}")
async def generar_reporte(
    tipo: str,
    desde: Optional[str] = None,
    hasta: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Genera reportes financieros."""
    org = _org_id()

    if tipo == "ingresos-diario":
        hoy = datetime.now(TZ_PERU).date()
        pagos = db.query(Payment).filter(
            Payment.organization_id == org,
            Payment.status == "approved",
            func.date(Payment.created_at) == hoy,
        ).order_by(Payment.created_at.desc()).all()

        return {
            "tipo": tipo,
            "fecha": hoy.strftime("%d/%m/%Y"),
            "total": sum(float(p.amount) for p in pagos),
            "operaciones": len(pagos),
            "detalle": [
                {
                    "hora": p.created_at.astimezone(TZ_PERU).strftime("%H:%M"),
                    "monto": float(p.amount),
                    "metodo": p.payment_method,
                    "colegiado_id": p.colegiado_id,
                }
                for p in pagos
            ],
        }

    if tipo == "morosidad":
        morosos = db.query(
            Colegiado.id,
            Colegiado.apellidos_nombres,
            Colegiado.condicion,
            func.sum(Debt.balance).label("deuda_total"),
            func.count(Debt.id).label("cuotas_pendientes"),
        ).join(Debt, Debt.colegiado_id == Colegiado.id).filter(
            Colegiado.organization_id == org,
            Debt.status.in_(["pending", "partial"]),
        ).group_by(
            Colegiado.id, Colegiado.apellidos_nombres, Colegiado.condicion,
        ).order_by(func.sum(Debt.balance).desc()).limit(100).all()

        return {
            "tipo": tipo,
            "total_morosos": len(morosos),
            "deuda_total": sum(float(m.deuda_total) for m in morosos),
            "detalle": [
                {
                    "id": m.id,
                    "nombre": m.apellidos_nombres,
                    "condicion": m.condicion,
                    "deuda": float(m.deuda_total),
                    "cuotas": m.cuotas_pendientes,
                }
                for m in morosos
            ],
        }

    return {"tipo": tipo, "mensaje": f"Reporte '{tipo}' próximamente"}


# ═══════════════════════════════════════
# WEBSOCKET
# ═══════════════════════════════════════

class FinanzasNotifier:
    """Maneja conexiones WebSocket para notificaciones en tiempo real."""

    def __init__(self):
        self.connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.connections.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.connections:
            self.connections.remove(ws)

    async def broadcast(self, event: str, data: dict):
        """Envía a todos los clientes conectados."""
        dead = []
        for ws in self.connections:
            try:
                await ws.send_json({"event": event, "data": data})
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


# Instancia global
notifier = FinanzasNotifier()


# Este endpoint se registra en main.py directamente (no con prefix del router)
# app.websocket("/ws/finanzas")(ws_finanzas)
async def ws_finanzas(websocket: WebSocket):
    await notifier.connect(websocket)
    try:
        while True:
            # Mantener conexión viva; el servidor envía eventos
            data = await websocket.receive_text()
            # Ping/pong
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        notifier.disconnect(websocket)
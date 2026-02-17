"""
Router: Conciliación de Pagos Digitales
app/routers/conciliacion.py

Endpoints:
  CONCILIACIÓN:
    GET  /resumen                    → Dashboard stats
    GET  /notificaciones             → Lista notificaciones bancarias
    POST /sincronizar                → Lee emails y procesa (manual)
    POST /manual                     → Conciliar manualmente
    POST /ignorar                    → Ignorar notificación

  VERIFICACIÓN TIEMPO REAL:
    POST /verificar-pago             → Busca match en tabla local (instantáneo)
    GET  /verificar-pago/status/{id} → Status de verificación de un pago

  CUENTAS RECEPTORAS (CRUD):
    GET    /cuentas                  → Listar
    POST   /cuentas                  → Crear
    PUT    /cuentas/{id}             → Modificar
    DELETE /cuentas/{id}             → Desactivar

  GMAIL OAuth2:
    GET  /gmail/autorizar            → Inicia OAuth2
    GET  /gmail/callback             → Callback OAuth2
    GET  /gmail/status               → Estado de conexión
"""

import os
import logging
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from app.database import get_db
from app.models import (
    NotificacionBancaria,
    CuentaReceptora,
    Payment,
)

logger = logging.getLogger(__name__)

TZ_PERU = timezone(timedelta(hours=-5))

router = APIRouter(prefix="/api/conciliacion", tags=["conciliacion"])


# ══════════════════════════════════════════════════════════
# SCHEMAS
# ══════════════════════════════════════════════════════════

class CuentaReceptoraCreate(BaseModel):
    nombre: str
    tipo: str                       # yape, plin, transferencia, deposito
    banco: str                      # scotiabank, interbank, bcp, bbva
    titular: Optional[str] = None
    numero_cuenta: Optional[str] = None
    telefono: Optional[str] = None
    email_remitente: Optional[str] = None
    email_destinatario: Optional[str] = None


class CuentaReceptoraUpdate(BaseModel):
    nombre: Optional[str] = None
    tipo: Optional[str] = None
    banco: Optional[str] = None
    titular: Optional[str] = None
    numero_cuenta: Optional[str] = None
    telefono: Optional[str] = None
    email_remitente: Optional[str] = None
    email_destinatario: Optional[str] = None
    activo: Optional[bool] = None


# ══════════════════════════════════════════════════════════
# HELPER: org_id (simplificado; adaptar a tu auth)
# ══════════════════════════════════════════════════════════

def _org_id(request: Request = None) -> int:
    """Obtener organization_id del contexto. TODO: adaptar a tu middleware."""
    return 1


# ══════════════════════════════════════════════════════════
# DASHBOARD / RESUMEN
# ══════════════════════════════════════════════════════════

@router.get("/resumen")
async def resumen_conciliacion(db: Session = Depends(get_db)):
    """Stats para el dashboard del tesorero."""
    org = _org_id()

    base = db.query(NotificacionBancaria).filter(
        NotificacionBancaria.organization_id == org,
    )
    total = base.count()
    conciliados = base.filter(NotificacionBancaria.estado == "conciliado").count()
    pendientes = base.filter(NotificacionBancaria.estado == "pendiente").count()
    sin_match = base.filter(NotificacionBancaria.estado == "sin_match").count()
    ignorados = base.filter(NotificacionBancaria.estado == "ignorado").count()

    # Pagos digitales sin verificar
    ya_conciliados = db.query(NotificacionBancaria.payment_id).filter(
        NotificacionBancaria.payment_id.isnot(None),
        NotificacionBancaria.estado == "conciliado",
    )
    pagos_digitales = db.query(Payment).filter(
        Payment.status == "approved",
        Payment.payment_method.in_(["yape", "plin", "transferencia"]),
    ).count()
    pagos_verificados = conciliados

    return {
        "notificaciones_total": total,
        "conciliados": conciliados,
        "pendientes": pendientes,
        "sin_match": sin_match,
        "ignorados": ignorados,
        "pagos_digitales_total": pagos_digitales,
        "pagos_verificados": pagos_verificados,
        "pagos_sin_verificar": max(0, pagos_digitales - pagos_verificados),
        "tasa_verificacion": round(
            pagos_verificados / pagos_digitales * 100, 1
        ) if pagos_digitales > 0 else 0,
    }


# ══════════════════════════════════════════════════════════
# NOTIFICACIONES
# ══════════════════════════════════════════════════════════

@router.get("/notificaciones")
async def listar_notificaciones(
    estado: Optional[str] = None,
    banco: Optional[str] = None,
    dias: int = Query(7, ge=1, le=90),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Lista notificaciones bancarias con filtros."""
    org = _org_id()
    query = db.query(NotificacionBancaria).filter(
        NotificacionBancaria.organization_id == org,
        NotificacionBancaria.created_at >= datetime.now(timezone.utc) - timedelta(days=dias),
    )
    if estado:
        query = query.filter(NotificacionBancaria.estado == estado)
    if banco:
        query = query.filter(NotificacionBancaria.banco == banco)

    total = query.count()
    notifs = query.order_by(
        NotificacionBancaria.fecha_operacion.desc()
    ).offset((page - 1) * limit).limit(limit).all()

    def _fmt(dt):
        if not dt:
            return ""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(TZ_PERU).strftime("%d/%m/%Y %H:%M")

    return {
        "notificaciones": [
            {
                "id": n.id,
                "banco": n.banco,
                "tipo": n.tipo_operacion,
                "monto": float(n.monto),
                "fecha_operacion": _fmt(n.fecha_operacion),
                "codigo_operacion": n.codigo_operacion,
                "remitente": n.remitente_nombre,
                "destino": n.destino_tipo,
                "estado": n.estado,
                "payment_id": n.payment_id,
                "conciliado_por": n.conciliado_por,
            }
            for n in notifs
        ],
        "total": total,
        "page": page,
        "pages": (total + limit - 1) // limit,
    }


# ══════════════════════════════════════════════════════════
# SINCRONIZAR (manual — leer Gmail y guardar en tabla)
# ══════════════════════════════════════════════════════════

@router.post("/sincronizar")
async def sincronizar_emails(
    horas: int = Query(24, ge=1, le=168),
    db: Session = Depends(get_db),
):
    """
    Lee emails bancarios de Gmail y guarda en notificaciones_bancarias.
    Luego intenta auto-conciliar los que no tienen match.
    Manual por ahora; después será Celery task.
    """
    from app.services.imap_service import ImapService
    from app.services.conciliacion_service import ConciliacionService

    imap = ImapService()
    desde = datetime.now(TZ_PERU) - timedelta(hours=horas)
    emails = imap.leer_notificaciones_bancarias(desde=desde)

    if not emails:
        return {"message": "No se encontraron emails bancarios", "stats": {}}

    svc = ConciliacionService(db)
    stats = svc.procesar_emails(organization_id=_org_id(), emails=emails)

    return {"message": f"Procesados {len(emails)} emails", "stats": stats}


# ══════════════════════════════════════════════════════════
# CONCILIACIÓN MANUAL
# ══════════════════════════════════════════════════════════

@router.post("/manual")
async def conciliar_manual(
    notificacion_id: int,
    payment_id: int,
    db: Session = Depends(get_db),
):
    """Vincula manualmente una notificación con un pago."""
    notif = db.query(NotificacionBancaria).filter(
        NotificacionBancaria.id == notificacion_id,
    ).first()
    if not notif:
        raise HTTPException(404, detail="Notificación no encontrada")

    notif.payment_id = payment_id
    notif.estado = "conciliado"
    notif.conciliado_por = "manual"
    notif.conciliado_at = datetime.now(TZ_PERU)
    db.commit()

    return {"success": True, "message": "Conciliado manualmente"}


@router.post("/ignorar")
async def ignorar_notificacion(
    notificacion_id: int,
    observacion: str = "",
    db: Session = Depends(get_db),
):
    """Marca una notificación como ignorada."""
    notif = db.query(NotificacionBancaria).filter(
        NotificacionBancaria.id == notificacion_id,
    ).first()
    if not notif:
        raise HTTPException(404, detail="Notificación no encontrada")

    notif.estado = "ignorado"
    notif.observaciones = observacion
    db.commit()

    return {"success": True, "message": "Notificación ignorada"}


# ══════════════════════════════════════════════════════════
# VERIFICACIÓN EN TIEMPO REAL (busca SOLO en tabla local)
# ══════════════════════════════════════════════════════════

@router.post("/verificar-pago")
async def verificar_pago(
    monto: float,
    metodo: str,
    payment_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """
    Verifica si existe una notificación bancaria que coincida.
    Busca SOLO en la tabla local (alimentada por Celery/sincronización).
    NO llama a Gmail — eso lo hace el worker en background.

    Criterios de match:
    - Mismo monto exacto
    - Últimos 15 minutos
    - No conciliada previamente con otro pago
    """
    org = _org_id()
    ahora_utc = datetime.now(timezone.utc)
    ventana = ahora_utc - timedelta(minutes=15)
    monto_dec = Decimal(str(round(monto, 2)))

    # Buscar notificación que coincida en monto y tiempo
    notif = db.query(NotificacionBancaria).filter(
        NotificacionBancaria.organization_id == org,
        NotificacionBancaria.monto == monto_dec,
        NotificacionBancaria.estado.in_(["pendiente", "sin_match"]),
        or_(
            # Por fecha de operación (parseada del email)
            and_(
                NotificacionBancaria.fecha_operacion.isnot(None),
                NotificacionBancaria.fecha_operacion >= ventana,
            ),
            # O por fecha de creación en nuestra tabla (si no se parseó fecha)
            NotificacionBancaria.created_at >= ventana,
        ),
    ).order_by(NotificacionBancaria.created_at.desc()).first()

    if notif:
        # Match encontrado → conciliar notificación
        if payment_id:
            notif.payment_id = payment_id
            notif.estado = "conciliado"
            notif.conciliado_por = "auto_realtime"
            notif.conciliado_at = datetime.now(TZ_PERU)

            # AUTO-APPROVE: Si el pago está en review, aprobarlo
            from app.services.aprobar_pago import aprobar_pago
            pago = db.query(Payment).filter(Payment.id == payment_id).first()
            aprobacion = {}
            if pago and pago.status in ("review", "pending"):
                aprobacion = aprobar_pago(
                    db=db,
                    payment_id=payment_id,
                    aprobado_por="auto_realtime"
                )
            else:
                db.commit()

        return {
            "verificado": True,
            "notificacion_id": notif.id,
            "banco": notif.banco,
            "codigo_operacion": notif.codigo_operacion,
            "remitente": notif.remitente_nombre,
            "fecha": notif.fecha_operacion.astimezone(TZ_PERU).strftime("%H:%M:%S") if notif.fecha_operacion else None,
            "message": f"✅ Pago verificado — {(notif.banco or '').upper()} {('#' + notif.codigo_operacion) if notif.codigo_operacion else ''}",
            "auto_aprobado": aprobacion.get("success", False) if payment_id else False,
            "certificado": aprobacion.get("certificado"),
            "cambio_habilidad": aprobacion.get("cambio_habilidad", False),
        }

    # No encontrado aún
    return {
        "verificado": False,
        "message": "⏳ Aún no se detecta la notificación bancaria.",
    }


@router.get("/verificar-pago/status/{payment_id}")
async def status_verificacion(payment_id: int, db: Session = Depends(get_db)):
    """Consulta si un pago específico ya fue verificado."""
    notif = db.query(NotificacionBancaria).filter(
        NotificacionBancaria.payment_id == payment_id,
        NotificacionBancaria.estado == "conciliado",
    ).first()

    if notif:
        return {
            "verificado": True,
            "banco": notif.banco,
            "codigo_operacion": notif.codigo_operacion,
            "conciliado_por": notif.conciliado_por,
            "fecha_verificacion": notif.conciliado_at.strftime("%d/%m/%Y %H:%M") if notif.conciliado_at else None,
        }

    return {"verificado": False}


# ══════════════════════════════════════════════════════════
# PAGOS SIN VERIFICAR
# ══════════════════════════════════════════════════════════

@router.get("/pagos-sin-verificar")
async def pagos_sin_verificar(
    dias: int = Query(7, ge=1, le=90),
    db: Session = Depends(get_db),
):
    """Lista pagos digitales sin notificación bancaria asociada."""
    fecha_desde = datetime.now(timezone.utc) - timedelta(days=dias)

    ya_conciliados = db.query(NotificacionBancaria.payment_id).filter(
        NotificacionBancaria.payment_id.isnot(None),
    ).subquery()

    pagos = db.query(Payment).filter(
        Payment.status == "approved",
        Payment.payment_method.in_(["yape", "plin", "transferencia"]),
        Payment.created_at >= fecha_desde,
        ~Payment.id.in_(ya_conciliados),
    ).order_by(Payment.created_at.desc()).all()

    def _fmt(dt):
        if not dt:
            return ""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(TZ_PERU).strftime("%d/%m/%Y %H:%M")

    return {
        "pagos": [
            {
                "id": p.id,
                "monto": float(p.amount or 0),
                "metodo": p.payment_method,
                "fecha": _fmt(p.created_at),
                "notas": (p.notes or "")[:80],
            }
            for p in pagos
        ],
        "total": len(pagos),
    }


# ══════════════════════════════════════════════════════════
# CRUD: CUENTAS RECEPTORAS
# ══════════════════════════════════════════════════════════

@router.get("/cuentas")
async def listar_cuentas(
    activo: Optional[bool] = None,
    db: Session = Depends(get_db),
):
    """Lista cuentas receptoras de la organización."""
    org = _org_id()
    query = db.query(CuentaReceptora).filter(CuentaReceptora.organization_id == org)
    if activo is not None:
        query = query.filter(CuentaReceptora.activo == activo)

    cuentas = query.order_by(CuentaReceptora.nombre).all()

    return {
        "cuentas": [
            {
                "id": c.id,
                "nombre": c.nombre,
                "tipo": c.tipo,
                "banco": c.banco,
                "titular": c.titular,
                "numero_cuenta": c.numero_cuenta,
                "telefono": c.telefono,
                "email_remitente": c.email_remitente,
                "email_destinatario": c.email_destinatario,
                "activo": c.activo,
            }
            for c in cuentas
        ]
    }


@router.post("/cuentas")
async def crear_cuenta(datos: CuentaReceptoraCreate, db: Session = Depends(get_db)):
    """Crea nueva cuenta receptora."""
    cuenta = CuentaReceptora(
        organization_id=_org_id(),
        nombre=datos.nombre,
        tipo=datos.tipo,
        banco=datos.banco,
        titular=datos.titular,
        numero_cuenta=datos.numero_cuenta,
        telefono=datos.telefono,
        email_remitente=datos.email_remitente,
        email_destinatario=datos.email_destinatario,
    )
    db.add(cuenta)
    db.commit()
    db.refresh(cuenta)
    return {"success": True, "id": cuenta.id, "message": f"Cuenta '{datos.nombre}' creada"}


@router.put("/cuentas/{cuenta_id}")
async def actualizar_cuenta(
    cuenta_id: int,
    datos: CuentaReceptoraUpdate,
    db: Session = Depends(get_db),
):
    """Actualiza cuenta receptora."""
    org = _org_id()
    cuenta = db.query(CuentaReceptora).filter(
        CuentaReceptora.id == cuenta_id,
        CuentaReceptora.organization_id == org,
    ).first()
    if not cuenta:
        raise HTTPException(404, detail="Cuenta no encontrada")

    for campo, valor in datos.dict(exclude_unset=True).items():
        setattr(cuenta, campo, valor)
    db.commit()
    return {"success": True, "message": f"Cuenta '{cuenta.nombre}' actualizada"}


@router.delete("/cuentas/{cuenta_id}")
async def desactivar_cuenta(cuenta_id: int, db: Session = Depends(get_db)):
    """Desactiva cuenta (no elimina, mantiene historial)."""
    org = _org_id()
    cuenta = db.query(CuentaReceptora).filter(
        CuentaReceptora.id == cuenta_id,
        CuentaReceptora.organization_id == org,
    ).first()
    if not cuenta:
        raise HTTPException(404, detail="Cuenta no encontrada")

    cuenta.activo = False
    db.commit()
    return {"success": True, "message": f"Cuenta '{cuenta.nombre}' desactivada"}




@router.get("/email/status")
async def email_status():
    """Estado de conexión del email."""
    from app.services.imap_service import ImapService

    imap = ImapService()
    configurado = bool(imap.user and imap.password)

    if not configurado:
        return {
            "configurado": False,
            "conectado": False,
            "mensaje": "Email no configurado. Agregar IMAP_SERVER, IMAP_USER, IMAP_PASSWORD.",
        }

    resultado = imap.probar_conexion()

    return {
        "configurado": True,
        "conectado": resultado["success"],
        "servidor": imap.server,
        "usuario": imap.user,
        "mensaje": resultado["message"],
    }


@router.post("/email/probar")
async def probar_email(
    server: str,
    port: int = 993,
    user: str = "",
    password: str = "",
):
    """Prueba conexión IMAP con credenciales dadas (sin guardar)."""
    from app.services.imap_service import ImapService

    imap = ImapService(server=server, port=port, user=user, password=password)
    resultado = imap.probar_conexion()
    return resultado


@router.post("/email/configurar")
async def configurar_email(
    server: str,
    user: str,
    password: str,
    port: int = 993,
    db: Session = Depends(get_db),
):
    """
    Guarda configuración IMAP para la organización.
    Primero prueba la conexión; si falla, no guarda.
    """
    from app.services.imap_service import ImapService

    # Probar primero
    imap = ImapService(server=server, port=port, user=user, password=password)
    resultado = imap.probar_conexion()

    if not resultado["success"]:
        raise HTTPException(400, detail=f"No se pudo conectar: {resultado['message']}")

    # Guardar en BD (tabla config_email_sync o en organization.email_config)
    # Por ahora guardar en variables de entorno del proceso
    # TODO: Implementar persistencia en BD con encriptación Fernet
    import os
    os.environ["IMAP_SERVER"] = server
    os.environ["IMAP_PORT"] = str(port)
    os.environ["IMAP_USER"] = user
    os.environ["IMAP_PASSWORD"] = password

    return {
        "success": True,
        "message": f"Email configurado: {user}@{server}",
        "total_emails": resultado.get("total_emails", 0),
    }
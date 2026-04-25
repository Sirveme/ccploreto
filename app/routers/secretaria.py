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
from typing import Optional, List, Dict
from decimal import Decimal
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Body, UploadFile, File
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import or_, func
from pydantic import BaseModel, Field

from app.database import get_db
from app.models import (
    Colegiado, Payment, Member, Organization, ConfiguracionFacturacion,
    Comprobante,
)
from app.models_debt_management import Debt, Fraccionamiento, FraccionamientoCuota
from app.models_audit_finanzas import log_audit_finanzas, AuditLogFinanzas
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
        "user_role": current_member.role,
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
    extras_2026 = []  # deudas del año 2026 que NO encajan en uno de los 12 slots mensuales

    import re as _re_periodo
    _RX_YYYY_MM = _re_periodo.compile(r"^(\d{4})-(\d{2})$")
    _RX_YYYY_PREFIX = _re_periodo.compile(r"^(\d{4})")

    def _anio_de_deuda(d) -> Optional[str]:
        """Extrae el año (YYYY) de una deuda usando periodo, due_date, fecha_generacion o created_at."""
        per = str(d.periodo or "")
        m = _RX_YYYY_PREFIX.match(per)
        if m:
            return m.group(1)
        for f in (d.due_date, d.fecha_generacion, d.created_at):
            if f:
                return str(f.year)
        return None

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
        m = _RX_YYYY_MM.match(periodo)
        if m and m.group(1) == "2026":
            anio_2026[periodo] = item
            continue

        anio = _anio_de_deuda(d)
        if anio == "2026":
            extras_2026.append(item)
        else:
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
        "extras_2026": extras_2026,
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
    # Incluir IDs de deudas en notes para reconstruir en facturación
    ids_deudas = [str(d.id) for d in deudas]
    ids_str = ",".join(ids_deudas)
    nota_payment += f" [DEBT_IDS:{ids_str}]"

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
            "base_legal_referencia": p.base_legal_referencia,
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


# ============================================================
# HISTORIAL DE PAGOS + REVERTIR PAGO SIN COMPROBANTE
# ============================================================

import re as _re_pagos

_DEBT_IDS_RE = _re_pagos.compile(r"\[DEBT_IDS:([\d,]+)\]")


def _debt_ids_from_notes(notes: Optional[str]) -> List[int]:
    if not notes:
        return []
    m = _DEBT_IDS_RE.search(notes)
    if not m:
        return []
    return [int(x) for x in m.group(1).split(",") if x.strip().isdigit()]


@router.get("/pagos/{colegiado_id}")
async def listar_pagos_colegiado(
    colegiado_id: int,
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_secretaria),
):
    """Historial de pagos del colegiado con flag tiene_comprobante."""
    colegiado = db.query(Colegiado).filter(Colegiado.id == colegiado_id).first()
    if not colegiado:
        raise HTTPException(404, detail="Colegiado no encontrado")

    pagos = (
        db.query(Payment)
        .filter(Payment.colegiado_id == colegiado_id)
        .order_by(Payment.created_at.desc())
        .limit(200)
        .all()
    )

    pagos_ids = [p.id for p in pagos]
    comps_por_pago = {}
    if pagos_ids:
        comps = db.query(Comprobante).filter(
            Comprobante.payment_id.in_(pagos_ids),
            Comprobante.tipo.in_(["01", "03"]),
        ).all()
        for c in comps:
            comps_por_pago[c.payment_id] = {
                "id": c.id,
                "serie": c.serie,
                "numero": c.numero,
                "numero_formato": f"{c.serie}-{str(c.numero).zfill(8)}",
                "tipo": c.tipo,
                "status": c.status,
            }

    return {
        "pagos": [
            {
                "id": p.id,
                "monto": float(p.amount or 0),
                "metodo_pago": p.payment_method,
                "operation_code": p.operation_code,
                "fecha": p.created_at.replace(tzinfo=timezone.utc).astimezone(PERU_TZ).strftime("%d/%m/%Y %H:%M") if p.created_at else "",
                "status": p.status,
                "notes": p.notes,
                "comprobante": comps_por_pago.get(p.id),
                "tiene_comprobante": p.id in comps_por_pago,
            }
            for p in pagos
        ]
    }


@router.post("/pagos/{pago_id}/revertir")
async def revertir_pago(
    pago_id: int,
    body: dict = Body(...),
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_secretaria),
):
    """Revierte un pago sin comprobante SUNAT: deudas vuelven a pendiente."""
    pago = db.query(Payment).filter(Payment.id == pago_id).first()
    if not pago:
        raise HTTPException(status_code=404, detail="Pago no encontrado")

    if pago.status == "reverted":
        raise HTTPException(status_code=400, detail="Este pago ya fue revertido")

    comp = db.query(Comprobante).filter(
        Comprobante.payment_id == pago_id,
        Comprobante.tipo.in_(["01", "03"]),
    ).first()
    if comp:
        raise HTTPException(
            status_code=400,
            detail="Este pago tiene comprobante SUNAT. Use Anular desde /caja."
        )

    motivo = (body.get("motivo") or "").strip()
    if not motivo:
        raise HTTPException(status_code=400, detail="Debe indicar el motivo")

    operador_dni = ""
    if current_member and current_member.user:
        operador_dni = getattr(current_member.user, "public_id", "") or ""
    ahora = datetime.now(PERU_TZ)

    deuda_ids = _debt_ids_from_notes(pago.notes)
    if not deuda_ids and pago.related_debt_id:
        deuda_ids = [pago.related_debt_id]

    deudas_revertidas: List[int] = []
    if deuda_ids:
        deudas = db.query(Debt).filter(Debt.id.in_(deuda_ids)).all()
        for d in deudas:
            d.status = "pending"
            d.balance = d.amount
            d.notes = (d.notes or "") + (
                f"\n[SECRETARIA:{operador_dni}] Pago #{pago.id} revertido "
                f"{ahora.strftime('%d/%m/%Y %H:%M')} — {motivo}"
            )
            deudas_revertidas.append(d.id)

    pago.status = "reverted"
    pago.notes = (pago.notes or "") + (
        f" | REVERTIDO {ahora.strftime('%d/%m/%Y %H:%M')} por DNI:{operador_dni}: {motivo}"
    )

    await log_audit_finanzas(
        db,
        organization_id=pago.organization_id,
        accion="revertir_pago",
        entidad_tipo="payments",
        entidad_id=pago.id,
        current_user=current_member,
        cambios={
            "status": {"antes": "approved", "despues": "reverted"},
            "deudas_revertidas": deudas_revertidas,
        },
        motivo=motivo,
        colegiado_id=pago.colegiado_id,
        monto=float(pago.amount or 0),
    )

    db.commit()

    # Reevaluar condición del colegiado
    colegiado = db.query(Colegiado).filter(Colegiado.id == pago.colegiado_id).first()
    if colegiado:
        sincronizar_condicion(db, colegiado, {})
        db.commit()

    return {
        "ok": True,
        "mensaje": f"Pago #{pago.id} revertido. {len(deudas_revertidas)} deuda(s) vueltas a pendiente.",
        "deudas_revertidas": deudas_revertidas,
    }


# ═══════════════════════════════════════════════════════════════
# IMPORTADOR CSV MASIVO DE CORRECCIONES (zClaude-43)
# ═══════════════════════════════════════════════════════════════

import csv as _csv
import io as _io
import re as _re

_TIPO_MANUAL = {"quitar_concepto", "modificar_concepto", "revertir_pago"}
_TIPOS_NO_EJECUTABLES = _TIPO_MANUAL | {"no_soportado"}


def _normalizar_tipo_operacion(raw: str) -> str:
    t = (raw or "").strip().upper()
    if not t:
        return "no_soportado"
    # Fraccionamiento primero (puede contener palabra "AGREGAR")
    if "FRACC" in t:
        return "agregar_fraccionamiento"
    if "REVERTIR" in t:
        return "revertir_pago"
    if "MODIFICAR MONTO" in t or "MODIFICAR PAGO" in t or t == "MODIFICAR":
        return "modificar_monto"
    if "MODIFICAR CONCEPTO" in t:
        return "modificar_concepto"
    if "QUITAR" in t or "BORRAR" in t:
        return "quitar_concepto"
    if "SUSPENDIDO" in t or "INACTIVO" in t or "SUSPENDER" in t or "INACTIVAR" in t:
        return "cambiar_estado"
    if "MULTA" in t or "AGREGAR DEUDA" in t or "FALTA AGREGAR" in t or "AGREGAR" in t:
        return "agregar_deuda"
    return "no_soportado"


def _parsear_monto(raw: str):
    if not raw:
        return None
    s = raw.replace("S/", "").replace("s/", "").strip()
    # "1.234,56" → "1234.56"
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    s = s.replace(" ", "")
    try:
        return round(float(s), 2)
    except (ValueError, TypeError):
        return None


def _parsear_fecha_es(raw: str):
    """Acepta dd/mm/yyyy o d/m/yyyy o yyyy-mm-dd. None si falla."""
    if not raw:
        return None
    raw = raw.strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _parsear_cuotas_de_descripcion(descripcion: str, fallback_total):
    """
    Extrae '5 cuotas de 100 y 1 cuota de 80' → [100,100,100,100,100,80].
    Si no se puede → devuelve fallback (una sola cuota con fallback_total).
    """
    cuotas = []
    if descripcion:
        for m in _re.finditer(
            r"(\d+)\s+cuotas?\s+de\s+([\d\.,]+)",
            descripcion,
            flags=_re.IGNORECASE,
        ):
            cantidad = int(m.group(1))
            valor = _parsear_monto(m.group(2))
            if valor is not None:
                cuotas.extend([valor] * cantidad)
    if not cuotas and fallback_total:
        cuotas = [float(fallback_total)]
    return cuotas


@page_router.get("/secretaria/importar", response_class=HTMLResponse)
async def pagina_importar(
    request: Request,
    current_member: Member = Depends(require_secretaria),
):
    return templates.TemplateResponse("pages/secretaria_importar.html", {"request": request})


@router.post("/importar/parsear")
async def importar_parsear(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_secretaria),
):
    """
    Lee el CSV (sep ';', encoding utf-8 o latin-1) y retorna las operaciones
    detectadas sin ejecutar nada. Fila sin código en col 0 hereda del anterior.
    """
    contenido = await file.read()
    texto = None
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            texto = contenido.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if texto is None:
        return {"ok": False, "error": "No se pudo decodificar el archivo"}

    lector = _csv.reader(_io.StringIO(texto), delimiter=";")

    org = db.query(Organization).first()
    org_id = org.id if org else None

    operaciones = []
    codigo_actual = None
    cod_re = _re.compile(r"^\d{1,3}-\d+$")

    # Cache para evitar hitear N veces la BD con el mismo código
    cache_colegiado = {}

    for i, cols in enumerate(lector, start=1):
        # Limpiar columnas
        cols = [(c or "").strip() for c in cols]
        if not any(cols):
            continue

        raw_cod = cols[0] if cols else ""
        if cod_re.match(raw_cod):
            codigo_actual = raw_cod
        elif not codigo_actual:
            # Fila de comentario global al inicio — omitir
            continue

        tipo_raw = cols[1] if len(cols) > 1 else ""
        descripcion = cols[2] if len(cols) > 2 else ""
        monto_raw = cols[3] if len(cols) > 3 else ""
        fechas_raw = [c for c in cols[4:] if c]

        monto = _parsear_monto(monto_raw)
        tipo = _normalizar_tipo_operacion(tipo_raw)

        colegiado = cache_colegiado.get(codigo_actual)
        if colegiado is None and codigo_actual and org_id:
            colegiado = db.query(Colegiado).filter(
                Colegiado.codigo_matricula == codigo_actual,
                Colegiado.organization_id == org_id,
            ).first()
            cache_colegiado[codigo_actual] = colegiado

        operaciones.append({
            "fila": i,
            "codigo": codigo_actual,
            "colegiado_id": colegiado.id if colegiado else None,
            "colegiado_nombre": colegiado.apellidos_nombres if colegiado else None,
            "colegiado_encontrado": colegiado is not None,
            "tipo": tipo,
            "tipo_raw": tipo_raw,
            "descripcion": descripcion,
            "monto": monto,
            "monto_raw": monto_raw,
            "fechas": fechas_raw,
            "estado": "pendiente",
            "mensaje": None,
        })

    return {"ok": True, "total": len(operaciones), "operaciones": operaciones}


# ─────────── EJECUTORES POR TIPO ───────────

def _ejec_agregar_fraccionamiento(op: dict, db: Session, current_member: Member, org_id: int) -> dict:
    colegiado = db.query(Colegiado).filter(Colegiado.id == op["colegiado_id"]).first()
    if not colegiado:
        return {"estado": "error", "mensaje": "Colegiado no encontrado"}

    # Idempotencia: no reimportar la misma fila del mismo CSV.
    # Se marca con sufijo en numero_solicitud (FRACC-YYYY-NNNN-CSV-FILA-N).
    marca_fila = f"CSV-FILA-{op['fila']}"
    existe = db.query(Fraccionamiento).filter(
        Fraccionamiento.colegiado_id == colegiado.id,
        Fraccionamiento.numero_solicitud.ilike(f"%{marca_fila}%"),
    ).first()
    if existe:
        return {"estado": "error", "mensaje": f"Ya importado antes (fracc #{existe.id})"}

    cuotas_montos = _parsear_cuotas_de_descripcion(op["descripcion"], op["monto"])
    fechas = [_parsear_fecha_es(f) for f in op["fechas"]]
    fechas = [f for f in fechas if f is not None]

    if not cuotas_montos:
        return {"estado": "error", "mensaje": "No se pudo determinar cuotas"}
    if not fechas:
        return {"estado": "error", "mensaje": "No hay fechas de vencimiento válidas"}

    # Ajustar longitud — si hay más cuotas que fechas, extender fechas con +1 mes
    while len(fechas) < len(cuotas_montos):
        fechas.append(fechas[-1] + timedelta(days=30))
    cuotas_montos = cuotas_montos[:len(fechas)]
    fechas = fechas[:len(cuotas_montos)]

    total = round(sum(cuotas_montos), 2)
    cuota_ini = round(cuotas_montos[0], 2)
    saldo_fracc = round(total - cuota_ini, 2)

    ahora = datetime.now(PERU_TZ)
    anio = ahora.year
    # Número de solicitud único importado
    secuencia = db.query(Fraccionamiento).filter(
        Fraccionamiento.organization_id == org_id,
        Fraccionamiento.numero_solicitud.like(f"FRACC-{anio}-%"),
    ).count() + 1
    numero_solicitud = f"FRACC-{anio}-{str(secuencia).zfill(4)}-{marca_fila}"

    fracc = Fraccionamiento(
        organization_id=org_id,
        colegiado_id=colegiado.id,
        numero_solicitud=numero_solicitud,
        fecha_solicitud=ahora.date(),
        deuda_total_original=total,
        cuota_inicial=cuota_ini,
        cuota_inicial_pagada=False,
        saldo_a_fraccionar=saldo_fracc,
        num_cuotas=len(cuotas_montos),
        monto_cuota=round(cuotas_montos[1] if len(cuotas_montos) > 1 else cuota_ini, 2),
        cuotas_pagadas=0,
        cuotas_atrasadas=0,
        saldo_pendiente=total,
        fecha_inicio=fechas[0],
        fecha_fin_estimada=fechas[-1],
        proxima_cuota_fecha=fechas[0],
        proxima_cuota_numero=1,
        estado="activo",
        base_legal_referencia=f"CSV import fila {op['fila']}"[:100],
        created_by=current_member.user_id,
    )
    db.add(fracc)
    db.flush()

    for idx, (valor, fecha) in enumerate(zip(cuotas_montos, fechas), start=1):
        cuota = FraccionamientoCuota(
            fraccionamiento_id=fracc.id,
            numero_cuota=idx,
            monto=float(valor),
            fecha_vencimiento=fecha,
            pagada=False,
        )
        db.add(cuota)

    return {
        "estado": "ok",
        "mensaje": f"Fracc #{fracc.id} creado: {len(cuotas_montos)} cuotas, total S/ {total:.2f}",
    }


def _ejec_agregar_deuda(op: dict, db: Session, current_member: Member, org_id: int) -> dict:
    if not op["monto"] or op["monto"] <= 0:
        return {"estado": "error", "mensaje": "Monto inválido o vacío"}

    concept = (op["descripcion"] or "Deuda").strip()[:255]
    tipo_raw_upper = (op["tipo_raw"] or "").upper()
    debt_type = "multa" if "MULTA" in tipo_raw_upper else "otro"

    # Intentar detectar periodo YYYY-MM dentro de la descripción
    periodo = None
    m = _re.search(r"(20\d{2})[-/](\d{1,2})", op["descripcion"] or "")
    if m:
        periodo = f"{m.group(1)}-{int(m.group(2)):02d}"

    marca = f"[CSV-IMPORT fila {op['fila']}]"
    existe = db.query(Debt).filter(
        Debt.colegiado_id == op["colegiado_id"],
        Debt.notes.ilike(f"%{marca}%"),
    ).first()
    if existe:
        return {"estado": "error", "mensaje": f"Ya importada antes (deuda #{existe.id})"}

    nueva = Debt(
        organization_id=org_id,
        colegiado_id=op["colegiado_id"],
        concept=concept,
        amount=Decimal(str(op["monto"])),
        balance=Decimal(str(op["monto"])),
        status="pending",
        debt_type=debt_type,
        periodo=periodo,
        notes=f"{marca} {op['descripcion']}"[:500],
    )
    db.add(nueva)
    db.flush()
    return {"estado": "ok", "mensaje": f"Deuda #{nueva.id} creada S/ {float(op['monto']):.2f}"}


def _ejec_modificar_monto(op: dict, db: Session, current_member: Member, org_id: int) -> dict:
    if op["monto"] is None or op["monto"] < 0:
        return {"estado": "error", "mensaje": "Monto inválido"}

    # Estrategia conservadora: buscar la deuda pendiente más reciente que coincida
    # en periodo (si el descriptor lo incluye) o la más antigua pendiente.
    q = db.query(Debt).filter(
        Debt.colegiado_id == op["colegiado_id"],
        Debt.status.in_(["pending", "partial"]),
    )
    m = _re.search(r"(20\d{2})[-/](\d{1,2})", op["descripcion"] or "")
    if m:
        periodo = f"{m.group(1)}-{int(m.group(2)):02d}"
        q = q.filter(Debt.periodo == periodo)

    deuda = q.order_by(Debt.periodo.asc().nullslast(), Debt.id.asc()).first()
    if not deuda:
        return {"estado": "error", "mensaje": "No se encontró deuda pendiente para modificar"}

    monto_anterior = float(deuda.amount or 0)
    saldo_pagado = monto_anterior - float(deuda.balance or 0)
    nuevo = float(op["monto"])
    nuevo_balance = max(0.0, nuevo - saldo_pagado)

    deuda.amount = Decimal(str(nuevo))
    deuda.balance = Decimal(str(nuevo_balance))
    if nuevo_balance == 0 and saldo_pagado > 0:
        deuda.status = "paid"
    elif nuevo_balance > 0 and saldo_pagado > 0:
        deuda.status = "partial"
    deuda.notes = (deuda.notes or "") + (
        f"\n[CSV-IMPORT fila {op['fila']}] Monto: S/ {monto_anterior:.2f} → S/ {nuevo:.2f}"
    )
    return {
        "estado": "ok",
        "mensaje": f"Deuda #{deuda.id} monto {monto_anterior:.2f} → {nuevo:.2f}",
    }


def _ejec_cambiar_estado(op: dict, db: Session, current_member: Member, org_id: int) -> dict:
    colegiado = db.query(Colegiado).filter(Colegiado.id == op["colegiado_id"]).first()
    if not colegiado:
        return {"estado": "error", "mensaje": "Colegiado no encontrado"}

    t_upper = (op["tipo_raw"] or "").upper() + " " + (op["descripcion"] or "").upper()
    if "SUSPEND" in t_upper:
        nueva = "suspendido"
    elif "INACTIV" in t_upper:
        nueva = "inhabil"
    else:
        return {"estado": "error", "mensaje": "No se pudo inferir el estado destino"}

    anterior = colegiado.condicion
    if anterior == nueva:
        return {"estado": "ok", "mensaje": f"Ya estaba '{nueva}' — sin cambios"}

    colegiado.condicion = nueva
    if hasattr(colegiado, "fecha_actualizacion_condicion"):
        colegiado.fecha_actualizacion_condicion = datetime.now(PERU_TZ)
    if nueva != "habil":
        colegiado.habilidad_vence = None
        colegiado.motivo_inhabilidad = f"[CSV-IMPORT fila {op['fila']}] {op['descripcion']}"[:500]
    return {"estado": "ok", "mensaje": f"Condición: {anterior} → {nueva}"}


_EJECUTORES = {
    "agregar_fraccionamiento": _ejec_agregar_fraccionamiento,
    "agregar_deuda": _ejec_agregar_deuda,
    "modificar_monto": _ejec_modificar_monto,
    "cambiar_estado": _ejec_cambiar_estado,
}


@router.post("/importar/ejecutar")
async def importar_ejecutar(
    body: dict = Body(...),
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_secretaria),
):
    """
    Ejecuta las operaciones marcadas con ejecutar=True. Cada fila es
    atómica via savepoint: si falla, rollback solo de esa fila.
    """
    operaciones = body.get("operaciones") or []
    if not operaciones:
        return {"ok": False, "error": "Sin operaciones"}

    org = db.query(Organization).first()
    if not org:
        return {"ok": False, "error": "Sin organización configurada"}

    resultados = []
    for op in operaciones:
        if not op.get("ejecutar"):
            resultados.append({**op, "estado": "omitido", "mensaje": None})
            continue

        if op.get("tipo") in _TIPOS_NO_EJECUTABLES:
            resultados.append({
                **op, "estado": "error",
                "mensaje": "Requiere revisión manual — no se ejecuta automáticamente",
            })
            continue

        if not op.get("colegiado_id"):
            resultados.append({**op, "estado": "error",
                               "mensaje": f"Colegiado {op.get('codigo')} no encontrado"})
            continue

        ejecutor = _EJECUTORES.get(op["tipo"])
        if not ejecutor:
            resultados.append({**op, "estado": "error",
                               "mensaje": f"Tipo '{op['tipo']}' sin ejecutor"})
            continue

        sp = db.begin_nested()
        try:
            resultado = ejecutor(op, db, current_member, org.id)
            if resultado.get("estado") == "ok":
                sp.commit()
            else:
                sp.rollback()
            resultados.append({**op, **resultado})
        except Exception as e:
            sp.rollback()
            logger.exception("Error ejecutando fila CSV")
            resultados.append({**op, "estado": "error", "mensaje": str(e)[:200]})

    db.commit()

    resumen = {
        "ok": sum(1 for r in resultados if r["estado"] == "ok"),
        "error": sum(1 for r in resultados if r["estado"] == "error"),
        "omitido": sum(1 for r in resultados if r["estado"] == "omitido"),
    }
    return {"ok": True, "resumen": resumen, "resultados": resultados}


# ============================================================
# EDICIÓN DIRECTA DE DEUDAS (Admin/Cajero/Secretaria/Tesorero/Sote)
# ============================================================

# Mapa: campo del payload (español) → atributo del modelo Debt
_CAMPOS_EDITABLES_DEUDA = {
    "concepto":       ("concept",        str),
    "monto":          ("amount",         float),
    "periodo":        ("periodo",        str),
    "estado":         ("status",         str),
    "estado_gestion": ("estado_gestion", str),
    "tipo":           ("debt_type",      str),
    "notas":          ("notes",          str),
}

_ESTADOS_VALIDOS = {"pending", "partial", "paid"}
_ESTADOS_GESTION_VALIDOS = {
    "vigente", "en_cobranza", "fraccionada", "condonada", "exonerada",
    "compensada", "prescrita", "incobrable", "en_reclamo", "suspendida",
    "justificada",
}
_TIPOS_VALIDOS = {
    "cuota_ordinaria", "cuota_extraordinaria", "multa", "evento", "derecho", "otro",
}


@router.put("/deudas/{deuda_id}")
async def editar_deuda(
    deuda_id: int,
    body: dict = Body(...),
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_secretaria),
):
    """Edita una deuda y registra el cambio en audit_logs."""
    deuda = db.query(Debt).filter(Debt.id == deuda_id).first()
    if not deuda:
        raise HTTPException(status_code=404, detail="Deuda no encontrada")

    motivo = (body.get("motivo") or "").strip()
    if not motivo:
        raise HTTPException(status_code=400, detail="El motivo del cambio es obligatorio")

    # Validar valores de campos enumerados (si vienen)
    if "estado" in body and body["estado"]:
        if body["estado"] not in _ESTADOS_VALIDOS:
            raise HTTPException(400, detail=f"Estado inválido: {body['estado']}")
    if "estado_gestion" in body and body["estado_gestion"]:
        if body["estado_gestion"] not in _ESTADOS_GESTION_VALIDOS:
            raise HTTPException(400, detail=f"Estado de gestión inválido: {body['estado_gestion']}")
    if "tipo" in body and body["tipo"]:
        if body["tipo"] not in _TIPOS_VALIDOS:
            raise HTTPException(400, detail=f"Tipo inválido: {body['tipo']}")

    cambios = {}
    monto_anterior = float(deuda.amount or 0)
    saldo_pagado = monto_anterior - float(deuda.balance or 0)

    for campo_es, (attr, conv) in _CAMPOS_EDITABLES_DEUDA.items():
        if campo_es not in body or body[campo_es] is None:
            continue
        try:
            nuevo = conv(body[campo_es])
        except (TypeError, ValueError):
            raise HTTPException(400, detail=f"Valor inválido para {campo_es}")
        anterior = getattr(deuda, attr, None)
        anterior_norm = conv(anterior) if anterior is not None and conv is not str else (
            str(anterior) if anterior is not None else ""
        )
        if conv is str:
            anterior_cmp = str(anterior or "")
            nuevo_cmp = str(nuevo or "")
        else:
            anterior_cmp = anterior_norm
            nuevo_cmp = nuevo
        if anterior_cmp != nuevo_cmp:
            cambios[campo_es] = {
                "antes": str(anterior) if anterior is not None else "",
                "despues": str(nuevo),
            }
            setattr(deuda, attr, nuevo)

    if not cambios:
        return {"ok": True, "mensaje": "Sin cambios", "cambios": {}}

    # Recalcular balance si cambió el monto, preservando lo ya pagado
    if "monto" in cambios:
        nuevo_amount = float(deuda.amount or 0)
        # Si el nuevo estado es paid → balance = 0
        estado_actual = deuda.status or "pending"
        if estado_actual == "paid":
            nuevo_balance = 0.0
        else:
            nuevo_balance = max(0.0, nuevo_amount - max(0.0, saldo_pagado))
        deuda.balance = nuevo_balance
        cambios["balance"] = {
            "antes": f"{(monto_anterior - saldo_pagado):.2f}",
            "despues": f"{nuevo_balance:.2f}",
        }

    # Si pasa a paid sin tocar monto, balance = 0
    if "estado" in cambios and (deuda.status == "paid"):
        if float(deuda.balance or 0) != 0:
            deuda.balance = 0.0
            cambios.setdefault("balance", {"antes": "—", "despues": "0.00"})

    deuda.updated_by = current_member.user_id

    operador_dni = ""
    if current_member and current_member.user:
        operador_dni = getattr(current_member.user, "public_id", "") or ""
    ahora = datetime.now(PERU_TZ)
    nota_edicion = (
        f"\n[EDIT-SECRETARIA:{operador_dni}] {ahora.strftime('%d/%m/%Y %H:%M')} — "
        f"motivo: {motivo[:200]}"
    )
    deuda.notes = ((deuda.notes or "") + nota_edicion).strip()

    # Auditoría — log_audit_finanzas
    await log_audit_finanzas(
        db,
        organization_id=deuda.organization_id,
        accion="editar_deuda",
        entidad_tipo="debts",
        entidad_id=deuda_id,
        current_user=current_member,
        cambios=cambios,
        motivo=motivo,
        colegiado_id=deuda.colegiado_id,
        monto=float(deuda.amount or 0) if deuda.amount is not None else None,
    )

    db.commit()

    return {"ok": True, "mensaje": "Deuda actualizada", "cambios": cambios}


# ============================================================
# EDICIÓN DE PAGOS (zClaude-52)
# ============================================================

_CAMPOS_EDITABLES_PAGO = {
    "monto":         ("amount",         float),
    "metodo_pago":   ("payment_method", str),
    "operation_code": ("operation_code", str),
    "notes":         ("notes",          str),
    "status":        ("status",         str),
}

_PAYMENT_STATUS_VALIDOS = {"review", "approved", "rejected", "reverted"}
_METODOS_PAGO_VALIDOS = {
    "yape", "plin", "transferencia", "efectivo", "tarjeta", "deposito", "otro"
}


@router.put("/pagos/{pago_id}")
async def editar_pago(
    pago_id: int,
    body: dict = Body(...),
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_secretaria),
):
    """Edita campos editables de un pago y registra el cambio en audit_log_finanzas."""
    pago = db.query(Payment).filter(Payment.id == pago_id).first()
    if not pago:
        raise HTTPException(404, detail="Pago no encontrado")

    motivo = (body.get("motivo") or "").strip()
    if not motivo:
        raise HTTPException(400, detail="El motivo del cambio es obligatorio")

    # Validaciones
    if "status" in body and body["status"]:
        if body["status"] not in _PAYMENT_STATUS_VALIDOS:
            raise HTTPException(400, detail=f"Status inválido: {body['status']}")
    if "metodo_pago" in body and body["metodo_pago"]:
        if str(body["metodo_pago"]).lower() not in _METODOS_PAGO_VALIDOS:
            raise HTTPException(400, detail=f"Método de pago inválido: {body['metodo_pago']}")

    cambios: Dict[str, Dict[str, str]] = {}
    for campo_es, (attr, conv) in _CAMPOS_EDITABLES_PAGO.items():
        if campo_es not in body or body[campo_es] is None:
            continue
        try:
            nuevo = conv(body[campo_es])
        except (TypeError, ValueError):
            raise HTTPException(400, detail=f"Valor inválido para {campo_es}")
        anterior = getattr(pago, attr, None)
        if conv is str:
            anterior_cmp = str(anterior or "")
            nuevo_cmp = str(nuevo or "")
        else:
            anterior_cmp = conv(anterior) if anterior is not None else None
            nuevo_cmp = nuevo
        if anterior_cmp != nuevo_cmp:
            cambios[campo_es] = {
                "antes": str(anterior) if anterior is not None else "",
                "despues": str(nuevo),
            }
            setattr(pago, attr, nuevo)

    if not cambios:
        return {"ok": True, "mensaje": "Sin cambios", "cambios": {}}

    operador_dni = ""
    if current_member and current_member.user:
        operador_dni = getattr(current_member.user, "public_id", "") or ""
    ahora = datetime.now(PERU_TZ)
    pago.notes = ((pago.notes or "") + (
        f" | EDIT {ahora.strftime('%d/%m/%Y %H:%M')} por DNI:{operador_dni}: {motivo[:200]}"
    )).strip()

    await log_audit_finanzas(
        db,
        organization_id=pago.organization_id,
        accion="editar_pago",
        entidad_tipo="payments",
        entidad_id=pago.id,
        current_user=current_member,
        cambios=cambios,
        motivo=motivo,
        colegiado_id=pago.colegiado_id,
        monto=float(pago.amount or 0) if pago.amount is not None else None,
    )

    db.commit()
    return {"ok": True, "mensaje": "Pago actualizado", "cambios": cambios}


# ============================================================
# EDICIÓN DE FRACCIONAMIENTOS Y CUOTAS (zClaude-52)
# ============================================================

_CAMPOS_EDITABLES_FRACC = {
    "numero_solicitud":      ("numero_solicitud",      str),
    "saldo_pendiente":       ("saldo_pendiente",       float),
    "monto_cuota":           ("monto_cuota",           float),
    "num_cuotas":            ("num_cuotas",            int),
    "estado":                ("estado",                str),
    "fecha_inicio":          ("fecha_inicio",          str),  # parse abajo
    "fecha_fin_estimada":    ("fecha_fin_estimada",    str),  # parse abajo
    "base_legal_referencia": ("base_legal_referencia", str),
}

_FRACC_ESTADOS_VALIDOS = {"activo", "completado", "perdido", "refinanciado"}


def _parse_fecha_iso(valor: str):
    """Convierte 'YYYY-MM-DD' a date. Acepta None/vacío como None."""
    if not valor:
        return None
    try:
        return date.fromisoformat(str(valor)[:10])
    except (TypeError, ValueError):
        raise HTTPException(400, detail=f"Fecha inválida (formato YYYY-MM-DD): {valor}")


@router.put("/fraccionamientos/{fracc_id}")
async def editar_fraccionamiento(
    fracc_id: int,
    body: dict = Body(...),
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_secretaria),
):
    fracc = db.query(Fraccionamiento).filter(Fraccionamiento.id == fracc_id).first()
    if not fracc:
        raise HTTPException(404, detail="Fraccionamiento no encontrado")

    motivo = (body.get("motivo") or "").strip()
    if not motivo:
        raise HTTPException(400, detail="El motivo del cambio es obligatorio")

    if "estado" in body and body["estado"]:
        if body["estado"] not in _FRACC_ESTADOS_VALIDOS:
            raise HTTPException(400, detail=f"Estado inválido: {body['estado']}")

    cambios: Dict[str, Dict[str, str]] = {}
    for campo, (attr, conv) in _CAMPOS_EDITABLES_FRACC.items():
        if campo not in body or body[campo] is None:
            continue
        if attr in ("fecha_inicio", "fecha_fin_estimada"):
            nuevo = _parse_fecha_iso(body[campo])
        else:
            try:
                nuevo = conv(body[campo])
            except (TypeError, ValueError):
                raise HTTPException(400, detail=f"Valor inválido para {campo}")
        anterior = getattr(fracc, attr, None)
        if str(anterior or "") != str(nuevo or ""):
            cambios[campo] = {
                "antes": str(anterior) if anterior is not None else "",
                "despues": str(nuevo) if nuevo is not None else "",
            }
            setattr(fracc, attr, nuevo)

    if not cambios:
        return {"ok": True, "mensaje": "Sin cambios", "cambios": {}}

    await log_audit_finanzas(
        db,
        organization_id=fracc.organization_id,
        accion="editar_fraccionamiento",
        entidad_tipo="fraccionamientos",
        entidad_id=fracc.id,
        current_user=current_member,
        cambios=cambios,
        motivo=motivo,
        colegiado_id=fracc.colegiado_id,
        monto=float(fracc.saldo_pendiente or 0) if fracc.saldo_pendiente is not None else None,
    )

    db.commit()
    return {"ok": True, "mensaje": "Fraccionamiento actualizado", "cambios": cambios}


@router.put("/fraccionamientos/cuotas/{cuota_id}")
async def editar_cuota_fraccionamiento(
    cuota_id: int,
    body: dict = Body(...),
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_secretaria),
):
    cuota = db.query(FraccionamientoCuota).filter(FraccionamientoCuota.id == cuota_id).first()
    if not cuota:
        raise HTTPException(404, detail="Cuota no encontrada")

    motivo = (body.get("motivo") or "").strip()
    if not motivo:
        raise HTTPException(400, detail="El motivo del cambio es obligatorio")

    cambios: Dict[str, Dict[str, str]] = {}

    if "monto" in body and body["monto"] is not None:
        try:
            nuevo = float(body["monto"])
        except (TypeError, ValueError):
            raise HTTPException(400, detail="Monto inválido")
        if nuevo < 0:
            raise HTTPException(400, detail="Monto no puede ser negativo")
        if float(cuota.monto or 0) != nuevo:
            cambios["monto"] = {"antes": str(cuota.monto), "despues": str(nuevo)}
            cuota.monto = nuevo

    if "fecha_vencimiento" in body and body["fecha_vencimiento"] is not None:
        nueva = _parse_fecha_iso(body["fecha_vencimiento"])
        if (cuota.fecha_vencimiento or None) != nueva:
            cambios["fecha_vencimiento"] = {
                "antes": str(cuota.fecha_vencimiento) if cuota.fecha_vencimiento else "",
                "despues": str(nueva) if nueva else "",
            }
            cuota.fecha_vencimiento = nueva

    if "pagada" in body and body["pagada"] is not None:
        nuevo_bool = bool(body["pagada"])
        if bool(cuota.pagada) != nuevo_bool:
            cambios["pagada"] = {"antes": str(bool(cuota.pagada)), "despues": str(nuevo_bool)}
            cuota.pagada = nuevo_bool
            if nuevo_bool and not cuota.fecha_pago:
                cuota.fecha_pago = datetime.now(PERU_TZ).date()
            if not nuevo_bool:
                cuota.fecha_pago = None

    if not cambios:
        return {"ok": True, "mensaje": "Sin cambios", "cambios": {}}

    fracc = db.query(Fraccionamiento).filter(
        Fraccionamiento.id == cuota.fraccionamiento_id
    ).first()
    org_id = fracc.organization_id if fracc else None
    col_id = fracc.colegiado_id if fracc else None

    await log_audit_finanzas(
        db,
        organization_id=org_id,
        accion="editar_cuota_fraccionamiento",
        entidad_tipo="fraccionamiento_cuotas",
        entidad_id=cuota.id,
        current_user=current_member,
        cambios={**cambios, "fraccionamiento_id": cuota.fraccionamiento_id},
        motivo=motivo,
        colegiado_id=col_id,
        monto=float(cuota.monto or 0) if cuota.monto is not None else None,
    )

    db.commit()
    return {"ok": True, "mensaje": "Cuota actualizada", "cambios": cambios}


# ============================================================
# HISTORIAL DE AUDITORÍA POR COLEGIADO (zClaude-52)
# ============================================================

ROLES_AUDITORIA = ("admin", "sote")


def require_auditoria(current_member: Member = Depends(get_current_member)):
    if current_member.role not in ROLES_AUDITORIA:
        raise HTTPException(status_code=403, detail="Acceso restringido a admin/sote")
    return current_member


@router.get("/auditoria/{colegiado_id}")
async def historial_auditoria(
    colegiado_id: int,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_auditoria),
):
    """
    Devuelve los últimos N cambios financieros relacionados al colegiado.
    Cruza entidad_id con deudas/pagos/fraccionamientos/cuotas del colegiado y,
    como respaldo, también filtra por detalle->>colegiado_id.
    """
    colegiado = db.query(Colegiado).filter(Colegiado.id == colegiado_id).first()
    if not colegiado:
        raise HTTPException(404, detail="Colegiado no encontrado")

    # IDs por tabla — clave del filtro principal
    deuda_ids = [d.id for d in db.query(Debt.id).filter(Debt.colegiado_id == colegiado_id).all()]
    pago_ids = [p.id for p in db.query(Payment.id).filter(Payment.colegiado_id == colegiado_id).all()]
    fracc_ids = [f.id for f in db.query(Fraccionamiento.id).filter(Fraccionamiento.colegiado_id == colegiado_id).all()]
    cuota_ids = []
    if fracc_ids:
        cuota_ids = [
            c.id for c in db.query(FraccionamientoCuota.id).filter(
                FraccionamientoCuota.fraccionamiento_id.in_(fracc_ids)
            ).all()
        ]

    from sqlalchemy import or_, and_, Integer as SAInteger

    condiciones = []
    if deuda_ids:
        condiciones.append(and_(AuditLogFinanzas.entidad_tipo == "debts",
                                AuditLogFinanzas.entidad_id.in_(deuda_ids)))
    if pago_ids:
        condiciones.append(and_(AuditLogFinanzas.entidad_tipo == "payments",
                                AuditLogFinanzas.entidad_id.in_(pago_ids)))
    if fracc_ids:
        condiciones.append(and_(AuditLogFinanzas.entidad_tipo == "fraccionamientos",
                                AuditLogFinanzas.entidad_id.in_(fracc_ids)))
    if cuota_ids:
        condiciones.append(and_(AuditLogFinanzas.entidad_tipo == "fraccionamiento_cuotas",
                                AuditLogFinanzas.entidad_id.in_(cuota_ids)))

    # Respaldo: leer colegiado_id desde el JSONB detalle
    try:
        condiciones.append(
            AuditLogFinanzas.detalle["colegiado_id"].astext.cast(SAInteger) == colegiado_id
        )
    except Exception:
        pass

    if not condiciones:
        return {"colegiado_id": colegiado_id, "total": 0, "logs": []}

    cond = condiciones[0] if len(condiciones) == 1 else or_(*condiciones)

    try:
        logs = (
            db.query(AuditLogFinanzas)
            .filter(cond)
            .order_by(AuditLogFinanzas.created_at.desc())
            .limit(limit)
            .all()
        )
    except Exception as e:
        logger.warning("Error consultando audit_log_finanzas: %s", e)
        logs = []

    items = []
    for l in logs:
        fecha_lima = ""
        if l.created_at:
            ts = l.created_at
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            fecha_lima = ts.astimezone(PERU_TZ).strftime("%d/%m/%Y %H:%M")

        detalle = l.detalle or {}
        cambios = detalle.get("cambios", {}) if isinstance(detalle, dict) else {}
        motivo = detalle.get("motivo") if isinstance(detalle, dict) else None

        items.append({
            "id": l.id,
            "tabla": l.entidad_tipo,
            "registro_id": l.entidad_id,
            "accion": l.accion,
            "cambios": cambios,
            "motivo": motivo,
            "usuario_id": l.actor_id,
            "usuario": l.actor_nombre or (f"user#{l.actor_id}" if l.actor_id else None),
            "fecha": fecha_lima,
            "monto": float(l.monto) if l.monto is not None else None,
        })

    return {"colegiado_id": colegiado_id, "total": len(items), "logs": items}

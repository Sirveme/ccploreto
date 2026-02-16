"""
Políticas Financieras — ColegiosPro SAAS
app/services/politicas_financieras.py

Formaliza las reglas no escritas de los colegios profesionales
y las eleva con buenas prácticas ISO 37001 / ISO 31000.

Cada organización tiene su config_finanzas (JSONB).
Este archivo provee:
  1. Config por defecto (basada en CCPL como caso base)
  2. Validador de fraccionamientos
  3. Validador de autorizaciones
  4. Generador de cronogramas
  5. Motor de alertas anti-fraude
"""

from dataclasses import dataclass, field
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional
import logging

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 1. CONFIGURACIÓN POR DEFECTO
# ═══════════════════════════════════════════════════════════

CONFIG_DEFECTO = {
    # ── Autorizaciones ──
    "umbral_anulacion": 100.00,          # Anulaciones > esto requieren autorización
    "umbral_gasto_libre": 50.00,         # Gastos <= esto NO requieren autorización
    "umbral_doble_firma": 1000.00,       # > esto requiere 2 autorizadores
    "umbral_pago_inusual": 500.00,       # Alerta si un pago individual supera esto

    # ── Adelantos ──
    "max_adelanto_persona": 500.00,      # Máx por adelanto individual
    "max_adelantos_activos": 1,          # Máx adelantos sin liquidar por persona
    "plazo_liquidacion_dias": 30,        # Días para liquidar un adelanto

    # ── Fraccionamiento ──
    "fraccionamiento": {
        "monto_minimo": 500.00,          # Deuda mínima para fraccionar
        "cuota_inicial_pct": 20,         # % mínimo de cuota inicial
        "cuota_minima": 100.00,          # Cuota mensual mínima
        "max_cuotas": 12,               # Máximo de cuotas
        "interes_mensual_pct": 0,        # 0% = sin interés (lo normal en colegios)
        "dia_vencimiento": 15,           # Día del mes para cuotas
        "requiere_autorizacion": False,  # True = finanzas debe aprobar cada uno
        "documentar_acuerdo": True,      # Generar documento PDF del acuerdo
        # HABILIDAD TEMPORAL:
        # El fraccionamiento NO habilita permanentemente.
        # Cada pago de cuota da habilidad solo hasta el próximo vencimiento.
        # Si no paga la cuota del mes → vuelve a inhábil automáticamente.
        "habilidad_temporal": True,
        "dias_gracia": 5,               # Días después del vencimiento antes de inhabilitar
    },

    # ── Caja ──
    "fondo_fijo_caja": 200.00,          # Fondo con que abre cada caja
    "max_diferencia_caja": 10.00,        # Diferencia aceptable en cierre
    "horario_caja": {
        "apertura": "08:00",
        "cierre": "17:00",
    },

    # ── Gastos recurrentes (plantilla) ──
    "gastos_recurrentes": [
        # Se llena por colegio. Ejemplo:
        # {"concepto": "Luz eléctrica", "monto_estimado": 200, "dia_vencimiento": 20, "proveedor": "Electro Oriente"},
        # {"concepto": "Internet", "monto_estimado": 150, "dia_vencimiento": 15, "proveedor": "Movistar"},
    ],

    # ── Presupuesto ──
    "presupuesto_anual": None,           # Se llena cuando la junta lo apruebe
    "alertar_ejecucion_pct": 80,         # Alertar cuando se gaste > 80% del presupuesto

    # ── Reportes ──
    "reporte_automatico": {
        "frecuencia": "mensual",         # mensual, quincenal, semanal
        "destinatarios": [],             # IDs de miembros que reciben el reporte
        "incluir_comparativo": True,
        "incluir_morosidad": True,
        "incluir_proyeccion": True,
    },

    # ── Anti-fraude (ISO 37001) ──
    "anti_fraude": {
        "max_anulaciones_dia_cajero": 3,       # Alerta si supera
        "max_gastos_consecutivos_24h": 3,      # Alerta por gastos fraccionados
        "max_devoluciones_colegiado_30d": 2,   # Alerta por devoluciones frecuentes
        "bloquear_auto_autorizacion": True,     # Solicitante ≠ autorizador
        "registrar_ip": True,                   # Log de IP en cada operación
        "alerta_horario_inusual": True,         # Operaciones fuera de horario
    },
}


# ═══════════════════════════════════════════════════════════
# 2. MOTOR DE FRACCIONAMIENTO
# ═══════════════════════════════════════════════════════════

@dataclass
class SolicitudFraccionamiento:
    colegiado_id: int
    colegiado_nombre: str
    deuda_total: Decimal
    cuota_inicial: Decimal
    num_cuotas: int
    solicitante_id: Optional[int] = None   # cajera que registra
    notas: str = ""


@dataclass
class CuotaFraccionada:
    numero: int
    monto: Decimal
    fecha_vencimiento: date
    concepto: str


@dataclass
class ResultadoFraccionamiento:
    valido: bool
    mensaje: str
    cuota_inicial: Decimal = Decimal("0")
    cuotas: list = field(default_factory=list)
    total_a_pagar: Decimal = Decimal("0")
    documento_url: Optional[str] = None


def validar_fraccionamiento(
    solicitud: SolicitudFraccionamiento,
    config: dict = None,
) -> ResultadoFraccionamiento:
    """
    Valida y genera cronograma de fraccionamiento.

    Reglas (basadas en práctica CCPL, formalizadas):
    1. Deuda mínima: S/ 500
    2. Cuota inicial: >= 20% de la deuda
    3. Cuota mensual: >= S/ 100
    4. Máximo 12 cuotas
    5. Sin interés (configurable)

    Returns:
        ResultadoFraccionamiento con cronograma si es válido
    """
    cfg = (config or CONFIG_DEFECTO).get("fraccionamiento", CONFIG_DEFECTO["fraccionamiento"])

    deuda = solicitud.deuda_total
    inicial = solicitud.cuota_inicial
    n_cuotas = solicitud.num_cuotas

    monto_min = Decimal(str(cfg["monto_minimo"]))
    pct_inicial = Decimal(str(cfg["cuota_inicial_pct"])) / 100
    cuota_min = Decimal(str(cfg["cuota_minima"]))
    max_cuotas = cfg["max_cuotas"]
    interes = Decimal(str(cfg.get("interes_mensual_pct", 0))) / 100
    dia_venc = cfg.get("dia_vencimiento", 15)

    # ── Validaciones ──

    if deuda < monto_min:
        return ResultadoFraccionamiento(
            valido=False,
            mensaje=f"La deuda (S/ {deuda}) es menor al mínimo fraccionable (S/ {monto_min})."
        )

    inicial_minima = (deuda * pct_inicial).quantize(Decimal("0.01"), ROUND_HALF_UP)
    if inicial < inicial_minima:
        return ResultadoFraccionamiento(
            valido=False,
            mensaje=f"La cuota inicial debe ser al menos S/ {inicial_minima} ({cfg['cuota_inicial_pct']}% de S/ {deuda})."
        )

    if n_cuotas < 1 or n_cuotas > max_cuotas:
        return ResultadoFraccionamiento(
            valido=False,
            mensaje=f"El número de cuotas debe ser entre 1 y {max_cuotas}."
        )

    saldo = deuda - inicial
    cuota_mensual = (saldo / n_cuotas).quantize(Decimal("0.01"), ROUND_HALF_UP)

    if cuota_mensual < cuota_min:
        # Recalcular cuotas máximas posibles
        max_posible = int(saldo / cuota_min)
        return ResultadoFraccionamiento(
            valido=False,
            mensaje=f"La cuota mensual (S/ {cuota_mensual}) es menor al mínimo (S/ {cuota_min}). "
                    f"Con cuota mínima de S/ {cuota_min}, máximo {max_posible} cuotas."
        )

    # ── Generar cronograma ──
    cuotas = []
    hoy = date.today()

    # Primera cuota: mes siguiente
    if hoy.day <= dia_venc:
        primer_mes = hoy.replace(day=dia_venc)
    else:
        if hoy.month == 12:
            primer_mes = hoy.replace(year=hoy.year + 1, month=1, day=dia_venc)
        else:
            primer_mes = hoy.replace(month=hoy.month + 1, day=dia_venc)

    saldo_restante = saldo
    for i in range(n_cuotas):
        # Calcular fecha
        mes = primer_mes.month + i
        anio = primer_mes.year + (mes - 1) // 12
        mes = ((mes - 1) % 12) + 1
        try:
            fecha = date(anio, mes, dia_venc)
        except ValueError:
            # Febrero u otros meses cortos
            fecha = date(anio, mes, min(dia_venc, 28))

        # Última cuota ajusta centavos
        if i == n_cuotas - 1:
            monto = saldo_restante
        else:
            monto = cuota_mensual
            saldo_restante -= monto

        cuotas.append(CuotaFraccionada(
            numero=i + 1,
            monto=monto,
            fecha_vencimiento=fecha,
            concepto=f"Fraccionamiento cuota {i+1}/{n_cuotas}"
        ))

    total = inicial + sum(c.monto for c in cuotas)

    return ResultadoFraccionamiento(
        valido=True,
        mensaje=f"Fraccionamiento aprobado: S/ {inicial} inicial + {n_cuotas} cuotas de S/ {cuota_mensual}",
        cuota_inicial=inicial,
        cuotas=cuotas,
        total_a_pagar=total,
    )


def simular_fraccionamiento(deuda: Decimal, config: dict = None) -> dict:
    """
    Calcula las opciones de fraccionamiento disponibles para una deuda.
    Útil para mostrar al colegiado las alternativas.
    """
    cfg = (config or CONFIG_DEFECTO).get("fraccionamiento", CONFIG_DEFECTO["fraccionamiento"])

    monto_min = Decimal(str(cfg["monto_minimo"]))
    pct_inicial = Decimal(str(cfg["cuota_inicial_pct"])) / 100
    cuota_min = Decimal(str(cfg["cuota_minima"]))
    max_cuotas = cfg["max_cuotas"]

    if deuda < monto_min:
        return {"disponible": False, "mensaje": f"Deuda menor a S/ {monto_min}"}

    inicial_minima = (deuda * pct_inicial).quantize(Decimal("0.01"), ROUND_HALF_UP)
    saldo = deuda - inicial_minima

    # Calcular opciones
    opciones = []
    for n in range(2, max_cuotas + 1):
        cuota = (saldo / n).quantize(Decimal("0.01"), ROUND_HALF_UP)
        if cuota >= cuota_min:
            opciones.append({
                "cuotas": n,
                "cuota_inicial": float(inicial_minima),
                "cuota_mensual": float(cuota),
                "total": float(deuda),
            })

    return {
        "disponible": True,
        "deuda": float(deuda),
        "cuota_inicial_minima": float(inicial_minima),
        "cuota_inicial_pct": cfg["cuota_inicial_pct"],
        "opciones": opciones,
    }


# ═══════════════════════════════════════════════════════════
# 3. VALIDADOR DE AUTORIZACIONES
# ═══════════════════════════════════════════════════════════

def requiere_autorizacion(
    tipo: str,
    monto: Decimal,
    solicitante_id: int,
    config: dict = None,
) -> dict:
    """
    Determina si una operación requiere autorización de Finanzas.

    Returns:
        {
            "requiere": bool,
            "nivel": "ninguno" | "simple" | "doble_firma",
            "motivo": str,
        }
    """
    cfg = config or CONFIG_DEFECTO

    umbral_anulacion = Decimal(str(cfg.get("umbral_anulacion", 100)))
    umbral_gasto = Decimal(str(cfg.get("umbral_gasto_libre", 50)))
    umbral_doble = Decimal(str(cfg.get("umbral_doble_firma", 1000)))

    monto = Decimal(str(monto))

    # Gastos pequeños: libres
    if tipo == "gasto" and monto <= umbral_gasto:
        return {"requiere": False, "nivel": "ninguno", "motivo": "Monto dentro del límite libre"}

    # Anulaciones
    if tipo == "anulacion":
        if monto <= umbral_anulacion:
            return {"requiere": False, "nivel": "ninguno", "motivo": f"Anulación <= S/ {umbral_anulacion}"}
        if monto > umbral_doble:
            return {"requiere": True, "nivel": "doble_firma", "motivo": f"Anulación > S/ {umbral_doble}"}
        return {"requiere": True, "nivel": "simple", "motivo": f"Anulación > S/ {umbral_anulacion}"}

    # Devoluciones: siempre requieren
    if tipo == "devolucion":
        if monto > umbral_doble:
            return {"requiere": True, "nivel": "doble_firma", "motivo": "Devolución con doble firma"}
        return {"requiere": True, "nivel": "simple", "motivo": "Toda devolución requiere autorización"}

    # Adelantos: siempre requieren
    if tipo == "adelanto":
        return {"requiere": True, "nivel": "simple", "motivo": "Todo adelanto requiere autorización"}

    # Fraccionamientos: según config
    if tipo == "fraccionamiento":
        req = cfg.get("fraccionamiento", {}).get("requiere_autorizacion", False)
        if req:
            return {"requiere": True, "nivel": "simple", "motivo": "Fraccionamiento con autorización"}
        return {"requiere": False, "nivel": "ninguno", "motivo": "Fraccionamiento sin autorización requerida"}

    # Gastos que superan umbral
    if tipo == "gasto":
        if monto > umbral_doble:
            return {"requiere": True, "nivel": "doble_firma", "motivo": f"Gasto > S/ {umbral_doble}"}
        return {"requiere": True, "nivel": "simple", "motivo": f"Gasto > S/ {umbral_gasto}"}

    # Default: requiere simple
    return {"requiere": True, "nivel": "simple", "motivo": "Operación requiere autorización"}


# ═══════════════════════════════════════════════════════════
# 4. DETECTOR DE ANOMALÍAS (ISO 37001)
# ═══════════════════════════════════════════════════════════

def detectar_anomalias(db, organization_id: int, config: dict = None) -> list[dict]:
    """
    Escanea operaciones recientes buscando patrones sospechosos.
    Se ejecuta periódicamente (cada cierre de caja o cada hora).

    Returns:
        Lista de alertas: [{tipo, severidad, descripcion, datos}]
    """
    from app.models import Payment, Comprobante
    from sqlalchemy import func

    cfg = (config or CONFIG_DEFECTO).get("anti_fraude", CONFIG_DEFECTO["anti_fraude"])
    alertas = []
    hoy = datetime.utcnow().date()
    hace_24h = datetime.utcnow() - timedelta(hours=24)
    hace_30d = datetime.utcnow() - timedelta(days=30)

    # ── Alerta 1: Anulaciones frecuentes (general, últimas 24h) ──
    max_anul = cfg.get("max_anulaciones_dia_cajero", 3)
    try:
        total_anulaciones = db.query(func.count(Comprobante.id)).filter(
            Comprobante.organization_id == organization_id,
            Comprobante.status == "anulado",
            Comprobante.updated_at >= hace_24h,
        ).scalar() or 0

        if total_anulaciones > max_anul:
            alertas.append({
                "tipo": "anulaciones_frecuentes",
                "severidad": "media",
                "descripcion": f"{total_anulaciones} comprobantes anulados en 24h (límite: {max_anul})",
                "datos": {"cantidad": total_anulaciones},
            })
    except Exception as e:
        logger.warning(f"Error detectando anulaciones: {e}")

    # ── Alerta 2: Devoluciones frecuentes a un colegiado ──
    max_devol = cfg.get("max_devoluciones_colegiado_30d", 2)
    try:
        devoluciones = db.query(
            Payment.colegiado_id,
            func.count(Payment.id)
        ).filter(
            Payment.organization_id == organization_id,
            Payment.status == "refunded",
            Payment.created_at >= hace_30d,
        ).group_by(Payment.colegiado_id).all()

        for col_id, count in devoluciones:
            if count > max_devol:
                alertas.append({
                    "tipo": "devoluciones_frecuentes",
                    "severidad": "media",
                    "descripcion": f"Colegiado #{col_id} con {count} devoluciones en 30 días (límite: {max_devol})",
                    "datos": {"colegiado_id": col_id, "cantidad": count},
                })
    except Exception as e:
        logger.warning(f"Error detectando devoluciones: {e}")

    return alertas


# ═══════════════════════════════════════════════════════════
# 5. RESUMEN FINANCIERO
# ═══════════════════════════════════════════════════════════

def generar_resumen_financiero(db, organization_id: int) -> dict:
    """
    Genera el resumen para el dashboard de Finanzas.
    Optimizado para una sola consulta por métrica.
    """
    from app.models import Payment
    from sqlalchemy import func

    hoy_inicio = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    mes_inicio = hoy_inicio.replace(day=1)

    # Ingresos del día
    ingresos_hoy = db.query(
        func.coalesce(func.sum(Payment.amount), 0)
    ).filter(
        Payment.organization_id == organization_id,
        Payment.status == "approved",
        Payment.created_at >= hoy_inicio,
    ).scalar()

    operaciones_hoy = db.query(func.count(Payment.id)).filter(
        Payment.organization_id == organization_id,
        Payment.status == "approved",
        Payment.created_at >= hoy_inicio,
    ).scalar()

    # Recaudación del mes por método
    recaudacion = db.query(
        Payment.payment_method,
        func.coalesce(func.sum(Payment.amount), 0)
    ).filter(
        Payment.organization_id == organization_id,
        Payment.status == "approved",
        Payment.created_at >= mes_inicio,
    ).group_by(Payment.payment_method).all()

    metodos = {m: float(t) for m, t in recaudacion}

    return {
        "ingresos_hoy": float(ingresos_hoy),
        "operaciones_hoy": operaciones_hoy,
        "egresos_hoy": 0,  # TODO: cuando exista tabla de egresos
        "saldo_neto": float(ingresos_hoy),
        "autorizaciones_pendientes": 0,  # TODO: contar de solicitudes_autorizacion
        "recaudacion_mes": {
            "efectivo": metodos.get("Efectivo", 0),
            "yape": metodos.get("Yape", 0),
            "plin": metodos.get("Plin", 0),
            "transferencia": metodos.get("Transferencia", 0),
            "total": sum(metodos.values()),
        }
    }


# ═══════════════════════════════════════════════════════════
# 6. HABILIDAD TEMPORAL POR FRACCIONAMIENTO
# ═══════════════════════════════════════════════════════════
#
# REGLA DE NEGOCIO:
#   Un colegiado fraccionado NO queda hábil permanentemente.
#   Cada pago de cuota le da habilidad solo hasta el próximo vencimiento.
#   Si no paga la cuota del mes → vuelve a inhábil.
#
# CAMPOS NECESARIOS EN colegiados:
#   habilidad_vence TIMESTAMP  → fecha hasta la cual es hábil
#   tiene_fraccionamiento BOOLEAN DEFAULT false
#
# FLUJO:
#   1. Colegiado fracciona → se le pone hábil hasta 1er vencimiento + días_gracia
#   2. Paga cuota mensual → habilidad se extiende hasta siguiente vencimiento + gracia
#   3. Tarea diaria revisa → si habilidad_vence < hoy y tiene_fraccionamiento → inhábil
#   4. Certificados muestran: "Válido hasta: DD/MM/YYYY" (no indefinido)


def habilitar_por_fraccionamiento(
    db,
    colegiado_id: int,
    proxima_cuota_vencimiento: date,
    config: dict = None,
):
    """
    Habilita temporalmente a un colegiado que pagó cuota de fraccionamiento.

    La habilidad dura hasta la fecha de la próxima cuota + días de gracia.
    """
    from app.models import Colegiado

    cfg = (config or CONFIG_DEFECTO).get("fraccionamiento", CONFIG_DEFECTO["fraccionamiento"])
    dias_gracia = cfg.get("dias_gracia", 5)

    col = db.query(Colegiado).filter(Colegiado.id == colegiado_id).first()
    if not col:
        return

    vence = proxima_cuota_vencimiento + timedelta(days=dias_gracia)

    col.condicion = "habil"
    col.fecha_actualizacion_condicion = datetime.now(timezone.utc)
    col.tiene_fraccionamiento = True
    col.habilidad_vence = datetime.combine(vence, datetime.min.time()).replace(
        tzinfo=timezone.utc
    )

    logger.info(
        f"Colegiado #{colegiado_id} → HÁBIL temporal hasta {vence} "
        f"(fraccionamiento, gracia {dias_gracia}d)"
    )


def verificar_habilidades_vencidas(db, organization_id: int) -> dict:
    """
    Tarea diaria: revisa colegiados con habilidad temporal vencida.
    Los que tengan habilidad_vence < hoy → inhábil.

    Ejecutar: 1 vez al día (cron o al abrir primera caja).

    Returns:
        {"inhabilitados": N, "detalle": [...]}
    """
    from app.models import Colegiado

    ahora = datetime.now(timezone.utc)

    vencidos = db.query(Colegiado).filter(
        Colegiado.organization_id == organization_id,
        Colegiado.tiene_fraccionamiento == True,
        Colegiado.condicion == "habil",
        Colegiado.habilidad_vence.isnot(None),
        Colegiado.habilidad_vence < ahora,
    ).all()

    inhabilitados = []
    for col in vencidos:
        col.condicion = "inhabil"
        col.motivo_inhabilidad = "Cuota de fraccionamiento vencida sin pago"
        col.fecha_actualizacion_condicion = ahora
        inhabilitados.append({
            "id": col.id,
            "nombre": col.apellidos_nombres,
            "vencia": col.habilidad_vence.strftime("%d/%m/%Y"),
        })
        logger.info(f"Colegiado #{col.id} → INHÁBIL (fraccionamiento vencido)")

    if inhabilitados:
        db.commit()

    return {
        "inhabilitados": len(inhabilitados),
        "detalle": inhabilitados,
    }


def proxima_cuota_fraccionamiento(db, colegiado_id: int) -> Optional[date]:
    """Obtiene la fecha de la próxima cuota pendiente de fraccionamiento."""
    from app.models import Debt

    cuota = db.query(Debt).filter(
        Debt.colegiado_id == colegiado_id,
        Debt.debt_type == "fraccionamiento",
        Debt.status.in_(["pending", "partial"]),
    ).order_by(Debt.due_date.asc()).first()

    return cuota.due_date if cuota else None
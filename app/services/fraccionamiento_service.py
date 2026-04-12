"""
Servicio: Creación y pago de fraccionamientos
app/services/fraccionamiento_service.py

Helper compartido entre:
- POST /api/secretaria/registrar-fraccionamiento (secretaria.py)
- POST /api/secretaria/registrar-pago-cuota-fracc (secretaria.py)

Nota: el endpoint canónico del portal del colegiado es
POST /api/portal/fraccionamiento/crear (portal_colegiado.py), que mantiene
su propia lógica equivalente. Este helper se mantiene como entrada para
los flujos administrativos (Sandra) que requieren seleccionar deudas
explícitamente con `deuda_ids`.

Reglas CCPL:
- Deuda mínima S/ 500
- Cuota inicial >= 20% de deuda
- Cuota mensual >= S/ 100
- Máximo 12 cuotas mensuales
- Cuota 0 = inicial (vence hoy), cuotas 1..N mensuales (vencen día 15)
- Al pagar cuota inicial → colegiado queda HÁBIL hasta próxima cuota
"""

from datetime import date as dt_date, datetime, timezone, timedelta
from typing import Optional, List
from dataclasses import dataclass

from sqlalchemy.orm import Session
from fastapi import HTTPException

from dateutil.relativedelta import relativedelta

from app.models_debt_management import Debt, Fraccionamiento, FraccionamientoCuota

PERU_TZ = timezone(timedelta(hours=-5))
DEUDA_MIN = 500.0
CUOTA_MENSUAL_MIN = 100.0
MAX_CUOTAS = 12
CUOTA_INICIAL_PCT = 0.20


@dataclass
class ResultadoFraccionamiento:
    fraccionamiento: Fraccionamiento
    cronograma: List[dict]   # [{n_cuota, monto, fecha_vencimiento}]
    condona_detalle: Optional[dict] = None


def _generar_numero_solicitud(db: Session, organization_id: int, anio: int) -> str:
    ultimo = (
        db.query(Fraccionamiento)
        .filter(Fraccionamiento.organization_id == organization_id)
        .filter(Fraccionamiento.numero_solicitud.like(f"FRACC-{anio}-%"))
        .count()
    )
    return f"FRACC-{anio}-{str(ultimo + 1).zfill(4)}"


def crear_fraccionamiento(
    db: Session,
    colegiado,
    deuda_ids: List[int],
    n_cuotas: int,
    monto_cuota_inicial: float,
    monto_cuota_mensual: Optional[float],
    created_by_user_id: int,
    nota_audit: Optional[str] = None,
    aplicar_acuerdo_007: bool = True,
) -> ResultadoFraccionamiento:
    """
    Crea un plan de fraccionamiento. Valida reglas, crea Fraccionamiento,
    FraccionamientoCuota[], marca las deudas como 'fraccionada' y
    (opcionalmente) aplica condonación del Acuerdo 007-2026.

    Raises HTTPException con detalles si la validación falla.
    """
    if not deuda_ids:
        raise HTTPException(400, "Debe seleccionar al menos una deuda para fraccionar")

    if not (2 <= n_cuotas <= MAX_CUOTAS):
        raise HTTPException(
            400,
            f"El número de cuotas debe estar entre 2 y {MAX_CUOTAS}"
        )

    # ── Verificar plan activo ──
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
            f"El colegiado ya tiene un plan activo (#{plan_existente.numero_solicitud})"
        )

    # ── Cargar deudas y validar pertenencia ──
    deudas_qs = (
        db.query(Debt)
        .filter(
            Debt.id.in_(deuda_ids),
            Debt.colegiado_id == colegiado.id,
            Debt.status.in_(["pending", "partial"]),
        )
        .all()
    )
    if len(deudas_qs) != len(set(deuda_ids)):
        encontradas = {d.id for d in deudas_qs}
        faltantes = set(deuda_ids) - encontradas
        raise HTTPException(
            400,
            f"Deudas no válidas o ya resueltas: {sorted(faltantes)}"
        )

    total = round(sum(float(d.balance or d.amount or 0) for d in deudas_qs), 2)
    if total < DEUDA_MIN:
        raise HTTPException(
            400,
            f"La deuda (S/ {total:.2f}) es menor al mínimo de S/ {DEUDA_MIN:.2f}"
        )

    # ── Validar cuota inicial ──
    minimo_inicial = round(total * CUOTA_INICIAL_PCT, 2)
    if monto_cuota_inicial < minimo_inicial - 0.009:
        raise HTTPException(
            400,
            f"La cuota inicial mínima es S/ {minimo_inicial:.2f} "
            f"({int(CUOTA_INICIAL_PCT * 100)}% de S/ {total:.2f})"
        )
    if monto_cuota_inicial >= total:
        raise HTTPException(
            400,
            "La cuota inicial no puede cubrir toda la deuda; usa pago directo"
        )

    # ── Calcular cuota mensual ──
    saldo = round(total - monto_cuota_inicial, 2)
    monto_mensual_calc = round(saldo / n_cuotas, 2)

    # Si el cliente mandó un valor, debe ser consistente (tolerancia 1 sol)
    if monto_cuota_mensual is not None:
        if abs(monto_cuota_mensual - monto_mensual_calc) > 1.0:
            raise HTTPException(
                400,
                f"La cuota mensual esperada es S/ {monto_mensual_calc:.2f} "
                f"(saldo {saldo:.2f} / {n_cuotas} cuotas)"
            )
    monto_mensual = monto_mensual_calc

    if monto_mensual < CUOTA_MENSUAL_MIN:
        raise HTTPException(
            400,
            f"La cuota mensual resultante (S/ {monto_mensual:.2f}) es menor "
            f"al mínimo de S/ {CUOTA_MENSUAL_MIN:.2f}. Reduce el número "
            f"de cuotas o aumenta la cuota inicial."
        )

    # ── Fechas ──
    hoy = dt_date.today()
    primer_venc = hoy.replace(day=15) + relativedelta(months=1)
    ultima_venc = primer_venc + relativedelta(months=n_cuotas - 1)

    # ── Número de solicitud ──
    numero_solicitud = _generar_numero_solicitud(db, colegiado.organization_id, hoy.year)

    # ── Crear Fraccionamiento ──
    fracc = Fraccionamiento(
        organization_id=colegiado.organization_id,
        colegiado_id=colegiado.id,
        numero_solicitud=numero_solicitud,
        fecha_solicitud=hoy,
        deuda_total_original=total,
        cuota_inicial=monto_cuota_inicial,
        cuota_inicial_pagada=False,
        saldo_a_fraccionar=saldo,
        num_cuotas=n_cuotas,
        monto_cuota=monto_mensual,
        cuotas_pagadas=0,
        cuotas_atrasadas=0,
        saldo_pendiente=total,
        fecha_inicio=hoy,
        fecha_fin_estimada=ultima_venc,
        proxima_cuota_fecha=hoy,
        proxima_cuota_numero=0,
        estado="activo",
        created_by=created_by_user_id,
        approved_by=None,
    )
    db.add(fracc)
    db.flush()

    # ── Crear cuotas ──
    cuotas_objs: List[FraccionamientoCuota] = []
    cronograma: List[dict] = []

    # Cuota 0 — inicial
    cuotas_objs.append(FraccionamientoCuota(
        fraccionamiento_id=fracc.id,
        numero_cuota=0,
        monto=monto_cuota_inicial,
        fecha_vencimiento=hoy,
        habilidad_hasta=None,
    ))
    cronograma.append({
        "n_cuota": 0,
        "monto": float(monto_cuota_inicial),
        "fecha_vencimiento": hoy.isoformat(),
        "tipo": "inicial",
    })

    # Cuotas mensuales 1..N
    for i in range(1, n_cuotas + 1):
        venc = primer_venc + relativedelta(months=i - 1)
        fin_mes = (venc.replace(day=1) + relativedelta(months=1)) - timedelta(days=1)
        cuotas_objs.append(FraccionamientoCuota(
            fraccionamiento_id=fracc.id,
            numero_cuota=i,
            monto=monto_mensual,
            fecha_vencimiento=venc,
            habilidad_hasta=fin_mes,
        ))
        cronograma.append({
            "n_cuota": i,
            "monto": float(monto_mensual),
            "fecha_vencimiento": venc.isoformat(),
            "tipo": "mensual",
        })

    db.bulk_save_objects(cuotas_objs)

    # ── Marcar deudas como fraccionadas ──
    for d in deudas_qs:
        d.estado_gestion = "fraccionada"
        d.fraccionamiento_id = fracc.id
        if nota_audit:
            d.notes = ((d.notes or "") + f"\n{nota_audit}").strip()

    db.commit()
    db.refresh(fracc)

    # ── Aplicar Acuerdo 007-2026 si corresponde ──
    condona_info = None
    if aplicar_acuerdo_007:
        try:
            from app.services.servicio_condona_007 import aplicar_condona_acuerdo_007
            resumen = aplicar_condona_acuerdo_007(
                db,
                colegiado_id=colegiado.id,
                org_id=colegiado.organization_id,
                aprobado_por_id=created_by_user_id,
            )
            if resumen.aplicado:
                condona_info = {
                    "aplicado": True,
                    "filas_condonadas": resumen.filas_condonadas,
                    "monto_condonado": float(resumen.monto_condonado),
                    "mensaje": resumen.mensaje,
                }
            else:
                condona_info = {
                    "aplicado": False,
                    "mensaje": resumen.mensaje,
                }
        except Exception as e:
            condona_info = {
                "aplicado": False,
                "mensaje": f"No se pudo evaluar Acuerdo 007-2026: {e}"
            }

    return ResultadoFraccionamiento(
        fraccionamiento=fracc,
        cronograma=cronograma,
        condona_detalle=condona_info,
    )


def pagar_cuota_fraccionamiento(
    db: Session,
    fraccionamiento_id: int,
    numero_cuota: int,
    monto: float,
    metodo_pago: str,
    operador_nota: str,
    payment_obj=None,
) -> dict:
    """
    Marca una cuota como pagada. Retorna dict con {cuota, es_inicial, habilidad_hasta}.
    Actualiza también fracc.cuotas_pagadas, saldo_pendiente, proxima_cuota_*.
    Si cuotas_pagadas == num_cuotas + 1 (inicial + todas), estado = 'completado'.
    """
    fracc = db.query(Fraccionamiento).filter(
        Fraccionamiento.id == fraccionamiento_id
    ).first()
    if not fracc:
        raise HTTPException(404, "Fraccionamiento no encontrado")
    if fracc.estado != "activo":
        raise HTTPException(
            400,
            f"El fraccionamiento está {fracc.estado}, no permite pagos"
        )

    cuota = db.query(FraccionamientoCuota).filter(
        FraccionamientoCuota.fraccionamiento_id == fraccionamiento_id,
        FraccionamientoCuota.numero_cuota == numero_cuota,
    ).first()
    if not cuota:
        raise HTTPException(404, f"Cuota {numero_cuota} no existe en el plan")
    if cuota.pagada:
        raise HTTPException(400, f"La cuota {numero_cuota} ya está pagada")

    hoy = dt_date.today()
    cuota.pagada = True
    cuota.fecha_pago = hoy
    if payment_obj is not None and getattr(payment_obj, "id", None):
        cuota.payment_id = payment_obj.id

    # Actualizar contadores del plan
    fracc.cuotas_pagadas = (fracc.cuotas_pagadas or 0) + 1
    fracc.saldo_pendiente = max(0.0, float(fracc.saldo_pendiente or 0) - float(monto))

    es_inicial = (numero_cuota == 0)
    if es_inicial:
        fracc.cuota_inicial_pagada = True

    # Próxima cuota pendiente
    proxima = db.query(FraccionamientoCuota).filter(
        FraccionamientoCuota.fraccionamiento_id == fraccionamiento_id,
        FraccionamientoCuota.pagada == False,  # noqa: E712
    ).order_by(FraccionamientoCuota.numero_cuota.asc()).first()

    if proxima:
        fracc.proxima_cuota_numero = proxima.numero_cuota
        fracc.proxima_cuota_fecha = proxima.fecha_vencimiento
    else:
        fracc.estado = "completado"
        fracc.proxima_cuota_numero = None
        fracc.proxima_cuota_fecha = None

    db.flush()

    return {
        "cuota_id": cuota.id,
        "numero_cuota": numero_cuota,
        "es_inicial": es_inicial,
        "habilidad_hasta": cuota.habilidad_hasta.isoformat() if cuota.habilidad_hasta else None,
        "completado": fracc.estado == "completado",
        "proxima_cuota_numero": fracc.proxima_cuota_numero,
        "proxima_cuota_fecha": (
            fracc.proxima_cuota_fecha.isoformat()
            if fracc.proxima_cuota_fecha else None
        ),
        "notas_operador": operador_nota,
    }

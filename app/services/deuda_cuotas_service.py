"""
Servicio: Cálculo de Deuda de Cuotas Ordinarias (Inferida)
app/services/deuda_cuotas_service.py

PRINCIPIO: La obligación de pagar cuotas mensuales nace del Estatuto + fecha_colegiatura.
No se registran filas de deuda para cuotas — se INFIEREN en tiempo real.

    Deuda Cuotas = Meses Obligados - Meses Pagados - Meses Exceptuados

Esto se combina con la deuda registrada en `debts` (multas, extraordinarias, etc.)
para obtener la deuda total del colegiado.
"""

from datetime import date, datetime, timezone, timedelta
from typing import List, Dict, Optional, Set, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_, func

from app.models import (
    Colegiado, Payment, ConceptoCobro, Organization
)
from app.models_debt_management import Debt, DebtAction

PERU_TZ = timezone(timedelta(hours=-5))

# Meses labels
MESES_LABEL = {
    1: 'Ene', 2: 'Feb', 3: 'Mar', 4: 'Abr', 5: 'May', 6: 'Jun',
    7: 'Jul', 8: 'Ago', 9: 'Set', 10: 'Oct', 11: 'Nov', 12: 'Dic'
}

MESES_LABEL_FULL = {
    1: 'Enero', 2: 'Febrero', 3: 'Marzo', 4: 'Abril', 5: 'Mayo',
    6: 'Junio', 7: 'Julio', 8: 'Agosto', 9: 'Setiembre',
    10: 'Octubre', 11: 'Noviembre', 12: 'Diciembre'
}


def generar_periodos(desde: date, hasta: date) -> List[str]:
    """
    Genera lista de periodos 'YYYY-MM' desde una fecha hasta otra.
    Ej: generar_periodos(date(2024,3,1), date(2024,7,15))
        → ['2024-03', '2024-04', '2024-05', '2024-06', '2024-07']
    """
    periodos = []
    current = date(desde.year, desde.month, 1)
    fin = date(hasta.year, hasta.month, 1)
    while current <= fin:
        periodos.append(current.strftime('%Y-%m'))
        # Avanzar un mes
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)
    return periodos


def obtener_meses_pagados(
    colegiado_id: int,
    organization_id: int,
    db: Session
) -> Set[str]:
    """
    Retorna set de periodos pagados (aprobados) para cuotas ordinarias.
    Busca en payments por concepto_cobro_id = CUOT-ORD o por debt_type.
    """
    # Buscar el concepto_cobro_id de cuota ordinaria
    cuot_ord = db.query(ConceptoCobro).filter(
        ConceptoCobro.organization_id == organization_id,
        ConceptoCobro.codigo == 'CUOT-ORD'
    ).first()

    pagados = set()

    if cuot_ord:
        # Pagos vinculados al concepto CUOT-ORD
        rows = db.query(Payment.periodo).filter(
            Payment.colegiado_id == colegiado_id,
            Payment.concepto_cobro_id == cuot_ord.id,
            Payment.estado == 'approved'
        ).distinct().all()
        pagados.update(r[0] for r in rows if r[0])

    # También buscar pagos con debt_type='cuota_ordinaria' (legacy)
    rows2 = db.query(Payment.periodo).filter(
        Payment.colegiado_id == colegiado_id,
        Payment.estado == 'approved'
    ).distinct().all()
    # Filtrar los que parecen cuota ordinaria por periodo format YYYY-MM
    import re
    for r in rows2:
        if r[0] and re.match(r'^\d{4}-\d{2}$', r[0]):
            pagados.add(r[0])

    return pagados


def obtener_meses_exceptuados(
    colegiado_id: int,
    organization_id: int,
    db: Session
) -> Set[str]:
    """
    Retorna set de periodos exceptuados (exonerados, condonados) de cuotas.
    Busca en debt_actions por tipo exoneracion/condonacion que apliquen a cuotas.
    
    Las excepciones se registran como DebtAction con periodos afectados
    en el campo descripcion (parsear) o con un campo dedicado.
    
    Para la primera versión, buscamos en Debt + DebtAction:
    - Debts con estado_gestion in (condonada, exonerada) y debt_type=cuota_ordinaria
    """
    exceptuados = set()

    # Debts de cuota ordinaria que fueron condonadas/exoneradas
    rows = db.query(Debt.periodo).filter(
        Debt.colegiado_id == colegiado_id,
        Debt.organization_id == organization_id,
        Debt.debt_type == 'cuota_ordinaria',
        Debt.estado_gestion.in_(['condonada', 'exonerada', 'compensada'])
    ).all()
    exceptuados.update(r[0] for r in rows if r[0])

    return exceptuados


def obtener_monto_cuota(
    organization_id: int,
    periodo: str,
    db: Session
) -> float:
    """
    Retorna el monto de cuota ordinaria vigente para un periodo dado.
    Permite que el monto haya cambiado en el tiempo.
    
    Por ahora usa monto_base de ConceptoCobro CUOT-ORD.
    En el futuro puede consultar un historial de montos.
    """
    cuot_ord = db.query(ConceptoCobro).filter(
        ConceptoCobro.organization_id == organization_id,
        ConceptoCobro.codigo == 'CUOT-ORD'
    ).first()

    return cuot_ord.monto_base if cuot_ord else 20.0


def calcular_deuda_cuotas(
    colegiado_id: int,
    organization_id: int,
    db: Session,
    hasta: Optional[date] = None
) -> Dict:
    """
    Calcula la deuda de cuotas ordinarias de un colegiado.
    
    Retorna:
    {
        'periodos_obligados': ['2024-01', '2024-02', ...],
        'periodos_pagados': {'2024-01', '2024-03'},
        'periodos_exceptuados': {'2024-02'},
        'periodos_pendientes': [
            {'periodo': '2024-04', 'label': 'Abr 2024', 'monto': 20.0, 'vencido': True, 'dias_mora': 300},
            ...
        ],
        'total_cuotas_pendientes': 8,
        'monto_total': 160.0,
        'monto_cuota_mensual': 20.0,
        'desde': '2023-06',
        'ultimo_pago': '2024-03',
    }
    """
    colegiado = db.query(Colegiado).filter(Colegiado.id == colegiado_id).first()
    if not colegiado:
        return {'error': 'Colegiado no encontrado'}

    # Determinar desde cuándo debe cuotas
    fecha_desde = getattr(colegiado, 'fecha_colegiatura', None)
    if not fecha_desde:
        # Fallback: usar created_at del colegiado
        if colegiado.created_at:
            fecha_desde = colegiado.created_at.date() if hasattr(colegiado.created_at, 'date') else colegiado.created_at
        else:
            fecha_desde = date(2020, 1, 1)  # Default conservador

    # Determinar hasta cuándo
    if not hasta:
        hoy = datetime.now(PERU_TZ).date()
        # Solo hasta el mes actual (no generar deuda futura)
        hasta = hoy

    # No generar deuda para fallecidos, retirados, vitalicios
    condicion = getattr(colegiado, 'condicion', 'habil')
    if condicion in ('fallecido', 'retirado', 'vitalicio'):
        fecha_baja = getattr(colegiado, 'fecha_baja', None)
        if fecha_baja:
            hasta = min(hasta, fecha_baja)
        else:
            return {
                'periodos_pendientes': [],
                'total_cuotas_pendientes': 0,
                'monto_total': 0,
                'condicion': condicion,
                'nota': f'Colegiado {condicion} — sin obligación vigente'
            }

    # 1. Generar meses obligados
    periodos_obligados = generar_periodos(fecha_desde, hasta)

    # 2. Obtener meses pagados
    pagados = obtener_meses_pagados(colegiado_id, organization_id, db)

    # 3. Obtener meses exceptuados
    exceptuados = obtener_meses_exceptuados(colegiado_id, organization_id, db)

    # 4. Calcular pendientes
    monto_cuota = obtener_monto_cuota(organization_id, '', db)
    hoy = datetime.now(PERU_TZ).date()

    pendientes = []
    for per in periodos_obligados:
        if per in pagados or per in exceptuados:
            continue

        anio, mes = int(per[:4]), int(per[5:7])
        # Fecha de vencimiento: último día del mes
        if mes == 12:
            venc = date(anio + 1, 1, 1) - timedelta(days=1)
        else:
            venc = date(anio, mes + 1, 1) - timedelta(days=1)

        vencido = hoy > venc
        dias_mora = (hoy - venc).days if vencido else 0

        pendientes.append({
            'periodo': per,
            'label': f"{MESES_LABEL.get(mes, '')} {anio}",
            'label_full': f"{MESES_LABEL_FULL.get(mes, '')} {anio}",
            'monto': monto_cuota,
            'vencido': vencido,
            'dias_mora': dias_mora,
            'vencimiento': venc.isoformat(),
        })

    # Último pago
    ultimo_pago = max(pagados) if pagados else None

    return {
        'periodos_obligados_count': len(periodos_obligados),
        'periodos_pagados': sorted(pagados),
        'periodos_exceptuados': sorted(exceptuados),
        'periodos_pendientes': pendientes,
        'total_cuotas_pendientes': len(pendientes),
        'monto_total': round(len(pendientes) * monto_cuota, 2),
        'monto_cuota_mensual': monto_cuota,
        'desde': periodos_obligados[0] if periodos_obligados else None,
        'ultimo_pago': ultimo_pago,
        'fecha_colegiatura': fecha_desde.isoformat() if fecha_desde else None,
    }


def calcular_deuda_total(
    colegiado_id: int,
    organization_id: int,
    db: Session
) -> Dict:
    """
    Deuda total = Cuotas inferidas + Obligaciones registradas en debts.
    
    Este es el endpoint que usa el frontend (Mis Pagos, Portal Inactivo).
    """
    # 1. Cuotas ordinarias (inferidas)
    cuotas = calcular_deuda_cuotas(colegiado_id, organization_id, db)

    # 2. Otras deudas (registradas en debts: multas, extraordinarias, eventos)
    otras = db.query(Debt).filter(
        Debt.colegiado_id == colegiado_id,
        Debt.organization_id == organization_id,
        Debt.status.in_(['pending', 'partial']),
        Debt.estado_gestion.in_(['vigente', 'en_cobranza']),
        Debt.debt_type != 'cuota_ordinaria',  # Las ordinarias se infieren
    ).order_by(Debt.due_date).all()

    obligaciones = []
    for d in otras:
        obligaciones.append({
            'id': d.id,
            'tipo': 'registrada',
            'concepto': d.concept,
            'periodo': d.periodo,
            'period_label': d.period_label or d.concept,
            'categoria': d.debt_type,
            'monto_original': d.amount,
            'balance': d.balance,
            'vencimiento': d.due_date.isoformat() if d.due_date else None,
            'base_legal': d.base_legal_referencia,
            'es_exigible': d.es_exigible if hasattr(d, 'es_exigible') else False,
        })

    monto_otras = sum(o['balance'] for o in obligaciones)

    # 3. Fraccionamientos activos
    from app.models.debt_management import Fraccionamiento
    fracc = db.query(Fraccionamiento).filter(
        Fraccionamiento.colegiado_id == colegiado_id,
        Fraccionamiento.organization_id == organization_id,
        Fraccionamiento.estado == 'activo'
    ).first()

    fraccionamiento = None
    if fracc:
        fraccionamiento = {
            'id': fracc.id,
            'deuda_original': fracc.deuda_total_original,
            'saldo': fracc.saldo_pendiente,
            'cuota_mensual': fracc.monto_cuota,
            'cuotas_pagadas': fracc.cuotas_pagadas,
            'cuotas_total': fracc.num_cuotas,
            'proxima_cuota': fracc.proxima_cuota_fecha.isoformat() if fracc.proxima_cuota_fecha else None,
            'estado': fracc.estado,
        }

    return {
        'colegiado_id': colegiado_id,
        'cuotas': cuotas,
        'obligaciones': obligaciones,
        'fraccionamiento': fraccionamiento,
        'resumen': {
            'deuda_cuotas': cuotas.get('monto_total', 0),
            'deuda_otras': monto_otras,
            'deuda_fraccionamiento': fracc.saldo_pendiente if fracc else 0,
            'deuda_total': (
                cuotas.get('monto_total', 0) +
                monto_otras +
                (fracc.saldo_pendiente if fracc else 0)
            ),
            'cuotas_pendientes': cuotas.get('total_cuotas_pendientes', 0),
            'ultimo_pago_cuota': cuotas.get('ultimo_pago'),
        }
    }


def aplicar_descuento_estacional(
    monto: float,
    periodos: List[str],
    fecha_pago: Optional[date] = None
) -> Dict:
    """
    Calcula descuento por pago anticipado de cuotas FUTURAS.
    
    Reglas:
    - Ene-Feb: 20% descuento en cuotas futuras hasta diciembre
    - Mar: 10% descuento en cuotas futuras hasta diciembre
    - Abr+: sin descuento
    
    Solo aplica a cuotas FUTURAS, NO a deuda atrasada.
    """
    if not fecha_pago:
        fecha_pago = datetime.now(PERU_TZ).date()

    mes_pago = fecha_pago.month
    anio_pago = fecha_pago.year

    if mes_pago <= 2:
        porcentaje = 20
    elif mes_pago == 3:
        porcentaje = 10
    else:
        porcentaje = 0

    if porcentaje == 0:
        return {
            'aplica': False,
            'porcentaje': 0,
            'monto_original': monto,
            'descuento': 0,
            'monto_final': monto,
        }

    # Solo periodos del año actual y futuros (no atrasados)
    primer_mes_futuro = f"{anio_pago}-{fecha_pago.month + 1:02d}" if fecha_pago.month < 12 else f"{anio_pago + 1}-01"
    periodos_futuros = [p for p in periodos if p >= primer_mes_futuro and p[:4] == str(anio_pago)]

    # Monto con descuento solo en los futuros
    monto_futuro = len(periodos_futuros) * (monto / len(periodos)) if periodos else 0
    monto_pasado = monto - monto_futuro
    descuento = round(monto_futuro * porcentaje / 100, 2)

    return {
        'aplica': True,
        'porcentaje': porcentaje,
        'periodo_descuento': f"{'Ene-Feb' if mes_pago <= 2 else 'Marzo'} {anio_pago}",
        'periodos_con_descuento': periodos_futuros,
        'monto_original': monto,
        'monto_atrasado': round(monto_pasado, 2),
        'monto_futuro': round(monto_futuro, 2),
        'descuento': descuento,
        'monto_final': round(monto - descuento, 2),
    }
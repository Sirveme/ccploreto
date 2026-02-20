"""
Módulo: API Pagos Colegiado
app/routers/api_colegiado_pagos.py

Endpoints para el modal "Mis Pagos" del dashboard del colegiado.
Sirve catálogo, deudas pendientes e historial de pagos.
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import and_, func, or_
from datetime import datetime, timezone, timedelta

from app.database import get_db
from app.routers.dashboard import get_current_member
from app.models import Member, Colegiado, Payment, Comprobante, ConceptoCobro
from app.models_debt_management import Debt

router = APIRouter(prefix="/api/colegiado", tags=["Colegiado Pagos"])

PERU_TZ = timezone(timedelta(hours=-5))

# Iconos y colores por categoría (usados en el frontend)
CATEGORIA_META = {
    "cuotas":        {"icon": "ph-calendar",            "color": "#3b82f6"},
    "constancias":   {"icon": "ph-certificate",         "color": "#d4af37"},
    "derechos":      {"icon": "ph-stamp",               "color": "#8b5cf6"},
    "capacitacion":  {"icon": "ph-graduation-cap",      "color": "#10b981"},
    "alquileres":    {"icon": "ph-building-apartment",   "color": "#06b6d4"},
    "recreacion":    {"icon": "ph-swimming-pool",        "color": "#14b8a6"},
    "mercaderia":    {"icon": "ph-storefront",           "color": "#f97316"},
    "multas":        {"icon": "ph-warning",              "color": "#ef4444"},
    "eventos":       {"icon": "ph-confetti",             "color": "#ec4899"},
    "otros":         {"icon": "ph-dots-three",           "color": "#64748b"},
}

CATEGORIA_LABELS = {
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


def _get_colegiado(member: Member, db: Session) -> Colegiado:
    """Obtiene el colegiado vinculado al member."""
    colegiado = db.query(Colegiado).filter(
        Colegiado.member_id == member.id
    ).first()
    if not colegiado:
        raise HTTPException(status_code=404, detail="Colegiado no vinculado")
    return colegiado


@router.get("/mis-pagos")
async def get_mis_pagos(
    member: Member = Depends(get_current_member),
    db: Session = Depends(get_db)
):
    """
    Endpoint principal para el modal Mis Pagos.
    Retorna resumen, deudas pendientes, catálogo de servicios e historial.
    """
    colegiado = _get_colegiado(member, db)

    # --- RESUMEN ---
    deudas_query = db.query(Debt).filter(
        Debt.colegiado_id == colegiado.id,
        Debt.status.in_(["pending", "partial"])
    )
    deuda_total = sum(d.balance for d in deudas_query.all()) if deudas_query.count() > 0 else 0

    total_pagado = db.query(func.coalesce(func.sum(Payment.amount), 0)).filter(
        or_(Payment.colegiado_id == colegiado.id, Payment.member_id == member.id),
        Payment.status == "approved"
    ).scalar() or 0

    en_revision = db.query(func.coalesce(func.sum(Payment.amount), 0)).filter(
        or_(Payment.colegiado_id == colegiado.id, Payment.member_id == member.id),
        Payment.status == "review"
    ).scalar() or 0

    resumen = {
        "deuda_total": float(deuda_total),
        "total_pagado": float(total_pagado),
        "en_revision": float(en_revision),
        "cuotas_pendientes": deudas_query.filter(
            Debt.debt_type == "cuota_ordinaria"
        ).count()
    }

    # --- DEUDAS PENDIENTES ---
    deudas_raw = db.query(Debt).filter(
        Debt.colegiado_id == colegiado.id,
        Debt.status.in_(["pending", "partial"])
    ).order_by(Debt.due_date).all()

    deudas = []
    for d in deudas_raw:
        deudas.append({
            "id":             d.id,
            "concepto":       d.concept or "Cuota",
            "concepto_corto": d.concept or "Cuota",
            "periodo":        d.periodo or "",
            "vencimiento":    d.due_date.isoformat() if d.due_date else None,
            "monto_original": float(d.amount),
            "balance":        float(d.balance),
            "categoria":      d.debt_type or "cuotas",
        })

    # --- CATÁLOGO DE SERVICIOS ---
    # Solo items activos que NO generan deuda automática (son compras on-demand)
    conceptos = db.query(ConceptoCobro).filter(
        ConceptoCobro.organization_id == member.organization_id,
        ConceptoCobro.activo == True,
        or_(ConceptoCobro.genera_deuda == False, ConceptoCobro.genera_deuda == None),
    ).order_by(ConceptoCobro.orden).all()

    catalogo = []
    for c in conceptos:
        item = {
            "id": c.id,
            "codigo": c.codigo,
            "nombre": c.nombre,
            "nombre_corto": c.nombre_corto or c.nombre,
            "descripcion": c.descripcion,
            "categoria": c.categoria,
            "categoria_label": CATEGORIA_LABELS.get(c.categoria, c.categoria.title()),
            "categoria_icon": CATEGORIA_META.get(c.categoria, {}).get("icon", "ph-circle"),
            "categoria_color": CATEGORIA_META.get(c.categoria, {}).get("color", "#64748b"),
            "monto_base": float(c.monto_base),
            "permite_monto_libre": c.permite_monto_libre,
            "monto_minimo": float(c.monto_minimo) if c.monto_minimo else 0,
            "monto_maximo": float(c.monto_maximo) if c.monto_maximo else 0,
            "afecto_igv": c.afecto_igv,
            "maneja_stock": c.maneja_stock,
            "stock_actual": c.stock_actual if c.maneja_stock else None,
            "requiere_colegiado": c.requiere_colegiado,
        }
        catalogo.append(item)

    # Categorías disponibles (para los filter pills)
    categorias_set = sorted(set(c["categoria"] for c in catalogo))
    categorias = [
        {
            "key": cat,
            "label": CATEGORIA_LABELS.get(cat, cat.title()),
            "icon": CATEGORIA_META.get(cat, {}).get("icon", "ph-circle"),
            "color": CATEGORIA_META.get(cat, {}).get("color", "#64748b"),
            "count": len([c for c in catalogo if c["categoria"] == cat])
        }
        for cat in categorias_set
    ]

    # --- HISTORIAL ---
    pagos_raw = db.query(Payment).filter(
        or_(
            Payment.colegiado_id == colegiado.id,
            Payment.member_id == member.id,
        )
    ).order_by(Payment.created_at.desc()).limit(30).all()

    historial = []
    for p in pagos_raw:
        historial.append({
            "id":             p.id,
            "fecha":          p.created_at.strftime("%d %b %Y") if p.created_at else "",
            "concepto":       p.notes or "Pago",
            "monto":          float(p.amount),
            "metodo":         p.payment_method or "",
            "operacion":      p.operation_code or "",
            "estado":         p.status,
            "rechazo_motivo": p.rejection_reason or None,
        })

    
    # ── CUOTAS INFO (para tab Deudas de hábiles) ────────────────
    from datetime import date as dt_date

    hoy             = dt_date.today()
    anio_actual     = hoy.year
    mes_pagado      = getattr(colegiado, 'mes_pagado_hasta', 0)  or 0
    anio_pagado     = getattr(colegiado, 'anio_pagado_hasta', anio_actual) or anio_actual
    monto_cuota     = getattr(colegiado, 'monto_cuota_mensual', None)

    # Si no hay monto en el colegiado, buscarlo en conceptos
    if not monto_cuota:
        cuota_concepto = db.query(ConceptoCobro).filter(
            ConceptoCobro.organization_id == member.organization_id,
            ConceptoCobro.es_cuota_mensual == True,
            ConceptoCobro.activo == True,
        ).first()
        monto_cuota = float(cuota_concepto.monto_base) if cuota_concepto else 20.0

    # Si el año pagado es anterior al actual, resetear mes a 0
    if anio_pagado < anio_actual:
        mes_pagado = 0
        anio_pagado = anio_actual

    cuotas_pendientes = 12 - mes_pagado

    # Descuento por pronto pago
    if hoy.month <= 2:
        descuento_pct        = 0.20
        ultimo_dia_mes       = 28 if hoy.year % 4 != 0 else 29  # febrero
        descuento_valido_hasta = f"28 Feb {anio_actual}"
    elif hoy.month == 3:
        descuento_pct          = 0.10
        descuento_valido_hasta = f"31 Mar {anio_actual}"
    else:
        descuento_pct          = 0.00
        descuento_valido_hasta = None

    cuotas_info = {
        "mes_pagado_hasta":     mes_pagado,
        "anio_pagado_hasta":    anio_actual,
        "cuotas_pendientes":    cuotas_pendientes,
        "monto_cuota":          monto_cuota,
        "mes_inicio_pago":      mes_pagado + 1,
        "descuento_pct":        descuento_pct,
        "descuento_valido_hasta": descuento_valido_hasta,
    } if cuotas_pendientes > 0 else None
    
    
    return {
        "colegiado": {
            "id":        colegiado.id,
            "nombre":    colegiado.apellidos_nombres,
            "matricula": colegiado.codigo_matricula,
            "dni":       getattr(colegiado, 'dni', '') or '',
            "condicion": getattr(colegiado, 'condicion', 'habil') or 'habil',
            "es_habil":  (getattr(colegiado, 'condicion', '') or '').lower() == 'habil',
            "cuotas_info": cuotas_info,
        },
        "resumen": resumen,
        "deudas": deudas,
        "catalogo": catalogo,
        "categorias": categorias,
        "historial": historial,
    }
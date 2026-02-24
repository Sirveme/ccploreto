# app/services/lote_service.py

import json
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.models import Colegiado, Payment
from app.models_debt_management import Debt, Fraccionamiento


def crear_lote(db: Session, codigo: str, tipo: str, descripcion: str = None) -> dict:
    """Registra un nuevo lote antes de empezar operaciones."""
    from sqlalchemy import text
    db.execute(text("""
        INSERT INTO lotes_operacion (codigo, tipo, descripcion, estado)
        VALUES (:c, :t, :d, 'borrador')
    """), {"c": codigo, "t": tipo, "d": descripcion})
    db.commit()
    return {"codigo": codigo, "tipo": tipo}


def registrar_pago(
    db: Session,
    lote_codigo: str,
    colegiado_id: int,
    organization_id: int,
    amount: float,
    payment_method: str,
    related_debt_id: int = None,
    notes: str = None,
    operation_code: str = None,
) -> Payment:
    """Registra un pago vinculado a un lote (reversible)."""
    pago = Payment(
        organization_id=organization_id,
        colegiado_id=colegiado_id,
        amount=amount,
        currency='PEN',
        payment_method=payment_method,
        status='approved',
        related_debt_id=related_debt_id,
        notes=notes,
        operation_code=operation_code,
        lote_operacion=lote_codigo,   # ← trazabilidad
    )
    db.add(pago)

    # Si tiene deuda vinculada, actualizar su balance
    if related_debt_id:
        debt = db.query(Debt).get(related_debt_id)
        if debt:
            debt.balance = max(0, debt.balance - amount)
            if debt.balance == 0:
                debt.status = 'paid'

    db.commit()
    db.refresh(pago)
    return pago


def registrar_vitalicio(
    db: Session,
    lote_codigo: str,
    colegiado_id: int,
    motivo: str = "30+ años de colegiatura",
) -> dict:
    """
    Cambia condición a VITALICIO y guarda snapshot para rollback.
    """
    from sqlalchemy import text

    colegiado = db.query(Colegiado).get(colegiado_id)
    if not colegiado:
        return {"error": "Colegiado no encontrado"}

    condicion_antes = colegiado.condicion

    # Guardar snapshot en el lote
    lote = db.execute(
        text("SELECT snapshot_json FROM lotes_operacion WHERE codigo = :c"),
        {"c": lote_codigo}
    ).fetchone()

    snapshot = json.loads(lote[0]) if lote and lote[0] else []
    snapshot.append({
        "tabla": "colegiados",
        "id": colegiado_id,
        "campo": "condicion",
        "valor_antes": condicion_antes,
        "valor_despues": "vitalicio",
        "motivo": motivo,
        "ts": datetime.now(timezone.utc).isoformat(),
    })

    db.execute(text("""
        UPDATE lotes_operacion
        SET snapshot_json = :s
        WHERE codigo = :c
    """), {"s": json.dumps(snapshot), "c": lote_codigo})

    # Aplicar cambio
    colegiado.condicion = 'vitalicio'

    # Cancelar deudas de cuotas ordinarias futuras
    deudas_futuras = db.query(Debt).filter(
        Debt.colegiado_id == colegiado_id,
        Debt.debt_type == 'cuota_ordinaria',
        Debt.status == 'pending',
    ).all()
    hoy = datetime.now(timezone.utc).date()
    for d in deudas_futuras:
        if d.due_date and d.due_date.date() > hoy:
            snapshot.append({
                "tabla": "debts",
                "id": d.id,
                "campo": "estado_gestion",
                "valor_antes": d.estado_gestion,
                "valor_despues": "exonerada",
            })
            d.estado_gestion = 'exonerada'
            d.status = 'paid'

    db.commit()
    return {
        "colegiado_id": colegiado_id,
        "condicion_antes": condicion_antes,
        "condicion_nueva": "vitalicio",
        "deudas_futuras_canceladas": len(deudas_futuras),
    }


def condonar_multas(
    db: Session,
    lote_codigo: str,
    organization_id: int,
    colegiado_id: int = None,   # None = MASIVO
    motivo: str = "Condonación por acuerdo de asamblea",
) -> dict:
    """
    Condona multas. Si colegiado_id=None, aplica a TODOS.
    Reversible via rollback del lote.
    """
    from sqlalchemy import text
    from app.models_debt_management import DebtAction

    query = db.query(Debt).filter(
        Debt.organization_id == organization_id,
        Debt.debt_type == 'multa',
        Debt.status.in_(['pending', 'partial']),
        Debt.estado_gestion == 'vigente',
    )
    if colegiado_id:
        query = query.filter(Debt.colegiado_id == colegiado_id)

    multas = query.all()

    lote_q = db.execute(
        text("SELECT snapshot_json FROM lotes_operacion WHERE codigo = :c"),
        {"c": lote_codigo}
    ).fetchone()
    snapshot = json.loads(lote_q[0]) if lote_q and lote_q[0] else []

    total_condonado = 0
    for multa in multas:
        # Snapshot para rollback
        snapshot.append({
            "tabla": "debts",
            "id": multa.id,
            "campo": "estado_gestion",
            "valor_antes": multa.estado_gestion,
            "valor_despues": "condonada",
        })
        snapshot.append({
            "tabla": "debts",
            "id": multa.id,
            "campo": "status",
            "valor_antes": multa.status,
            "valor_despues": "paid",
        })

        total_condonado += multa.balance
        multa.estado_gestion = 'condonada'
        multa.status = 'paid'
        multa.balance = 0
        multa.lote_migracion = lote_codigo  # marcar para rollback

        # Acción de auditoría
        accion = DebtAction(
            debt_id=multa.id,
            tipo_accion='condonacion',
            descripcion=motivo,
            monto_ajuste=-multa.amount,
            created_by=None,
        )
        db.add(accion)

    db.execute(text("""
        UPDATE lotes_operacion SET snapshot_json = :s WHERE codigo = :c
    """), {"s": json.dumps(snapshot), "c": lote_codigo})

    db.commit()
    return {
        "multas_condonadas": len(multas),
        "monto_total_condonado": round(total_condonado, 2),
        "lote": lote_codigo,
    }


def sellar_para_produccion(db: Session, lote_codigo: str) -> dict:
    """
    Sella un lote como PRODUCCIÓN. Después de esto NO se puede revertir.
    Llamar solo cuando todo esté verificado y listo para operar.
    """
    from sqlalchemy import text
    db.execute(text("""
        UPDATE lotes_operacion
        SET estado = 'produccion', confirmado_at = :ts
        WHERE codigo = :c AND estado != 'revertido'
    """), {"c": lote_codigo, "ts": datetime.now(timezone.utc)})
    db.commit()
    return {"lote": lote_codigo, "estado": "produccion", "reversible": False}
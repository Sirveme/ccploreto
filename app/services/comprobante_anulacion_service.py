"""
Servicio: al anular un comprobante (boleta/factura), restaurar las deudas
que el pago vinculado había cubierto.

Fuente de verdad: marcador [DEBT_IDS:id1,id2,...] embebido en payment.notes
al momento del cobro (ver caja.py / secretaria.py).

Idempotente y seguro frente a cuotas de fraccionamiento (no las toca).
"""
import re
import logging
from typing import List, Tuple
from datetime import datetime

from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)

RE_DEBT_IDS = re.compile(r"\[DEBT_IDS:([\d,\s]+)\]")


def extraer_debt_ids_desde_notas(notas: str) -> List[int]:
    """
    Extrae IDs de deuda desde el campo notes de un payment.
    '[DEBT_IDS:63770]'              -> [63770]
    '[DEBT_IDS:50810,52966,55134]'  -> [50810, 52966, 55134]
    sin match                        -> []
    """
    if not notas:
        return []
    ids: List[int] = []
    for match in RE_DEBT_IDS.finditer(notas):
        bloque = match.group(1)
        for token in bloque.split(","):
            token = token.strip()
            if token.isdigit():
                ids.append(int(token))
    return list(dict.fromkeys(ids))  # dedup preservando orden


def restaurar_deudas_por_anulacion(
    db: Session,
    payment_id: int,
    user_id: int,
    comprobante_serie_numero: str,
) -> Tuple[List[int], List[int], List[str]]:
    """
    Restaura las deudas vinculadas al pago anulado.

    Retorna (ids_restauradas, ids_omitidas, mensajes):
    - ids_restauradas: deudas que pasaron a balance=amount, status='pending'
    - ids_omitidas: deudas que NO se tocaron (ya restauradas, no encontradas,
                    o cuotas de fraccionamiento ya pagadas)
    - mensajes: detalle por deuda para log/auditoría

    Idempotente: si las deudas ya están restauradas, no falla; las reporta
    como omitidas.

    Atómico: NO hace commit ni rollback; el caller maneja la transacción.
    """
    mensajes: List[str] = []
    ids_restauradas: List[int] = []
    ids_omitidas: List[int] = []

    row_payment = db.execute(text("""
        SELECT id, amount, status, notes
        FROM payments
        WHERE id = :pid
    """), {"pid": payment_id}).fetchone()

    if not row_payment:
        mensajes.append(f"Payment {payment_id} no existe")
        return [], [], mensajes

    debt_ids = extraer_debt_ids_desde_notas(row_payment.notes or "")
    if not debt_ids:
        mensajes.append(
            f"Payment {payment_id}: no se encontraron DEBT_IDS en notes. "
            f"No hay deudas que restaurar automáticamente."
        )
        return [], [], mensajes

    rows = db.execute(text("""
        SELECT id, amount, balance, status, concept, estado_gestion, debt_type
        FROM debts
        WHERE id = ANY(:ids)
    """), {"ids": debt_ids}).fetchall()

    deudas_por_id = {r.id: r for r in rows}

    nota_marcador = (
        f"[ANULACION-AUTO:user{user_id}] "
        f"{datetime.now().strftime('%d/%m/%Y %H:%M')} — "
        f"restauración automática por anulación de {comprobante_serie_numero}"
    )

    for did in debt_ids:
        d = deudas_por_id.get(did)
        if d is None:
            ids_omitidas.append(did)
            mensajes.append(f"Deuda {did}: NO EXISTE")
            continue

        # Cuota de fraccionamiento ya pagada: no restaurar (rompería el fracc)
        es_fracc = (
            (d.estado_gestion == "fraccionada")
            or (d.debt_type == "fraccionamiento")
        )
        if es_fracc and d.status == "paid":
            ids_omitidas.append(did)
            mensajes.append(
                f"Deuda {did} ({d.concept}): omitida — cuota de "
                f"fraccionamiento, no se restaura por anulación de "
                f"comprobante."
            )
            continue

        # Ya restaurada: balance >= amount
        if (
            d.balance is not None
            and d.amount is not None
            and d.balance >= d.amount
        ):
            ids_omitidas.append(did)
            mensajes.append(
                f"Deuda {did} ({d.concept}): omitida — balance ya está "
                f"en {d.balance} >= amount {d.amount}"
            )
            continue

        db.execute(text("""
            UPDATE debts
            SET balance = amount,
                status = 'pending',
                updated_at = NOW(),
                notes = COALESCE(notes,'') || E'\n' || :nota
            WHERE id = :did
        """), {"did": did, "nota": nota_marcador})

        ids_restauradas.append(did)
        mensajes.append(
            f"Deuda {did} ({d.concept}): "
            f"balance {d.balance} → {d.amount}, status → 'pending'"
        )

    return ids_restauradas, ids_omitidas, mensajes

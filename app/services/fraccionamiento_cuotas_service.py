"""
Servicio: generar/regenerar las filas espejo en `debts` para las cuotas
del cronograma de un fraccionamiento (cuota 0 inicial + cuotas 1..N).

Motivación (zClaude-84):
- Hasta zClaude-83 el modal de creación de fracc en /caja registraba el
  cronograma sólo en `fraccionamiento_cuotas`, sin las filas equivalentes
  en `debts`. Resultado: Sandra no podía cobrar la cuota inicial el mismo
  día, y el modal del plan mostraba "·sin enlace" por falta de la deuda
  real asociada.
- Este servicio genera esas filas en `debts` siguiendo el patrón existente
  (visto p.ej. en el fracc 124): debt_type='fraccionamiento',
  estado_gestion='fraccionada', notes='fracc_id:X cuota_id:Y num:N',
  con `due_date` real de la cuota (decisión zClaude-84).

Idempotencia:
- La función `generar_cuotas_fracc_en_debts` filtra previamente por las
  filas ya existentes en `debts` para el mismo `fraccionamiento_id`,
  reconociendo el número de cuota a partir de `notes` ('num:N').
- No existe UNIQUE en BD; la garantía es a nivel de código. Documentado
  aquí intencionalmente.
"""
import re
from datetime import date, datetime

from sqlalchemy.orm import Session
from sqlalchemy import text


_RE_NUM_CUOTA_EN_NOTES = re.compile(r"num:(\d+)")


def generar_cuotas_fracc_en_debts(
    db: Session,
    fraccionamiento_id: int,
    user_id: int | None = None,
    marcador_origen: str = "AUTO-zClaude-84",
) -> dict:
    """
    Crea filas en `debts` para cada cuota del cronograma del fracc.

    Idempotente: si ya existe una fila en `debts` para
    (fraccionamiento_id, num_cuota), se omite.

    Retorna:
    {
        "fraccionamiento_id": int,
        "creadas":  [{debt_id, num_cuota, monto}, ...],
        "omitidas": [num_cuota, ...],
        "errores":  [str, ...],
    }
    """
    fr = db.execute(text("""
        SELECT id, colegiado_id, organization_id, numero_solicitud,
               num_cuotas, cuota_inicial, monto_cuota, deuda_total_original,
               fecha_solicitud, created_at
        FROM fraccionamientos
        WHERE id = :fid
    """), {"fid": fraccionamiento_id}).fetchone()

    if not fr:
        return {
            "fraccionamiento_id": fraccionamiento_id,
            "creadas": [],
            "omitidas": [],
            "errores": ["Fraccionamiento no existe"],
        }

    cronograma = db.execute(text("""
        SELECT id, numero_cuota, monto, fecha_vencimiento
        FROM fraccionamiento_cuotas
        WHERE fraccionamiento_id = :fid
        ORDER BY numero_cuota
    """), {"fid": fraccionamiento_id}).fetchall()

    if not cronograma:
        return {
            "fraccionamiento_id": fraccionamiento_id,
            "creadas": [],
            "omitidas": [],
            "errores": ["Sin cronograma en fraccionamiento_cuotas"],
        }

    existentes = db.execute(text("""
        SELECT notes
        FROM debts
        WHERE fraccionamiento_id = :fid
          AND debt_type = 'fraccionamiento'
    """), {"fid": fraccionamiento_id}).fetchall()

    nums_existentes: set[int] = set()
    for row in existentes:
        m = _RE_NUM_CUOTA_EN_NOTES.search(row.notes or "")
        if m:
            nums_existentes.add(int(m.group(1)))

    creadas: list[dict] = []
    omitidas: list[int] = []
    periodo_label = (fr.fecha_solicitud or date.today()).strftime("%Y-%m")
    marcador_user = f":user{user_id}" if user_id else ""

    for c in cronograma:
        if c.numero_cuota in nums_existentes:
            omitidas.append(c.numero_cuota)
            continue

        concept = f"Cuota {c.numero_cuota} Fraccionamiento {fr.numero_solicitud}"
        notes_val = (
            f"fracc_id:{fr.id} cuota_id:{c.id} num:{c.numero_cuota}\n"
            f"[{marcador_origen}{marcador_user}] "
            f"{datetime.now().strftime('%d/%m/%Y %H:%M')} — generado automaticamente"
        )

        row = db.execute(text("""
            INSERT INTO debts (
                organization_id, colegiado_id, member_id,
                periodo, debt_type, concept,
                amount, balance, status,
                due_date, estado_gestion, fraccionamiento_id,
                notes, created_at, updated_at
            )
            VALUES (
                :org_id, :col_id, NULL,
                :periodo, 'fraccionamiento', :concept,
                :amount, :amount, 'pending',
                :due_date, 'fraccionada', :fid,
                :notes, NOW(), NOW()
            )
            RETURNING id
        """), {
            "org_id":   fr.organization_id,
            "col_id":   fr.colegiado_id,
            "periodo":  periodo_label,
            "concept":  concept,
            "amount":   c.monto,
            "due_date": c.fecha_vencimiento,
            "fid":      fr.id,
            "notes":    notes_val,
        }).fetchone()
        debt_id = row[0]
        creadas.append({
            "debt_id":   debt_id,
            "num_cuota": c.numero_cuota,
            "monto":     float(c.monto),
        })

    return {
        "fraccionamiento_id": fraccionamiento_id,
        "creadas":  creadas,
        "omitidas": omitidas,
        "errores":  [],
    }


def obtener_debt_id_cuota_inicial(
    db: Session, fraccionamiento_id: int
) -> int | None:
    """
    Devuelve el debt_id de la cuota 0 (inicial) de un fracc, si existe.
    """
    row = db.execute(text("""
        SELECT id
        FROM debts
        WHERE fraccionamiento_id = :fid
          AND debt_type = 'fraccionamiento'
          AND notes LIKE '%num:0%'
        LIMIT 1
    """), {"fid": fraccionamiento_id}).fetchone()
    return row.id if row else None

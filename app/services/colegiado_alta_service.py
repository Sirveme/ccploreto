"""
Alta rapida de Colegiado desde /caja (zClaude-78).

Solo crea el registro en `colegiados`. NO crea User, NO genera deudas.
El módulo formal de alta queda para un prompt posterior.
"""
from datetime import datetime, timezone, timedelta
from sqlalchemy import text
from sqlalchemy.orm import Session

PREFIJO_MATRICULA = "10-"   # Loreto
PERU_TZ = timezone(timedelta(hours=-5))


def calcular_siguiente_matricula(db: Session) -> str:
    """
    Devuelve la siguiente matrícula disponible con formato '10-NNNN'.
    No reserva; el llamador debe insertar con UNIQUE y reintentar si choca.
    Robusto frente a valores sin formato esperado (los descarta del MAX).
    """
    sql = text("""
        SELECT COALESCE(
            MAX(CAST(SUBSTRING(codigo_matricula FROM 4) AS INTEGER)),
            0
        ) AS max_num
        FROM colegiados
        WHERE codigo_matricula LIKE :prefijo
          AND SUBSTRING(codigo_matricula FROM 4) ~ '^[0-9]+$'
    """)
    row = db.execute(sql, {"prefijo": f"{PREFIJO_MATRICULA}%"}).fetchone()
    siguiente_num = (row.max_num or 0) + 1
    return f"{PREFIJO_MATRICULA}{siguiente_num:04d}"

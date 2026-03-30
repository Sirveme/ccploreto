"""
Servicio: Control de límites por operación y rol
app/services/limites_operacion.py

Uso en cualquier endpoint de caja:

    from app.services.limites_operacion import verificar_limite, OperacionPendiente

    resultado = verificar_limite(
        db       = db,
        org_id   = member.organization_id,
        operacion= 'anular_cobro',
        monto    = cobro.monto,
        rol      = member.role,
    )

    if resultado.requiere_aprobacion:
        # Guardar en cola y notificar
        raise HTTPException(403, detail=resultado.mensaje)
    # Si no, proceder normalmente
"""

from dataclasses import dataclass
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import text


@dataclass
class ResultadoLimite:
    permitido:            bool    # False = operación bloqueada totalmente
    requiere_aprobacion:  bool    # True  = guardar en cola
    aprobador:            str     # 'admin', 'director_finanzas', etc.
    limite_aplicado:      float   # El límite del rol actual
    mensaje:              str


# Mapa de roles a columna en la tabla
_COL_ROL = {
    "cajero":            "limite_cajero",
    "caja":              "limite_cajero",
    "admin":             "limite_admin",
    "administrador":     "limite_admin",
    "director_finanzas": "limite_finanzas",
    "finanzas":          "limite_finanzas",
    "superadmin":        "limite_finanzas",
    "decano":            "limite_finanzas",
}


def verificar_limite(
    db:        Session,
    org_id:    int,
    operacion: str,
    monto:     float,
    rol:       str,
) -> ResultadoLimite:
    """
    Verifica si el usuario con `rol` puede ejecutar `operacion` por `monto`.

    Retorna ResultadoLimite con la decisión.
    """
    col = _COL_ROL.get(rol.lower(), "limite_cajero")

    row = db.execute(text(f"""
        SELECT {col}          AS mi_limite,
               limite_finanzas,
               aprobador_siguiente,
               descripcion
        FROM   limites_operacion
        WHERE  organization_id = :org
          AND  operacion        = :op
          AND  activo           = true
        LIMIT 1
    """), {'org': org_id, 'op': operacion}).first()

    # Si no hay config → permitir con log (fail-open para no bloquear operaciones)
    if not row:
        return ResultadoLimite(
            permitido=True, requiere_aprobacion=False,
            aprobador='ninguno', limite_aplicado=-1,
            mensaje=f"Sin configuración para '{operacion}' — operación permitida."
        )

    limite = float(row.mi_limite)

    # -1 = sin límite → permitido siempre
    if limite == -1:
        return ResultadoLimite(
            permitido=True, requiere_aprobacion=False,
            aprobador='ninguno', limite_aplicado=-1,
            mensaje="Operación permitida sin restricción de monto."
        )

    # 0 = no permitido para este rol → siempre a cola de aprobación
    if limite == 0:
        return ResultadoLimite(
            permitido=False, requiere_aprobacion=True,
            aprobador=row.aprobador_siguiente,
            limite_aplicado=0,
            mensaje=(
                f"El rol '{rol}' no puede ejecutar '{row.descripcion or operacion}' "
                f"directamente. Se requiere aprobación de {row.aprobador_siguiente}."
            )
        )

    # Monto dentro del límite → permitido
    if monto <= limite:
        return ResultadoLimite(
            permitido=True, requiere_aprobacion=False,
            aprobador='ninguno', limite_aplicado=limite,
            mensaje=f"Operación dentro del límite permitido (S/ {limite:,.2f})."
        )

    # Monto supera el límite → a cola
    return ResultadoLimite(
        permitido=False, requiere_aprobacion=True,
        aprobador=row.aprobador_siguiente,
        limite_aplicado=limite,
        mensaje=(
            f"Monto S/ {monto:,.2f} supera el límite de S/ {limite:,.2f} "
            f"para el rol '{rol}'. Requiere aprobación de {row.aprobador_siguiente}."
        )
    )


def obtener_todos_limites(db: Session, org_id: int) -> list:
    """Retorna todos los límites configurados — para panel de admin."""
    rows = db.execute(text("""
        SELECT operacion, descripcion,
               limite_cajero, limite_admin, limite_finanzas,
               aprobador_siguiente, activo, base_legal
        FROM   limites_operacion
        WHERE  organization_id = :org
        ORDER  BY operacion
    """), {'org': org_id}).fetchall()
    return [dict(r._mapping) for r in rows]


def actualizar_limite(
    db:        Session,
    org_id:    int,
    operacion: str,
    campo:     str,   # 'limite_cajero', 'limite_admin', 'limite_finanzas'
    nuevo_valor: float,
    modificado_por: Optional[int] = None,
) -> bool:
    """
    Actualiza un límite específico.
    Registra el cambio con timestamp para auditoría ISO.
    """
    if campo not in ('limite_cajero', 'limite_admin', 'limite_finanzas'):
        return False

    db.execute(text(f"""
        UPDATE limites_operacion
        SET    {campo}   = :valor,
               updated_at = NOW()
        WHERE  organization_id = :org
          AND  operacion        = :op
    """), {'valor': nuevo_valor, 'org': org_id, 'op': operacion})
    db.commit()
    return True
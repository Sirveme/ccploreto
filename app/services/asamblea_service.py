"""
app/services/asamblea_service.py
================================
Lógica del módulo de asistencia a asamblea. Robusto para 3 mesas en paralelo:
el registro maneja el choque del índice único (asamblea_id, colegiado_id) con gracia.
"""
import re

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Colegiado
from app.models_asamblea import Asamblea, AsambleaAsistencia


def extraer_dni(raw):
    """Extrae los 8 dígitos del DNI de lo que llegue del lector (tolera formato extra)."""
    m = re.search(r"\d{8}", raw or "")
    return m.group(0) if m else None


def asamblea_abierta(db: Session, org_id: int):
    return (db.query(Asamblea)
            .filter(Asamblea.organization_id == org_id, Asamblea.estado == "abierta")
            .order_by(Asamblea.id.desc())
            .first())


def asamblea_actual(db: Session, org_id: int):
    """La asamblea abierta si existe; si no, la más reciente. Sirve para mostrar la mesa
    aunque el registro ya esté cerrado (con su estado), en vez de 'no hay asamblea'."""
    ab = asamblea_abierta(db, org_id)
    if ab:
        return ab
    return (db.query(Asamblea)
            .filter(Asamblea.organization_id == org_id)
            .order_by(Asamblea.id.desc())
            .first())


def get_asamblea(db: Session, org_id: int, asamblea_id: int):
    return (db.query(Asamblea)
            .filter(Asamblea.organization_id == org_id, Asamblea.id == asamblea_id)
            .first())


def buscar_colegiado(db: Session, org_id: int, q: str):
    """Busca por DNI (8 díg. extraídos), matrícula exacta o nombre/apellido (ilike)."""
    q = (q or "").strip()
    if not q:
        return []
    base = db.query(Colegiado).filter(Colegiado.organization_id == org_id)
    # 1) DNI exacto (del escaneo o tecleado)
    dni = extraer_dni(q)
    if dni:
        rows = base.filter(Colegiado.dni == dni).all()
        if rows:
            return rows
    # 2) Matrícula exacta
    rows = base.filter(func.upper(Colegiado.codigo_matricula) == q.upper()).all()
    if rows:
        return rows
    # 3) Nombre/apellido: todas las palabras deben aparecer
    filtro = base
    for palabra in [p for p in q.split() if p]:
        filtro = filtro.filter(Colegiado.apellidos_nombres.ilike("%" + palabra + "%"))
    return filtro.order_by(Colegiado.apellidos_nombres).limit(15).all()


def estado_registro(db: Session, asamblea_id: int, colegiado_id: int):
    """Devuelve la fila de asistencia si el colegiado ya está registrado, o None."""
    return (db.query(AsambleaAsistencia)
            .filter_by(asamblea_id=asamblea_id, colegiado_id=colegiado_id)
            .first())


def total_asistentes(db: Session, asamblea_id: int) -> int:
    """Cuenta TODOS los registros de la asamblea (las 3 mesas juntas, sin filtrar operador)."""
    return int(db.query(func.count(AsambleaAsistencia.id))
               .filter(AsambleaAsistencia.asamblea_id == asamblea_id).scalar() or 0)


def registrar(db: Session, org_id: int, asamblea_id: int, colegiado_id: int,
              member_id, foto_url=None):
    """Registra asistencia. Anti-duplicado a prueba de concurrencia:
    - Si ya está → 'duplicado' con la hora previa.
    - Si dos mesas escanean casi a la vez, el índice único hace fallar al segundo INSERT;
      se captura, se hace rollback y se devuelve 'duplicado' con la hora del ganador.
    Devuelve {status, hora, total}."""
    existing = estado_registro(db, asamblea_id, colegiado_id)
    if existing:
        return {"status": "duplicado", "hora": existing.hora_registro,
                "total": total_asistentes(db, asamblea_id)}

    row = AsambleaAsistencia(
        organization_id=org_id, asamblea_id=asamblea_id, colegiado_id=colegiado_id,
        registrado_por=member_id, foto_url=foto_url,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = estado_registro(db, asamblea_id, colegiado_id)
        return {"status": "duplicado",
                "hora": existing.hora_registro if existing else None,
                "total": total_asistentes(db, asamblea_id)}
    db.refresh(row)
    return {"status": "ok", "hora": row.hora_registro,
            "total": total_asistentes(db, asamblea_id)}


def lista_publica(db: Session, asamblea_id: int):
    """Lista pública: SOLO nombre + matrícula (nunca DNI/foto/condición). Alfabética."""
    rows = (db.query(Colegiado.apellidos_nombres, Colegiado.codigo_matricula)
            .join(AsambleaAsistencia, AsambleaAsistencia.colegiado_id == Colegiado.id)
            .filter(AsambleaAsistencia.asamblea_id == asamblea_id)
            .order_by(Colegiado.apellidos_nombres)
            .all())
    return [{"nombre": r[0], "matricula": r[1]} for r in rows]


def filas_export(db: Session, asamblea_id: int):
    """Filas para el Excel interno: nombre, matrícula, condición, hora."""
    return (db.query(Colegiado.apellidos_nombres, Colegiado.codigo_matricula,
                     Colegiado.condicion, AsambleaAsistencia.hora_registro)
            .join(AsambleaAsistencia, AsambleaAsistencia.colegiado_id == Colegiado.id)
            .filter(AsambleaAsistencia.asamblea_id == asamblea_id)
            .order_by(AsambleaAsistencia.hora_registro)
            .all())

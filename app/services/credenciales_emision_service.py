"""
app/services/credenciales_emision_service.py
=============================================
Parte 3 — Emisión controlada de carnés CCPL.

Reglas:
  - Un solo carné VIGENTE por colegiado (respaldado por uq_issuance_colegiado_vigente):
    al emitir, la vigente anterior pasa a 'reemplazada' ANTES de insertar la nueva.
  - Token = codigo_verificacion (UUID). N° de copia = version (max+1).
  - Un pago (payment_id) respalda a lo sumo UNA emisión: "disponible" = payment_id
    NO referenciado por NINGUNA issuance (vigente o reemplazada). Reforzado por
    uq_issuance_payment (índice único parcial).
  - Emitir descuenta stock (movimiento 'emision'); DESECHO descuenta stock SIN
    consumir el derecho ni crear issuance.

Las funciones hacen FLUSH, NO commit — el llamador (router) decide commit/rollback
(así el dry-run puede ejecutar todo y hacer rollback sin ensuciar producción).
"""
import re
import json
import base64
import uuid
import logging

from sqlalchemy import func, text, bindparam
from sqlalchemy.orm import Session

from app.models_credenciales import (
    CredentialIssuance, CredentialGratuidadRegla,
)
from app.services.credencial_reportlab import generar_credencial_pdf

logger = logging.getLogger(__name__)

CARNE_CODIGO = "MERC-3251"   # concepto "CARNET COLEGIADO" (mercadería, no genera deuda)


# ── Elegibilidad (resolver_derecho) — compartido con la Parte 4 (listas) ──
def _der_col_pagado(db: Session, org_id: int, colegiado_id: int) -> bool:
    return db.execute(text("""
        SELECT 1 FROM debts d
        JOIN conceptos_cobro cc ON cc.id = d.concepto_cobro_id
        WHERE d.organization_id = :org AND d.colegiado_id = :cid
          AND cc.codigo = 'DER-COL' AND d.status = 'paid'
        LIMIT 1
    """), {"org": org_id, "cid": colegiado_id}).first() is not None


def _es_gratuito_por_condicion(db: Session, org_id: int, colegiado) -> bool:
    cond = (getattr(colegiado, "condicion", "") or "").lower()
    reglas = db.query(CredentialGratuidadRegla).filter_by(
        organization_id=org_id, activo=True).all()
    for r in reglas:
        if r.tipo == "condicion" and cond == (r.valor or "").lower():
            return True
        if r.tipo == "colegiado" and str(colegiado.id) == str(r.valor):
            return True
    return False


def _pagos_carne_disponibles(db: Session, org_id: int, colegiado_id: int):
    """IDs de payments (aprobados) del colegiado con el concepto carné (MERC-3251,
    decodificando CONCEPTOS_B64) que NO están referenciados por NINGUNA issuance."""
    rows = db.execute(text("""
        SELECT p.id, p.notes
        FROM payments p
        WHERE p.organization_id = :org AND p.colegiado_id = :cid
          AND p.status = 'approved'
          AND p.notes LIKE '%[CONCEPTOS_B64:%'
        ORDER BY p.created_at
    """), {"org": org_id, "cid": colegiado_id}).mappings().all()

    usados = {row[0] for row in db.execute(text(
        "SELECT payment_id FROM credential_issuances WHERE payment_id IS NOT NULL"
    )).all()}

    disponibles = []
    for r in rows:
        if r["id"] in usados:
            continue
        m = re.search(r"\[CONCEPTOS_B64:([A-Za-z0-9+/=]+)\]", r["notes"] or "")
        if not m:
            continue
        try:
            arr = json.loads(base64.b64decode(m.group(1)).decode("utf-8"))
        except Exception:
            continue
        if any((it.get("codigo") or "") == CARNE_CODIGO for it in arr):
            disponibles.append(r["id"])
    return disponibles


def resolver_derecho(db: Session, org_id: int, colegiado):
    """Devuelve {'origen_derecho', 'payment_id', 'reposicion'} o None si sin derecho.
    Prioridad: gratuidad por condición → carné pagado → nuevo (DER-COL pagado)."""
    vigente = db.query(CredentialIssuance).filter_by(
        colegiado_id=colegiado.id, estado="vigente").first()

    if _es_gratuito_por_condicion(db, org_id, colegiado):
        return {"origen_derecho": "condicion_gratuita", "payment_id": None,
                "reposicion": bool(vigente)}

    pagos = _pagos_carne_disponibles(db, org_id, colegiado.id)
    if pagos:
        return {"origen_derecho": ("reposicion" if vigente else "carne_pagado"),
                "payment_id": pagos[0], "reposicion": bool(vigente)}

    if not vigente and _der_col_pagado(db, org_id, colegiado.id):
        return {"origen_derecho": "nuevo_gratuito", "payment_id": None,
                "reposicion": False}

    return None


# ── Stock ────────────────────────────────────────────────────────────────
def stock_actual(db: Session, org_id: int) -> int:
    disp = db.execute(text(
        "SELECT disponibles FROM credential_stock WHERE organization_id = :org"
    ), {"org": org_id}).scalar()
    return int(disp or 0)


def _lock_stock(db: Session, org_id: int):
    """Bloquea la fila de stock (FOR UPDATE) y devuelve disponibles (o None)."""
    return db.execute(text(
        "SELECT disponibles FROM credential_stock WHERE organization_id = :org FOR UPDATE"
    ), {"org": org_id}).scalar()


def ingreso_stock(db: Session, org_id: int, usuario_id, cantidad: int, motivo=None) -> int:
    if cantidad <= 0:
        raise ValueError("La cantidad debe ser mayor a 0.")
    db.execute(text("""
        INSERT INTO credential_stock (organization_id, disponibles)
        VALUES (:org, :c)
        ON CONFLICT (organization_id)
        DO UPDATE SET disponibles = credential_stock.disponibles + :c, updated_at = now()
    """), {"org": org_id, "c": cantidad})
    db.execute(text("""
        INSERT INTO credential_stock_movimientos (organization_id, tipo, cantidad, motivo, usuario_id)
        VALUES (:org, 'ingreso', :c, :m, :uid)
    """), {"org": org_id, "c": cantidad, "m": motivo, "uid": usuario_id})
    db.flush()
    return stock_actual(db, org_id)


def desechar(db: Session, org_id: int, usuario_id, motivo=None, issuance_id=None) -> int:
    """Carné en blanco arruinado: descuenta stock, NO consume derecho ni crea issuance."""
    disp = _lock_stock(db, org_id)
    if disp is None or disp <= 0:
        raise ValueError("Sin stock de carnés en blanco.")
    db.execute(text(
        "UPDATE credential_stock SET disponibles = disponibles - 1, updated_at = now() WHERE organization_id = :org"
    ), {"org": org_id})
    db.execute(text("""
        INSERT INTO credential_stock_movimientos (organization_id, tipo, cantidad, motivo, issuance_id, usuario_id)
        VALUES (:org, 'desecho', -1, :m, :iid, :uid)
    """), {"org": org_id, "m": motivo, "iid": issuance_id, "uid": usuario_id})
    db.flush()
    return stock_actual(db, org_id)


# ── Emisión ──────────────────────────────────────────────────────────────
def emitir(db: Session, org, tpl, colegiado, usuario_id):
    """Emite el carné del colegiado. FLUSH (no commit). Devuelve (issuance, pdf_bytes).
    Orden: resolver derecho → bloquear stock → PDF (parte frágil) → escrituras atómicas."""
    derecho = resolver_derecho(db, org.id, colegiado)
    if not derecho:
        raise ValueError("El colegiado no tiene derecho a emisión (sin pago de carné, "
                         "sin DER-COL pagado y sin condición gratuita).")

    disp = _lock_stock(db, org.id)
    if disp is None or disp <= 0:
        raise ValueError("Sin stock de carnés en blanco.")

    token = str(uuid.uuid4())
    max_v = db.query(func.coalesce(func.max(CredentialIssuance.version), 0)).filter_by(
        colegiado_id=colegiado.id).scalar()
    version = int(max_v or 0) + 1

    # PDF ANTES de tocar la BD: si falla, no se descuenta stock ni se crea issuance.
    pdf = generar_credencial_pdf(colegiado, org, tpl, token=token)

    # 1) Marcar la vigente anterior como 'reemplazada' (antes de insertar la nueva)
    db.query(CredentialIssuance).filter_by(
        colegiado_id=colegiado.id, estado="vigente").update({"estado": "reemplazada"})

    # 2) Insertar la nueva emisión vigente
    iss = CredentialIssuance(
        organization_id=org.id,
        template_id=tpl.id,
        colegiado_id=colegiado.id,
        version=version,
        tipo_emision=("REPOSICION" if derecho["reposicion"] else "ORIGINAL"),
        codigo_verificacion=token,
        estado="vigente",
        origen_derecho=derecho["origen_derecho"],
        payment_id=derecho["payment_id"],
        usuario_id=usuario_id,
    )
    db.add(iss)
    db.flush()   # obtiene iss.id

    # 3) Descontar stock + movimiento
    db.execute(text(
        "UPDATE credential_stock SET disponibles = disponibles - 1, updated_at = now() WHERE organization_id = :org"
    ), {"org": org.id})
    db.execute(text("""
        INSERT INTO credential_stock_movimientos (organization_id, tipo, cantidad, issuance_id, usuario_id)
        VALUES (:org, 'emision', -1, :iid, :uid)
    """), {"org": org.id, "iid": iss.id, "uid": usuario_id})
    db.flush()

    return iss, pdf


# ── Listas del panel (Parte 4) — mismos criterios que resolver_derecho ────
def _rows_nuevos(db: Session, org_id: int):
    """DER-COL pagado y SIN emisión vigente (primer carné gratis)."""
    return db.execute(text("""
        SELECT c.id, c.codigo_matricula, c.apellidos_nombres
        FROM colegiados c
        JOIN debts d ON d.colegiado_id = c.id
        JOIN conceptos_cobro cc ON cc.id = d.concepto_cobro_id AND cc.codigo = 'DER-COL'
        WHERE c.organization_id = :org AND d.status = 'paid'
          AND NOT EXISTS (SELECT 1 FROM credential_issuances i
                          WHERE i.colegiado_id = c.id AND i.estado = 'vigente')
        GROUP BY c.id, c.codigo_matricula, c.apellidos_nombres
        ORDER BY c.apellidos_nombres
    """), {"org": org_id}).mappings().all()


def _rows_antiguos(db: Session, org_id: int):
    """Pago de carné (MERC-3251, decodificando CONCEPTOS_B64) NO consumido por
    ninguna issuance. Incluye reposiciones (pago nuevo aunque tenga vigente)."""
    return db.execute(text(r"""
        SELECT c.id, c.codigo_matricula, c.apellidos_nombres,
               MIN(p.id) AS payment_id,
               MIN(cp.serie || '-' || lpad(cp.numero::text, 8, '0')) AS comprobante
        FROM payments p
        JOIN colegiados c ON c.id = p.colegiado_id
        LEFT JOIN comprobantes cp ON cp.payment_id = p.id
        WHERE p.organization_id = :org AND p.status = 'approved'
          AND p.notes ~ '\[CONCEPTOS_B64:[A-Za-z0-9+/=]+\]'
          AND EXISTS (
              SELECT 1 FROM jsonb_array_elements(
                  convert_from(decode(substring(p.notes from '\[CONCEPTOS_B64:([A-Za-z0-9+/=]+)\]'), 'base64'), 'UTF8')::jsonb
              ) e WHERE e->>'codigo' = :cod
          )
          AND p.id NOT IN (SELECT payment_id FROM credential_issuances WHERE payment_id IS NOT NULL)
        GROUP BY c.id, c.codigo_matricula, c.apellidos_nombres
        ORDER BY c.apellidos_nombres
    """), {"org": org_id, "cod": CARNE_CODIGO}).mappings().all()


def _rows_gratuitos(db: Session, org_id: int):
    """Gratuidad por condición (regla tipo='condicion') o por colegiado (tipo='colegiado'),
    SIN emisión vigente."""
    reglas = db.query(CredentialGratuidadRegla).filter_by(organization_id=org_id, activo=True).all()
    conds = [(r.valor or "").lower() for r in reglas if r.tipo == "condicion" and r.valor]
    ids = [int(r.valor) for r in reglas if r.tipo == "colegiado" and str(r.valor).isdigit()]
    if not conds and not ids:
        return []
    stmt = text("""
        SELECT c.id, c.codigo_matricula, c.apellidos_nombres, c.condicion
        FROM colegiados c
        WHERE c.organization_id = :org
          AND (lower(c.condicion) IN :conds OR c.id IN :ids)
          AND NOT EXISTS (SELECT 1 FROM credential_issuances i
                          WHERE i.colegiado_id = c.id AND i.estado = 'vigente')
        ORDER BY c.apellidos_nombres
    """).bindparams(bindparam("conds", expanding=True), bindparam("ids", expanding=True))
    return db.execute(stmt, {"org": org_id, "conds": conds or [""], "ids": ids or [0]}).mappings().all()


def listas_panel(db: Session, org_id: int):
    """Las 3 listas para el panel, dedup por prioridad: gratuito > antiguo > nuevo
    (igual que resolver_derecho). Cada colegiado aparece en UNA sola lista."""
    gratuitos = [{"id": r["id"], "matricula": r["codigo_matricula"], "nombre": r["apellidos_nombres"],
                  "detalle": (r["condicion"] or "").upper()}
                 for r in _rows_gratuitos(db, org_id)]
    vistos = {g["id"] for g in gratuitos}

    antiguos = []
    for r in _rows_antiguos(db, org_id):
        if r["id"] in vistos:
            continue
        vistos.add(r["id"])
        antiguos.append({"id": r["id"], "matricula": r["codigo_matricula"], "nombre": r["apellidos_nombres"],
                         "detalle": r["comprobante"] or ("Pago #%s" % r["payment_id"])})

    nuevos = []
    for r in _rows_nuevos(db, org_id):
        if r["id"] in vistos:
            continue
        vistos.add(r["id"])
        nuevos.append({"id": r["id"], "matricula": r["codigo_matricula"], "nombre": r["apellidos_nombres"],
                       "detalle": "Derecho de Colegiatura pagado"})

    return {"nuevos": nuevos, "antiguos": antiguos, "gratuitos": gratuitos}

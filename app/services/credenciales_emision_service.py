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
import os
import re
import json
import base64
import uuid
import secrets
import logging
from datetime import datetime, timedelta

from sqlalchemy import func, text, bindparam
from sqlalchemy.orm import Session

from app.models_credenciales import (
    CredentialIssuance, CredentialGratuidadRegla, CredentialShareToken,
)
from app.services.credencial_reportlab import (
    generar_credencial_pdf, split_nombre,
    DEFAULT_LAYOUT, _DIR_FONDOS, _DIR_LOGOS,
)

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


# ── Validación de emisión (gate a prueba de errores — Entrega 1) ──
_RE_DNI = re.compile(r"^\d{8}$")
# Formato de matrícula del Colegio: 10- + 3 a 5 dígitos + sufijo de letra opcional.
# El sufijo cubre matrículas históricas de los inicios (10-0136A, 10-0137A).
_RE_MATRICULA = re.compile(r"^10-\d{3,5}[A-Z]?$")


def _layout_de(tpl):
    """Layout efectivo de la plantilla (JSONB) o el DEFAULT."""
    lay = getattr(tpl, "layout", None)
    if not lay and isinstance(tpl, dict):
        lay = tpl.get("layout")
    return lay or DEFAULT_LAYOUT


def _tpl_attr(tpl, name):
    if isinstance(tpl, dict):
        return tpl.get(name)
    return getattr(tpl, name, None)


def validar_emision(tpl, colegiado):
    """Campos mínimos para poder IMPRIMIR. Dos niveles:
      - faltan_colegiado: bloquean ESE carné (datos del colegiado).
      - faltan_plantilla: bloquean TODOS los carnés (recursos de la plantilla/ORG).
    Devuelve {"faltan_colegiado": [...], "faltan_plantilla": [...]}.
    Se usa en el front (deshabilitar IMPRIMIR) Y como gate server-side en /emitir."""
    fc, ft = [], []

    # ── Nivel COLEGIADO ──
    if not (getattr(colegiado, "foto_url", None) or "").strip():
        fc.append("Foto del colegiado")

    apellidos, nombres = split_nombre(getattr(colegiado, "apellidos_nombres", None))
    ap_parts = apellidos.split()
    if not ap_parts:
        fc.append("Apellido paterno")
        fc.append("Apellido materno")
    elif len(ap_parts) < 2:
        fc.append("Apellido materno")
    if not (nombres or "").strip():
        fc.append("Nombre(s)")

    if not _RE_DNI.match((getattr(colegiado, "dni", None) or "").strip()):
        fc.append("DNI válido (8 dígitos)")

    if not _RE_MATRICULA.match((getattr(colegiado, "codigo_matricula", None) or "").strip()):
        fc.append("Matrícula (formato 10-XXXX)")

    if not getattr(colegiado, "fecha_colegiatura", None):
        fc.append("Fecha de incorporación")

    # ── Nivel PLANTILLA / ORG ──
    layout = _layout_de(tpl)

    tiene_qr = any(
        isinstance(el, dict) and el.get("tipo") == "qr"
        for cara in layout.values() if isinstance(cara, dict)
        for el in cara.values()
    )
    if not tiene_qr:
        ft.append("QR de verificación en el diseño")

    def _fondo_ok(cara_key, url_attr):
        cara = layout.get(cara_key, {}) if isinstance(layout, dict) else {}
        el = cara.get("fondo") if isinstance(cara, dict) else None
        src = el.get("src") if isinstance(el, dict) else None
        if src and os.path.exists(os.path.join(_DIR_FONDOS, src)):
            return True
        return bool(_tpl_attr(tpl, url_attr))

    if not _fondo_ok("frente", "fondo_frente_url"):
        ft.append("Imagen de fondo del anverso")
    if not _fondo_ok("reverso", "fondo_reverso_url"):
        ft.append("Imagen de fondo del reverso")

    if not os.path.exists(os.path.join(_DIR_LOGOS, "logo_ccpl.png")):
        ft.append("Logo del CCPL")
    if not os.path.exists(os.path.join(_DIR_LOGOS, "logo_junta.png")):
        ft.append("Logo de la Junta de Decanos")

    return {"faltan_colegiado": fc, "faltan_plantilla": ft}


# ── Compartir preview por enlace temporal (Entrega 2) ──
SHARE_TTL_HORAS = 24   # caducidad corta; el token es revocable (flag) por si hay que cortarlo antes.


def crear_share_token(db: Session, org_id: int, colegiado_id: int, member_id, horas: int = SHARE_TTL_HORAS) -> str:
    """Crea un token aleatorio no adivinable con caducidad. FLUSH (el router commitea)."""
    tok = secrets.token_urlsafe(24)   # ~32 chars, [A-Za-z0-9_-]
    row = CredentialShareToken(
        token=tok,
        colegiado_id=colegiado_id,
        organization_id=org_id,
        creado_por=member_id,
        expires_at=datetime.utcnow() + timedelta(hours=horas),
    )
    db.add(row)
    db.flush()
    return tok


def resolver_share_token(db: Session, token: str):
    """Devuelve colegiado_id si el token es válido (existe, no revocado, no vencido); si no, None."""
    if not token:
        return None
    row = db.query(CredentialShareToken).filter(CredentialShareToken.token == token).first()
    if not row or row.revocado:
        return None
    if row.expires_at and row.expires_at < datetime.utcnow():
        return None
    return row.colegiado_id

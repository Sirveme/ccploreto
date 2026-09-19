"""
app/routers/pagos_externos.py
Módulo Pagos Externos — Fase 1.

CAPTURA (Anggie, /caja — roles cajero+admin+sote):
  GET  /caja/pago-externo                       -> página HTML (stepper de captura)
  GET  /api/pagos-externos/buscar-colegiado     -> busca por DNI/matrícula/nombre
  GET  /api/pagos-externos/deudas/{colegiado_id}-> deudas exigibles del colegiado
  POST /api/pagos-externos/analizar             -> PREVIEW read-only + CANDADO (sin commit)
  POST /api/pagos-externos/solicitar            -> crea solicitud pendiente (NO crea Payment)

RESOLUCIÓN (admin, /admin/pagos-externos — roles admin+sote): sub-paso 3.
La captura NO ejecuta: crea solicitud_pago_externo estado='pendiente'. El admin ejecuta.
"""
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import or_, func, text
from pydantic import BaseModel

from app.database import get_db
from app.models import Colegiado, Member
from app.models_debt_management import Debt
from app.utils.deuda_fracc_filtro import excluir_absorbidas_por_fracc_activo
from app.routers.dashboard import get_current_member
from app.utils.templates import templates
from app.services import pagos_externos_service as pex
from app.services import pago_externo_service as pxw

# CAPTURA (Anggie, /caja): cajero + admin + sote.
# RESOLUCIÓN — ver/rechazar (admin + sote; sote es soporte, puede ver/rechazar).
# EJECUTAR DINERO (resolver/nc/devolución): admin + tesorero — SOTE JAMÁS firma dinero.
# FIRMA 2 (doble firma): admin + tesorero + decano — nunca sote.
ROLES_CAPTURA = ("cajero", "admin", "sote")
ROLES_RESOLUCION = ("admin", "sote")
ROLES_DINERO = ("admin", "tesorero")
ROLES_FIRMA2 = ("admin", "tesorero", "decano")
ORG_CCPL = 1

router = APIRouter(prefix="/api/pagos-externos", tags=["PagosExternos"])
page_router = APIRouter(tags=["PagosExternos"])


def require_captura(current_member: Member = Depends(get_current_member)):
    if current_member.role not in ROLES_CAPTURA:
        raise HTTPException(status_code=403, detail="Acceso restringido (cajero/admin/sote)")
    return current_member


def require_resolucion(current_member: Member = Depends(get_current_member)):
    if current_member.role not in ROLES_RESOLUCION:
        raise HTTPException(status_code=403, detail="Acceso restringido (admin/sote)")
    return current_member


def require_dinero(current_member: Member = Depends(get_current_member)):
    """Ejecuta movimientos de dinero. SOTE excluido (soporte, no autoriza dinero)."""
    if current_member.role not in ROLES_DINERO:
        raise HTTPException(status_code=403, detail="Solo admin/tesorero ejecutan dinero (SOTE no)")
    return current_member


def require_firma2(current_member: Member = Depends(get_current_member)):
    if current_member.role not in ROLES_FIRMA2:
        raise HTTPException(status_code=403, detail="Segunda firma: admin/tesorero/decano (SOTE no)")
    return current_member


def _get_autorizacion(db, aut_id):
    from app.models import SolicitudAutorizacion
    sa = db.query(SolicitudAutorizacion).filter(
        SolicitudAutorizacion.id == aut_id,
        SolicitudAutorizacion.organization_id == ORG_CCPL,
    ).first()
    if not sa:
        raise HTTPException(404, detail="Autorización no encontrada")
    return sa


def _ref_desde_motor(db, sol, desenlace):
    """Deriva server-side el comprobante a revertir (para NC/devolución) desde el motor,
    para que el frontend NO pase refs sensibles."""
    prop = pex.analizar_conciliacion(db, sol, organization_id=ORG_CCPL)
    r0 = (prop.get("resultados") or [{}])[0]
    rev = r0.get("revertir") or {}
    if desenlace == "NOTA_CREDITO":
        pid = rev.get("payment_id")
        monto_rev = round(float(rev.get("monto") or 0), 2)
        # NC parcial si el pago cubre MÁS que este monto (p.ej. pago mixto S/360, NC S/180).
        es_parcial = False
        if pid:
            pago_total = db.execute(text("SELECT amount FROM payments WHERE id = :p"),
                                    {"p": pid}).scalar()
            es_parcial = bool(pago_total is not None and round(float(pago_total), 2) > monto_rev + 0.01)
        return {"anular_ref": {"payment_id": pid, "comprobante": rev.get("comprobante"),
                               "monto": monto_rev, "es_parcial": es_parcial, "motivo_sunat": "01"}}
    if desenlace == "DEVOLUCION":
        return {"devolucion_ref": {"es_externo_eb01": bool(rev.get("es_externo_eb01", True)),
                                   "comprobante": rev.get("comprobante"),
                                   "monto": rev.get("monto")}}
    return {}


def _get_solicitud_pendiente(db, solicitud_id):
    from app.models import SolicitudPagoExterno
    sol = db.query(SolicitudPagoExterno).filter(
        SolicitudPagoExterno.id == solicitud_id,
        SolicitudPagoExterno.organization_id == ORG_CCPL,
    ).first()
    if not sol:
        raise HTTPException(404, detail="Solicitud no encontrada")
    return sol


# ── SCHEMAS ────────────────────────────────────────────────────────────────────
class ImputacionIn(BaseModel):
    debt_id: int
    monto: Optional[float] = None


class AnalizarIn(BaseModel):
    colegiado_id: int
    tipo: int                      # 1=EB01 pasado, 2=comunicado, 3=EB01 contingencia hoy
    serie: Optional[str] = None
    numero: Optional[int] = None
    fecha_comprobante: Optional[str] = None
    monto: float
    metodo_pago: Optional[str] = None
    nro_operacion: Optional[str] = None
    fecha_pago: Optional[str] = None
    concepto: Optional[str] = None
    imputaciones: List[ImputacionIn] = []


# ── PÁGINA DE CAPTURA (Anggie, desde /caja) ──────────────────────────────────────
@page_router.get("/caja/pago-externo", response_class=HTMLResponse)
async def pagina_captura_pago_externo(
    request: Request,
    current_member: Member = Depends(require_captura),
):
    return templates.TemplateResponse("pages/pago_externo_captura.html", {
        "request": request,
        "user_role": current_member.role,
        "tipos": pex.TIPOS_PAGO_EXTERNO,
    })


# ── BÚSQUEDA DE COLEGIADO ────────────────────────────────────────────────────────
@router.get("/buscar-colegiado")
async def buscar_colegiado(
    q: str = Query(..., min_length=2, description="DNI, matrícula o nombre"),
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_captura),
):
    q = q.strip()
    query = db.query(Colegiado)
    if q.isdigit() and len(q) >= 7:
        query = query.filter(Colegiado.dni == q)
    elif "-" in q:
        query = query.filter(Colegiado.codigo_matricula == q)
    else:
        query = query.filter(or_(
            Colegiado.apellidos_nombres.ilike(f"%{q}%"),
            Colegiado.dni.contains(q),
            Colegiado.codigo_matricula.contains(q),
        ))
    resultados = []
    for col in query.limit(20).all():
        resultados.append({
            "id": col.id,
            "dni": col.dni or "",
            "codigo_matricula": col.codigo_matricula or "",
            "apellidos_nombres": col.apellidos_nombres or "",
            "condicion": col.condicion,
        })
    return resultados


# ── DEUDAS EXIGIBLES ─────────────────────────────────────────────────────────────
@router.get("/deudas/{colegiado_id}")
async def obtener_deudas(
    colegiado_id: int,
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_captura),
):
    colegiado = db.query(Colegiado).filter(Colegiado.id == colegiado_id).first()
    if not colegiado:
        raise HTTPException(404, detail="Colegiado no encontrado")

    deudas = db.query(Debt).filter(
        Debt.colegiado_id == colegiado_id,
        Debt.status.in_(["pending", "partial"]),
        excluir_absorbidas_por_fracc_activo(),   # evita doble conteo por fracc activo
    ).order_by(Debt.periodo.asc()).all()

    resultado = []
    for d in deudas:
        resultado.append({
            "id": d.id,
            "concept": d.concept or "Cuota",
            "period_label": d.period_label or (str(d.periodo) if d.periodo else ""),
            "periodo": str(d.periodo) if d.periodo else "",
            "amount": float(d.amount or 0),
            "saldo": float(d.balance or 0),
            "status": d.status,
            "debt_type": d.debt_type or "cuota_ordinaria",
            "estado_notificacion": d.estado_notificacion or "no_notificada",
            "exigible": (d.estado_notificacion or "no_notificada") != "no_notificada",
        })

    return {
        "colegiado": {
            "id": colegiado.id,
            "dni": colegiado.dni,
            "codigo_matricula": colegiado.codigo_matricula,
            "apellidos_nombres": colegiado.apellidos_nombres,
            "condicion": colegiado.condicion,
        },
        "deudas": resultado,
        "total_saldo": round(sum(d["saldo"] for d in resultado), 2),
    }


# ── ANÁLISIS / PREVIEW (READ-ONLY, sin commit) ───────────────────────────────────
@router.post("/analizar")
async def analizar(
    datos: AnalizarIn,
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_captura),
):
    """PREVIEW read-only del pago externo + CANDADO anti-duplicado. NO escribe nada."""
    payload = datos.model_dump()
    payload["imputaciones"] = [i for i in payload.get("imputaciones", [])]
    return pex.analizar_pago_externo(db, payload, organization_id=1)


# ── FASE 3: AVISO AL COBRAR (read-only, separado del cobro — nunca lo rompe) ──────
@page_router.get("/caja/avisos-externos/{colegiado_id}")
async def avisos_externos_caja(
    colegiado_id: int,
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_captura),
):
    """Devuelve {debt_id: aviso} para las deudas pendientes del colegiado que tengan
    un pago externo (solicitud pendiente o Payment externo registrado). SOLO informa;
    vive aparte de /caja/deudas para que un fallo aquí NO afecte el cobro."""
    ids = [r[0] for r in db.query(Debt.id).filter(
        Debt.colegiado_id == colegiado_id,
        Debt.status.in_(["pending", "partial"]),
    ).all()]
    return pex.avisos_pago_externo(db, ids, organization_id=ORG_CCPL)


# ── SOLICITAR (CAPTURA — crea solicitud pendiente; NO crea Payment) ──────────────
@router.post("/solicitar")
async def solicitar(
    datos: AnalizarIn,
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_captura),
):
    """CAPTURA de Anggie: analiza y CREA una solicitud pendiente.

    - Malformados (monto≤0, deuda ajena, sin imputación, EB01 duplicado) → 422, no crea.
    - Conciliación (PAGO_SIS/duplicado) → ADVIERTE pero crea (3-A); la advertencia
      queda en candado_snapshot para el admin. NUNCA crea Payment ni imputa.
    """
    payload = datos.model_dump()
    analisis = pex.analizar_pago_externo(db, payload, organization_id=1)
    res = await pxw.crear_solicitud(db, payload=payload, analisis=analisis,
                                    solicitante=current_member, organization_id=1)
    if not res.get("ok"):
        raise HTTPException(status_code=422, detail={
            "mensaje": "Captura inválida (malformada); corrige antes de enviar.",
            "frena": res.get("frena", []),
            "advertencias": res.get("advertencias", []),
        })
    return res


# ══════════════════════════════════════════════════════════════════════════════
# RESOLUCIÓN — /admin/pagos-externos (admin+sote). Lista + detalle + rechazar.
# El APROBAR/EJECUTAR es sub-paso 4 (crea Payments, necesita comprobantes.origen).
# ══════════════════════════════════════════════════════════════════════════════
@page_router.get("/admin/pagos-externos", response_class=HTMLResponse)
async def pagina_resolucion(
    request: Request,
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_resolucion),
):
    tipos = pex.TIPOS_PAGO_EXTERNO
    rows = db.execute(text("""
        SELECT s.id, s.tipo, s.origen, s.serie, s.numero, s.monto, s.metodo_pago,
               s.imputaciones, s.candado_snapshot, s.concepto,
               s.solicitante_nombre, s.created_at,
               c.apellidos_nombres, c.dni, c.codigo_matricula
        FROM solicitud_pago_externo s
        LEFT JOIN colegiados c ON c.id = s.colegiado_id
        WHERE s.organization_id = :org AND s.estado = 'pendiente'
        ORDER BY s.created_at ASC
    """), {"org": ORG_CCPL}).fetchall()

    pendientes = []
    for r in rows:
        imps = r.imputaciones or []
        snap = r.candado_snapshot or {}
        adv_cap = [a.get("codigo") for a in (snap.get("advertencias") or [])]
        pendientes.append({
            "id": r.id, "tipo": r.tipo,
            "tipo_nombre": tipos.get(r.tipo, {}).get("nombre", f"Tipo {r.tipo}"),
            "origen": r.origen,
            "comprobante": (f"{r.serie}-{r.numero}" if r.serie else "— (sin comprobante)"),
            "monto": float(r.monto or 0), "metodo": r.metodo_pago or "—",
            "colegiado": r.apellidos_nombres or "—", "dni": r.dni or "—",
            "matricula": r.codigo_matricula or "—",
            "n_imputaciones": len(imps), "concepto": r.concepto,
            "solicitante": r.solicitante_nombre or "—", "fecha": r.created_at,
            "adv_captura": adv_cap,
        })

    hist = db.execute(text("""
        SELECT s.id, s.tipo, s.serie, s.numero, s.monto, s.estado,
               s.resuelto_por_nombre, s.resuelto_at, s.nota_resolucion,
               c.apellidos_nombres, c.dni
        FROM solicitud_pago_externo s
        LEFT JOIN colegiados c ON c.id = s.colegiado_id
        WHERE s.organization_id = :org AND s.estado <> 'pendiente'
        ORDER BY s.resuelto_at DESC NULLS LAST, s.id DESC
        LIMIT 100
    """), {"org": ORG_CCPL}).fetchall()
    historial = [{
        "id": h.id, "comprobante": (f"{h.serie}-{h.numero}" if h.serie else "—"),
        "monto": float(h.monto or 0), "estado": h.estado,
        "colegiado": h.apellidos_nombres or "—", "dni": h.dni or "—",
        "resuelto_por": h.resuelto_por_nombre or "—", "resuelto_at": h.resuelto_at,
        "nota": h.nota_resolucion or "",
    } for h in hist]

    return templates.TemplateResponse("pages/admin/pagos_externos.html", {
        "request": request, "user_role": current_member.role,
        "pendientes": pendientes, "historial": historial,
    })


@router.get("/solicitud/{solicitud_id}")
async def detalle_solicitud(
    solicitud_id: int,
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_resolucion),
):
    """Detalle de la solicitud + PREVIEW RE-CALCULADO EN VIVO (no el snapshot viejo)."""
    sol = _get_solicitud_pendiente(db, solicitud_id)
    recomputo = pxw.recalcular_preview(db, sol, organization_id=ORG_CCPL)
    resp = {
        "solicitud": {
            "id": sol.id, "estado": sol.estado, "tipo": sol.tipo, "origen": sol.origen,
            "serie": sol.serie, "numero": sol.numero,
            "fecha_comprobante": (sol.fecha_comprobante.isoformat() if sol.fecha_comprobante else None),
            "monto": float(sol.monto or 0), "metodo_pago": sol.metodo_pago,
            "nro_operacion": sol.nro_operacion,
            "concepto": sol.concepto, "imputaciones": sol.imputaciones or [],
            "solicitante": sol.solicitante_nombre,
            "candado_snapshot": sol.candado_snapshot or {},
        },
        "recomputo": recomputo,
    }
    # Fase 2: si está bloqueada, adjunta la PROPUESTA de conciliación (read-only).
    if not recomputo.get("puede_aprobar_simple"):
        resp["conciliacion"] = pex.analizar_conciliacion(db, sol, organization_id=ORG_CCPL)
    return resp


@page_router.post("/admin/pagos-externos/{solicitud_id}/aprobar")
async def aprobar(
    solicitud_id: int,
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_resolucion),
):
    """APRUEBA/EJECUTA (crea Payment + imputa + comprobante). Re-ejecuta candado en vivo;
    si está bloqueado devuelve 409 'requiere conciliación (Fase 2)' sin crear nada."""
    sol = _get_solicitud_pendiente(db, solicitud_id)
    if sol.estado != "pendiente":
        raise HTTPException(400, detail=f"La solicitud ya está '{sol.estado}'")
    res = await pxw.aprobar_solicitud(db, sol, current_member, organization_id=ORG_CCPL, commit=True)
    if not res.get("success"):
        code = 409 if res.get("bloqueado") else 400
        return JSONResponse(res, status_code=code)
    return JSONResponse(res)


@page_router.post("/admin/pagos-externos/{solicitud_id}/rechazar")
async def rechazar(
    solicitud_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_member: Member = Depends(require_resolucion),
):
    sol = _get_solicitud_pendiente(db, solicitud_id)
    if sol.estado != "pendiente":
        raise HTTPException(400, detail=f"La solicitud ya está '{sol.estado}'")
    data = await request.json()
    nota = (data.get("nota") or "").strip()
    res = await pxw.rechazar_solicitud(db, sol, current_member, nota)
    return res


# ══════════════════════════════════════════════════════════════════════════════
# FASE 2 — DESENLACES (4 endpoints). SOTE nunca ejecuta dinero.
# ══════════════════════════════════════════════════════════════════════════════
@page_router.post("/admin/pagos-externos/{solicitud_id}/resolver")
async def resolver(
    solicitud_id: int, request: Request,
    db: Session = Depends(get_db), current_member: Member = Depends(require_dinero),
):
    """Elige el desenlace de conciliación.
      IMPUTAR/REIMPUTAR → ejecuta en el acto (crea Payment + imputa).
      NOTA_CREDITO/DEVOLUCION → crea la autorización (firma 1); NO ejecuta aún
        (la NC se confirma en /ejecutar-nc; la devolución en /confirmar-devolucion)."""
    sol = _get_solicitud_pendiente(db, solicitud_id)
    if sol.estado != "pendiente":
        raise HTTPException(400, detail=f"La solicitud ya está '{sol.estado}'")
    data = await request.json()
    desenlace = (data.get("desenlace") or "").upper()

    if desenlace in ("IMPUTAR", "REIMPUTAR"):
        res = await pxw.resolver_conciliacion(
            db, sol, desenlace, current_member, organization_id=ORG_CCPL,
            reimputar_debt_ids=data.get("reimputar_debt_ids") or [],
            justificacion=data.get("justificacion") or "", commit=True)
        return JSONResponse(res, status_code=(200 if res.get("success") else 400))

    if desenlace in ("NOTA_CREDITO", "DEVOLUCION"):
        adv = None
        r0 = (pex.analizar_conciliacion(db, sol, ORG_CCPL).get("resultados") or [{}])[0]
        # registrar advertencia tributaria si el operador va CONTRA la sugerencia
        sug = r0.get("sugiere_anular")
        elige_anular = "B400" if desenlace == "NOTA_CREDITO" else "EB01"
        if sug and elige_anular != sug and r0.get("advertencia_tributaria"):
            adv = r0["advertencia_tributaria"]
        refs = _ref_desde_motor(db, sol, desenlace)
        res = await pxw.crear_autorizacion(
            db, sol=sol, desenlace=desenlace, actor=current_member, organization_id=ORG_CCPL,
            justificacion=data.get("justificacion") or "", advertencia=adv,
            anular_ref=refs.get("anular_ref"), devolucion_ref=refs.get("devolucion_ref"),
            commit=True)
        return JSONResponse(res, status_code=(200 if res.get("success") else 400))

    raise HTTPException(400, detail="Desenlace inválido")


@page_router.post("/admin/pagos-externos/autorizacion/{aut_id}/firmar-segunda")
async def firmar_segunda_ep(
    aut_id: int, request: Request,
    db: Session = Depends(get_db), current_member: Member = Depends(require_firma2),
):
    """Segunda firma (solo si la doble firma está activa). SOTE rechazado por el guard."""
    sa = _get_autorizacion(db, aut_id)
    data = await request.json()
    res = await pxw.firmar_segunda(db, sa, current_member,
                                   respuesta=data.get("respuesta") or "",
                                   aprobar=bool(data.get("aprobar", True)),
                                   organization_id=ORG_CCPL, commit=True)
    return JSONResponse(res, status_code=(200 if res.get("success") else 400))


@page_router.post("/admin/pagos-externos/autorizacion/{aut_id}/ejecutar-nc")
async def ejecutar_nc_ep(
    aut_id: int, request: Request,
    db: Session = Depends(get_db), current_member: Member = Depends(require_dinero),
):
    """Emite la NC (IRREVERSIBLE SUNAT). Requiere autorización 'autorizada' + confirmar=True."""
    sa = _get_autorizacion(db, aut_id)
    data = await request.json()
    res = await pxw.ejecutar_nota_credito(
        db, sa, current_member, confirmar=bool(data.get("confirmar", False)),
        ejecutar_sunat=True, organization_id=ORG_CCPL, commit=True)
    code = 200 if res.get("success") else (409 if res.get("bloqueado") or res.get("requiere_confirmacion") else 400)
    return JSONResponse(res, status_code=code)


@page_router.post("/admin/pagos-externos/autorizacion/{aut_id}/confirmar-devolucion")
async def confirmar_devolucion_ep(
    aut_id: int, request: Request,
    db: Session = Depends(get_db), current_member: Member = Depends(require_dinero),
):
    """Tesorería confirma las acciones de la devolución (EB01: devolver plata + anular en SOL).
    ejecutado=true solo cuando TODAS las acciones requeridas están confirmadas."""
    sa = _get_autorizacion(db, aut_id)
    data = await request.json()
    res = await pxw.confirmar_ejecucion_devolucion(
        db, sa, current_member,
        devolver_plata=data.get("devolver_plata"), anular_eb01_sol=data.get("anular_eb01_sol"),
        organization_id=ORG_CCPL, commit=True)
    code = 200 if res.get("success") else (409 if res.get("bloqueado") else 400)
    return JSONResponse(res, status_code=code)

"""
app/routers/openpay.py
======================
Endpoints de integración OpenPay para ColegiosPro CCPL.

Rutas:
  POST /pagos/openpay/iniciar        → Crea cargo y redirige al checkout
  POST /pagos/openpay/webhook        → Recibe notificaciones de OpenPay
  GET  /portal/pago-resultado        → Página de resultado post-pago

Agregar en main.py:
    from app.routers.openpay import router as router_openpay
    app.include_router(router_openpay)
"""

import os
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.database import get_db
from app.models import Member
from app.utils.templates import templates
from app.routers.dashboard import get_current_member
from app.services.openpay_service import (
    crear_cargo_redirect,
    consultar_cargo,
    construir_redirect_url,
    construir_order_id,
    OpenPayError,
    APP_BASE_URL,
)

from app.models_debt_management import Fraccionamiento

#para el HANDLER de webhook, que no tiene autenticación ni sesión, se valida el webhook con la firma de OpenPay y se procesa igual aunque falle la verificación (queda en revisión manual).
from fastapi.responses import PlainTextResponse

logger = logging.getLogger(__name__)
router = APIRouter(tags=["openpay"])


# ══════════════════════════════════════════════════════════════
# 1. INICIAR PAGO
#    El colegiado selecciona deudas y hace clic en "Pagar"
# ══════════════════════════════════════════════════════════════
@router.post("/pagos/openpay/iniciar", response_class=HTMLResponse)
async def openpay_iniciar_pago(
    request: Request,
    deuda_ids:         str   = Form(""),     # "123,456" — vacío en flujos sin IDs
    monto_directo:     float = Form(0.0),    # monto libre (pago directo o cuota inicial)
    fraccionamiento_id: int  = Form(None),   # si viene del simulador de fraccionamiento
    numero_cuota:      int   = Form(0),      # 0 = cuota inicial
    incluir_constancia: str  = Form(""),     # "1" si quiere constancia (+S/10)
    db: Session = Depends(get_db),
    current_member: Member = Depends(get_current_member),
):
    """
    Crea cargo OpenPay. Acepta tres flujos:

    FLUJO A — deuda_ids no vacío:
        Colegiado hábil selecciona deudas del modal. Se validan IDs en BD.

    FLUJO B — monto_directo > 0 sin fraccionamiento_id:
        Colegiado inhábil paga monto libre directamente (sin plan).

    FLUJO C — fraccionamiento_id + monto_directo:
        Colegiado inhábil paga cuota inicial de fraccionamiento.
    """
    from app.models import Colegiado, User

    col = db.query(Colegiado).filter(
        Colegiado.member_id == current_member.id
    ).first()
    if not col:
        return _err_html("Colegiado no encontrado.")

    user = db.query(User).filter(User.id == current_member.user_id).first()
    email = (getattr(user, 'email', '') or col.email or "sin-email@ccploreto.org.pe")

    con_constancia = (incluir_constancia == "1")
    MONTO_CONSTANCIA = 10.0

    # ── Determinar monto y descripción según flujo ─────────────
    ids = [int(x.strip()) for x in deuda_ids.split(",") if x.strip().isdigit()]

    if ids:
        # ── FLUJO A: pago por IDs de deudas ───────────────────
        deudas = db.execute(text("""
            SELECT id, concept, period_label, balance
            FROM debts
            WHERE id = ANY(:ids)
              AND colegiado_id = :cid
              AND status IN ('pending', 'partial')
              AND balance > 0
        """), {"ids": ids, "cid": col.id}).fetchall()

        if not deudas:
            return _err_html("Las deudas seleccionadas ya no están disponibles.")

        monto_base  = sum(float(d.balance) for d in deudas)
        conceptos   = ", ".join(d.period_label or d.concept for d in deudas)
        notas_pago  = f"OpenPay deudas | {conceptos[:100]}"
        debt_ids_db = [d.id for d in deudas]

    elif fraccionamiento_id and monto_directo > 0:
        # ── FLUJO C: cuota inicial de fraccionamiento ─────────
        fracc = db.query(Fraccionamiento).filter(
            Fraccionamiento.id == fraccionamiento_id,
            Fraccionamiento.colegiado_id == col.id,
            Fraccionamiento.estado == "activo",
        ).first()
        if not fracc:
            return _err_html("Plan de fraccionamiento no encontrado o ya no está activo.")

        monto_base = float(monto_directo)
        conceptos  = f"Cuota inicial fracc. {fracc.numero_solicitud}"
        notas_pago = f"OpenPay fracc | {fracc.numero_solicitud} | cuota {numero_cuota}"
        debt_ids_db = []

    elif monto_directo > 0:
        # ── FLUJO B: pago directo libre ───────────────────────
        if monto_directo < 1:
            return _err_html("El monto mínimo de pago es S/ 1.00.")

        monto_base  = float(monto_directo)
        conceptos   = "Abono a deuda"
        notas_pago  = f"OpenPay directo | S/ {monto_base:.2f}"
        debt_ids_db = []

    else:
        return _err_html("Selecciona una deuda o ingresa un monto a pagar.")

    # Sumar constancia si aplica
    monto_total = monto_base + (MONTO_CONSTANCIA if con_constancia else 0)
    if con_constancia:
        notas_pago += " | +Constancia S/10"

    # ── Registrar payment pendiente ────────────────────────────
    result = db.execute(text("""
        INSERT INTO payments (
            organization_id, colegiado_id, member_id,
            amount, status, payment_method, notes, created_at
        ) VALUES (
            :org, :cid, :mid,
            :amount, 'pendiente_openpay', 'openpay',
            :notes, now()
        ) RETURNING id
    """), {
        "org":    current_member.organization_id,
        "cid":    col.id,
        "mid":    current_member.id,
        "amount": monto_total,
        "notes":  notas_pago,
    })
    db.commit()
    payment_id = result.fetchone()[0]

    # Metadatos extra para el webhook
    if fraccionamiento_id:
        db.execute(text("""
            UPDATE payments
            SET notes = notes || :nota
            WHERE id = :pid
        """), {
            "nota": f" | fracc_id:{fraccionamiento_id} cuota:{numero_cuota}",
            "pid":  payment_id,
        })
        db.commit()

    # ── Construir URLs ─────────────────────────────────────────
    order_id     = construir_order_id(payment_id)
    redirect_url = (
        construir_redirect_url(col.id, debt_ids_db)
        if debt_ids_db
        else f"{APP_BASE_URL}/pagos/resultado?payment={payment_id}"
    )

    # ── Llamar a OpenPay ───────────────────────────────────────
    try:
        cargo = await crear_cargo_redirect(
            order_id       = order_id,
            amount         = monto_total,
            description    = f"CCPL - {conceptos[:80]}",
            customer_name  = col.apellidos_nombres,
            customer_email = email,
            redirect_url   = redirect_url,
            due_hours      = 48,
        )
    except OpenPayError as e:
        logger.error(f"OpenPay error: {e.message} [{e.code}]")
        db.execute(text("""
            UPDATE payments SET status = 'error_openpay',
            notes = notes || :nota WHERE id = :pid
        """), {"nota": f" | Error: {e.message}", "pid": payment_id})
        db.commit()
        return _err_html(f"No se pudo conectar con la pasarela. {e.message}")

    # ── Guardar transaction_id ─────────────────────────────────
    transaction_id = cargo.get("id", "")
    checkout_url   = cargo.get("payment_method", {}).get("url", "")

    db.execute(text("""
        UPDATE payments
        SET status = 'esperando_pago',
            openpay_transaction_id = :txid,
            notes = notes || :nota
        WHERE id = :pid
    """), {
        "txid": transaction_id,
        "nota": f" | TX:{transaction_id}",
        "pid":  payment_id,
    })

    for did in debt_ids_db:
        db.execute(text("""
            INSERT INTO payment_debts (payment_id, debt_id)
            VALUES (:pid, :did) ON CONFLICT DO NOTHING
        """), {"pid": payment_id, "did": did})

    db.commit()
    logger.info(f"OpenPay cargo: order={order_id} tx={transaction_id} monto={monto_total} flujo={'ids' if ids else 'fracc' if fraccionamiento_id else 'directo'}")

    if not checkout_url:
        return _err_html("OpenPay no devolvió URL de pago. Contacta a soporte.")

    if request.headers.get("HX-Request"):
        from fastapi.responses import Response
        resp = Response(status_code=200)
        resp.headers["HX-Redirect"] = checkout_url
        return resp

    return RedirectResponse(url=checkout_url, status_code=302)


# ── Helper HTML error ──────────────────────────────────────────
def _err_html(msg: str) -> HTMLResponse:
    return HTMLResponse(f"""
    <div style="padding:12px;background:#fee2e2;border-radius:8px;color:#991b1b;font-size:13px;margin-top:8px;">
        ⚠ {msg}
    </div>
    """)


"""
PATCH: app/routers/openpay.py
==============================
Añadir este endpoint DESPUÉS de openpay_iniciar_pago (línea ~190, antes del webhook).
Es la variante sin login — recibe colegiado_id_externo del partial pagos.html.
"""

@router.post("/pagos/openpay/iniciar-publico", response_class=HTMLResponse)
async def openpay_iniciar_pago_publico(
    request: Request,
    deuda_ids: str = Form(...),
    colegiado_id_externo: int = Form(...),
    db: Session = Depends(get_db),
):
    """
    Versión sin login del inicio de pago OpenPay.
    Usada desde el partial pagos.html (home pública).
    El colegiado_id viene del frontend tras la búsqueda por DNI.
    """
    from app.models import Colegiado, User
    from sqlalchemy import text

    org = request.state.org
    if not org:
        raise HTTPException(status_code=400, detail="Organización no identificada")

    # Verificar que el colegiado pertenece a esta organización
    col = db.query(Colegiado).filter(
        Colegiado.id == colegiado_id_externo,
        Colegiado.organization_id == org["id"],
    ).first()
    if not col:
        return HTMLResponse("""
        <div class="pag-alert pag-alert-error">
            ⚠ Colegiado no válido. Recarga la página e intenta nuevamente.
        </div>""")

    # Parsear IDs de deudas
    try:
        ids = [int(x.strip()) for x in deuda_ids.split(",") if x.strip()]
    except ValueError:
        return HTMLResponse("""
        <div class="pag-alert pag-alert-error">
            ⚠ Selección de deudas inválida.
        </div>""")

    if not ids:
        return HTMLResponse("""
        <div class="pag-alert pag-alert-error">
            ⚠ Selecciona al menos una deuda para continuar.
        </div>""")

    # Consultar deudas — validar que pertenecen al colegiado
    deudas = db.execute(text("""
        SELECT id, concept, period_label, balance
        FROM debts
        WHERE id = ANY(:ids)
          AND colegiado_id = :cid
          AND organization_id = :oid
          AND status IN ('pending', 'parcial')
          AND balance > 0
    """), {"ids": ids, "cid": col.id, "oid": org["id"]}).fetchall()

    if not deudas:
        return HTMLResponse("""
        <div class="pag-alert pag-alert-error">
            ⚠ Las deudas seleccionadas ya no están disponibles o ya fueron pagadas.
        </div>""")

    monto_total = sum(float(d.balance) for d in deudas)
    conceptos   = ", ".join(d.period_label or d.concept for d in deudas)

    # Registrar payment pendiente
    result = db.execute(text("""
        INSERT INTO payments (
            organization_id, colegiado_id, member_id,
            amount, status, payment_method, notes, created_at
        ) VALUES (
            :org, :cid, :mid,
            :amount, 'pendiente_openpay', 'openpay',
            :notes, now()
        ) RETURNING id
    """), {
        "org":    org["id"],
        "cid":    col.id,
        "mid":    col.member_id,
        "amount": monto_total,
        "notes":  f"OpenPay público | {conceptos}",
    })
    db.commit()
    payment_id = result.fetchone()[0]

    order_id     = construir_order_id(payment_id)
    # Resultado va a página neutral (sin login requerido)
    redirect_url = f"{APP_BASE_URL}/pagos/resultado?payment={payment_id}"

    try:
        cargo = await crear_cargo_redirect(
            order_id       = order_id,
            amount         = monto_total,
            description    = f"CCPL - {conceptos[:80]}",
            customer_name  = col.apellidos_nombres,
            customer_email = col.email or "sin-email@ccploreto.org.pe",
            redirect_url   = redirect_url,
            due_hours      = 48,
        )
    except OpenPayError as e:
        logger.error(f"OpenPay público error: {e.message}")
        db.execute(text("""
            UPDATE payments SET status = 'error_openpay',
            notes = notes || :nota WHERE id = :pid
        """), {"nota": f" | Error: {e.message}", "pid": payment_id})
        db.commit()
        return HTMLResponse(f"""
        <div class="pag-alert pag-alert-error">
            ⚠ No se pudo conectar con la pasarela de pago. Intenta en unos minutos.
            <br><small style="opacity:.7">{e.message}</small>
        </div>""")

    transaction_id = cargo.get("id", "")
    checkout_url   = cargo.get("payment_method", {}).get("url", "")

    db.execute(text("""
        UPDATE payments
        SET status = 'esperando_pago',
            openpay_transaction_id = :txid,
            notes = notes || :nota
        WHERE id = :pid
    """), {
        "txid": transaction_id,
        "nota": f" | TX:{transaction_id}",
        "pid":  payment_id,
    })
    for deuda in deudas:
        db.execute(text("""
            INSERT INTO payment_debts (payment_id, debt_id)
            VALUES (:pid, :did) ON CONFLICT DO NOTHING
        """), {"pid": payment_id, "did": deuda.id})
    db.commit()

    if not checkout_url:
        return HTMLResponse("""
        <div class="pag-alert pag-alert-error">
            ⚠ OpenPay no devolvió URL de pago. Contacta a soporte.
        </div>""")

    # HTMX redirect
    from fastapi.responses import Response as FastResponse
    resp = FastResponse(status_code=200)
    resp.headers["HX-Redirect"] = checkout_url
    return resp


# ══════════════════════════════════════════════════════════════
# 2. WEBHOOK
#    OpenPay notifica cuando el pago se completa
# ══════════════════════════════════════════════════════════════
@router.post("/pagos/openpay/webhook")
async def openpay_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Recibe notificaciones POST de OpenPay.
    DEBE ser HTTPS, puerto 443, sin autenticación de cookie.
    Configurar en panel OpenPay → Webhooks.
    URL: https://ccploreto.org.pe/pagos/openpay/webhook
    """
    body_bytes = await request.body()

    try:
        data = json.loads(body_bytes)
    except json.JSONDecodeError:
        logger.error("OpenPay webhook: body no es JSON válido")
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event_type = data.get("type", "")
    # Verificación de webhook por OpenPay
    if event_type == "verification":
        code = data.get("verification_code", "")
        logger.info(f"OpenPay webhook verificado: {code}")
        return JSONResponse({"verification_code": code})
    

    # Solo procesar pagos completados
    if event_type != "charge.succeeded":
        return JSONResponse({"received": True, "processed": False})

    transaction = data.get("transaction", {})
    tx_id       = transaction.get("id", "")
    order_id    = transaction.get("order_id", "")
    monto       = float(transaction.get("amount", 0))
    status_op   = transaction.get("status", "")

    if not tx_id or status_op != "completed":
        return JSONResponse({"received": True, "processed": False})

    # ── Verificar el cargo directamente con OpenPay (seguridad) ──
    try:
        cargo_verificado = await consultar_cargo(tx_id)
        if cargo_verificado.get("status") != "completed":
            logger.warning(f"Webhook recibido pero cargo {tx_id} no está completed")
            return JSONResponse({"received": True, "processed": False})
    except OpenPayError as e:
        logger.error(f"No se pudo verificar cargo {tx_id}: {e.message}")
        # Procesamos igual para no perder el pago — quedará en revisión manual
        logger.warning("Procesando sin verificación — revisar manualmente")

    # ── Buscar payment por transaction_id ──────────────────────
    payment = db.execute(text("""
        SELECT p.id, p.colegiado_id, p.amount, p.status, p.organization_id
        FROM payments p
        WHERE p.openpay_transaction_id = :txid
           OR p.notes LIKE :order_pattern
        LIMIT 1
    """), {
        "txid":          tx_id,
        "order_pattern": f"%{order_id}%",
    }).fetchone()

    if not payment:
        logger.error(f"Webhook OpenPay: no se encontró payment para TX:{tx_id} order:{order_id}")
        # Devolver 200 para que OpenPay no reintente — registrar para revisión manual
        db.execute(text("""
            INSERT INTO openpay_webhooks_pendientes
                (transaction_id, order_id, amount, payload, created_at)
            VALUES (:txid, :oid, :amt, :payload, now())
            ON CONFLICT DO NOTHING
        """), {
            "txid":    tx_id,
            "oid":     order_id,
            "amt":     monto,
            "payload": json.dumps(data),
        })
        db.commit()
        return JSONResponse({"received": True, "processed": False, "note": "payment not found"})

    if payment.status in ("completado", "pagado"):
        # Ya fue procesado (webhook duplicado)
        return JSONResponse({"received": True, "processed": False, "note": "already processed"})

    # ── Marcar payment como pagado ─────────────────────────────
    db.execute(text("""
        UPDATE payments
        SET status = 'pagado',
            paid_at = now(),
            notes = notes || :nota
        WHERE id = :pid
    """), {
        "nota": f" | Confirmado OpenPay {tx_id}",
        "pid":  payment.id,
    })

    # ── Cerrar deudas vinculadas o imputar automáticamente ─────────
    deudas_vinculadas = db.execute(text("""
        SELECT debt_id FROM payment_debts WHERE payment_id = :pid
    """), {"pid": payment.id}).fetchall()

    if deudas_vinculadas:
        # FLUJO A: deudas específicas seleccionadas por el colegiado
        for d in deudas_vinculadas:
            db.execute(text("""
                UPDATE debts
                SET balance = 0,
                    status  = 'pagado',
                    updated_at = now()
                WHERE id = :did AND status IN ('pending', 'partial', 'parcial', 'esperando_pago')
            """), {"did": d.debt_id})
    else:
        # FLUJO B/C: pago libre o cuota inicial — imputar a más antigua primero
        from app.services.deuda_cuotas_service import imputar_pago_a_deudas
        resultado = imputar_pago_a_deudas(
            colegiado_id    = payment.colegiado_id,
            organization_id = payment.organization_id,
            monto_pagado    = float(payment.amount),
            payment_id      = payment.id,
            db              = db,
        )
        logger.info(
            f"Imputación automática: {resultado['deudas_cerradas']} deudas cerradas, "
            f"imputado S/{resultado['monto_imputado']:.2f}, "
            f"sobrante S/{resultado['monto_sobrante']:.2f}"
        )
        # Si hay sobrante, anotarlo en el payment para revisión manual
        if resultado['monto_sobrante'] > 0:
            db.execute(text("""
                UPDATE payments SET notes = notes || :nota WHERE id = :pid
            """), {
                "nota": f" | Sobrante S/{resultado['monto_sobrante']:.2f} pendiente de imputar",
                "pid":  payment.id,
            })

    # ── Recalcular habilidad del colegiado ──────────────────────
    # Verificar si ya no tiene deudas pendientes y actualizar condicion
    from app.services.evaluar_habilidad import evaluar_habilidad
    from app.services.deuda_cuotas_service import calcular_deuda_total as _svc_deuda

    deuda_info = _svc_deuda(payment.colegiado_id, payment.organization_id, db)
    col_obj = db.execute(text("SELECT * FROM colegiados WHERE id = :cid"),
        {"cid": payment.colegiado_id}).fetchone()
    org_obj = db.execute(text("SELECT * FROM organizations WHERE id = :oid"),
        {"oid": payment.organization_id}).fetchone()

    eval_hab = evaluar_habilidad(deuda_info, dict(org_obj._mapping), col_obj)
    if not eval_hab.debe_inhabilitar:
        db.execute(text("""
            UPDATE colegiados SET condicion = 'habil'
            WHERE id = :cid AND condicion = 'inhabil'
        """), {"cid": payment.colegiado_id})
        logger.info(f"Colegiado {payment.colegiado_id} → HÁBIL tras pago OpenPay")

    db.commit()
    logger.info(f"✅ Pago OpenPay procesado: payment={payment.id} tx={tx_id} monto={monto}")

    return JSONResponse({"received": True, "processed": True})


# ══════════════════════════════════════════════════════════════
# 3. PÁGINA DE RESULTADO
#    OpenPay redirige aquí después del checkout
# ══════════════════════════════════════════════════════════════
@router.get("/portal/pago-resultado", response_class=HTMLResponse)
async def portal_pago_resultado(
    request: Request,
    colegiado: int = None,
    deudas: str = "",
    db: Session = Depends(get_db),
    current_member: Member = Depends(get_current_member),
):
    """
    Página intermedia de espera/confirmación.
    OpenPay redirige aquí después del checkout.
    El pago real se confirma vía webhook — esta página
    muestra estado y refresca automáticamente.
    """
    from app.models import Colegiado
    col = db.query(Colegiado).filter(
        Colegiado.member_id == current_member.id
    ).first()

    # Buscar el último payment pendiente
    ultimo_pago = db.execute(text("""
        SELECT id, amount, status, openpay_transaction_id, created_at
        FROM payments
        WHERE colegiado_id = :cid
          AND payment_method = 'openpay'
        ORDER BY created_at DESC
        LIMIT 1
    """), {"cid": col.id if col else 0}).fetchone()

    return templates.TemplateResponse("pages/portal/pago_resultado.html", {
        "request":    request,
        "user":       current_member,
        "col":        col,
        "pago":       ultimo_pago,
        "org":        getattr(request.state, "org", {}),
    })


"""
PATCH 2: app/routers/openpay.py
================================
Añadir este endpoint AL FINAL del router, después de portal_pago_resultado.
Es la página de resultado para pagos públicos (sin login).
"""

@router.get("/pagos/resultado", response_class=HTMLResponse)
async def pago_resultado_publico(
    request: Request,
    payment: int = None,
    db: Session = Depends(get_db),
):
    """
    Página de resultado post-OpenPay para pagos públicos (sin login).
    OpenPay redirige aquí tras el checkout.
    Muestra estado y refresca automáticamente cada 5s hasta confirmar.
    """
    from sqlalchemy import text

    org = request.state.org
    pago = None

    if payment:
        pago = db.execute(text("""
            SELECT p.id, p.amount, p.status, p.openpay_transaction_id,
                   c.apellidos_nombres, c.codigo_matricula
            FROM payments p
            JOIN colegiados c ON c.id = p.colegiado_id
            WHERE p.id = :pid
              AND p.organization_id = :oid
        """), {"pid": payment, "oid": org["id"] if org else 0}).fetchone()

    return templates.TemplateResponse("partials/pago_resultado_publico.html", {
        "request": request,
        "pago":    pago,
        "org":     org or {},
    })


# ── Endpoint 1: consulta estado en BD (para el polling JS) ──
@router.get("/pagos/resultado/estado")
async def consultar_estado_pago(
    payment: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Consulta rápida del estado de un payment en BD."""
    from sqlalchemy import text
    org = request.state.org
    row = db.execute(text("""
        SELECT status FROM payments
        WHERE id = :pid AND organization_id = :oid
    """), {"pid": payment, "oid": org["id"] if org else 0}).fetchone()

    if not row:
        return JSONResponse({"status": "not_found"}, status_code=404)
    return JSONResponse({"status": row.status})


# ── Endpoint 2: consultar OpenPay directamente (fallback webhook) ──
@router.get("/pagos/openpay/consultar/{payment_id}")
async def consultar_openpay_directo(
    payment_id: int,
    request:    Request,
    db:         Session = Depends(get_db),
):
    """
    Consulta el estado real del cargo en OpenPay (GET al charge).
    Recomendación explícita del equipo OpenPay como fallback del webhook.
    Si OpenPay dice 'completed' pero BD no lo tiene → procesar ahora.
    """
    from sqlalchemy import text
    import httpx, base64

    org     = request.state.org
    payment = db.execute(text("""
        SELECT id, status, openpay_transaction_id, colegiado_id, organization_id, amount
        FROM payments
        WHERE id = :pid AND organization_id = :oid
    """), {"pid": payment_id, "oid": org["id"] if org else 0}).fetchone()

    if not payment:
        return JSONResponse({"status": "not_found"}, status_code=404)

    # Si ya está pagado en BD, devolver directo
    if payment.status == "pagado":
        return JSONResponse({"status": "pagado"})

    tx_id = payment.openpay_transaction_id
    if not tx_id:
        return JSONResponse({"status": payment.status})

    # Consultar directamente a OpenPay
    try:
        sk         = os.getenv("OPENPAY_SK", "")
        merchant   = os.getenv("OPENPAY_MERCHANT_ID", "")
        sandbox    = os.getenv("OPENPAY_SANDBOX", "true").lower() == "true"
        base_url   = "https://sandbox-api.openpay.pe" if sandbox else "https://api.openpay.pe"
        creds      = base64.b64encode(f"{sk}:".encode()).decode()
        url        = f"{base_url}/v1/{merchant}/charges/{tx_id}"

        async with httpx.AsyncClient(timeout=10) as client:
            r    = await client.get(url, headers={"Authorization": f"Basic {creds}"})
            data = r.json()

        estado_op = data.get("status", "")
        logger.info(f"[ConsultaOpenPay] payment={payment_id} tx={tx_id} estado={estado_op}")

        # Si OpenPay dice completed pero BD no lo tiene → procesar
        if estado_op == "completed" and payment.status != "pagado":
            logger.warning(f"[ConsultaOpenPay] Webhook no llegó — procesando payment={payment_id}")
            # Actualizar BD directamente
            db.execute(text("""
                UPDATE payments
                SET status = 'pagado', paid_at = NOW()
                WHERE id = :pid
            """), {"pid": payment_id})
            db.commit()

            # Recalcular habilidad
            try:
                from app.services.deuda_cuotas_service import calcular_deuda_total
                from app.services.evaluar_habilidad import evaluar_habilidad
                from app.models import Colegiado, Organization

                col_obj = db.query(Colegiado).filter(
                    Colegiado.id == payment.colegiado_id
                ).first()
                org_obj = db.query(Organization).filter(
                    Organization.id == payment.organization_id
                ).first()

                if col_obj and org_obj:
                    deuda_info = calcular_deuda_total(col_obj.id, org_obj.id, db)
                    eval_hab   = evaluar_habilidad(deuda_info, dict(org_obj._mapping), col_obj)
                    if not eval_hab.debe_inhabilitar:
                        db.execute(text("""
                            UPDATE colegiados SET condicion = 'habil'
                            WHERE id = :cid AND condicion = 'inhabil'
                        """), {"cid": payment.colegiado_id})
                        db.commit()
                        logger.info(f"[ConsultaOpenPay] Colegiado {payment.colegiado_id} → HÁBIL")
            except Exception as e:
                logger.error(f"[ConsultaOpenPay] Error recalculando habilidad: {e}")

            return JSONResponse({"status": "pagado", "fuente": "consulta_directa"})

        return JSONResponse({"status": payment.status, "openpay_estado": estado_op})

    except Exception as e:
        logger.error(f"[ConsultaOpenPay] Error: {e}")
        return JSONResponse({"status": payment.status})


# CAMBIAR TEMPORALMENTE en app/routers/openpay.py:

@router.get("/pagos/openpay/webhook")
async def webhook_verificar(
    request: Request,
    verification_code: str = None,
):
    # LOG TEMPORAL — ver qué envía OpenPay
    logger.info(f"Webhook GET params: {dict(request.query_params)}")
    
    if verification_code:
        return PlainTextResponse(verification_code)
    # Si viene con otro nombre, devolver el primer valor que haya
    params = dict(request.query_params)
    if params:
        primer_valor = list(params.values())[0]
        return PlainTextResponse(primer_valor)
    return PlainTextResponse("ok")
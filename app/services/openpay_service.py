"""
app/services/openpay_service.py
================================
Cliente OpenPay para CCPL.

Configuración mediante variables de entorno (NO hardcodear valores reales aquí):
    OPENPAY_MERCHANT_ID         → ID del merchant
    OPENPAY_SK                  → Secret key (server-side, nunca exponer)
    OPENPAY_PK                  → Public key (frontend, no usado en flujo redirect)
    OPENPAY_SANDBOX             → "true"/"false" (default "true")
    APP_BASE_URL                → URL pública del sitio (default ccploreto.org.pe)

Hardening del webhook (opcional — si vacío, se cae a la mitigación por re-consulta):
    OPENPAY_WEBHOOK_HMAC_SECRET → Clave HMAC entregada por OpenPay PE
    OPENPAY_WEBHOOK_HMAC_HEADER → Nombre del header de firma (default X-Openpay-Signature)
    OPENPAY_WEBHOOK_HMAC_ALGO   → Algoritmo hash (default sha256)
    OPENPAY_WEBHOOK_ALLOWED_IPS → CIDRs autorizados separados por coma (vacío = todas)
"""

import os
import hmac
import hashlib
import ipaddress
import logging
from functools import lru_cache
from datetime import datetime, timezone, timedelta
from typing import Mapping, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)


# ── Configuración leída del entorno al cargar el módulo ──────────
OPENPAY_MERCHANT_ID = os.getenv("OPENPAY_MERCHANT_ID", "")
OPENPAY_SK          = os.getenv("OPENPAY_SK", "")
OPENPAY_PK          = os.getenv("OPENPAY_PK", "")
APP_BASE_URL        = os.getenv("APP_BASE_URL", "https://ccploreto.org.pe")

# Aliases legacy mantenidos por compatibilidad interna
MERCHANT_ID = OPENPAY_MERCHANT_ID
SECRET_KEY  = OPENPAY_SK
PUBLIC_KEY  = OPENPAY_PK


def _sandbox_enabled() -> bool:
    """True si OPENPAY_SANDBOX no está explícitamente en 'false'."""
    return os.getenv("OPENPAY_SANDBOX", "true").strip().lower() == "true"


@lru_cache(maxsize=1)
def get_openpay_base_url() -> str:
    """
    URL base del API OpenPay según el flag de ambiente.
    Centralizada para evitar drift entre service y router.
    Cacheada con lru_cache; invalidar con reset_base_url_cache() si
    cambia el env var en runtime.
    """
    merchant = OPENPAY_MERCHANT_ID
    if not merchant:
        raise RuntimeError("OPENPAY_MERCHANT_ID no configurado")
    host = "sandbox-api.openpay.pe" if _sandbox_enabled() else "api.openpay.pe"
    return f"https://{host}/v1/{merchant}"


def reset_base_url_cache() -> None:
    """Invalida el cache de get_openpay_base_url(). Uso operativo."""
    get_openpay_base_url.cache_clear()


class OpenPayError(Exception):
    def __init__(self, message: str, code: str = None, http_status: int = None):
        self.message     = message
        self.code        = code
        self.http_status = http_status
        super().__init__(message)


async def crear_cargo_redirect(
    *,
    order_id: str,
    amount: float,
    description: str,
    customer_name: str,
    customer_email: str,
    redirect_url: str,
    due_hours: int = 48,
) -> dict:
    """
    Crea un cargo tipo redirect en OpenPay.
    Retorna el objeto completo de la transacción, incluyendo
    payment_method.url para redirigir al colegiado.
    """
    if not OPENPAY_MERCHANT_ID or not OPENPAY_SK:
        raise OpenPayError(
            "OpenPay no configurado. Verificar variables OPENPAY_MERCHANT_ID y OPENPAY_SK.",
            code="CONFIG_ERROR"
        )

    due_date = (
        datetime.now(timezone.utc) + timedelta(hours=due_hours)
    ).strftime("%Y-%m-%dT%H:%M:%S")

    payload = {
        "method":       "card",
        "amount":       round(float(amount), 2),
        "currency":     "PEN",
        "description":  description,
        "order_id":     order_id,
        "confirm":      "false",
        "send_email":   "false",
        "redirect_url": redirect_url,
        "due_date":     due_date,
        "customer": {
            "name":  customer_name,
            "email": customer_email or "sin-email@ccploreto.org.pe",
        }
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{get_openpay_base_url()}/charges",
            json=payload,
            auth=(OPENPAY_SK, ""),   # Basic auth: SK como usuario, password vacío
        )

    if resp.status_code not in (200, 201):
        try:
            err = resp.json()
            msg  = err.get("description", "Error desconocido de OpenPay")
            code = str(err.get("error_code", ""))
        except Exception:
            msg  = f"HTTP {resp.status_code}"
            code = "HTTP_ERROR"
        raise OpenPayError(msg, code=code, http_status=resp.status_code)

    return resp.json()


def construir_redirect_url(colegiado_id: int, deuda_ids: list[int]) -> str:
    """URL de retorno después del pago — regresa al portal del colegiado."""
    deudas_str = ",".join(str(d) for d in deuda_ids)
    return f"{APP_BASE_URL}/portal/pago-resultado?colegiado={colegiado_id}&deudas={deudas_str}"


def construir_order_id(pago_id: int) -> str:
    """Formato estándar de order_id para OpenPay."""
    return f"CCPL-{pago_id:06d}"


# ══════════════════════════════════════════════════════════════════
# Hardening del webhook (zClaude-81b)
# ══════════════════════════════════════════════════════════════════
OPENPAY_WEBHOOK_HMAC_SECRET = os.getenv("OPENPAY_WEBHOOK_HMAC_SECRET", "").strip()
OPENPAY_WEBHOOK_HMAC_HEADER = os.getenv("OPENPAY_WEBHOOK_HMAC_HEADER", "X-Openpay-Signature").strip()
OPENPAY_WEBHOOK_HMAC_ALGO   = os.getenv("OPENPAY_WEBHOOK_HMAC_ALGO", "sha256").strip().lower()
OPENPAY_WEBHOOK_ALLOWED_IPS = os.getenv("OPENPAY_WEBHOOK_ALLOWED_IPS", "").strip()


def verificar_webhook_ip(remote_ip: str) -> Tuple[bool, str]:
    """
    Si OPENPAY_WEBHOOK_ALLOWED_IPS está seteado (CIDRs separados por coma),
    verifica que remote_ip pertenezca a alguna red autorizada.
    Si está vacío, retorna (True, 'whitelist deshabilitada').
    """
    if not OPENPAY_WEBHOOK_ALLOWED_IPS:
        return True, "whitelist deshabilitada"

    try:
        addr = ipaddress.ip_address(remote_ip)
    except ValueError:
        return False, f"IP inválida: {remote_ip}"

    cidrs = [c.strip() for c in OPENPAY_WEBHOOK_ALLOWED_IPS.split(",") if c.strip()]
    for cidr in cidrs:
        try:
            net = ipaddress.ip_network(cidr, strict=False)
            if addr in net:
                return True, f"match {cidr}"
        except ValueError:
            logger.warning(f"OPENPAY_WEBHOOK_ALLOWED_IPS contiene CIDR inválido: {cidr}")
            continue
    return False, f"IP {remote_ip} fuera de whitelist"


def verificar_webhook_signature(
    payload_bytes: bytes,
    headers: Mapping[str, str],
) -> Tuple[bool, str]:
    """
    Verifica HMAC del payload del webhook.

    Modos:
    - Si OPENPAY_WEBHOOK_HMAC_SECRET está seteado:
        Calcula HMAC del payload_bytes con la clave y algoritmo configurados.
        Compara contra el header OPENPAY_WEBHOOK_HMAC_HEADER (case-insensitive).
        Retorna (True, motivo) o (False, motivo).
    - Si OPENPAY_WEBHOOK_HMAC_SECRET está vacío:
        Retorna (True, 'hmac deshabilitado') y emite log WARN.
        El handler debe seguir aplicando re-consulta a OpenPay como segunda barrera.
    """
    if not OPENPAY_WEBHOOK_HMAC_SECRET:
        logger.warning(
            "OPENPAY_WEBHOOK_HMAC_SECRET no configurado. "
            "Webhook sin verificación criptográfica. "
            "Mitigación activa: re-consulta del cargo a OpenPay."
        )
        return True, "hmac deshabilitado"

    firma_recibida: Optional[str] = None
    for k, v in headers.items():
        if k.lower() == OPENPAY_WEBHOOK_HMAC_HEADER.lower():
            firma_recibida = v.strip()
            break

    if not firma_recibida:
        return False, f"header {OPENPAY_WEBHOOK_HMAC_HEADER} ausente"

    try:
        algo = getattr(hashlib, OPENPAY_WEBHOOK_HMAC_ALGO)
    except AttributeError:
        return False, f"algoritmo no soportado: {OPENPAY_WEBHOOK_HMAC_ALGO}"

    firma_calculada = hmac.new(
        OPENPAY_WEBHOOK_HMAC_SECRET.encode("utf-8"),
        payload_bytes,
        algo,
    ).hexdigest()

    if hmac.compare_digest(firma_calculada, firma_recibida):
        return True, "firma válida"
    return False, "firma no coincide"


async def consultar_cargo(transaction_id: str) -> dict:
    """Consulta el estado de un cargo en OpenPay (defensa en profundidad del webhook)."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{get_openpay_base_url()}/charges/{transaction_id}",
            auth=(OPENPAY_SK, ""),
        )
    if resp.status_code != 200:
        raise OpenPayError(
            f"No se pudo consultar cargo {transaction_id}",
            http_status=resp.status_code
        )
    return resp.json()


# ══════════════════════════════════════════════════════════════════
# Procesamiento de pago confirmado (reusable: webhook / reproceso /
# consulta directa). Idempotente: si el payment ya está procesado,
# retorna sin reprocesar.
# ══════════════════════════════════════════════════════════════════
async def procesar_pago_confirmado(
    db,
    payment_id: int,
    tx_id: str,
    payload: dict,
    source: str = "webhook",
) -> dict:
    """
    Procesa un pago OpenPay confirmado. Encapsula la lógica que estaba inline
    en el handler del webhook. Llamable desde:
      - Handler del webhook al recibir charge.succeeded
      - Reproceso de openpay_webhooks_pendientes
      - Consulta directa (fallback de polling)

    Idempotente: si payment.status ya es 'approved'/'pagado'/'completado',
    no reprocesa.

    Retorna dict con {"ok": bool, "flujo": str, "payment_id": int, ...}.
    """
    import json as _json
    from sqlalchemy import text
    from app.models import Payment as _Payment, Organization as _Org

    # 1. Cargar payment con bloqueo de fila
    payment = db.execute(text("""
        SELECT id, colegiado_id, amount, status, organization_id, notes,
               openpay_transaction_id
        FROM payments
        WHERE id = :pid
        FOR UPDATE
    """), {"pid": payment_id}).fetchone()

    if not payment:
        return {"ok": False, "error": "payment_no_encontrado", "payment_id": payment_id}

    # 2. Idempotencia
    if payment.status in ("approved", "pagado", "completado"):
        return {
            "ok": True,
            "estado": "ya_procesado",
            "status_actual": payment.status,
            "payment_id": payment_id,
        }

    # 3. Asegurar que la columna tx_id esté poblada
    if not payment.openpay_transaction_id and tx_id:
        db.execute(text("""
            UPDATE payments
            SET openpay_transaction_id = :tx
            WHERE id = :pid AND openpay_transaction_id IS NULL
        """), {"tx": tx_id, "pid": payment_id})

    # 4. Detectar flujo desde notes
    try:
        notas = (
            _json.loads(payment.notes)
            if payment.notes and payment.notes.strip().startswith("{")
            else {}
        )
    except Exception:
        notas = {}

    flujo = notas.get("flujo", "")

    # ── RAMA TIENDA PÚBLICA OPENPAY ─────────────────────────────
    if flujo == "tienda_publica_openpay":
        from app.routers.api_tienda import _emitir_cpe_tienda_y_stock

        pay_obj = db.query(_Payment).filter(_Payment.id == payment.id).first()
        org_obj = db.query(_Org).filter(_Org.id == payment.organization_id).first()

        if not (pay_obj and org_obj):
            return {"ok": False, "error": "lookup_failed_tienda", "payment_id": payment_id}

        await _emitir_cpe_tienda_y_stock(db, pay_obj, org_obj)
        pay_obj.status = "approved"
        try:
            pay_obj.paid_at = datetime.now(timezone.utc)
        except Exception:
            pass
        db.commit()
        logger.info(
            f"[procesar_pago_confirmado] Tienda pública procesada payment={pay_obj.id} "
            f"tx={tx_id} source={source}"
        )
        return {
            "ok": True,
            "flujo": "tienda_publica_openpay",
            "payment_id": pay_obj.id,
            "source": source,
        }

    # ── RAMA DEUDAS / FRACCIONAMIENTO / DIRECTO ─────────────────
    db.execute(text("""
        UPDATE payments
        SET status = 'pagado',
            paid_at = now(),
            notes = notes || :nota
        WHERE id = :pid
    """), {
        "nota": f" | Confirmado OpenPay {tx_id} (source={source})",
        "pid":  payment.id,
    })

    deudas_vinculadas = db.execute(text("""
        SELECT debt_id FROM payment_debts WHERE payment_id = :pid
    """), {"pid": payment.id}).fetchall()

    if deudas_vinculadas:
        for d in deudas_vinculadas:
            db.execute(text("""
                UPDATE debts
                SET balance = 0,
                    status  = 'pagado',
                    updated_at = now()
                WHERE id = :did
                  AND status IN ('pending', 'partial', 'parcial', 'esperando_pago')
            """), {"did": d.debt_id})
    else:
        from app.services.deuda_cuotas_service import imputar_pago_a_deudas
        resultado = imputar_pago_a_deudas(
            colegiado_id    = payment.colegiado_id,
            organization_id = payment.organization_id,
            monto_pagado    = float(payment.amount),
            payment_id      = payment.id,
            db              = db,
        )
        logger.info(
            f"[procesar_pago_confirmado] Imputación payment={payment.id}: "
            f"{resultado['deudas_cerradas']} deudas cerradas, "
            f"S/{resultado['monto_imputado']:.2f} imputado, "
            f"sobrante S/{resultado['monto_sobrante']:.2f}"
        )
        if resultado['monto_sobrante'] > 0:
            db.execute(text("""
                UPDATE payments SET notes = notes || :nota WHERE id = :pid
            """), {
                "nota": f" | Sobrante S/{resultado['monto_sobrante']:.2f} pendiente de imputar",
                "pid":  payment.id,
            })

    # ── Recalcular habilidad ────────────────────────────────────
    try:
        from app.services.evaluar_habilidad import evaluar_habilidad
        from app.services.deuda_cuotas_service import calcular_deuda_total
        deuda_info = calcular_deuda_total(payment.colegiado_id, payment.organization_id, db)
        col_obj = db.execute(text("SELECT * FROM colegiados WHERE id = :cid"),
            {"cid": payment.colegiado_id}).fetchone()
        org_obj_row = db.execute(text("SELECT * FROM organizations WHERE id = :oid"),
            {"oid": payment.organization_id}).fetchone()

        if col_obj and org_obj_row:
            eval_hab = evaluar_habilidad(deuda_info, dict(org_obj_row._mapping), col_obj)
            if not eval_hab.debe_inhabilitar:
                db.execute(text("""
                    UPDATE colegiados SET condicion = 'habil'
                    WHERE id = :cid AND condicion = 'inhabil'
                """), {"cid": payment.colegiado_id})
                logger.info(
                    f"[procesar_pago_confirmado] Colegiado {payment.colegiado_id} → HÁBIL"
                )
    except Exception as e:
        logger.error(f"[procesar_pago_confirmado] Error recalc habilidad: {e}", exc_info=True)

    db.commit()
    logger.info(
        f"[procesar_pago_confirmado] Pago procesado payment={payment.id} "
        f"tx={tx_id} source={source}"
    )

    # ── Emitir comprobante electrónico (si aplica) ──────────────
    try:
        tipo_comp = notas.get("tipo_comprobante")
        if tipo_comp in ("boleta", "factura"):
            from app.services.facturacion import FacturacionService
            svc = FacturacionService(db, payment.organization_id)

            if svc.esta_configurado():
                tipo_doc     = "01" if tipo_comp == "factura" else "03"
                forzar_datos = None

                if tipo_comp == "factura":
                    ruc  = notas.get("factura_ruc")
                    rs   = notas.get("factura_razon_social") or "CLIENTE"
                    dire = notas.get("factura_direccion") or ""
                    if ruc:
                        forzar_datos = {
                            "tipo_doc":  "6",
                            "num_doc":   ruc,
                            "nombre":    rs,
                            "direccion": dire,
                            "email":     None,
                        }

                resultado_comp = await svc.emitir_comprobante_por_pago(
                    payment.id,
                    tipo                 = tipo_doc,
                    forzar_datos_cliente = forzar_datos,
                )

                if resultado_comp.get("success"):
                    logger.info(
                        f"[procesar_pago_confirmado] Comprobante emitido: "
                        f"{resultado_comp.get('numero_formato')}"
                    )
                else:
                    logger.warning(
                        f"[procesar_pago_confirmado] Comprobante no emitido: "
                        f"{resultado_comp.get('error')}"
                    )
    except Exception as e:
        logger.error(
            f"[procesar_pago_confirmado] Error emitiendo comprobante payment={payment.id}: {e}",
            exc_info=True
        )

    return {
        "ok": True,
        "flujo": flujo or "directo",
        "payment_id": payment.id,
        "source": source,
    }

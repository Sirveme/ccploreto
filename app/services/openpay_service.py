"""
app/services/openpay_service.py
================================
Lógica de integración con OpenPay Perú.

Variables de entorno requeridas (Railway → Variables):
    OPENPAY_MERCHANT_ID   = mzjvubnp1si9mul8oe2g
    OPENPAY_SK            = sk_1c59708c38ad4d41937c10efafd30762
    OPENPAY_PK            = pk_7036c220ca4c45b39d180c3964f97dfe
    OPENPAY_SANDBOX       = true   (cambiar a false en producción)
    APP_BASE_URL          = https://ccploreto.org.pe
"""

import os
import httpx
import hashlib
import hmac
from datetime import datetime, timezone, timedelta
from typing import Optional


# ── Configuración ─────────────────────────────────────────────
MERCHANT_ID   = os.getenv("OPENPAY_MERCHANT_ID", "")
SECRET_KEY    = os.getenv("OPENPAY_SK", "")
PUBLIC_KEY    = os.getenv("OPENPAY_PK", "")
SANDBOX       = os.getenv("OPENPAY_SANDBOX", "true").lower() == "true"
APP_BASE_URL  = os.getenv("APP_BASE_URL", "https://ccploreto.org.pe")

BASE_URL = (
    f"https://sandbox-api.openpay.pe/v1/{MERCHANT_ID}"
    if SANDBOX else
    f"https://api.openpay.pe/v1/{MERCHANT_ID}"
)


class OpenPayError(Exception):
    def __init__(self, message: str, code: str = None, http_status: int = None):
        self.message   = message
        self.code      = code
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
    Retorna el objeto completo de la transacción,
    incluyendo payment_method.url para redirigir al colegiado.

    Args:
        order_id:       ID único del pedido (ej: "CCPL-PAY-00123")
        amount:         Monto en soles (ej: 120.00)
        description:    Descripción visible al pagador
        customer_name:  Nombre del colegiado
        customer_email: Email del colegiado
        redirect_url:   URL a la que OpenPay redirige DESPUÉS del pago
        due_hours:      Horas antes de vencer el link de pago (default 48)
    """
    if not MERCHANT_ID or not SECRET_KEY:
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
            f"{BASE_URL}/charges",
            json=payload,
            auth=(SECRET_KEY, ""),   # Basic auth: SK como usuario, password vacío
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


def verificar_webhook_signature(payload_bytes: bytes, signature_header: str) -> bool:
    """
    OpenPay no envía firma HMAC estándar en su webhook actual.
    Se recomienda validar por IP origen + verificar el ID de transacción
    consultando directamente a la API de OpenPay.
    Retorna True mientras no haya firma configurada.
    """
    # TODO: implementar validación por IP whitelist de OpenPay
    # IPs OpenPay: consultar con el equipo técnico en la cita de producción
    return True


async def consultar_cargo(transaction_id: str) -> dict:
    """Consulta el estado de un cargo en OpenPay para verificar webhook."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{BASE_URL}/charges/{transaction_id}",
            auth=(SECRET_KEY, ""),
        )
    if resp.status_code != 200:
        raise OpenPayError(
            f"No se pudo consultar cargo {transaction_id}",
            http_status=resp.status_code
        )
    return resp.json()
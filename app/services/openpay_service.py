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

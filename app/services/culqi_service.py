"""
app/services/culqi_service.py
==============================
Módulo reutilizable de integración Culqi para el ecosistema Peru Sistemas Pro.

Compatible con: ColegiosPro · QueVendi · Metraes · Facturalo

Culqi API v2.0 — Custom Checkout (único método soportado actualmente).
Docs: https://docs.culqi.com

─────────────────────────────────────────────────────────────────────────────
DIFERENCIA ARQUITECTÓNICA VS OPENPAY
─────────────────────────────────────────────────────────────────────────────

OpenPay (redirect):
  Backend crea cargo → devuelve checkout_url → usuario va a otra página → webhook

Culqi (token/orden):
  ┌─ Tarjeta ─────────────────────────────────────────────────────────────┐
  │  Frontend (Culqi JS) tokeniza tarjeta → envía token_id al backend     │
  │  Backend llama crear_cargo(token_id) → cargo inmediato                │
  └───────────────────────────────────────────────────────────────────────┘
  ┌─ Yape / Plin / PagoEfectivo ──────────────────────────────────────────┐
  │  Backend crea Orden → devuelve order_id al frontend                   │
  │  Frontend pasa order_id al Culqi Checkout JS → muestra QR/opciones    │
  │  Usuario paga → Culqi notifica via webhook (order.status.changed)     │
  └───────────────────────────────────────────────────────────────────────┘

─────────────────────────────────────────────────────────────────────────────
VARIABLES DE ENTORNO REQUERIDAS
─────────────────────────────────────────────────────────────────────────────
  CULQI_SK          Secret key  (sk_test_xxxx en sandbox / sk_live_xxxx en prod)
  CULQI_PK          Public key  (pk_test_xxxx / pk_live_xxxx)  — solo para frontend
  CULQI_RSA_ID      ID de la llave RSA (CulqiPanel → Desarrollo → RSA Keys)
  CULQI_RSA_KEY     Llave pública RSA (para encriptar payload)
  CULQI_SANDBOX     true | false  (default: true)
  APP_BASE_URL      https://ccploreto.org.pe (o dominio del proyecto)

─────────────────────────────────────────────────────────────────────────────
TASAS VIGENTES (Marzo 2026 — verificar con Culqi al contratar)
─────────────────────────────────────────────────────────────────────────────
  Tarjeta nacional:      3.44% + IGV  (mínimo S/3.50 si venta < S/87.72)
  Tarjeta internacional: 3.99% + IGV
  Yape / Plin / QR:      negociable (parte del checkout multipago)
  PagoEfectivo:          negociable
  Cuotéalo:              negociable
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURACIÓN
# ─────────────────────────────────────────────────────────────────────────────

CULQI_API_BASE   = "https://api.culqi.com/v2"
CULQI_API_SECURE = "https://secure.culqi.com/v2"  # para operaciones con encriptación RSA


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


class CulqiConfig:
    """Configuración centralizada. Instanciar una vez por proyecto."""

    def __init__(
        self,
        sk: str | None = None,
        pk: str | None = None,
        rsa_id: str | None = None,
        rsa_key: str | None = None,
        sandbox: bool | None = None,
    ):
        self.sk       = sk      or _env("CULQI_SK")
        self.pk       = pk      or _env("CULQI_PK")
        self.rsa_id   = rsa_id  or _env("CULQI_RSA_ID")
        self.rsa_key  = rsa_key or _env("CULQI_RSA_KEY")
        sandbox_env   = _env("CULQI_SANDBOX", "true").lower()
        self.sandbox  = sandbox if sandbox is not None else (sandbox_env != "false")
        self.base_url = _env("APP_BASE_URL", "http://localhost:8000")

        if not self.sk:
            raise ValueError("CULQI_SK no configurado")

    @property
    def headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.sk}",
            "Content-Type":  "application/json",
        }

    def __repr__(self):
        modo = "SANDBOX" if self.sandbox else "PRODUCCIÓN"
        return f"<CulqiConfig {modo} pk={self.pk[:12]}...>"


# Instancia global (se puede sobrescribir en tests)
_config: CulqiConfig | None = None


def get_config() -> CulqiConfig:
    global _config
    if _config is None:
        _config = CulqiConfig()
    return _config


def set_config(cfg: CulqiConfig) -> None:
    """Para tests o multi-tenant con distintas llaves."""
    global _config
    _config = cfg


# ─────────────────────────────────────────────────────────────────────────────
# TIPOS / DATACLASSES
# ─────────────────────────────────────────────────────────────────────────────

class EstadoCargo(str, Enum):
    PAGADO    = "paid"
    PENDIENTE = "pending"
    DECLINADO = "declined"
    EXPIRADO  = "expired"
    ANULADO   = "annulled"


class EstadoOrden(str, Enum):
    PENDIENTE = "pending"
    PAGADO    = "paid"
    EXPIRADO  = "expired"
    ELIMINADO = "deleted"


@dataclass
class ResultadoCargo:
    """Resultado de crear_cargo_con_token()."""
    exito:          bool
    cargo_id:       Optional[str]   = None   # tkn_live_xxxx o tkn_test_xxxx
    monto:          Optional[float] = None
    moneda:         str             = "PEN"
    estado:         Optional[str]   = None
    email:          Optional[str]   = None
    referencia:     Optional[str]   = None   # order_id / referencia interna
    error_codigo:   Optional[str]   = None
    error_mensaje:  Optional[str]   = None
    raw:            dict            = field(default_factory=dict)


@dataclass
class ResultadoOrden:
    """Resultado de crear_orden() para Yape/Plin/PagoEfectivo."""
    exito:          bool
    order_id:       Optional[str]   = None   # ord_live_xxxx
    order_code:     Optional[str]   = None   # código corto legible
    monto:          Optional[float] = None
    moneda:         str             = "PEN"
    estado:         Optional[str]   = None
    expiracion:     Optional[int]   = None   # unix timestamp
    error_codigo:   Optional[str]   = None
    error_mensaje:  Optional[str]   = None
    raw:            dict            = field(default_factory=dict)


@dataclass
class ResultadoDevolucion:
    """Resultado de devolver_cargo()."""
    exito:          bool
    devolucion_id:  Optional[str]   = None
    monto:          Optional[float] = None
    estado:         Optional[str]   = None
    error_codigo:   Optional[str]   = None
    error_mensaje:  Optional[str]   = None
    raw:            dict            = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS INTERNOS
# ─────────────────────────────────────────────────────────────────────────────

def _soles_a_centimos(monto: float) -> int:
    """Culqi trabaja en centavos (int). S/10.50 → 1050."""
    return int(round(monto * 100))


def _centimos_a_soles(centimos: int) -> float:
    return centimos / 100.0


async def _post(endpoint: str, payload: dict, cfg: CulqiConfig) -> dict:
    """POST async a la API de Culqi."""
    url = f"{CULQI_API_BASE}{endpoint}"
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.post(url, json=payload, headers=cfg.headers)
            data = resp.json()
            if not resp.is_success:
                logger.error(f"Culqi {endpoint} HTTP {resp.status_code}: {data}")
            return data
        except httpx.TimeoutException:
            logger.error(f"Culqi {endpoint}: timeout")
            return {"object": "error", "user_message": "Timeout conectando con Culqi"}
        except Exception as e:
            logger.exception(f"Culqi {endpoint}: {e}")
            return {"object": "error", "user_message": str(e)}


async def _get(endpoint: str, cfg: CulqiConfig) -> dict:
    """GET async a la API de Culqi."""
    url = f"{CULQI_API_BASE}{endpoint}"
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.get(url, headers=cfg.headers)
            return resp.json()
        except Exception as e:
            logger.exception(f"Culqi GET {endpoint}: {e}")
            return {"object": "error", "user_message": str(e)}


def _es_error(data: dict) -> bool:
    return data.get("object") == "error" or "merchant_message" in data


def _extraer_error(data: dict) -> tuple[str, str]:
    """Retorna (codigo, mensaje_usuario)."""
    code    = data.get("code", "CULQI_ERROR")
    mensaje = data.get("user_message") or data.get("merchant_message") or "Error en pasarela de pago"
    return code, mensaje


# ─────────────────────────────────────────────────────────────────────────────
# FLUJO TARJETA — crear_cargo_con_token()
# ─────────────────────────────────────────────────────────────────────────────

async def crear_cargo_con_token(
    token_id:    str,
    monto:       float,
    email:       str,
    descripcion: str,
    referencia:  str,
    *,
    moneda:      str             = "PEN",
    metadata:    dict | None     = None,
    cfg:         CulqiConfig | None = None,
) -> ResultadoCargo:
    """
    Crea un cargo con el token generado por el frontend (Culqi JS).

    El frontend debe haber llamado a Culqi.createToken() y enviado el token_id
    al backend. Este método es el paso final del flujo de tarjeta.

    Args:
        token_id:    ID del token generado por Culqi JS ('tkn_test_xxxx')
        monto:       Monto en soles (ej: 250.00)
        email:       Email del pagador
        descripcion: Descripción breve del cargo (max 150 chars)
        referencia:  Referencia interna (ej: 'CCPL-PAYMENT-88')
        moneda:      'PEN' (default) o 'USD'
        metadata:    Dict con datos adicionales para trazabilidad (max 20 claves)
        cfg:         Config Culqi (usa get_config() si no se pasa)

    Returns:
        ResultadoCargo

    Ejemplo de uso en router FastAPI:
        token_id = form.token_id   # enviado por el frontend
        resultado = await crear_cargo_con_token(
            token_id    = token_id,
            monto       = payment.amount,
            email       = colegiado.email,
            descripcion = f"Pago CCPL - {colegiado.apellidos_nombres[:50]}",
            referencia  = f"CCPL-PAY-{payment.id}",
            metadata    = {"payment_id": payment.id, "colegiado_id": colegiado.id},
        )
    """
    cfg = cfg or get_config()

    payload = {
        "amount":       _soles_a_centimos(monto),
        "currency_code": moneda,
        "email":        email,
        "source_id":    token_id,
        "description":  descripcion[:150],
        "capture":      True,
        "metadata":     metadata or {},
    }

    logger.info(f"Culqi crear_cargo: ref={referencia} monto={monto} email={email[:20]}...")
    data = await _post("/charges", payload, cfg)

    if _es_error(data):
        code, msg = _extraer_error(data)
        logger.warning(f"Culqi cargo fallido: {code} — {msg}")
        return ResultadoCargo(exito=False, error_codigo=code, error_mensaje=msg, raw=data)

    return ResultadoCargo(
        exito      = True,
        cargo_id   = data.get("id"),
        monto      = _centimos_a_soles(data.get("amount", 0)),
        moneda     = data.get("currency_code", moneda),
        estado     = data.get("outcome", {}).get("type"),
        email      = data.get("email"),
        referencia = referencia,
        raw        = data,
    )


# ─────────────────────────────────────────────────────────────────────────────
# FLUJO YAPE/PLIN/PAGOEFECTIVO — crear_orden()
# ─────────────────────────────────────────────────────────────────────────────

async def crear_orden(
    monto:           float,
    descripcion:     str,
    referencia:      str,
    *,
    moneda:          str             = "PEN",
    expiracion_mins: int             = 30,
    metadata:        dict | None     = None,
    cfg:             CulqiConfig | None = None,
) -> ResultadoOrden:
    """
    Crea una Orden de Pago para Yape, Plin, PagoEfectivo o Cuotéalo.

    La Orden se crea en el backend y el order_id se envía al frontend,
    donde Culqi Checkout JS muestra las opciones de billetera/QR.
    Culqi notifica el pago completado via webhook (order.status.changed).

    Args:
        monto:           Monto en soles
        descripcion:     Descripción del cobro
        referencia:      Referencia interna (ej: 'CCPL-PAY-88')
        moneda:          'PEN' (default)
        expiracion_mins: Minutos hasta que la orden expira (default: 30)
        metadata:        Datos adicionales
        cfg:             Config Culqi

    Returns:
        ResultadoOrden con order_id para pasar al frontend JS

    Ejemplo en router FastAPI:
        orden = await crear_orden(
            monto       = 810.00,
            descripcion = "Pago cuotas CCPL",
            referencia  = f"CCPL-PAY-{payment.id}",
            metadata    = {"payment_id": payment.id},
        )
        if orden.exito:
            return {"order_id": orden.order_id, "pk": get_config().pk, "rsa_id": get_config().rsa_id}

    Frontend JS (pasado al Culqi Checkout):
        Culqi.settings({
            currency: 'PEN',
            amount: 81000,        // centavos
            order: 'ord_live_xxx' // order_id del backend
        });
    """
    cfg = cfg or get_config()

    import time
    expiracion_ts = int(time.time()) + (expiracion_mins * 60)

    payload = {
        "amount":           _soles_a_centimos(monto),
        "currency_code":    moneda,
        "description":      descripcion[:250],
        "order_number":     referencia,
        "client_details":   {"first_name": "", "last_name": "", "email": "", "phone_number": ""},
        "expiration_date":  expiracion_ts,
        "confirm":          False,  # False = no confirmar automáticamente
        "metadata":         metadata or {},
    }

    logger.info(f"Culqi crear_orden: ref={referencia} monto={monto}")
    data = await _post("/orders", payload, cfg)

    if _es_error(data):
        code, msg = _extraer_error(data)
        logger.warning(f"Culqi orden fallida: {code} — {msg}")
        return ResultadoOrden(exito=False, error_codigo=code, error_mensaje=msg, raw=data)

    return ResultadoOrden(
        exito      = True,
        order_id   = data.get("id"),
        order_code = data.get("order_number"),
        monto      = _centimos_a_soles(data.get("amount", 0)),
        moneda     = data.get("currency_code", moneda),
        estado     = data.get("state"),
        expiracion = data.get("expiration_date"),
        raw        = data,
    )


async def consultar_orden(order_id: str, cfg: CulqiConfig | None = None) -> dict:
    """Consulta el estado actual de una orden."""
    cfg = cfg or get_config()
    return await _get(f"/orders/{order_id}", cfg)


# ─────────────────────────────────────────────────────────────────────────────
# CONSULTAR CARGO
# ─────────────────────────────────────────────────────────────────────────────

async def consultar_cargo(cargo_id: str, cfg: CulqiConfig | None = None) -> dict:
    """Consulta el detalle de un cargo existente."""
    cfg = cfg or get_config()
    return await _get(f"/charges/{cargo_id}", cfg)


# ─────────────────────────────────────────────────────────────────────────────
# DEVOLUCIONES
# ─────────────────────────────────────────────────────────────────────────────

async def devolver_cargo(
    cargo_id: str,
    monto:    float | None = None,   # None = devolución total
    razon:    str          = "requested_by_customer",
    cfg:      CulqiConfig | None = None,
) -> ResultadoDevolucion:
    """
    Genera una devolución (parcial o total) sobre un cargo.

    Args:
        cargo_id: ID del cargo original ('c_live_xxxx')
        monto:    Monto a devolver en soles. None = devolver todo.
        razon:    'requested_by_customer' | 'duplicate' | 'fraudulent'
    """
    cfg = cfg or get_config()

    payload: dict[str, Any] = {"reason": razon}
    if monto is not None:
        payload["amount"] = _soles_a_centimos(monto)

    data = await _post(f"/charges/{cargo_id}/refunds", payload, cfg)

    if _es_error(data):
        code, msg = _extraer_error(data)
        return ResultadoDevolucion(exito=False, error_codigo=code, error_mensaje=msg, raw=data)

    return ResultadoDevolucion(
        exito         = True,
        devolucion_id = data.get("id"),
        monto         = _centimos_a_soles(data.get("amount", 0)),
        estado        = data.get("outcome", {}).get("type"),
        raw           = data,
    )


# ─────────────────────────────────────────────────────────────────────────────
# VERIFICACIÓN DE WEBHOOK
# ─────────────────────────────────────────────────────────────────────────────

def verificar_firma_webhook(
    payload_bytes: bytes,
    firma_header:  str,
    secret:        str | None = None,
    cfg:           CulqiConfig | None = None,
) -> bool:
    """
    Verifica la firma HMAC-SHA256 del webhook de Culqi.

    Culqi envía el header 'x-culqi-signature' con el HMAC del body.
    Usar el CULQI_WEBHOOK_SECRET configurado en CulqiPanel → Eventos → Webhooks.

    Args:
        payload_bytes: body crudo de la request (await request.body())
        firma_header:  valor del header 'x-culqi-signature'
        secret:        CULQI_WEBHOOK_SECRET (o se lee de env)

    Uso en router FastAPI:
        body  = await request.body()
        firma = request.headers.get("x-culqi-signature", "")
        if not verificar_firma_webhook(body, firma):
            raise HTTPException(status_code=403, detail="Firma inválida")
    """
    webhook_secret = secret or _env("CULQI_WEBHOOK_SECRET")
    if not webhook_secret:
        logger.warning("CULQI_WEBHOOK_SECRET no configurado — saltando verificación")
        return True  # En sandbox sin secret configurado, aceptar

    expected = hmac.new(
        webhook_secret.encode("utf-8"),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, firma_header.lower())


def parsear_evento_webhook(body: bytes | str) -> dict:
    """
    Parsea el body del webhook de Culqi a dict.

    Tipos de evento relevantes:
        charge.creation.succeeded    → cargo con tarjeta exitoso
        charge.creation.failed       → cargo con tarjeta fallido
        order.status.changed         → orden Yape/Plin/PagoEfectivo cambia estado

    Estructura del evento:
        {
          "type": "charge.creation.succeeded",
          "data": {
            "id": "c_live_xxxx",
            "amount": 81000,
            "currency_code": "PEN",
            "email": "...",
            "metadata": {"payment_id": 88, ...},
            ...
          }
        }
    """
    if isinstance(body, bytes):
        body = body.decode("utf-8")
    return json.loads(body)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS PARA EL FRONTEND
# ─────────────────────────────────────────────────────────────────────────────

def get_culqi_config_frontend(cfg: CulqiConfig | None = None) -> dict:
    """
    Retorna la configuración necesaria para inicializar el Culqi Checkout
    en el frontend. Llamar desde el router y pasar al template.

    En el template Jinja2:
        <script>
          Culqi.publicKey = "{{ culqi_cfg.pk }}";
          // Para órdenes con Yape/Plin:
          Culqi.settings({
            currency: 'PEN',
            amount: {{ monto_centavos }},
            order: "{{ order_id }}",
            xculqirsaid: "{{ culqi_cfg.rsa_id }}",
            rsapublickey: "{{ culqi_cfg.rsa_key }}",
          });
        </script>
    """
    cfg = cfg or get_config()
    return {
        "pk":        cfg.pk,
        "rsa_id":    cfg.rsa_id,
        "rsa_key":   cfg.rsa_key,
        "sandbox":   cfg.sandbox,
        "script_url": "https://checkout.culqi.com/js/v4",
    }


# ─────────────────────────────────────────────────────────────────────────────
# CONSTRUCCIÓN DE order_number (referencia interna)
# ─────────────────────────────────────────────────────────────────────────────

def construir_order_number(
    prefijo:    str,
    payment_id: int,
    extra:      str = "",
) -> str:
    """
    Construye un order_number único para Culqi (max 100 chars).

    Ejemplos:
        construir_order_number("CCPL", 88)        → "CCPL-PAY-88"
        construir_order_number("QVEND", 12, "F")  → "QVEND-PAY-12-F"
        construir_order_number("METR", 45)        → "METR-PAY-45"
    """
    partes = [prefijo.upper(), "PAY", str(payment_id)]
    if extra:
        partes.append(str(extra).upper())
    return "-".join(partes)[:100]


# ─────────────────────────────────────────────────────────────────────────────
# GUÍA DE INTEGRACIÓN EN ROUTER FASTAPI
# ─────────────────────────────────────────────────────────────────────────────
"""
═══════════════════════════════════════════════════════════════════════════════
FLUJO 1 — TARJETA (sin Yape/Plin)
═══════════════════════════════════════════════════════════════════════════════

FRONTEND (template HTML):
─────────────────────────
    <script src="https://checkout.culqi.com/js/v4"></script>
    <script>
        // Configurar con los valores del backend
        Culqi.publicKey = "{{ culqi_cfg.pk }}";
        Culqi.settings({
            currency: 'PEN',
            amount: {{ monto_centavos }},
            xculqirsaid: "{{ culqi_cfg.rsa_id }}",
            rsapublickey: "{{ culqi_cfg.rsa_key }}",
        });

        // Cuando el usuario completa el formulario, Culqi llama a culqi():
        function culqi() {
            if (Culqi.token) {
                // Enviar token al backend
                fetch('/pagos/culqi/cargo', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        token_id: Culqi.token.id,
                        payment_id: {{ payment_id }},
                    })
                }).then(r => r.json()).then(data => {
                    if (data.exito) window.location = '/pagos/resultado?payment=' + data.payment_id;
                    else mostrarError(data.mensaje);
                });
                Culqi.close();
            } else if (Culqi.order) {
                console.log('Orden completada:', Culqi.order);
            }
        }

        document.getElementById('btn-pagar').addEventListener('click', () => Culqi.open());
    </script>
    <button id="btn-pagar">Pagar con tarjeta</button>

BACKEND (router FastAPI):
─────────────────────────
    @router.post("/pagos/culqi/cargo")
    async def culqi_cargo(
        request: Request,
        token_id: str = Body(...),
        payment_id: int = Body(...),
        db: Session = Depends(get_db),
    ):
        payment = db.query(Payment).get(payment_id)
        colegiado = db.query(Colegiado).get(payment.colegiado_id)

        resultado = await crear_cargo_con_token(
            token_id    = token_id,
            monto       = float(payment.amount),
            email       = colegiado.email or "sinregistro@ccpl.pe",
            descripcion = f"Pago CCPL - {colegiado.apellidos_nombres[:40]}",
            referencia  = construir_order_number("CCPL", payment.id),
            metadata    = {"payment_id": payment.id, "colegiado_id": colegiado.id},
        )

        if resultado.exito:
            payment.status = "pagado"
            payment.openpay_transaction_id = resultado.cargo_id  # reusar campo existente
            db.commit()
            # recalcular habilidad...
            return {"exito": True, "payment_id": payment_id}
        else:
            return {"exito": False, "mensaje": resultado.error_mensaje}


═══════════════════════════════════════════════════════════════════════════════
FLUJO 2 — YAPE / PLIN / PAGOEFECTIVO
═══════════════════════════════════════════════════════════════════════════════

BACKEND — endpoint para crear la orden:
    @router.post("/pagos/culqi/orden")
    async def culqi_crear_orden(payment_id: int = Form(...), db: Session = Depends(get_db)):
        payment = db.query(Payment).get(payment_id)
        orden = await crear_orden(
            monto       = float(payment.amount),
            descripcion = "Pago cuotas CCPL",
            referencia  = construir_order_number("CCPL", payment.id),
            metadata    = {"payment_id": payment.id},
        )
        if not orden.exito:
            raise HTTPException(400, detail=orden.error_mensaje)

        payment.status = "esperando_pago"
        payment.openpay_transaction_id = orden.order_id
        db.commit()

        culqi_cfg = get_culqi_config_frontend()
        return {
            "order_id":      orden.order_id,
            "monto_centavos": int(payment.amount * 100),
            "culqi_cfg":     culqi_cfg,
        }

BACKEND — webhook:
    @router.post("/pagos/culqi/webhook")
    async def culqi_webhook(request: Request, db: Session = Depends(get_db)):
        body  = await request.body()
        firma = request.headers.get("x-culqi-signature", "")

        if not verificar_firma_webhook(body, firma):
            raise HTTPException(403, detail="Firma inválida")

        evento = parsear_evento_webhook(body)
        tipo   = evento.get("type")
        data   = evento.get("data", {})

        # Cargo con tarjeta exitoso
        if tipo == "charge.creation.succeeded":
            cargo_id   = data.get("id")
            metadata   = data.get("metadata", {})
            payment_id = metadata.get("payment_id")
            if payment_id:
                payment = db.query(Payment).get(payment_id)
                if payment:
                    payment.status = "pagado"
                    payment.openpay_transaction_id = cargo_id
                    db.commit()
                    # imputar_pago_a_deudas(...)
                    # evaluar_habilidad(...)

        # Orden Yape/Plin pagada
        elif tipo == "order.status.changed":
            order_id = data.get("id")
            estado   = data.get("state")
            if estado == "paid":
                payment = db.query(Payment).filter(
                    Payment.openpay_transaction_id == order_id
                ).first()
                if payment:
                    payment.status = "pagado"
                    db.commit()
                    # imputar_pago_a_deudas(...)
                    # evaluar_habilidad(...)

        return {"ok": True}
"""
"""
app/utils/candado_facturalo.py — Tanda 20 (PROPUESTA, no aplicada).

CANDADO: fuera de producción NUNCA se llama al Facturalo real, aunque la URL y la llave guardadas en la base
(configuracion_facturacion) sean las reales — por ejemplo, al levantar en local un volcado de producción.

  · ENVIRONMENT = production (exacto, sin importar mayúsculas/espacios) → este módulo NO HACE NADA:
    no importa nada extra, no parcha nada, no agrega rutas. Producción queda byte-idéntica.
  · Cualquier otro valor, o sin la variable ("si hay duda, simulador") → candado ACTIVO:
    toda petición httpx (síncrona o asíncrona) que parezca ir a Facturalo y NO vaya a loopback se REDIRIGE al
    simulador de la propia app (/sandbox/facturalo). La llave real se reemplaza por la del simulador y el secreto
    se quita: ni siquiera viajan por loopback.

"Parece ir a Facturalo" (ante la duda, sí): lleva cabecera X-API-Key o X-API-Secret (en esta app solo Facturalo
las usa), o el host contiene "facturalo". Loopback (127.0.0.1, localhost, ::1) se deja pasar: ya es un simulador
(el del banco de escenarios en :8765, o el de la propia app).

No toca facturacion.py, caja.py, openpay.py ni ninguna regla de negocio: actúa debajo de ellos, en httpx.
En sandbox/demo convive con el cortafuegos de sandbox.py: el candado redirige ANTES (queda más externo) y la
petición ya va a loopback, que el cortafuegos permite.
"""
import os

ACTIVO = False
REDIRIGIDAS = []          # registro para pruebas (sin datos personales: método, host original, ruta)


def es_produccion():
    return os.getenv("ENVIRONMENT", "").strip().lower() == "production"


def activar_temprano():
    """Se llama al inicio de main.py, justo después de sandbox.activar_temprano() y ANTES de importar routers."""
    global ACTIVO
    if es_produccion() or ACTIVO:
        return
    ACTIVO = True
    from urllib.parse import urlparse
    import httpx
    from app.utils import sandbox as _sbx

    loop = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}

    def _destino():
        return (os.getenv("SANDBOX_FACTURALO_URL")
                or "http://127.0.0.1:%s%s" % (os.getenv("PORT", "8000"), _sbx.RUTA_FACTURALO)).rstrip("/")

    def _es_facturalo(req):
        h = (req.url.host or "").lower()
        if h in loop:
            return False
        return ("x-api-key" in req.headers or "x-api-secret" in req.headers or "facturalo" in h)

    def _redirigir(req):
        base = urlparse(_destino())
        ruta = req.url.path
        i = ruta.find("/comprobantes")                 # .../api/v1/comprobantes/... → /sandbox/facturalo/comprobantes/...
        cola = ruta[i:] if i >= 0 else "/comprobantes"
        REDIRIGIDAS.append({"metodo": req.method, "host_original": req.url.host, "ruta": cola[:60]})
        print("🔒 CANDADO FACTURALO: %s %s → simulador" % (req.method, req.url.host), flush=True)
        req.url = req.url.copy_with(scheme=base.scheme, host=base.hostname, port=base.port,
                                    path=(base.path or "") + cola)
        req.headers["host"] = "%s:%s" % (base.hostname, base.port) if base.port else base.hostname
        req.headers["x-api-key"] = _sbx.TOKEN_FACTURALO
        if "x-api-secret" in req.headers:
            del req.headers["x-api-secret"]
        return req

    _send_sync = httpx.Client.send
    _send_async = httpx.AsyncClient.send

    def send_sync(self, request, *a, **k):
        if _es_facturalo(request):
            request = _redirigir(request)
        return _send_sync(self, request, *a, **k)

    async def send_async(self, request, *a, **k):
        if _es_facturalo(request):
            request = _redirigir(request)
        return await _send_async(self, request, *a, **k)

    httpx.Client.send = send_sync
    httpx.AsyncClient.send = send_async
    print("🔒 CANDADO FACTURALO activo (ENVIRONMENT=%s): nada sale al Facturalo real"
          % (os.getenv("ENVIRONMENT") or "(sin definir)"), flush=True)


def instalar(app):
    """Se llama al FINAL de main.py, después de sandbox.instalar(app). En producción no hace nada.
    En sandbox/demo el simulador ya lo instala sandbox.py. En local (desarrollo) instala el mismo simulador para
    que las peticiones redirigidas tengan a dónde llegar (solo acepta loopback)."""
    if es_produccion():
        return
    from app.utils import sandbox as _sbx
    if _sbx.ES_SANDBOX:
        return
    _sbx.instalar_simulador_facturalo(app, solo_loopback=True)

"""
app/utils/sandbox.py — Ambiente de prueba (ENVIRONMENT=sandbox).

Fuera del sandbox este módulo NO HACE NADA: `activar_temprano()` e `instalar(app)`
regresan de inmediato si ENVIRONMENT no es exactamente "sandbox" o "demo". Producción no cambia.
ENVIRONMENT=demo (demostración para videos públicos) se comporta igual que el sandbox, con su propia
franja «DEMOSTRACIÓN — datos ficticios» y exige una base enmascarada y verificada (preparar_demo.py).

Dentro del sandbox, sin excepción:
  1. Ninguna comunicación sale hacia colegiados reales:
     - push web: `pywebpush.webpush` se reemplaza por una función que solo anota;
     - correo: `smtplib.SMTP` / `SMTP_SSL` lanzan SandboxBloqueado;
     - WhatsApp / SMS / cualquier API externa: cortafuegos de salida con lista de
       permitidos (BD, Redis, la propia app, sandbox-api.openpay.pe y lo que se agregue
       en SANDBOX_HOSTS_PERMITIDOS). Se aplica en tres capas: sockets de Python,
       httpx (síncrono y asíncrono) y requests.
  2. Todo el sitio exige inicio de sesión, también las páginas y consultas públicas.
     Solo entran las cuentas de prueba registradas en
     organizations.config['sandbox_testers'] (ids de members). Una cuenta real copiada
     de producción NO entra aunque su clave sea correcta.
  3. noindex: cabecera X-Robots-Tag en toda respuesta, <meta name="robots"> en cada
     página y /robots.txt con Disallow total.
  4. Franja fija "AMBIENTE DE PRUEBA — no es el sistema real" en todas las páginas.
  5. Facturalo simulado dentro de la misma app (/sandbox/facturalo/...): no se envía
     nada a SUNAT ni a Facturalo. OpenPay forzado a modo sandbox.
  6. Seguro de arranque: la app NO arranca si la base no tiene la marca de sandbox
     (organizations.config['sandbox'] = true, que pone el script de restauración) o si
     la configuración de Facturalo no apunta al simulador. Así un sandbox nunca puede
     quedar conectado por error a la base de producción.

No toca facturacion.py, tenant_middleware ni ninguna regla de negocio.
"""
import json
import os
import socket
import threading
import time
from urllib.parse import urlparse

_ENTORNO = os.getenv("ENVIRONMENT", "").strip().lower()
# Demostración (videos públicos): se comporta EXACTAMENTE como el sandbox (sin comunicaciones externas, Facturalo
# simulado, noindex, solo cuentas de prueba) sobre una base con datos ficticios (preparar_demo.py). Cambian la
# franja, la pantalla de ingreso y el seguro de arranque (exige la marca de demo y la verificación aprobada).
ES_DEMO = _ENTORNO == "demo"
ES_SANDBOX = _ENTORNO in ("sandbox", "demo")

TEXTO_FRANJA = "DEMOSTRACIÓN — datos ficticios" if ES_DEMO else "AMBIENTE DE PRUEBA — no es el sistema real"
TOKEN_FACTURALO = "SANDBOX-SIMULADO"
RUTA_FACTURALO = "/sandbox/facturalo"
RUTA_INGRESO = "/sandbox/ingresar"

# Registro de lo que se bloqueó (lo leen las pruebas; no lleva datos personales).
BLOQUEOS = []
PUSH_SIMULADOS = []


class SandboxBloqueado(OSError):
    """Comunicación externa bloqueada en el sandbox."""


def _anotar(canal, destino):
    BLOQUEOS.append({"canal": canal, "destino": str(destino)[:120], "t": time.time()})
    try:
        print("🧪 SANDBOX: bloqueado %s → %s" % (canal, str(destino)[:80]))
    except Exception:
        pass


# ───────────────────────── Cortafuegos de salida ─────────────────────────
_LOOPBACK = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
_HOSTS_OK = set(_LOOPBACK)
_IPS_OK = set(_LOOPBACK)


def _host_de_url(u):
    try:
        return (urlparse(u).hostname or "").lower()
    except Exception:
        return ""


def _armar_permitidos():
    for var in ("DATABASE_URL", "REDIS_URL"):
        h = _host_de_url(os.getenv(var) or "")
        if h:
            _HOSTS_OK.add(h)
    _HOSTS_OK.add("sandbox-api.openpay.pe")
    for h in (os.getenv("SANDBOX_HOSTS_PERMITIDOS") or "").split(","):
        if h.strip():
            _HOSTS_OK.add(h.strip().lower())


def host_permitido(host):
    h = (host or "").lower().strip("[]")
    return h in _HOSTS_OK or h in _IPS_OK


def _canal_por_host(host):
    h = (host or "").lower()
    if any(x in h for x in ("whatsapp", "graph.facebook", "wa.me", "ultramsg", "wati", "gupshup")):
        return "whatsapp"
    if any(x in h for x in ("twilio", "sns.", "nexmo", "vonage", "sms", "infobip", "messagebird")):
        return "sms"
    if any(x in h for x in ("smtp", "mail", "sendgrid", "mailgun", "resend", "postmark", "ses.")):
        return "correo"
    if any(x in h for x in ("fcm.googleapis", "push.services.mozilla", "notify.windows", "push.apple", "web.push.apple")):
        return "push"
    return "red"


_gai_real = socket.getaddrinfo
_connect_real = socket.socket.connect
_connect_ex_real = socket.socket.connect_ex


def _gai_sandbox(host, *a, **k):
    if host is None:
        return _gai_real(host, *a, **k)
    h = host.decode() if isinstance(host, bytes) else str(host)
    if not host_permitido(h):
        _anotar(_canal_por_host(h), h)
        raise SandboxBloqueado("SANDBOX: salida a %s bloqueada" % h)
    res = _gai_real(host, *a, **k)
    for r in res:
        try:
            _IPS_OK.add(str(r[4][0]).lower())
        except Exception:
            pass
    return res


def _destino_ok(address):
    if not isinstance(address, tuple):      # socket unix u otros: locales
        return True
    return host_permitido(str(address[0]))


def _connect_sandbox(self, address, *a, **k):
    if not _destino_ok(address):
        _anotar(_canal_por_host(str(address[0])), address[0])
        raise SandboxBloqueado("SANDBOX: conexión a %s bloqueada" % (address[0],))
    return _connect_real(self, address, *a, **k)


def _connect_ex_sandbox(self, address, *a, **k):
    if not _destino_ok(address):
        _anotar(_canal_por_host(str(address[0])), address[0])
        raise SandboxBloqueado("SANDBOX: conexión a %s bloqueada" % (address[0],))
    return _connect_ex_real(self, address, *a, **k)


def _vigilar_url(url, canal_lib):
    h = _host_de_url(str(url))
    if h and not host_permitido(h):
        _anotar(_canal_por_host(h) if _canal_por_host(h) != "red" else canal_lib, h)
        raise SandboxBloqueado("SANDBOX: salida a %s bloqueada" % h)


def _parchar_librerias():
    # httpx (lo usan Facturalo, OpenPay y otros)
    try:
        import httpx
        _send_sync = httpx.Client.send
        _send_async = httpx.AsyncClient.send

        def _interno(cliente):
            # Transportes que NO salen a la red (cliente de pruebas, ASGI/WSGI en proceso).
            return type(getattr(cliente, "_transport", None)).__name__ in ("_TestClientTransport", "ASGITransport", "WSGITransport")

        def send_sync(self, request, *a, **k):
            if not _interno(self):
                _vigilar_url(request.url, "red")
            return _send_sync(self, request, *a, **k)

        async def send_async(self, request, *a, **k):
            if not _interno(self):
                _vigilar_url(request.url, "red")
            return await _send_async(self, request, *a, **k)

        httpx.Client.send = send_sync
        httpx.AsyncClient.send = send_async
    except Exception:
        pass
    # requests (lo usa pywebpush por dentro, y algunos routers)
    try:
        import requests
        _req_send = requests.Session.send

        def req_send(self, request, *a, **k):
            _vigilar_url(request.url, "red")
            return _req_send(self, request, *a, **k)

        requests.Session.send = req_send
    except Exception:
        pass
    # correo
    import smtplib

    class _SMTPBloqueado:
        def __init__(self, host="", *a, **k):
            _anotar("correo", host or "smtp")
            raise SandboxBloqueado("SANDBOX: envío de correo bloqueado")

    smtplib.SMTP = _SMTPBloqueado
    smtplib.SMTP_SSL = _SMTPBloqueado
    # push web
    try:
        import pywebpush

        def webpush_simulado(subscription_info=None, data=None, *a, **k):
            ep = (subscription_info or {}).get("endpoint", "") if isinstance(subscription_info, dict) else ""
            PUSH_SIMULADOS.append({"host": _host_de_url(ep), "t": time.time()})
            _anotar("push", _host_de_url(ep) or "push")

            class _R:
                status_code = 201
                text = "SANDBOX: push no enviado"
                ok = True
            return _R()

        pywebpush.webpush = webpush_simulado
    except Exception:
        pass


_ACTIVADO = False


def activar_temprano():
    """Se llama al inicio de main.py, ANTES de importar los routers (algunos hacen
    `from pywebpush import webpush` al importarse). Fuera del sandbox no hace nada."""
    global _ACTIVADO
    if not ES_SANDBOX or _ACTIVADO:
        return
    _ACTIVADO = True
    os.environ["OPENPAY_SANDBOX"] = "true"          # OpenPay siempre en modo sandbox
    _armar_permitidos()
    socket.getaddrinfo = _gai_sandbox
    socket.socket.connect = _connect_sandbox
    socket.socket.connect_ex = _connect_ex_sandbox
    _parchar_librerias()
    print("🧪 SANDBOX activo: comunicaciones externas bloqueadas; permitidos: %s" % sorted(_HOSTS_OK))


# ───────────────────────── Seguro de arranque ─────────────────────────
def url_facturalo_simulado():
    return os.getenv("SANDBOX_FACTURALO_URL") or ("http://127.0.0.1:%s%s" % (os.getenv("PORT", "8000"), RUTA_FACTURALO))


def verificar_base(engine):
    """La app no arranca si la base no es un sandbox preparado. Devuelve el resumen."""
    from sqlalchemy import text
    with engine.connect() as c:
        orgs = c.execute(text("SELECT id, config FROM organizations ORDER BY id")).fetchall()
        sin_marca = [o.id for o in orgs if not ((o.config or {}).get("sandbox") is True)]
        if not orgs or sin_marca:
            raise RuntimeError("SANDBOX: la base no tiene la marca de sandbox (organizaciones %s). "
                               "¿Está apuntando a producción? Restaure con el script de sandbox." % sin_marca)
        if ES_DEMO:
            # La demo solo arranca sobre una base ENMASCARADA y VERIFICADA (preparar_demo.py): nunca sobre el sandbox
            # (datos reales) ni sobre producción.
            sin_demo = [o.id for o in orgs if not ((o.config or {}).get("demo") is True
                                                   and (o.config or {}).get("demo_verificado") is True)]
            if sin_demo:
                raise RuntimeError("DEMO: la base no está enmascarada y verificada (organizaciones %s). "
                                   "Prepárela con preparar_demo.py." % sin_demo)
        fac = c.execute(text("SELECT id, facturalo_url FROM configuracion_facturacion")).fetchall()
        malos = [f.id for f in fac if not str(f.facturalo_url or "").rstrip("/").endswith(RUTA_FACTURALO)]
        if malos:
            raise RuntimeError("SANDBOX: configuracion_facturacion %s no apunta al Facturalo simulado." % malos)
        testers = sorted({int(x) for o in orgs for x in ((o.config or {}).get("sandbox_testers") or [])})
        hosts = sorted({str(h).lower() for o in orgs for h in ((o.config or {}).get("sandbox_hosts") or [])})
    # El simulador vive en ESTA instancia: se ajusta solo el puerto (Railway asigna PORT).
    # Únicamente toca filas que YA apuntan al simulador; nunca una URL real.
    url = url_facturalo_simulado().rstrip("/")
    with engine.begin() as c:
        c.execute(text("""UPDATE configuracion_facturacion SET facturalo_url = :u
                          WHERE rtrim(facturalo_url, '/') LIKE :pat AND rtrim(facturalo_url, '/') <> :u"""),
                  {"u": url, "pat": "%" + RUTA_FACTURALO})
    return {"organizaciones": len(orgs), "testers": len(testers), "direcciones": hosts}


# ───────────────── Dirección del sandbox → organización (mapeo en la BASE del sandbox) ─────────────────
_cache_hosts = {"t": 0.0, "mapa": {}}


def _org_por_host(host):
    """organizations.config['sandbox_hosts'] (lo registra el script de restauración)."""
    if time.time() - _cache_hosts["t"] > 60:
        from sqlalchemy import text
        from app.database import SessionLocal
        db = SessionLocal()
        try:
            mapa = {}
            for r in db.execute(text("SELECT id, name, type, slug, theme_color, logo_url, config FROM organizations")).fetchall():
                for h in ((r.config or {}).get("sandbox_hosts") or []):
                    mapa[str(h).lower()] = {"id": r.id, "name": r.name, "type": r.type, "slug": r.slug,
                                            "theme_color": r.theme_color, "logo_url": r.logo_url, "config": r.config or {}}
        finally:
            db.close()
        _cache_hosts.update(t=time.time(), mapa=mapa)
    return _cache_hosts["mapa"].get(host)


# ───────────────────────── Cuentas de prueba (caché) ─────────────────────────
_cache = {"t": 0.0, "ids": frozenset()}
_lock = threading.Lock()


def testers(forzar=False):
    with _lock:
        if not forzar and time.time() - _cache["t"] < 30:
            return _cache["ids"]
    from sqlalchemy import text
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        ids = set()
        for (cfg,) in db.execute(text("SELECT config FROM organizations")).fetchall():
            ids |= {int(x) for x in ((cfg or {}).get("sandbox_testers") or [])}
        roles = {}
        if ids:
            roles = {int(r.id): (r.role or "") for r in db.execute(
                text("SELECT id, role FROM members WHERE id = ANY(:i)"), {"i": list(ids)}).fetchall()}
    finally:
        db.close()
    with _lock:
        _cache.update(t=time.time(), ids=frozenset(ids), roles=roles)
    return _cache["ids"]


def rol_tester(mid):
    testers()
    return (_cache.get("roles") or {}).get(mid, "")


# Cuentas de prueba con rol CAJERO (cajera, Walter, Anggie): sin admin, Parámetros, Reportes ni Soporte.
# Solo se dejan las dos lecturas que la propia pantalla de Caja usa.
_CAJERO_PERMITIDAS = ("/api/admin/parametros/", "/api/reportes/exportar-dia")
_CAJERO_PROHIBIDAS = ("/admin", "/sote", "/api/admin/", "/api/reportes/")


def cajero_prohibida(path, metodo):
    if not path.startswith(_CAJERO_PROHIBIDAS):
        return False
    if metodo == "GET" and path.startswith(_CAJERO_PERMITIDAS):
        return False
    return True


def _member_de_cookie(request):
    tok = request.cookies.get("access_token")
    if not tok:
        return None
    try:
        from jose import jwt
        from app.config import SECRET_KEY
        from app.utils.security import ALGORITHM
        tv = tok.split()[-1]
        p = jwt.decode(tv, os.getenv("SECRET_KEY", SECRET_KEY), algorithms=[ALGORITHM])
        if p.get("cambio_clave"):
            return None
        return int(p.get("sub"))
    except Exception:
        return None


# ───────────────────────── Franja y noindex ─────────────────────────
FRANJA_HTML = (
    '<meta name="robots" content="noindex, nofollow, noarchive">'
    '<style>#sbx-franja{position:fixed;top:0;left:0;right:0;z-index:2147483647;'
    'background:#78350f;color:#fef3c7;border-bottom:1px solid #b45309;'
    'font:600 13px/26px system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;'
    'height:26px;text-align:center;letter-spacing:.02em;pointer-events:none;'
    'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;padding:0 12px}'
    'html body{padding-top:26px!important}'
    # Pantallas de alto completo (100vh): se descuenta la franja para no cortar su borde inferior.
    'html body:has(.caja-layout),html body:has(.sec-layout){height:100dvh!important}'
    '.caja-layout,.sec-layout,body>.app{height:calc(100vh - 26px)!important;height:calc(100dvh - 26px)!important}'
    '@media print{#sbx-franja{position:static}}</style>'
    '<div id="sbx-franja" role="status" aria-live="polite">' + TEXTO_FRANJA + '</div>'
    # Tanda 13: marca para las pantallas (Caja): los comprobantes se rotulan «SIMULADO — SIN VALOR TRIBUTARIO».
    '<script>window.CCPL_SANDBOX=true;</script>'
)
ROTULO_COMPROBANTE = "SIMULADO — SIN VALOR TRIBUTARIO"

ROBOTS_TXT = "User-agent: *\nDisallow: /\n"
_ABIERTAS = (RUTA_INGRESO, "/static/", "/favicon.ico", "/robots.txt", "/auth/logout", "/manifest.json")


def inyectar_franja(html):
    """Inserta la franja justo después de <body ...>. Si no hay <body>, al inicio."""
    bajo = html.lower()
    i = bajo.find("<body")
    if i >= 0:
        j = bajo.find(">", i)
        if j >= 0:
            return html[:j + 1] + FRANJA_HTML + html[j + 1:]
    return FRANJA_HTML + html


# ───────────────────────── Facturalo simulado ─────────────────────────
_NUM_LOCK = threading.Lock()
_NUM = {}            # serie → último número entregado en ESTE proceso (se siembra desde la base)


def _siguiente_numero(serie):
    """Tanda 20: el número ya no vuelve a 1 al reiniciar. Se siembra UNA vez por serie con el mayor número que ya
    tiene esa serie en comprobantes con respuesta de Facturalo (facturalo_id no nulo: el comprobante en curso
    todavía no lo tiene), y luego sube en memoria bajo candado. Un solo proceso por servicio (Railway)."""
    with _NUM_LOCK:
        if serie not in _NUM:
            from sqlalchemy import text
            from app.database import engine
            with engine.connect() as c:
                _NUM[serie] = int(c.execute(text(
                    "SELECT coalesce(max(numero), 0) FROM comprobantes WHERE serie = :s AND facturalo_id IS NOT NULL"),
                    {"s": serie}).scalar() or 0)
        _NUM[serie] += 1
        return _NUM[serie]


def _emisor_pdf():
    """Líneas del emisor para el PDF simulado. Solo en la DEMO (base marcada demo + demo_verificado) se leen de
    configuracion_facturacion, que preparar_demo.py deja con datos ficticios. En cualquier otro caso, ninguna."""
    sin_datos = ["Ambiente de prueba — sin datos del emisor"]
    if not ES_DEMO:
        return sin_datos
    try:
        from sqlalchemy import text
        from app.database import engine
        with engine.connect() as c:
            ok = c.execute(text("SELECT bool_and(coalesce((config->>'demo')::boolean, false) AND "
                                "coalesce((config->>'demo_verificado')::boolean, false)) FROM organizations")).scalar()
            if not ok:
                return sin_datos
            r = c.execute(text("SELECT razon_social, ruc, direccion FROM configuracion_facturacion ORDER BY id LIMIT 1")).fetchone()
        if not r:
            return sin_datos
        return [x for x in (r.razon_social, ("RUC %s" % r.ruc) if r.ruc else None, r.direccion) if x]
    except Exception:
        return sin_datos


def instalar_simulador_facturalo(app, solo_loopback=False):
    """Rutas /sandbox/facturalo/... (misma forma de respuesta que Facturalo). Las usa el sandbox/demo y, desde la
    tanda 20, el candado en local (solo_loopback=True: fuera del sandbox no hay muro de sesión que las proteja)."""
    import time as _t
    from fastapi import Request
    from fastapi.responses import JSONResponse, Response
    _emitidos = {}

    def _clave_ok(request):
        if solo_loopback and ((request.client.host if request.client else "") not in _LOOPBACK | {"testclient"}):
            return False
        return request.headers.get("x-api-key") == TOKEN_FACTURALO

    @app.post(RUTA_FACTURALO + "/comprobantes", include_in_schema=False)
    async def _fac_emitir(request: Request):
        if not _clave_ok(request):
            return JSONResponse({"exito": False, "mensaje": "clave inválida"}, status_code=401)
        try:
            p = await request.json()
        except Exception:
            p = {}
        serie = p.get("serie") or "B400"
        numero = p.get("numero") or _siguiente_numero(serie)
        fid = "SBX-%d-%d-%s" % (int(_t.time()), numero, serie)
        comp = {"id": fid, "numero": numero, "serie": serie, "estado": "aceptado",
                "numero_formato": "%s-%08d" % (serie, int(numero)), "codigo_sunat": "0",
                "mensaje_sunat": ROTULO_COMPROBANTE + (" (demostración, no enviado a SUNAT)" if ES_DEMO
                                                       else " (ambiente de prueba, no enviado a SUNAT)"),
                "hash_cpe": "SIMULADO"}
        _emitidos[fid] = comp
        return {"exito": True, "comprobante": comp, "archivos": {"pdf_url": None, "xml_url": None, "cdr_url": None}}

    def _buscar(fid):
        """Tras un reinicio el diccionario está vacío: se busca el comprobante en la base por facturalo_id."""
        if fid in _emitidos:
            return _emitidos[fid]
        from sqlalchemy import text
        from app.database import engine
        with engine.connect() as c:
            r = c.execute(text("SELECT serie, numero FROM comprobantes WHERE facturalo_id = :f"), {"f": fid}).fetchone()
        return {"numero_formato": "%s-%08d" % (r.serie, int(r.numero))} if r else {}

    @app.get(RUTA_FACTURALO + "/comprobantes/{fid}", include_in_schema=False)
    async def _fac_consultar(fid: str, request: Request):
        if not _clave_ok(request):
            return JSONResponse({"exito": False}, status_code=401)
        comp = dict(_buscar(fid), id=fid, estado="aceptado", hash_cpe="SIMULADO",
                    mensaje_sunat="Consulta SIMULADA (ambiente de prueba)")
        return {"exito": True, "comprobante": comp, "archivos": {}}

    @app.get(RUTA_FACTURALO + "/comprobantes/{fid}/pdf", include_in_schema=False)
    async def _fac_pdf(fid: str, request: Request):
        if not _clave_ok(request):
            return JSONResponse({"exito": False}, status_code=401)
        import io
        from reportlab.lib.pagesizes import A5
        from reportlab.pdfgen import canvas
        buf = io.BytesIO()
        cv = canvas.Canvas(buf, pagesize=A5)
        comp = _buscar(fid)
        cv.setFont("Helvetica-Bold", 16)
        cv.setFillColorRGB(0.6, 0.1, 0.1)
        cv.drawString(40, 530, ROTULO_COMPROBANTE)
        cv.setFillColorRGB(0, 0, 0)
        cv.setFont("Helvetica-Bold", 12)
        cv.drawString(40, 506, "DEMOSTRACIÓN — DATOS FICTICIOS" if ES_DEMO else "AMBIENTE DE PRUEBA")
        cv.setFont("Helvetica", 11)
        cv.drawString(40, 486, "Comprobante simulado: no es válido ni fue enviado a SUNAT.")
        if comp.get("numero_formato"):
            cv.drawString(40, 468, "Número: %s" % comp["numero_formato"])
        cv.drawString(40, 450, "Referencia: %s" % fid[:40])
        # Emisor (tanda 19/20): en la DEMO, el emisor FICTICIO de su base enmascarada y verificada; en el sandbox y en
        # local (bases con datos reales) NO se imprime ningún dato del emisor real (RUC, razón social, dirección).
        cv.setFont("Helvetica-Bold", 10)
        cv.drawString(40, 424, "Emisor (ficticio):" if ES_DEMO else "Emisor:")
        cv.setFont("Helvetica", 10)
        for k, linea in enumerate(_emisor_pdf()):
            cv.drawString(40, 410 - 14 * k, linea[:70])
        # Marca de agua diagonal
        cv.saveState()
        cv.setFont("Helvetica-Bold", 34)
        cv.setFillColorRGB(0.85, 0.85, 0.85)
        cv.translate(210, 260)
        cv.rotate(35)
        cv.drawCentredString(0, 0, "SIMULADO")
        cv.drawCentredString(0, -40, "SIN VALOR TRIBUTARIO")
        cv.restoreState()
        cv.showPage()
        cv.save()
        return Response(buf.getvalue(), media_type="application/pdf")


# ───────────────────────── Página de ingreso ─────────────────────────
def _pagina_ingreso(mensaje="", siguiente="/"):
    from html import escape
    if ES_DEMO:
        titulo, h1, sub = ("Ingreso · Demostración", "Demostración",
                           "Datos ficticios: ninguna persona ni comprobante es real. Aquí nada llega a SUNAT ni a nadie.")
    else:
        titulo, h1, sub = ("Ingreso · Ambiente de prueba", "Ambiente de prueba",
                           "Solo cuentas de prueba personales. Aquí nada llega a los colegiados ni a SUNAT.")
    return ("""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITULO__</title>
<style>
:root{color-scheme:dark}
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
background:#0f172a;color:#e2e8f0;font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;padding:16px;box-sizing:border-box}
.c{width:100%%;max-width:360px;background:#1e293b;border:1px solid #334155;border-radius:12px;padding:24px}
h1{font-size:18px;margin:0 0 4px}p{margin:0 0 16px;color:#94a3b8;font-size:13px}
label{display:block;font-size:13px;color:#cbd5e1;margin:12px 0 4px}
input{width:100%%;box-sizing:border-box;padding:10px;border-radius:8px;border:1px solid #475569;background:#0f172a;color:#e2e8f0;font-size:15px}
button{margin-top:18px;width:100%%;padding:11px;border:0;border-radius:8px;background:#1E3A5F;color:#fff;font-weight:600;font-size:15px;cursor:pointer}
.m{margin-top:12px;padding:8px 10px;border-radius:8px;background:#450a0a;color:#fecaca;font-size:13px}
</style></head><body>
<form class="c" method="post" action="%s">
<h1>__H1__</h1>
<p>__SUB__</p>
<input type="hidden" name="siguiente" value="%s">
<label for="u">Usuario</label><input id="u" name="usuario" autocomplete="username" required autofocus>
<label for="k">Clave</label><input id="k" name="clave" type="password" autocomplete="current-password" required>
<button type="submit">Ingresar</button>
%s
</form></body></html>""" % (RUTA_INGRESO, escape(siguiente), ('<div class="m">%s</div>' % escape(mensaje)) if mensaje else "")
            ).replace("__TITULO__", titulo).replace("__H1__", h1).replace("__SUB__", sub)


# ───────────────────────── Instalación en la app ─────────────────────────
def instalar(app):
    """Se llama al FINAL de main.py. Fuera del sandbox no hace nada."""
    if not ES_SANDBOX:
        return
    from fastapi import Request, Form
    from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
    from app.database import engine

    resumen = verificar_base(engine)          # si falla, la app no arranca
    print("🧪 SANDBOX: base verificada (%s)" % resumen)

    instalar_simulador_facturalo(app)

    # ── Ingreso solo para cuentas de prueba ──
    @app.get(RUTA_INGRESO, include_in_schema=False)
    async def _ingreso_get(siguiente: str = "/"):
        return HTMLResponse(_pagina_ingreso(siguiente=siguiente))

    @app.post(RUTA_INGRESO, include_in_schema=False)
    async def _ingreso_post(request: Request, usuario: str = Form(...), clave: str = Form(...), siguiente: str = Form("/")):
        from app.database import SessionLocal
        from app.models import Member, User
        from app.utils.security import verify_password
        from app.routers.auth import create_session_response
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.public_id == usuario.strip()).first()
            ok = False
            member = None
            if user and user.access_code:
                try:
                    ok = verify_password(clave, user.access_code)
                except Exception:
                    ok = False
            if ok:
                ids = testers(forzar=True)
                member = (db.query(Member).filter(Member.user_id == user.id, Member.is_active == True)  # noqa: E712
                          .order_by(Member.id).all())
                member = next((m for m in member if m.id in ids), None)
            if not ok or member is None:
                return HTMLResponse(_pagina_ingreso("Usuario o clave incorrectos, o la cuenta no es de prueba.", siguiente), status_code=401)
            r = create_session_response(user, member, db)
            destino = r.headers.get("HX-Redirect") or "/dashboard"
            if siguiente and siguiente.startswith("/") and not siguiente.startswith("//") and siguiente != "/":
                destino = siguiente
            r.status_code = 303
            r.headers["location"] = destino
            del r.headers["HX-Redirect"]
            return r
        finally:
            db.close()

    # ── Dirección del sandbox → organización ──
    # tenant_middleware NO se toca: solo conoce sus dominios fijos (ccploreto.org.pe,
    # *.duilio.store, localhost...). Este paso corre DESPUÉS de él (se agrega al final de la
    # lista = el más interno) y, si dejó la petición sin organización y la dirección figura en
    # organizations.config['sandbox_hosts'] de la base del sandbox, le asigna esa organización.
    from starlette.middleware import Middleware
    from starlette.middleware.base import BaseHTTPMiddleware

    async def _mapa_hosts(request, call_next):
        if getattr(request.state, "org", None) is None:
            host = (request.headers.get("host", "").lower().split(":")[0])
            if host.startswith("www."):
                host = host[4:]
            org = _org_por_host(host)
            if org:
                request.state.org = org
                request.state.theme = {
                    "site_name": org["name"], "primary_color": org["theme_color"], "logo": org["logo_url"],
                    "tone": "formal" if org["type"] == "colegio_prof" else "friendly",
                    "modules": (org["config"] or {}).get("modules", {}),
                }
        return await call_next(request)

    app.user_middleware.append(Middleware(BaseHTTPMiddleware, dispatch=_mapa_hosts))

    # ── Muro de sesión + noindex + franja (middleware más externo) ──
    @app.middleware("http")
    async def sandbox_middleware(request: Request, call_next):
        path = request.url.path
        if path == "/robots.txt":
            return PlainTextResponse(ROBOTS_TXT, headers={"X-Robots-Tag": "noindex, nofollow, noarchive"})
        abierta = path.startswith(_ABIERTAS) or path == RUTA_INGRESO
        if path.startswith(RUTA_FACTURALO + "/"):
            # Solo la propia app (loopback) con la clave del simulador.
            cli = (request.client.host if request.client else "") or ""
            abierta = cli in _LOOPBACK or cli == "testclient"
        if not abierta:
            mid = _member_de_cookie(request)
            if mid is None or mid not in testers():
                acepta = request.headers.get("accept") or ""
                if request.method == "GET" and "text/html" in acepta and not path.startswith("/api/"):
                    from urllib.parse import quote
                    resp = RedirectResponse(RUTA_INGRESO + "?siguiente=" + quote(path), status_code=302)
                else:
                    resp = JSONResponse({"detail": "Ambiente de prueba: inicie sesión con su cuenta de prueba."}, status_code=401)
                resp.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
                if mid is not None:
                    resp.delete_cookie("access_token", path="/")
                return resp
            if rol_tester(mid) == "cajero" and cajero_prohibida(path, request.method):
                if request.method == "GET" and "text/html" in (request.headers.get("accept") or "") and not path.startswith("/api/"):
                    resp = HTMLResponse(
                        '<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Sin acceso</title>'
                        '<style>body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;'
                        'background:#0f172a;color:#e2e8f0;font:15px system-ui,sans-serif;padding:16px}'
                        'a{color:#93c5fd}</style></head><body><div><h1 style="font-size:18px">Sin acceso</h1>'
                        '<p>Su cuenta de prueba es de Caja: esta sección no está disponible.</p>'
                        '<p><a href="/caja">Volver a Caja</a></p></div></body></html>', status_code=403)
                else:
                    resp = JSONResponse({"detail": "Cuenta de Caja: sin acceso a esta sección."}, status_code=403)
                resp.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
                return resp

        response = await call_next(request)
        response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        ctype = response.headers.get("content-type", "")
        if "text/html" in ctype and request.method != "HEAD":
            cuerpo = b""
            async for trozo in response.body_iterator:
                cuerpo += trozo if isinstance(trozo, bytes) else trozo.encode()
            try:
                html = cuerpo.decode(response.charset if hasattr(response, "charset") else "utf-8")
            except Exception:
                html = cuerpo.decode("utf-8", errors="replace")
            nuevo = inyectar_franja(html).encode("utf-8")
            headers = {k: v for k, v in response.headers.items() if k.lower() != "content-length"}
            out = Response(nuevo, status_code=response.status_code, headers=headers, media_type=None)
            return out
        return response

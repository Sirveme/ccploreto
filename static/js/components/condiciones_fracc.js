/* Tanda 14 — Bloque «Condiciones vigentes» del fraccionamiento (componente reutilizable).
   Lo usan: Caja (Crear fraccionamiento, panel de situación), Secretaría (Crear y Refinanciar).
   Pensado también para el portal del colegiado («¿Puedo fraccionar mi deuda?»): NO publicado allí aún.

   Los valores vienen del servidor (GET /api/secretaria/fraccionamiento/condiciones-vigentes →
   _resolver_parametros_fracc + dia_vencimiento_plan). Aquí no hay cifras fijas: si cambia un
   Parámetro, el bloque cambia solo. Si la consulta falla, no se muestra nada (no se inventan valores).

   Uso:
     CondicionesFracc.pintar('id-del-contenedor');                 // recuadro compacto
     CondicionesFracc.pintarMinimo('id-del-contenedor', deuda);    // línea solo si la deuda no llega al mínimo
     CondicionesFracc.config({ url: '/otra/ruta' });               // p. ej. el portal, con su propia ruta
*/
(function () {
    'use strict';
    let URL = '/api/secretaria/fraccionamiento/condiciones-vigentes';
    let _datos = null, _prom = null;

    function _css() {
        if (document.getElementById('cf-estilos')) return;
        const s = document.createElement('style');
        s.id = 'cf-estilos';
        s.textContent =
            '.cf-box{background:rgba(124,58,237,.07);border:1px solid rgba(167,139,250,.28);border-radius:10px;' +
            'padding:8px 12px;margin:0 0 10px;font-size:12px;line-height:1.55;color:#cbd5e1}' +
            '.cf-box .cf-tit{font-size:10px;font-weight:800;letter-spacing:.6px;text-transform:uppercase;color:#a78bfa;margin-bottom:2px}' +
            '.cf-box .cf-sep{color:#64748b;margin:0 5px}' +
            '.cf-box .cf-it{white-space:nowrap}' +
            '.cf-min{background:rgba(249,198,74,.08);border:1px solid rgba(249,198,74,.3);border-radius:10px;' +
            'padding:8px 12px;margin:10px 0;font-size:12px;color:#f9c64a;line-height:1.5}';
        document.head.appendChild(s);
    }

    function _esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    }

    // Mismo formato que el servidor (condiciones_fracc_service._soles): sin decimales si es entero.
    function soles(v) {
        v = Math.round((+v || 0) * 100) / 100;
        const ent = Math.abs(v - Math.round(v)) < 0.005;
        return 'S/ ' + v.toLocaleString('en-US', { minimumFractionDigits: ent ? 0 : 2, maximumFractionDigits: ent ? 0 : 2 });
    }

    function _el(x) { return typeof x === 'string' ? document.getElementById(x) : x; }

    function config(o) {
        if (o && o.url && o.url !== URL) { URL = o.url; _datos = null; _prom = null; }
    }

    function cargar() {
        if (_datos) return Promise.resolve(_datos);
        if (_prom) return _prom;
        _prom = fetch(URL, { credentials: 'same-origin' })
            .then(r => (r.ok ? r.json() : null))
            .then(d => { _datos = (d && d.items) ? d : null; return _datos; })
            .catch(() => null)
            .finally(() => { if (!_datos) _prom = null; });   // si falló, se reintenta la próxima vez
        return _prom;
    }

    function html(d, opts) {
        if (!d || !d.items) return '';
        const tit = (opts && opts.titulo) || 'Condiciones vigentes';
        return '<div class="cf-box" data-cf="condiciones"><div class="cf-tit">' + _esc(tit) + '</div>' +
            d.items.map(i => '<span class="cf-it">' + _esc(i.texto) + '</span>').join('<span class="cf-sep">·</span>') +
            '</div>';
    }

    function llega(d, deuda) { return !d || (+deuda || 0) + 0.005 >= Number(d.monto_minimo || 0); }

    function lineaMinimo(d, deuda) {
        if (!d || llega(d, deuda)) return '';
        return '<div class="cf-min" data-cf="minimo">Fraccionamiento disponible desde ' + _esc(d.monto_minimo_texto || soles(d.monto_minimo)) +
            '; deuda actual ' + _esc(soles(deuda)) + '.</div>';
    }

    function pintar(destino, opts) {
        _css();
        return cargar().then(d => { const el = _el(destino); if (el) el.innerHTML = html(d, opts); return d; });
    }

    // Devuelve una promesa con true si la deuda NO llega al mínimo (y pintó la línea).
    function pintarMinimo(destino, deuda) {
        _css();
        return cargar().then(d => {
            const el = _el(destino);
            const t = lineaMinimo(d, deuda);
            if (el) el.innerHTML = t;
            return !!t;
        });
    }

    window.CondicionesFracc = { config, cargar, html, lineaMinimo, llega, pintar, pintarMinimo, soles };
})();

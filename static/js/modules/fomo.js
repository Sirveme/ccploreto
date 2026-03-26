/**
 * fomo.js
 * static/js/modules/fomo.js
 * 
 * Maneja:
 * 1. Display de toasts FOMO recibidos por WebSocket
 * 2. Panel de activación manual para emisores
 * 
 * Incluir en dashboard_colegiado.html Y en comunicaciones.html:
 * <script src="/static/js/modules/fomo.js?v=1"></script>
 */

const FomoUI = (() => {

    let _ws = null;
    const _cola = [];          // Cola de toasts pendientes
    let _mostrando = false;    // Semáforo para no apilar toasts

    // ── WebSocket ────────────────────────────────────────────
    function conectar() {
        const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        _ws = new WebSocket(`${proto}//${location.host}/ws/alerta`);

        _ws.onmessage = e => {
            try {
                const msg = JSON.parse(e.data);
                if (msg.type === 'FOMO') {
                    encolar({
                        mensaje:  msg.mensaje,
                        icono:    msg.icono || '📢',
                        duracion: msg.duracion || 5000,
                    });
                }
            } catch(err) {}
        };

        _ws.onclose = () => setTimeout(conectar, 3000);
        _ws.onerror = () => _ws?.close();
    }

    // ── Cola de toasts ───────────────────────────────────────
    function encolar(item) {
        _cola.push(item);
        if (!_mostrando) procesarCola();
    }

    async function procesarCola() {
        if (!_cola.length) { _mostrando = false; return; }
        _mostrando = true;
        const item = _cola.shift();
        await mostrarToast(item);
        // Esperar un poco entre toasts
        await sleep(600);
        procesarCola();
    }

    function mostrarToast({ mensaje, icono, duracion = 5000 }) {
        return new Promise(resolve => {
            const container = document.getElementById('fomo-toast-container');
            if (!container) { resolve(); return; }

            const toast = document.createElement('div');
            toast.className = 'fomo-toast';
            toast.innerHTML = `
                <span class="fomo-toast-icono">${icono}</span>
                <span class="fomo-toast-texto">${escHtml(mensaje)}</span>
            `;
            container.appendChild(toast);

            // Auto-cerrar
            setTimeout(() => {
                toast.classList.add('out');
                setTimeout(() => {
                    toast.remove();
                    resolve();
                }, 350);
            }, duracion);
        });
    }

    // ── Panel manual (solo emisores) ─────────────────────────
    async function cargarOpciones() {
        const lista = document.getElementById('fomo-opciones-lista');
        if (!lista) return;

        try {
            const r = await fetch('/api/comunicados/fomo/opciones');
            if (!r.ok) throw new Error();
            const d = await r.json();

            lista.innerHTML = (d.opciones || []).map(op => `
                <button class="fomo-btn" onclick="FomoUI.activar('${op.id}', this)">
                    <span class="fomo-btn-label">
                        ${op.label}
                        <span class="fomo-btn-desc">${op.desc}</span>
                    </span>
                    <span class="fomo-btn-send">▶</span>
                </button>
            `).join('');

        } catch(e) {
            if (lista) lista.innerHTML = '<div style="font-size:11px;color:var(--c-muted);text-align:center">No disponible</div>';
        }
    }

    async function activar(tipo, btn) {
        const orig = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<span class="fomo-btn-label">Enviando...</span>';

        try {
            const r = await fetch('/api/comunicados/fomo/activar', {
                method:  'POST',
                headers: { 'Content-Type': 'application/json' },
                body:    JSON.stringify({ tipo }),
            });
            const d = await r.json();

            const fb = document.getElementById('fomo-feedback');
            if (fb) {
                fb.style.display    = 'block';
                fb.style.background = d.ok ? 'rgba(56,178,114,.1)' : 'rgba(229,62,62,.1)';
                fb.style.color      = d.ok ? '#38b272' : '#fc8181';
                fb.style.border     = `1px solid ${d.ok ? 'rgba(56,178,114,.2)' : 'rgba(229,62,62,.2)'}`;
                fb.textContent      = d.ok ? `✅ ${d.mensaje}` : `❌ ${d.mensaje}`;
                setTimeout(() => fb.style.display = 'none', 4000);
            }
        } catch(e) {
            console.warn('[FOMO] activar error:', e);
        } finally {
            btn.disabled  = false;
            btn.innerHTML = orig;
        }
    }

    // ── Helpers ──────────────────────────────────────────────
    function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

    function escHtml(str) {
        if (!str) return '';
        return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    }

    // ── Init ─────────────────────────────────────────────────
    function init() {
        conectar();
        // Cargar opciones del panel si existe
        if (document.getElementById('fomo-opciones-lista')) {
            cargarOpciones();
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    return { activar, encolar, cargarOpciones };
})();
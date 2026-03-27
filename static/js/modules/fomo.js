/**
 * fomo.js  v2
 * static/js/modules/fomo.js
 * Card flotante con modo claro/oscuro, icono grande, gradiente
 */

const FomoUI = (() => {

    let _ws = null;
    const _cola = [];
    let _mostrando = false;

    // Colores por tipo
    const TIPO_THEME = {
        transparencia: { grad: 'linear-gradient(135deg,#1a3a2a,#0d2018)', accent: '#38b272', border: 'rgba(56,178,114,.3)' },
        tendencias:    { grad: 'linear-gradient(135deg,#2a1a0a,#1a0f05)', accent: '#f59e0b', border: 'rgba(245,158,11,.3)' },
        eventos:       { grad: 'linear-gradient(135deg,#0a1a3a,#050f20)', accent: '#60a5fa', border: 'rgba(96,165,250,.3)' },
        comunidad:     { grad: 'linear-gradient(135deg,#2a0a2a,#180a18)', accent: '#c084fc', border: 'rgba(192,132,252,.3)' },
        default:       { grad: 'linear-gradient(135deg,#1a1a2a,#0d0d18)', accent: '#d4a843', border: 'rgba(212,168,67,.3)' },
    };

    // ── WebSocket ─────────────────────────────────────────────
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
                        tipo:     msg.tipo  || 'default',
                        duracion: msg.duracion || 6000,
                        modo:     msg.modo || 'oscuro',
                    });
                }
            } catch(e) {}
        };
        _ws.onclose = () => setTimeout(conectar, 3000);
        _ws.onerror = () => _ws?.close();
    }

    // ── Cola ──────────────────────────────────────────────────
    function encolar(item) {
        _cola.push(item);
        if (!_mostrando) procesarCola();
    }

    async function procesarCola() {
        if (!_cola.length) { _mostrando = false; return; }
        _mostrando = true;
        await mostrarCard(_cola.shift());
        await sleep(800);
        procesarCola();
    }

    // ── Card flotante ─────────────────────────────────────────
    function mostrarCard({ mensaje, icono, tipo, duracion, modo }) {
        return new Promise(resolve => {
            const container = document.getElementById('fomo-toast-container');
            if (!container) { resolve(); return; }

            const theme  = TIPO_THEME[tipo] || TIPO_THEME.default;
            const esClaro = modo === 'claro';

            const card = document.createElement('div');
            card.className = 'fomo-card';
            card.style.cssText = `
                display:flex;align-items:flex-start;gap:14px;
                padding:16px 18px;
                background:${esClaro
                    ? 'rgba(255,255,255,.97)'
                    : theme.grad};
                border:1px solid ${esClaro ? 'rgba(0,0,0,.08)' : theme.border};
                border-left:4px solid ${theme.accent};
                border-radius:14px;
                box-shadow:0 12px 40px rgba(0,0,0,.35),
                           0 0 0 1px rgba(255,255,255,.04) inset;
                width:320px;
                pointer-events:all;
                cursor:pointer;
                animation:fomoCardIn .4s cubic-bezier(.23,1,.32,1);
                position:relative;
                overflow:hidden;
            `;

            // Brillo decorativo
            const glow = document.createElement('div');
            glow.style.cssText = `
                position:absolute;top:-30px;right:-30px;
                width:80px;height:80px;border-radius:50%;
                background:${theme.accent};
                opacity:${esClaro ? '.06' : '.12'};
                filter:blur(20px);pointer-events:none;
            `;
            card.appendChild(glow);

            // Icono
            const iconEl = document.createElement('div');
            iconEl.style.cssText = `
                font-size:28px;line-height:1;flex-shrink:0;
                filter:drop-shadow(0 2px 4px rgba(0,0,0,.3));
            `;
            iconEl.textContent = icono;

            // Texto
            const textEl = document.createElement('div');
            textEl.style.cssText = 'flex:1;min-width:0;';
            textEl.innerHTML = `
                <div style="
                    font-size:10px;font-weight:700;
                    text-transform:uppercase;letter-spacing:.08em;
                    color:${theme.accent};margin-bottom:4px">
                    CCPL · Info
                </div>
                <div style="
                    font-size:13px;font-weight:500;line-height:1.5;
                    color:${esClaro ? '#1a1a2a' : '#e8edf5'};
                ">${escHtml(mensaje)}</div>
            `;

            // Cerrar
            const closeEl = document.createElement('button');
            closeEl.style.cssText = `
                position:absolute;top:8px;right:10px;
                background:none;border:none;
                color:${esClaro ? 'rgba(0,0,0,.3)' : 'rgba(255,255,255,.3)'};
                font-size:14px;cursor:pointer;padding:2px 4px;
                line-height:1;
            `;
            closeEl.textContent = '✕';
            closeEl.onclick = e => { e.stopPropagation(); cerrarCard(card, resolve); };

            // Barra de progreso
            const progress = document.createElement('div');
            progress.style.cssText = `
                position:absolute;bottom:0;left:0;
                height:3px;background:${theme.accent};
                opacity:.6;border-radius:0 0 0 14px;
                animation:fomoProgress ${duracion}ms linear forwards;
            `;

            card.appendChild(iconEl);
            card.appendChild(textEl);
            card.appendChild(closeEl);
            card.appendChild(progress);

            card.onclick = () => cerrarCard(card, resolve);
            container.appendChild(card);

            setTimeout(() => cerrarCard(card, resolve), duracion);
        });
    }

    function cerrarCard(card, resolve) {
        card.style.animation = 'fomoCardOut .3s ease forwards';
        setTimeout(() => {
            card.remove();
            if (resolve) resolve();
        }, 320);
    }

    // ── Panel manual ──────────────────────────────────────────
    async function cargarOpciones() {
        const lista = document.getElementById('fomo-opciones-lista');
        if (!lista) return;
        try {
            const r = await fetch('/api/comunicados/fomo/opciones');
            if (!r.ok) throw new Error();
            const d = await r.json();
            lista.innerHTML = (d.opciones || []).map(op => `
                <div class="fomo-opcion">
                    <div class="fomo-opcion-info">
                        <span class="fomo-opcion-label">${op.label}</span>
                        <span class="fomo-opcion-desc">${op.desc}</span>
                    </div>
                    <div class="fomo-opcion-modos">
                        <button class="fomo-modo-btn"
                                onclick="FomoUI.activar('${op.id}','oscuro',this)"
                                title="Modo oscuro">🌙</button>
                        <button class="fomo-modo-btn"
                                onclick="FomoUI.activar('${op.id}','claro',this)"
                                title="Modo claro">☀️</button>
                    </div>
                </div>
            `).join('');

            // Agregar opción de FOMO personalizado
            lista.innerHTML += `
                <div style="margin-top:10px;border-top:1px solid var(--c-border,#1e2631);padding-top:10px">
                    <div style="font-size:10px;font-weight:700;text-transform:uppercase;
                                letter-spacing:.06em;color:var(--c-muted);margin-bottom:8px">
                        FOMO personalizado
                    </div>
                    <textarea id="fomo-custom-texto"
                              placeholder="Escribe tu mensaje FOMO..."
                              style="width:100%;background:rgba(255,255,255,.04);
                                     border:1px solid var(--c-border,#1e2631);
                                     border-radius:8px;padding:8px 10px;
                                     color:var(--c-text,#e8edf5);font-size:12px;
                                     resize:none;font-family:inherit;
                                     box-sizing:border-box"
                              rows="2"></textarea>
                    <div style="display:flex;gap:6px;margin-top:6px">
                        <input id="fomo-custom-icono" type="text"
                               placeholder="🎯" maxlength="2"
                               style="width:44px;text-align:center;
                                      background:rgba(255,255,255,.04);
                                      border:1px solid var(--c-border,#1e2631);
                                      border-radius:8px;padding:7px;
                                      color:var(--c-text,#e8edf5);font-size:16px">
                        <button class="fomo-modo-btn" style="flex:1;padding:7px"
                                onclick="FomoUI.activarCustom('oscuro')">
                            🌙 Enviar oscuro
                        </button>
                        <button class="fomo-modo-btn" style="flex:1;padding:7px"
                                onclick="FomoUI.activarCustom('claro')">
                            ☀️ Enviar claro
                        </button>
                    </div>
                </div>
            `;
        } catch(e) {
            if (lista) lista.innerHTML = '<div style="font-size:11px;color:var(--c-muted);text-align:center">No disponible</div>';
        }
    }

    async function activar(tipo, modo, btn) {
        const orig = btn.textContent;
        btn.disabled = true; btn.textContent = '...';
        try {
            const r = await fetch('/api/comunicados/fomo/activar', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ tipo, modo }),
            });
            const d = await r.json();
            mostrarFeedback(d.ok ? `✅ ${d.mensaje}` : `❌ ${d.mensaje}`, d.ok);
        } catch(e) { mostrarFeedback('Error de conexión', false); }
        finally { btn.disabled = false; btn.textContent = orig; }
    }

    async function activarCustom(modo) {
        const texto = document.getElementById('fomo-custom-texto')?.value.trim();
        const icono = document.getElementById('fomo-custom-icono')?.value.trim() || '📢';
        if (!texto) {
            mostrarFeedback('Escribe un mensaje primero', false);
            return;
        }
        try {
            const r = await fetch('/api/comunicados/fomo/activar', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ tipo: 'custom', modo, mensaje: texto, icono }),
            });
            const d = await r.json();
            if (d.ok) {
                document.getElementById('fomo-custom-texto').value = '';
                mostrarFeedback('✅ FOMO enviado', true);
            } else {
                mostrarFeedback(`❌ ${d.mensaje}`, false);
            }
        } catch(e) { mostrarFeedback('Error', false); }
    }

    function mostrarFeedback(msg, ok) {
        const el = document.getElementById('fomo-feedback');
        if (!el) return;
        el.textContent = msg;
        el.style.display = 'block';
        el.style.background = ok ? 'rgba(56,178,114,.1)' : 'rgba(229,62,62,.1)';
        el.style.color      = ok ? '#38b272' : '#fc8181';
        el.style.border     = `1px solid ${ok ? 'rgba(56,178,114,.2)' : 'rgba(229,62,62,.2)'}`;
        setTimeout(() => el.style.display = 'none', 4000);
    }

    // ── FOMO automático al login (delay 2 min) ────────────────
    function programarFomoLogin() {
        // Solo si hay elemento dashboard (usuario logueado)
        if (!document.getElementById('com-feed') &&
            !document.querySelector('[data-dashboard]')) return;
        setTimeout(async () => {
            try {
                const r = await fetch('/api/comunicados/fomo/activar', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ tipo: 'auto_login', modo: 'oscuro' }),
                });
            } catch(e) {}
        }, 2 * 60 * 1000); // 2 minutos
    }

    // ── Helpers ───────────────────────────────────────────────
    function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
    function escHtml(s) {
        if (!s) return '';
        return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    }

    // ── CSS dinámico ──────────────────────────────────────────
    function inyectarCSS() {
        if (document.getElementById('fomo-css')) return;
        const style = document.createElement('style');
        style.id = 'fomo-css';
        style.textContent = `
@keyframes fomoCardIn {
    from { opacity:0; transform:translateX(-30px) scale(.92); }
    to   { opacity:1; transform:translateX(0) scale(1); }
}
@keyframes fomoCardOut {
    from { opacity:1; transform:translateX(0) scale(1); }
    to   { opacity:0; transform:translateX(-20px) scale(.95); }
}
@keyframes fomoProgress {
    from { width:100%; }
    to   { width:0%; }
}

/* Panel opciones */
.fomo-opcion {
    display:flex;align-items:center;justify-content:space-between;
    gap:8px;padding:8px 10px;
    border:1px solid var(--c-border,#1e2631);
    border-radius:9px;background:rgba(255,255,255,.03);
    margin-bottom:6px;
}
.fomo-opcion-info { flex:1;min-width:0; }
.fomo-opcion-label { display:block;font-size:12px;font-weight:600;color:var(--c-text2,#a0aec0); }
.fomo-opcion-desc  { display:block;font-size:10px;color:var(--c-muted,#4a5568);margin-top:1px; }
.fomo-opcion-modos { display:flex;gap:4px;flex-shrink:0; }
.fomo-modo-btn {
    padding:5px 8px;border-radius:7px;font-size:13px;
    background:rgba(255,255,255,.05);
    border:1px solid var(--c-border,#1e2631);
    cursor:pointer;transition:all .15s;
}
.fomo-modo-btn:hover { background:rgba(255,255,255,.1); }
.fomo-modo-btn:disabled { opacity:.4;cursor:not-allowed; }
        `;
        document.head.appendChild(style);
    }

    // ── Init ──────────────────────────────────────────────────
    function init() {
        inyectarCSS();
        conectar();
        if (document.getElementById('fomo-opciones-lista')) cargarOpciones();
        programarFomoLogin();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    return { activar, activarCustom, encolar, cargarOpciones };
})();
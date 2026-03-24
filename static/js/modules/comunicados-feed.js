/**
 * comunicados-feed.js
 * Feed de comunicados para dashboard_colegiado.html
 * static/js/modules/comunicados-feed.js
 * 
 * Agregar en dashboard_colegiado.html:
 * <script src="/static/js/modules/comunicados-feed.js?v=1"></script>
 */

const ComunicadosFeed = (() => {

    const ICONS = {
        info:    '📢',
        warning: '⚠️',
        alert:   '🚨',
    };

    // ── Cargar comunicados ───────────────────────────────────
    async function cargar() {
        const lista = document.getElementById('comunicados-lista');
        if (!lista) return;

        try {
            const r = await fetch('/api/comunicados/recientes?limit=3');
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            const data = await r.json();

            if (!data.comunicados || data.comunicados.length === 0) {
                lista.innerHTML = `
                    <div style="font-size:11px;color:var(--text-dim,#888);
                                text-align:center;padding:12px 0;font-style:italic">
                        Sin comunicados recientes
                    </div>`;
                return;
            }

            lista.innerHTML = data.comunicados.map(c => renderCard(c)).join('');

            // Marcar leídos al hacer click
            lista.querySelectorAll('.comunicado-card').forEach(card => {
                card.addEventListener('click', () => {
                    const id = card.dataset.id;
                    marcarLeido(id);
                    // Quitar punto de nuevo
                    card.querySelector('.comunicado-nuevo')?.remove();
                    // Abrir modal o ir a /comunicaciones
                    if (card.dataset.url) {
                        window.location.href = card.dataset.url;
                    } else {
                        window.location.href = '/comunicaciones';
                    }
                });
            });

        } catch(e) {
            lista.innerHTML = `
                <div style="font-size:11px;color:var(--text-dim,#888);
                            text-align:center;padding:10px 0">
                    No se pudieron cargar los comunicados
                </div>`;
        }
    }

    function renderCard(c) {
        const esNuevo = !c.leido;
        const fecha   = formatFecha(c.created_at);
        const icono   = ICONS[c.priority] || '📢';
        const badgeClass = `badge-${c.priority || 'info'}`;
        const badgeLabel = {
            info:    'INFO',
            warning: 'AVISO',
            alert:   'URGENTE',
        }[c.priority] || 'INFO';

        const imgHtml = c.image_url
            ? `<div class="comunicado-img"><img src="${c.image_url}" alt=""></div>`
            : `<div class="comunicado-img">${icono}</div>`;

        return `
            <div class="comunicado-card"
                 data-id="${c.id}"
                 data-url="${c.action_payload || ''}">
                ${imgHtml}
                <div class="comunicado-body">
                    <div class="comunicado-titulo-text">${escapeHtml(c.title)}</div>
                    <div class="comunicado-resumen">${escapeHtml(c.content)}</div>
                    <div class="comunicado-meta">
                        <span class="comunicado-badge ${badgeClass}">${badgeLabel}</span>
                        <span class="comunicado-fecha">${fecha}</span>
                        ${esNuevo ? '<span class="comunicado-nuevo"></span>' : ''}
                    </div>
                </div>
            </div>`;
    }

    // ── Marcar como leído ────────────────────────────────────
    async function marcarLeido(id) {
        try {
            await fetch(`/api/comunicados/${id}/leer`, { method: 'POST' });
        } catch(e) { /* silencioso */ }
    }

    // ── Recibir push en tiempo real (WebSocket) ──────────────
    function conectarWS() {
        const intentar = (reintentos) => {
            if (window._dashboardSocket) {
                window._dashboardSocket.addEventListener('message', e => {
                    try {
                        const msg = JSON.parse(e.data);
                        if (msg.type === 'BULLETIN') {
                            setTimeout(cargar, 300);
                            // Sonido según prioridad
                            const sonidos = {
                                alert:   '/static/sounds/sirena.mp3',
                                warning: '/static/sounds/new-notification-sound.mp3',
                                info:    '/static/sounds/ding-dong.mp3',
                            };
                            const src = sonidos[msg.priority] || sonidos.info;
                            new Audio(src).play().catch(() => {});
                            if (window.Toast) Toast.show(`📢 ${msg.title}`, 'info');
                        }
                    } catch(err) {}
                });
            } else if (reintentos > 0) {
                setTimeout(() => intentar(reintentos - 1), 1000);
            }
        };
        intentar(8);
    }

    // ── Helpers ──────────────────────────────────────────────
    function formatFecha(iso) {
        if (!iso) return '';
        const d   = new Date(iso);
        const now = new Date();
        const diff = Math.floor((now - d) / 1000);
        if (diff < 60)     return 'Ahora';
        if (diff < 3600)   return `Hace ${Math.floor(diff/60)} min`;
        if (diff < 86400)  return `Hace ${Math.floor(diff/3600)}h`;
        if (diff < 604800) return `Hace ${Math.floor(diff/86400)}d`;
        return d.toLocaleDateString('es-PE', { day:'numeric', month:'short' });
    }

    function escapeHtml(str) {
        if (!str) return '';
        return str
            .replace(/&/g,'&amp;')
            .replace(/</g,'&lt;')
            .replace(/>/g,'&gt;')
            .replace(/"/g,'&quot;');
    }

    // ── Init ─────────────────────────────────────────────────
    function init() {
        cargar();
        conectarWS();
        // Refrescar cada 5 minutos
        setInterval(cargar, 5 * 60 * 1000);
    }

    // Auto-init cuando el DOM está listo
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    return { cargar, init };
})();
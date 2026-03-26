/**
 * comunicados-feed.js  v3
 * static/js/modules/comunicados-feed.js
 */

const ComunicadosFeed = (() => {

    const ICONS = { info:'📢', warning:'⚠️', alert:'🚨' };
    const SONIDOS = {
        alert:   '/static/sounds/swoosh-sound.mp3',
        warning: '/static/sounds/new-notification-sound.mp3',
        info:    '/static/sounds/ding-dong.mp3',
    };

    async function cargar() {
        const lista = document.getElementById('comunicados-lista');
        if (!lista) return;
        try {
            const r = await fetch('/api/comunicados/recientes?limit=3');
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            const data = await r.json();
            if (!data.comunicados || data.comunicados.length === 0) {
                lista.innerHTML = `<div style="font-size:11px;color:var(--text-dim,#888);text-align:center;padding:12px 0;font-style:italic">Sin comunicados recientes</div>`;
                return;
            }
            lista.innerHTML = data.comunicados.map(c => renderCard(c)).join('');
            lista.querySelectorAll('.comunicado-card').forEach(card => {
                card.addEventListener('click', () => {
                    marcarLeido(card.dataset.id);
                    card.querySelector('.comunicado-nuevo')?.remove();
                    window.location.href = `/comunicaciones?id=${card.dataset.id}`;
                });
            });
        } catch(e) {
            lista.innerHTML = `<div style="font-size:11px;color:var(--text-dim,#888);text-align:center;padding:10px 0">No se pudieron cargar los comunicados</div>`;
        }
    }

    function renderCard(c) {
        const icono      = ICONS[c.priority] || '📢';
        const badgeClass = `badge-${c.priority || 'info'}`;
        const badgeLabel = { info:'INFO', warning:'AVISO', alert:'URGENTE' }[c.priority] || 'INFO';
        const imgHtml    = c.image_url
            ? `<div class="comunicado-img"><img src="${c.image_url}" alt=""></div>`
            : `<div class="comunicado-img">${icono}</div>`;
        return `
            <div class="comunicado-card" data-id="${c.id}" data-url="${c.action_payload || ''}">
                ${imgHtml}
                <div class="comunicado-body">
                    <div class="comunicado-titulo-text">${escapeHtml(c.title)}</div>
                    <div class="comunicado-resumen">${escapeHtml(c.content)}</div>
                    <div class="comunicado-meta">
                        <span class="comunicado-badge ${badgeClass}">${badgeLabel}</span>
                        <span class="comunicado-fecha">${formatFecha(c.created_at)}</span>
                        ${!c.leido ? '<span class="comunicado-nuevo"></span>' : ''}
                    </div>
                </div>
            </div>`;
    }

    async function marcarLeido(id) {
        try { await fetch(`/api/comunicados/${id}/leer`, { method: 'POST' }); } catch(e) {}
    }

    function abrirWS() {
        const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        const ws    = new WebSocket(`${proto}//${location.host}/ws/alerta`);

        ws.onopen = () => console.log('[Comunicados] WS conectado');

        ws.onmessage = e => {
            console.log('[Comunicados] WS mensaje:', e.data.substring(0, 80));
            try {
                const msg = JSON.parse(e.data);
                if (msg.type === 'BULLETIN') {
                    setTimeout(cargar, 300);
                    
                    // REEMPLAZAR:
                    const sndId = { alert:'snd-alert', warning:'snd-warning', info:'snd-info' }[msg.priority] || 'snd-info';
                    const sndEl = document.getElementById(sndId);
                    if (sndEl) sndEl.play().catch(() => {});
                    
                    if (window.Toast) Toast.show('📢 ' + msg.title, 'info');
                }
            } catch(err) {}
        };

        ws.onclose = e => {
            console.log('[Comunicados] WS cerrado, reconectando...', e.code);
            setTimeout(abrirWS, 3000);
        };

        ws.onerror = () => ws.close();
    }

    function formatFecha(iso) {
        if (!iso) return '';
        const diff = Math.floor((Date.now() - new Date(iso)) / 1000);
        if (diff < 60)     return 'Ahora';
        if (diff < 3600)   return 'Hace ' + Math.floor(diff/60) + ' min';
        if (diff < 86400)  return 'Hace ' + Math.floor(diff/3600) + 'h';
        if (diff < 604800) return 'Hace ' + Math.floor(diff/86400) + 'd';
        return new Date(iso).toLocaleDateString('es-PE', { day:'numeric', month:'short' });
    }

    function escapeHtml(str) {
        if (!str) return '';
        return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
    }

    function init() {
        cargar('todos');
        conectarWS();
        // Abrir detalle si viene con ?id=
        const params = new URLSearchParams(location.search);
        const id = params.get('id');
        if (id) setTimeout(() => abrirDetalle(id), 800);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    return { cargar, init };
})();
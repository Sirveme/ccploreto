/**
 * comunicaciones.js
 * static/js/pages/comunicaciones.js
 */

const ComUI = (() => {

    let _tipoFiltro = 'todos';
    let _comunicados = [];

    const TIPO_CONFIG = {
        comunicado:     { icon:'📢', label:'Comunicado',  css:'tipo-comunicado' },
        evento:         { icon:'📅', label:'Evento',      css:'tipo-evento' },
        oferta_laboral: { icon:'💼', label:'Oferta',      css:'tipo-oferta_laboral' },
        convenio:       { icon:'🤝', label:'Convenio',    css:'tipo-convenio' },
        fallecimiento:  { icon:'🕊', label:'Fallecimiento',css:'tipo-fallecimiento' },
        alerta:         { icon:'⚡', label:'Alerta',      css:'tipo-alerta' },
    };

    // ── Cargar comunicados ───────────────────────────────────
    async function cargar(tipo='todos') {
        const feed = document.getElementById('com-feed');
        feed.innerHTML = `
            <div class="com-loading">
                <div class="com-skeleton"></div>
                <div class="com-skeleton"></div>
                <div class="com-skeleton"></div>
            </div>`;

        try {
            const url = tipo === 'todos'
                ? '/api/comunicados/lista'
                : `/api/comunicados/lista?tipo=${tipo}`;
            const r = await fetch(url);
            const d = await r.json();
            _comunicados = d.comunicados || [];
            renderFeed(_comunicados);
        } catch(e) {
            feed.innerHTML = `
                <div class="com-empty">
                    <i class="ph ph-wifi-slash"></i>
                    <p>No se pudieron cargar los comunicados</p>
                </div>`;
        }
    }

    function renderFeed(lista) {
        const feed = document.getElementById('com-feed');
        if (!lista.length) {
            feed.innerHTML = `
                <div class="com-empty">
                    <i class="ph ph-megaphone-slash"></i>
                    <p>Sin comunicados en esta categoría</p>
                </div>`;
            return;
        }

        feed.innerHTML = lista.map((c, i) => renderCard(c, i)).join('');
        feed.querySelectorAll('.com-card').forEach(card => {
            card.addEventListener('click', () => abrirDetalle(card.dataset.id));
        });
    }

    function renderCard(c, idx) {
        const cfg   = TIPO_CONFIG[c.tipo] || TIPO_CONFIG.comunicado;
        const fecha = formatFecha(c.created_at);
        const delay = idx * 60;

        const imgHtml = c.image_url
            ? `<img class="com-card-img" src="${c.image_url}" alt="" loading="lazy">`
            : '';

        const eventoHtml = c.tipo === 'evento' && c.fecha_evento ? `
            <div class="com-card-evento-info">
                <i class="ph ph-calendar-check"></i>
                ${formatFechaEvento(c.fecha_evento)}
                ${c.lugar_evento ? `· <i class="ph ph-map-pin"></i> ${c.lugar_evento}` : ''}
            </div>` : '';

        return `
            <div class="com-card" data-id="${c.id}"
                 style="animation-delay:${delay}ms">
                ${imgHtml}
                <div class="com-card-body">
                    <div class="com-card-meta">
                        <span class="com-tipo-badge ${cfg.css}">${cfg.icon} ${cfg.label}</span>
                        ${!c.leido ? '<span class="com-card-nuevo"></span>' : ''}
                        <span class="com-card-fecha">${fecha}</span>
                    </div>
                    <div class="com-card-titulo">${escHtml(c.title)}</div>
                    <div class="com-card-resumen">${escHtml(c.content)}</div>
                </div>
                ${eventoHtml}
                <div class="com-card-footer">
                    <span>${c.autor || 'Directiva CCPL'}</span>
                    <span><i class="ph ph-arrow-right"></i></span>
                </div>
            </div>`;
    }

    // ── Detalle ──────────────────────────────────────────────
    function abrirDetalle(id) {
        const c = _comunicados.find(x => String(x.id) === String(id));
        if (!c) return;

        const cfg = TIPO_CONFIG[c.tipo] || TIPO_CONFIG.comunicado;

        const imgHtml = c.image_url
            ? `<img src="${c.image_url}" style="width:100%;border-radius:12px;margin-bottom:16px;object-fit:cover;max-height:220px">`
            : '';

        const videoHtml = c.video_url ? `
            <div style="position:relative;aspect-ratio:16/9;margin-bottom:16px">
                <iframe src="${c.video_url}" style="position:absolute;inset:0;width:100%;height:100%;border:none;border-radius:12px" allowfullscreen></iframe>
            </div>` : '';

        const eventoHtml = c.tipo === 'evento' ? `
            <div style="background:rgba(59,130,246,.08);border:1px solid rgba(59,130,246,.15);
                        border-radius:10px;padding:12px 14px;margin-bottom:16px;font-size:12px">
                ${c.fecha_evento ? `<div style="color:#60a5fa;margin-bottom:4px">
                    <i class="ph ph-calendar-check"></i> ${formatFechaEvento(c.fecha_evento)}</div>` : ''}
                ${c.lugar_evento ? `<div style="color:#94a3b8">
                    <i class="ph ph-map-pin"></i> ${c.lugar_evento}</div>` : ''}
                ${c.requiere_confirmacion ? `<div style="color:#f59e0b;margin-top:8px">
                    ⚠️ Requiere confirmación de asistencia</div>` : ''}
                ${c.genera_multa ? `<div style="color:#ef4444;margin-top:4px">
                    ⚡ La inasistencia genera multa</div>` : ''}
            </div>` : '';

        document.getElementById('com-modal-body').innerHTML = `
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:16px">
                <span class="com-tipo-badge ${cfg.css}">${cfg.icon} ${cfg.label}</span>
                <span style="font-size:11px;color:var(--muted);margin-left:auto">${formatFecha(c.created_at)}</span>
            </div>
            ${imgHtml}
            <h2 style="font-family:'Fraunces',serif;font-size:20px;font-weight:700;
                        margin-bottom:12px;line-height:1.3">${escHtml(c.title)}</h2>
            ${eventoHtml}
            <p style="font-size:14px;line-height:1.75;color:var(--text);margin-bottom:16px;
                      white-space:pre-wrap">${escHtml(c.content)}</p>
            ${videoHtml}
            <div style="font-size:11px;color:var(--muted);padding-top:12px;
                        border-top:1px solid var(--border)">
                Publicado por ${c.autor || 'Directiva CCPL'}
            </div>`;

        document.getElementById('com-modal').classList.add('open');

        // Marcar como leído
        fetch(`/api/comunicados/${id}/leer`, { method: 'POST' }).catch(() => {});
    }

    function cerrarDetalle(e) {
        if (e && e.target !== document.getElementById('com-modal')) return;
        document.getElementById('com-modal').classList.remove('open');
    }

    // ── Filtrar tabs ─────────────────────────────────────────
    function filtrar(tipo, btn) {
        _tipoFiltro = tipo;
        document.querySelectorAll('.com-tab').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');

        if (tipo === '__chat__') {
            document.getElementById('com-feed').style.display = 'none';
            document.getElementById('com-chat-panel').style.display = 'grid';
        } else {
            document.getElementById('com-feed').style.display = 'block';
            document.getElementById('com-chat-panel').style.display = 'none';
            cargar(tipo);
        }
    }

    // ── Compositor ───────────────────────────────────────────
    function abrirCompositor() {
        document.getElementById('com-compositor').style.display = 'flex';
    }

    function cerrarCompositor() {
        document.getElementById('com-compositor').style.display = 'none';
    }

    function selTipo(tipo, btn) {
        document.querySelectorAll('.comp-tipo-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById('comp-tipo-val').value = tipo;
        // Mostrar campos de evento si aplica
        const evFields = document.getElementById('comp-evento-fields');
        if (evFields) evFields.style.display = tipo === 'evento' ? 'block' : 'none';
    }

    function selPrior(p, btn) {
        document.querySelectorAll('.comp-prior-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById('comp-prior-val').value = p;
    }

    function selSeg(seg, btn) {
        document.querySelectorAll('.comp-seg-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById('comp-seg-val').value = seg;
    }

    function cargarImagen(input) {
        const file = input.files[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = e => {
            document.getElementById('comp-img-preview-img').src = e.target.result;
            document.getElementById('comp-img-preview').style.display = 'block';
            document.getElementById('comp-img-drop').innerHTML =
                `<i class="ph ph-check-circle"></i><span>${file.name}</span>`;
        };
        reader.readAsDataURL(file);
        subirImagen(file);
    }

    function soltarImagen(e) {
        e.preventDefault();
        document.getElementById('comp-img-drop').classList.remove('drag-over');
        const file = e.dataTransfer.files[0];
        if (file && file.type.startsWith('image/')) {
            const dt = new DataTransfer();
            dt.items.add(file);
            document.getElementById('comp-img-file').files = dt.files;
            cargarImagen(document.getElementById('comp-img-file'));
        }
    }

    async function subirImagen(file) {
        const fd = new FormData();
        fd.append('imagen', file);
        try {
            const r = await fetch('/api/comunicados/subir-imagen', { method:'POST', body:fd });
            const d = await r.json();
            if (d.url) document.getElementById('comp-img-url').value = d.url;
        } catch(e) {}
    }

    async function enviar() {
        const titulo    = document.getElementById('comp-titulo')?.value.trim();
        const contenido = document.getElementById('comp-contenido')?.value.trim();
        const tipo      = document.getElementById('comp-tipo-val')?.value || 'comunicado';
        const prioridad = document.getElementById('comp-prior-val')?.value || 'info';
        const segmento  = document.getElementById('comp-seg-val')?.value || 'todos';
        const imgUrl    = document.getElementById('comp-img-url')?.value.trim();
        const videoUrl  = document.getElementById('comp-video-url')?.value.trim();
        const caduca    = document.getElementById('comp-caduca')?.value;
        const fechaEvento = document.getElementById('comp-fecha-evento')?.value;
        const lugar     = document.getElementById('comp-lugar')?.value.trim();
        const reqConf   = document.getElementById('comp-requiere-conf')?.checked;
        const genMulta  = document.getElementById('comp-genera-multa')?.checked;

        if (!titulo) { mostrarFeedback('El título es obligatorio', 'error'); return; }
        if (!contenido) { mostrarFeedback('El mensaje es obligatorio', 'error'); return; }

        const btn = document.getElementById('comp-btn-enviar');
        btn.disabled = true;
        btn.innerHTML = '<i class="ph ph-spinner"></i> Publicando...';

        try {
            const r = await fetch('/api/comunicados/enviar', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    title:                 titulo,
                    content:               contenido,
                    tipo,
                    priority:              prioridad,
                    image_url:             imgUrl || null,
                    video_url:             videoUrl || null,
                    segmento,
                    expires_at:            caduca || null,
                    fecha_evento:          fechaEvento || null,
                    lugar_evento:          lugar || null,
                    requiere_confirmacion: reqConf || false,
                    genera_multa:          genMulta || false,
                    target_criteria:       { segmento },
                }),
            });
            const d = await r.json();
            if (d.ok) {
                mostrarFeedback(`✅ Publicado — notificado a ${d.destinatarios} dispositivos`, 'success');
                setTimeout(() => {
                    cerrarCompositor();
                    cargar(_tipoFiltro);
                }, 2000);
            } else {
                mostrarFeedback(`Error: ${d.error || d.mensaje}`, 'error');
            }
        } catch(e) {
            mostrarFeedback('Error de conexión', 'error');
        } finally {
            btn.disabled = false;
            btn.innerHTML = '<i class="ph ph-paper-plane-tilt"></i> Publicar y notificar';
        }
    }

    function mostrarFeedback(msg, tipo) {
        const el = document.getElementById('comp-feedback');
        if (!el) return;
        el.textContent = msg;
        el.style.display = 'block';
        el.style.cssText += `;margin-top:10px;padding:10px;border-radius:8px;font-size:12px;
            text-align:center;
            background:${tipo==='success'?'rgba(0,217,126,.1)':'rgba(239,68,68,.1)'};
            color:${tipo==='success'?'#00d97e':'#ef4444'};
            border:1px solid ${tipo==='success'?'rgba(0,217,126,.2)':'rgba(239,68,68,.2)'}`;
        setTimeout(() => { el.style.display = 'none'; }, 4000);
    }

    // ── WS tiempo real ───────────────────────────────────────
    function conectarWS() {
        const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        const ws = new WebSocket(`${proto}//${location.host}/ws/alerta`);
        ws.onmessage = e => {
            try {
                const msg = JSON.parse(e.data);
                if (msg.type === 'BULLETIN') {
                    // Recargar si estamos en el tab correcto
                    if (_tipoFiltro === 'todos' || _tipoFiltro === msg.tipo) {
                        cargar(_tipoFiltro);
                    }
                    // Mostrar punto en bell
                    const dot = document.getElementById('com-bell-dot');
                    if (dot) dot.style.display = 'block';
                }
            } catch(err) {}
        };
        ws.onclose = () => setTimeout(conectarWS, 3000);
        ws.onerror = () => ws.close();
    }

    // ── Helpers ──────────────────────────────────────────────
    function formatFecha(iso) {
        if (!iso) return '';
        const diff = Math.floor((Date.now() - new Date(iso)) / 1000);
        if (diff < 60)     return 'Ahora';
        if (diff < 3600)   return `Hace ${Math.floor(diff/60)} min`;
        if (diff < 86400)  return `Hace ${Math.floor(diff/3600)}h`;
        if (diff < 604800) return `Hace ${Math.floor(diff/86400)}d`;
        return new Date(iso).toLocaleDateString('es-PE', { day:'numeric', month:'short', year:'numeric' });
    }

    function formatFechaEvento(iso) {
        if (!iso) return '';
        return new Date(iso).toLocaleDateString('es-PE', {
            weekday:'long', day:'numeric', month:'long', hour:'2-digit', minute:'2-digit'
        });
    }

    function escHtml(str) {
        if (!str) return '';
        return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    }

    // ── Init ─────────────────────────────────────────────────
    function init() {
        cargar('todos');
        conectarWS();
    }

    document.addEventListener('DOMContentLoaded', init);

    return {
        filtrar, cargar,
        abrirDetalle, cerrarDetalle,
        abrirCompositor, cerrarCompositor,
        selTipo, selPrior, selSeg,
        cargarImagen, soltarImagen,
        enviar,
    };
})();
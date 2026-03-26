/**
 * comunicaciones.js  v2
 * static/js/pages/comunicaciones.js
 */

const ComUI = (() => {

    let _tipo = 'todos';
    let _lista = [];

    const TIPO_CFG = {
        comunicado:     { icon:'📢', label:'Comunicado',    css:'tipo-comunicado',     plantilla:'compacto' },
        evento:         { icon:'📅', label:'Evento',        css:'tipo-evento',         plantilla:'evento'   },
        oferta_laboral: { icon:'💼', label:'Oferta Laboral',css:'tipo-oferta_laboral', plantilla:'oferta'   },
        convenio:       { icon:'🤝', label:'Convenio',      css:'tipo-convenio',       plantilla:'imagen'   },
        fallecimiento:  { icon:'🕊', label:'Fallecimiento', css:'tipo-fallecimiento',  plantilla:'duelo'    },
        alerta:         { icon:'⚡', label:'Alerta',        css:'tipo-alerta',         plantilla:'alerta'   },
    };

    // Tipos que permiten chat
    const CHAT_DEST = {
        evento: 'mesa_partes', comunicado: 'secretaria',
        oferta_laboral: 'admin', convenio: 'admin',
    };

    // ── Cargar ───────────────────────────────────────────────
    async function cargar(tipo='todos') {
        const feed = document.getElementById('com-feed');
        feed.innerHTML = `
            <div class="com-skel com-skel-tall"></div>
            <div class="com-skel com-skel-medium"></div>
            <div class="com-skel com-skel-medium"></div>`;

        try {
            const url = tipo === 'todos'
                ? '/api/comunicados/lista'
                : `/api/comunicados/lista?tipo=${tipo}`;
            const r = await fetch(url);
            const d = await r.json();
            _lista = d.comunicados || [];
            renderFeed(_lista);
            cargarSidebar(_lista);
        } catch(e) {
            feed.innerHTML = `<div class="com-empty">
                <i class="ph ph-wifi-slash"></i>
                <p>No se pudieron cargar los comunicados</p></div>`;
        }
    }

    // ── Render feed ──────────────────────────────────────────
    function renderFeed(lista) {
        const feed = document.getElementById('com-feed');
        if (!lista.length) {
            feed.innerHTML = `<div class="com-empty">
                <i class="ph ph-megaphone-slash"></i>
                <p>Sin comunicados en esta categoría</p></div>`;
            return;
        }
        feed.innerHTML = lista.map((c, i) => renderCard(c, i)).join('');
        feed.querySelectorAll('.com-card').forEach(card => {
            card.addEventListener('click', () => abrirDetalle(card.dataset.id));
        });
    }

    // ── Plantillas ───────────────────────────────────────────
    function renderCard(c, idx) {
        const cfg     = TIPO_CFG[c.tipo] || TIPO_CFG.comunicado;
        const delay   = Math.min(idx * 55, 400);
        const acciones = renderAcciones(c);
        const footer   = renderFooter(c);

        // Elegir plantilla según tipo (o si tiene imagen → imagen)
        const plantilla = c.image_url && cfg.plantilla !== 'evento'
            ? (cfg.plantilla === 'alerta' ? 'alerta' : 'imagen')
            : cfg.plantilla;

        let html = '';

        switch(plantilla) {

            case 'imagen':
                html = `
                <div class="com-card card-imagen" data-id="${c.id}"
                     style="animation-delay:${delay}ms">
                    <img class="card-img" src="${c.image_url}" alt="" loading="lazy">
                    <div class="card-body">
                        <div class="card-meta">
                            <span class="com-tipo-badge ${cfg.css}">${cfg.icon} ${cfg.label}</span>
                            ${!c.leido?'<span class="com-card-nuevo"></span>':''}
                            <span class="card-fecha">${fmt(c.created_at)}</span>
                        </div>
                        <div class="card-titulo">${esc(c.title)}</div>
                        <div class="card-resumen">${esc(c.content)}</div>
                    </div>
                    ${acciones}${footer}
                </div>`;
                break;

            case 'evento':
                const ev   = c.fecha_evento ? new Date(c.fecha_evento) : null;
                const dia  = ev ? ev.getDate() : '?';
                const mes  = ev ? ev.toLocaleDateString('es-PE',{month:'short'}).toUpperCase() : '';
                html = `
                <div class="com-card card-evento" data-id="${c.id}"
                     style="animation-delay:${delay}ms">
                    <div class="card-body">
                        <div class="card-meta">
                            <span class="com-tipo-badge ${cfg.css}">${cfg.icon} ${cfg.label}</span>
                            ${!c.leido?'<span class="com-card-nuevo"></span>':''}
                        </div>
                        <div style="display:flex;gap:14px;align-items:flex-start">
                            ${ev?`<div class="card-fecha-badge">
                                <div class="dia">${dia}</div>
                                <div class="mes">${mes}</div>
                            </div>`:''}
                            <div class="card-info">
                                <div class="card-titulo">${esc(c.title)}</div>
                                ${c.lugar_evento?`<div class="card-lugar">
                                    <i class="ph ph-map-pin"></i> ${esc(c.lugar_evento)}</div>`:''}
                            </div>
                        </div>
                        ${c.genera_multa?`<div class="card-multa-warn">
                            <i class="ph ph-warning"></i> La inasistencia genera multa</div>`:''}
                    </div>
                    ${acciones}${footer}
                </div>`;
                break;

            case 'oferta':
                html = `
                <div class="com-card card-oferta" data-id="${c.id}"
                     style="animation-delay:${delay}ms">
                    <div class="card-body">
                        <div class="card-meta" style="display:flex;gap:8px;align-items:center;margin-bottom:10px">
                            <span class="com-tipo-badge ${cfg.css}">${cfg.icon} ${cfg.label}</span>
                            ${!c.leido?'<span class="com-card-nuevo"></span>':''}
                            <span style="font-size:11px;color:var(--c-muted);margin-left:auto">${fmt(c.created_at)}</span>
                        </div>
                        <div class="card-titulo">${esc(c.title)}</div>
                        <div class="card-empresa">${esc(c.autor||'Directiva CCPL')}</div>
                        <div class="card-resumen">${esc(c.content)}</div>
                    </div>
                    ${acciones}${footer}
                </div>`;
                break;

            case 'duelo':
                html = `
                <div class="com-card card-duelo" data-id="${c.id}"
                     style="animation-delay:${delay}ms">
                    <div class="card-body">
                        <div class="card-cruz">✝</div>
                        <div class="card-titulo">${esc(c.title)}</div>
                        <div class="card-resumen">${esc(c.content)}</div>
                        <div style="margin-top:10px;font-size:11px;color:var(--c-muted)">${fmt(c.created_at)}</div>
                    </div>
                    ${footer}
                </div>`;
                break;

            case 'alerta':
                html = `
                <div class="com-card card-alerta" data-id="${c.id}"
                     style="animation-delay:${delay}ms">
                    <div class="card-body">
                        <div class="card-breaking">
                            <span class="breaking-dot"></span>
                            <span class="breaking-label">Alerta</span>
                            <span style="font-size:11px;color:var(--c-muted);margin-left:auto">${fmt(c.created_at)}</span>
                        </div>
                        <div class="card-titulo">${esc(c.title)}</div>
                        <div class="card-resumen">${esc(c.content)}</div>
                    </div>
                    ${acciones}${footer}
                </div>`;
                break;

            default: // compacto
                html = `
                <div class="com-card card-compacto" data-id="${c.id}"
                     style="animation-delay:${delay}ms">
                    <div class="card-body">
                        <div class="card-meta">
                            <span class="com-tipo-badge ${cfg.css}">${cfg.icon} ${cfg.label}</span>
                            ${!c.leido?'<span class="com-card-nuevo"></span>':''}
                            <span class="card-fecha">${fmt(c.created_at)}</span>
                        </div>
                        <div class="card-titulo">${esc(c.title)}</div>
                        <div class="card-resumen">${esc(c.content)}</div>
                    </div>
                    ${acciones}${footer}
                </div>`;
        }
        return html;
    }

    function renderAcciones(c) {
        const tienechat = !!CHAT_DEST[c.tipo];
        return `
            <div class="com-card-acciones">
                <button class="com-accion-btn"
                        onclick="event.stopPropagation();ComUI.likeCard(${c.id},this)"
                        data-liked="false">
                    <i class="ph ph-thumbs-up"></i>
                    <span class="like-count">${c.likes||0}</span>
                </button>
                <button class="com-accion-btn"
                        onclick="event.stopPropagation();ComUI.compartir(${c.id},'${esc(c.title)}')">
                    <i class="ph ph-share-network"></i> Compartir
                </button>
                ${tienechat?`
                <button class="com-accion-btn com-accion-chat"
                        onclick="event.stopPropagation();ComUI.iniciarChat(${c.id},'${c.tipo}')">
                    <i class="ph ph-chat-circle-dots"></i> Consultar
                </button>`:''}
            </div>`;
    }

    function renderFooter(c) {
        return `
            <div class="com-card-footer">
                <span class="autor">
                    <i class="ph ph-user-circle"></i>
                    ${esc(c.autor||'Directiva CCPL')}
                </span>
                <span class="ver-mas">Ver más <i class="ph ph-arrow-right"></i></span>
            </div>`;
    }

    // ── Sidebar ──────────────────────────────────────────────
    function cargarSidebar(lista) {
        // Próximos eventos
        const eventos = lista
            .filter(c => c.tipo === 'evento' && c.fecha_evento)
            .sort((a,b) => new Date(a.fecha_evento) - new Date(b.fecha_evento))
            .slice(0, 3);

        const evBody = document.getElementById('sidebar-eventos-body');
        if (evBody) {
            evBody.innerHTML = eventos.length ? eventos.map(c => {
                const d = new Date(c.fecha_evento);
                return `
                    <div class="sidebar-evento-item" onclick="ComUI.abrirDetalle(${c.id})">
                        <div class="sidebar-evento-fecha">
                            <div class="d">${d.getDate()}</div>
                            <div class="m">${d.toLocaleDateString('es-PE',{month:'short'}).toUpperCase()}</div>
                        </div>
                        <div class="sidebar-evento-info">
                            <div class="sidebar-evento-titulo">${esc(c.title)}</div>
                            ${c.lugar_evento?`<div class="sidebar-evento-lugar"><i class="ph ph-map-pin"></i> ${esc(c.lugar_evento)}</div>`:''}
                        </div>
                    </div>`;
            }).join('') : '<div style="font-size:12px;color:var(--c-muted);text-align:center;padding:8px 0;font-style:italic">Sin eventos próximos</div>';
        }

        // Stats
        const hoy = lista.filter(c => {
            const d = new Date(c.created_at);
            const n = new Date();
            return d.getDate()===n.getDate() && d.getMonth()===n.getMonth();
        }).length;
        const noleidos = lista.filter(c => !c.leido).length;

        const el = (id, v) => { const e=document.getElementById(id); if(e) e.textContent=v; };
        el('stat-hoy', hoy);
        el('stat-mes', lista.length);
        el('stat-noleidos', noleidos);
        if(noleidos>0) {
            const dot = document.getElementById('com-bell-dot');
            if(dot) dot.style.display='block';
        }
    }

    // ── Detalle ──────────────────────────────────────────────
    function abrirDetalle(id) {
        const c = _lista.find(x => String(x.id)===String(id));
        if (!c) return;
        const cfg = TIPO_CFG[c.tipo] || TIPO_CFG.comunicado;

        const imgHtml = c.image_url
            ? `<img class="com-modal-img" src="${c.image_url}" alt="">`
            : '';

        const videoHtml = c.video_url ? `
            <div style="position:relative;aspect-ratio:16/9;margin-bottom:16px">
                <iframe src="${c.video_url}" style="position:absolute;inset:0;width:100%;
                    height:100%;border:none;border-radius:12px" allowfullscreen></iframe>
            </div>` : '';

        const eventoHtml = c.tipo==='evento' && c.fecha_evento ? `
            <div class="com-modal-fecha-evento">
                <i class="ph ph-calendar-check"></i> ${fmtEvento(c.fecha_evento)}
                ${c.lugar_evento?`<br><i class="ph ph-map-pin"></i> ${esc(c.lugar_evento)}`:''}
                ${c.requiere_confirmacion?`<br>⚠️ Requiere confirmación de asistencia`:''}
                ${c.genera_multa?`<br>⚡ La inasistencia genera multa`:''}
            </div>` : '';

        document.getElementById('com-modal-body').innerHTML = `
            <div class="com-modal-meta">
                <span class="com-tipo-badge ${cfg.css}">${cfg.icon} ${cfg.label}</span>
                <span style="font-size:11px;color:var(--c-muted);margin-left:auto">${fmt(c.created_at)}</span>
            </div>
            ${imgHtml}
            <h2 class="com-modal-titulo">${esc(c.title)}</h2>
            ${eventoHtml}
            <p class="com-modal-contenido">${linkificar(esc(c.content))}</p>
            ${videoHtml}
            <div class="com-modal-footer">
                <i class="ph ph-user-circle"></i>
                ${esc(c.autor||'Directiva CCPL')}
            </div>`;

        document.getElementById('com-modal').classList.add('open');
        fetch(`/api/comunicados/${id}/leer`, {method:'POST'}).catch(()=>{});
    }

    function cerrarDetalle(e) {
        if (e && e.target !== document.getElementById('com-modal')) return;
        document.getElementById('com-modal').classList.remove('open');
    }

    // ── Filtrar ──────────────────────────────────────────────
    function filtrar(tipo, btn) {
        _tipo = tipo;
        document.querySelectorAll('.com-tab').forEach(b=>b.classList.remove('active'));
        btn.classList.add('active');

        const feed    = document.getElementById('com-feed');
        const chat    = document.getElementById('com-chat-section');
        const sidebar = document.getElementById('com-sidebar');

        if (tipo === '__chat__') {
            feed.style.display    = 'none';
            sidebar.style.display = 'none';
            chat.style.display    = 'block';
        } else {
            feed.style.display    = 'block';
            sidebar.style.display = 'flex';
            chat.style.display    = 'none';
            cargar(tipo);
        }
    }

    function linkificar(texto) {
        return texto.replace(
            /(https?:\/\/[^\s<]+)/g,
            '<a href="$1" target="_blank" rel="noopener" '
            + 'style="color:var(--c-gold);text-decoration:underline">$1</a>'
        );
    }

    // ── Acciones ─────────────────────────────────────────────
    function likeCard(id, btn) {
        const liked = btn.dataset.liked==='true';
        btn.dataset.liked = String(!liked);
        const icon  = btn.querySelector('i');
        const count = btn.querySelector('.like-count');
        if (!liked) {
            icon.className='ph ph-thumbs-up-fill';
            btn.classList.add('liked');
            count.textContent=parseInt(count.textContent||0)+1;
        } else {
            icon.className='ph ph-thumbs-up';
            btn.classList.remove('liked');
            count.textContent=Math.max(0,parseInt(count.textContent||0)-1);
        }
        fetch(`/api/comunicados/${id}/like`,{method:'POST'}).catch(()=>{});
    }

    function compartir(id, titulo) {
        const url=`${location.origin}/comunicaciones?id=${id}`;
        if (navigator.share) {
            navigator.share({title:titulo,url}).catch(()=>{});
        } else {
            navigator.clipboard?.writeText(url);
            if(window.Toast) Toast.show('🔗 Enlace copiado','success');
        }
    }

    function iniciarChat(bulletinId, tipo) {
        const dest = CHAT_DEST[tipo];
        if (!dest) return;
        const tab = document.querySelector('.com-tab[data-tipo="__chat__"]');
        if (tab) tab.click();
        else window.location.href='/dashboard?chat='+dest;
        window._chatContexto={bulletin_id:bulletinId,tipo,dest};
    }

    // ── Compositor ───────────────────────────────────────────
    function abrirCompositor()  { document.getElementById('com-compositor').style.display='flex'; }
    function cerrarCompositor() { document.getElementById('com-compositor').style.display='none'; }

    function selTipo(t,btn) {
        document.querySelectorAll('.comp-tipo-btn').forEach(b=>b.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById('comp-tipo-val').value=t;
        const ef=document.getElementById('comp-evento-fields');
        if(ef) ef.style.display=t==='evento'?'block':'none';
    }

    function selPrior(p,btn) {
        document.querySelectorAll('.comp-prior-btn').forEach(b=>b.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById('comp-prior-val').value=p;
    }

    function selSeg(s,btn) {
        document.querySelectorAll('.comp-seg-btn').forEach(b=>b.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById('comp-seg-val').value=s;
    }

    function cargarImagen(input) {
        const file=input.files[0]; if(!file) return;
        const r=new FileReader();
        r.onload=e=>{
            document.getElementById('comp-img-preview-img').src=e.target.result;
            document.getElementById('comp-img-preview').style.display='block';
            document.getElementById('comp-img-drop').innerHTML=`<i class="ph ph-check-circle"></i><span>${file.name}</span>`;
        };
        r.readAsDataURL(file);
        subirImagen(file);
    }

    function soltarImagen(e) {
        e.preventDefault();
        document.getElementById('comp-img-drop').classList.remove('drag-over');
        const file=e.dataTransfer.files[0];
        if(file&&file.type.startsWith('image/')){
            const dt=new DataTransfer(); dt.items.add(file);
            document.getElementById('comp-img-file').files=dt.files;
            cargarImagen(document.getElementById('comp-img-file'));
        }
    }

    async function subirImagen(file) {
        const fd=new FormData(); fd.append('imagen',file);
        try {
            const r=await fetch('/api/comunicados/subir-imagen',{method:'POST',body:fd});
            const d=await r.json();
            if(d.url) document.getElementById('comp-img-url').value=d.url;
        } catch(e){}
    }

    async function enviar() {
        const titulo   =document.getElementById('comp-titulo')?.value.trim();
        const contenido=document.getElementById('comp-contenido')?.value.trim();
        const tipo     =document.getElementById('comp-tipo-val')?.value||'comunicado';
        const prioridad=document.getElementById('comp-prior-val')?.value||'info';
        const segmento =document.getElementById('comp-seg-val')?.value||'todos';
        const imgUrl   =document.getElementById('comp-img-url')?.value.trim();
        const videoUrl =document.getElementById('comp-video-url')?.value.trim();
        const caduca   =document.getElementById('comp-caduca')?.value;
        const fechaEv  =document.getElementById('comp-fecha-evento')?.value;
        const lugar    =document.getElementById('comp-lugar')?.value.trim();
        const reqConf  =document.getElementById('comp-requiere-conf')?.checked;
        const multa    =document.getElementById('comp-genera-multa')?.checked;

        if(!titulo)   { feedback('El título es obligatorio','error'); return; }
        if(!contenido){ feedback('El mensaje es obligatorio','error'); return; }

        const btn=document.getElementById('comp-btn-enviar');
        btn.disabled=true;
        btn.innerHTML='<i class="ph ph-spinner"></i> Publicando...';

        try {
            const r=await fetch('/api/comunicados/enviar',{
                method:'POST',
                headers:{'Content-Type':'application/json'},
                body:JSON.stringify({
                    title:titulo, content:contenido, tipo,
                    priority:prioridad, image_url:imgUrl||null,
                    video_url:videoUrl||null, segmento,
                    expires_at:caduca||null, fecha_evento:fechaEv||null,
                    lugar_evento:lugar||null,
                    requiere_confirmacion:reqConf||false,
                    genera_multa:multa||false,
                    target_criteria:{segmento},
                }),
            });
            const d=await r.json();
            if(d.ok){
                feedback(`✅ Publicado — ${d.destinatarios} dispositivos notificados`,'success');
                
                setTimeout(()=>{
                    cerrarCompositor();
                    cargar(_tipo);
                    // Limpiar formulario
                    ['comp-titulo','comp-contenido','comp-img-url','comp-video-url','comp-caduca',
                    'comp-fecha-evento','comp-lugar'].forEach(id=>{
                        const el=document.getElementById(id); if(el) el.value='';
                    });
                    document.getElementById('comp-img-preview').style.display='none';
                    document.getElementById('comp-img-drop').innerHTML='<i class="ph ph-image"></i><span>Arrastra o toca para seleccionar</span>';
                    document.getElementById('comp-requiere-conf').checked=false;
                    document.getElementById('comp-genera-multa').checked=false;
                },2000);


            } else {
                feedback(`Error: ${d.error||d.mensaje}`,'error');
            }
        } catch(e){ feedback('Error de conexión','error'); }
        finally {
            btn.disabled=false;
            btn.innerHTML='<i class="ph ph-paper-plane-tilt"></i> Publicar y notificar';
        }
    }

    function feedback(msg,tipo) {
        const el=document.getElementById('comp-feedback'); if(!el) return;
        el.textContent=msg; el.style.display='block';
        el.style.background=tipo==='success'?'rgba(56,178,114,.1)':'rgba(229,62,62,.1)';
        el.style.color=tipo==='success'?'#38b272':'#fc8181';
        el.style.border=`1px solid ${tipo==='success'?'rgba(56,178,114,.2)':'rgba(229,62,62,.2)'}`;
        setTimeout(()=>el.style.display='none',4000);
    }

    // ── WS ───────────────────────────────────────────────────
    function conectarWS() {
        const proto=location.protocol==='https:'?'wss:':'ws:';
        const ws=new WebSocket(`${proto}//${location.host}/ws/alerta`);
        ws.onmessage=e=>{
            try {
                const msg=JSON.parse(e.data);
                if(msg.type==='BULLETIN'){
                    if(_tipo==='todos'||_tipo===msg.tipo) cargar(_tipo);
                    const dot=document.getElementById('com-bell-dot');
                    if(dot) dot.style.display='block';
                }
            } catch(err){}
        };
        ws.onclose=()=>setTimeout(conectarWS,3000);
        ws.onerror=()=>ws.close();
    }

    // ── Helpers ──────────────────────────────────────────────
    function fmt(iso) {
        if(!iso) return '';
        const diff=Math.floor((Date.now()-new Date(iso))/1000);
        if(diff<60)     return 'Ahora';
        if(diff<3600)   return `Hace ${Math.floor(diff/60)} min`;
        if(diff<86400)  return `Hace ${Math.floor(diff/3600)}h`;
        if(diff<604800) return `Hace ${Math.floor(diff/86400)}d`;
        return new Date(iso).toLocaleDateString('es-PE',{day:'numeric',month:'short',year:'numeric'});
    }

    function fmtEvento(iso) {
        if(!iso) return '';
        return new Date(iso).toLocaleDateString('es-PE',{
            weekday:'long',day:'numeric',month:'long',hour:'2-digit',minute:'2-digit'
        });
    }

    function esc(str) {
        if(!str) return '';
        return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    }

    // ── Init ─────────────────────────────────────────────────
    function init() {
        cargar('todos');
        conectarWS();
        // Abrir detalle si viene con ?id=
        const id=new URLSearchParams(location.search).get('id');
        if(id) setTimeout(()=>abrirDetalle(id),700);
    }

    document.addEventListener('DOMContentLoaded', init);

    return {
        filtrar, cargar,
        abrirDetalle, cerrarDetalle,
        abrirCompositor, cerrarCompositor,
        selTipo, selPrior, selSeg,
        cargarImagen, soltarImagen,
        enviar, likeCard, compartir, iniciarChat,
    };
})();
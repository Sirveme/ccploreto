/**
 * Modal Mis Pagos — Dashboard Colegiado CCPL
 * Adaptado a: GET /api/colegiado/mis-pagos
 *
 * Estructura de respuesta esperada:
 *   colegiado, resumen, deudas[], catalogo[], categorias[], historial[]
 *
 * Archivo: static/js/modules/modal-pagos.js
 */

if (typeof window.ModalPagos === 'undefined') {

window.ModalPagos = {
    data:          null,
    isLoading:     false,
    carrito:       [],          // { id, nombre, precio, cantidad }
    tabActiva:     'deudas',
    catFiltro:     'todos',     // filtro activo en tab Servicios

    // ─────────────────────────────────────────────────────────
    //  INIT
    // ─────────────────────────────────────────────────────────
    init() {
        this._injectStyles();

        // Delegation desde document — funciona aunque el fragment cargue tarde (lazy)
        document.addEventListener('click', e => {
            // Solo actuar si el click está dentro de #modal-pagos
            if (!e.target.closest('#modal-pagos')) return;

            const tab = e.target.closest('[data-pagos-tab]');
            if (tab) { this.switchTab(tab.dataset.pagosTab); return; }

            const accion = e.target.closest('[data-accion]');
            if (accion) { this._dispatch(accion); return; }

            const pill = e.target.closest('[data-cat-filtro]');
            if (pill) { this._filtrarCatalogo(pill.dataset.catFiltro); return; }
        });

        document.addEventListener('change', e => {
            if (!e.target.closest('#modal-pagos')) return;
            if (e.target.dataset.cantidadId) {
                this._setCantidad(
                    parseInt(e.target.dataset.cantidadId),
                    parseInt(e.target.value) || 1
                );
            }
        });
    },

    _injectStyles() {
        if (document.getElementById('mp-styles')) return;
        const s = document.createElement('style');
        s.id = 'mp-styles';
        s.textContent = `
.mp-tabs{display:flex;gap:0;border-bottom:2px solid var(--color-border,#2a2a3a);margin:0 -1.25rem;padding:0 1.25rem}
[data-pagos-tab]{display:flex;align-items:center;gap:.4rem;padding:.65rem 1rem;background:none;border:none;border-bottom:2px solid transparent;margin-bottom:-2px;color:var(--color-text-muted,#999);font-size:.85rem;font-weight:500;cursor:pointer;transition:color .15s,border-color .15s;white-space:nowrap}
[data-pagos-tab]:hover{color:var(--color-text,#eee)}
[data-pagos-tab].active{color:var(--color-primary,#f59e0b);border-bottom-color:var(--color-primary,#f59e0b)}
[data-pagos-tab] i{font-size:1rem}
[data-pagos-panel]{display:none;padding:1rem 0}
[data-pagos-panel].active{display:block}
.mp-resumen-header{display:grid;grid-template-columns:repeat(3,1fr);gap:.6rem;margin-bottom:.75rem}
.mp-resumen-item{background:var(--color-bg-card,#1e1e2e);border:1px solid var(--color-border,#2a2a3a);border-radius:8px;padding:.65rem .75rem;text-align:center}
.mp-resumen-item label{display:block;font-size:.68rem;color:var(--color-text-muted,#888);margin-bottom:.2rem;white-space:nowrap}
.mp-resumen-item strong{font-size:1rem;font-weight:700;color:var(--color-text,#eee)}
.mp-resumen-item.mp-deuda strong{color:#ef4444}
.mp-resumen-item.mp-revision strong{color:#f59e0b}
.mp-resumen-item.mp-pagado strong{color:#22c55e}
.mp-badge{display:inline-flex;align-items:center;padding:.12rem .5rem;border-radius:999px;font-size:.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.04em}
.mp-badge--habil{background:#dcfce7;color:#166534}
.mp-badge--inhabil{background:#fee2e2;color:#991b1b}
.mp-badge--approved{background:#dcfce7;color:#166534}
.mp-badge--review{background:#fef9c3;color:#854d0e}
.mp-badge--rejected{background:#fee2e2;color:#991b1b}
.mp-deudas-total{display:flex;justify-content:space-between;align-items:center;padding:.5rem 0 .75rem;font-size:.83rem;color:var(--color-text-muted,#888)}
.mp-monto-danger{color:#ef4444!important;font-size:1.05rem;font-weight:700}
.mp-deudas-lista{display:flex;flex-direction:column;gap:.5rem}
.mp-deuda-row{display:flex;align-items:center;justify-content:space-between;gap:.75rem;background:var(--color-bg-card,#1e1e2e);border:1px solid var(--color-border,#2a2a3a);border-radius:8px;padding:.7rem .9rem}
.mp-deuda-info{display:flex;flex-direction:column;gap:.12rem;flex:1;min-width:0}
.mp-deuda-concepto{font-size:.88rem;font-weight:600;color:var(--color-text,#eee);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mp-deuda-meta{font-size:.72rem;color:var(--color-text-muted,#888)}
.mp-deuda-right{display:flex;align-items:center;gap:.65rem;flex-shrink:0}
.mp-monto{display:flex;flex-direction:column;align-items:flex-end;gap:.08rem;font-size:.92rem;font-weight:700;color:var(--color-text,#eee)}
.mp-monto small{font-size:.68rem;font-weight:400;color:var(--color-text-muted,#888)}
.mp-monto--parcial{color:#f59e0b}
.mp-monto-sm{font-size:.9rem;font-weight:700;color:var(--color-text,#eee)}
.mp-fraccionar-box{display:flex;align-items:flex-start;gap:.75rem;background:rgba(99,102,241,.07);border:1px solid rgba(99,102,241,.25);border-radius:10px;padding:.85rem 1rem;margin-top:1rem;font-size:.82rem}
.mp-fraccionar-box>i{font-size:1.4rem;color:#818cf8;flex-shrink:0;margin-top:.1rem}
.mp-fraccionar-box strong{display:block;font-size:.84rem;color:var(--color-text,#eee)}
.mp-fraccionar-box p{margin:.15rem 0 0;color:var(--color-text-muted,#999)}
.mp-cat-pills{display:flex;gap:.45rem;overflow-x:auto;padding-bottom:.6rem;margin-bottom:.75rem;scrollbar-width:none}
.mp-cat-pills::-webkit-scrollbar{display:none}
.mp-cat-pill{display:inline-flex;align-items:center;gap:.35rem;padding:.3rem .75rem;background:var(--color-bg-card,#1e1e2e);border:1px solid var(--color-border,#2a2a3a);border-radius:999px;color:var(--color-text-muted,#999);font-size:.78rem;font-weight:500;white-space:nowrap;cursor:pointer;transition:all .15s}
.mp-cat-pill:hover,.mp-cat-pill.active{border-color:var(--cat-color,#f59e0b);color:var(--cat-color,#f59e0b)}
.mp-cat-pill.active{background:rgba(245,158,11,.1)}
.mp-cat-count{background:var(--color-border,#2a2a3a);border-radius:999px;padding:0 .35rem;font-size:.68rem;font-weight:700;min-width:16px;text-align:center;color:var(--color-text-muted,#888)}
.mp-catalogo-grupo{margin-bottom:.9rem}
.mp-grupo-header{display:flex;align-items:center;gap:.45rem;font-size:.72rem;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:var(--cat-color,var(--color-text-muted,#888));padding:.3rem 0;border-bottom:1px solid var(--color-border,#2a2a3a);margin-bottom:.5rem}
.mp-grupo-header i{font-size:1rem}
.mp-item{display:flex;align-items:center;justify-content:space-between;gap:.75rem;padding:.65rem .85rem;background:var(--color-bg-card,#1e1e2e);border:1px solid var(--color-border,#2a2a3a);border-radius:8px;margin-bottom:.4rem;transition:border-color .15s}
.mp-item:hover{border-color:rgba(245,158,11,.3)}
.mp-item-info{display:flex;flex-direction:column;gap:.1rem;flex:1;min-width:0}
.mp-item-nombre{font-size:.87rem;font-weight:500;color:var(--color-text,#eee)}
.mp-item-desc{font-size:.72rem;color:var(--color-text-muted,#888)}
.mp-stock{font-size:.7rem;margin-top:.1rem}
.mp-stock--ok{color:#22c55e}
.mp-stock--agotado,.mp-tag-agotado{color:#ef4444;font-size:.72rem}
.mp-item-acciones{display:flex;align-items:center;gap:.5rem;flex-shrink:0}
.mp-item-precio{font-size:.9rem;font-weight:700;color:var(--color-primary,#f59e0b);white-space:nowrap}
.mp-item-en-carrito{display:flex;align-items:center;gap:.4rem}
.mp-item-en-carrito input{width:52px;padding:.25rem .4rem;background:var(--color-bg,#12121f);border:1px solid var(--color-border,#2a2a3a);color:var(--color-text,#eee);border-radius:6px;font-size:.82rem;text-align:center}
.mp-carrito-footer{display:none;position:sticky;bottom:0;background:var(--color-bg-card,#1e1e2e);border-top:1px solid var(--color-border,#2a2a3a);margin:0 -1.25rem -1rem;padding:.75rem 1.25rem;justify-content:space-between;align-items:center;gap:.75rem;z-index:10}
.mp-carrito-footer--visible{display:flex}
.mp-carrito-info{display:flex;align-items:center;gap:.6rem;font-size:.88rem;color:var(--color-text,#eee)}
.mp-carrito-info i{font-size:1.1rem;color:#f59e0b}
.mp-carrito-info strong{color:#f59e0b;font-size:1rem}
.mp-historial-lista{display:flex;flex-direction:column;gap:.5rem}
.mp-historial-row{display:grid;grid-template-columns:72px 1fr auto;gap:.1rem .75rem;align-items:start;background:var(--color-bg-card,#1e1e2e);border:1px solid var(--color-border,#2a2a3a);border-radius:8px;padding:.7rem .9rem}
.mp-historial-fecha{font-size:.72rem;color:var(--color-text-muted,#888);padding-top:.1rem}
.mp-historial-info{display:flex;flex-direction:column;gap:.1rem}
.mp-historial-info span{font-size:.87rem;font-weight:500;color:var(--color-text,#eee)}
.mp-historial-info small{font-size:.72rem;color:var(--color-text-muted,#888)}
.mp-historial-right{display:flex;flex-direction:column;align-items:flex-end;gap:.25rem}
.mp-rechazo-msg{grid-column:2/-1;font-size:.75rem;color:#ef4444;background:rgba(239,68,68,.07);border-radius:5px;padding:.3rem .55rem;margin-top:.25rem}
.mp-btn-pagar,.mp-btn-agregar{display:inline-flex;align-items:center;gap:.3rem;padding:.3rem .7rem;background:var(--color-primary,#f59e0b);color:#000;border:none;border-radius:6px;font-size:.78rem;font-weight:600;cursor:pointer;white-space:nowrap;transition:opacity .15s}
.mp-btn-pagar:hover,.mp-btn-agregar:hover{opacity:.85}
.mp-btn-quitar{display:inline-flex;align-items:center;padding:.3rem .5rem;background:rgba(239,68,68,.1);color:#ef4444;border:1px solid rgba(239,68,68,.3);border-radius:6px;font-size:.8rem;cursor:pointer}
.mp-btn-secundario{padding:.35rem .8rem;background:transparent;border:1px solid var(--color-border,#3a3a4a);color:var(--color-text,#eee);border-radius:6px;font-size:.78rem;cursor:pointer;white-space:nowrap;flex-shrink:0}
.mp-btn-pagar-carrito{display:inline-flex;align-items:center;gap:.4rem;padding:.5rem 1.1rem;background:var(--color-primary,#f59e0b);color:#000;border:none;border-radius:8px;font-size:.85rem;font-weight:700;cursor:pointer;transition:opacity .15s}
.mp-btn-pagar-carrito:hover{opacity:.85}
.mp-empty,.mp-loading,.mp-error{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:.6rem;padding:2.5rem 1rem;text-align:center;color:var(--color-text-muted,#888);font-size:.85rem}
.mp-empty i{font-size:2.2rem;color:#22c55e}
.mp-error i{font-size:2rem;color:#ef4444}
.mp-error button{display:inline-flex;align-items:center;gap:.35rem;padding:.4rem 1rem;background:transparent;border:1px solid var(--color-border,#3a3a4a);color:var(--color-text,#eee);border-radius:7px;font-size:.82rem;cursor:pointer}
.mp-spinner{width:28px;height:28px;border:3px solid var(--color-border,#2a2a3a);border-top-color:var(--color-primary,#f59e0b);border-radius:50%;animation:mp-spin .7s linear infinite}
@keyframes mp-spin{to{transform:rotate(360deg)}}
@media(max-width:480px){
.mp-resumen-header{grid-template-columns:1fr 1fr}
.mp-resumen-header .mp-pagado{grid-column:1/-1}
[data-pagos-tab] span{display:none}
[data-pagos-tab]{padding:.6rem .7rem}
.mp-deuda-row{flex-wrap:wrap}
.mp-deuda-right{width:100%;justify-content:flex-end}
.mp-historial-row{grid-template-columns:60px 1fr}
.mp-historial-right{grid-column:2;flex-direction:row;align-items:center;flex-wrap:wrap}
.mp-item{flex-wrap:wrap}
.mp-item-acciones{width:100%;justify-content:flex-end}
.mp-cat-pill-label{display:none}
}`;
        document.head.appendChild(s);
    },

    _dispatch(el) {
        const accion = el.dataset.accion;
        const id     = parseInt(el.dataset.id);
        switch (accion) {
            case 'agregar':        this._agregarAlCarrito(id);   break;
            case 'quitar':         this._quitarDelCarrito(id);   break;
            case 'pagar-carrito':  this._pagarCarrito();         break;
            case 'pagar-deuda':    this._pagarDeuda(id);         break;
            case 'fraccionar':     this._abrirFraccionamiento(); break;
        }
    },

    // ─────────────────────────────────────────────────────────
    //  ABRIR / CARGAR
    // ─────────────────────────────────────────────────────────
    async open() {
        const modal = document.getElementById('modal-pagos');
        if (!modal) return;
        if (typeof Modal !== 'undefined') Modal.open('modal-pagos');
        else { modal.showModal?.() || modal.classList.add('open'); }

        if (!this.data) await this._cargarDatos();
    },

    async _cargarDatos() {
        if (this.isLoading) return;
        this.isLoading = true;
        this._mostrarLoading();
        try {
            const res = await fetch('/api/colegiado/mis-pagos');
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            this.data = await res.json();
            this._renderTodo();
            this.switchTab(this.tabActiva);
        } catch (err) {
            console.error('[ModalPagos]', err);
            this._mostrarError();
        } finally {
            this.isLoading = false;
        }
    },

    async refresh() {
        this.data    = null;
        this.carrito = [];
        await this._cargarDatos();
    },

    // ─────────────────────────────────────────────────────────
    //  TABS
    // ─────────────────────────────────────────────────────────
    switchTab(id) {
        this.tabActiva = id;
        document.querySelectorAll('[data-pagos-tab]').forEach(b =>
            b.classList.toggle('active', b.dataset.pagosTab === id)
        );
        document.querySelectorAll('[data-pagos-panel]').forEach(p =>
            p.classList.toggle('active', p.dataset.pagosPanel === id)
        );
    },

    // ─────────────────────────────────────────────────────────
    //  RENDER PRINCIPAL
    // ─────────────────────────────────────────────────────────
    _renderTodo() {
        if (!this.data) return;
        this._renderHeader();
        this._renderDeudas();
        this._renderServicios();
        this._renderHistorial();
    },

    /* ── Header: badge condición + KPIs ── */
    _renderHeader() {
        const { resumen, colegiado } = this.data;

        // Badge condición (habil / inhabil / suspendido)
        const badge = document.getElementById('mp-condicion-badge');
        if (badge && colegiado) {
            const condicion = colegiado.es_habil ? 'habil' : 'inhabil';
            badge.textContent = colegiado.es_habil ? 'Hábil' : 'Inhábil';
            badge.className   = `mp-badge mp-badge--${condicion}`;
        }

        const set = (id, val) => {
            const el = document.getElementById(id);
            if (el) el.textContent = this._fmt(val);
        };
        set('mp-deuda-total',  resumen.deuda_total);
        set('mp-en-revision',  resumen.en_revision);
        set('mp-total-pagado', resumen.total_pagado);
    },

    /* ── TAB DEUDAS ── */
    _renderDeudas() {
        const el = document.getElementById('mp-panel-deudas');
        if (!el) return;
        const { deudas, resumen } = this.data;

        if (!deudas?.length) {
            el.innerHTML = `
                <div class="mp-empty">
                    <i class="ph ph-check-circle"></i>
                    <p>¡Sin deudas pendientes!</p>
                    <small>Estás al día con tus pagos.</small>
                </div>`;
            return;
        }

        const rows = deudas.map(d => `
            <div class="mp-deuda-row">
                <div class="mp-deuda-info">
                    <span class="mp-deuda-concepto">${d.concepto}</span>
                    <span class="mp-deuda-meta">
                        ${d.periodo || ''}
                        ${d.vencimiento ? ' · Vence: ' + this._fmtFecha(d.vencimiento) : ''}
                    </span>
                </div>
                <div class="mp-deuda-right">
                    <div class="mp-monto ${d.status === 'partial' ? 'mp-monto--parcial' : ''}">
                        S/ ${this._fmt(d.balance)}
                        ${d.monto_original && d.monto_original !== d.balance
                            ? `<small>de S/ ${this._fmt(d.monto_original)}</small>` : ''}
                    </div>
                    <button class="mp-btn-pagar" data-accion="pagar-deuda" data-id="${d.id}">
                        <i class="ph ph-credit-card"></i> Pagar
                    </button>
                </div>
            </div>`).join('');

        // ¿Fraccionamiento disponible?
        let fBox = '';
        const deudaTotal = resumen.deuda_total;
        if (deudaTotal >= 500) {
            const inicial = (deudaTotal * 0.20).toFixed(2);
            fBox = `
                <div class="mp-fraccionar-box">
                    <i class="ph ph-calendar-blank"></i>
                    <div>
                        <strong>¿Necesitas fraccionar tu deuda?</strong>
                        <p>Deuda total S/ ${this._fmt(deudaTotal)}.
                           Pago inicial 20% (S/ ${inicial}),
                           desde S/ 100/mes hasta 12 cuotas.</p>
                    </div>
                    <button class="mp-btn-secundario" data-accion="fraccionar">
                        Ver opciones
                    </button>
                </div>`;
        }

        el.innerHTML = `
            <div class="mp-deudas-total">
                <span>Deuda total</span>
                <strong class="mp-monto-danger">S/ ${this._fmt(deudaTotal)}</strong>
            </div>
            <div class="mp-deudas-lista">${rows}</div>
            ${fBox}`;
    },

    /* ── TAB SERVICIOS / CATÁLOGO ── */
    _renderServicios() {
        const el = document.getElementById('mp-panel-servicios');
        if (!el) return;
        const { catalogo, categorias } = this.data;

        if (!catalogo?.length) {
            el.innerHTML = `<div class="mp-empty"><p>Sin servicios disponibles.</p></div>`;
            return;
        }

        // Pills de categoría
        const pills = [
            `<button class="mp-cat-pill ${this.catFiltro === 'todos' ? 'active' : ''}"
                data-cat-filtro="todos">
                <i class="ph ph-squares-four"></i> Todos
                <span class="mp-cat-count">${catalogo.length}</span>
             </button>`,
            ...(categorias || []).map(cat => `
                <button class="mp-cat-pill ${this.catFiltro === cat.key ? 'active' : ''}"
                    data-cat-filtro="${cat.key}"
                    style="--cat-color:${cat.color}">
                    <i class="ph ${cat.icon}"></i>
                    <span class="mp-cat-pill-label">${cat.label}</span>
                    <span class="mp-cat-count">${cat.count}</span>
                </button>`)
        ].join('');

        // Items (filtrados)
        const filtrados = this.catFiltro === 'todos'
            ? catalogo
            : catalogo.filter(c => c.categoria === this.catFiltro);

        // Agrupar por categoría si no hay filtro activo
        let itemsHtml = '';
        if (this.catFiltro === 'todos') {
            const grupos = {};
            filtrados.forEach(item => {
                if (!grupos[item.categoria]) grupos[item.categoria] = [];
                grupos[item.categoria].push(item);
            });
            itemsHtml = Object.entries(grupos).map(([cat, items]) => {
                const meta = (categorias || []).find(c => c.key === cat) || {};
                return `
                    <div class="mp-catalogo-grupo">
                        <div class="mp-grupo-header" style="--cat-color:${meta.color || '#888'}">
                            <i class="ph ${meta.icon || 'ph-circle'}"></i>
                            ${meta.label || cat}
                        </div>
                        ${items.map(i => this._renderItem(i)).join('')}
                    </div>`;
            }).join('');
        } else {
            itemsHtml = `<div class="mp-catalogo-grupo">
                ${filtrados.map(i => this._renderItem(i)).join('')}
            </div>`;
        }

        el.innerHTML = `
            <div class="mp-cat-pills">${pills}</div>
            <div id="mp-catalogo-items">${itemsHtml}</div>
            <div id="mp-carrito-footer" class="mp-carrito-footer ${this.carrito.length ? 'mp-carrito-footer--visible' : ''}">
                ${this._renderCarritoFooter()}
            </div>`;
    },

    _renderItem(item) {
        const enCarrito = this.carrito.find(c => c.id === item.id);
        const agotado   = item.maneja_stock && item.stock_actual <= 0;

        const stockTag  = item.maneja_stock
            ? `<span class="mp-stock ${item.stock_actual > 0 ? 'mp-stock--ok' : 'mp-stock--agotado'}">
                   ${item.stock_actual > 0 ? 'Stock: ' + item.stock_actual : 'Agotado'}
               </span>`
            : '';

        const acciones = agotado
            ? `<span class="mp-tag-agotado">Agotado</span>`
            : enCarrito
                ? `<div class="mp-item-en-carrito">
                       <input type="number" min="1" max="${item.stock_actual || 99}"
                           value="${enCarrito.cantidad}"
                           data-cantidad-id="${item.id}">
                       <button class="mp-btn-quitar" data-accion="quitar" data-id="${item.id}">
                           <i class="ph ph-trash"></i>
                       </button>
                   </div>`
                : `<button class="mp-btn-agregar" data-accion="agregar" data-id="${item.id}">
                       <i class="ph ph-plus"></i> Agregar
                   </button>`;

        return `
            <div class="mp-item" data-item-id="${item.id}">
                <div class="mp-item-info">
                    <span class="mp-item-nombre">${item.nombre}</span>
                    ${item.descripcion ? `<small class="mp-item-desc">${item.descripcion}</small>` : ''}
                    ${stockTag}
                </div>
                <div class="mp-item-acciones">
                    <span class="mp-item-precio">S/ ${this._fmt(item.monto_base)}</span>
                    ${acciones}
                </div>
            </div>`;
    },

    _renderCarritoFooter() {
        const total = this.carrito.reduce((s, c) => s + c.precio * c.cantidad, 0);
        const count = this.carrito.reduce((s, c) => s + c.cantidad, 0);
        return `
            <div class="mp-carrito-info">
                <i class="ph ph-shopping-cart"></i>
                <span>${count} item${count !== 1 ? 's' : ''}</span>
                <strong>S/ ${this._fmt(total)}</strong>
            </div>
            <button class="mp-btn-pagar-carrito" data-accion="pagar-carrito">
                Pagar selección <i class="ph ph-arrow-right"></i>
            </button>`;
    },

    _filtrarCatalogo(cat) {
        this.catFiltro = cat;
        this._renderServicios();
        this.switchTab('servicios');
    },

    /* ── TAB HISTORIAL ── */
    _renderHistorial() {
        const el = document.getElementById('mp-panel-historial');
        if (!el) return;
        const { historial } = this.data;

        if (!historial?.length) {
            el.innerHTML = `<div class="mp-empty"><p>Sin pagos registrados aún.</p></div>`;
            return;
        }

        const rows = historial.map(p => {
            const cfg = this._estadoCfg(p.estado);
            return `
                <div class="mp-historial-row">
                    <div class="mp-historial-fecha">${p.fecha}</div>
                    <div class="mp-historial-info">
                        <span>${p.concepto || 'Pago'}</span>
                        <small>${[p.metodo, p.operacion].filter(Boolean).join(' · ')}</small>
                    </div>
                    <div class="mp-historial-right">
                        <span class="mp-monto-sm">S/ ${this._fmt(p.monto)}</span>
                        <span class="mp-badge mp-badge--${p.estado}">${cfg.label}</span>
                    </div>
                    ${p.estado === 'rejected' && p.rechazo_motivo ? `
                        <div class="mp-rechazo-msg">
                            <i class="ph ph-warning"></i> ${p.rechazo_motivo}
                        </div>` : ''}
                </div>`;
        }).join('');

        el.innerHTML = `<div class="mp-historial-lista">${rows}</div>`;
    },

    // ─────────────────────────────────────────────────────────
    //  CARRITO
    // ─────────────────────────────────────────────────────────
    _agregarAlCarrito(id) {
        const item = this.data?.catalogo?.find(i => i.id === id);
        if (!item || this.carrito.find(c => c.id === id)) return;
        this.carrito.push({
            id,
            nombre: item.nombre,
            precio: item.monto_base,
            cantidad: 1,
        });
        this._renderServicios();
    },

    _quitarDelCarrito(id) {
        this.carrito = this.carrito.filter(c => c.id !== id);
        this._renderServicios();
    },

    _setCantidad(id, qty) {
        const item = this.carrito.find(c => c.id === id);
        if (item) item.cantidad = Math.max(1, qty);
        // Actualizar solo el footer sin re-renderizar todo
        const footer = document.getElementById('mp-carrito-footer');
        if (footer) footer.innerHTML = this._renderCarritoFooter();
    },

    // ─────────────────────────────────────────────────────────
    //  ACCIONES DE PAGO
    // ─────────────────────────────────────────────────────────
    _pagarDeuda(id) {
        const deuda    = this.data?.deudas?.find(d => d.id === id);
        if (!deuda) return;
        const ctx      = this._colegiadoCtx();
        if (typeof AIFab !== 'undefined') {
            AIFab.openPagoFormPrellenado({
                ...ctx,
                concepto: deuda.concepto + (deuda.periodo ? ' ' + deuda.periodo : ''),
                monto_sugerido: deuda.balance,
                debt_id: deuda.id,
            });
        }
        this._cerrar();
    },

    _pagarCarrito() {
        if (!this.carrito.length) return;
        const total   = this.carrito.reduce((s, c) => s + c.precio * c.cantidad, 0);
        const concepto = this.carrito
            .map(c => c.cantidad > 1 ? `${c.cantidad}x ${c.nombre}` : c.nombre)
            .join(', ');
        const ctx     = this._colegiadoCtx();
        if (typeof AIFab !== 'undefined') {
            AIFab.openPagoFormPrellenado({
                ...ctx,
                concepto,
                monto_sugerido: total,
                items_carrito: this.carrito.map(c => ({
                    concepto_id: c.id,
                    nombre: c.nombre,
                    cantidad: c.cantidad,
                    precio: c.precio,
                })),
            });
        }
        this._cerrar();
    },

    _abrirFraccionamiento() {
        if (typeof Toast !== 'undefined') {
            Toast.show(
                'Funcionalidad de fraccionamiento próximamente. Contacta con administración.',
                'info'
            );
        }
    },

    // ─────────────────────────────────────────────────────────
    //  HELPERS
    // ─────────────────────────────────────────────────────────
    _cerrar() {
        const modal = document.getElementById('modal-pagos');
        if (!modal) return;
        if (typeof Modal !== 'undefined') Modal.close('modal-pagos');
        else { modal.close?.() || modal.classList.remove('open', 'active'); }
    },

    _colegiadoCtx() {
        // Prefiere datos del endpoint; fallback a APP_CONFIG
        const col = this.data?.colegiado;
        return {
            id:        col?.id        ?? window.APP_CONFIG?.user?.id       ?? null,
            nombre:    col?.nombre    ?? window.APP_CONFIG?.user?.name     ?? '',
            matricula: col?.matricula ?? window.APP_CONFIG?.user?.matricula ?? '',
            dni:       col?.dni       ?? '',
            deuda:     this.data?.resumen ?? {},
        };
    },

    _fmt(val) {
        return (parseFloat(val) || 0)
            .toLocaleString('es-PE', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    },

    _fmtFecha(iso) {
        if (!iso) return '';
        try {
            const d = new Date(iso);
            return d.toLocaleDateString('es-PE', { day: '2-digit', month: 'short', year: 'numeric' });
        } catch { return iso; }
    },

    _estadoCfg(estado) {
        return {
            approved: { label: 'Aprobado'    },
            review:   { label: 'En revisión' },
            rejected: { label: 'Rechazado'   },
        }[estado] || { label: 'Pendiente' };
    },

    _mostrarLoading() {
        ['mp-panel-deudas', 'mp-panel-servicios', 'mp-panel-historial'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.innerHTML = `
                <div class="mp-loading">
                    <div class="mp-spinner"></div>
                    <span>Cargando...</span>
                </div>`;
        });
    },

    _mostrarError() {
        ['mp-panel-deudas', 'mp-panel-servicios', 'mp-panel-historial'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.innerHTML = `
                <div class="mp-error">
                    <i class="ph ph-warning-circle"></i>
                    <p>No se pudieron cargar los datos.</p>
                    <button data-accion="reintentar" onclick="ModalPagos.refresh()">
                        <i class="ph ph-arrow-clockwise"></i> Reintentar
                    </button>
                </div>`;
        });
    },
};

document.addEventListener('DOMContentLoaded', () => ModalPagos.init());

} // end guard
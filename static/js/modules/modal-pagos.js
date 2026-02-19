/**
 * Modal Mis Pagos — CCPL Dashboard
 * v5 — Tab DEUDAS con selector de cuotas + descuentos por pronto pago
 * GET /api/colegiado/mis-pagos
 */

if (typeof window.ModalPagos === 'undefined') {

window.ModalPagos = {
    data:       null,
    isLoading:  false,
    carrito:    [],
    tabActiva:  'deudas',
    catFiltro:  'todos',
    _abriendo:  false,

    // ── INIT ─────────────────────────────────────────────────
    init() {
        this._injectStyles();
        document.addEventListener('click', e => {
            if (!e.target.closest('#modal-pagos')) return;
            const tab   = e.target.closest('[data-pagos-tab]');
            if (tab)   { this.switchTab(tab.dataset.pagosTab); return; }
            const el    = e.target.closest('[data-accion]');
            if (el)    { this._dispatch(el); return; }
            const pill  = e.target.closest('[data-cat-filtro]');
            if (pill)  { this._filtrarCatalogo(pill.dataset.catFiltro); }
        });
        document.addEventListener('change', e => {
            if (!e.target.closest('#modal-pagos')) return;
            if (e.target.name === 'n_cuotas')   { this._actualizarCalculoCuotas(parseInt(e.target.value)); }
            if (e.target.dataset.cantidadId)    { this._setCantidad(parseInt(e.target.dataset.cantidadId), parseInt(e.target.value)||1); }
        });
    },

    _dispatch(el) {
        const a  = el.dataset.accion;
        const id = parseInt(el.dataset.id);
        if (a === 'pagar-deuda')    this._pagarDeuda(id);
        if (a === 'pagar-cuotas')   this._pagarCuotas();
        if (a === 'agregar')        this._agregarAlCarrito(id);
        if (a === 'quitar')         this._quitarDelCarrito(id);
        if (a === 'pagar-carrito')  this._pagarCarrito();
        if (a === 'fraccionar')     this._abrirFraccionamiento();
    },

    // ── ABRIR ─────────────────────────────────────────────────
    async open(tabInicial, catFiltro) {
        if (this._abriendo) return;
        this._abriendo = true;
        const modal = document.getElementById('modal-pagos');
        if (!modal) { this._abriendo = false; return; }

        if (!document.getElementById('mp-panel-deudas')) {
            this._buildModalHTML(modal);
        }

        if (tabInicial)  this.tabActiva  = tabInicial;
        if (catFiltro)   this.catFiltro  = catFiltro;

        if (typeof Modal !== 'undefined') Modal.open('modal-pagos');
        else modal.classList.add('open', 'active');

        if (!this.data) await this._cargarDatos();
        else { this._renderTodo(); this.switchTab(this.tabActiva); }

        setTimeout(() => { this._abriendo = false; }, 600);
    },

    _buildModalHTML(modal) {
        modal.innerHTML = `
            <div class="modal-header">
                <div style="display:flex;align-items:center;gap:.6rem">
                    <i class="ph ph-credit-card" style="color:var(--color-primary,#f59e0b)"></i>
                    <h3 class="modal-title">Mis Pagos</h3>
                    <span id="mp-condicion-badge" class="mp-badge"></span>
                </div>
                <button class="modal-close" onclick="Modal.close('modal-pagos')">
                    <i class="ph ph-x"></i>
                </button>
            </div>
            <div class="modal-body mp-body">
                <div class="mp-resumen-header">
                    <div class="mp-resumen-item mp-deuda">
                        <label>Deuda pendiente</label>
                        <strong>S/ <span id="mp-deuda-total">—</span></strong>
                    </div>
                    <div class="mp-resumen-item mp-revision">
                        <label>En revisión</label>
                        <strong>S/ <span id="mp-en-revision">—</span></strong>
                    </div>
                    <div class="mp-resumen-item mp-pagado">
                        <label>Pagado (histórico)</label>
                        <strong>S/ <span id="mp-total-pagado">—</span></strong>
                    </div>
                </div>
                <div class="mp-tabs">
                    <button data-pagos-tab="deudas" class="active">
                        <i class="ph ph-receipt"></i><span>Deudas</span>
                    </button>
                    <button data-pagos-tab="servicios">
                        <i class="ph ph-storefront"></i><span>Servicios</span>
                    </button>
                    <button data-pagos-tab="historial">
                        <i class="ph ph-clock-counter-clockwise"></i><span>Historial</span>
                    </button>
                </div>
                <div class="mp-panels">
                    <div data-pagos-panel="deudas" class="active">
                        <div id="mp-panel-deudas"><div class="mp-loading"><div class="mp-spinner"></div><span>Cargando...</span></div></div>
                    </div>
                    <div data-pagos-panel="servicios">
                        <div id="mp-panel-servicios"><div class="mp-loading"><div class="mp-spinner"></div><span>Cargando catálogo...</span></div></div>
                    </div>
                    <div data-pagos-panel="historial">
                        <div id="mp-panel-historial"><div class="mp-loading"><div class="mp-spinner"></div><span>Cargando historial...</span></div></div>
                    </div>
                </div>
            </div>`;
    },

    async _cargarDatos() {
        if (this.isLoading) return;
        this.isLoading = true;
        try {
            const res = await fetch('/api/colegiado/mis-pagos');
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            this.data = await res.json();
            this._renderTodo();
            this.switchTab(this.tabActiva);
        } catch(err) {
            console.error('[ModalPagos]', err);
            this._mostrarError();
        } finally {
            this.isLoading = false;
        }
    },

    async refresh() {
        this.data   = null;
        this.carrito = [];
        const modal = document.getElementById('modal-pagos');
        if (modal) this._buildModalHTML(modal);
        await this._cargarDatos();
    },

    // ── TABS ──────────────────────────────────────────────────
    switchTab(id) {
        this.tabActiva = id;
        document.querySelectorAll('[data-pagos-tab]').forEach(b =>
            b.classList.toggle('active', b.dataset.pagosTab === id));
        document.querySelectorAll('[data-pagos-panel]').forEach(p =>
            p.classList.toggle('active', p.dataset.pagosPanel === id));
    },

    // ── RENDER ────────────────────────────────────────────────
    _renderTodo() {
        if (!this.data) return;
        this._renderHeader();
        this._renderDeudas();
        this._renderServicios();
        this._renderHistorial();
    },

    _renderHeader() {
        const { resumen, colegiado } = this.data;
        const badge = document.getElementById('mp-condicion-badge');
        if (badge && colegiado) {
            const cond    = (colegiado.condicion || '').toLowerCase();
            const esHabil = cond === 'habil' || colegiado.es_habil === true;
            badge.textContent = esHabil ? 'Hábil' : 'Inhábil';
            badge.className   = 'mp-badge mp-badge--' + (esHabil ? 'habil' : 'inhabil');
        }
        const set = (id, val) => { const el = document.getElementById(id); if(el) el.textContent = this._fmt(val); };
        set('mp-deuda-total',  resumen.deuda_total);
        set('mp-en-revision',  resumen.en_revision);
        set('mp-total-pagado', resumen.total_pagado);
    },

    // ── TAB DEUDAS ────────────────────────────────────────────
    _renderDeudas() {
        const el = document.getElementById('mp-panel-deudas');
        if (!el) return;
        const { deudas, resumen } = this.data;
        const cuotas_info = this.data?.colegiado?.cuotas_info;
        let html = '';

        // ── A. Deudas obligatorias (Debt table) ──
        if (deudas && deudas.length > 0) {
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
                        <span class="mp-monto ${d.status==='partial'?'mp-monto--parcial':''}">
                            S/ ${this._fmt(d.balance)}
                            ${d.monto_original && d.monto_original !== d.balance
                                ? `<small>de S/ ${this._fmt(d.monto_original)}</small>` : ''}
                        </span>
                        <button class="mp-btn-pagar" data-accion="pagar-deuda" data-id="${d.id}">
                            <i class="ph ph-credit-card"></i> Pagar
                        </button>
                    </div>
                </div>`).join('');

            html += `
                <div class="mp-seccion-titulo">
                    <i class="ph ph-warning-circle" style="color:#ef4444"></i>
                    Cuotas vencidas
                </div>
                <div class="mp-deudas-lista">${rows}</div>`;

            // Fraccionamiento si deuda total >= 500
            if (resumen.deuda_total >= 500) {
                const ini = (resumen.deuda_total * 0.20).toFixed(2);
                html += `
                    <div class="mp-fraccionar-box">
                        <i class="ph ph-calendar-blank"></i>
                        <div>
                            <strong>¿Necesitas fraccionar tu deuda de S/ ${this._fmt(resumen.deuda_total)}?</strong>
                            <p>Pago inicial 20% (S/ ${ini}) · desde S/ 100/mes · máx. 12 cuotas.</p>
                        </div>
                        <button class="mp-btn-secundario" data-accion="fraccionar">Ver opciones</button>
                    </div>`;
            }
        }

        // ── B. Selector de cuotas del año (hábiles y colegiados al día) ──
        if (cuotas_info) {
            html += this._renderSelectorCuotas(cuotas_info);
        }

        // ── C. Sin nada ──
        if (!deudas?.length && !cuotas_info) {
            html = `<div class="mp-empty">
                <i class="ph ph-check-circle"></i>
                <p>¡Sin deudas pendientes!</p>
                <small>Estás completamente al día.</small>
            </div>`;
        }

        el.innerHTML = html;
    },

    _renderSelectorCuotas(ci) {
        // ci: { mes_pagado_hasta, anio_pagado_hasta, cuotas_pendientes,
        //       monto_cuota, descuento_pct, descuento_valido_hasta, mes_inicio_pago }
        if (ci.cuotas_pendientes <= 0) {
            return `<div class="mp-cuotas-ok">
                <i class="ph ph-calendar-check"></i>
                <p>Tienes todas las cuotas del año pagadas.</p>
            </div>`;
        }

        const MESES = ['','Enero','Febrero','Marzo','Abril','Mayo','Junio',
                       'Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre'];
        const mesPagado  = ci.mes_pagado_hasta  || 0;
        const anio       = ci.anio_pagado_hasta || new Date().getFullYear();
        const pendientes = ci.cuotas_pendientes;
        const montoCuota = ci.monto_cuota || 20;
        const descPct    = ci.descuento_pct || 0;  // 0.20, 0.10 o 0
        const mesInicio  = ci.mes_inicio_pago || (mesPagado + 1);

        const descLabel = descPct > 0
            ? `<span class="mp-badge-descuento">${(descPct*100).toFixed(0)}% Dto. hasta ${ci.descuento_valido_hasta || ''}</span>`
            : '';

        // Generar opciones del select
        let options = '';
        for (let n = 1; n <= pendientes; n++) {
            const mesFin = mesInicio + n - 1;
            options += `<option value="${n}">${n} cuota${n>1?'s':''} — hasta ${MESES[mesFin] || 'Dic'} ${anio}</option>`;
        }

        const montoDefault = (pendientes * montoCuota * (1 - descPct)).toFixed(2);
        const mesPagadoLabel = mesPagado > 0
            ? `${MESES[mesPagado]} ${anio}`
            : 'ninguna aún este año';

        return `
            <div class="mp-cuotas-selector">
                <div class="mp-seccion-titulo" style="margin-top:${document.querySelector('.mp-deudas-lista') ? '1.25rem' : '0'}">
                    <i class="ph ph-calendar"></i>
                    Cuotas del año ${anio}
                    ${descLabel}
                </div>

                <div class="mp-cuotas-info-row">
                    <span>Pagado hasta</span>
                    <strong>${mesPagadoLabel}</strong>
                </div>
                <div class="mp-cuotas-info-row">
                    <span>Cuotas pendientes</span>
                    <strong>${pendientes} de 12</strong>
                </div>
                <div class="mp-cuotas-info-row">
                    <span>Monto por cuota</span>
                    <strong>S/ ${this._fmt(montoCuota)}</strong>
                </div>

                <div class="mp-cuotas-elegir">
                    <label>¿Cuántas cuotas quieres pagar?</label>
                    <select name="n_cuotas" id="mp-n-cuotas">
                        ${options}
                    </select>
                </div>

                <div class="mp-cuotas-resultado" id="mp-cuotas-resultado">
                    ${this._calcularResultadoCuotas(pendientes, montoCuota, descPct, mesInicio, anio)}
                </div>

                <button class="mp-btn-pagar-cuotas" data-accion="pagar-cuotas">
                    <i class="ph ph-credit-card"></i>
                    Pagar S/ <span id="mp-monto-cuotas">${montoDefault}</span>
                </button>
            </div>`;
    },

    _calcularResultadoCuotas(n, monto, descPct, mesInicio, anio) {
        const MESES = ['','Enero','Febrero','Marzo','Abril','Mayo','Junio',
                       'Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre'];
        const montoNormal  = n * monto;
        const descuento    = montoNormal * descPct;
        const montoFinal   = montoNormal - descuento;
        const mesFin       = Math.min(mesInicio + n - 1, 12);
        const quedanDespues = 12 - (mesInicio + n - 1);

        return `
            <div class="mp-calc-row">
                <span>Pagarás de ${MESES[mesInicio]} a ${MESES[mesFin]} ${anio}</span>
            </div>
            ${descPct > 0 ? `
            <div class="mp-calc-row mp-calc-descuento">
                <span>${(descPct*100).toFixed(0)}% descuento aplicado</span>
                <span>- S/ ${this._fmt(descuento)}</span>
            </div>` : ''}
            <div class="mp-calc-row mp-calc-total">
                <span>Total a pagar</span>
                <strong>S/ ${this._fmt(montoFinal)}</strong>
            </div>
            ${quedanDespues > 0 ? `
            <div class="mp-calc-row mp-calc-restante">
                <span>Quedarían ${quedanDespues} cuota${quedanDespues>1?'s':''} pendientes del año</span>
            </div>` : `
            <div class="mp-calc-row mp-calc-completo">
                <i class="ph ph-star"></i> Pagarías todo el año ${anio}
            </div>`}`;
    },

    _actualizarCalculoCuotas(n) {
        const ci = this.data?.colegiado?.cuotas_info;
        if (!ci) return;
        const resultado = document.getElementById('mp-cuotas-resultado');
        const montoEl   = document.getElementById('mp-monto-cuotas');
        if (!resultado || !montoEl) return;

        const monto  = ci.monto_cuota || 20;
        const desc   = ci.descuento_pct || 0;
        const inicio = ci.mes_inicio_pago || ((ci.mes_pagado_hasta||0) + 1);
        const anio   = ci.anio_pagado_hasta || new Date().getFullYear();

        resultado.innerHTML = this._calcularResultadoCuotas(n, monto, desc, inicio, anio);
        montoEl.textContent = ((n * monto * (1 - desc)).toFixed(2)).replace('.', '.');
    },

    // ── TAB SERVICIOS ─────────────────────────────────────────
    _renderServicios() {
        const el = document.getElementById('mp-panel-servicios');
        if (!el) return;
        const { catalogo, categorias } = this.data;
        if (!catalogo?.length) {
            el.innerHTML = `<div class="mp-empty"><i class="ph ph-storefront"></i><p>Sin servicios disponibles por ahora.</p></div>`;
            return;
        }
        const pills = [
            `<button class="mp-cat-pill ${this.catFiltro==='todos'?'active':''}" data-cat-filtro="todos">
                <i class="ph ph-squares-four"></i><span class="mp-cat-pill-label">Todos</span>
                <span class="mp-cat-count">${catalogo.length}</span>
             </button>`,
            ...(categorias||[]).map(cat =>
                `<button class="mp-cat-pill ${this.catFiltro===cat.key?'active':''}"
                    data-cat-filtro="${cat.key}" style="--cat-color:${cat.color}">
                    <i class="ph ${cat.icon}"></i>
                    <span class="mp-cat-pill-label">${cat.label}</span>
                    <span class="mp-cat-count">${cat.count}</span>
                </button>`)
        ].join('');

        const filtrados = this.catFiltro === 'todos'
            ? catalogo : catalogo.filter(c => c.categoria === this.catFiltro);

        let itemsHtml = '';
        if (this.catFiltro === 'todos') {
            const grupos = {};
            filtrados.forEach(i => { (grupos[i.categoria] = grupos[i.categoria]||[]).push(i); });
            itemsHtml = Object.entries(grupos).map(([cat, items]) => {
                const meta = (categorias||[]).find(c=>c.key===cat)||{};
                return `<div class="mp-catalogo-grupo">
                    <div class="mp-grupo-header" style="--cat-color:${meta.color||'#888'}">
                        <i class="ph ${meta.icon||'ph-circle'}"></i>${meta.label||cat}
                    </div>
                    ${items.map(i=>this._renderItem(i)).join('')}
                </div>`;
            }).join('');
        } else {
            itemsHtml = `<div class="mp-catalogo-grupo">${filtrados.map(i=>this._renderItem(i)).join('')}</div>`;
        }
        el.innerHTML = `
            <div class="mp-cat-pills">${pills}</div>
            <div>${itemsHtml}</div>
            <div id="mp-carrito-footer" class="mp-carrito-footer ${this.carrito.length?'mp-carrito-footer--visible':''}">
                ${this._renderCarritoFooter()}
            </div>`;
    },

    _renderItem(item) {
        const enCarrito = this.carrito.find(c => c.id === item.id);
        const agotado   = item.maneja_stock && item.stock_actual <= 0;
        const stock     = item.maneja_stock ? `<span class="mp-stock ${item.stock_actual>0?'mp-stock--ok':'mp-stock--agotado'}">${item.stock_actual>0?'Stock: '+item.stock_actual:'Agotado'}</span>` : '';
        const acciones  = agotado ? `<span class="mp-tag-agotado">Agotado</span>` :
            enCarrito ? `<div class="mp-item-en-carrito">
                <input type="number" min="1" max="${item.stock_actual||99}" value="${enCarrito.cantidad}" data-cantidad-id="${item.id}">
                <button class="mp-btn-quitar" data-accion="quitar" data-id="${item.id}"><i class="ph ph-trash"></i></button>
            </div>` :
            `<button class="mp-btn-agregar" data-accion="agregar" data-id="${item.id}"><i class="ph ph-plus"></i> Agregar</button>`;
        return `<div class="mp-item">
            <div class="mp-item-info">
                <span class="mp-item-nombre">${item.nombre}</span>
                ${item.descripcion?`<small class="mp-item-desc">${item.descripcion}</small>`:''}
                ${stock}
            </div>
            <div class="mp-item-acciones">
                <span class="mp-item-precio">S/ ${this._fmt(item.monto_base)}</span>
                ${acciones}
            </div>
        </div>`;
    },

    _renderCarritoFooter() {
        const total = this.carrito.reduce((s,c)=>s+c.precio*c.cantidad,0);
        const count = this.carrito.reduce((s,c)=>s+c.cantidad,0);
        return `<div class="mp-carrito-info">
            <i class="ph ph-shopping-cart"></i><span>${count} item${count!==1?'s':''}</span>
            <strong>S/ ${this._fmt(total)}</strong>
        </div>
        <button class="mp-btn-pagar-carrito" data-accion="pagar-carrito">
            Pagar selección <i class="ph ph-arrow-right"></i>
        </button>`;
    },

    _filtrarCatalogo(cat) {
        this.catFiltro = cat;
        this._renderServicios();
    },

    // ── TAB HISTORIAL ─────────────────────────────────────────
    _renderHistorial() {
        const el = document.getElementById('mp-panel-historial');
        if (!el) return;
        const { historial } = this.data;
        if (!historial?.length) {
            el.innerHTML = `<div class="mp-empty"><i class="ph ph-clock-counter-clockwise"></i><p>Sin pagos registrados aún.</p></div>`;
            return;
        }
        const cfg = { approved:'Aprobado', review:'En revisión', rejected:'Rechazado' };
        el.innerHTML = `<div class="mp-historial-lista">${historial.map(p=>`
            <div class="mp-historial-row">
                <div class="mp-historial-fecha">${p.fecha}</div>
                <div class="mp-historial-info">
                    <span>${p.concepto||'Pago'}</span>
                    <small>${[p.metodo,p.operacion].filter(Boolean).join(' · ')}</small>
                </div>
                <div class="mp-historial-right">
                    <span class="mp-monto-sm">S/ ${this._fmt(p.monto)}</span>
                    <span class="mp-badge mp-badge--${p.estado}">${cfg[p.estado]||'Pendiente'}</span>
                    ${p.comprobante_url?`<a href="${p.comprobante_url}" target="_blank" class="mp-link-comprobante" title="Ver comprobante"><i class="ph ph-file-pdf"></i></a>`:''}
                </div>
                ${p.estado==='rejected'&&p.rechazo_motivo?`
                <div class="mp-rechazo-msg"><i class="ph ph-warning"></i> ${p.rechazo_motivo}</div>`:''}
            </div>`).join('')}</div>`;
    },

    // ── CARRITO ───────────────────────────────────────────────
    _agregarAlCarrito(id) {
        const item = this.data?.catalogo?.find(i=>i.id===id);
        if (!item || this.carrito.find(c=>c.id===id)) return;
        this.carrito.push({ id, nombre:item.nombre, precio:item.monto_base, cantidad:1 });
        this._renderServicios();
    },
    _quitarDelCarrito(id) {
        this.carrito = this.carrito.filter(c=>c.id!==id);
        this._renderServicios();
    },
    _setCantidad(id, qty) {
        const item = this.carrito.find(c=>c.id===id);
        if (item) item.cantidad = Math.max(1, qty);
        const f = document.getElementById('mp-carrito-footer');
        if (f) f.innerHTML = this._renderCarritoFooter();
    },

    // ── PAGOS ─────────────────────────────────────────────────
    _pagarDeuda(id) {
        const deuda = this.data?.deudas?.find(d=>d.id===id);
        if (!deuda || typeof AIFab==='undefined') return;
        const col = this.data?.colegiado;
        AIFab.openPagoFormPrellenado({
            id: col?.id, nombre: col?.nombre, matricula: col?.matricula, dni: col?.dni,
            deuda: {
                deuda_total: deuda.balance, total: deuda.balance, cantidad_cuotas: 1,
                en_revision: this.data.resumen?.en_revision||0,
                debt_id: deuda.id,
                concepto: deuda.concepto + (deuda.periodo?' '+deuda.periodo:''),
            },
        });
        this._cerrar();
    },

    _pagarCuotas() {
        const ci  = this.data?.colegiado?.cuotas_info;
        if (!ci || typeof AIFab==='undefined') return;
        const col = this.data?.colegiado;
        const sel = document.getElementById('mp-n-cuotas');
        const n   = parseInt(sel?.value) || ci.cuotas_pendientes;
        const monto = parseFloat(document.getElementById('mp-monto-cuotas')?.textContent) || (n * ci.monto_cuota);
        const MESES = ['','Enero','Febrero','Marzo','Abril','Mayo','Junio','Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre'];
        const inicio = ci.mes_inicio_pago || (ci.mes_pagado_hasta+1);
        const fin    = Math.min(inicio+n-1, 12);
        const anio   = ci.anio_pagado_hasta || new Date().getFullYear();
        AIFab.openPagoFormPrellenado({
            id: col?.id, nombre: col?.nombre, matricula: col?.matricula, dni: col?.dni,
            deuda: {
                deuda_total: monto, total: monto, cantidad_cuotas: n,
                en_revision: this.data.resumen?.en_revision||0,
                concepto: `${n} cuota${n>1?'s':''} ordinarias ${MESES[inicio]}-${MESES[fin]} ${anio}`,
                descuento_pct: ci.descuento_pct || 0,
                mes_desde: inicio, mes_hasta: fin, anio,
            },
        });
        this._cerrar();
    },

    _pagarCarrito() {
        if (!this.carrito.length || typeof AIFab==='undefined') return;
        const total   = this.carrito.reduce((s,c)=>s+c.precio*c.cantidad,0);
        const concepto = this.carrito.map(c=>c.cantidad>1?c.cantidad+'x '+c.nombre:c.nombre).join(', ');
        const col = this.data?.colegiado;
        AIFab.openPagoFormPrellenado({
            id: col?.id, nombre: col?.nombre, matricula: col?.matricula, dni: col?.dni,
            deuda: {
                deuda_total: total, total, cantidad_cuotas: this.carrito.length,
                en_revision: this.data?.resumen?.en_revision||0, concepto,
                items: this.carrito.map(c=>({concepto_id:c.id,nombre:c.nombre,cantidad:c.cantidad,precio:c.precio})),
            },
        });
        this._cerrar();
    },

    _abrirFraccionamiento() {
        if (typeof Toast!=='undefined') Toast.show('Funcionalidad de fraccionamiento próximamente. Contacta con administración.','info');
    },

    _cerrar() {
        if (typeof Modal!=='undefined') Modal.close('modal-pagos');
        else { const m=document.getElementById('modal-pagos'); if(m) m.classList.remove('open','active'); }
    },

    // ── ESTADO ────────────────────────────────────────────────
    _mostrarError() {
        ['mp-panel-deudas','mp-panel-servicios','mp-panel-historial'].forEach(id=>{
            const el=document.getElementById(id);
            if(el) el.innerHTML=`<div class="mp-error">
                <i class="ph ph-warning-circle"></i>
                <p>No se pudieron cargar los datos.</p>
                <button onclick="ModalPagos.refresh()"><i class="ph ph-arrow-clockwise"></i> Reintentar</button>
            </div>`;
        });
    },

    // ── UTILS ─────────────────────────────────────────────────
    _fmt(val) {
        return (parseFloat(val)||0).toLocaleString('es-PE',{minimumFractionDigits:2,maximumFractionDigits:2});
    },
    _fmtFecha(iso) {
        try { return new Date(iso).toLocaleDateString('es-PE',{day:'2-digit',month:'short',year:'numeric'}); }
        catch { return iso; }
    },

    // ── CSS INYECTADO ─────────────────────────────────────────
    _injectStyles() {
        if (document.getElementById('mp-styles')) return;
        const s = document.createElement('style');
        s.id = 'mp-styles';
        s.textContent = `
/* LAYOUT */
.mp-body{display:flex;flex-direction:column;padding:1rem 1.25rem 0}
.mp-panels{overflow-y:auto;overflow-x:hidden;min-height:280px;max-height:52vh}
.mp-tabs{display:flex;gap:0;border-bottom:2px solid var(--color-border,#2a2a3a);margin:0;flex-shrink:0}
[data-pagos-tab]{display:flex;align-items:center;gap:.4rem;padding:.65rem 1rem;background:none;border:none;border-bottom:2px solid transparent;margin-bottom:-2px;color:var(--color-text-muted,#999);font-size:.85rem;font-weight:500;cursor:pointer;transition:color .15s,border-color .15s;white-space:nowrap}
[data-pagos-tab]:hover{color:var(--color-text,#eee)}
[data-pagos-tab].active{color:var(--color-primary,#f59e0b);border-bottom-color:var(--color-primary,#f59e0b)}
[data-pagos-panel]{display:none;padding:1rem 0}
[data-pagos-panel].active{display:block}
/* KPIs */
.mp-resumen-header{display:grid;grid-template-columns:repeat(3,1fr);gap:.6rem;margin-bottom:.75rem}
.mp-resumen-item{background:var(--color-bg-card,#1e1e2e);border:1px solid var(--color-border,#2a2a3a);border-radius:8px;padding:.65rem .75rem;text-align:center}
.mp-resumen-item label{display:block;font-size:.68rem;color:var(--color-text-muted,#888);margin-bottom:.2rem;white-space:nowrap}
.mp-resumen-item strong{font-size:1rem;font-weight:700;color:var(--color-text,#eee)}
.mp-resumen-item.mp-deuda strong{color:#ef4444}
.mp-resumen-item.mp-revision strong{color:#f59e0b}
.mp-resumen-item.mp-pagado strong{color:#22c55e}
/* BADGES */
.mp-badge{display:inline-flex;align-items:center;padding:.12rem .5rem;border-radius:999px;font-size:.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.04em}
.mp-badge--habil{background:#dcfce7;color:#166534}
.mp-badge--inhabil{background:#fee2e2;color:#991b1b}
.mp-badge--approved{background:#dcfce7;color:#166534}
.mp-badge--review{background:#fef9c3;color:#854d0e}
.mp-badge--rejected{background:#fee2e2;color:#991b1b}
.mp-badge-descuento{background:rgba(245,158,11,.15);color:#f59e0b;border:1px solid rgba(245,158,11,.3);border-radius:999px;font-size:.7rem;font-weight:700;padding:.1rem .5rem;margin-left:.5rem}
/* SECCIÓN */
.mp-seccion-titulo{display:flex;align-items:center;gap:.5rem;font-size:.75rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--color-text-muted,#888);margin-bottom:.6rem}
/* DEUDAS */
.mp-deudas-lista{display:flex;flex-direction:column;gap:.5rem;margin-bottom:.75rem}
.mp-deuda-row{display:flex;align-items:center;justify-content:space-between;gap:.75rem;background:var(--color-bg-card,#1e1e2e);border:1px solid var(--color-border,#2a2a3a);border-radius:8px;padding:.7rem .9rem}
.mp-deuda-info{display:flex;flex-direction:column;gap:.12rem;flex:1;min-width:0}
.mp-deuda-concepto{font-size:.88rem;font-weight:600;color:var(--color-text,#eee);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mp-deuda-meta{font-size:.72rem;color:var(--color-text-muted,#888)}
.mp-deuda-right{display:flex;align-items:center;gap:.65rem;flex-shrink:0}
.mp-monto{font-size:.92rem;font-weight:700;color:var(--color-text,#eee);display:flex;flex-direction:column;align-items:flex-end}
.mp-monto small{font-size:.68rem;font-weight:400;color:var(--color-text-muted,#888)}
.mp-monto--parcial{color:#f59e0b}
.mp-monto-sm{font-size:.9rem;font-weight:700;color:var(--color-text,#eee)}
.mp-fraccionar-box{display:flex;align-items:flex-start;gap:.75rem;background:rgba(99,102,241,.07);border:1px solid rgba(99,102,241,.25);border-radius:10px;padding:.85rem 1rem;margin:.75rem 0;font-size:.82rem}
.mp-fraccionar-box>i{font-size:1.4rem;color:#818cf8;flex-shrink:0;margin-top:.1rem}
.mp-fraccionar-box strong{display:block;font-size:.84rem;color:var(--color-text,#eee)}
.mp-fraccionar-box p{margin:.15rem 0 0;color:var(--color-text-muted,#999)}
/* SELECTOR CUOTAS */
.mp-cuotas-selector{background:var(--color-bg-card,#1e1e2e);border:1px solid var(--color-border,#2a2a3a);border-radius:10px;padding:1rem}
.mp-cuotas-ok{display:flex;align-items:center;gap:.6rem;padding:.75rem;color:var(--color-success,#22c55e);font-size:.85rem;background:rgba(34,197,94,.07);border-radius:8px;margin-top:.5rem}
.mp-cuotas-info-row{display:flex;justify-content:space-between;align-items:center;font-size:.82rem;padding:.3rem 0;border-bottom:1px solid var(--color-border,#2a2a3a)}
.mp-cuotas-info-row:last-of-type{border-bottom:none}
.mp-cuotas-info-row span{color:var(--color-text-muted,#888)}
.mp-cuotas-info-row strong{color:var(--color-text,#eee)}
.mp-cuotas-elegir{margin:.9rem 0 .5rem}
.mp-cuotas-elegir label{display:block;font-size:.75rem;color:var(--color-text-muted,#888);margin-bottom:.4rem;font-weight:600;text-transform:uppercase;letter-spacing:.05em}
.mp-cuotas-elegir select{width:100%;background:var(--color-bg,#12121f);border:1px solid var(--color-border,#2a2a3a);color:var(--color-text,#eee);border-radius:8px;padding:.5rem .75rem;font-size:.88rem;cursor:pointer}
.mp-cuotas-resultado{background:rgba(0,0,0,.2);border-radius:8px;padding:.65rem .85rem;margin:.5rem 0;font-size:.82rem}
.mp-calc-row{display:flex;justify-content:space-between;align-items:center;padding:.2rem 0;color:var(--color-text-muted,#888)}
.mp-calc-descuento{color:#f59e0b}
.mp-calc-total{color:var(--color-text,#eee);font-size:.92rem;border-top:1px solid var(--color-border,#2a2a3a);margin-top:.3rem;padding-top:.4rem}
.mp-calc-total strong{color:var(--color-primary,#f59e0b);font-size:1.05rem}
.mp-calc-restante{color:var(--color-text-muted,#888);font-size:.75rem}
.mp-calc-completo{color:#22c55e;font-size:.78rem;justify-content:center;gap:.4rem}
.mp-btn-pagar-cuotas{width:100%;display:flex;align-items:center;justify-content:center;gap:.5rem;margin-top:.75rem;padding:.6rem 1rem;background:var(--color-primary,#f59e0b);color:#000;border:none;border-radius:8px;font-size:.9rem;font-weight:700;cursor:pointer;transition:opacity .15s}
.mp-btn-pagar-cuotas:hover{opacity:.85}
/* CATÁLOGO */
.mp-cat-pills{display:flex;gap:.45rem;overflow-x:auto;padding-bottom:.6rem;margin-bottom:.75rem;scrollbar-width:none}
.mp-cat-pills::-webkit-scrollbar{display:none}
.mp-cat-pill{display:inline-flex;align-items:center;gap:.35rem;padding:.3rem .75rem;background:var(--color-bg-card,#1e1e2e);border:1px solid var(--color-border,#2a2a3a);border-radius:999px;color:var(--color-text-muted,#999);font-size:.78rem;font-weight:500;white-space:nowrap;cursor:pointer;transition:all .15s}
.mp-cat-pill.active,.mp-cat-pill:hover{border-color:var(--cat-color,#f59e0b);color:var(--cat-color,#f59e0b)}
.mp-cat-pill.active{background:rgba(245,158,11,.08)}
.mp-cat-count{background:var(--color-border,#2a2a3a);border-radius:999px;padding:0 .35rem;font-size:.68rem;font-weight:700;min-width:16px;text-align:center;color:var(--color-text-muted,#888)}
.mp-catalogo-grupo{margin-bottom:.9rem}
.mp-grupo-header{display:flex;align-items:center;gap:.45rem;font-size:.72rem;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:var(--cat-color,var(--color-text-muted,#888));padding:.3rem 0;border-bottom:1px solid var(--color-border,#2a2a3a);margin-bottom:.5rem}
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
.mp-carrito-footer{display:none;position:sticky;bottom:0;background:var(--color-bg-card,#1e1e2e);border-top:1px solid var(--color-border,#2a2a3a);padding:.75rem;justify-content:space-between;align-items:center;gap:.75rem;z-index:10}
.mp-carrito-footer--visible{display:flex}
.mp-carrito-info{display:flex;align-items:center;gap:.6rem;font-size:.88rem;color:var(--color-text,#eee)}
.mp-carrito-info i{color:#f59e0b;font-size:1.1rem}
.mp-carrito-info strong{color:#f59e0b;font-size:1rem}
/* HISTORIAL */
.mp-historial-lista{display:flex;flex-direction:column;gap:.5rem}
.mp-historial-row{display:grid;grid-template-columns:70px 1fr auto;gap:.1rem .75rem;align-items:start;background:var(--color-bg-card,#1e1e2e);border:1px solid var(--color-border,#2a2a3a);border-radius:8px;padding:.7rem .9rem}
.mp-historial-fecha{font-size:.72rem;color:var(--color-text-muted,#888);padding-top:.1rem}
.mp-historial-info{display:flex;flex-direction:column;gap:.1rem}
.mp-historial-info span{font-size:.87rem;font-weight:500;color:var(--color-text,#eee)}
.mp-historial-info small{font-size:.72rem;color:var(--color-text-muted,#888)}
.mp-historial-right{display:flex;flex-direction:column;align-items:flex-end;gap:.25rem}
.mp-link-comprobante{color:var(--color-primary,#f59e0b);font-size:1rem}
.mp-rechazo-msg{grid-column:2/-1;font-size:.75rem;color:#ef4444;background:rgba(239,68,68,.07);border-radius:5px;padding:.3rem .55rem;margin-top:.25rem}
/* BOTONES */
.mp-btn-pagar,.mp-btn-agregar{display:inline-flex;align-items:center;gap:.3rem;padding:.3rem .7rem;background:var(--color-primary,#f59e0b);color:#000;border:none;border-radius:6px;font-size:.78rem;font-weight:600;cursor:pointer;white-space:nowrap;transition:opacity .15s}
.mp-btn-pagar:hover,.mp-btn-agregar:hover{opacity:.85}
.mp-btn-quitar{display:inline-flex;align-items:center;padding:.3rem .5rem;background:rgba(239,68,68,.1);color:#ef4444;border:1px solid rgba(239,68,68,.3);border-radius:6px;font-size:.8rem;cursor:pointer}
.mp-btn-secundario{padding:.35rem .8rem;background:transparent;border:1px solid var(--color-border,#3a3a4a);color:var(--color-text,#eee);border-radius:6px;font-size:.78rem;cursor:pointer;white-space:nowrap;flex-shrink:0}
.mp-btn-pagar-carrito{display:inline-flex;align-items:center;gap:.4rem;padding:.5rem 1.1rem;background:var(--color-primary,#f59e0b);color:#000;border:none;border-radius:8px;font-size:.85rem;font-weight:700;cursor:pointer;transition:opacity .15s}
.mp-btn-pagar-carrito:hover{opacity:.85}
/* EMPTY / LOADING / ERROR */
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
};

document.addEventListener('DOMContentLoaded', () => ModalPagos.init());

} // end guard
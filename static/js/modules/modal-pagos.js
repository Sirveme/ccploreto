/**
 * Modal Mis Pagos — CCPL Dashboard
 * v8 — Deudas | Futuro | Servicios | Historial + Fraccionamiento + PagoFlowHabil
 * GET /api/colegiado/mis-pagos
 */

if (typeof window.ModalPagos === 'undefined') {

window.ModalPagos = {
    data:       null,
    isLoading:  false,
    carrito:    [],
    tabActiva:  'deudas',
    _abriendo:  false,
    catFiltro:  'todos',

    // Preferencias de sesión (persisten mientras el modal esté abierto)
    prefs: {
        tipoComprobante: null,   // 'boleta' | 'factura' | null
        quiereConstancia: false,
        costoConstancia: 10,     // S/ 10 — se actualiza desde backend
    },

    MESES: ['','Enero','Febrero','Marzo','Abril','Mayo','Junio',
            'Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre'],

    // ── INIT ─────────────────────────────────────────────────
    init() {
        this._injectStyles();
        document.addEventListener('click', e => {
            if (!e.target.closest('#modal-pagos')) return;
            const tab  = e.target.closest('[data-pagos-tab]');
            if (tab)  { this.switchTab(tab.dataset.pagosTab); return; }
            const el   = e.target.closest('[data-accion]');
            if (el)   { this._dispatch(el); return; }
            const pill = e.target.closest('[data-cat-filtro]');
            if (pill) { this.catFiltro = pill.dataset.catFiltro; this._renderServicios(); }
        });
        document.addEventListener('change', e => {
            if (!e.target.closest('#modal-pagos')) return;
            if (e.target.name === 'n_cuotas')         this._actualizarCalculoCuotas(parseInt(e.target.value));
            if (e.target.name === 'tipo_comprobante') this._setComprobante(e.target.value);
            if (e.target.id   === 'mp-constancia')    this._setConstancia(e.target.checked);
            if (e.target.dataset.cantidadId) this._setCantidad(parseInt(e.target.dataset.cantidadId), parseInt(e.target.value)||1);
        });
    },

    _dispatch(el) {
        const a  = el.dataset.accion;
        const id = parseInt(el.dataset.id);
        if (a === 'pagar-deuda')         this._pagarDeuda(id);
        if (a === 'pagar-online-deuda')  this._pagarDeudaOnline(id);
        if (a === 'pagar-cuotas')        this._pagarCuotas();
        if (a === 'pagar-online-cuotas') this._pagarCuotasOnline();
        if (a === 'pagar-fracc-cuota')   this._pagarCuotaFracc(id);
        if (a === 'pagar-online-fracc')  this._pagarCuotaFraccOnline(id);
        if (a === 'agregar')             this._agregarAlCarrito(id);
        if (a === 'quitar')              this._quitarDelCarrito(id);
        if (a === 'pagar-carrito')       this._pagarCarrito();
    },

    // ── ABRIR ─────────────────────────────────────────────────
    async open(tabInicial, _catFiltro) {
        if (this._abriendo) return;
        this._abriendo = true;
        const modal = document.getElementById('modal-pagos');
        if (!modal) { this._abriendo = false; return; }

        if (!document.getElementById('mp-panel-deudas')) {
            this._buildModalHTML(modal);
        }

        if (tabInicial) this.tabActiva = tabInicial;

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

                <!-- Resumen financiero -->
                <div class="mp-resumen-header">
                    <div class="mp-resumen-item mp-deuda">
                        <label>Deuda vencida</label>
                        <strong>S/ <span id="mp-deuda-total">—</span></strong>
                    </div>
                    <div class="mp-resumen-item mp-revision">
                        <label>En revisión</label>
                        <strong>S/ <span id="mp-en-revision">—</span></strong>
                    </div>
                    <div class="mp-resumen-item mp-pagado">
                        <label>Pagado histórico</label>
                        <strong>S/ <span id="mp-total-pagado">—</span></strong>
                    </div>
                </div>

                <!-- Preferencias de pago (opcionales, persisten en sesión) -->
                <div class="mp-prefs" id="mp-prefs">
                    <div class="mp-prefs-titulo">
                        <i class="ph ph-sliders"></i> Preferencias de pago
                        <span class="mp-prefs-hint">— opcional, puedes ver primero</span>
                    </div>
                    <div class="mp-prefs-row">
                        <label class="mp-pref-lbl">Comprobante</label>
                        <div class="mp-radio-group">
                            <label class="mp-radio-opt">
                                <input type="radio" name="tipo_comprobante" value="boleta"
                                       ${this.prefs.tipoComprobante==='boleta'?'checked':''}>
                                <span>Boleta</span>
                            </label>
                            <label class="mp-radio-opt">
                                <input type="radio" name="tipo_comprobante" value="factura"
                                       ${this.prefs.tipoComprobante==='factura'?'checked':''}>
                                <span>Factura</span>
                            </label>
                        </div>
                    </div>
                    <div class="mp-prefs-row">
                        <label class="mp-check-opt" for="mp-constancia">
                            <input type="checkbox" id="mp-constancia"
                                   ${this.prefs.quiereConstancia?'checked':''}>
                            <span>Incluir Constancia de Habilidad <strong style="color:var(--color-primary,#f59e0b)">+ S/ ${this.prefs.costoConstancia}</strong></span>
                        </label>
                    </div>
                </div>

                <!-- Tabs -->
                <div class="mp-tabs">
                    <button data-pagos-tab="deudas" class="active">
                        <i class="ph ph-warning-circle"></i><span>Deudas</span>
                    </button>
                    <button data-pagos-tab="futuro">
                        <i class="ph ph-calendar"></i><span>Futuro</span>
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
                    <div data-pagos-panel="futuro">
                        <div id="mp-panel-futuro"><div class="mp-loading"><div class="mp-spinner"></div><span>Cargando...</span></div></div>
                    </div>
                    <div data-pagos-panel="servicios">
                        <div id="mp-panel-servicios"><div class="mp-loading"><div class="mp-spinner"></div><span>Cargando catálogo...</span></div></div>
                    </div>
                    <div data-pagos-panel="historial">
                        <div id="mp-panel-historial"><div class="mp-loading"><div class="mp-spinner"></div><span>Cargando...</span></div></div>
                    </div>
                </div>
            </div>`;
    },

    async _cargarDatos() {
        if (this.isLoading) return;
        this.isLoading = true;
        try {
            const [resPagos, resFracc] = await Promise.all([
                fetch('/api/colegiado/mis-pagos'),
                fetch('/api/colegiado/mi-fraccionamiento').catch(() => null),
            ]);
            if (!resPagos.ok) throw new Error(`HTTP ${resPagos.status}`);
            this.data = await resPagos.json();
            if (resFracc?.ok) {
                const df = await resFracc.json();
                this.data.fraccionamiento = df.plan || null;
            }
            // Costo constancia desde backend si viene
            if (this.data.costo_constancia) {
                this.prefs.costoConstancia = this.data.costo_constancia;
            }
            try { this._renderTodo(); } catch(e) { console.error('[ModalPagos] renderTodo:', e); }
            this.switchTab(this.tabActiva);
        } catch(err) {
            console.error('[ModalPagos]', err);
            this._mostrarError();
        } finally {
            this.isLoading = false;
        }
    },

    async refresh() {
        this.data    = null;
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

    // ── PREFERENCIAS ──────────────────────────────────────────
    _setComprobante(val) {
        this.prefs.tipoComprobante = val;
    },

    _setConstancia(checked) {
        this.prefs.quiereConstancia = checked;
    },

    _montoConExtras(monto) {
        return monto + (this.prefs.quiereConstancia ? this.prefs.costoConstancia : 0);
    },

    // ── RENDER ────────────────────────────────────────────────
    _renderTodo() {
        if (!this.data) return;
        this._renderHeader();
        this._renderDeudas();
        this._renderFuturo();
        this._renderServicios();
        this._renderHistorial();
    },

    _renderHeader() {
        const { resumen, colegiado } = this.data;
        const badge = document.getElementById('mp-condicion-badge');
        if (badge && colegiado) {
            const esHabil = (colegiado.condicion||'').toLowerCase()==='habil' || colegiado.es_habil;
            badge.textContent = esHabil ? 'Hábil' : 'Inhábil';
            badge.className   = 'mp-badge mp-badge--' + (esHabil ? 'habil' : 'inhabil');
        }
        const set = (id, val) => { const el = document.getElementById(id); if(el) el.textContent = this._fmt(val); };
        set('mp-deuda-total',  resumen.deuda_total);
        set('mp-en-revision',  resumen.en_revision);
        set('mp-total-pagado', resumen.total_pagado);
    },

    // ── TAB DEUDAS (vencidas) ─────────────────────────────────
    _renderDeudas() {
        const el = document.getElementById('mp-panel-deudas');
        if (!el) return;

        const deudas = this.data.deudas || [];
        const fracc  = this.data.fraccionamiento;

        // Cuotas de fraccionamiento VENCIDAS
        const cuotasVencidas = fracc?.cuotas?.filter(c =>
            !c.pagada && c.vencida
        ) || [];

        let html = '';

        // Deudas ordinarias vencidas
        if (deudas.length) {
            html += `
                <div class="mp-seccion-titulo">
                    <i class="ph ph-warning-circle" style="color:#ef4444"></i>
                    Obligaciones vencidas
                </div>
                <div class="mp-deudas-lista">
                    ${deudas.map(d => this._renderDeudaRow(d)).join('')}
                </div>`;
        }

        // Cuotas fraccionamiento vencidas
        if (cuotasVencidas.length) {
            html += `
                <div class="mp-seccion-titulo" style="margin-top:1rem">
                    <i class="ph ph-calendar-x" style="color:#f59e0b"></i>
                    Cuotas de fraccionamiento vencidas
                    <span class="mp-fracc-badge">FRACC-${fracc.numero_solicitud?.split('-').pop()}</span>
                </div>
                <div class="mp-deudas-lista">
                    ${cuotasVencidas.map(c => this._renderCuotaFraccRow(c, true)).join('')}
                </div>`;
        }

        if (!deudas.length && !cuotasVencidas.length) {
            html = `<div class="mp-empty">
                <i class="ph ph-check-circle"></i>
                <p>¡Sin obligaciones vencidas!</p>
                <small>Estás completamente al día.</small>
            </div>`;
        }

        el.innerHTML = html;
    },

    _renderDeudaRow(d) {
        return `
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
                        <i class="ph ph-upload"></i> Reportar
                    </button>
                    <button class="mp-btn-pagar-online" data-accion="pagar-online-deuda" data-id="${d.id}">
                        <i class="ph ph-credit-card"></i> En línea
                    </button>
                </div>
            </div>`;
    },

    _renderCuotaFraccRow(c, esVencida = false) {
        const colorBorde = esVencida ? 'border-color:rgba(245,158,11,.3)' : '';
        return `
            <div class="mp-deuda-row" style="${colorBorde}">
                <div class="mp-deuda-info">
                    <span class="mp-deuda-concepto">Cuota ${c.numero} de fraccionamiento</span>
                    <span class="mp-deuda-meta">
                        Vence: ${this._fmtFecha(c.fecha_vencimiento)}
                        ${c.habilidad_hasta ? ' · Habilita hasta: ' + this._fmtFecha(c.habilidad_hasta) : ''}
                    </span>
                </div>
                <div class="mp-deuda-right">
                    <span class="mp-monto">S/ ${this._fmt(c.monto)}</span>
                    <button class="mp-btn-pagar" data-accion="pagar-fracc-cuota" data-id="${c.numero}">
                        <i class="ph ph-upload"></i> Reportar
                    </button>
                    <button class="mp-btn-pagar-online" data-accion="pagar-online-fracc" data-id="${c.numero}">
                        <i class="ph ph-credit-card"></i> En línea
                    </button>
                </div>
            </div>`;
    },

    // ── TAB FUTURO ────────────────────────────────────────────
    _renderFuturo() {
        const el = document.getElementById('mp-panel-futuro');
        if (!el) return;

        const ci   = this.data?.colegiado?.cuotas_info;
        const fracc = this.data.fraccionamiento;
        const hoy   = new Date();
        const mes   = hoy.getMonth() + 1;

        // Descuento por pronto pago
        const descPct = mes === 1 ? 0.30 : mes === 2 ? 0.20 : mes === 3 ? 0.10 : 0;

        let html = '';

        // Banner de descuento
        if (descPct > 0) {
            const label = {1:'30%',2:'20%',3:'10%'}[mes];
            const hasta = {1:'31 enero',2:'28 febrero',3:'31 marzo'}[mes];
            html += `
                <div class="mp-descuento-banner">
                    <div>
                        <strong>🎉 ${label} de descuento por pago adelantado</strong>
                        <p>Válido hasta el ${hasta} — paga cuotas ordinarias del año con descuento</p>
                    </div>
                    <span class="mp-badge-descuento">${label}</span>
                </div>`;
        }

        // Cuotas ordinarias futuras
        if (ci && ci.cuotas_pendientes > 0) {
            html += this._renderSelectorCuotas(ci, descPct);
        } else if (ci && ci.cuotas_pendientes <= 0) {
            html += `<div class="mp-cuotas-ok">
                <i class="ph ph-calendar-check"></i>
                <p>Cuotas ordinarias del año pagadas. ¡Felicitaciones!</p>
            </div>`;
        }

        // Cuotas de fraccionamiento PRÓXIMAS (no vencidas)
        const proximas = fracc?.cuotas?.filter(c => !c.pagada && !c.vencida) || [];
        if (proximas.length) {
            const cuotaProx = proximas[0];
            html += `
                <div class="mp-seccion-titulo" style="margin-top:1.25rem">
                    <i class="ph ph-calendar-blank" style="color:#818cf8"></i>
                    Plan de fraccionamiento — ${fracc.numero_solicitud}
                </div>
                <div class="mp-fracc-resumen">
                    <div class="mp-fracc-stat">
                        <span>Cuotas pagadas</span>
                        <strong>${fracc.cuotas_pagadas} / ${fracc.num_cuotas}</strong>
                    </div>
                    <div class="mp-fracc-stat">
                        <span>Saldo pendiente</span>
                        <strong style="color:#f59e0b">S/ ${this._fmt(fracc.saldo_pendiente)}</strong>
                    </div>
                    <div class="mp-fracc-stat">
                        <span>Fin estimado</span>
                        <strong>${this._fmtFecha(fracc.fecha_fin_estimada)}</strong>
                    </div>
                </div>
                <div class="mp-seccion-titulo" style="margin-top:.75rem;font-size:.7rem">
                    Próximas cuotas
                    <span style="margin-left:auto;font-size:.68rem;color:var(--color-text-muted,#888);text-transform:none;letter-spacing:0">
                        Paga de a 1 o por adelantado
                    </span>
                </div>
                <div class="mp-deudas-lista">
                    ${proximas.map(c => this._renderCuotaFraccRow(c, false)).join('')}
                </div>
                <div class="mp-fracc-pagar-varias">
                    <label>Pagar varias cuotas de una vez:</label>
                    <div style="display:flex;gap:.5rem;align-items:center;margin-top:.4rem">
                        <select id="mp-fracc-n-cuotas" style="flex:1;background:var(--color-bg,#12121f);
                            border:1px solid var(--color-border,#2a2a3a);color:var(--color-text,#eee);
                            border-radius:8px;padding:.45rem .75rem;font-size:.85rem">
                            ${proximas.map((_,i) => `<option value="${i+1}">${i+1} cuota${i>0?'s':''} — S/ ${this._fmt((i+1)*fracc.monto_cuota)}</option>`).join('')}
                        </select>
                        <button class="mp-btn-pagar" onclick="ModalPagos._pagarVariasCuotasFracc()"
                                style="padding:.45rem .9rem">
                            <i class="ph ph-upload"></i> Reportar
                        </button>
                        <button class="mp-btn-pagar-online" onclick="ModalPagos._pagarVariasCuotasFraccOnline()"
                                style="padding:.45rem .9rem">
                            <i class="ph ph-credit-card"></i> En línea
                        </button>
                    </div>
                </div>`;
        }

        if (!ci && !fracc) {
            html = `<div class="mp-empty">
                <i class="ph ph-calendar"></i>
                <p>Sin obligaciones futuras registradas.</p>
            </div>`;
        }

        el.innerHTML = html;
    },

    _renderSelectorCuotas(ci, descPct) {
        const pendientes = ci.cuotas_pendientes;
        const montoCuota = ci.monto_cuota || 20;
        const mesInicio  = ci.mes_inicio_pago || ((ci.mes_pagado_hasta||0) + 1);
        const anio       = ci.anio_pagado_hasta || new Date().getFullYear();
        const mesPagado  = ci.mes_pagado_hasta || 0;

        const descLabel = descPct > 0
            ? `<span class="mp-badge-descuento">${(descPct*100).toFixed(0)}% Dto.</span>`
            : '';

        let options = '';
        for (let n = 1; n <= pendientes; n++) {
            const mesFin = mesInicio + n - 1;
            options += `<option value="${n}">${n} cuota${n>1?'s':''} — hasta ${this.MESES[mesFin] || 'Dic'} ${anio}</option>`;
        }

        const montoDefault = (pendientes * montoCuota * (1 - descPct)).toFixed(2);
        const mesPagadoLabel = mesPagado > 0
            ? `${this.MESES[mesPagado]} ${anio}` : 'ninguna aún este año';

        return `
            <div class="mp-seccion-titulo">
                <i class="ph ph-calendar"></i>
                Cuotas ordinarias ${anio}
                ${descLabel}
            </div>
            <div class="mp-cuotas-selector">
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
                    <select name="n_cuotas" id="mp-n-cuotas">${options}</select>
                </div>
                <div class="mp-cuotas-resultado" id="mp-cuotas-resultado">
                    ${this._calcularResultadoCuotas(pendientes, montoCuota, descPct, mesInicio, anio)}
                </div>
                <button class="mp-btn-pagar-cuotas" data-accion="pagar-cuotas">
                    <i class="ph ph-buildings"></i> Reportar pago
                </button>
                <button class="mp-btn-pagar-cuotas mp-btn-pagar-cuotas-online"
                        data-accion="pagar-online-cuotas"
                        style="background:#3b82f6;color:#fff;margin-top:.4rem">
                    <i class="ph ph-credit-card"></i> Pagar en línea — OpenPay
                </button>
            </div>`;
    },

    _calcularResultadoCuotas(n, monto, descPct, mesInicio, anio) {
        const montoNormal  = n * monto;
        const descuento    = montoNormal * descPct;
        const montoFinal   = montoNormal - descuento;
        const montoConExtra = this._montoConExtras(montoFinal);
        const mesFin       = Math.min(mesInicio + n - 1, 12);
        const quedan       = 12 - (mesInicio + n - 1);

        return `
            <div class="mp-calc-row">
                <span>Pagarás de ${this.MESES[mesInicio]} a ${this.MESES[mesFin]} ${anio}</span>
            </div>
            ${descPct > 0 ? `
            <div class="mp-calc-row mp-calc-descuento">
                <span>${(descPct*100).toFixed(0)}% descuento aplicado</span>
                <span>- S/ ${this._fmt(descuento)}</span>
            </div>` : ''}
            ${this.prefs.quiereConstancia ? `
            <div class="mp-calc-row" style="color:#a78bfa">
                <span>Constancia de Habilidad</span>
                <span>+ S/ ${this._fmt(this.prefs.costoConstancia)}</span>
            </div>` : ''}
            <div class="mp-calc-row mp-calc-total">
                <span>Total a pagar</span>
                <strong>S/ ${this._fmt(montoConExtra)}</strong>
            </div>
            ${quedan > 0 ? `
            <div class="mp-calc-row mp-calc-restante">
                <span>Quedarían ${quedan} cuota${quedan>1?'s':''} pendientes</span>
            </div>` : `
            <div class="mp-calc-row mp-calc-completo">
                <i class="ph ph-star"></i> ¡Pagarías todo el año ${anio}!
            </div>`}`;
    },

    _actualizarCalculoCuotas(n) {
        const ci = this.data?.colegiado?.cuotas_info;
        if (!ci) return;
        const hoy    = new Date();
        const mes    = hoy.getMonth() + 1;
        const descPct = mes===1?0.30:mes===2?0.20:mes===3?0.10:0;
        const inicio  = ci.mes_inicio_pago || ((ci.mes_pagado_hasta||0)+1);
        const anio    = ci.anio_pagado_hasta || hoy.getFullYear();
        const resultado = document.getElementById('mp-cuotas-resultado');
        const montoEl   = document.getElementById('mp-monto-cuotas');
        if (resultado) resultado.innerHTML = this._calcularResultadoCuotas(n, ci.monto_cuota||20, descPct, inicio, anio);
        if (montoEl) {
            const base = n * (ci.monto_cuota||20) * (1-descPct);
            montoEl.textContent = this._montoConExtras(base).toFixed(2);
        }
    },

    // ── TAB HISTORIAL ─────────────────────────────────────────
    _renderHistorial() {
        const el = document.getElementById('mp-panel-historial');
        if (!el) return;
        const historial = this.data.historial || this.data.pagos;
        if (!historial?.length) {
            el.innerHTML = `<div class="mp-empty"><i class="ph ph-clock-counter-clockwise"></i><p>Sin pagos registrados aún.</p></div>`;
            return;
        }
        const cfg = { approved:'Aprobado', review:'En revisión', rejected:'Rechazado' };
        el.innerHTML = `<div class="mp-historial-lista">${historial.map(p=>`
            <div class="mp-historial-row">
                <div class="mp-historial-fecha">${p.fecha}</div>
                <div class="mp-historial-info">
                    <span>${this._parseConcepto(p.concepto)}</span>
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

    // ── PAGOS ─────────────────────────────────────────────────
    _extraInfo() {
        return {
            tipo_comprobante: this.prefs.tipoComprobante,
            con_constancia:   this.prefs.quiereConstancia,
        };
    },

    _pagarDeuda(id) {
        const deuda = this.data?.deudas?.find(d=>d.id===id);
        if (!deuda) return;
        if (typeof PagoFlowHabil === 'undefined') return;
        Modal.close('modal-pagos');
        PagoFlowHabil.iniciar({
            deudaId:  deuda.id,
            deudaIds: [deuda.id],
            monto:    this._montoConExtras(deuda.balance),
            concepto: deuda.concepto + (deuda.periodo ? ' · ' + deuda.periodo : ''),
            ...this._extraInfo(),
        });
    },

    _pagarDeudaOnline(id) {
        const deuda = this.data?.deudas?.find(d=>d.id===id);
        if (!deuda) return;
        if (typeof PagoFlowHabil !== 'undefined') {
            Modal.close('modal-pagos');
            PagoFlowHabil.iniciarOnline({
                deudaIds: [id],
                monto:    this._montoConExtras(deuda.balance),
                concepto: deuda.concepto + (deuda.periodo ? ' · ' + deuda.periodo : ''),
                ...this._extraInfo(),
            });
        } else {
            this._iniciarPagoOpenpay([id], this._montoConExtras(deuda.balance));
        }
    },

    _pagarCuotas() {
        const ci  = this.data?.colegiado?.cuotas_info;
        if (!ci || typeof PagoFlowHabil==='undefined') return;
        const sel = document.getElementById('mp-n-cuotas');
        const n   = parseInt(sel?.value) || ci.cuotas_pendientes;
        const hoy = new Date(); const mes = hoy.getMonth()+1;
        const descPct = mes===1?0.30:mes===2?0.20:mes===3?0.10:0;
        const inicio  = ci.mes_inicio_pago||((ci.mes_pagado_hasta||0)+1);
        const fin     = Math.min(inicio+n-1,12);
        const anio    = ci.anio_pagado_hasta||hoy.getFullYear();
        const base    = n * ci.monto_cuota * (1-descPct);
        const monto   = this._montoConExtras(base);
        const concepto = `${n} cuota${n>1?'s':''} ordinarias ${this.MESES[inicio]}-${this.MESES[fin]} ${anio}`;
        this._cerrar();
        PagoFlowHabil.iniciar({ deudaIds:[], monto, concepto });
    },

    _pagarCuotasOnline() {
        const ci  = this.data?.colegiado?.cuotas_info;
        if (!ci || typeof PagoFlowHabil==='undefined') return;
        const sel   = document.getElementById('mp-n-cuotas');
        const n     = parseInt(sel?.value) || ci.cuotas_pendientes;
        const hoy   = new Date(); const mes = hoy.getMonth()+1;
        const descPct = mes===1?0.30:mes===2?0.20:mes===3?0.10:0;
        const inicio  = ci.mes_inicio_pago||((ci.mes_pagado_hasta||0)+1);
        const fin     = Math.min(inicio+n-1,12);
        const anio    = ci.anio_pagado_hasta||hoy.getFullYear();
        const base    = n * ci.monto_cuota * (1-descPct);
        const monto   = this._montoConExtras(base);
        const concepto = `${n} cuota${n>1?'s':''} ordinarias ${this.MESES[inicio]}-${this.MESES[fin]} ${anio}`;
        this._cerrar();
        PagoFlowHabil.iniciarOnline({ deudaIds:[], monto, concepto });
    },

    _pagarCuotaFracc(numeroCuota) {
        const fracc = this.data?.fraccionamiento;
        if (!fracc || typeof PagoFlowHabil==='undefined') return;
        const cuota = fracc.cuotas?.find(c=>c.numero===numeroCuota);
        if (!cuota) return;
        const monto   = this._montoConExtras(cuota.monto);
        const concepto = `Cuota ${numeroCuota} fraccionamiento ${fracc.numero_solicitud}`;
        this._cerrar();
        PagoFlowHabil.iniciar({ deudaIds:[], monto, concepto });
    },

    _pagarCuotaFraccOnline(numeroCuota) {
        const fracc = this.data?.fraccionamiento;
        if (!fracc || typeof PagoFlowHabil==='undefined') return;
        const cuota = fracc.cuotas?.find(c=>c.numero===numeroCuota);
        if (!cuota) return;
        const monto   = this._montoConExtras(cuota.monto);
        const concepto = `Cuota ${numeroCuota} fraccionamiento ${fracc.numero_solicitud}`;
        this._cerrar();
        PagoFlowHabil.iniciarOnline({ deudaIds:[], monto, concepto });
    },

    async _iniciarPagoOpenpay(deudaIds, monto, extra={}) {
        this._cerrar();
        if (typeof Toast!=='undefined') Toast.show('Conectando con pasarela de pago...','info');

        const overlay = document.createElement('div');
        overlay.id = 'openpay-overlay';
        overlay.style.cssText = `position:fixed;inset:0;background:rgba(0,0,0,.75);
            display:flex;flex-direction:column;align-items:center;justify-content:center;
            gap:16px;z-index:9999`;
        overlay.innerHTML = `
            <div style="width:48px;height:48px;border:4px solid #334155;
                border-top-color:#3b82f6;border-radius:50%;
                animation:openpay-spin .8s linear infinite"></div>
            <div style="color:#f1f5f9;font-size:15px;font-weight:600">Preparando pago seguro...</div>
            <div style="color:#64748b;font-size:13px">S/ ${parseFloat(monto).toFixed(2)}</div>
            <style>@keyframes openpay-spin{to{transform:rotate(360deg)}}</style>`;
        document.body.appendChild(overlay);

        try {
            const body = new FormData();
            body.append('deuda_ids', deudaIds.join(','));
            if (deudaIds.length===0 && extra.tipo) {
                body.append('tipo_pago', extra.tipo);
                body.append('cantidad_cuotas', extra.cantidad||1);
                if (extra.fraccionamiento_id) {
                    body.append('fraccionamiento_id', extra.fraccionamiento_id);
                    body.append('numero_cuota', extra.numero_cuota);
                }
            }
            if (this.prefs.tipoComprobante) body.append('tipo_comprobante', this.prefs.tipoComprobante);
            if (this.prefs.quiereConstancia) body.append('con_constancia', '1');

            const resp = await fetch('/pagos/openpay/iniciar', {
                method:'POST', headers:{'HX-Request':'true'}, body,
            });
            const hxRedirect = resp.headers.get('HX-Redirect');
            if (hxRedirect) { window.location.href = hxRedirect; return; }
            const html = await resp.text();
            if (html.includes('alerta-error') || !resp.ok) {
                overlay.remove();
                if (typeof Toast!=='undefined') Toast.show('No se pudo conectar con la pasarela. Intenta nuevamente.','error');
                return;
            }
            if (resp.redirected) { window.location.href = resp.url; return; }
            overlay.remove();
        } catch(err) {
            overlay.remove();
            if (typeof Toast!=='undefined') Toast.show('Error de conexión. Verifica tu internet.','error');
        }
    },


    // ── TAB SERVICIOS ─────────────────────────────────────────
    _renderServicios() {
        const el = document.getElementById('mp-panel-servicios');
        if (!el) return;
        const { catalogo, categorias } = this.data;
        if (!catalogo?.length) {
            el.innerHTML = `<div class="mp-empty"><i class="ph ph-storefront"></i><p>Sin servicios disponibles.</p></div>`;
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
        const filtrados = this.catFiltro==='todos' ? catalogo : catalogo.filter(c=>c.categoria===this.catFiltro);
        let itemsHtml = '';
        if (this.catFiltro==='todos') {
            const grupos = {};
            filtrados.forEach(i => { (grupos[i.categoria]=grupos[i.categoria]||[]).push(i); });
            itemsHtml = Object.entries(grupos).map(([cat,items]) => {
                const meta=(categorias||[]).find(c=>c.key===cat)||{};
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
        const enCarrito = this.carrito.find(c=>c.id===item.id);
        const agotado   = item.maneja_stock && item.stock_actual<=0;
        const stock     = item.maneja_stock
            ? `<span class="mp-stock ${item.stock_actual>0?'mp-stock--ok':'mp-stock--agotado'}">${item.stock_actual>0?'Stock: '+item.stock_actual:'Agotado'}</span>`
            : '';
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

    _agregarAlCarrito(id) {
        const item = this.data?.catalogo?.find(i=>i.id===id);
        if (!item || this.carrito.find(c=>c.id===id)) return;
        this.carrito.push({id, nombre:item.nombre, precio:item.monto_base, cantidad:1});
        this._renderServicios();
    },

    _quitarDelCarrito(id) {
        this.carrito = this.carrito.filter(c=>c.id!==id);
        this._renderServicios();
    },

    _setCantidad(id, qty) {
        const item = this.carrito.find(c=>c.id===id);
        if (item) item.cantidad = Math.max(1,qty);
        const f = document.getElementById('mp-carrito-footer');
        if (f) f.innerHTML = this._renderCarritoFooter();
    },

    _pagarCarrito() {
        if (!this.carrito.length || typeof PagoFlowHabil==='undefined') return;
        const total   = this.carrito.reduce((s,c)=>s+c.precio*c.cantidad,0);
        const concepto = this.carrito.map(c=>c.cantidad>1?c.cantidad+'x '+c.nombre:c.nombre).join(', ');
        this._cerrar();
        PagoFlowHabil.iniciar({ deudaIds:[], monto:total, concepto });
    },


    _pagarVariasCuotasFracc() {
        const fracc = this.data?.fraccionamiento;
        if (!fracc || typeof PagoFlowHabil==='undefined') return;
        const sel = document.getElementById('mp-fracc-n-cuotas');
        const n   = parseInt(sel?.value) || 1;
        const proximas = fracc.cuotas?.filter(c => !c.pagada && !c.vencida) || [];
        const cuotasPagar = proximas.slice(0, n);
        const base    = cuotasPagar.reduce((s,c) => s + c.monto, 0);
        const monto   = this._montoConExtras(base);
        const concepto = `${n} cuota${n>1?'s':''} fraccionamiento ${fracc.numero_solicitud}`;
        this._cerrar();
        PagoFlowHabil.iniciar({ deudaIds:[], monto, concepto });
    },

    _pagarVariasCuotasFraccOnline() {
        const fracc = this.data?.fraccionamiento;
        if (!fracc || typeof PagoFlowHabil==='undefined') return;
        const sel = document.getElementById('mp-fracc-n-cuotas');
        const n   = parseInt(sel?.value) || 1;
        const proximas = fracc.cuotas?.filter(c => !c.pagada && !c.vencida) || [];
        const cuotasPagar = proximas.slice(0, n);
        const base    = cuotasPagar.reduce((s,c) => s + c.monto, 0);
        const monto   = this._montoConExtras(base);
        const concepto = `${n} cuota${n>1?'s':''} fraccionamiento ${fracc.numero_solicitud}`;
        this._cerrar();
        PagoFlowHabil.iniciarOnline({ deudaIds:[], monto, concepto });
    },

    _cerrar() {
        if (typeof Modal!=='undefined') Modal.close('modal-pagos');
        else { const m=document.getElementById('modal-pagos'); if(m) m.classList.remove('open','active'); }
    },

    _mostrarError() {
        ['mp-panel-deudas','mp-panel-futuro','mp-panel-historial'].forEach(id=>{
            const el=document.getElementById(id);
            if(el) el.innerHTML=`<div class="mp-error">
                <i class="ph ph-warning-circle"></i>
                <p>No se pudo cargar la información.</p>
                <button onclick="ModalPagos.refresh()"><i class="ph ph-arrow-clockwise"></i> Reintentar</button>
            </div>`;
        });
    },

    // ── HELPERS ───────────────────────────────────────────────
    _parseConcepto(concepto) {
        if (!concepto) return 'Pago';
        try {
            const o = JSON.parse(concepto);
            return o.conceptos || o.concepto || o.descripcion || concepto;
        } catch { return concepto; }
    },

    _fmt(n) {
        const v = parseFloat(n)||0;
        return v.toLocaleString('es-PE', {minimumFractionDigits:2, maximumFractionDigits:2});
    },

    _fmtFecha(iso) {
        if (!iso) return '';
        // Handle date-only "2023-10-28", datetime with tz, etc.
        let d;
        if (typeof iso === 'string' && iso.length === 10) {
            // "YYYY-MM-DD" — parse as local noon to avoid timezone shift
            const [y,m,day] = iso.split('-').map(Number);
            d = new Date(y, m-1, day, 12, 0, 0);
        } else {
            d = new Date(iso);
        }
        if (isNaN(d.getTime())) return iso; // fallback: show raw
        return d.toLocaleDateString('es-PE', {day:'numeric', month:'short', year:'numeric'});
    },

    // ── ESTILOS ───────────────────────────────────────────────
    _injectStyles() {
        if (document.getElementById('mp-styles')) return;
        const s = document.createElement('style');
        s.id = 'mp-styles';
        s.textContent = `
/* ── BASE ── */
.mp-body{display:flex;flex-direction:column;gap:0;padding:0 1rem 1rem;overflow-x:hidden}
/* RESUMEN */
.mp-resumen-header{display:grid;grid-template-columns:repeat(3,1fr);gap:.5rem;padding:.75rem 0;border-bottom:1px solid var(--color-border,#2a2a3a);margin-bottom:.75rem}
.mp-resumen-item{display:flex;flex-direction:column;gap:.15rem}
.mp-resumen-item label{font-size:.68rem;font-weight:600;text-transform:uppercase;letter-spacing:.05em;color:var(--color-text-muted,#888)}
.mp-resumen-item strong{font-size:1rem;font-weight:700}
.mp-resumen-item.mp-deuda strong{color:#ef4444}
.mp-resumen-item.mp-revision strong{color:#f59e0b}
.mp-resumen-item.mp-pagado strong{color:#22c55e}
/* PREFS */
.mp-prefs{background:rgba(99,102,241,.06);border:1px solid rgba(99,102,241,.15);border-radius:10px;padding:.75rem .9rem;margin-bottom:.75rem}
.mp-prefs-titulo{font-size:.72rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:#818cf8;margin-bottom:.6rem;display:flex;align-items:center;gap:.4rem}
.mp-prefs-hint{font-weight:400;text-transform:none;letter-spacing:0;color:var(--color-text-muted,#888)}
.mp-prefs-row{display:flex;align-items:center;gap:.75rem;margin-bottom:.4rem}
.mp-prefs-row:last-child{margin-bottom:0}
.mp-pref-lbl{font-size:.75rem;color:var(--color-text-muted,#888);min-width:80px}
.mp-radio-group{display:flex;gap:.5rem}
.mp-radio-opt{display:flex;align-items:center;gap:.3rem;cursor:pointer;font-size:.82rem;color:var(--color-text,#eee)}
.mp-check-opt{display:flex;align-items:center;gap:.4rem;cursor:pointer;font-size:.82rem;color:var(--color-text,#eee)}
/* BADGES */
.mp-badge{display:inline-flex;align-items:center;padding:.12rem .5rem;border-radius:999px;font-size:.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.04em}
.mp-badge--habil{background:#dcfce7;color:#166534}
.mp-badge--inhabil{background:#fee2e2;color:#991b1b}
.mp-badge--approved{background:#dcfce7;color:#166534}
.mp-badge--review{background:#fef9c3;color:#854d0e}
.mp-badge--rejected{background:#fee2e2;color:#991b1b}
.mp-badge-descuento{background:rgba(245,158,11,.15);color:#f59e0b;border:1px solid rgba(245,158,11,.3);border-radius:999px;font-size:.7rem;font-weight:700;padding:.1rem .5rem;margin-left:.5rem;flex-shrink:0}
.mp-fracc-badge{background:rgba(129,140,248,.15);color:#818cf8;border:1px solid rgba(129,140,248,.25);border-radius:999px;font-size:.65rem;font-weight:700;padding:.1rem .45rem;margin-left:.4rem}
/* TABS */
.mp-tabs{display:flex;gap:0;border-bottom:1px solid var(--color-border,#2a2a3a);margin-bottom:.75rem}
[data-pagos-tab]{display:inline-flex;align-items:center;gap:.35rem;padding:.6rem .9rem;background:none;border:none;border-bottom:2px solid transparent;color:var(--color-text-muted,#888);font-size:.82rem;font-weight:600;cursor:pointer;white-space:nowrap;transition:all .15s}
[data-pagos-tab]:hover{color:var(--color-text,#eee)}
[data-pagos-tab].active{color:var(--color-primary,#f59e0b);border-bottom-color:var(--color-primary,#f59e0b)}
[data-pagos-panel]{display:none}
[data-pagos-panel].active{display:block}
/* SECCIONES */
.mp-seccion-titulo{display:flex;align-items:center;gap:.5rem;font-size:.75rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--color-text-muted,#888);margin-bottom:.6rem}
/* DESCUENTO BANNER */
.mp-descuento-banner{display:flex;align-items:center;justify-content:space-between;gap:.75rem;background:rgba(245,158,11,.08);border:1px solid rgba(245,158,11,.2);border-radius:10px;padding:.85rem 1rem;margin-bottom:1rem;font-size:.82rem}
.mp-descuento-banner strong{display:block;font-size:.88rem;color:var(--color-text,#eee)}
.mp-descuento-banner p{margin:.15rem 0 0;color:var(--color-text-muted,#999)}
/* DEUDAS */
.mp-deudas-lista{display:flex;flex-direction:column;gap:.5rem;margin-bottom:.75rem}
.mp-deuda-row{display:flex;align-items:center;justify-content:space-between;gap:.75rem;background:var(--color-bg-card,#1e1e2e);border:1px solid var(--color-border,#2a2a3a);border-radius:8px;padding:.7rem .9rem}
.mp-deuda-info{display:flex;flex-direction:column;gap:.12rem;flex:1;min-width:0}
.mp-deuda-concepto{font-size:.88rem;font-weight:600;color:var(--color-text,#eee);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mp-deuda-meta{font-size:.72rem;color:var(--color-text-muted,#888)}
.mp-deuda-right{display:flex;align-items:center;gap:.5rem;flex-shrink:0;flex-wrap:wrap;justify-content:flex-end}
.mp-monto{font-size:.92rem;font-weight:700;color:var(--color-text,#eee);display:flex;flex-direction:column;align-items:flex-end}
.mp-monto small{font-size:.68rem;font-weight:400;color:var(--color-text-muted,#888)}
.mp-monto--parcial{color:#f59e0b}
.mp-monto-sm{font-size:.9rem;font-weight:700;color:var(--color-text,#eee)}
/* FRACCIONAMIENTO */
.mp-fracc-resumen{display:grid;grid-template-columns:repeat(3,1fr);gap:.5rem;background:rgba(129,140,248,.06);border:1px solid rgba(129,140,248,.15);border-radius:10px;padding:.75rem;margin-bottom:.75rem}
.mp-fracc-stat{display:flex;flex-direction:column;gap:.1rem}
.mp-fracc-stat span{font-size:.68rem;color:var(--color-text-muted,#888);text-transform:uppercase;letter-spacing:.04em}
.mp-fracc-stat strong{font-size:.9rem;font-weight:700;color:var(--color-text,#eee)}
.mp-fracc-mas{font-size:.75rem;color:var(--color-text-muted,#888);text-align:center;padding:.5rem;font-style:italic}
/* CUOTAS SELECTOR */
.mp-cuotas-selector{background:var(--color-bg-card,#1e1e2e);border:1px solid var(--color-border,#2a2a3a);border-radius:10px;padding:1rem;margin-bottom:.75rem}
.mp-cuotas-ok{display:flex;align-items:center;gap:.6rem;padding:.75rem;color:var(--color-success,#22c55e);font-size:.85rem;background:rgba(34,197,94,.07);border-radius:8px;margin-bottom:.75rem}
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
/* BOTONES */
.mp-btn-pagar,.mp-btn-agregar{display:inline-flex;align-items:center;gap:.3rem;padding:.3rem .65rem;background:var(--color-primary,#f59e0b);color:#000;border:none;border-radius:6px;font-size:.75rem;font-weight:600;cursor:pointer;white-space:nowrap;transition:opacity .15s}
.mp-btn-pagar:hover{opacity:.85}
.mp-btn-pagar-online{display:inline-flex;align-items:center;gap:.3rem;padding:.3rem .65rem;background:#3b82f6;color:#fff;border:none;border-radius:6px;font-size:.75rem;font-weight:600;cursor:pointer;white-space:nowrap;transition:opacity .15s}
.mp-btn-pagar-online:hover{opacity:.85}
.mp-btn-pagar-cuotas{width:100%;display:flex;align-items:center;justify-content:center;gap:.5rem;margin-top:.75rem;padding:.6rem 1rem;background:var(--color-primary,#f59e0b);color:#000;border:none;border-radius:8px;font-size:.9rem;font-weight:700;cursor:pointer;transition:opacity .15s}
.mp-btn-pagar-cuotas:hover{opacity:.85}
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
/* EMPTY/LOADING/ERROR */
.mp-empty,.mp-loading,.mp-error{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:.6rem;padding:2.5rem 1rem;text-align:center;color:var(--color-text-muted,#888);font-size:.85rem}
.mp-empty i{font-size:2.2rem;color:#22c55e}
.mp-error i{font-size:2rem;color:#ef4444}
.mp-error button{display:inline-flex;align-items:center;gap:.35rem;padding:.4rem 1rem;background:transparent;border:1px solid var(--color-border,#3a3a4a);color:var(--color-text,#eee);border-radius:7px;font-size:.82rem;cursor:pointer}
.mp-spinner{width:28px;height:28px;border:3px solid var(--color-border,#2a2a3a);border-top-color:var(--color-primary,#f59e0b);border-radius:50%;animation:mp-spin .7s linear infinite}
@keyframes mp-spin{to{transform:rotate(360deg)}}
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
.mp-btn-quitar{display:inline-flex;align-items:center;padding:.3rem .5rem;background:rgba(239,68,68,.1);color:#ef4444;border:1px solid rgba(239,68,68,.3);border-radius:6px;font-size:.8rem;cursor:pointer}
.mp-btn-pagar-carrito{display:inline-flex;align-items:center;gap:.4rem;padding:.5rem 1.1rem;background:var(--color-primary,#f59e0b);color:#000;border:none;border-radius:8px;font-size:.85rem;font-weight:700;cursor:pointer;transition:opacity .15s}
.mp-btn-pagar-carrito:hover{opacity:.85}
.mp-cat-pill-label{display:inline}
.mp-fracc-pagar-varias{background:rgba(129,140,248,.06);border:1px solid rgba(129,140,248,.15);
border-radius:10px;padding:.75rem;margin-top:.5rem}
.mp-fracc-pagar-varias label{font-size:.75rem;font-weight:600;color:var(--color-text-muted,#888);
text-transform:uppercase;letter-spacing:.05em}
@media(max-width:480px){
.mp-resumen-header{grid-template-columns:1fr 1fr}
.mp-resumen-header .mp-pagado{grid-column:1/-1}
[data-pagos-tab] span{display:none}
[data-pagos-tab]{padding:.6rem .7rem}
.mp-deuda-row{flex-wrap:wrap}
.mp-deuda-right{width:100%;justify-content:flex-end}
.mp-fracc-resumen{grid-template-columns:1fr 1fr}
.mp-historial-row{grid-template-columns:60px 1fr}
.mp-historial-right{grid-column:2;flex-direction:row;align-items:center;flex-wrap:wrap}
}`;
        document.head.appendChild(s);
    },
};

document.addEventListener('DOMContentLoaded', () => ModalPagos.init());

} // end guard
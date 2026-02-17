/**
 * Modal Pagos v2 — Dashboard Colegiado
 * Tabs: Deudas | Servicios (Catálogo) | Historial
 * Con sistema de carrito y checkout integrado.
 */

if (typeof window.ModalPagos === 'undefined') {

window.ModalPagos = {
    data: null,
    isLoading: false,
    activeTab: 'deudas',

    // Carrito unificado: deudas seleccionadas + servicios agregados
    cart: {
        deudas: [],      // [{ id, concepto, balance }]
        servicios: [],   // [{ id, codigo, nombre, monto, cantidad }]
    },

    // Categoría activa en el catálogo
    catFilter: 'todos',

    /* ==========================================
       INICIALIZACIÓN
       ========================================== */

    init() {
        this.bindTabs();
    },

    bindTabs() {
        document.querySelectorAll('#modal-pagos .pagos-tab').forEach(tab => {
            tab.addEventListener('click', (e) => {
                const tabId = e.currentTarget.dataset.tab;
                this.switchTab(tabId);
            });
        });
    },

    switchTab(tabId) {
        this.activeTab = tabId;
        document.querySelectorAll('#modal-pagos .pagos-tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('#modal-pagos .pagos-tab-content').forEach(c => c.classList.remove('active'));

        const tab = document.querySelector(`#modal-pagos .pagos-tab[data-tab="${tabId}"]`);
        const content = document.getElementById(`pagos-${tabId}`);
        if (tab) tab.classList.add('active');
        if (content) content.classList.add('active');

        this.updateFooter();
    },

    /* ==========================================
       ABRIR MODAL + CARGAR DATOS
       ========================================== */

    async open(options = {}) {
        Modal.open('modal-pagos');

        if (!this.data) {
            await this.cargarDatos();
        }

        // Si viene con concepto preseleccionado (ej: desde botón Constancia)
        if (options.concepto_preseleccionado) {
            this.switchTab('servicios');
            setTimeout(() => this.preseleccionarServicio(options.concepto_preseleccionado), 100);
        }
    },

    async cargarDatos() {
        if (this.isLoading) return;
        this.isLoading = true;
        this.mostrarLoading();

        try {
            const res = await fetch('/api/colegiado/mis-pagos');
            if (!res.ok) throw new Error(`HTTP ${res.status}`);

            this.data = await res.json();
            this.renderAll();
        } catch (err) {
            console.error('[ModalPagos] Error:', err);
            this.mostrarError('No se pudieron cargar los datos.');
        } finally {
            this.isLoading = false;
        }
    },

    mostrarLoading() {
        ['pagos-deudas', 'pagos-servicios', 'pagos-historial'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.innerHTML = `<div class="pagos-skeleton">
                <div class="skeleton-item"></div><div class="skeleton-item"></div><div class="skeleton-item"></div>
            </div>`;
        });
    },

    mostrarError(msg) {
        const el = document.getElementById('pagos-deudas');
        if (el) el.innerHTML = `<div class="pagos-empty">
            <i class="ph ph-warning-circle"></i>
            <p>${msg}</p>
            <button onclick="ModalPagos.refresh()" style="margin-top:12px;padding:8px 16px;border-radius:8px;border:1px solid rgba(255,255,255,0.2);background:transparent;color:#94a3b8;cursor:pointer;">
                <i class="ph ph-arrow-clockwise"></i> Reintentar
            </button>
        </div>`;
    },

    renderAll() {
        this.renderDeudas();
        this.renderCatalogo();
        this.renderHistorial();
        this.updateBadges();
        this.updateFooter();
    },

    /* ==========================================
       TAB: DEUDAS
       ========================================== */

    renderDeudas() {
        const container = document.getElementById('pagos-deudas');
        if (!container || !this.data) return;

        const { resumen, deudas } = this.data;

        // Resumen cards
        let html = `
            <div class="cuenta-resumen">
                <div class="cuenta-card deuda">
                    <div class="cuenta-label">Deuda</div>
                    <div class="cuenta-valor">S/ ${this.fmt(resumen.deuda_total)}</div>
                </div>
                <div class="cuenta-card pagado">
                    <div class="cuenta-label">Pagado</div>
                    <div class="cuenta-valor">S/ ${this.fmt(resumen.total_pagado)}</div>
                </div>
                <div class="cuenta-card pendiente">
                    <div class="cuenta-label">Revisión</div>
                    <div class="cuenta-valor">S/ ${this.fmt(resumen.en_revision)}</div>
                </div>
            </div>
        `;

        if (!deudas || deudas.length === 0) {
            html += `<div class="pagos-info-box">
                <i class="ph ph-check-circle"></i>
                <p>¡Estás al día! No tienes deudas pendientes.</p>
            </div>`;
            container.innerHTML = html;
            return;
        }

        // Header con select all
        html += `
            <div class="deudas-section-title">
                <span>${deudas.length} cuota${deudas.length > 1 ? 's' : ''} pendiente${deudas.length > 1 ? 's' : ''}</span>
                <button class="deudas-select-all" onclick="ModalPagos.toggleSelectAll()">
                    ${this.cart.deudas.length === deudas.length ? 'Deseleccionar' : 'Seleccionar todo'}
                </button>
            </div>
        `;

        // Lista de deudas con checkbox
        deudas.forEach(d => {
            const isSelected = this.cart.deudas.some(cd => cd.id === d.id);
            const vencClass = this.getVencimientoClass(d.vencimiento);
            const vencText = this.getVencimientoText(d.vencimiento);

            html += `
                <div class="deuda-check-item ${isSelected ? 'selected' : ''} ${vencClass}"
                     onclick="ModalPagos.toggleDeuda(${d.id})">
                    <div class="deuda-checkbox">
                        ${isSelected ? '<i class="ph ph-check-bold"></i>' : ''}
                    </div>
                    <div class="deuda-check-info">
                        <div class="deuda-check-concepto">${d.concepto}</div>
                        <div class="deuda-check-meta">
                            ${d.periodo ? `<span>${d.periodo}</span>` : ''}
                            ${vencText ? `<span class="${vencClass}">${vencText}</span>` : ''}
                        </div>
                    </div>
                    <div class="deuda-check-monto">S/ ${this.fmt(d.balance)}</div>
                </div>
            `;
        });

        container.innerHTML = html;
    },

    toggleDeuda(deudaId) {
        const idx = this.cart.deudas.findIndex(d => d.id === deudaId);
        if (idx >= 0) {
            this.cart.deudas.splice(idx, 1);
        } else {
            const deuda = this.data.deudas.find(d => d.id === deudaId);
            if (deuda) {
                this.cart.deudas.push({
                    id: deuda.id,
                    concepto: deuda.concepto_corto || deuda.concepto,
                    balance: deuda.balance,
                    tipo: 'deuda'
                });
            }
        }
        this.renderDeudas();
        this.updateFooter();
    },

    toggleSelectAll() {
        if (!this.data) return;
        if (this.cart.deudas.length === this.data.deudas.length) {
            this.cart.deudas = [];
        } else {
            this.cart.deudas = this.data.deudas.map(d => ({
                id: d.id,
                concepto: d.concepto_corto || d.concepto,
                balance: d.balance,
                tipo: 'deuda'
            }));
        }
        this.renderDeudas();
        this.updateFooter();
    },

    /* ==========================================
       TAB: CATÁLOGO DE SERVICIOS
       ========================================== */

    renderCatalogo() {
        const container = document.getElementById('pagos-servicios');
        if (!container || !this.data) return;

        const { catalogo, categorias } = this.data;
        if (!catalogo || catalogo.length === 0) {
            container.innerHTML = `<div class="pagos-empty">
                <i class="ph ph-storefront"></i>
                <p>No hay servicios disponibles</p>
            </div>`;
            return;
        }

        // Filter pills
        let html = `<div class="cat-filters">
            <button class="cat-pill ${this.catFilter === 'todos' ? 'active' : ''}"
                    onclick="ModalPagos.filterCat('todos')">
                <i class="ph ph-squares-four"></i> Todos
                <span class="pill-count">${catalogo.length}</span>
            </button>`;

        (categorias || []).forEach(cat => {
            html += `
                <button class="cat-pill ${this.catFilter === cat.key ? 'active' : ''}"
                        onclick="ModalPagos.filterCat('${cat.key}')">
                    <i class="ph ${cat.icon}"></i>
                    ${cat.label}
                    <span class="pill-count">${cat.count}</span>
                </button>`;
        });
        html += `</div>`;

        // Filtered items
        const items = this.catFilter === 'todos'
            ? catalogo
            : catalogo.filter(c => c.categoria === this.catFilter);

        // Group by category if showing all
        if (this.catFilter === 'todos') {
            const groups = {};
            items.forEach(item => {
                if (!groups[item.categoria]) groups[item.categoria] = [];
                groups[item.categoria].push(item);
            });

            Object.entries(groups).forEach(([cat, catItems]) => {
                const meta = (categorias || []).find(c => c.key === cat);
                html += `
                    <div class="cat-section-header">
                        <i class="ph ${meta?.icon || 'ph-circle'}" style="color:${meta?.color || '#64748b'}"></i>
                        ${meta?.label || cat}
                    </div>
                    <div class="cat-grid">
                        ${catItems.map(item => this.renderCatItem(item)).join('')}
                    </div>
                `;
            });
        } else {
            html += `<div class="cat-grid">
                ${items.map(item => this.renderCatItem(item)).join('')}
            </div>`;
        }

        container.innerHTML = html;
    },

    renderCatItem(item) {
        const inCart = this.cart.servicios.find(s => s.id === item.id);
        const cantidad = inCart ? inCart.cantidad : 0;
        const isOutOfStock = item.maneja_stock && item.stock_actual <= 0;

        let priceHtml;
        if (item.monto_base > 0) {
            priceHtml = `<div class="cat-item-price">S/ ${this.fmt(item.monto_base)}</div>`;
        } else if (item.permite_monto_libre) {
            priceHtml = `<div class="cat-item-price libre">Monto libre</div>`;
        } else {
            priceHtml = `<div class="cat-item-price libre">Consultar</div>`;
        }

        let stockHtml = '';
        if (item.maneja_stock) {
            if (item.stock_actual <= 0) {
                stockHtml = `<div class="cat-item-stock out">Agotado</div>`;
            } else if (item.stock_actual <= 3) {
                stockHtml = `<div class="cat-item-stock low">Quedan ${item.stock_actual}</div>`;
            }
        }

        const onclick = isOutOfStock
            ? ''
            : `onclick="ModalPagos.addServicio(${item.id})"`;

        return `
            <div class="cat-item ${cantidad > 0 ? 'in-cart' : ''}" ${onclick}
                 style="${isOutOfStock ? 'opacity:0.4;cursor:not-allowed;' : ''}">
                ${cantidad > 0 ? `<div class="cat-item-cart-badge">${cantidad}</div>` : ''}
                <div class="cat-item-icon" style="background:${item.categoria_color}15;color:${item.categoria_color}">
                    <i class="ph ${item.categoria_icon}"></i>
                </div>
                <div class="cat-item-name">${item.nombre_corto || item.nombre}</div>
                ${priceHtml}
                ${stockHtml}
            </div>
        `;
    },

    filterCat(cat) {
        this.catFilter = cat;
        this.renderCatalogo();
    },

    addServicio(itemId) {
        const item = this.data.catalogo.find(c => c.id === itemId);
        if (!item) return;

        // Si requiere monto libre, pedir monto
        if (item.permite_monto_libre && item.monto_base === 0) {
            this.pedirMontoLibre(item);
            return;
        }

        const existing = this.cart.servicios.find(s => s.id === itemId);
        if (existing) {
            existing.cantidad++;
            existing.monto = item.monto_base * existing.cantidad;
        } else {
            this.cart.servicios.push({
                id: item.id,
                codigo: item.codigo,
                nombre: item.nombre_corto || item.nombre,
                monto_unitario: item.monto_base,
                monto: item.monto_base,
                cantidad: 1,
                tipo: 'servicio'
            });
        }

        this.renderCatalogo();
        this.updateFooter();
    },

    removeServicio(itemId) {
        const idx = this.cart.servicios.findIndex(s => s.id === itemId);
        if (idx >= 0) {
            this.cart.servicios.splice(idx, 1);
            this.renderCatalogo();
            this.updateFooter();
        }
    },

    removeDeudaFromCart(deudaId) {
        const idx = this.cart.deudas.findIndex(d => d.id === deudaId);
        if (idx >= 0) {
            this.cart.deudas.splice(idx, 1);
            this.renderDeudas();
            this.updateFooter();
        }
    },

    pedirMontoLibre(item) {
        // Create overlay
        const overlay = document.createElement('div');
        overlay.className = 'monto-libre-overlay';
        overlay.id = 'monto-libre-overlay';

        const minText = item.monto_minimo > 0 ? `Mínimo: S/ ${this.fmt(item.monto_minimo)}` : '';
        const maxText = item.monto_maximo > 0 ? `Máximo: S/ ${this.fmt(item.monto_maximo)}` : '';
        const rangeText = [minText, maxText].filter(Boolean).join(' · ') || 'Ingresa el monto';

        overlay.innerHTML = `
            <div class="monto-libre-card">
                <h4>${item.nombre_corto || item.nombre}</h4>
                <div class="monto-sub">${rangeText}</div>
                <input type="number" id="input-monto-libre" placeholder="0.00"
                       min="${item.monto_minimo || 0}" ${item.monto_maximo > 0 ? `max="${item.monto_maximo}"` : ''}
                       step="0.01" inputmode="decimal" autofocus>
                <div class="monto-libre-actions">
                    <button class="btn-cancel" onclick="ModalPagos.cerrarMontoLibre()">Cancelar</button>
                    <button class="btn-confirm" onclick="ModalPagos.confirmarMontoLibre(${item.id})">
                        <i class="ph ph-plus"></i> Agregar
                    </button>
                </div>
            </div>
        `;

        document.body.appendChild(overlay);
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) this.cerrarMontoLibre();
        });

        setTimeout(() => document.getElementById('input-monto-libre')?.focus(), 100);
    },

    confirmarMontoLibre(itemId) {
        const input = document.getElementById('input-monto-libre');
        const monto = parseFloat(input?.value);

        if (!monto || monto <= 0) {
            input?.focus();
            return;
        }

        const item = this.data.catalogo.find(c => c.id === itemId);
        if (!item) return;

        if (item.monto_minimo > 0 && monto < item.monto_minimo) {
            if (typeof Toast !== 'undefined') Toast.show(`Monto mínimo: S/ ${this.fmt(item.monto_minimo)}`, 'warning');
            return;
        }
        if (item.monto_maximo > 0 && monto > item.monto_maximo) {
            if (typeof Toast !== 'undefined') Toast.show(`Monto máximo: S/ ${this.fmt(item.monto_maximo)}`, 'warning');
            return;
        }

        this.cart.servicios.push({
            id: item.id,
            codigo: item.codigo,
            nombre: item.nombre_corto || item.nombre,
            monto_unitario: monto,
            monto: monto,
            cantidad: 1,
            tipo: 'servicio'
        });

        this.cerrarMontoLibre();
        this.renderCatalogo();
        this.updateFooter();
    },

    cerrarMontoLibre() {
        const overlay = document.getElementById('monto-libre-overlay');
        if (overlay) overlay.remove();
    },

    preseleccionarServicio(codigo) {
        if (!this.data) return;
        const item = this.data.catalogo.find(c => c.codigo === codigo);
        if (item) {
            this.addServicio(item.id);
        }
    },

    /* ==========================================
       TAB: HISTORIAL
       ========================================== */

    renderHistorial() {
        const container = document.getElementById('pagos-historial');
        if (!container || !this.data) return;

        const { historial } = this.data;

        if (!historial || historial.length === 0) {
            container.innerHTML = `<div class="pagos-empty">
                <i class="ph ph-receipt"></i>
                <p>No tienes pagos registrados</p>
            </div>`;
            return;
        }

        const estadoTexto = { approved: 'Aprobado', review: 'En revisión', rejected: 'Rechazado' };
        const metodoIcono = { Yape: 'ph-device-mobile', Plin: 'ph-device-mobile', Transferencia: 'ph-bank', Efectivo: 'ph-money' };

        container.innerHTML = `<div class="pagos-lista">
            ${historial.map(p => `
                <div class="pago-item">
                    <div class="pago-info">
                        <span class="pago-fecha">${p.fecha}</span>
                        <span class="pago-concepto">${p.concepto || 'Pago'}</span>
                        <span class="pago-metodo">
                            <i class="ph ${metodoIcono[p.metodo] || 'ph-credit-card'}"></i>
                            ${p.metodo || ''} ${p.operacion ? '· ' + p.operacion : ''}
                        </span>
                    </div>
                    <div class="pago-monto-estado">
                        <span class="pago-monto">S/ ${this.fmt(p.monto)}</span>
                        <span class="pago-estado ${p.estado}">${estadoTexto[p.estado] || p.estado}</span>
                    </div>
                </div>
            `).join('')}
        </div>`;
    },

    /* ==========================================
       FOOTER: CARRITO + BOTÓN PAGAR
       ========================================== */

    updateFooter() {
        const footer = document.getElementById('pagos-footer');
        if (!footer) return;

        const totalDeudas = this.cart.deudas.reduce((sum, d) => sum + d.balance, 0);
        const totalServicios = this.cart.servicios.reduce((sum, s) => sum + s.monto, 0);
        const total = totalDeudas + totalServicios;
        const itemCount = this.cart.deudas.length + this.cart.servicios.length;

        if (itemCount === 0) {
            footer.classList.remove('visible');
            return;
        }

        footer.classList.add('visible');

        // Cart chips
        let chipsHtml = '';
        this.cart.deudas.forEach(d => {
            chipsHtml += `<div class="cart-chip">
                ${d.concepto} · S/${this.fmt(d.balance)}
                <button class="chip-remove" onclick="event.stopPropagation();ModalPagos.removeDeudaFromCart(${d.id})">
                    <i class="ph ph-x-bold"></i>
                </button>
            </div>`;
        });
        this.cart.servicios.forEach(s => {
            chipsHtml += `<div class="cart-chip">
                ${s.nombre}${s.cantidad > 1 ? ' x' + s.cantidad : ''} · S/${this.fmt(s.monto)}
                <button class="chip-remove" onclick="event.stopPropagation();ModalPagos.removeServicio(${s.id})">
                    <i class="ph ph-x-bold"></i>
                </button>
            </div>`;
        });

        footer.innerHTML = `
            <div class="pagos-footer-cart">${chipsHtml}</div>
            <div class="pagos-footer-summary">
                <div class="pagos-footer-items">
                    <strong>${itemCount}</strong> item${itemCount > 1 ? 's' : ''}
                </div>
                <div class="pagos-footer-total">
                    <small>Total </small>S/ ${this.fmt(total)}
                </div>
            </div>
            <button class="btn-pagar-footer" onclick="ModalPagos.checkout()">
                <i class="ph ph-credit-card"></i>
                Pagar S/ ${this.fmt(total)}
            </button>
        `;
    },

    updateBadges() {
        if (!this.data) return;
        // Badge de deudas pendientes
        const tabDeudas = document.querySelector('.pagos-tab[data-tab="deudas"]');
        if (tabDeudas && this.data.deudas?.length > 0) {
            // Remove existing badge
            const existing = tabDeudas.querySelector('.tab-badge');
            if (existing) existing.remove();
            const badge = document.createElement('span');
            badge.className = 'tab-badge';
            badge.textContent = this.data.deudas.length;
            tabDeudas.appendChild(badge);
        }
    },

    /* ==========================================
       CHECKOUT — Integración con formulario de pago
       ========================================== */

    checkout() {
        const totalDeudas = this.cart.deudas.reduce((sum, d) => sum + d.balance, 0);
        const totalServicios = this.cart.servicios.reduce((sum, s) => sum + s.monto, 0);
        const total = totalDeudas + totalServicios;

        if (total <= 0) return;

        // Cerrar modal-pagos
        Modal.close('modal-pagos');

        // Preparar resumen para el formulario de pago
        const items = [
            ...this.cart.deudas.map(d => ({
                tipo: 'deuda',
                id: d.id,
                concepto: d.concepto,
                monto: d.balance
            })),
            ...this.cart.servicios.map(s => ({
                tipo: 'servicio',
                id: s.id,
                codigo: s.codigo,
                concepto: s.nombre,
                monto: s.monto,
                cantidad: s.cantidad
            }))
        ];

        // Intentar usar AIFab (formulario de pago existente)
        if (typeof AIFab !== 'undefined' && AIFab.openPagoFormPrellenado) {
            AIFab.openPagoFormPrellenado({
                id: this.data.colegiado.id,
                nombre: this.data.colegiado.nombre,
                dni: this.data.colegiado.dni,
                matricula: this.data.colegiado.matricula,
                items: items,
                monto_total: total,
                deuda: this.data.resumen
            });
        } else {
            // Fallback: mostrar resumen con toast
            const resumen = items.map(i => `${i.concepto}: S/${this.fmt(i.monto)}`).join(', ');
            if (typeof Toast !== 'undefined') {
                Toast.show(`Total a pagar: S/ ${this.fmt(total)} — ${resumen}`, 'info');
            }
            console.log('[ModalPagos] Checkout items:', items, 'Total:', total);
        }
    },

    /* ==========================================
       UTILIDADES
       ========================================== */

    fmt(n) {
        if (!n && n !== 0) return '0.00';
        return parseFloat(n).toFixed(2);
    },

    getVencimientoClass(fechaStr) {
        if (!fechaStr) return '';
        const hoy = new Date();
        const vence = new Date(fechaStr);
        const dias = Math.ceil((vence - hoy) / (1000 * 60 * 60 * 24));
        if (dias < 0) return 'vencida';
        if (dias <= 7) return 'proxima';
        return '';
    },

    getVencimientoText(fechaStr) {
        if (!fechaStr) return '';
        const hoy = new Date();
        const vence = new Date(fechaStr);
        const dias = Math.ceil((vence - hoy) / (1000 * 60 * 60 * 24));
        if (dias < 0) return `Vencida hace ${Math.abs(dias)}d`;
        if (dias === 0) return 'Vence hoy';
        if (dias <= 7) return `Vence en ${dias}d`;
        return `Vence: ${vence.toLocaleDateString('es-PE', { day: '2-digit', month: 'short' })}`;
    },

    async refresh() {
        this.data = null;
        this.cart = { deudas: [], servicios: [] };
        await this.cargarDatos();
    },

    clearCart() {
        this.cart = { deudas: [], servicios: [] };
        this.renderAll();
    }
};

// Init on DOM ready
document.addEventListener('DOMContentLoaded', () => ModalPagos.init());

}
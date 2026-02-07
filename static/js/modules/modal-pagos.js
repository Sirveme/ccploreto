/**
 * Modal Pagos - Dashboard Colegiado
 * Historial de pagos, estado de cuenta y deudas pendientes
 */

// Evitar redeclaración
if (typeof window.ModalPagos === 'undefined') {

window.ModalPagos = {
    data: null,
    isLoading: false,
    
    /**
     * Inicializa el modal de pagos
     */
    init() {
        console.log('[ModalPagos] Inicializando...');
        this.bindEvents();
    },
    
    /**
     * Bindea eventos
     */
    bindEvents() {
        // Tabs
        document.querySelectorAll('.pagos-tab').forEach(tab => {
            tab.addEventListener('click', (e) => {
                const targetId = e.currentTarget.dataset.tab;
                this.switchTab(targetId);
            });
        });
    },
    
    /**
     * Cambia de tab
     */
    switchTab(tabId) {
        // Desactivar tabs
        document.querySelectorAll('.pagos-tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.pagos-tab-content').forEach(c => c.classList.remove('active'));
        
        // Activar tab seleccionado
        document.querySelector(`.pagos-tab[data-tab="${tabId}"]`)?.classList.add('active');
        document.getElementById(`pagos-${tabId}`)?.classList.add('active');
    },
    
    /**
     * Abre el modal y carga datos
     */
    async open() {
        Modal.open('modal-pagos');
        
        if (!this.data) {
            await this.cargarDatos();
        }
    },
    
    /**
     * Carga datos del servidor
     */
    async cargarDatos() {
        if (this.isLoading) return;
        this.isLoading = true;
        
        this.mostrarLoading();
        
        try {
            const response = await fetch('/api/colegiado/mis-pagos');
            
            if (!response.ok) {
                throw new Error(`Error ${response.status}`);
            }
            
            this.data = await response.json();
            this.renderizar();
            
        } catch (error) {
            console.error('[ModalPagos] Error cargando datos:', error);
            this.mostrarError('No se pudieron cargar los datos. Intenta de nuevo.');
        } finally {
            this.isLoading = false;
        }
    },
    
    /**
     * Muestra estado de carga
     */
    mostrarLoading() {
        const container = document.getElementById('pagos-resumen');
        if (container) {
            container.innerHTML = `
                <div class="pagos-skeleton">
                    <div class="skeleton-item"></div>
                    <div class="skeleton-item"></div>
                    <div class="skeleton-item"></div>
                </div>
            `;
        }
    },
    
    /**
     * Muestra mensaje de error
     */
    mostrarError(mensaje) {
        const container = document.getElementById('pagos-resumen');
        if (container) {
            container.innerHTML = `
                <div class="pagos-empty">
                    <i class="ph ph-warning-circle"></i>
                    <p>${mensaje}</p>
                    <button class="btn-secondary" onclick="ModalPagos.cargarDatos()" style="margin-top:12px;">
                        <i class="ph ph-arrow-clockwise"></i> Reintentar
                    </button>
                </div>
            `;
        }
    },
    
    /**
     * Renderiza todos los datos
     */
    renderizar() {
        this.renderResumen();
        this.renderHistorial();
        this.renderDeudas();
    },
    
    /**
     * Renderiza el resumen de cuenta
     */
    renderResumen() {
        const container = document.getElementById('pagos-resumen');
        if (!container || !this.data) return;
        
        const { resumen } = this.data;
        
        container.innerHTML = `
            <div class="cuenta-resumen">
                <div class="cuenta-card deuda">
                    <div class="cuenta-label">Deuda Total</div>
                    <div class="cuenta-valor">S/ ${this.formatMonto(resumen.deuda_total)}</div>
                </div>
                <div class="cuenta-card pagado">
                    <div class="cuenta-label">Pagado</div>
                    <div class="cuenta-valor">S/ ${this.formatMonto(resumen.total_pagado)}</div>
                </div>
                <div class="cuenta-card pendiente">
                    <div class="cuenta-label">En Revisión</div>
                    <div class="cuenta-valor">S/ ${this.formatMonto(resumen.en_revision)}</div>
                </div>
            </div>
            
            ${resumen.deuda_total > 0 ? `
                <button class="btn-pagar-deuda" onclick="ModalPagos.irAPagar()">
                    <i class="ph ph-credit-card"></i>
                    Pagar Deuda
                </button>
            ` : `
                <div class="pagos-info-box">
                    <i class="ph ph-check-circle"></i>
                    <p>¡Excelente! Estás al día con tus pagos. No tienes deudas pendientes.</p>
                </div>
            `}
        `;
    },
    
    /**
     * Renderiza el historial de pagos
     */
    renderHistorial() {
        const container = document.getElementById('pagos-historial');
        if (!container || !this.data) return;
        
        const { pagos } = this.data;
        
        if (!pagos || pagos.length === 0) {
            container.innerHTML = `
                <div class="pagos-empty">
                    <i class="ph ph-receipt"></i>
                    <p>No tienes pagos registrados</p>
                </div>
            `;
            return;
        }
        
        container.innerHTML = `
            <div class="pagos-lista">
                ${pagos.map(p => this.renderPagoItem(p)).join('')}
            </div>
        `;
    },
    
    /**
     * Renderiza un item de pago
     */
    renderPagoItem(pago) {
        const estadoTexto = {
            'approved': 'Aprobado',
            'review': 'En revisión',
            'rejected': 'Rechazado'
        };
        
        const metodosIcono = {
            'Yape': 'ph-device-mobile',
            'Plin': 'ph-device-mobile',
            'Transferencia': 'ph-bank',
            'Efectivo': 'ph-money'
        };
        
        return `
            <div class="pago-item" onclick="ModalPagos.verDetalle(${pago.id})">
                <div class="pago-info">
                    <span class="pago-fecha">${pago.fecha}</span>
                    <span class="pago-concepto">${pago.concepto || 'Pago de cuotas'}</span>
                    <span class="pago-metodo">
                        <i class="ph ${metodosIcono[pago.metodo] || 'ph-credit-card'}"></i>
                        ${pago.metodo} ${pago.operacion ? `• ${pago.operacion}` : ''}
                    </span>
                </div>
                <div class="pago-monto-estado">
                    <span class="pago-monto">S/ ${this.formatMonto(pago.monto)}</span>
                    <span class="pago-estado ${pago.estado}">${estadoTexto[pago.estado] || pago.estado}</span>
                </div>
            </div>
        `;
    },
    
    /**
     * Renderiza las deudas pendientes
     */
    renderDeudas() {
        const container = document.getElementById('pagos-deudas');
        if (!container || !this.data) return;
        
        const { deudas } = this.data;
        
        if (!deudas || deudas.length === 0) {
            container.innerHTML = `
                <div class="pagos-empty">
                    <i class="ph ph-check-circle"></i>
                    <p>No tienes deudas pendientes</p>
                </div>
            `;
            return;
        }
        
        // Calcular total
        const total = deudas.reduce((sum, d) => sum + d.balance, 0);
        
        container.innerHTML = `
            <div class="deudas-lista">
                ${deudas.map(d => this.renderDeudaItem(d)).join('')}
            </div>
            
            <div class="cuenta-resumen" style="margin-top:20px;">
                <div class="cuenta-card deuda" style="grid-column: span 2;">
                    <div class="cuenta-label">Total a Pagar</div>
                    <div class="cuenta-valor">S/ ${this.formatMonto(total)}</div>
                </div>
            </div>
            
            <button class="btn-pagar-deuda" onclick="ModalPagos.irAPagar()">
                <i class="ph ph-credit-card"></i>
                Pagar Ahora
            </button>
        `;
    },
    
    /**
     * Renderiza un item de deuda
     */
    renderDeudaItem(deuda) {
        const hoy = new Date();
        const vence = new Date(deuda.vencimiento);
        const esVencida = vence < hoy;
        const diasRestantes = Math.ceil((vence - hoy) / (1000 * 60 * 60 * 24));
        
        let claseVencimiento = '';
        let textoVencimiento = '';
        
        if (esVencida) {
            claseVencimiento = 'vencida';
            textoVencimiento = `Vencida hace ${Math.abs(diasRestantes)} días`;
        } else if (diasRestantes <= 7) {
            claseVencimiento = 'proxima';
            textoVencimiento = `Vence en ${diasRestantes} días`;
        } else {
            textoVencimiento = `Vence: ${this.formatFecha(deuda.vencimiento)}`;
        }
        
        return `
            <div class="deuda-item ${claseVencimiento}">
                <div class="deuda-info">
                    <span class="deuda-concepto">${deuda.concepto}</span>
                    <span class="deuda-periodo">${deuda.periodo}</span>
                    <span class="deuda-vence">${textoVencimiento}</span>
                </div>
                <span class="deuda-monto">S/ ${this.formatMonto(deuda.balance)}</span>
            </div>
        `;
    },
    
    /**
     * Ir a la pantalla de pago
     */
    irAPagar() {
        ModalPagos.close();
        // Usar el formulario del FAB con datos del colegiado
        if (typeof AIFab !== 'undefined' && this.data?.colegiado) {
            const colegiado = {
                id: this.data.colegiado.id || null,
                nombre: this.data.colegiado.nombre,
                dni: this.data.colegiado.dni || '',
                matricula: this.data.colegiado.matricula,
                deuda: this.data.resumen
            };
            AIFab.openPagoFormPrellenado(colegiado);
        }
    },
    
    /**
     * Ver detalle de un pago
     */
    verDetalle(pagoId) {
        // Por ahora solo log, después se puede implementar modal de detalle
        console.log('[ModalPagos] Ver detalle:', pagoId);
        
        const pago = this.data?.pagos?.find(p => p.id === pagoId);
        if (pago) {
            Toast.show(`Pago #${pagoId}: S/ ${this.formatMonto(pago.monto)} - ${pago.estado}`, 'info');
        }
    },
    
    /**
     * Refresca los datos
     */
    async refresh() {
        this.data = null;
        await this.cargarDatos();
    },
    
    /**
     * Formatea un monto
     */
    formatMonto(monto) {
        if (!monto && monto !== 0) return '0.00';
        return parseFloat(monto).toFixed(2);
    },
    
    /**
     * Formatea una fecha
     */
    formatFecha(fechaStr) {
        if (!fechaStr) return '-';
        const fecha = new Date(fechaStr);
        return fecha.toLocaleDateString('es-PE', {
            day: '2-digit',
            month: 'short',
            year: 'numeric'
        });
    }
};

// Inicializar cuando se cargue el DOM
document.addEventListener('DOMContentLoaded', () => {
    ModalPagos.init();
});
}

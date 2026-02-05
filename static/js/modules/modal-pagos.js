/**
 * modal-pagos.js
 * Módulo lazy: estado de cuenta, historial de pagos, registrar pago
 */
(function() {
    'use strict';

    const MODAL_ID = 'modal-pagos';
    let initialized = false;

    function init() {
        if (initialized) return;
        initialized = true;
        cargarEstadoCuenta();
    }

    // ========================================
    // CARGAR ESTADO DE CUENTA
    // ========================================
    async function cargarEstadoCuenta() {
        const container = document.getElementById('modal-pagos-content');
        if (!container) return;

        container.innerHTML = `
            <div style="text-align:center; padding:32px; color:#94a3b8;">
                <i class="ph ph-spinner" style="font-size:24px; animation: spin 1s linear infinite;"></i>
                <p style="margin-top:8px;">Cargando estado de cuenta...</p>
            </div>
        `;

        try {
            const matricula = APP_CONFIG.user?.matricula;
            if (!matricula) throw new Error('Matrícula no disponible');

            const res = await fetch(`/api/pagos/estado-cuenta/${matricula}`);
            if (!res.ok) throw new Error('Error al cargar');
            const data = await res.json();

            renderEstadoCuenta(container, data);

        } catch (err) {
            container.innerHTML = `
                <div style="text-align:center; padding:32px; color:#ef4444;">
                    <i class="ph ph-warning-circle" style="font-size:32px;"></i>
                    <p style="margin-top:8px;">${err.message}</p>
                    <button onclick="window._pagosModule.recargar()" 
                        class="btn-retry" style="margin-top:12px; padding:8px 16px; 
                        border-radius:8px; border:1px solid #334155; 
                        background:transparent; color:#94a3b8; cursor:pointer;">
                        Reintentar
                    </button>
                </div>
            `;
        }
    }

    function renderEstadoCuenta(container, data) {
        const { deuda_total, cuotas_pendientes, ultimo_pago, historial } = data;

        const deudaColor = deuda_total > 0 ? '#f59e0b' : '#10b981';
        const deudaIcon = deuda_total > 0 ? 'ph-warning' : 'ph-check-circle';

        container.innerHTML = `
            <!-- Resumen -->
            <div style="
                background: linear-gradient(135deg, ${deudaColor}15, ${deudaColor}05);
                border: 1px solid ${deudaColor}30;
                border-radius: 12px; padding: 20px; margin-bottom: 16px;
            ">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <div>
                        <div style="font-size:12px; color:#94a3b8; text-transform:uppercase;">Deuda Total</div>
                        <div style="font-size:28px; font-weight:700; color:${deudaColor}; margin-top:4px;">
                            S/ ${deuda_total.toFixed(2)}
                        </div>
                    </div>
                    <i class="ph ${deudaIcon}" style="font-size:40px; color:${deudaColor}; opacity:0.5;"></i>
                </div>
                ${cuotas_pendientes > 0 ? `
                    <div style="margin-top:8px; font-size:13px; color:#94a3b8;">
                        ${cuotas_pendientes} cuota(s) pendiente(s)
                    </div>
                ` : ''}
            </div>

            ${deuda_total > 0 ? `
                <button onclick="window._pagosModule.iniciarPago()" style="
                    width:100%; padding:14px; border-radius:12px; border:none;
                    background:#6366f1; color:white; font-size:15px; font-weight:600;
                    cursor:pointer; margin-bottom:20px;
                ">
                    <i class="ph ph-credit-card"></i> Registrar Pago
                </button>
            ` : ''}

            <!-- Historial -->
            <div style="font-size:14px; font-weight:600; margin-bottom:12px; color:#e2e8f0;">
                Historial de Pagos
            </div>
            ${historial && historial.length > 0 ? 
                historial.map(p => renderPago(p)).join('') 
                : '<p style="text-align:center; color:#64748b; padding:20px;">Sin pagos registrados</p>'
            }
        `;
    }

    function renderPago(pago) {
        const estadoMap = {
            'aprobado': { color: '#10b981', icon: 'ph-check-circle', label: 'Aprobado' },
            'pendiente': { color: '#f59e0b', icon: 'ph-clock', label: 'Pendiente' },
            'rechazado': { color: '#ef4444', icon: 'ph-x-circle', label: 'Rechazado' },
            'review': { color: '#6366f1', icon: 'ph-eye', label: 'En revisión' }
        };
        const estado = estadoMap[pago.estado] || estadoMap['pendiente'];

        return `
            <div style="
                padding:14px; margin-bottom:8px;
                background:rgba(255,255,255,0.03);
                border-radius:10px; border:1px solid rgba(255,255,255,0.05);
                display:flex; justify-content:space-between; align-items:center;
            ">
                <div>
                    <div style="font-size:14px; font-weight:500;">${pago.fecha}</div>
                    <div style="font-size:12px; color:#64748b; margin-top:2px;">
                        ${pago.metodo} · Op. ${pago.numero_operacion || '-'}
                    </div>
                </div>
                <div style="text-align:right;">
                    <div style="font-size:15px; font-weight:600;">S/ ${pago.monto.toFixed(2)}</div>
                    <div style="font-size:11px; color:${estado.color}; margin-top:2px;">
                        <i class="ph ${estado.icon}"></i> ${estado.label}
                    </div>
                </div>
            </div>
        `;
    }

    // ========================================
    // FLUJO DE PAGO
    // ========================================
    function iniciarPago() {
        SoundFX.play('click');
        // TODO: Mostrar paso 1 del flujo de pago
        // (monto, método, voucher)
        Toast.show('Módulo de pago en desarrollo', 'info');
    }

    // ========================================
    // ESCUCHAR APERTURA
    // ========================================
    const modal = document.getElementById(MODAL_ID);
    if (modal) {
        modal.addEventListener('modal:opened', () => {
            init();
            if (initialized) cargarEstadoCuenta();
        });
    }

    window._pagosModule = {
        recargar: cargarEstadoCuenta,
        iniciarPago: iniciarPago
    };

})();
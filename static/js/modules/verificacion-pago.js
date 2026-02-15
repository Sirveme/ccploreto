/**
 * Verificación de Pagos en Tiempo Real — Integración Portal Colegiado
 * static/js/modules/verificacion-pago.js
 *
 * Se carga SIEMPRE (junto a ai-fab.js) porque se usa en el flujo de pago.
 *
 * Responsabilidades:
 * 1. Clase VerificadorPago (polling a tabla local)
 * 2. Parche a AIFab.llenarFormularioPago para mostrar datos de cuenta
 * 3. Parche a AIFab.enviarPagoRapido para iniciar verificación post-pago
 * 4. Panel de verificación visual
 */

// ═══════════════════════════════════════════════════
// 1. CLASE VERIFICADOR (polling a /verificar-pago)
// ═══════════════════════════════════════════════════

class VerificadorPago {
    constructor(opts = {}) {
        this.intervalo = opts.intervalo || 10000;
        this.maxIntentos = opts.maxIntentos || 12;
        this.api = opts.api || '/api/conciliacion';
        this.timer = null;
        this.intentos = 0;
        this.onVerificado = opts.onVerificado || null;
        this.onTimeout = opts.onTimeout || null;
        this.onProgreso = opts.onProgreso || null;
    }

    async iniciar(monto, metodo, paymentId) {
        this.detener();
        this.intentos = 0;
        if (await this._check(monto, metodo, paymentId)) return;
        this.timer = setInterval(async () => {
            this.intentos++;
            if (this.onProgreso) this.onProgreso(this.intentos, this.maxIntentos);
            if (this.intentos >= this.maxIntentos) {
                this.detener();
                if (this.onTimeout) this.onTimeout(monto, metodo, paymentId);
                return;
            }
            await this._check(monto, metodo, paymentId);
        }, this.intervalo);
    }

    async _check(monto, metodo, paymentId) {
        try {
            let url = `${this.api}/verificar-pago?monto=${monto}&metodo=${metodo}`;
            if (paymentId) url += `&payment_id=${paymentId}`;
            const r = await fetch(url, { method: 'POST' });
            const d = await r.json();
            if (d.verificado) {
                this.detener();
                if (this.onVerificado) this.onVerificado(d);
                return true;
            }
        } catch (e) { console.warn('[Verificador] error:', e); }
        return false;
    }

    detener() {
        if (this.timer) { clearInterval(this.timer); this.timer = null; }
    }
}

window.VerificadorPago = VerificadorPago;


// ═══════════════════════════════════════════════════
// 2. CACHE DE CUENTAS RECEPTORAS
// ═══════════════════════════════════════════════════

const CuentasPago = {
    _data: null,

    async obtener() {
        if (this._data) return this._data;
        try {
            const r = await fetch('/api/conciliacion/cuentas?activo=true');
            const d = await r.json();
            this._data = d.cuentas || [];
        } catch (e) {
            console.warn('[CuentasPago] No se pudieron cargar cuentas:', e);
            this._data = [];
        }
        return this._data;
    },

    /** Busca cuenta por tipo: yape, plin, transferencia */
    buscarPorTipo(tipo) {
        if (!this._data) return null;
        tipo = tipo.toLowerCase();
        return this._data.find(c =>
            c.tipo === tipo || c.nombre.toLowerCase().includes(tipo)
        );
    }
};

window.CuentasPago = CuentasPago;


// ═══════════════════════════════════════════════════
// 3. PARCHE A AIFab — Mostrar datos de cuenta + verificación
// ═══════════════════════════════════════════════════

(function patchAIFab() {
    // Esperar a que AIFab exista
    const esperar = setInterval(() => {
        if (typeof AIFab === 'undefined') return;
        clearInterval(esperar);

        // Guardar originales
        const _originalLlenar = AIFab.llenarFormularioPago.bind(AIFab);
        const _originalEnviar = AIFab.enviarPagoRapido.bind(AIFab);

        // ─── PARCHE: llenarFormularioPago ───
        AIFab.llenarFormularioPago = async function(colegiado) {
            // Llamar al original
            _originalLlenar(colegiado);

            // Precargar cuentas
            const cuentas = await CuentasPago.obtener();

            const container = document.getElementById('pago-rapido-content');
            if (!container) return;

            // Insertar panel de datos de cuenta DESPUÉS de los métodos de pago
            const metodosDiv = container.querySelector('#metodos-pago');
            if (!metodosDiv) return;

            // Crear panel de info de cuenta
            const infoPanel = document.createElement('div');
            infoPanel.id = 'info-cuenta-pago';
            infoPanel.style.cssText = 'margin: 12px 0 4px; transition: all 0.3s ease;';
            metodosDiv.parentElement.insertBefore(infoPanel, metodosDiv.nextSibling);

            // Crear panel de verificación (oculto inicialmente)
            const verifPanel = document.createElement('div');
            verifPanel.id = 'verif-panel-portal';
            verifPanel.style.cssText = 'display:none; margin: 16px 0;';
            const resultado = container.querySelector('#pago-rapido-resultado');
            if (resultado) {
                resultado.parentElement.insertBefore(verifPanel, resultado);
            }

            // Mostrar info de la cuenta seleccionada por defecto
            _mostrarInfoCuenta('yape');

            // Hook en cambio de método de pago
            container.querySelectorAll('.metodo-btn').forEach(label => {
                label.addEventListener('click', function() {
                    const metodo = this.dataset.metodo.toLowerCase();
                    _mostrarInfoCuenta(metodo);
                });
            });
        };

        // ─── PARCHE: enviarPagoRapido ───
        AIFab.enviarPagoRapido = async function(event) {
            event.preventDefault();

            const form = document.getElementById('form-pago-rapido');
            const formData = new FormData(form);
            const resultadoDiv = document.getElementById('pago-rapido-resultado');
            const btnSubmit = document.getElementById('btn-pago-rapido');

            const monto = parseFloat(formData.get('monto'));
            const metodo = (formData.get('metodo_pago') || 'yape').toLowerCase();

            btnSubmit.disabled = true;
            btnSubmit.innerHTML = '⏳ Procesando...';

            try {
                const response = await fetch('/pagos/registrar', {
                    method: 'POST',
                    body: formData
                });

                const html = await response.text();

                if (response.ok && !html.includes('❌')) {
                    // Pago registrado OK
                    // Extraer payment_id si viene en la respuesta
                    const paymentIdMatch = html.match(/payment[_-]id[=":\s]+(\d+)/i);
                    const paymentId = paymentIdMatch ? parseInt(paymentIdMatch[1]) : null;

                    // ¿Es pago digital? → Iniciar verificación
                    if (['yape', 'plin', 'transferencia'].includes(metodo)) {
                        _mostrarVerificacion(monto, metodo, paymentId, html);
                    } else {
                        // Efectivo → mostrar respuesta normal
                        const contentDiv = document.getElementById('pago-rapido-content');
                        if (contentDiv) contentDiv.innerHTML = html;
                    }

                    // Refrescar ModalPagos
                    if (typeof ModalPagos !== 'undefined' && ModalPagos.cargarDatos) {
                        setTimeout(() => ModalPagos.cargarDatos(), 500);
                    }

                } else {
                    if (resultadoDiv) resultadoDiv.innerHTML = html;
                    btnSubmit.disabled = false;
                    btnSubmit.innerHTML = '✓ REGISTRAR PAGO';
                }
            } catch (error) {
                console.error('[Pago] Error:', error);
                if (resultadoDiv) {
                    resultadoDiv.innerHTML = `
                        <div style="background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.3);color:#ef4444;padding:10px;border-radius:8px;font-size:12px;">
                            ❌ Error de conexión. Intenta de nuevo.
                        </div>`;
                }
                btnSubmit.disabled = false;
                btnSubmit.innerHTML = '✓ REGISTRAR PAGO';
            }
        };

        console.log('[Verificación] Parches aplicados a AIFab');
    }, 200);


    // ─── Helper: Mostrar info de la cuenta receptora ───
    function _mostrarInfoCuenta(metodo) {
        const panel = document.getElementById('info-cuenta-pago');
        if (!panel) return;

        const cuenta = CuentasPago.buscarPorTipo(metodo);

        if (!cuenta) {
            panel.innerHTML = '';
            panel.style.display = 'none';
            return;
        }

        panel.style.display = 'block';

        const esWallet = ['yape', 'plin'].includes(metodo);

        if (esWallet) {
            panel.innerHTML = `
                <div style="background:rgba(99,102,241,0.08);border:1px solid rgba(99,102,241,0.2);border-radius:10px;padding:12px 14px;display:flex;align-items:center;gap:12px;">
                    <div style="font-size:28px;">${metodo === 'yape' ? '💜' : '💚'}</div>
                    <div style="flex:1;">
                        <div style="color:#e2e8f0;font-size:13px;font-weight:600;">
                            Enviar a ${metodo.charAt(0).toUpperCase() + metodo.slice(1)}
                        </div>
                        <div style="color:#6366f1;font-size:20px;font-weight:800;font-family:monospace;letter-spacing:1px;">
                            ${cuenta.telefono || '—'}
                        </div>
                        <div style="color:#94a3b8;font-size:11px;">
                            ${cuenta.titular || ''} ${cuenta.banco ? '• ' + cuenta.banco : ''}
                        </div>
                    </div>
                    <button type="button" onclick="navigator.clipboard.writeText('${cuenta.telefono || ''}');this.innerHTML='✓';setTimeout(()=>this.innerHTML='📋',1500)"
                            style="background:rgba(255,255,255,0.08);border:1px solid rgba(255,255,255,0.1);color:#94a3b8;padding:8px;border-radius:8px;cursor:pointer;font-size:16px;">
                        📋
                    </button>
                </div>
            `;
        } else {
            // Transferencia bancaria
            panel.innerHTML = `
                <div style="background:rgba(245,158,11,0.08);border:1px solid rgba(245,158,11,0.2);border-radius:10px;padding:12px 14px;">
                    <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px;">
                        <span style="font-size:22px;">🏦</span>
                        <div>
                            <div style="color:#e2e8f0;font-size:13px;font-weight:600;">
                                ${cuenta.banco || 'Banco'}
                            </div>
                            <div style="color:#94a3b8;font-size:11px;">${cuenta.titular || ''}</div>
                        </div>
                    </div>
                    <div style="display:flex;align-items:center;gap:8px;margin-top:8px;">
                        <div style="color:#f59e0b;font-size:15px;font-weight:700;font-family:monospace;flex:1;">
                            ${cuenta.numero_cuenta || '—'}
                        </div>
                        <button type="button" onclick="navigator.clipboard.writeText('${(cuenta.numero_cuenta || '').replace(/-/g, '')}');this.innerHTML='✓';setTimeout(()=>this.innerHTML='📋',1500)"
                                style="background:rgba(255,255,255,0.08);border:1px solid rgba(255,255,255,0.1);color:#94a3b8;padding:6px 8px;border-radius:6px;cursor:pointer;font-size:14px;">
                            📋
                        </button>
                    </div>
                </div>
            `;
        }
    }


    // ─── Helper: Mostrar panel de verificación post-pago ───
    function _mostrarVerificacion(monto, metodo, paymentId, htmlRespuesta) {
        const container = document.getElementById('pago-rapido-content');
        if (!container) return;

        container.innerHTML = `
            <div id="verif-resultado" style="text-align:center;padding:8px 0;">

                <!-- Respuesta del servidor (éxito del registro) -->
                <div style="background:rgba(34,197,94,0.08);border:1px solid rgba(34,197,94,0.2);border-radius:12px;padding:16px;margin-bottom:16px;">
                    <div style="font-size:32px;margin-bottom:4px;">✅</div>
                    <div style="color:#22c55e;font-size:16px;font-weight:700;">Pago registrado</div>
                    <div style="color:#94a3b8;font-size:12px;margin-top:4px;">S/ ${monto.toFixed(2)} vía ${metodo.toUpperCase()}</div>
                </div>

                <!-- Panel de verificación bancaria -->
                <div id="verif-status-panel" style="background:rgba(99,102,241,0.06);border:1px solid rgba(99,102,241,0.15);border-radius:12px;padding:20px;">
                    <div id="verif-icon" style="font-size:36px;margin-bottom:8px;" class="verif-pulsing">🔍</div>
                    <div id="verif-title" style="color:#e2e8f0;font-size:14px;font-weight:600;">
                        Verificando con tu banco...
                    </div>
                    <div id="verif-subtitle" style="color:#94a3b8;font-size:12px;margin-top:4px;">
                        Buscando confirmación bancaria automáticamente
                    </div>
                    <div style="margin:14px auto;width:180px;height:4px;background:rgba(255,255,255,0.06);border-radius:2px;overflow:hidden;">
                        <div id="verif-bar" style="height:100%;background:#6366f1;border-radius:2px;transition:width 0.5s ease;width:5%;"></div>
                    </div>
                    <div id="verif-timer" style="color:#64748b;font-size:11px;"></div>
                </div>

                <!-- Botones (aparecen según resultado) -->
                <div id="verif-actions" style="margin-top:16px;display:flex;gap:10px;justify-content:center;flex-wrap:wrap;"></div>
            </div>
        `;

        // Inyectar CSS de animación si no existe
        if (!document.getElementById('verif-pulse-css')) {
            const style = document.createElement('style');
            style.id = 'verif-pulse-css';
            style.textContent = `
                @keyframes verifPulse {
                    0%, 100% { opacity:1; transform:scale(1); }
                    50% { opacity:0.6; transform:scale(0.95); }
                }
                .verif-pulsing { animation: verifPulse 1.5s infinite; }
            `;
            document.head.appendChild(style);
        }

        // Iniciar verificación
        const verificador = new VerificadorPago({
            intervalo: 10000,
            maxIntentos: 12,

            onVerificado: (data) => {
                const panel = document.getElementById('verif-status-panel');
                if (panel) {
                    panel.style.borderColor = 'rgba(34,197,94,0.3)';
                    panel.style.background = 'rgba(34,197,94,0.08)';
                }
                const icon = document.getElementById('verif-icon');
                if (icon) { icon.textContent = '✅'; icon.className = ''; }

                // Título según si se auto-aprobó
                const autoAprobado = data.auto_aprobado;
                const cert = data.certificado;
                const habil = data.cambio_habilidad;

                let titulo = '¡Pago verificado!';
                if (autoAprobado) titulo = '¡Pago verificado y aprobado!';

                document.getElementById('verif-title').innerHTML =
                    `<span style="color:#22c55e;">${titulo}</span>`;
                document.getElementById('verif-subtitle').innerHTML =
                    `${data.banco.toUpperCase()} ${data.codigo_operacion ? '• Operación #' + data.codigo_operacion : ''}`;
                document.getElementById('verif-bar').style.width = '100%';
                document.getElementById('verif-bar').style.background = '#22c55e';
                document.getElementById('verif-timer').textContent = '';

                // Badges extra
                let badges = '';
                if (habil) {
                    badges += `<div style="background:rgba(34,197,94,0.1);border:1px solid rgba(34,197,94,0.2);border-radius:8px;padding:8px 12px;margin:10px 0;text-align:center;">
                        <span style="color:#22c55e;font-size:13px;font-weight:600;">🎉 ¡Felicidades! Tu condición cambió a <strong>HÁBIL</strong></span>
                    </div>`;
                }
                if (cert && cert.emitido) {
                    badges += `<div style="background:rgba(99,102,241,0.08);border:1px solid rgba(99,102,241,0.15);border-radius:8px;padding:8px 12px;margin:6px 0;text-align:center;">
                        <span style="color:#818cf8;font-size:12px;">📜 Certificado ${cert.codigo || ''} emitido automáticamente</span>
                    </div>`;
                }

                const actions = document.getElementById('verif-actions');
                actions.innerHTML = `
                    ${badges}
                    <div style="display:flex;gap:10px;justify-content:center;flex-wrap:wrap;width:100%;margin-top:6px;">
                        <button onclick="if(typeof generarConstancia==='function') generarConstancia(); else Toast.show('Constancia disponible desde el dashboard','info');"
                                style="background:#22c55e;color:#fff;border:none;padding:12px 24px;border-radius:10px;font-size:14px;font-weight:600;cursor:pointer;">
                            📄 Descargar Constancia
                        </button>
                        <button onclick="AIFab.cerrarModalPagoRapido()"
                                style="background:rgba(255,255,255,0.08);color:#94a3b8;border:1px solid rgba(255,255,255,0.1);padding:12px 20px;border-radius:10px;font-size:13px;cursor:pointer;">
                            Cerrar
                        </button>
                    </div>
                `;

                // Sonido
                if (typeof SoundFX !== 'undefined') SoundFX.play('success');
                if (typeof Toast !== 'undefined') Toast.show('✅ Pago verificado con el banco', 'success');

                // Refrescar ModalPagos
                if (typeof ModalPagos !== 'undefined') {
                    setTimeout(() => { ModalPagos.data = null; ModalPagos.cargarDatos(); }, 1000);
                }
            },

            onTimeout: (monto, metodo, paymentId) => {
                const icon = document.getElementById('verif-icon');
                if (icon) { icon.textContent = '⏳'; icon.className = ''; }

                document.getElementById('verif-title').innerHTML =
                    `<span style="color:#f59e0b;">Verificación pendiente</span>`;
                document.getElementById('verif-subtitle').innerHTML =
                    'No detectamos la confirmación bancaria aún.<br>Tu pago quedó registrado y será validado manualmente.';
                document.getElementById('verif-timer').textContent = '';

                const panel = document.getElementById('verif-status-panel');
                if (panel) {
                    panel.style.borderColor = 'rgba(245,158,11,0.2)';
                    panel.style.background = 'rgba(245,158,11,0.06)';
                }

                const actions = document.getElementById('verif-actions');
                actions.innerHTML = `
                    <button onclick="location.reload()"
                            style="background:rgba(99,102,241,0.15);color:#818cf8;border:1px solid rgba(99,102,241,0.2);padding:10px 20px;border-radius:8px;font-size:13px;cursor:pointer;">
                        🔄 Reintentar
                    </button>
                    <button onclick="AIFab.cerrarModalPagoRapido()"
                            style="background:rgba(255,255,255,0.08);color:#94a3b8;border:1px solid rgba(255,255,255,0.1);padding:10px 20px;border-radius:8px;font-size:13px;cursor:pointer;">
                        Cerrar
                    </button>
                `;
            },

            onProgreso: (intento, max) => {
                const pct = Math.round((intento / max) * 100);
                const segs = (max - intento) * 10;
                const bar = document.getElementById('verif-bar');
                const timer = document.getElementById('verif-timer');
                if (bar) bar.style.width = pct + '%';
                if (timer) timer.textContent = `~${segs}s restantes`;
            }
        });

        verificador.iniciar(monto, metodo, paymentId);
    }

})();
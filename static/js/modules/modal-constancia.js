/**
 * modal-constancia.js
 * Módulo lazy: generar y descargar constancia de habilidad PDF
 */
(function() {
    'use strict';

    const MODAL_ID = 'modal-constancia';
    let initialized = false;

    function init() {
        if (initialized) return;
        initialized = true;
        verificarEstado();
    }

    async function verificarEstado() {
        const container = document.getElementById('constancia-content');
        if (!container) return;

        container.innerHTML = `
            <div style="text-align:center; padding:32px; color:#94a3b8;">
                <i class="ph ph-spinner" style="font-size:24px; animation: spin 1s linear infinite;"></i>
                <p style="margin-top:8px;">Verificando estado...</p>
            </div>
        `;

        try {
            const res = await fetch('/api/colegiado/estado-habilidad');
            if (!res.ok) throw new Error('Error al verificar');
            const data = await res.json();

            renderConstancia(container, data);
        } catch (err) {
            container.innerHTML = `
                <div style="text-align:center; padding:32px; color:#ef4444;">
                    <p>${err.message}</p>
                    <button onclick="window._constanciaModule.recargar()" 
                        style="margin-top:12px; padding:8px 16px; border-radius:8px; 
                        border:1px solid #334155; background:transparent; color:#94a3b8; cursor:pointer;">
                        Reintentar
                    </button>
                </div>
            `;
        }
    }

    function renderConstancia(container, data) {
        const esHabil = data.condicion === 'habil';

        container.innerHTML = `
            <div style="text-align:center; padding:24px 0;">
                <div style="
                    width:80px; height:80px; border-radius:50%; margin:0 auto 16px;
                    background:${esHabil ? '#10b981' : '#ef4444'}15;
                    display:flex; align-items:center; justify-content:center;
                ">
                    <i class="ph ${esHabil ? 'ph-check-circle' : 'ph-x-circle'}" 
                        style="font-size:40px; color:${esHabil ? '#10b981' : '#ef4444'};"></i>
                </div>
                <div style="font-size:13px; color:#64748b; text-transform:uppercase; letter-spacing:1px;">
                    Estado actual
                </div>
                <div style="font-size:24px; font-weight:700; margin-top:4px; color:${esHabil ? '#10b981' : '#ef4444'};">
                    ${esHabil ? 'HÁBIL' : 'INHÁBIL'}
                </div>
                ${data.vigencia_hasta ? `
                    <div style="font-size:13px; color:#94a3b8; margin-top:8px;">
                        Vigente hasta: ${data.vigencia_hasta}
                    </div>
                ` : ''}
            </div>

            ${esHabil ? `
                <button onclick="window._constanciaModule.generar()" style="
                    width:100%; padding:14px; border-radius:12px; border:none;
                    background:#10b981; color:white; font-size:15px; font-weight:600;
                    cursor:pointer; margin-top:8px;
                ">
                    <i class="ph ph-file-pdf"></i> Generar Constancia PDF
                </button>
                <p style="text-align:center; font-size:12px; color:#64748b; margin-top:8px;">
                    La constancia incluye código QR de verificación
                </p>
            ` : `
                <div style="
                    padding:16px; border-radius:12px; margin-top:16px;
                    background:rgba(239,68,68,0.08); border:1px solid rgba(239,68,68,0.2);
                    font-size:13px; color:#94a3b8; text-align:center;
                ">
                    Para generar tu constancia, debes estar al día en tus pagos.
                    <button onclick="abrirModalLazy('modal-pagos')" style="
                        display:block; margin:12px auto 0; padding:8px 20px;
                        border-radius:8px; border:none; background:#6366f1; 
                        color:white; font-size:13px; cursor:pointer;
                    ">Ver mis pagos</button>
                </div>
            `}
        `;
    }

    async function generarConstancia() {
        SoundFX.play('click');
        Toast.show('Generando constancia...', 'info');

        try {
            const res = await fetch('/api/constancia/generar', { method: 'POST' });
            if (!res.ok) throw new Error('No se pudo generar');

            const blob = await res.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `constancia-habilidad-${APP_CONFIG.user?.matricula || 'doc'}.pdf`;
            a.click();
            URL.revokeObjectURL(url);

            SoundFX.play('success');
            Toast.show('Constancia descargada', 'success');
        } catch (err) {
            SoundFX.play('error');
            Toast.show(err.message, 'error');
        }
    }

    const modal = document.getElementById(MODAL_ID);
    if (modal) {
        modal.addEventListener('modal:opened', () => {
            init();
            if (initialized) verificarEstado();
        });
    }

    window._constanciaModule = {
        recargar: verificarEstado,
        generar: generarConstancia
    };

})();
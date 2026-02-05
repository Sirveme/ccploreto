/**
 * modal-certificados.js
 * Módulo lazy: se carga solo cuando el colegiado abre el modal de certificados
 * 
 * Patrón: cada módulo se auto-registra escuchando 'modal:opened' en su dialog
 */
(function() {
    'use strict';

    const MODAL_ID = 'modal-certificados';
    let initialized = false;

    // ========================================
    // INICIALIZACIÓN (se ejecuta al abrir)
    // ========================================
    function init() {
        if (initialized) return;
        initialized = true;

        const modal = document.getElementById(MODAL_ID);
        if (!modal) return;

        // Bindear eventos internos del modal
        modal.addEventListener('click', handleDelegatedClicks);

        // Cargar certificados del colegiado
        cargarCertificados();
    }

    // ========================================
    // CARGAR CERTIFICADOS DESDE API
    // ========================================
    async function cargarCertificados() {
        const container = document.getElementById('certificados-lista');
        if (!container) return;

        container.innerHTML = `
            <div style="text-align:center; padding:32px; color:#94a3b8;">
                <i class="ph ph-spinner" style="font-size:24px; animation: spin 1s linear infinite;"></i>
                <p style="margin-top:8px; font-size:13px;">Cargando certificados...</p>
            </div>
        `;

        try {
            const res = await fetch('/api/colegiado/certificados');
            if (!res.ok) throw new Error('Error al obtener certificados');
            const data = await res.json();

            if (!data.certificados || data.certificados.length === 0) {
                container.innerHTML = `
                    <div style="text-align:center; padding:32px; color:#64748b;">
                        <i class="ph ph-certificate" style="font-size:40px; opacity:0.5;"></i>
                        <p style="margin-top:12px;">No tienes certificados emitidos aún</p>
                        <p style="font-size:12px; margin-top:4px; color:#475569;">
                            Los certificados se generan automáticamente al aprobar tu pago
                        </p>
                    </div>
                `;
                return;
            }

            container.innerHTML = data.certificados.map(cert => renderCertificado(cert)).join('');

        } catch (err) {
            container.innerHTML = `
                <div style="text-align:center; padding:32px; color:#ef4444;">
                    <i class="ph ph-warning-circle" style="font-size:32px;"></i>
                    <p style="margin-top:8px;">${err.message}</p>
                    <button onclick="window._certModule.recargar()" 
                        class="btn-sm" style="margin-top:12px; padding:8px 16px; 
                        border-radius:8px; border:1px solid #334155; 
                        background:transparent; color:#94a3b8; cursor:pointer;">
                        Reintentar
                    </button>
                </div>
            `;
        }
    }

    // ========================================
    // RENDER DE UN CERTIFICADO
    // ========================================
    function renderCertificado(cert) {
        const estadoColor = {
            'vigente': '#10b981',
            'vencido': '#ef4444',
            'anulado': '#64748b'
        };
        const color = estadoColor[cert.estado] || '#94a3b8';

        return `
            <div class="cert-card" style="
                padding:16px; margin-bottom:12px; 
                background:rgba(255,255,255,0.03); 
                border-radius:12px; border:1px solid rgba(255,255,255,0.06);
            ">
                <div style="display:flex; justify-content:space-between; align-items:start;">
                    <div>
                        <div style="font-size:11px; color:#64748b; text-transform:uppercase; letter-spacing:0.5px;">
                            Certificado Nº
                        </div>
                        <div style="font-size:16px; font-weight:600; margin-top:2px;">
                            ${cert.codigo_verificacion}
                        </div>
                    </div>
                    <span style="
                        padding:4px 10px; border-radius:6px; font-size:11px; font-weight:600;
                        background:${color}22; color:${color}; text-transform:uppercase;
                    ">${cert.estado}</span>
                </div>
                <div style="margin-top:12px; display:flex; gap:16px; font-size:13px; color:#94a3b8;">
                    <span><i class="ph ph-calendar"></i> ${cert.fecha_emision}</span>
                    <span><i class="ph ph-clock"></i> Vigente hasta ${cert.fecha_vigencia_hasta}</span>
                </div>
                <div style="margin-top:12px; display:flex; gap:8px;">
                    ${cert.estado === 'vigente' ? `
                        <button onclick="window._certModule.descargar('${cert.codigo_verificacion}')" 
                            style="flex:1; padding:8px; border-radius:8px; border:none; 
                            background:#6366f1; color:white; font-size:13px; font-weight:500; cursor:pointer;">
                            <i class="ph ph-download-simple"></i> Descargar PDF
                        </button>
                        <button onclick="window._certModule.verificar('${cert.codigo_verificacion}', '${cert.codigo_seguridad}')" 
                            style="padding:8px 12px; border-radius:8px; border:1px solid #334155; 
                            background:transparent; color:#94a3b8; cursor:pointer;">
                            <i class="ph ph-qr-code"></i>
                        </button>
                    ` : ''}
                </div>
            </div>
        `;
    }

    // ========================================
    // ACCIONES
    // ========================================
    async function descargarCertificado(codigoVerificacion) {
        SoundFX.play('click');
        Toast.show('Generando PDF...', 'info');

        try {
            const res = await fetch(`/api/certificado/descargar/${codigoVerificacion}`);
            if (!res.ok) throw new Error('No se pudo descargar');

            const blob = await res.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `certificado-${codigoVerificacion}.pdf`;
            a.click();
            URL.revokeObjectURL(url);

            SoundFX.play('success');
            Toast.show('Certificado descargado', 'success');
        } catch (err) {
            SoundFX.play('error');
            Toast.show(err.message, 'error');
        }
    }

    function verificarCertificado(codigo, seguridad) {
        const url = `/verificar/ccpl?codigo=${codigo}&seguridad=${seguridad}`;
        window.open(url, '_blank');
        SoundFX.play('click');
    }

    function handleDelegatedClicks(e) {
        // Delegación de eventos dentro del modal
    }

    // ========================================
    // ESCUCHAR APERTURA DEL MODAL
    // ========================================
    const modal = document.getElementById(MODAL_ID);
    if (modal) {
        modal.addEventListener('modal:opened', () => {
            init();
            // Recargar siempre al abrir (datos pueden cambiar)
            if (initialized) cargarCertificados();
        });
    }

    // API pública del módulo
    window._certModule = {
        recargar: cargarCertificados,
        descargar: descargarCertificado,
        verificar: verificarCertificado
    };

})();
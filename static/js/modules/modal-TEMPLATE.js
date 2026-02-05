/**
 * modal-TEMPLATE.js
 * ──────────────────────────────────────────
 * INSTRUCCIONES: Copiar este archivo y reemplazar:
 *   1. MODAL_ID → id real del <dialog>
 *   2. _templateModule → nombre único del módulo  
 *   3. Implementar init() y las funciones del módulo
 * ──────────────────────────────────────────
 */
(function() {
    'use strict';

    const MODAL_ID = 'modal-TEMPLATE';  // ← Cambiar
    let initialized = false;

    // Se ejecuta la primera vez que se abre el modal
    function init() {
        if (initialized) return;
        initialized = true;

        // Bindear eventos, cargar datos iniciales, etc.
        cargarDatos();
    }

    // Carga de datos desde API
    async function cargarDatos() {
        const container = document.getElementById('TEMPLATE-content'); // ← Cambiar
        if (!container) return;

        // Spinner
        container.innerHTML = `
            <div style="text-align:center; padding:32px; color:#94a3b8;">
                <i class="ph ph-spinner" style="font-size:24px; animation: spin 1s linear infinite;"></i>
                <p style="margin-top:8px;">Cargando...</p>
            </div>
        `;

        try {
            const res = await fetch('/api/ENDPOINT');  // ← Cambiar
            if (!res.ok) throw new Error('Error al cargar');
            const data = await res.json();

            // Renderizar contenido
            container.innerHTML = `<p>Contenido cargado</p>`;

        } catch (err) {
            container.innerHTML = `
                <div style="text-align:center; padding:32px; color:#ef4444;">
                    <i class="ph ph-warning-circle" style="font-size:32px;"></i>
                    <p style="margin-top:8px;">${err.message}</p>
                    <button onclick="window._templateModule.recargar()" 
                        style="margin-top:12px; padding:8px 16px; border-radius:8px; 
                        border:1px solid #334155; background:transparent; 
                        color:#94a3b8; cursor:pointer;">
                        Reintentar
                    </button>
                </div>
            `;
        }
    }

    // ========================================
    // AUTO-REGISTRO: escuchar apertura del modal
    // ========================================
    const modal = document.getElementById(MODAL_ID);
    if (modal) {
        modal.addEventListener('modal:opened', () => {
            init();
            if (initialized) cargarDatos(); // Recargar cada vez que se abre
        });
    }

    // API pública del módulo
    window._templateModule = {  // ← Cambiar nombre
        recargar: cargarDatos
    };

})();
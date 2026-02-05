/**
 * modal-herramientas.js
 * Módulo lazy: Calculadoras IGV, Renta 4ta, Tipo de Cambio
 * (Migrado de herramientas_pro.js al patrón lazy)
 */
(function() {
    'use strict';

    const MODAL_ID = 'modal-herramientas';
    let initialized = false;
    let tipoIGV = 'sin';
    let tcCompra = 0;
    let tcVenta = 0;

    function init() {
        if (initialized) return;
        initialized = true;
        cargarTipoCambio();
    }

    // === Tabs ===
    function cambiarTab(tab, btn) {
        document.querySelectorAll('.tools-tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.tools-panel').forEach(p => p.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById('tab-' + tab)?.classList.add('active');
        if (tab === 'calc') cargarTipoCambio();
        SoundFX.play('click');
    }

    // === IGV ===
    function setTipoIGV(tipo) {
        tipoIGV = tipo;
        document.getElementById('btn-sin-igv')?.classList.toggle('active', tipo === 'sin');
        document.getElementById('btn-con-igv')?.classList.toggle('active', tipo === 'con');
        calcularIGV();
    }

    function calcularIGV() {
        const monto = parseFloat(document.getElementById('calc-igv-monto')?.value) || 0;
        let base, igv, total;
        if (tipoIGV === 'sin') {
            base = monto; igv = monto * 0.18; total = monto + igv;
        } else {
            total = monto; base = monto / 1.18; igv = total - base;
        }
        const setText = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = 'S/ ' + val.toFixed(2); };
        setText('igv-base', base);
        setText('igv-monto', igv);
        setText('igv-total', total);
    }

    // === Renta 4ta ===
    function calcularRenta4ta() {
        const monto = parseFloat(document.getElementById('calc-4ta-monto')?.value) || 0;
        let retencion = 0, aplica = 'No', neto = monto;
        if (monto > 1500) {
            retencion = monto * 0.08;
            aplica = 'Sí (8%)';
            neto = monto - retencion;
        }
        const el = (id) => document.getElementById(id);
        if (el('renta4ta-retencion')) el('renta4ta-retencion').textContent = 'S/ ' + retencion.toFixed(2);
        if (el('renta4ta-aplica')) { el('renta4ta-aplica').textContent = aplica; el('renta4ta-aplica').style.color = aplica === 'No' ? '#10b981' : '#f59e0b'; }
        if (el('renta4ta-neto')) el('renta4ta-neto').textContent = 'S/ ' + neto.toFixed(2);
    }

    // === Tipo de Cambio ===
    async function cargarTipoCambio() {
        const fechaEl = document.getElementById('tc-fecha');
        const compraEl = document.getElementById('tc-compra');
        const ventaEl = document.getElementById('tc-venta');
        if (fechaEl) fechaEl.textContent = 'Cargando...';

        try {
            // TODO: Conectar con API real de TC SUNAT
            tcCompra = 3.72; tcVenta = 3.78;
            if (compraEl) compraEl.textContent = tcCompra.toFixed(2);
            if (ventaEl) ventaEl.textContent = tcVenta.toFixed(2);
            if (fechaEl) fechaEl.textContent = new Date().toLocaleDateString('es-PE', { day: '2-digit', month: 'short' });
        } catch (error) {
            if (fechaEl) fechaEl.textContent = 'Error';
            if (compraEl) compraEl.textContent = '-';
            if (ventaEl) ventaEl.textContent = '-';
        }
    }

    function convertirTC() {
        const usd = parseFloat(document.getElementById('tc-usd')?.value) || 0;
        const resultEl = document.getElementById('tc-resultado');
        if (resultEl) resultEl.textContent = 'S/ ' + (usd * tcVenta).toFixed(2);
    }

    // === Auto-registro ===
    const modal = document.getElementById(MODAL_ID);
    if (modal) {
        modal.addEventListener('modal:opened', () => init());
    }

    // API pública
    window._herramientasModule = {
        cambiarTab, setTipoIGV, calcularIGV,
        calcularRenta4ta, cargarTipoCambio, convertirTC
    };
    // Alias globales para onclick en HTML
    window.cambiarTabHerramientas = cambiarTab;
    window.setTipoIGV = setTipoIGV;
    window.calcularIGV = calcularIGV;
    window.calcularRenta4ta = calcularRenta4ta;
    window.convertirTC = convertirTC;

})();
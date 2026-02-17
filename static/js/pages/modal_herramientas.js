/**
 * Modal Herramientas Pro — Tabs, Calculadoras, Tipo de Cambio
 */

// Tab switching
function cambiarTabHerramientas(tabId, btn) {
    document.querySelectorAll('.tools-panel').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.tools-tab').forEach(t => t.classList.remove('active'));

    const panel = document.getElementById('tab-' + tabId);
    if (panel) panel.classList.add('active');
    if (btn) btn.classList.add('active');

    // Cargar TC cuando se abre la tab de cálculos
    if (tabId === 'calc') cargarTipoCambio();
}

// ═══ Calculadora IGV ═══
let tipoIGV = 'sin';

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
        base = monto;
        igv = monto * 0.18;
        total = monto + igv;
    } else {
        total = monto;
        base = monto / 1.18;
        igv = total - base;
    }

    const el = (id) => document.getElementById(id);
    if (el('igv-base'))  el('igv-base').textContent  = 'S/ ' + base.toFixed(2);
    if (el('igv-monto')) el('igv-monto').textContent = 'S/ ' + igv.toFixed(2);
    if (el('igv-total')) el('igv-total').textContent = 'S/ ' + total.toFixed(2);
}

// ═══ Calculadora Renta 4ta ═══
function calcularRenta4ta() {
    const monto = parseFloat(document.getElementById('calc-4ta-monto')?.value) || 0;
    const aplica = monto > 1500;
    const retencion = aplica ? monto * 0.08 : 0;
    const neto = monto - retencion;

    const el = (id) => document.getElementById(id);
    if (el('renta4ta-retencion')) el('renta4ta-retencion').textContent = 'S/ ' + retencion.toFixed(2);
    if (el('renta4ta-aplica')) {
        el('renta4ta-aplica').textContent = aplica ? 'Sí' : 'No';
        el('renta4ta-aplica').style.color = aplica ? '#ef4444' : '#10b981';
    }
    if (el('renta4ta-neto')) el('renta4ta-neto').textContent = 'S/ ' + neto.toFixed(2);
}

// ═══ Tipo de Cambio ═══
let tcCompra = 0, tcVenta = 0;

async function cargarTipoCambio() {
    const fechaEl = document.getElementById('tc-fecha');
    const compraEl = document.getElementById('tc-compra');
    const ventaEl = document.getElementById('tc-venta');

    if (!fechaEl || tcCompra > 0) return; // Ya cargado

    fechaEl.textContent = 'Cargando...';

    try {
        // TODO: Conectar con API real → /api/tipo-cambio
        tcCompra = 3.72;
        tcVenta = 3.78;

        compraEl.textContent = tcCompra.toFixed(2);
        ventaEl.textContent = tcVenta.toFixed(2);

        const hoy = new Date();
        fechaEl.textContent = hoy.toLocaleDateString('es-PE', { day: '2-digit', month: 'short' });
    } catch (error) {
        fechaEl.textContent = 'Error';
        compraEl.textContent = '-';
        ventaEl.textContent = '-';
    }
}

function convertirTC() {
    const usd = parseFloat(document.getElementById('tc-usd')?.value) || 0;
    const pen = usd * tcVenta;
    const el = document.getElementById('tc-resultado');
    if (el) el.textContent = 'S/ ' + pen.toFixed(2);
}

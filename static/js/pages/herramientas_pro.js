// Variables globales para cálculos
let tipoIGV = 'sin'; // 'sin' o 'con'
let tcCompra = 0;
let tcVenta = 0;

// Cambiar tab de herramientas
function cambiarTabHerramientas(tab, btn) {
    // Desactivar todos los tabs
    document.querySelectorAll('.tools-tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tools-panel').forEach(p => p.classList.remove('active'));
    
    // Activar el seleccionado
    btn.classList.add('active');
    document.getElementById('tab-' + tab).classList.add('active');
    
    // Si es tab de cálculos, cargar tipo de cambio
    if (tab === 'calc') {
        cargarTipoCambio();
    }
    
    if (typeof SoundFX !== 'undefined') SoundFX.play('tap');
}

// Calculadora IGV
function setTipoIGV(tipo) {
    tipoIGV = tipo;
    document.getElementById('btn-sin-igv').classList.toggle('active', tipo === 'sin');
    document.getElementById('btn-con-igv').classList.toggle('active', tipo === 'con');
    calcularIGV();
}

function calcularIGV() {
    const monto = parseFloat(document.getElementById('calc-igv-monto').value) || 0;
    let base, igv, total;
    
    if (tipoIGV === 'sin') {
        // Monto es la base, agregar IGV
        base = monto;
        igv = monto * 0.18;
        total = monto + igv;
    } else {
        // Monto incluye IGV, extraer
        total = monto;
        base = monto / 1.18;
        igv = total - base;
    }
    
    document.getElementById('igv-base').textContent = 'S/ ' + base.toFixed(2);
    document.getElementById('igv-monto').textContent = 'S/ ' + igv.toFixed(2);
    document.getElementById('igv-total').textContent = 'S/ ' + total.toFixed(2);
}

// Calculadora Renta 4ta Categoría
function calcularRenta4ta() {
    const monto = parseFloat(document.getElementById('calc-4ta-monto').value) || 0;
    const limiteRetencion = 1500;
    
    let retencion = 0;
    let aplica = 'No';
    let neto = monto;
    
    if (monto > limiteRetencion) {
        retencion = monto * 0.08;
        aplica = 'Sí (8%)';
        neto = monto - retencion;
    }
    
    document.getElementById('renta4ta-retencion').textContent = 'S/ ' + retencion.toFixed(2);
    document.getElementById('renta4ta-aplica').textContent = aplica;
    document.getElementById('renta4ta-aplica').style.color = aplica === 'No' ? '#10b981' : '#f59e0b';
    document.getElementById('renta4ta-neto').textContent = 'S/ ' + neto.toFixed(2);
}

// Cargar Tipo de Cambio (simulado - conectar con API real)
async function cargarTipoCambio() {
    const fechaEl = document.getElementById('tc-fecha');
    const compraEl = document.getElementById('tc-compra');
    const ventaEl = document.getElementById('tc-venta');
    
    fechaEl.textContent = 'Cargando...';
    
    try {
        // API de tipo de cambio SUNAT (usar tu propio endpoint)
        // Por ahora usamos valores aproximados
        // En producción: const res = await fetch('/api/tipo-cambio');
        
        // Valores aproximados (actualizar con API real)
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

// Convertir USD a PEN
function convertirTC() {
    const usd = parseFloat(document.getElementById('tc-usd').value) || 0;
    const pen = usd * tcVenta;
    document.getElementById('tc-resultado').textContent = 'S/ ' + pen.toFixed(2);
}

// Cargar TC cuando se abre el modal
document.getElementById('modal-herramientas')?.addEventListener('open', cargarTipoCambio);
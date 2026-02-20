/**
 * ══════════════════════════════════════════════════════════════
 * CAJA.JS — Sistema de Caja CCPL
 * ══════════════════════════════════════════════════════════════
 * Extraído de caja.html para mejorar mantenibilidad y cache.
 * v7 — Responsive + separación de archivos
 */

/* ══════════════════════════════════════════════════
   ESTADO GLOBAL
   ══════════════════════════════════════════════════ */
const API = '/api/caja';
let colActual = null, deudasDisp = [], conceptosDisp = [];
let catActiva = null, carrito = [], metodo = 'efectivo', tipoComp = '03', formaPago = 'contado';
let tabAct = 'deudas', sesion = null, totalEsperado = 0;
let pdfPollTimer = null, lastPaymentId = null, lastCompNumero = null, lastCompPdfUrl = null;
let ultimaSesionCerrada = null;

// Métodos que requieren N° de operación obligatorio
const METODOS_REQ_REF = ['yape', 'plin', 'transferencia', 'tarjeta'];

// Placeholders por método de pago
const REF_PLACEHOLDERS = {
    yape: 'Nro. operación Yape (obligatorio)',
    plin: 'Nro. operación Plin (obligatorio)',
    transferencia: 'Nro. operación / CCI (obligatorio)',
    tarjeta: 'Nro. voucher / últimos 4 dígitos (obligatorio)',
    deposito: 'Nro. de operación / voucher'
};

/**
 * Truncar número de comprobante: B001-00000042 → B001-42
 */
function fmtNum(num) {
    if (!num) return '';
    return num.replace(/(-)(0+)(\d+)$/, '$1$3');
}

/**
 * Formato de método de pago con ícono
 */
function fmtMetodo(m) {
    const map = {
        efectivo: '💵', yape: '📱', plin: '📱',
        tarjeta: '💳', transferencia: '🏦', deposito: '🧾'
    };
    return `${map[m] || ''} ${(m || '').toUpperCase()}`;
}

/**
 * Badge de estado para comprobantes
 */
function statusBadge(s) {
    const map = {
        accepted: ['Aceptado', 'st-ok'],
        pending: ['Pendiente', 'st-warn'],
        encolado: ['Encolado', 'st-warn'],
        rejected: ['Rechazado', 'st-err'],
        anulado: ['Anulado', 'st-muted'],
        error: ['Error', 'st-err'],
    };
    const [label, cls] = map[s] || ['?', 'st-muted'];
    return `<span class="st-badge ${cls}">${label}</span>`;
}

// Sedes CCPL para geolocalización
const SEDES_CCPL = [
    { nombre: 'Oficina Principal', lat: -3.7486127, lng: -73.2529467, radio: 100 },
    { nombre: 'Centro Recreacional', lat: -3.793031, lng: -73.299236, radio: 100 },
];


/* ══════════════════════════════════════════════════
   INICIALIZACIÓN
   ══════════════════════════════════════════════════ */
document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('geoBlock').classList.remove('active');
    iniciarApp();
    // verificarGeo(); // Desactivado temporalmente

    document.addEventListener('keydown', e => {
        if (e.key === 'F2') {
            e.preventDefault();
            const s = document.getElementById('searchInput');
            s.focus(); s.select();
        }
        if (e.key === 'Escape') {
            cerrarModal(); cerrarModalCierre(); cerrarModalLiq();
            cerrarModalAnular(); cerrarSuccess();
            document.getElementById('searchResults').classList.remove('active');
        }
        if (e.key === 'F9' && carrito.length) {
            e.preventDefault(); confirmarCobro();
        }
    });

    // Limpiar error del ref input al escribir
    document.getElementById('refInput').addEventListener('input', () => {
        document.getElementById('refInput').classList.remove('error');
        document.getElementById('refHint').classList.remove('visible');
    });
});

function iniciarApp() {
    actualizarReloj();
    setInterval(actualizarReloj, 30000);
    verificarSesion();
    cargarCats();
    cargarConceptos();
    document.getElementById('searchInput').focus();
}


/* ══════════════════════════════════════════════════
   GEOLOCALIZACIÓN (desactivada por ahora)
   ══════════════════════════════════════════════════ */
function distanciaMetros(lat1, lon1, lat2, lon2) {
    const R = 6371000;
    const dLat = (lat2 - lat1) * Math.PI / 180;
    const dLon = (lon2 - lon1) * Math.PI / 180;
    const a = Math.sin(dLat / 2) ** 2 + Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * Math.sin(dLon / 2) ** 2;
    return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

/*
function verificarGeo() { ... } // Comentado — activar cuando se requiera
*/


/* ══════════════════════════════════════════════════
   RELOJ + RESUMEN
   ══════════════════════════════════════════════════ */
function actualizarReloj() {
    document.getElementById('horaActual').textContent = new Date().toLocaleTimeString('es-PE', { hour: '2-digit', minute: '2-digit' });
}

async function cargarResumen() {
    try {
        const r = await fetch(`${API}/resumen-dia`);
        const d = await r.json();
        document.getElementById('totalDia').textContent = `S/ ${d.total_cobrado.toFixed(2)}`;
        document.getElementById('opsDia').textContent = d.cantidad_operaciones;
    } catch (e) { /* silencioso */ }
}


/* ══════════════════════════════════════════════════
   SESIÓN DE CAJA (apertura / cierre)
   ══════════════════════════════════════════════════ */
async function verificarSesion() {
    try {
        const r = await fetch(`${API}/sesion-actual?centro_costo_id=1`);
        const d = await r.json();
        if (d.caja_abierta && d.sesion) { sesion = d.sesion; abrirCajaUI(); }
        else { mostrarApertura(); }
    } catch (e) { /* silencioso */ }
    cargarResumen();
}

function mostrarApertura() {
    document.getElementById('aperturaOverlay').classList.add('active');
    document.getElementById('aperturaCentro').innerHTML =
        '<option value="1">Oficina Principal</option>' +
        '<option value="2">Restaurante</option>' +
        '<option value="3">Cafetín</option>' +
        '<option value="4">Hotel</option>' +
        '<option value="5">Bazar / Merchandising</option>' +
        '<option value="6">Centro Recreacional</option>';
    setTimeout(() => {
        document.getElementById('aperturaMontoInput').focus();
        document.getElementById('aperturaMontoInput').select();
    }, 300);
}

async function ejecutarApertura() {
    const m = parseFloat(document.getElementById('aperturaMontoInput').value) || 0;
    const c = parseInt(document.getElementById('aperturaCentro').value) || 1;
    try {
        const r = await fetch(`${API}/abrir-caja`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ monto_apertura: m, centro_costo_id: c })
        });
        const d = await r.json();
        if (d.success) {
            document.getElementById('aperturaOverlay').classList.remove('active');
            toast(d.mensaje, 'ok');
            verificarSesion();
        } else {
            toast(d.detail?.error || d.detail || 'Error', 'err');
        }
    } catch (e) { toast('Error', 'err'); }
}

function abrirCajaUI() {
    document.getElementById('aperturaOverlay').classList.remove('active');
    document.getElementById('sesionIndicator').style.display = 'flex';
    document.getElementById('sesionInfo').textContent = `${sesion.centro_costo} · ${sesion.hora_apertura}`;
    document.getElementById('headerTitle').textContent = `Caja — ${sesion.centro_costo}`;
    document.getElementById('btnCerrar').style.display = 'block';
    document.getElementById('btnEgreso').style.display = 'block';
}


/* ══════════════════════════════════════════════════
   CIERRE DE CAJA
   ══════════════════════════════════════════════════ */
function mostrarCierreCaja() {
    if (!sesion) return;
    fetch(`${API}/sesion-actual?centro_costo_id=${sesion.centro_costo_id || 1}`)
        .then(r => r.json())
        .then(d => {
            if (!d.sesion) return;
            sesion = d.sesion;
            totalEsperado = sesion.total_esperado;
            document.getElementById('cierreResumen').innerHTML = `
                <div class="c-row"><span>Apertura</span><span class="cmonto">S/ ${sesion.monto_apertura.toFixed(2)}</span></div>
                <div class="c-row"><span>Cobros efectivo</span><span class="cmonto" style="color:var(--green)">+ S/ ${sesion.total_cobros_efectivo.toFixed(2)}</span></div>
                <div class="c-row"><span>Cobros digitales</span><span class="cmonto" style="color:var(--accent)">S/ ${sesion.total_cobros_digital.toFixed(2)}</span></div>
                <div class="c-row"><span>Egresos (neto)</span><span class="cmonto" style="color:var(--red)">- S/ ${sesion.total_egresos.toFixed(2)}</span></div>
                <div class="c-row"><span>Operaciones</span><span class="cmonto">${sesion.cantidad_operaciones}</span></div>
                <div class="c-row total"><span>Esperado en caja</span><span class="cmonto" style="color:var(--green)">S/ ${sesion.total_esperado.toFixed(2)}</span></div>`;
            document.getElementById('cierreMontoInput').value = '';
            document.getElementById('cierreDiff').style.display = 'none';
            document.getElementById('cierreObsCont').style.display = 'none';
            document.getElementById('modalCierre').classList.add('active');
            document.getElementById('cierreMontoInput').focus();
        });
}

function calcDiff() {
    const v = parseFloat(document.getElementById('cierreMontoInput').value);
    const el = document.getElementById('cierreDiff');
    if (isNaN(v)) { el.style.display = 'none'; document.getElementById('cierreObsCont').style.display = 'none'; return; }
    const d = v - totalEsperado;
    el.style.display = 'block';
    if (Math.abs(d) < 0.01) {
        el.className = 'c-diff ok'; el.textContent = '✓ Caja cuadrada';
        document.getElementById('cierreObsCont').style.display = 'none';
    } else if (d > 0) {
        el.className = 'c-diff over'; el.textContent = `Sobrante: + S/ ${d.toFixed(2)}`;
        document.getElementById('cierreObsCont').style.display = Math.abs(d) > 50 ? 'block' : 'none';
    } else {
        el.className = 'c-diff under'; el.textContent = `Faltante: - S/ ${Math.abs(d).toFixed(2)}`;
        document.getElementById('cierreObsCont').style.display = Math.abs(d) > 50 ? 'block' : 'none';
    }
}

function cerrarModalCierre() {
    document.getElementById('modalCierre').classList.remove('active');
}

async function ejecutarCierre() {
    const m = parseFloat(document.getElementById('cierreMontoInput').value);
    if (isNaN(m)) { toast('Ingresa monto', 'err'); return; }
    const obs = document.getElementById('cierreObsInput').value.trim();
    if (Math.abs(m - totalEsperado) > 50 && !obs) { toast('Dif >S/50: observación obligatoria', 'err'); return; }
    try {
        const r = await fetch(`${API}/cerrar-caja/${sesion.id}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ monto_cierre: m, observaciones: obs || null })
        });
        const d = await r.json();
        if (d.success) {
            cerrarModalCierre();
            // Mostrar modal de cierre exitoso si hay resumen
            if (d.resumen) {
                mostrarCierreExitoso(sesion.id, d.resumen, d.mensaje);
            } else {
                toast(d.mensaje, 'ok');
            }
            sesion = null;
            document.getElementById('sesionIndicator').style.display = 'none';
            document.getElementById('btnCerrar').style.display = 'none';
            document.getElementById('btnEgreso').style.display = 'none';
            if (!d.resumen) setTimeout(() => mostrarApertura(), 1500);
        } else {
            toast(d.detail || 'Error', 'err');
        }
    } catch (e) { toast('Error', 'err'); }
}

function mostrarCierreExitoso(sesionId, resumen, mensaje) {
    ultimaSesionCerrada = sesionId;
    const dif = resumen.diferencia || 0;
    const difColor = Math.abs(dif) < 0.01 ? 'var(--green)' : (dif < 0 ? 'var(--red)' : 'var(--yellow)');
    const difIcon = Math.abs(dif) < 0.01 ? '✓ Cuadra' : (dif < 0 ? '⚠ Faltante' : '⚠ Sobrante');

    document.getElementById('cierreResumenBox').innerHTML = `
        <div style="display:flex;justify-content:space-between;"><span style="color:var(--text-sec);">Apertura</span><span>S/ ${(resumen.monto_apertura || 0).toFixed(2)}</span></div>
        <div style="display:flex;justify-content:space-between;"><span style="color:var(--text-sec);">(+) Efectivo</span><span>S/ ${(resumen.total_cobros_efectivo || 0).toFixed(2)}</span></div>
        <div style="display:flex;justify-content:space-between;"><span style="color:var(--text-sec);">(+) Digital</span><span>S/ ${(resumen.total_cobros_digital || 0).toFixed(2)}</span></div>
        <div style="display:flex;justify-content:space-between;"><span style="color:var(--text-sec);">(-) Egresos</span><span>S/ ${(resumen.total_egresos || 0).toFixed(2)}</span></div>
        <hr style="border:none;border-top:1px solid var(--border);margin:8px 0;">
        <div style="display:flex;justify-content:space-between;"><span style="font-weight:600;">Esperado</span><span style="font-weight:600;">S/ ${(resumen.total_esperado || 0).toFixed(2)}</span></div>
        <div style="display:flex;justify-content:space-between;"><span style="color:var(--text-sec);">Declarado</span><span>S/ ${(resumen.monto_cierre || 0).toFixed(2)}</span></div>
        <hr style="border:none;border-top:1px solid var(--border);margin:8px 0;">
        <div style="display:flex;justify-content:space-between;font-size:15px;font-weight:700;">
            <span>Diferencia</span>
            <span style="color:${difColor};">${dif >= 0 ? '+' : ''}${dif.toFixed(2)} ${difIcon}</span>
        </div>
        <div style="text-align:center;margin-top:8px;font-size:11px;color:var(--text-sec);">${resumen.cantidad_operaciones || 0} operaciones</div>`;

    document.getElementById('modalCierreExitoso').style.display = 'flex';
}

function descargarPDFCierre() {
    if (ultimaSesionCerrada) {
        const url = `/api/caja/cierre-caja/${ultimaSesionCerrada}/pdf`;
        const win = window.open(url, '_blank');
        if (!win || win.closed) {
            const a = document.createElement('a');
            a.href = url; a.target = '_blank'; a.click();
        }
    }
}

function cerrarModalCierreExitoso() {
    document.getElementById('modalCierreExitoso').style.display = 'none';
    location.reload();
}


/* ══════════════════════════════════════════════════
   BÚSQUEDA DE COLEGIADOS
   ══════════════════════════════════════════════════ */
let sT;
document.addEventListener('DOMContentLoaded', () => {
    const searchInput = document.getElementById('searchInput');
    if (searchInput) {
        searchInput.addEventListener('input', e => {
            clearTimeout(sT);
            const q = e.target.value.trim();
            if (q.length < 2) { document.getElementById('searchResults').classList.remove('active'); return; }
            sT = setTimeout(() => buscar(q), 300);
        });
        searchInput.addEventListener('focus', e => {
            if (e.target.value.trim().length >= 2) document.getElementById('searchResults').classList.add('active');
        });
    }
    document.addEventListener('click', e => {
        if (!e.target.closest('.search-card')) document.getElementById('searchResults').classList.remove('active');
    });
});

async function buscar(q) {
    try {
        const r = await fetch(`${API}/buscar-colegiado?q=${encodeURIComponent(q)}`);
        renderRes(await r.json());
    } catch (e) { toast('Error', 'err'); }
}

function renderRes(arr) {
    const c = document.getElementById('searchResults');
    if (!arr.length) {
        c.innerHTML = '<div style="padding:12px;color:var(--text-muted);text-align:center;font-size:11px;">Sin resultados</div>';
        c.classList.add('active'); return;
    }
    c.innerHTML = arr.map(r => `<div class="search-result-item" onclick='selCol(${JSON.stringify(r)})'>
        <div class="result-info"><div class="result-name">${r.apellidos_nombres}</div>
        <div class="result-meta">DNI ${r.dni} · Mat. ${r.codigo_matricula || '-'}
        <span class="badge badge-${r.habilitado ? 'ok' : 'no'}">${r.habilitado ? 'HÁBIL' : 'INHÁBIL'}</span></div></div>
        <div class="result-deuda ${r.total_deuda > 0 ? 'tiene' : 'no-tiene'}">${r.total_deuda > 0 ? `S/ ${r.total_deuda.toFixed(2)}` : 'Al día ✓'}</div>
    </div>`).join('');
    c.classList.add('active');
}

function selCol(col) {
    colActual = col;
    document.getElementById('searchResults').classList.remove('active');
    document.getElementById('searchInput').value = '';
    document.getElementById('colCard').classList.add('active');
    document.getElementById('colAvatar').textContent = col.apellidos_nombres.split(' ').slice(0, 2).map(n => n[0]).join('');
    document.getElementById('colName').textContent = col.apellidos_nombres;
    document.getElementById('colDetail').textContent = `DNI ${col.dni} · Mat. ${col.codigo_matricula || '-'} · Deuda: S/ ${col.total_deuda.toFixed(2)}`;
    const b = document.getElementById('colBadge');
    b.textContent = col.habilitado ? 'HÁBIL' : 'INHÁBIL';
    b.className = `badge badge-${col.habilitado ? 'ok' : 'no'}`;
    cargarDeudas(col.id);
    cambiarTab('deudas');

    // ← AÑADIR ESTA LÍNEA:
    if (!col.habilitado) setTimeout(() => abrirModalInhabil(col), 200);
}

function limpiarCol() {
    cerrarModalInhabil();
    colActual = null; deudasDisp = [];
    document.getElementById('colCard').classList.remove('active');
    document.getElementById('panelDeudas').innerHTML = '<div class="empty"><div class="empty-icon">📋</div><div class="empty-title">Busca un colegiado</div><div class="empty-desc">DNI, matrícula o nombre</div></div>';
    document.getElementById('cntDeudas').textContent = '0';
    carrito = carrito.filter(i => i.tipo !== 'deuda');
    renderCarrito();
    document.getElementById('searchInput').focus();

    // ← AÑADIR ESTA LÍNEA:
    limpiarSituacion();
}


/* ══════════════════════════════════════════════════
   DEUDAS
   ══════════════════════════════════════════════════ */
async function cargarDeudas(id) {
    try {
        const r = await fetch(`${API}/deudas/${id}`);
        const d = await r.json();
        deudasDisp = d.deudas || [];
        renderDeudas();
    } catch (e) { toast('Error', 'err'); }
}

function renderDeudas() {
    const p = document.getElementById('panelDeudas');
    document.getElementById('cntDeudas').textContent = deudasDisp.length;
    if (!deudasDisp.length) {
        p.innerHTML = '<div class="empty"><div class="empty-icon">✅</div><div class="empty-title">Sin deudas pendientes</div></div>';
        return;
    }
    const sel = carrito.filter(i => i.tipo === 'deuda').map(i => i.deuda_id);
    p.innerHTML = `<div class="section-box red"><div class="sec-title red">📋 Deudas pendientes</div>
        <button class="btn-sel-all" onclick="selTodas()">Seleccionar todas (${deudasDisp.length})</button>
        ${deudasDisp.map(d => `<div class="deuda-row ${sel.includes(d.id) ? 'selected' : ''}" onclick="togDeuda(${d.id})">
            <div class="d-check">${sel.includes(d.id) ? '✓' : ''}</div>
            <div class="d-info"><div class="d-concepto">${d.concepto}</div><div class="d-periodo">${d.periodo || ''} ${d.fecha_vencimiento ? '· Vence: ' + d.fecha_vencimiento : ''}</div></div>
            <div class="d-monto">S/ ${d.saldo.toFixed(2)}</div>
        </div>`).join('')}</div>`;
}

function togDeuda(id) {
    const i = carrito.findIndex(x => x.tipo === 'deuda' && x.deuda_id === id);
    if (i >= 0) carrito.splice(i, 1);
    else {
        const d = deudasDisp.find(x => x.id === id);
        if (d) carrito.push({ tipo: 'deuda', deuda_id: d.id, descripcion: `${d.concepto} ${d.periodo || ''}`.trim(), monto: d.saldo });
    }
    renderDeudas(); renderCarrito();
}

function selTodas() {
    carrito = carrito.filter(i => i.tipo !== 'deuda');
    deudasDisp.forEach(d => carrito.push({ tipo: 'deuda', deuda_id: d.id, descripcion: `${d.concepto} ${d.periodo || ''}`.trim(), monto: d.saldo }));
    renderDeudas(); renderCarrito();
}


/* ══════════════════════════════════════════════════
   CATÁLOGO DE CONCEPTOS
   ══════════════════════════════════════════════════ */
async function cargarCats() {
    try {
        const r = await fetch(`${API}/categorias`);
        const c = await r.json();
        document.getElementById('catsGrid').innerHTML =
            `<span class="cat-chip active" onclick="filtCat(null,this)">Todos</span>` +
            c.map(x => `<span class="cat-chip" onclick="filtCat('${x.codigo}',this)">${x.nombre} (${x.total})</span>`).join('');
    } catch (e) { /* silencioso */ }
}

async function cargarConceptos(cat) {
    try {
        let u = `${API}/conceptos`;
        if (cat) u += `?categoria=${cat}`;
        const r = await fetch(u);
        conceptosDisp = await r.json();
        document.getElementById('cntConceptos').textContent = conceptosDisp.length;
        renderConc();
    } catch (e) { /* silencioso */ }
}

function filtCat(c, el) {
    catActiva = c;
    document.querySelectorAll('.cat-chip').forEach(x => x.classList.remove('active'));
    if (el) el.classList.add('active');
    cargarConceptos(c);
}

function renderConc() {
    document.getElementById('concLista').innerHTML = conceptosDisp.map(c => `<div class="concepto-row" onclick="addConc(${c.id})">
        <div><div class="c-nombre">${c.nombre_corto || c.nombre}</div><div class="c-cat">${c.categoria}${c.maneja_stock ? ` · Stock: ${c.stock_actual}` : ''}</div></div>
        <div class="c-precio">${c.monto_base > 0 ? `S/ ${c.monto_base.toFixed(2)}` : 'Variable'}</div>
    </div>`).join('');
}

function addConc(id) {
    const c = conceptosDisp.find(x => x.id === id);
    if (!c) return;
    if (c.requiere_colegiado && !colActual) { toast('Selecciona un colegiado', 'err'); return; }
    let m = c.monto_base;
    if (c.permite_monto_libre || m === 0) {
        const i = prompt(`Monto para "${c.nombre}":`, m > 0 ? m : '');
        if (!i) return;
        m = parseFloat(i);
        if (isNaN(m) || m <= 0) { toast('Monto inválido', 'err'); return; }
    }
    carrito.push({ tipo: 'concepto', concepto_id: c.id, descripcion: c.nombre_corto || c.nombre, cantidad: 1, monto_unitario: m, monto: m });
    renderCarrito();
    toast(`${c.nombre_corto || c.nombre} agregado`, 'ok');
}


/* ══════════════════════════════════════════════════
   CARRITO
   ══════════════════════════════════════════════════ */
function renderCarrito() {
    const t = carrito.reduce((s, i) => s + i.monto, 0);
    document.getElementById('cartCnt').textContent = carrito.length;
    document.getElementById('cartTot').textContent = t.toFixed(2);
    document.getElementById('btnMonto').textContent = `S/ ${t.toFixed(2)}`;
    document.getElementById('btnCobrar').disabled = !carrito.length;
    const fb = document.getElementById('fabBadge');
    if (carrito.length) { fb.style.display = 'block'; fb.textContent = carrito.length; }
    else fb.style.display = 'none';
    if (!carrito.length) {
        document.getElementById('cartBody').innerHTML = '<div class="cart-empty"><div class="cart-empty-icon">🛒</div>Selecciona deudas o conceptos<br>para agregar al cobro</div>';
        return;
    }
    document.getElementById('cartBody').innerHTML = carrito.map((x, i) => `<div class="cart-item">
        <div class="ci-info"><div class="ci-name">${x.descripcion}</div><div class="ci-type">${x.tipo === 'deuda' ? 'Deuda' : 'Concepto'}</div></div>
        <div class="ci-amt">S/ ${x.monto.toFixed(2)}</div>
        <button class="ci-rm" onclick="rmItem(${i})">✕</button>
    </div>`).join('');
}

function rmItem(i) {
    const x = carrito[i];
    carrito.splice(i, 1);
    if (x.tipo === 'deuda') renderDeudas();
    renderCarrito();
}

function toggleCart() {
    document.getElementById('panelRight').classList.toggle('open');
}


/* ══════════════════════════════════════════════════
   MÉTODO DE PAGO / COMPROBANTE / FORMA PAGO
   ══════════════════════════════════════════════════ */
function requiereReferencia(m) { return METODOS_REQ_REF.includes(m); }

function setMetodo(m) {
    metodo = m;
    document.querySelectorAll('.m-btn').forEach(b => b.classList.toggle('active', b.dataset.m === m));
    const r = document.getElementById('refInput');
    const hint = document.getElementById('refHint');
    r.classList.remove('error');
    hint.classList.remove('visible');
    if (m !== 'efectivo') {
        r.classList.add('visible');
        r.placeholder = REF_PLACEHOLDERS[m] || 'Nro. de operación / voucher';
        r.focus();
    } else {
        r.classList.remove('visible');
        r.value = '';
    }
}

function setComp(t) {
    tipoComp = t;
    document.querySelectorAll('.comp-btn').forEach(b => b.classList.toggle('active', b.dataset.c === t));
    const ff = document.getElementById('facturaFields');
    if (t === '01') {
        ff.classList.add('active');
        document.getElementById('ffRuc').focus();
    } else {
        ff.classList.remove('active');
    }
}

function setFormaPago(fp) {
    formaPago = fp;
    document.querySelectorAll('.pago-btn').forEach(b => b.classList.toggle('active', b.dataset.fp === fp));
}

async function buscarRuc() {
    const ruc = document.getElementById('ffRuc').value.trim();
    if (ruc.length !== 11) { toast('RUC debe tener 11 dígitos', 'err'); return; }
    const btn = document.getElementById('ffBuscarRuc');
    btn.disabled = true; btn.textContent = '⏳';
    try {
        const r = await fetch(`${API}/consulta-ruc/${ruc}`);
        if (r.ok) {
            const d = await r.json();
            if (d.razon_social) {
                document.getElementById('ffRazonSocial').value = d.razon_social;
                document.getElementById('ffDireccion').value = d.direccion || '';
                toast('RUC encontrado', 'ok');
            } else { toast('RUC no encontrado', 'err'); }
        } else { toast('Error consultando RUC', 'err'); }
    } catch (e) { toast('Error de conexión', 'err'); }
    btn.disabled = false; btn.textContent = '🔍 Buscar';
}


/* ══════════════════════════════════════════════════
   TABS
   ══════════════════════════════════════════════════ */
function cambiarTab(t) {
    tabAct = t;
    document.querySelectorAll('.tab').forEach(b => b.classList.toggle('active', b.dataset.t === t));
    document.getElementById('panelDeudas').style.display = t === 'deudas' ? 'block' : 'none';
    document.getElementById('panelCatalogo').style.display = t === 'catalogo' ? 'block' : 'none';
    document.getElementById('panelEgresos').style.display = t === 'egresos' ? 'block' : 'none';
    document.getElementById('panelHistorial').style.display = t === 'historial' ? 'block' : 'none';
    document.getElementById('panelComprobantes').style.display = t === 'comprobantes' ? 'block' : 'none';
    if (t === 'egresos') cargarEgresos();
    if (t === 'historial') {
        if (!document.getElementById('histFecha').value) {
            const ah = new Date();
            ah.setMinutes(ah.getMinutes() - ah.getTimezoneOffset() - 300);
            document.getElementById('histFecha').value = ah.toISOString().split('T')[0];
        }
        cargarHistorial();
    }
    if (t === 'comprobantes' && !document.getElementById('compLista').querySelector('.comp-row')) {
        buscarComprobantes();
    }
}


/* ══════════════════════════════════════════════════
   COBRO — Confirmar / Ejecutar
   ══════════════════════════════════════════════════ */
function confirmarCobro() {
    if (!carrito.length) return;

    // Validar N° operación obligatorio
    if (requiereReferencia(metodo)) {
        const ref = document.getElementById('refInput').value.trim();
        if (!ref) {
            const refEl = document.getElementById('refInput');
            const hintEl = document.getElementById('refHint');
            refEl.classList.add('error');
            hintEl.classList.add('visible');
            refEl.focus();
            toast(`Ingresa el N° de operación para ${metodo.charAt(0).toUpperCase() + metodo.slice(1)}`, 'err');
            return;
        }
    }

    // Validar datos de Factura
    if (tipoComp === '01') {
        const ruc = document.getElementById('ffRuc').value.trim();
        const razon = document.getElementById('ffRazonSocial').value.trim();
        if (!ruc || ruc.length !== 11) {
            document.getElementById('ffRuc').classList.add('error');
            document.getElementById('ffRuc').focus();
            toast('Ingresa un RUC válido (11 dígitos)', 'err');
            return;
        }
        document.getElementById('ffRuc').classList.remove('error');
        if (!razon) {
            document.getElementById('ffRazonSocial').classList.add('error');
            document.getElementById('ffRazonSocial').focus();
            toast('Ingresa la Razón Social', 'err');
            return;
        }
        document.getElementById('ffRazonSocial').classList.remove('error');
    }

    const t = carrito.reduce((s, i) => s + i.monto, 0);
    const ref = document.getElementById('refInput').value.trim();
    const fpLabel = formaPago === 'credito' ? '📅 Crédito' : '💵 Contado';
    let clienteLabel = colActual ? colActual.apellidos_nombres : 'Público general';
    if (tipoComp === '01') {
        clienteLabel = document.getElementById('ffRazonSocial').value.trim() + ' (RUC: ' + document.getElementById('ffRuc').value.trim() + ')';
    }
    document.getElementById('mTotal').textContent = `S/ ${t.toFixed(2)}`;
    document.getElementById('mDetail').innerHTML = `
        <div><span>Cliente:</span><span>${clienteLabel}</span></div>
        <div><span>Items:</span><span>${carrito.length}</span></div>
        <div><span>Método:</span><span>${metodo}${ref ? ' · Op: ' + ref : ''}</span></div>
        <div><span>Comprobante:</span><span>${tipoComp === '01' ? 'Factura' : 'Boleta'} · ${fpLabel}</span></div>`;
    document.getElementById('modalConfirm').classList.add('active');
}

function cerrarModal() {
    document.getElementById('modalConfirm').classList.remove('active');
}

async function ejecutarCobro() {
    cerrarModal();
    const total = carrito.reduce((s, i) => s + i.monto, 0);
    const ref = document.getElementById('refInput').value.trim();
    const payload = {
        colegiado_id: colActual?.id || null,
        items: carrito.map(i => ({
            tipo: i.tipo, deuda_id: i.deuda_id || null, concepto_id: i.concepto_id || null,
            descripcion: i.descripcion, cantidad: i.cantidad || 1,
            monto_unitario: i.monto_unitario || i.monto, monto_total: i.monto
        })),
        total, metodo_pago: metodo, referencia_pago: ref || null,
        tipo_comprobante: tipoComp, forma_pago: formaPago
    };
    if (tipoComp === '01') {
        payload.cliente_ruc = document.getElementById('ffRuc').value.trim();
        payload.cliente_razon_social = document.getElementById('ffRazonSocial').value.trim();
        payload.cliente_direccion = document.getElementById('ffDireccion').value.trim();
    }
    try {
        const r = await fetch(`${API}/cobrar`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
        const d = await r.json();
        if (d.success) {
            document.getElementById('successAmt').textContent = `S/ ${total.toFixed(2)}`;
            document.getElementById('successRef').textContent = `${metodo.toUpperCase()} ${ref ? '· Op: ' + ref : ''} · ${colActual?.apellidos_nombres || 'Público general'}`;

            const compEl = document.getElementById('successComp');
            const compNum = document.getElementById('successCompNum');
            const compLoading = document.getElementById('successCompLoading');
            const compActions = document.getElementById('successActions');
            const compPdf = document.getElementById('successCompPdf');
            const compErr = document.getElementById('successCompErr');
            compErr.textContent = '';
            lastCompPdfUrl = null;
            lastPaymentId = d.payment_id || null;

            if (d.comprobante_numero) {
                lastCompNumero = d.comprobante_numero;
                compNum.textContent = '📄 ' + d.comprobante_numero;
                compEl.classList.add('active');
                if (d.comprobante_pdf && lastPaymentId) {
                    const proxyUrl = `${API}/comprobante/${lastPaymentId}/pdf`;
                    lastCompPdfUrl = proxyUrl;
                    compPdf.href = proxyUrl;
                    compLoading.style.display = 'none';
                    compActions.style.display = 'flex';
                } else if (lastPaymentId) {
                    compLoading.style.display = 'flex';
                    compActions.style.display = 'none';
                    startPdfPolling(lastPaymentId);
                }
            } else {
                compEl.classList.remove('active');
                if (!d.comprobante_emitido && d.comprobante_mensaje) {
                    compErr.textContent = d.comprobante_mensaje;
                    compEl.classList.add('active');
                    compLoading.style.display = 'none';
                    compActions.style.display = 'none';
                }
            }

            document.getElementById('successBg').classList.add('active');
            carrito = []; renderCarrito();
            if (colActual) cargarDeudas(colActual.id);
            cargarResumen();

            // Limpiar campos
            document.getElementById('refInput').value = '';
            document.getElementById('refInput').classList.remove('error');
            document.getElementById('refHint').classList.remove('visible');
            document.getElementById('ffRuc').value = '';
            document.getElementById('ffRazonSocial').value = '';
            document.getElementById('ffDireccion').value = '';
            setComp('03');
            setFormaPago('contado');

            if (!d.comprobante_numero) { setTimeout(cerrarSuccess, 2500); }
        } else {
            toast(d.detail || 'Error', 'err');
        }
    } catch (e) { toast('Error', 'err'); }
}

function cerrarSuccess() {
    stopPdfPolling();
    document.getElementById('successBg').classList.remove('active');
    document.getElementById('successComp').classList.remove('active');
    document.getElementById('successActions').style.display = 'none';
    document.getElementById('successCompLoading').style.display = 'none';
    document.getElementById('searchInput').focus();
}

document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('successBg')?.addEventListener('click', e => {
        if (e.target.closest('.success-action-btn')) return;
        cerrarSuccess();
    });
});


/* ══════════════════════════════════════════════════
   POLLING PDF
   ══════════════════════════════════════════════════ */
function startPdfPolling(paymentId) {
    stopPdfPolling();
    let intentos = 0;
    const maxIntentos = 15;
    pdfPollTimer = setInterval(async () => {
        intentos++;
        try {
            const r = await fetch(`${API}/comprobante/${paymentId}`);
            if (r.ok) {
                const d = await r.json();
                if (d.pdf_url) {
                    lastCompPdfUrl = d.pdf_url;
                    document.getElementById('successCompPdf').href = d.pdf_url;
                    document.getElementById('successCompLoading').style.display = 'none';
                    document.getElementById('successActions').style.display = 'flex';
                    stopPdfPolling();
                    return;
                }
            }
        } catch (e) { /* silencioso */ }
        if (intentos >= maxIntentos) {
            stopPdfPolling();
            document.getElementById('successCompLoading').innerHTML = '⚠ PDF en proceso. Revisa en Historial.';
        }
    }, 2000);
}

function stopPdfPolling() {
    if (pdfPollTimer) { clearInterval(pdfPollTimer); pdfPollTimer = null; }
}


/* ══════════════════════════════════════════════════
   COMPARTIR COMPROBANTE
   ══════════════════════════════════════════════════ */
async function compartirComprobante() {
    const numero = lastCompNumero || 'Comprobante';
    const pdfUrl = lastCompPdfUrl;
    const texto = `${numero} — CCPL\nTotal: ${document.getElementById('successAmt').textContent}\n${pdfUrl || ''}`;
    if (navigator.share && pdfUrl) {
        try { await navigator.share({ title: numero, text: texto, url: pdfUrl }); return; }
        catch (e) { /* usuario canceló */ }
    }
    try {
        await navigator.clipboard.writeText(pdfUrl || texto);
        toast('Link copiado al portapapeles', 'ok');
    } catch (e) {
        const ta = document.createElement('textarea');
        ta.value = pdfUrl || texto;
        document.body.appendChild(ta); ta.select();
        document.execCommand('copy'); document.body.removeChild(ta);
        toast('Link copiado', 'ok');
    }
}

async function verComprobante(paymentId) {
    window.open(`${API}/comprobante/${paymentId}/pdf`, '_blank');
}


/* ══════════════════════════════════════════════════
   EGRESOS
   ══════════════════════════════════════════════════ */
async function cargarEgresos() {
    try {
        const r = await fetch(`${API}/egresos-actual?centro_costo_id=1`);
        renderEgr(await r.json());
    } catch (e) { /* silencioso */ }
}

function renderEgr(data) {
    const { egresos, totales } = data;
    document.getElementById('cntEgresos').textContent = egresos.length;
    const s = document.getElementById('egrSummary');
    if (egresos.length) {
        s.style.display = 'block';
        document.getElementById('egrTotEnt').textContent = `S/ ${totales.entregado.toFixed(2)}`;
        document.getElementById('egrTotFact').textContent = `S/ ${totales.facturado.toFixed(2)}`;
        document.getElementById('egrTotDev').textContent = `S/ ${totales.devuelto.toFixed(2)}`;
        const pr = document.getElementById('egrPendRow');
        if (totales.pendientes > 0) { pr.style.display = 'flex'; document.getElementById('egrPend').textContent = totales.pendientes; }
        else pr.style.display = 'none';
    } else s.style.display = 'none';

    const tl = { gasto: '🛒 Gasto', devolucion: '↩️ Devolución', retiro_fondo: '🏦 Retiro' };
    const l = document.getElementById('egrLista');
    if (!egresos.length) {
        l.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text-muted);font-size:11px;">Sin egresos en esta sesión</div>';
        return;
    }
    l.innerHTML = egresos.map(e => `<div class="egr-item ${e.estado}">
        <div class="egr-item-top"><div class="egr-item-concepto">${e.concepto}</div><div class="egr-item-monto">- S/ ${e.monto.toFixed(2)}</div></div>
        <div class="egr-item-meta"><span>👤 ${e.responsable}</span><span>🕐 ${e.hora}</span><span>${tl[e.tipo] || e.tipo}</span>
        <span class="egr-badge ${e.estado}">${e.estado === 'pendiente' ? '⏳ Pendiente' : '✓ Liquidado'}</span></div>
        ${e.estado === 'liquidado'
            ? `<div class="egr-liq-detail"><div><span>Factura${e.numero_documento ? ' (' + e.numero_documento + ')' : ''}:</span><span class="mono">S/ ${(e.monto_factura ?? 0).toFixed(2)}</span></div>${e.monto_devuelto > 0 ? `<div><span>Vuelto a caja:</span><span class="mono" style="color:var(--green)">+ S/ ${e.monto_devuelto.toFixed(2)}</span></div>` : ''}</div>`
            : `<button class="btn-liquidar" onclick="abrirLiq(${e.id},${e.monto},'${e.concepto.replace(/'/g, "\\'")}','${e.responsable.replace(/'/g, "\\'")}')">📄 Liquidar (trajo factura)</button>`}
    </div>`).join('');
}

async function registrarEgreso() {
    const m = parseFloat(document.getElementById('eMonto').value),
        resp = document.getElementById('eResp').value.trim(),
        conc = document.getElementById('eConc').value.trim(),
        det = document.getElementById('eDet').value.trim(),
        tipo = document.getElementById('eTipo').value;
    if (!m || m <= 0) { toast('Ingresa monto', 'err'); return; }
    if (!resp) { toast('Ingresa responsable', 'err'); return; }
    if (!conc) { toast('Ingresa concepto', 'err'); return; }
    try {
        const r = await fetch(`${API}/egreso?centro_costo_id=1`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ monto: m, responsable: resp, concepto: conc, detalle: det || null, tipo })
        });
        const d = await r.json();
        if (d.success) {
            toast(d.mensaje, 'ok');
            ['eMonto', 'eResp', 'eConc', 'eDet'].forEach(x => document.getElementById(x).value = '');
            document.getElementById('eTipo').value = 'gasto';
            cargarEgresos();
        } else toast(d.detail || 'Error', 'err');
    } catch (e) { toast('Error', 'err'); }
}


/* ══════════════════════════════════════════════════
   LIQUIDAR EGRESO
   ══════════════════════════════════════════════════ */
function abrirLiq(id, monto, concepto, responsable) {
    document.getElementById('liqId').value = id;
    document.getElementById('liqOriginal').value = monto;
    document.getElementById('liqInfo').innerHTML = `<strong>${concepto}</strong><br>Responsable: ${responsable}<br>Entregado: <strong>S/ ${monto.toFixed(2)}</strong>`;
    document.getElementById('liqFactura').value = '';
    document.getElementById('liqNroDoc').value = '';
    document.getElementById('liqVuelto').style.display = 'none';
    document.getElementById('modalLiquidar').classList.add('active');
    document.getElementById('liqFactura').focus();
}

function calcVuelto() {
    const o = parseFloat(document.getElementById('liqOriginal').value) || 0;
    const f = parseFloat(document.getElementById('liqFactura').value);
    const el = document.getElementById('liqVuelto');
    if (isNaN(f)) { el.style.display = 'none'; return; }
    const v = o - f;
    el.style.display = 'block';
    if (v > 0) { el.className = 'c-diff over'; el.textContent = `Vuelto a caja: + S/ ${v.toFixed(2)}`; }
    else if (v === 0) { el.className = 'c-diff ok'; el.textContent = '✓ Monto exacto'; }
    else { el.className = 'c-diff under'; el.textContent = '⚠ Factura mayor al entregado'; }
}

function cerrarModalLiq() { document.getElementById('modalLiquidar').classList.remove('active'); }

async function ejecutarLiq() {
    const id = document.getElementById('liqId').value;
    const mf = parseFloat(document.getElementById('liqFactura').value);
    const nd = document.getElementById('liqNroDoc').value.trim();
    if (isNaN(mf) || mf < 0) { toast('Ingresa monto factura', 'err'); return; }
    try {
        const r = await fetch(`${API}/egreso/${id}/liquidar`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ monto_factura: mf, numero_documento: nd || null })
        });
        const d = await r.json();
        if (d.success) { cerrarModalLiq(); toast(d.mensaje, 'ok'); cargarEgresos(); }
        else toast(d.detail || 'Error', 'err');
    } catch (e) { toast('Error', 'err'); }
}


/* ══════════════════════════════════════════════════
   HISTORIAL
   ══════════════════════════════════════════════════ */
async function cargarHistorial() {
    const fecha = document.getElementById('histFecha').value;
    const tipo = document.getElementById('histTipo').value;
    if (!fecha) return;
    try {
        let url = `${API}/historial-cobros?fecha=${fecha}`;
        if (tipo) url += `&metodo_pago=${tipo}`;
        const r = await fetch(url);
        renderHistorial(await r.json());
    } catch (e) {
        document.getElementById('histLista').innerHTML = '<div class="hist-empty">Error cargando historial</div>';
    }
}

function renderHistorial(data) {
    const ops = data.operaciones || data.cobros || data || [];
    const lista = document.getElementById('histLista');
    const summ = document.getElementById('histSummary');

    if (ops.length) {
        const activos = ops.filter(o => o.status !== 'anulado' && o.status !== 'refunded');
        const anulados = ops.length - activos.length;
        const totalEfect = activos.filter(o => o.metodo_pago === 'efectivo').reduce((s, o) => s + (o.amount || o.total || 0), 0);
        const totalDigit = activos.filter(o => o.metodo_pago !== 'efectivo').reduce((s, o) => s + (o.amount || o.total || 0), 0);
        const totalGen = activos.reduce((s, o) => s + (o.amount || o.total || 0), 0);
        summ.innerHTML = `
            <span class="ss-item"><span class="ss-lbl">Ops</span><span class="ss-val">${activos.length}${anulados ? `<span style="color:var(--red)">(-${anulados})</span>` : ''}</span></span>
            <span class="ss-sep"></span>
            <span class="ss-item"><span class="ss-lbl">Total</span><span class="ss-val green">S/ ${totalGen.toFixed(2)}</span></span>
            <span class="ss-sep"></span>
            <span class="ss-item"><span class="ss-lbl">Efectivo</span><span class="ss-val">S/ ${totalEfect.toFixed(2)}</span></span>
            <span class="ss-sep"></span>
            <span class="ss-item"><span class="ss-lbl">Digital</span><span class="ss-val accent">S/ ${totalDigit.toFixed(2)}</span></span>`;
    } else { summ.innerHTML = ''; }

    if (!ops.length) { lista.innerHTML = '<div class="hist-empty">Sin operaciones en esta fecha</div>'; return; }

    lista.innerHTML = ops.map(o => {
        const hora = o.reviewed_at ? new Date(o.reviewed_at).toLocaleTimeString('es-PE', { hour: '2-digit', minute: '2-digit' }) : (o.hora || '--:--');
        const monto = o.amount || o.total || 0;
        const desc = o.notes || o.descripcion || 'Cobro';
        const compNum = o.numero_comprobante || o.comprobante_numero || '';
        const compCorto = fmtNum(compNum);
        const esAnulado = o.status === 'anulado' || o.status === 'refunded';
        const met = o.metodo_pago || o.payment_method || '';
        const ncParcialMatch = desc.match(/\[NC PARCIAL S\/([\d.]+)\]/);
        const ncNumMatch = desc.match(/\[NC:\s*([^\]]+)\]/);
        const ncMonto = ncParcialMatch ? ncParcialMatch[1] : null;
        const ncNumero = ncNumMatch ? fmtNum(ncNumMatch[1].trim()) : null;
        const descLimpia = desc.replace('[CAJA] ', '').replace(/\[NC PARCIAL S\/[\d.]+\][^\[]*/g, '').replace(/\[NC:[^\]]+\]/g, '').replace(/\[ANULADO\][^\[]*/g, '').trim();

        let ncBadge = '';
        if (ncParcialMatch && !esAnulado) {
            ncBadge = `<span class="hi-nc-badge">NC -${ncMonto}</span>`;
        }
        if (ncNumero) {
            ncBadge += `<span class="hi-nc-num">${ncNumero}</span>`;
        }

        return `<div class="hi-card${esAnulado ? ' hi-anulado' : ''}">
            <div class="hi-row1">
                <span class="hi-desc">${descLimpia}${ncBadge}</span>
                <span class="hi-monto">${esAnulado ? '<s>' : ''}S/ ${monto.toFixed(2)}${esAnulado ? '</s>' : ''}</span>
            </div>
            <div class="hi-row2">
                <span class="hi-hora">${hora}</span>
                ${compCorto ? `<span class="hi-comp">${compCorto}</span>` : ''}
                <span class="hi-met">${met}</span>
                ${esAnulado ? '<span class="hi-badge-anul">anulado</span>' : ''}
                <span class="hi-actions">
                    ${compNum && !esAnulado ? `<button class="hi-btn-pdf" onclick="verComprobante(${o.id})" title="Ver PDF">📄</button>` : ''}
                    ${!esAnulado ? `<button class="hi-btn-anul" onclick="mostrarAnular(${o.id},'${descLimpia.replace(/'/g, "\\'")}',${monto})">✕</button>` : ''}
                </span>
            </div>
        </div>`;
    }).join('');
}

function exportarDia() {
    const fecha = document.getElementById('histFecha').value;
    if (!fecha) { toast('Selecciona una fecha', 'err'); return; }
    window.open(`/api/reportes/exportar-dia?fecha=${fecha}`, '_blank');
}

async function verSesionesAnteriores() {
    try {
        const r = await fetch('/api/caja/sesiones-caja?estado=cerrada&limit=10');
        const d = await r.json();
        const sesiones = d.sesiones || [];
        if (!sesiones.length) { toast('No hay sesiones cerradas', 'info'); return; }
        const items = sesiones.map(s => {
            const dif = s.diferencia || 0;
            const difStr = Math.abs(dif) < 0.01 ? '✓' : `${dif >= 0 ? '+' : ''}${dif.toFixed(2)}`;
            return `${s.fecha} — ${s.cajero} — S/ ${s.total_cobros.toFixed(2)} — ${difStr}`;
        });
        const sel = prompt('Sesiones cerradas (ingrese número para PDF):\n\n' + sesiones.map((s, i) => `${i + 1}. ${items[i]}`).join('\n'));
        if (sel && !isNaN(sel)) {
            const idx = parseInt(sel) - 1;
            if (idx >= 0 && idx < sesiones.length) {
                window.open(`/api/caja/cierre-caja/${sesiones[idx].id}/pdf`, '_blank');
            }
        }
    } catch (e) { toast('Error cargando sesiones', 'err'); }
}


/* ══════════════════════════════════════════════════
   ANULACIÓN
   ══════════════════════════════════════════════════ */
function mostrarAnular(payId, desc, monto) {
    document.getElementById('anularPayId').value = payId;
    document.getElementById('anularTotal').value = monto;
    document.getElementById('anularInfo').innerHTML = `<strong>S/ ${monto.toFixed(2)}</strong> — ${desc.replace('[CAJA] ', '')}`;
    document.getElementById('anularMotivo').value = '01';
    document.getElementById('anularObs').value = '';
    document.getElementById('anularMonto').value = '';
    document.getElementById('anularMontoCont').style.display = 'none';
    document.getElementById('modalAnular').classList.add('active');
}

function cerrarModalAnular() { document.getElementById('modalAnular').classList.remove('active'); }

function toggleMontoParcial() {
    const m = document.getElementById('anularMotivo').value;
    const necesitaMonto = ['04', '05', '07'].includes(m);
    document.getElementById('anularMontoCont').style.display = necesitaMonto ? 'block' : 'none';
    if (necesitaMonto) document.getElementById('anularMonto').focus();
}

async function ejecutarAnulacion() {
    const payId = document.getElementById('anularPayId').value;
    let motivo = document.getElementById('anularMotivo').value;
    const obs = document.getElementById('anularObs').value.trim();
    let motivoTexto = document.getElementById('anularMotivo').selectedOptions[0].text;
    const totalOriginal = parseFloat(document.getElementById('anularTotal').value) || 0;
    let montoAnular = totalOriginal;
    const motivosParciales = ['04', '05', '07'];
    if (motivosParciales.includes(motivo)) {
        montoAnular = parseFloat(document.getElementById('anularMonto').value) || 0;
        if (montoAnular <= 0) { toast('Ingresa el monto', 'err'); return; }
        if (montoAnular > totalOriginal) { toast(`El monto no puede superar S/ ${totalOriginal.toFixed(2)}`, 'err'); return; }
        if (motivo === '07' && Math.abs(montoAnular - totalOriginal) < 0.01) { motivo = '06'; motivoTexto = 'Devolución total'; }
    }
    const esParcial = motivosParciales.includes(motivo);
    if (!confirm(`¿Confirmas la ${esParcial ? 'operación por S/ ' + montoAnular.toFixed(2) : 'ANULACIÓN'}?\nMotivo: ${motivoTexto}`)) return;
    try {
        const r = await fetch(`${API}/anular-cobro`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ payment_id: parseInt(payId), motivo_codigo: motivo, motivo_texto: motivoTexto, monto: montoAnular, observaciones: obs })
        });
        const d = await r.json();
        if (d.success) {
            cerrarModalAnular();
            toast('Cobro anulado' + (d.nota_credito ? ` · NC: ${d.nota_credito} (en proceso SUNAT)` : ''), 'ok');
            cargarHistorial(); cargarResumen();
        } else { toast(d.detail || d.error || 'Error al anular', 'err'); }
    } catch (e) { toast('Error de conexión', 'err'); }
}


/* ══════════════════════════════════════════════════
   COMPROBANTES
   ══════════════════════════════════════════════════ */
let compPageActual = 1;

async function buscarComprobantes(page = 1) {
    compPageActual = page;
    const buscar = document.getElementById('compBuscar').value.trim();
    const tipo = document.getElementById('compTipo').value;
    const estado = document.getElementById('compEstado').value;
    let url = `${API}/comprobantes?page=${page}&limit=20`;
    if (buscar) url += `&buscar=${encodeURIComponent(buscar)}`;
    if (tipo) url += `&tipo=${tipo}`;
    if (estado) url += `&estado=${estado}`;
    try {
        const r = await fetch(url);
        renderComprobantes(await r.json());
    } catch (e) {
        document.getElementById('compLista').innerHTML = '<div class="hist-empty">Error cargando comprobantes</div>';
    }
}

function renderComprobantes(data) {
    const lista = document.getElementById('compLista');
    const pag = document.getElementById('compPaginacion');
    const summ = document.getElementById('compSummary');
    const comps = data.comprobantes || [];

    summ.innerHTML = data.total > 0
        ? `<span class="ss-item"><span class="ss-val">${data.total}</span> <span class="ss-lbl">comprobante(s)</span></span> <span class="ss-sep"></span> <span class="ss-item"><span class="ss-lbl">Pág.</span> <span class="ss-val">${data.page}/${data.pages}</span></span>`
        : '';

    if (!comps.length) {
        lista.innerHTML = '<div class="hist-empty">No se encontraron comprobantes</div>';
        pag.innerHTML = ''; return;
    }

    const tipoNames = { '01': 'Factura', '03': 'Boleta', '07': 'NC', '08': 'ND' };

    lista.innerHTML = comps.map(c => {
        const esNC = c.tipo === '07' || c.tipo === '08';
        const tipoLabel = tipoNames[c.tipo] || c.tipo;
        const numCorto = fmtNum(c.numero_formato);
        // Fecha completa: "17/02/2026 10:03"
        const fechaCorta = (c.fecha || '').replace(/:\d{2}$/, ''); // solo quitar segundos si los hay

        return `<div class="co-card${esNC ? ' co-nc' : ''}">
            <div class="co-row1">
                <span class="co-num">${numCorto}${esNC ? `<span class="co-tipo-nc">${tipoLabel}</span>` : ''}</span>
                <span class="co-monto${esNC ? ' co-monto-nc' : ''}">${c.total.toFixed(2)}</span>
            </div>
            <div class="co-row2">
                <span class="co-cliente">${c.cliente_nombre || 'Sin cliente'}${c.cliente_doc ? ` · ${c.cliente_doc}` : ''}</span>
                ${statusBadge(c.status)}
            </div>
            <div class="co-row3">
                <span class="co-fecha">${fechaCorta}</span>
                <span class="co-actions">
                    ${c.pdf_url ? `<button class="co-btn-pdf" onclick="window.open('/api/caja/comprobante/${c.payment_id}/pdf','_blank')" title="Ver PDF">📄 PDF</button>` : ''}
                    ${c.status === 'accepted' && !esNC ? `<button class="co-btn-anul" onclick="mostrarAnular(${c.payment_id},'${(c.cliente_nombre || '').replace(/'/g, "\\'")} - ${numCorto}',${c.total})">Anular</button>` : ''}
                </span>
            </div>
        </div>`;
    }).join('');

    if (data.pages > 1) {
        let pagHTML = '';
        if (data.page > 1) pagHTML += `<button class="pag-btn" onclick="buscarComprobantes(${data.page - 1})">‹</button>`;
        for (let i = Math.max(1, data.page - 2); i <= Math.min(data.pages, data.page + 2); i++) {
            pagHTML += `<button class="pag-btn${i === data.page ? ' pag-active' : ''}" onclick="buscarComprobantes(${i})">${i}</button>`;
        }
        if (data.page < data.pages) pagHTML += `<button class="pag-btn" onclick="buscarComprobantes(${data.page + 1})">›</button>`;
        pag.innerHTML = pagHTML;
    } else { pag.innerHTML = ''; }
}


/* ══════════════════════════════════════════════════
   MENÚ / LOGOUT
   ══════════════════════════════════════════════════ */
function toggleMenu() {
    const m = document.getElementById('headerMenu');
    m.classList.toggle('active');
    if (m.classList.contains('active')) {
        setTimeout(() => document.addEventListener('click', cerrarMenuFuera, { once: true }), 10);
    }
}

function cerrarMenuFuera(e) {
    const m = document.getElementById('headerMenu');
    if (!e.target.closest('.hdr-menu')) m.classList.remove('active');
}

function notificarDesdeCaja() {
    document.getElementById('headerMenu').classList.remove('active');
    toast('Notificaciones: próximamente', 'ok');
}

function cerrarSesionUsuario() {
    document.getElementById('headerMenu').classList.remove('active');
    if (sesion) {
        if (!confirm('Tienes una caja abierta. Debes cerrarla antes de salir.\n¿Ir al cierre de caja?')) return;
        mostrarCierreCaja();
        return;
    }
    window.location.href = '/logout';
}


/* ══════════════════════════════════════════════════
   TOAST
   ══════════════════════════════════════════════════ */
function toast(msg, type = 'ok') {
    const el = document.createElement('div');
    el.className = `toast toast-${type}`;
    el.textContent = msg;
    document.getElementById('toastBox').appendChild(el);
    setTimeout(() => el.remove(), 3000);
}


/* ══════════════════════════════════════════════════
   VERIFICACIÓN DE PAGO BANCARIO
   (VerificadorPago — protegido con try-catch)
   ══════════════════════════════════════════════════ */
let verifCaja = null;

try {
    if (typeof VerificadorPago !== 'undefined') {
        verifCaja = new VerificadorPago({
            intervalo: 10000,
            maxIntentos: 12,
            onVerificado: (data) => {
                const badge = document.getElementById('verifBadge');
                badge.className = 'verif-ok';
                document.getElementById('verifIcon').textContent = '✅';
                document.getElementById('verifText').innerHTML =
                    `<strong>Pago verificado</strong> — ${data.banco.toUpperCase()} ${data.codigo_operacion ? '#' + data.codigo_operacion : ''}`;
                document.getElementById('verifTimer').textContent = data.fecha || '';
                if (typeof toast === 'function') toast(data.message, 'ok');
                setTimeout(() => { badge.style.display = 'none'; }, 10000);
            },
            onTimeout: (monto, metodo, paymentId) => {
                const badge = document.getElementById('verifBadge');
                badge.className = 'verif-fail';
                document.getElementById('verifIcon').textContent = '⚠️';
                document.getElementById('verifText').innerHTML =
                    `No verificado aún — <a href="#" onclick="reiniciarVerifCaja(${monto},'${metodo}',${paymentId});return false;" style="color:var(--accent);">Reintentar</a>`;
                document.getElementById('verifTimer').textContent = '';
            },
            onProgreso: (intento, max) => {
                const segs = (max - intento) * 10;
                document.getElementById('verifTimer').textContent = `${segs}s`;
                document.getElementById('verifIcon').textContent = '🔍';
                document.getElementById('verifIcon').className = 'verif-pulsing';
            },
        });
    }
} catch (e) {
    console.warn('[Caja] VerificadorPago no disponible:', e.message);
}

function verificarPagoDigital(monto, metodo, paymentId) {
    if (!verifCaja) return;
    const badge = document.getElementById('verifBadge');
    badge.style.display = 'flex';
    badge.className = '';
    document.getElementById('verifIcon').textContent = '🔍';
    document.getElementById('verifIcon').className = 'verif-pulsing';
    document.getElementById('verifText').textContent = `Verificando pago S/ ${monto.toFixed(2)} (${metodo})...`;
    document.getElementById('verifTimer').textContent = '120s';
    verifCaja.iniciar(monto, metodo, paymentId);
}

function reiniciarVerifCaja(monto, metodo, paymentId) {
    verificarPagoDigital(monto, metodo, paymentId);
}



/* =====================================================
    FUNCIONES PARA QUE CAJE VEA DEUDAS DE INHÁBILES
    Y PROPONGA FRACCIONAMIENTOS EN LOS PAGOS
 ========================================================*/
 /* ══════════════════════════════════════════════════
   SITUACIÓN COLEGIADO INHÁBIL
   ══════════════════════════════════════════════════ */

let _situacion = null;   // cache del último fetch

async function cargarSituacion(col) {
    // Solo para inhábiles
    if (col.habilitado) { limpiarSituacion(); return; }

    try {
        const r = await fetch(`/api/caja/situacion/${col.id}`);
        if (!r.ok) return;
        _situacion = await r.json();
        renderSituacion(_situacion);
    } catch (e) {
        console.warn('[CAJA] Error cargando situación:', e);
    }
}

function limpiarSituacion() {
    _situacion = null;
    const el = document.getElementById('panel-situacion');
    if (el) el.remove();
}

function renderSituacion(data) {
    // Quitar panel anterior si existe
    limpiarSituacion();

    const { deudas, total, califica_fraccionamiento, plan_activo, campana } = data;

    // Agrupar por año
    const grupos = {};
    deudas.forEach(d => {
        const m = (d.periodo || '').match(/(\d{4})/);
        const anio = m ? m[1] : 'Sin año';
        if (!grupos[anio]) grupos[anio] = { items: [], subtotal: 0 };
        grupos[anio].items.push(d);
        grupos[anio].subtotal += d.balance;
    });
    const anios = Object.keys(grupos).sort((a, b) => parseInt(b) - parseInt(a));

    // Banner campaña
    const campBanner = campana ? `
        <div style="background:rgba(245,158,11,.08);border:1px solid rgba(245,158,11,.2);
                    border-radius:10px;padding:10px 14px;margin-bottom:12px;
                    display:flex;align-items:center;gap:10px">
            <span style="font-size:22px">🎯</span>
            <div>
                <div style="font-size:12px;font-weight:700;color:#f59e0b">${campana.nombre} — ${Math.round(campana.descuento_pct*100)}% dto.</div>
                <div style="font-size:11px;color:#94a3b8">${campana.descripcion} · Hasta ${campana.fecha_fin}</div>
            </div>
        </div>` : '';

    // Deuda por año
    const deudaHTML = anios.map((anio, idx) => `
        <div style="margin-bottom:6px;border:1px solid rgba(239,68,68,.15);border-radius:10px;overflow:hidden">
            <div onclick="toggleSitAnio('sit-${anio}')"
                 style="display:flex;align-items:center;justify-content:space-between;
                        padding:10px 14px;cursor:pointer;background:rgba(239,68,68,.04)">
                <div style="display:flex;align-items:center;gap:8px">
                    <span style="font-size:13px;font-weight:700">${anio}</span>
                    <span style="font-size:10px;color:#94a3b8;background:rgba(255,255,255,.06);
                                 padding:2px 8px;border-radius:20px">
                        ${grupos[anio].items.length} concepto${grupos[anio].items.length > 1 ? 's' : ''}
                    </span>
                </div>
                <span style="font-size:13px;font-weight:700;color:${grupos[anio].subtotal > 100 ? '#f87171' : '#e2e8f0'}">
                    S/ ${grupos[anio].subtotal.toFixed(2)}
                </span>
            </div>
            <div id="sit-${anio}" style="display:${idx === 0 ? 'block' : 'none'}">
                ${grupos[anio].items.map(d => `
                    <div style="display:flex;justify-content:space-between;align-items:center;
                                padding:8px 14px;border-top:1px solid rgba(255,255,255,.04);
                                font-size:12px">
                        <div>
                            <div style="font-weight:600;color:#e2e8f0">${d.concept}</div>
                            <div style="color:#64748b">${d.period_label || d.periodo || ''}</div>
                        </div>
                        <div style="font-weight:700;color:#fca5a5">S/ ${d.balance.toFixed(2)}</div>
                    </div>`).join('')}
            </div>
        </div>`).join('');

    // Simulador de fraccionamiento (visible solo si califica)
    const simHTML = califica_fraccionamiento ? `
        <div style="background:rgba(99,102,241,.06);border:1px solid rgba(99,102,241,.15);
                    border-radius:10px;padding:14px;margin-top:14px">
            <div style="font-size:12px;font-weight:700;color:#818cf8;margin-bottom:10px">
                🧮 Simulador de Fraccionamiento
            </div>
            <div style="font-size:11px;color:#94a3b8;margin-bottom:10px;line-height:1.5">
                Deuda total: <strong style="color:#e2e8f0">S/ ${total.toFixed(2)}</strong> ·
                Inicial mínima: <strong style="color:#e2e8f0">S/ ${(total * 0.20).toFixed(2)}</strong>
            </div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px">
                <div>
                    <label style="font-size:10px;color:#64748b;display:block;margin-bottom:4px">
                        Cuota inicial (S/)
                    </label>
                    <input type="number" id="sit-fracc-ini" 
                           min="${(total * 0.20).toFixed(2)}" step="10"
                           value="${(total * 0.20).toFixed(2)}"
                           oninput="calcSitFracc(${total})"
                           style="width:100%;padding:8px 10px;background:rgba(15,23,42,.6);
                                  border:1px solid rgba(99,102,241,.3);border-radius:8px;
                                  color:#fff;font-size:13px;font-weight:700">
                </div>
                <div>
                    <label style="font-size:10px;color:#64748b;display:block;margin-bottom:4px">
                        N° cuotas (máx. 12)
                    </label>
                    <select id="sit-fracc-n" onchange="calcSitFracc(${total})"
                            style="width:100%;padding:8px 10px;background:rgba(15,23,42,.6);
                                   border:1px solid rgba(99,102,241,.3);border-radius:8px;
                                   color:#fff;font-size:13px">
                        ${[2,3,4,6,8,10,12].map(n => `<option value="${n}">${n} cuotas</option>`).join('')}
                    </select>
                </div>
            </div>
            <div id="sit-fracc-result" style="font-size:11px;color:#94a3b8;text-align:center"></div>
        </div>` : (plan_activo ? `
        <div style="background:rgba(59,130,246,.06);border:1px solid rgba(59,130,246,.15);
                    border-radius:10px;padding:12px 14px;margin-top:14px;font-size:12px">
            📋 <strong style="color:#60a5fa">Plan de fraccionamiento activo</strong>
            <div style="color:#94a3b8;margin-top:4px">El colegiado tiene un plan vigente en curso.</div>
        </div>` : '');

    // Botón constancia
    const constanciaBtn = `
        <button onclick="agregarConstanciaCaja()"
                style="width:100%;margin-top:14px;padding:10px;border:none;border-radius:10px;
                       font-size:12px;font-weight:700;cursor:pointer;
                       background:linear-gradient(135deg,#059669,#10b981);color:#fff;
                       display:flex;align-items:center;justify-content:center;gap:8px">
            📜 Agregar Constancia de Habilidad al cobro
            <span style="background:rgba(255,255,255,.2);padding:2px 8px;border-radius:20px">S/ 10</span>
        </button>`;

    // Beneficios rápidos
    const beneficios = `
        <div style="margin-top:14px;border-top:1px solid rgba(255,255,255,.06);padding-top:12px">
            <div style="font-size:10px;font-weight:700;color:#64748b;text-transform:uppercase;
                        letter-spacing:1px;margin-bottom:8px">Al regularizarse recupera</div>
            <div style="display:grid;gap:6px">
                ${['🎓 Capacitaciones gratuitas del colegio',
                   '💼 Acceso a bolsa laboral exclusiva',
                   '📜 Constancia de Habilidad inmediata (S/ 10)',
                   '🔔 Alertas tributarias en su celular',
                   '🤝 Respaldo legal del colegio'].map(b => `
                    <div style="font-size:11px;color:#94a3b8;display:flex;align-items:center;gap:6px">
                        ${b}
                    </div>`).join('')}
            </div>
        </div>`;

    // Panel completo
    const panel = document.createElement('div');
    panel.id = 'panel-situacion';
    panel.innerHTML = `
        <div style="background:rgba(239,68,68,.04);border:1px solid rgba(239,68,68,.15);
                    border-radius:12px;padding:14px;margin-bottom:12px">
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">
                <div style="font-size:12px;font-weight:700;color:#f87171;text-transform:uppercase;
                            letter-spacing:.5px">⚠ Colegiado Inhábil</div>
                <div style="font-size:16px;font-weight:800;color:#f87171">S/ ${total.toFixed(2)}</div>
            </div>

            ${campBanner}

            <div style="font-size:10px;font-weight:700;color:#64748b;text-transform:uppercase;
                        letter-spacing:1px;margin-bottom:8px">Deuda por año</div>
            ${deudaHTML}
            ${simHTML}
            ${constanciaBtn}
            ${beneficios}
        </div>`;

    // Insertar ANTES del panel de deudas existente
    const panelDeudas = document.getElementById('panelDeudas');
    panelDeudas.insertBefore(panel, panelDeudas.firstChild);

    // Calcular resultado inicial del simulador
    if (califica_fraccionamiento) calcSitFracc(total);
}

function toggleSitAnio(id) {
    const el = document.getElementById(id);
    if (el) el.style.display = el.style.display === 'none' ? 'block' : 'none';
}

function calcSitFracc(total) {
    const ini = parseFloat(document.getElementById('sit-fracc-ini')?.value || 0);
    const n   = parseInt(document.getElementById('sit-fracc-n')?.value || 3);
    const res = document.getElementById('sit-fracc-result');
    if (!res) return;

    const minIni = total * 0.20;
    if (ini < minIni) {
        res.innerHTML = `<span style="color:#f59e0b">⚠ Mínimo S/ ${minIni.toFixed(2)}</span>`;
        return;
    }
    const saldo = total - ini;
    const cuota = saldo / n;
    if (cuota < 100) {
        res.innerHTML = `<span style="color:#f59e0b">⚠ Cuota mensual mínima S/ 100 — reduce el número de cuotas</span>`;
        return;
    }
    res.innerHTML = `
        <div style="background:rgba(99,102,241,.08);border-radius:8px;padding:10px;text-align:left;margin-top:6px">
            <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;text-align:center">
                <div>
                    <div style="font-size:10px;color:#64748b">Inicial</div>
                    <div style="font-size:14px;font-weight:800;color:#818cf8">S/ ${ini.toFixed(2)}</div>
                </div>
                <div>
                    <div style="font-size:10px;color:#64748b">x${n} cuotas</div>
                    <div style="font-size:14px;font-weight:800;color:#818cf8">S/ ${cuota.toFixed(2)}</div>
                </div>
                <div>
                    <div style="font-size:10px;color:#64748b">Total</div>
                    <div style="font-size:14px;font-weight:800;color:#e2e8f0">S/ ${total.toFixed(2)}</div>
                </div>
            </div>
            <div style="margin-top:8px;font-size:11px;color:#4ade80;text-align:center">
                ✓ Al pagar la inicial → hábil inmediatamente
            </div>
        </div>`;
}

async function agregarConstanciaCaja() {
    // Buscar concepto "Constancia de Habilidad" en el catálogo ya cargado
    const conc = conceptosDisp.find(c =>
        c.nombre?.toLowerCase().includes('constancia') ||
        c.nombre?.toLowerCase().includes('habilidad')
    );
    if (conc) {
        agregarConcepto(conc);   // función existente de caja.js
        toast('Constancia de Habilidad agregada al cobro — S/ 10', 'ok');
    } else {
        // Fallback: agregar como ítem libre
        carrito.push({
            tipo:        'concepto',
            concepto_id: null,
            descripcion: 'Constancia de Habilidad Profesional',
            monto:       10.00,
        });
        renderCarrito();
        toast('Constancia S/ 10 agregada al cobro', 'ok');
    }
}


/* =====================================================
    INICIALIZACIÓN de
 ========================================================*/
let _modalSit = null;   // datos de situación cargados

/* ── ABRIR MODAL ─────────────────────────────────────────────────── */
async function abrirModalInhabil(col) {
    // Crear backdrop + modal si no existe
    let bg = document.getElementById('modal-inhabil-bg');
    if (!bg) {
        bg = document.createElement('div');
        bg.id = 'modal-inhabil-bg';
        bg.style.cssText = `position:fixed;inset:0;background:rgba(0,0,0,.7);
            z-index:1500;display:flex;align-items:flex-start;justify-content:center;
            padding:16px;overflow-y:auto;backdrop-filter:blur(4px)`;
        bg.innerHTML = `<div id="modal-inhabil-box" style="
            background:#0f1117;border:1px solid rgba(239,68,68,.2);
            border-radius:20px;width:100%;max-width:680px;
            box-shadow:0 30px 80px rgba(0,0,0,.8);overflow:hidden;
            margin:auto;position:relative">
            <div id="modal-inhabil-inner"></div>
        </div>`;
        bg.addEventListener('click', e => { if (e.target === bg) cerrarModalInhabil(); });
        document.body.appendChild(bg);
    }
    document.getElementById('modal-inhabil-inner').innerHTML = _loadingHTML();
    bg.style.display = 'flex';
    document.body.style.overflow = 'hidden';

    try {
        const r = await fetch(`/api/caja/situacion/${col.id}`);
        if (!r.ok) throw new Error(r.status);
        _modalSit = await r.json();
        document.getElementById('modal-inhabil-inner').innerHTML = _renderModal(_modalSit);
        _initSimulador(_modalSit.total);
        _startNotifAnim();
    } catch(e) {
        document.getElementById('modal-inhabil-inner').innerHTML =
            `<div style="padding:40px;text-align:center;color:#94a3b8">
                ❌ Error cargando situación. Usa la lista de deudas normal.
             </div>`;
    }
}

function cerrarModalInhabil() {
    const bg = document.getElementById('modal-inhabil-bg');
    if (bg) bg.style.display = 'none';
    document.body.style.overflow = '';
}

/* ── TEMPLATE PRINCIPAL ──────────────────────────────────────────── */
function _renderModal(data) {
    const { colegiado: col, deudas, total, califica_fraccionamiento, plan_activo, campana } = data;

    // Agrupar deudas por año
    const grupos = {};
    deudas.forEach(d => {
        const m = (d.periodo||'').match(/(\d{4})/);
        const anio = m ? m[1] : 'Sin año';
        if (!grupos[anio]) grupos[anio] = { items:[], subtotal:0 };
        grupos[anio].items.push(d);
        grupos[anio].subtotal += d.balance;
    });
    const anios = Object.keys(grupos).sort((a,b) => parseInt(b)-parseInt(a));
    const aniosMas3 = anios.length > 3;

    return `
    <!-- HEADER -->
    <div style="background:linear-gradient(135deg,rgba(239,68,68,.12),rgba(239,68,68,.04));
                border-bottom:1px solid rgba(239,68,68,.15);padding:20px 24px;
                display:flex;align-items:center;justify-content:space-between">
        <div style="display:flex;align-items:center;gap:14px">
            <div style="width:46px;height:46px;background:linear-gradient(135deg,#dc2626,#ef4444);
                        border-radius:14px;display:flex;align-items:center;justify-content:center;
                        font-size:20px;font-weight:800;color:#fff;flex-shrink:0">
                ${col.nombre.split(' ').slice(0,2).map(n=>n[0]).join('')}
            </div>
            <div>
                <div style="font-size:15px;font-weight:800;color:#fff">${col.nombre}</div>
                <div style="font-size:12px;color:#94a3b8">Mat. ${col.matricula} · 
                    <span style="background:#dc2626;color:#fff;padding:1px 8px;border-radius:20px;font-size:10px;font-weight:700">INHÁBIL</span>
                </div>
            </div>
        </div>
        <div style="text-align:right">
            <div style="font-size:24px;font-weight:900;color:#f87171">S/ ${total.toFixed(2)}</div>
            <div style="font-size:11px;color:#64748b">${deudas.length} deuda${deudas.length!==1?'s':''} pendiente${deudas.length!==1?'s':''}</div>
        </div>
        <button onclick="cerrarModalInhabil()" style="position:absolute;top:14px;right:14px;
            background:none;border:none;color:#64748b;font-size:22px;cursor:pointer;
            line-height:1;padding:4px">✕</button>
    </div>

    <!-- TABS -->
    <div style="display:flex;border-bottom:1px solid rgba(255,255,255,.06)">
        ${['deuda','fracc','beneficios'].map((t,i) => `
        <button onclick="_tabModal('${t}')" id="mtab-${t}"
            style="flex:1;padding:12px;border:none;background:none;cursor:pointer;
                   font-size:12px;font-weight:700;color:${i===0?'#e2e8f0':'#64748b'};
                   border-bottom:2px solid ${i===0?'#ef4444':'transparent'};transition:all .2s">
            ${t==='deuda'?'📋 Deuda':''}${t==='fracc'?'🧮 Fraccionamiento':''}${t==='beneficios'?'⭐ Beneficios':''}
        </button>`).join('')}
    </div>

    <!-- BODY -->
    <div style="padding:20px;max-height:60vh;overflow-y:auto" id="modal-tab-body">

        <!-- TAB: DEUDA -->
        <div id="mtab-body-deuda">
            ${campana ? `<div style="background:rgba(245,158,11,.08);border:1px solid rgba(245,158,11,.2);
                border-radius:10px;padding:10px 14px;margin-bottom:14px;display:flex;align-items:center;gap:10px">
                <span style="font-size:20px">🎯</span>
                <div><div style="font-size:12px;font-weight:700;color:#f59e0b">${campana.nombre} — ${Math.round(campana.descuento_pct*100)}% dto.</div>
                <div style="font-size:11px;color:#94a3b8">${campana.descripcion} · Hasta ${campana.fecha_fin}</div></div>
            </div>` : ''}

            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
                <div style="font-size:11px;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:1px">
                    Deuda consolidada por año
                </div>
                <button onclick="_selTodasModal()" style="font-size:11px;color:#60a5fa;background:none;border:none;cursor:pointer;font-weight:600">
                    ☑ Seleccionar todas
                </button>
            </div>

            ${anios.map((anio,idx) => `
            <div style="margin-bottom:8px;border:1px solid rgba(255,255,255,.07);border-radius:10px;overflow:hidden">
                <div onclick="_toggleAnioModal('manio-${anio}')"
                     style="display:flex;align-items:center;justify-content:space-between;
                            padding:10px 14px;cursor:pointer;background:rgba(255,255,255,.02);
                            user-select:none">
                    <div style="display:flex;align-items:center;gap:8px">
                        <span style="font-size:13px;font-weight:700;color:#e2e8f0">${anio}</span>
                        <span style="font-size:10px;color:#64748b;background:rgba(255,255,255,.06);
                                     padding:2px 8px;border-radius:20px">
                            ${grupos[anio].items.length} concepto${grupos[anio].items.length>1?'s':''}
                        </span>
                    </div>
                    <div style="display:flex;align-items:center;gap:10px">
                        <span style="font-size:13px;font-weight:700;
                            color:${grupos[anio].subtotal>100?'#f87171':'#e2e8f0'}">
                            S/ ${grupos[anio].subtotal.toFixed(2)}
                        </span>
                        <span id="manio-arrow-${anio}" style="color:#64748b;font-size:12px">
                            ${idx<3?'▼':'▶'}
                        </span>
                    </div>
                </div>
                <div id="manio-${anio}" style="display:${idx<3?'block':'none'}">
                    ${grupos[anio].items.map(d => `
                    <div onclick="_togDeudaModal(${d.id})" id="mdeuda-${d.id}"
                         style="display:flex;align-items:center;gap:10px;
                                padding:9px 14px;border-top:1px solid rgba(255,255,255,.04);
                                cursor:pointer;transition:background .15s">
                        <div id="mchk-${d.id}" style="width:18px;height:18px;border-radius:5px;
                             border:2px solid #334155;flex-shrink:0;display:flex;align-items:center;
                             justify-content:center;font-size:11px;transition:all .15s"></div>
                        <div style="flex:1;min-width:0">
                            <div style="font-size:12px;font-weight:600;color:#e2e8f0;
                                        white-space:nowrap;overflow:hidden;text-overflow:ellipsis">
                                ${d.concept}
                            </div>
                            <div style="font-size:10px;color:#64748b">${d.period_label||d.periodo||''}</div>
                        </div>
                        <div style="font-size:13px;font-weight:700;color:#fca5a5;flex-shrink:0">
                            S/ ${d.balance.toFixed(2)}
                        </div>
                    </div>`).join('')}
                </div>
            </div>`).join('')}

            <!-- Botones de acción deuda -->
            <div style="display:grid;gap:8px;margin-top:16px">
                <button onclick="_agregarSeleccionadasAlCarrito()" style="padding:13px;border:none;border-radius:12px;
                    font-size:13px;font-weight:700;cursor:pointer;
                    background:linear-gradient(135deg,#059669,#10b981);color:#fff;
                    display:flex;align-items:center;justify-content:center;gap:8px">
                    🛒 Agregar deudas seleccionadas al carrito de caja
                </button>
                <button onclick="_agregarConstanciaModal()" style="padding:11px;border:none;border-radius:12px;
                    font-size:12px;font-weight:700;cursor:pointer;
                    background:rgba(16,185,129,.1);border:1px solid rgba(16,185,129,.2);color:#4ade80;
                    display:flex;align-items:center;justify-content:center;gap:8px">
                    📜 + Constancia de Habilidad
                    <span style="background:rgba(16,185,129,.2);padding:2px 8px;border-radius:20px">S/ 10</span>
                </button>
                <!-- Pago online — preparado para Izipay -->
                <button onclick="_pagoOnlineModal()" style="padding:11px;border:1px dashed rgba(99,102,241,.3);
                    border-radius:12px;font-size:12px;font-weight:600;cursor:pointer;
                    background:rgba(99,102,241,.05);color:#818cf8;
                    display:flex;align-items:center;justify-content:center;gap:8px">
                    💳 Pago online (Yape / Plin / Tarjeta)
                    <span style="font-size:10px;background:rgba(99,102,241,.15);padding:2px 8px;border-radius:20px">
                        Próximamente — Izipay
                    </span>
                </button>
            </div>
        </div>

        <!-- TAB: FRACCIONAMIENTO -->
        <div id="mtab-body-fracc" style="display:none">
            ${plan_activo ? `
            <div style="background:rgba(59,130,246,.08);border:1px solid rgba(59,130,246,.2);
                        border-radius:12px;padding:16px;margin-bottom:16px;text-align:center">
                <div style="font-size:20px;margin-bottom:8px">📋</div>
                <div style="font-size:14px;font-weight:700;color:#60a5fa">Plan de fraccionamiento activo</div>
                <div style="font-size:12px;color:#94a3b8;margin-top:4px">
                    El colegiado tiene un plan vigente en curso. Puede pagar la siguiente cuota en caja.
                </div>
            </div>` : ''}

            ${califica_fraccionamiento ? `
            <div style="background:rgba(99,102,241,.06);border:1px solid rgba(99,102,241,.15);
                        border-radius:12px;padding:18px;margin-bottom:16px">
                <div style="font-size:13px;font-weight:700;color:#818cf8;margin-bottom:4px">
                    🧮 Simulador de Plan de Pago
                </div>
                <div style="font-size:11px;color:#94a3b8;margin-bottom:16px">
                    Deuda total: <strong style="color:#e2e8f0">S/ ${total.toFixed(2)}</strong> ·
                    Inicial mínima (20%): <strong style="color:#e2e8f0">S/ ${(total*.2).toFixed(2)}</strong>
                </div>

                <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:14px">
                    <div>
                        <label style="font-size:10px;color:#64748b;display:block;margin-bottom:5px;font-weight:700;text-transform:uppercase;letter-spacing:.5px">
                            Cuota inicial (S/)
                        </label>
                        <input type="number" id="msim-ini"
                            min="${(total*.2).toFixed(2)}" step="10"
                            value="${(total*.2).toFixed(2)}"
                            oninput="_calcSim(${total})"
                            style="width:100%;padding:10px 12px;background:#1e2535;
                                   border:1px solid rgba(99,102,241,.3);border-radius:10px;
                                   color:#fff;font-size:15px;font-weight:700;font-family:inherit">
                    </div>
                    <div>
                        <label style="font-size:10px;color:#64748b;display:block;margin-bottom:5px;font-weight:700;text-transform:uppercase;letter-spacing:.5px">
                            N° de cuotas
                        </label>
                        <select id="msim-n" oninput="_calcSim(${total})"
                            style="width:100%;padding:10px 12px;background:#1e2535;
                                   border:1px solid rgba(99,102,241,.3);border-radius:10px;
                                   color:#fff;font-size:14px;font-family:inherit">
                            ${[2,3,4,6,8,10,12].map(n=>`<option value="${n}">${n} cuotas mensuales</option>`).join('')}
                        </select>
                    </div>
                </div>

                <div id="msim-result"></div>

                <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:14px">
                    <button onclick="_imprimirPlanFracc(${total})"
                        style="padding:11px;border:1px solid rgba(99,102,241,.3);border-radius:10px;
                               font-size:12px;font-weight:700;cursor:pointer;
                               background:rgba(99,102,241,.08);color:#818cf8">
                        🖨️ Imprimir plan
                    </button>
                    <button onclick="_compartirPlanFracc(${total})"
                        style="padding:11px;border:1px solid rgba(16,185,129,.3);border-radius:10px;
                               font-size:12px;font-weight:700;cursor:pointer;
                               background:rgba(16,185,129,.08);color:#4ade80">
                        📤 Compartir plan
                    </button>
                </div>
            </div>` : `
            <div style="text-align:center;padding:30px;color:#64748b">
                <div style="font-size:32px;margin-bottom:8px">⚠️</div>
                <div style="font-size:13px">Deuda mínima para fraccionar: S/ 500</div>
                <div style="font-size:12px;margin-top:4px">Deuda actual: S/ ${total.toFixed(2)}</div>
            </div>`}

            <!-- Reglamento -->
            <div style="background:rgba(255,255,255,.02);border:1px solid rgba(255,255,255,.06);
                        border-radius:10px;padding:14px">
                <div style="font-size:11px;font-weight:700;color:#64748b;text-transform:uppercase;
                            letter-spacing:1px;margin-bottom:10px">Condiciones del plan</div>
                ${[
                    ['✅','Deuda mínima: S/ 500'],
                    ['📌','Cuota inicial mínima: 20% de la deuda total'],
                    ['📌','Cuota mensual mínima: S/ 100'],
                    ['📌','Máximo 12 cuotas mensuales'],
                    ['⭐','Al pagar la inicial: habilidad inmediata'],
                    ['⚠️','2 cuotas impagas consecutivas: pérdida del plan'],
                ].map(([ico,txt])=>`
                    <div style="display:flex;align-items:flex-start;gap:8px;margin-bottom:6px;font-size:11px;color:#94a3b8">
                        <span>${ico}</span><span>${txt}</span>
                    </div>`).join('')}
            </div>
        </div>

        <!-- TAB: BENEFICIOS -->
        <div id="mtab-body-beneficios" style="display:none">
            <div style="text-align:center;margin-bottom:20px">
                <div style="font-size:14px;font-weight:700;color:#e2e8f0;margin-bottom:4px">
                    Al regularizarse, ${col.nombre.split(' ')[0]} recupera:
                </div>
                <div style="font-size:12px;color:#64748b">Beneficios exclusivos para colegiados hábiles</div>
            </div>

            <!-- Notificaciones animadas -->
            <div style="background:#0a0d16;border-radius:16px;padding:14px;margin-bottom:18px;min-height:120px">
                <div style="font-size:10px;color:#334155;text-align:center;margin-bottom:8px;
                            text-transform:uppercase;letter-spacing:1px;font-weight:700">
                    Vista previa de notificaciones
                </div>
                <div id="modal-notifs-wrap" style="position:relative;min-height:80px;display:flex;align-items:center">
                    ${[
                        ['⚠️','Vencimiento mañana','Declaración tributaria de "Panadería Camilo" vence el 20/02'],
                        ['🎓','GRATIS para ti','Conferencia 3h: Reforma Tributaria 2026 — hoy 6pm'],
                        ['💼','Convocatoria abierta','Contadores para proyecto minero en Loreto — toda edad'],
                        ['✅','Tu constancia está lista','Constancia de Habilidad disponible. Toca para descargar PDF.'],
                        ['🚨','Aviso laboral URGENTE','Estudio contable requiere tributarista — incorporación inmediata'],
                    ].map((n,i)=>`
                    <div class="modal-notif" data-idx="${i}"
                         style="position:absolute;inset:0;display:flex;align-items:center;gap:10px;
                                background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.07);
                                border-radius:12px;padding:12px;opacity:0;transition:opacity .5s ease">
                        <div style="width:36px;height:36px;border-radius:10px;flex-shrink:0;
                                    background:rgba(255,255,255,.06);display:flex;align-items:center;
                                    justify-content:center;font-size:18px">${n[0]}</div>
                        <div>
                            <div style="font-size:12px;font-weight:700;color:#fff;margin-bottom:2px">${n[1]}</div>
                            <div style="font-size:11px;color:#64748b;line-height:1.3">${n[2]}</div>
                        </div>
                    </div>`).join('')}
                </div>
            </div>

            <!-- Beneficios lista -->
            <div style="display:grid;gap:8px">
                ${[
                    ['#f59e0b','ph-calendar-check','Alertas tributarias personalizadas','Vencimientos de tus clientes directo al celular'],
                    ['#818cf8','ph-graduation-cap','Capacitaciones gratuitas','Conferencias y talleres exclusivos para hábiles'],
                    ['#4ade80','ph-briefcase','Bolsa laboral exclusiva','Empleos y proyectos disponibles solo para ti'],
                    ['#f87171','ph-certificate','Constancia de Habilidad en minutos','PDF oficial al instante · S/ 10'],
                    ['#60a5fa','ph-shield-check','Respaldo legal del colegio','Representación ante organismos reguladores'],
                ].map(([color,ico,title,desc])=>`
                <div style="display:flex;align-items:center;gap:12px;background:rgba(255,255,255,.02);
                            border:1px solid rgba(255,255,255,.06);border-radius:12px;padding:12px 14px">
                    <div style="width:38px;height:38px;border-radius:10px;background:${color}18;
                                display:flex;align-items:center;justify-content:center;flex-shrink:0">
                        <i class="ph ${ico}" style="font-size:20px;color:${color}"></i>
                    </div>
                    <div>
                        <div style="font-size:12px;font-weight:700;color:#e2e8f0">${title}</div>
                        <div style="font-size:11px;color:#64748b">${desc}</div>
                    </div>
                </div>`).join('')}
            </div>
        </div>

    </div><!-- /body -->
    `;
}

/* ── TABS ────────────────────────────────────────────────────────── */
function _tabModal(tab) {
    ['deuda','fracc','beneficios'].forEach(t => {
        const btn  = document.getElementById(`mtab-${t}`);
        const body = document.getElementById(`mtab-body-${t}`);
        const active = t === tab;
        if (btn)  { btn.style.color = active ? '#e2e8f0' : '#64748b'; btn.style.borderBottomColor = active ? '#ef4444' : 'transparent'; }
        if (body) body.style.display = active ? 'block' : 'none';
    });
    if (tab === 'beneficios') _startNotifAnim();
    if (tab === 'fracc' && _modalSit) _calcSim(_modalSit.total);
}

/* ── SIMULADOR ───────────────────────────────────────────────────── */
function _calcSim(total) {
    const ini = parseFloat(document.getElementById('msim-ini')?.value || 0);
    const n   = parseInt(document.getElementById('msim-n')?.value || 3);
    const res = document.getElementById('msim-result');
    if (!res) return;

    const minIni = total * 0.20;
    if (ini < minIni) {
        res.innerHTML = `<div style="color:#f59e0b;font-size:12px;text-align:center;padding:8px">
            ⚠ Mínimo S/ ${minIni.toFixed(2)}</div>`;
        return;
    }
    const saldo = total - ini;
    const cuota = saldo / n;
    if (cuota < 100) {
        res.innerHTML = `<div style="color:#f59e0b;font-size:12px;text-align:center;padding:8px">
            ⚠ Cuota mínima S/ 100 — reduce el número de cuotas</div>`;
        return;
    }

    // Generar cronograma
    const hoy = new Date();
    const meses = ['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic'];
    const cuotas = [];
    for (let i = 1; i <= n; i++) {
        const d = new Date(hoy.getFullYear(), hoy.getMonth() + i, 15);
        cuotas.push({ num: i, fecha: `${meses[d.getMonth()]} ${d.getFullYear()}`, monto: cuota });
    }

    res.innerHTML = `
        <div style="background:rgba(99,102,241,.08);border-radius:10px;overflow:hidden">
            <div style="display:grid;grid-template-columns:1fr 1fr 1fr;text-align:center;
                        padding:14px;border-bottom:1px solid rgba(255,255,255,.06)">
                <div>
                    <div style="font-size:10px;color:#64748b">Inicial hoy</div>
                    <div style="font-size:18px;font-weight:800;color:#818cf8">S/ ${ini.toFixed(2)}</div>
                </div>
                <div>
                    <div style="font-size:10px;color:#64748b">x${n} cuotas de</div>
                    <div style="font-size:18px;font-weight:800;color:#818cf8">S/ ${cuota.toFixed(2)}</div>
                </div>
                <div>
                    <div style="font-size:10px;color:#64748b">Total</div>
                    <div style="font-size:18px;font-weight:800;color:#e2e8f0">S/ ${total.toFixed(2)}</div>
                </div>
            </div>
            <div style="padding:12px 14px">
                <div style="font-size:10px;font-weight:700;color:#64748b;text-transform:uppercase;
                            letter-spacing:1px;margin-bottom:8px">Cronograma de cuotas</div>
                ${cuotas.map(c=>`
                <div style="display:flex;justify-content:space-between;align-items:center;
                            padding:6px 0;border-bottom:1px solid rgba(255,255,255,.04);font-size:12px">
                    <div style="display:flex;align-items:center;gap:8px">
                        <span style="width:20px;height:20px;background:rgba(99,102,241,.2);
                                     border-radius:50%;display:inline-flex;align-items:center;
                                     justify-content:center;font-size:10px;font-weight:700;color:#818cf8">
                            ${c.num}
                        </span>
                        <span style="color:#94a3b8">${c.fecha}</span>
                    </div>
                    <span style="font-weight:700;color:#e2e8f0">S/ ${c.monto.toFixed(2)}</span>
                </div>`).join('')}
            </div>
            <div style="padding:10px 14px;background:rgba(74,222,128,.06);
                        border-top:1px solid rgba(74,222,128,.1);font-size:11px;color:#4ade80;text-align:center">
                ⭐ Pagando la inicial hoy → habilidad inmediata · Constancia disponible al instante
            </div>
        </div>`;
}

/* ── IMPRIMIR / COMPARTIR PLAN ────────────────────────────────────── */
function _imprimirPlanFracc(total) {
    const ini = parseFloat(document.getElementById('msim-ini')?.value || total*0.2);
    const n   = parseInt(document.getElementById('msim-n')?.value || 3);
    if (!_modalSit) return;
    const col = _modalSit.colegiado;
    const cuota = (total - ini) / n;
    const hoy = new Date();
    const meses = ['Enero','Febrero','Marzo','Abril','Mayo','Junio','Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre'];

    const cuotas = [];
    for (let i = 1; i <= n; i++) {
        const d = new Date(hoy.getFullYear(), hoy.getMonth() + i, 15);
        cuotas.push({ num: i, mes: `${meses[d.getMonth()]} ${d.getFullYear()}`, monto: cuota.toFixed(2) });
    }

    const w = window.open('', '_blank', 'width=600,height=700');
    w.document.write(`<!DOCTYPE html><html><head>
    <meta charset="UTF-8"><title>Plan de Fraccionamiento</title>
    <style>
        body{font-family:Arial,sans-serif;padding:30px;color:#111;max-width:560px;margin:auto}
        h2{color:#1e3a5f;border-bottom:2px solid #1e3a5f;padding-bottom:8px}
        .info{background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:14px;margin:16px 0}
        table{width:100%;border-collapse:collapse;margin-top:14px}
        th{background:#1e3a5f;color:#fff;padding:8px 12px;text-align:left;font-size:12px}
        td{padding:8px 12px;border-bottom:1px solid #e2e8f0;font-size:13px}
        .total{font-weight:700;font-size:16px;color:#1e3a5f}
        .footer{margin-top:24px;font-size:11px;color:#64748b;border-top:1px solid #e2e8f0;padding-top:12px}
        @media print{button{display:none}}
    </style></head><body>
    <h2>📋 Propuesta de Plan de Fraccionamiento</h2>
    <div class="info">
        <strong>${col.nombre}</strong><br>
        Matrícula: ${col.matricula}<br>
        Deuda total: <strong>S/ ${total.toFixed(2)}</strong><br>
        Fecha: ${hoy.toLocaleDateString('es-PE',{day:'2-digit',month:'long',year:'numeric'})}
    </div>
    <table>
        <tr><th>#</th><th>Vencimiento</th><th>Monto</th></tr>
        <tr><td><strong>0</strong></td><td><strong>Inicial — hoy</strong></td><td><strong>S/ ${ini.toFixed(2)}</strong></td></tr>
        ${cuotas.map(c=>`<tr><td>${c.num}</td><td>${c.mes} (día 15)</td><td>S/ ${c.monto}</td></tr>`).join('')}
        <tr style="background:#f8fafc"><td colspan="2" class="total">TOTAL</td><td class="total">S/ ${total.toFixed(2)}</td></tr>
    </table>
    <div style="margin-top:16px;background:#f0fdf4;border:1px solid #bbf7d0;border-radius:6px;padding:12px;font-size:12px">
        ✅ Al pagar la cuota inicial, el colegiado recupera su condición de <strong>HÁBIL</strong> de forma inmediata.
    </div>
    <div class="footer">
        Colegio de Contadores Públicos de Loreto · Propuesta sujeta a aprobación del Consejo Directivo<br>
        Máx. 12 cuotas · Cuota mínima S/ 100 · Vigencia del plan: 30 días
    </div>
    <br><button onclick="window.print()" style="padding:10px 20px;background:#1e3a5f;color:#fff;border:none;border-radius:6px;font-size:14px;cursor:pointer">🖨️ Imprimir</button>
    </body></html>`);
    w.document.close();
}

function _compartirPlanFracc(total) {
    const ini = parseFloat(document.getElementById('msim-ini')?.value || total*0.2);
    const n   = parseInt(document.getElementById('msim-n')?.value || 3);
    const cuota = ((total - ini) / n).toFixed(2);
    const col = _modalSit?.colegiado;
    const texto = `📋 *Propuesta de Fraccionamiento CCPL*\n\n` +
        `Colegiado: ${col?.nombre}\nDeuda total: S/ ${total.toFixed(2)}\n\n` +
        `✅ Cuota inicial: S/ ${ini.toFixed(2)}\n` +
        `📅 ${n} cuotas mensuales de S/ ${cuota}\n\n` +
        `Al pagar la inicial recuperas tu habilidad de inmediato.\n` +
        `Mayor info: CCPL Oficina Principal.`;
    if (navigator.share) {
        navigator.share({ title: 'Plan de Fraccionamiento CCPL', text: texto });
    } else {
        navigator.clipboard.writeText(texto);
        toast('Plan copiado al portapapeles — pega en WhatsApp', 'ok');
    }
}

/* ── SELECCIÓN DE DEUDAS ─────────────────────────────────────────── */
const _deudaSel = new Set();

function _togDeudaModal(id) {
    const row = document.getElementById(`mdeuda-${id}`);
    const chk = document.getElementById(`mchk-${id}`);
    if (_deudaSel.has(id)) {
        _deudaSel.delete(id);
        if (chk) { chk.style.background=''; chk.style.borderColor='#334155'; chk.textContent=''; }
        if (row) row.style.background='';
    } else {
        _deudaSel.add(id);
        if (chk) { chk.style.background='#059669'; chk.style.borderColor='#059669'; chk.textContent='✓'; }
        if (row) row.style.background='rgba(5,150,105,.06)';
    }
}

function _selTodasModal() {
    if (!_modalSit) return;
    _modalSit.deudas.forEach(d => {
        _deudaSel.add(d.id);
        const chk = document.getElementById(`mchk-${d.id}`);
        const row = document.getElementById(`mdeuda-${d.id}`);
        if (chk) { chk.style.background='#059669'; chk.style.borderColor='#059669'; chk.textContent='✓'; }
        if (row) row.style.background='rgba(5,150,105,.06)';
    });
}

function _agregarSeleccionadasAlCarrito() {
    if (!_modalSit || _deudaSel.size === 0) {
        toast('Selecciona al menos una deuda', 'warn'); return;
    }
    let agregadas = 0;
    _modalSit.deudas.forEach(d => {
        if (!_deudaSel.has(d.id)) return;
        // No duplicar si ya está en el carrito
        if (carrito.some(i => i.tipo==='deuda' && i.deuda_id===d.id)) return;
        carrito.push({
            tipo: 'deuda', deuda_id: d.id,
            descripcion: `${d.concept} ${d.period_label||d.periodo||''}`.trim(),
            monto: d.balance,
        });
        agregadas++;
    });
    renderCarrito();
    toast(`${agregadas} deuda${agregadas!==1?'s':''} agregada${agregadas!==1?'s':''} al carrito`, 'ok');
    cerrarModalInhabil();
}

function _agregarConstanciaModal() {
    const conc = conceptosDisp.find(c =>
        (c.nombre||'').toLowerCase().includes('constancia') ||
        (c.nombre||'').toLowerCase().includes('habilidad')
    );
    if (conc) {
        agregarConcepto(conc);
    } else {
        carrito.push({ tipo:'concepto', concepto_id:null,
            descripcion:'Constancia de Habilidad Profesional', monto:10.00 });
        renderCarrito();
    }
    toast('Constancia de Habilidad S/ 10 agregada al carrito', 'ok');
}

function _pagoOnlineModal() {
    toast('Integración Izipay pendiente de credenciales — usa pago presencial', 'warn');
    // TODO: window.open(urlIzipay, '_blank');
}

/* ── TOGGLE AÑO ──────────────────────────────────────────────────── */
function _toggleAnioModal(id) {
    const el  = document.getElementById(id);
    const anio = id.replace('manio-','');
    const arr = document.getElementById(`manio-arrow-${anio}`);
    if (!el) return;
    const open = el.style.display === 'none';
    el.style.display = open ? 'block' : 'none';
    if (arr) arr.textContent = open ? '▼' : '▶';
}

/* ── ANIMACIÓN NOTIFICACIONES ────────────────────────────────────── */
let _notifTimer = null;
let _notifIdx = 0;

function _startNotifAnim() {
    clearInterval(_notifTimer);
    const items = document.querySelectorAll('.modal-notif');
    if (!items.length) return;
    items.forEach(el => { el.style.opacity = '0'; });
    _notifIdx = 0;
    const show = () => {
        items.forEach(el => { el.style.opacity = '0'; });
        const cur = items[_notifIdx % items.length];
        if (cur) cur.style.opacity = '1';
        _notifIdx++;
    };
    show();
    _notifTimer = setInterval(show, 3200);
}

function _initSimulador(total) {
    // Calcular resultado inicial si ya está en tab fracc
    setTimeout(() => _calcSim(total), 100);
}

/* ── LOADING SKELETON ────────────────────────────────────────────── */
function _loadingHTML() {
    return `<div style="padding:40px;text-align:center">
        <div style="width:40px;height:40px;border:3px solid rgba(239,68,68,.2);
                    border-top-color:#ef4444;border-radius:50%;
                    animation:spin .8s linear infinite;margin:0 auto 12px"></div>
        <div style="color:#64748b;font-size:13px">Cargando situación del colegiado…</div>
        <style>@keyframes spin{to{transform:rotate(360deg)}}</style>
    </div>`;
}
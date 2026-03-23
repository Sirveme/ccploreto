/**
 * PagoFlowHabil — Flujo de pago para Dashboard Colegiado Hábil
 * static/js/modules/pago-flow-habil.js
 *
 * Flujo:
 *   1. Elegir comprobante (Boleta / Factura / Ninguno)
 *   2. ¿Cómo pagas? → Reportar Pago | Pagar con Tarjeta
 *   3. (si Reportar) Formulario con OCR + cuenta bancaria
 */

window.PagoFlowHabil = (() => {

  let _ctx = {
    deudaId:null, deudaIds:[], monto:null, concepto:null,
    tipoComp:null, facturaRuc:'', facturaRs:'', facturaDir:'',
    modo:null, archivo:null, metodo:null,
  };

  const CUENTAS = {
    transferencia: {
      banco:'BBVA', titular:'CCPL', icon:'🏦',
      numero:'0011-0301-0100000594',
      cci:'011-301-000100000594-90',
    },
  };

  const $ = id => document.getElementById(id);

  // ── Inyectar modal ─────────────────────────────────────────────────────────
  function _ensureModal() {
    if ($('pfh-modal')) return;
    const s = document.createElement('style');
    s.id = 'pfh-styles';
    s.textContent = `
#pfh-modal{background:var(--color-bg-card,#1e1e2e);border:1px solid var(--color-border,#2a2a3a);
 border-radius:16px;padding:0;width:min(440px,96vw);max-height:90vh;overflow:hidden;
 color:var(--color-text,#eee)}
#pfh-modal::backdrop{background:rgba(0,0,0,.65)}
.pfh-comp-opt{display:flex;align-items:center;gap:12px;padding:12px 14px;border-radius:10px;
 background:var(--color-bg-card,#1e1e2e);border:1px solid var(--color-border,#2a2a3a);
 cursor:pointer;width:100%;transition:all .18s;user-select:none;box-sizing:border-box}
.pfh-comp-opt:hover{background:rgba(255,255,255,.04)}
.pfh-comp-opt.pfh-sel{border-color:var(--color-primary,#f59e0b);background:rgba(245,158,11,.07)}
.pfh-comp-opt input[type=radio]{display:none}
.pfh-chk{margin-left:auto;font-size:16px;flex-shrink:0}
.pfh-comp-opt.pfh-sel .pfh-chk{color:var(--color-primary,#f59e0b)}
.pfh-opt-btn{display:flex;align-items:center;gap:12px;padding:14px 16px;border-radius:10px;
 background:var(--color-bg-card,#1e1e2e);border:1px solid var(--color-border,#2a2a3a);
 cursor:pointer;width:100%;text-align:left;transition:all .18s;color:var(--color-text,#eee)}
.pfh-opt-btn:hover{background:rgba(255,255,255,.04);transform:translateX(3px)}
.pfh-met-btn{padding:8px 4px;border-radius:8px;font-size:12px;font-weight:600;
 background:var(--color-bg-card,#1e1e2e);border:1px solid var(--color-border,#2a2a3a);
 color:var(--color-text-muted,#888);cursor:pointer;transition:all .15s;flex:1}
.pfh-met-btn.active{background:var(--color-primary,#f59e0b);border-color:var(--color-primary,#f59e0b);color:#000}
.pfh-input{width:100%;background:var(--color-bg,#12121f);border:1px solid var(--color-border,#2a2a3a);
 color:var(--color-text,#eee);border-radius:8px;padding:8px 12px;font-size:14px;box-sizing:border-box}
.pfh-lbl{display:block;font-size:11px;color:var(--color-text-muted,#888);
 font-weight:600;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px}
.pfh-btn-primary{width:100%;padding:13px;border:none;border-radius:10px;
 background:var(--color-primary,#f59e0b);color:#000;font-weight:700;font-size:14px;cursor:pointer}
.pfh-btn-primary:disabled{opacity:.45;cursor:not-allowed}
`;
    document.head.appendChild(s);

    const d = document.createElement('dialog');
    d.id = 'pfh-modal';
    d.innerHTML = `
<div style="display:flex;align-items:center;justify-content:space-between;
 padding:16px 20px;border-bottom:1px solid var(--color-border,#2a2a3a)">
  <div style="display:flex;align-items:center;gap:10px">
    <div>
      <div id="pfh-titulo" style="font-weight:700;font-size:15px">Comprobante de pago</div>
      <div id="pfh-sub" style="font-size:11px;color:var(--color-text-muted,#888)">Paso 1 de 2</div>
    </div>
  </div>
  <button onclick="PagoFlowHabil.cerrar()" style="background:none;border:none;
   color:var(--color-text-muted,#888);font-size:20px;cursor:pointer">✕</button>
</div>
<div style="overflow-y:auto;max-height:calc(90vh - 70px);padding:20px">

<!-- PASO 1: Comprobante -->
<div id="pfh-p1">
  <p style="font-size:12px;color:var(--color-text-muted,#888);margin-bottom:14px">
    Selecciona el comprobante que necesitas.</p>
  <div style="display:flex;flex-direction:column;gap:8px;margin-bottom:16px">
    <label class="pfh-comp-opt" id="pfh-opt-boleta">
      <input type="radio" name="pfh-tc" value="boleta" onchange="PagoFlowHabil._tc('boleta')">
      <span style="font-size:18px">🧾</span>
      <div><div style="font-weight:600;font-size:13px">Boleta Electrónica</div>
           <div style="font-size:11px;color:var(--color-text-muted,#888)">A tu nombre y DNI</div></div>
      <span class="pfh-chk">○</span>
    </label>
    <label class="pfh-comp-opt" id="pfh-opt-factura">
      <input type="radio" name="pfh-tc" value="factura" onchange="PagoFlowHabil._tc('factura')">
      <span style="font-size:18px">📄</span>
      <div><div style="font-weight:600;font-size:13px">Factura Electrónica</div>
           <div style="font-size:11px;color:var(--color-text-muted,#888)">Para empresas o personas con RUC</div></div>
      <span class="pfh-chk">○</span>
    </label>
    <label class="pfh-comp-opt" id="pfh-opt-ninguno">
      <input type="radio" name="pfh-tc" value="" onchange="PagoFlowHabil._tc('')">
      <span style="font-size:18px">🚫</span>
      <div><div style="font-weight:600;font-size:13px">Sin comprobante</div></div>
      <span class="pfh-chk">○</span>
    </label>
  </div>
  <!-- Datos factura -->
  <div id="pfh-fdat" style="display:none;background:rgba(0,0,0,.2);
       border:1px solid var(--color-border,#2a2a3a);border-radius:10px;padding:14px;margin-bottom:14px">
    <div style="margin-bottom:10px">
      <label class="pfh-lbl">RUC *</label>
      <div style="display:flex;align-items:center;gap:8px">
        <input type="text" id="pfh-ruc" maxlength="11" placeholder="11 dígitos"
               class="pfh-input" style="flex:1"
               oninput="PagoFlowHabil._rucInput(this.value)">
        <span id="pfh-ruc-spin" style="display:none">⏳</span>
      </div>
      <div id="pfh-ruc-est" style="font-size:10px;margin-top:3px;color:var(--color-text-muted,#888)"></div>
    </div>
    <div style="margin-bottom:10px">
      <label class="pfh-lbl">Razón Social *</label>
      <input type="text" id="pfh-rs" class="pfh-input" placeholder="Se completará automáticamente">
    </div>
    <div>
      <label class="pfh-lbl">Dirección *
        <span id="pfh-dir-hint" style="font-size:9px;font-weight:400;color:#ef4444;margin-left:4px"></span>
      </label>
      <input type="text" id="pfh-dir" class="pfh-input" placeholder="Dirección fiscal (obligatoria)"
             oninput="PagoFlowHabil._updBtn()">
    </div>
  </div>
  <button id="pfh-btn-cont" class="pfh-btn-primary" disabled
          onclick="PagoFlowHabil._p2()">Continuar →</button>
</div>

<!-- PASO 2: Método -->
<div id="pfh-p2" style="display:none">
  <div style="display:flex;align-items:center;gap:8px;padding:10px 12px;border-radius:9px;
              margin-bottom:14px;background:rgba(0,0,0,.2);
              border:1px solid var(--color-border,#2a2a3a)">
    <span id="pfh-comp-ico" style="font-size:16px">🧾</span>
    <span id="pfh-comp-txt" style="font-size:12px;flex:1"></span>
    <button onclick="PagoFlowHabil._p1()" style="background:none;border:none;
     color:var(--color-text-muted,#888);font-size:11px;cursor:pointer;text-decoration:underline">
      Cambiar</button>
  </div>
  <p style="font-size:12px;color:var(--color-text-muted,#888);margin-bottom:12px">
    ¿Cómo realizaste o realizarás el pago?</p>
  <div style="display:flex;flex-direction:column;gap:8px">
    <button class="pfh-opt-btn" onclick="PagoFlowHabil._p3r()">
      <span style="font-size:20px">📤</span>
      <div><div style="font-weight:600;font-size:13px">Ya pagué (Yape / Plin / Transferencia)</div>
           <div style="font-size:11px;color:var(--color-text-muted,#888)">Adjunta tu voucher · Validación en 24h</div></div>
      <span style="margin-left:auto;color:var(--color-text-muted,#888)">›</span>
    </button>
    <button class="pfh-opt-btn" id="pfh-btn-online" onclick="PagoFlowHabil._online()">
      <span style="font-size:20px">💳</span>
      <div><div style="font-weight:600;font-size:13px">Pagar con Tarjeta</div>
           <div style="font-size:11px;color:var(--color-text-muted,#888)">Visa, Mastercard · OpenPay Perú</div></div>
      <span style="margin-left:auto;color:var(--color-text-muted,#888)">›</span>
    </button>
  </div>
  <div style="text-align:center;font-size:10px;color:var(--color-text-muted,#888);margin-top:14px">
    🔒 Datos protegidos con cifrado SSL</div>
</div>

<!-- PASO 3: Reportar pago -->
<div id="pfh-p3" style="display:none">
  <!-- Resumen deuda -->
  <div style="padding:10px 12px;border-radius:9px;margin-bottom:14px;
              background:rgba(0,0,0,.2);border:1px solid var(--color-border,#2a2a3a);font-size:12px">
    <div style="display:flex;justify-content:space-between">
      <span style="color:var(--color-text-muted,#888)">Concepto:</span>
      <span id="pfh-conc" style="font-weight:600"></span>
    </div>
    <div style="display:flex;justify-content:space-between;margin-top:4px">
      <span style="color:var(--color-text-muted,#888)">Importe deuda:</span>
      <span id="pfh-monto-deuda" style="font-weight:700;color:#ef4444"></span>
    </div>
  </div>
  <!-- Voucher -->
  <div style="margin-bottom:14px">
    <label class="pfh-lbl">Voucher / Captura *</label>
    <div id="pfh-vdrop" onclick="document.getElementById('pfh-finput').click()"
         style="margin-top:4px;border:2px dashed var(--color-border,#2a2a3a);border-radius:10px;
                padding:20px;text-align:center;cursor:pointer;color:var(--color-text-muted,#888);font-size:13px">
      📷 Toca para adjuntar o arrastra aquí
    </div>
    <input type="file" id="pfh-finput" accept="image/*,.pdf" style="display:none"
           onchange="PagoFlowHabil._file(this.files[0])">
    <div id="pfh-ocr" style="display:none;margin-top:6px;padding:7px 11px;border-radius:8px;
         font-size:11px;background:rgba(245,158,11,.1);color:#f59e0b">
      ⏳ Analizando con IA...
    </div>
  </div>
  <!-- Monto + N° Op -->
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px">
    <div>
      <label class="pfh-lbl">Monto pagado (S/) *</label>
      <input type="number" id="pfh-monto" class="pfh-input" placeholder="0.00"
             step="0.01" oninput="PagoFlowHabil._montoInp()">
      <div style="font-size:9px;color:var(--color-text-muted,#888);margin-top:2px">✏ Pre-llenado por IA</div>
    </div>
    <div>
      <label class="pfh-lbl">N° Operación *</label>
      <input type="text" id="pfh-nrop" class="pfh-input" placeholder="Requerido">
    </div>
  </div>
  <!-- Info cobertura -->
  <div id="pfh-cob" style="display:none;padding:9px 12px;border-radius:9px;margin-bottom:10px;
       font-size:11px;background:rgba(0,0,0,.2);border:1px solid var(--color-border,#2a2a3a)">
    <div style="display:flex;justify-content:space-between">
      <span style="color:var(--color-text-muted,#888)">Tu pago cubre:</span>
      <span id="pfh-pct" style="font-weight:700">—</span>
    </div>
    <div id="pfh-parcial" style="display:none;margin-top:4px;font-size:10px;color:#f59e0b">
      ⚠ Se registrará como pago parcial — la caja lo revisará</div>
  </div>
  <!-- Banco OCR -->
  <div id="pfh-banco-row" style="display:none;margin-bottom:10px">
    <span style="display:inline-flex;align-items:center;gap:6px;padding:5px 11px;border-radius:20px;
          background:rgba(34,197,94,.1);border:1px solid rgba(34,197,94,.2);font-size:11px;color:#22c55e">
      ✨ IA detectó: <strong id="pfh-banco-txt"></strong>
    </span>
  </div>
  <!-- Métodos -->
  <div style="margin-bottom:14px">
    <label class="pfh-lbl">Método usado *</label>
    <div style="display:flex;gap:8px;margin-top:6px">
      <button class="pfh-met-btn" data-m="yape"
              onclick="PagoFlowHabil._met('yape',this)">💜 Yape</button>
      <button class="pfh-met-btn" data-m="plin"
              onclick="PagoFlowHabil._met('plin',this)">💚 Plin</button>
      <button class="pfh-met-btn" data-m="transferencia"
              onclick="PagoFlowHabil._met('transferencia',this)">🏦 Transf.</button>
    </div>
    <div id="pfh-cuenta" style="display:none;margin-top:8px;padding:10px 12px;border-radius:9px;
         font-size:12px;background:rgba(0,0,0,.2);border:1px solid var(--color-border,#2a2a3a)"></div>
  </div>
  <button class="pfh-btn-primary" onclick="PagoFlowHabil._enviar()">📤 Enviar reporte</button>
</div>

</div>`;
    document.body.appendChild(d);
  }

  // ── Paso 1 ─────────────────────────────────────────────────────────────────
  function _tc(tipo) {
    _ctx.tipoComp = tipo;
    ['boleta','factura',''].forEach(t => {
      const id = t==='' ? 'pfh-opt-ninguno' : `pfh-opt-${t}`;
      $(id)?.classList.toggle('pfh-sel', t===tipo);
      const chk = $(id)?.querySelector('.pfh-chk');
      if (chk) chk.textContent = t===tipo ? '●' : '○';
    });
    if ($('pfh-fdat')) $('pfh-fdat').style.display = tipo==='factura' ? 'block':'none';
    _updBtn();
  }

  function _updBtn() {
    const btn = $('pfh-btn-cont');
    if (!btn) return;
    if (_ctx.tipoComp === null) { btn.disabled=true; return; }
    if (_ctx.tipoComp === 'factura') {
      const ruc = ($('pfh-ruc')?.value||'').trim();
      const rs  = ($('pfh-rs')?.value||'').trim();
      const dir = ($('pfh-dir')?.value||'').trim();
      btn.disabled = !(ruc.length===11 && rs && dir);
      const hint = $('pfh-dir-hint');
      if (hint) hint.textContent = (!dir && ruc.length===11 && rs) ? '⚠ Obligatoria':'';
    } else { btn.disabled=false; }
  }

  let _rucT=null;
  function _rucInput(ruc) {
    if ($('pfh-ruc-est')) $('pfh-ruc-est').textContent='';
    if ($('pfh-btn-cont')) $('pfh-btn-cont').disabled=true;
    if (_rucT) clearTimeout(_rucT);
    if (ruc.length!==11 || !/^\d+$/.test(ruc)) return;
    _rucT = setTimeout(()=>_fetchRuc(ruc),600);
  }

  async function _fetchRuc(ruc) {
    const spin=$('pfh-ruc-spin'), est=$('pfh-ruc-est'), rsEl=$('pfh-rs'), dirEl=$('pfh-dir');
    if (spin) spin.style.display='inline';
    if (est)  est.textContent='Consultando...';
    try {
      const d = await fetch(`/api/portal/ruc/${ruc}`).then(r=>r.json());
      if (spin) spin.style.display='none';
      const nat = (d.tipo_ruc==='natural')||ruc.startsWith('10');
      if (d.ok && d.nombre) {
        if (rsEl) { rsEl.value=d.nombre; rsEl.readOnly=true; }
        if (dirEl) { dirEl.value=d.direccion||''; dirEl.readOnly=!nat&&!!d.direccion; }
        if (est) { est.textContent=`✅ ${d.estado||'ACTIVO'}`; est.style.color='#22c55e'; }
      } else {
        if (rsEl) { rsEl.value=''; rsEl.readOnly=false; }
        if (dirEl) { dirEl.value=''; dirEl.readOnly=false; }
        if (est) { est.textContent=d.msg||'No encontrado'; est.style.color='#f59e0b'; }
      }
    } catch(e) {
      if (spin) spin.style.display='none';
    }
    _updBtn();
  }

  function _p2() {
    _ctx.facturaRuc = _ctx.tipoComp==='factura' ? ($('pfh-ruc')?.value||'') : '';
    _ctx.facturaRs  = _ctx.tipoComp==='factura' ? ($('pfh-rs')?.value||'')  : '';
    _ctx.facturaDir = _ctx.tipoComp==='factura' ? ($('pfh-dir')?.value||'') : '';
    const ico = _ctx.tipoComp==='boleta'?'🧾':_ctx.tipoComp==='factura'?'📄':'🚫';
    const txt = _ctx.tipoComp==='boleta'?'Boleta Electrónica'
              : _ctx.tipoComp==='factura'?`Factura · RUC ${_ctx.facturaRuc}`:'Sin comprobante';
    if ($('pfh-comp-ico')) $('pfh-comp-ico').textContent=ico;
    if ($('pfh-comp-txt')) $('pfh-comp-txt').textContent=txt;
    $('pfh-p1').style.display='none';
    $('pfh-p2').style.display='block';
    if ($('pfh-titulo')) $('pfh-titulo').textContent='¿Cómo quieres pagar?';
    if ($('pfh-sub'))    $('pfh-sub').textContent='Paso 2 de 2';
  }

  function _p1() {
    $('pfh-p1').style.display='block';
    $('pfh-p2').style.display='none';
    if ($('pfh-titulo')) $('pfh-titulo').textContent='Comprobante de pago';
    if ($('pfh-sub'))    $('pfh-sub').textContent='Paso 1 de 2';
  }

  // ── Paso 3: reportar ───────────────────────────────────────────────────────
  function _p3r() {
    $('pfh-p2').style.display='none';
    $('pfh-p3').style.display='block';
    if ($('pfh-titulo')) $('pfh-titulo').textContent='Reportar pago';
    if ($('pfh-sub'))    $('pfh-sub').textContent='';
    if ($('pfh-conc'))       $('pfh-conc').textContent       = _ctx.concepto||'—';
    if ($('pfh-monto-deuda')) $('pfh-monto-deuda').textContent = _ctx.monto?`S/ ${parseFloat(_ctx.monto).toFixed(2)}`:'—';
    ['pfh-monto','pfh-nrop'].forEach(id=>{const e=$(id);if(e)e.value='';});
    if ($('pfh-banco-row')) $('pfh-banco-row').style.display='none';
    document.querySelectorAll('.pfh-met-btn').forEach(b=>b.classList.remove('active'));
    _ctx.metodo=null; _ctx.archivo=null;
    if ($('pfh-vdrop')) $('pfh-vdrop').textContent='📷 Toca para adjuntar o arrastra aquí';
  }

  // ── Online: ir a OpenPay ───────────────────────────────────────────────────
  async function _online() {
    cerrar();
    const body = new FormData();
    body.append('deuda_ids',            _ctx.deudaIds.join(','));
    body.append('monto_directo',        _ctx.monto||0);
    body.append('tipo_comprobante',     _ctx.tipoComp||'');
    body.append('factura_ruc',          _ctx.facturaRuc);
    body.append('factura_razon_social', _ctx.facturaRs);
    body.append('factura_direccion',    _ctx.facturaDir);
    try {
      const r = await fetch('/pagos/openpay/iniciar',{method:'POST',headers:{'HX-Request':'true'},body});
      const hx = r.headers.get('HX-Redirect');
      if (hx) { location.href=hx; return; }
      if (r.redirected) { location.href=r.url; return; }
      const d = await r.json().catch(()=>({}));
      if (d.redirect_url) location.href=d.redirect_url;
    } catch(e) {
      if (typeof Toast!=='undefined') Toast.show('Error al conectar con la pasarela','error');
    }
  }

  // ── OCR ────────────────────────────────────────────────────────────────────
  function _file(file) {
    if (!file) return;
    _ctx.archivo=file;
    if ($('pfh-vdrop')) $('pfh-vdrop').textContent='✅ '+file.name;
    ['pfh-monto','pfh-nrop'].forEach(id=>{const e=$(id);if(e)e.value='';});
    if ($('pfh-banco-row')) $('pfh-banco-row').style.display='none';
    document.querySelectorAll('.pfh-met-btn').forEach(b=>b.classList.remove('active'));
    _ctx.metodo=null;
    _doOcr(file);
  }

  async function _doOcr(file) {
    const o=$('pfh-ocr');
    if (o){o.style.display='block';o.textContent='⏳ Analizando voucher con IA...';}
    try {
      const fd=new FormData(); fd.append('voucher',file);
      const d=await fetch('/api/portal/analizar-voucher',{method:'POST',body:fd}).then(r=>r.json());
      if (d.ok) {
        if (d.amount && $('pfh-monto'))  $('pfh-monto').value=d.amount;
        if (d.operation_code && $('pfh-nrop')) $('pfh-nrop').value=d.operation_code;
        const app=d.app_emisora||d.bank;
        if (app){ if($('pfh-banco-row'))$('pfh-banco-row').style.display='block';
                  if($('pfh-banco-txt'))$('pfh-banco-txt').textContent=app; _autoMet(app); }
        if (o){o.textContent='✅ Datos extraídos — revisa si hace falta';o.style.color='#22c55e';}
        _montoInp();
      } else if(o) o.textContent=d.msg||'Ingresa los datos manualmente';
    } catch(e){ if(o) o.textContent='OCR no disponible';}
  }

  function _autoMet(banco) {
    const b=(banco||'').toLowerCase();
    const m=b.includes('yape')?'yape':b.includes('plin')?'plin':
           (b.includes('bbva')||b.includes('bcp')||b.includes('inter'))?'transferencia':null;
    if (m){ const btn=document.querySelector(`.pfh-met-btn[data-m="${m}"]`); if(btn)_met(m,btn); }
  }

  function _met(m,btn) {
    _ctx.metodo=m;
    document.querySelectorAll('.pfh-met-btn').forEach(b=>b.classList.remove('active'));
    btn.classList.add('active');
    const c=$('pfh-cuenta'), cuenta=CUENTAS[m];
    if (c) {
      if (cuenta) {
        c.style.display='block';
        c.innerHTML=`<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
          <span style="font-size:18px">${cuenta.icon}</span>
          <span style="font-weight:700">${cuenta.banco}</span>
          <span style="color:var(--color-text-muted,#888);font-size:11px">${cuenta.titular}</span>
        </div>
        <div style="font-family:monospace;font-size:13px;color:var(--color-primary,#f59e0b);
             letter-spacing:.05em;margin-bottom:4px">${cuenta.numero}</div>
        ${cuenta.cci?`<div style="font-size:10px;color:var(--color-text-muted,#888)">CCI: ${cuenta.cci}</div>`:''}`;
      } else c.style.display='none';
    }
  }

  function _montoInp() {
    const monto=parseFloat($('pfh-monto')?.value||0);
    const deuda=parseFloat(_ctx.monto||0);
    const cob=$('pfh-cob'), pct=$('pfh-pct'), par=$('pfh-parcial');
    if (deuda>0&&cob) {
      cob.style.display='block';
      if (monto>0) {
        const p=Math.round((monto/deuda)*100);
        if(pct){pct.textContent=p+'%';pct.style.color=p>=100?'#22c55e':'#f59e0b';}
        if(par) par.style.display=monto<deuda*0.99?'block':'none';
      }
    }
  }

  // ── Enviar ─────────────────────────────────────────────────────────────────
  async function _enviar() {
    const monto=parseFloat($('pfh-monto')?.value||0);
    const nrop=($('pfh-nrop')?.value||'').trim();
    if (!_ctx.archivo){alert('El voucher es obligatorio.');return;}
    if (!monto||monto<=0){alert('El monto debe ser mayor a cero.');return;}
    if (!nrop){alert('El N° de operación es obligatorio.');return;}
    if (!_ctx.metodo){alert('Selecciona el método de pago.');return;}
    const deuda=parseFloat(_ctx.monto||0);
    if (deuda>0&&monto<deuda*0.99) {
      if (!confirm(`⚠️ El monto (S/ ${monto}) es menor a la deuda (S/ ${deuda}).\nSe registrará como pago parcial. ¿Continuar?`)) return;
    }
    const fd=new FormData();
    fd.append('monto',monto); fd.append('nro_operacion',nrop);
    fd.append('metodo',_ctx.metodo); fd.append('deuda_ids',_ctx.deudaIds.join(','));
    fd.append('tipo_comprobante',_ctx.tipoComp||''); fd.append('voucher',_ctx.archivo);
    if (_ctx.tipoComp==='factura') {
      fd.append('factura_ruc',_ctx.facturaRuc);
      fd.append('factura_razon_social',_ctx.facturaRs);
      fd.append('factura_direccion',_ctx.facturaDir);
    }
    try {
      const d=await fetch('/api/portal/reportar-pago',{method:'POST',body:fd}).then(r=>r.json());
      cerrar();
      if (typeof Toast!=='undefined') Toast.show(d.mensaje||'✅ Pago reportado. La caja lo validará en 24h.','success');
      if (typeof ModalPagos!=='undefined') ModalPagos.refresh();
    } catch(e) {
      if (typeof Toast!=='undefined') Toast.show('Error al enviar. Intenta de nuevo.','error');
    }
  }

  // ── Reset ──────────────────────────────────────────────────────────────────
  function _reset() {
    _ctx={deudaId:null,deudaIds:[],monto:null,concepto:null,
          tipoComp:null,facturaRuc:'',facturaRs:'',facturaDir:'',
          modo:null,archivo:null,metodo:null};
    document.querySelectorAll('input[name="pfh-tc"]').forEach(r=>r.checked=false);
    ['pfh-opt-boleta','pfh-opt-factura','pfh-opt-ninguno'].forEach(id=>{
      $(id)?.classList.remove('pfh-sel');
      const c=$(id)?.querySelector('.pfh-chk'); if(c) c.textContent='○';
    });
    if($('pfh-fdat'))$('pfh-fdat').style.display='none';
    if($('pfh-btn-cont'))$('pfh-btn-cont').disabled=true;
    ['pfh-ruc','pfh-rs','pfh-dir'].forEach(id=>{const e=$(id);if(e){e.value='';e.readOnly=false;}});
    $('pfh-p1').style.display='block';
    $('pfh-p2').style.display='none';
    $('pfh-p3').style.display='none';
    if($('pfh-titulo'))$('pfh-titulo').textContent='Comprobante de pago';
    if($('pfh-sub'))   $('pfh-sub').textContent='Paso 1 de 2';
  }

  function cerrar() { $('pfh-modal')?.close(); }

  return {
    iniciar({deudaId=null,deudaIds=[],monto=null,concepto=null}={}) {
      _ensureModal(); _reset();
      _ctx.deudaId=deudaId;
      _ctx.deudaIds=deudaIds.length?deudaIds:(deudaId?[deudaId]:[]);
      _ctx.monto=monto; _ctx.concepto=concepto;
      $('pfh-modal')?.showModal();
    },
    iniciarOnline({deudaIds=[],monto=null,concepto=null}={}) {
      _ensureModal(); _reset();
      _ctx.deudaIds=deudaIds; _ctx.monto=monto; _ctx.concepto=concepto;
      $('pfh-modal')?.showModal();
    },
    cerrar,
    _tc, _updBtn, _rucInput, _p2, _p1, _p3r, _online,
    _file, _met, _montoInp, _enviar,
  };

})();
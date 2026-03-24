/**
 * caja_correccion.js
 * Panel de corrección de datos para Caja — pre producción
 * static/js/pages/caja_correccion.js
 */

const CorrPanel = (() => {
  let _tipo   = 'inhabil_sin_deuda';
  let _page   = 1;
  let _editId = null;
  let _deudas = [];  // deudas cargadas del colegiado en edición
  let _cambiosDeuda = {};  // {debt_id: nuevo_estado_gestion}
  let _condNueva = null;

  // ── Abrir / Cerrar ───────────────────────────────────────────
  function abrir() {
    document.getElementById('overlayCorreccion').style.display = 'block';
    cargarCasos();
  }

  function cerrar() {
    document.getElementById('overlayCorreccion').style.display = 'none';
  }

  // ── Tabs ─────────────────────────────────────────────────────
  function cambiarTipo(tipo, btn) {
    _tipo = tipo;
    _page = 1;
    // Resetear estilos de tabs
    document.querySelectorAll('.corr-tab').forEach(b => {
      b.style.borderBottomColor = 'transparent';
      b.style.color = '#888';
    });
    btn.style.borderBottomColor = '#f59e0b';
    btn.style.color = '#f59e0b';

    if (tipo === 'log') {
      cargarLog();
    } else {
      cargarCasos();
    }
  }

  // ── Cargar casos ─────────────────────────────────────────────
  async function cargarCasos() {
    const lista = document.getElementById('corr-lista');
    lista.innerHTML = '<div style="text-align:center;color:#888;padding:40px;font-size:13px">Cargando...</div>';

    try {
      const r = await fetch(`/caja/correccion/casos?tipo=${_tipo}&page=${_page}`);
      const d = await r.json();

      // Actualizar contadores en tabs
      if (d.totales) {
        const t = d.totales;
        const set = (id, v) => { const el = document.getElementById(id); if(el) el.textContent = v ?? '—'; };
        set('corr-cnt-inhabil', t.inhabil_sin_deuda);
        set('corr-cnt-habil',   t.habil_con_deuda_alta);
        set('corr-cnt-mixto',   t.mixto);
      }

      if (!d.casos || d.casos.length === 0) {
        lista.innerHTML = `
          <div style="text-align:center;padding:40px;color:#22c55e;font-size:13px">
            ✅ Sin casos de este tipo — todo parece correcto
          </div>`;
        document.getElementById('corr-paginacion').innerHTML = '';
        return;
      }

      lista.innerHTML = d.casos.map(c => `
        <div style="
          display:flex;align-items:center;gap:12px;
          padding:10px 12px;border-radius:8px;margin-bottom:6px;
          background:rgba(255,255,255,.02);
          border:1px solid var(--border,#2a2a3a);
          cursor:pointer;transition:border-color .15s"
          onmouseover="this.style.borderColor='rgba(245,158,11,.3)'"
          onmouseout="this.style.borderColor='var(--border,#2a2a3a)'"
          onclick="CorrPanel.abrirEdicion(${c.id})">
          <div style="flex:1;min-width:0">
            <div style="font-size:13px;font-weight:600;color:#eee">
              ${c.apellidos_nombres}
            </div>
            <div style="font-size:11px;color:#888;margin-top:2px">
              ${c.codigo_matricula}
              · <span style="color:${c.condicion==='habil'?'#22c55e':'#ef4444'}">${c.condicion.toUpperCase()}</span>
              ${c.deuda_total > 0 ? `· Deuda: <span style="color:#f59e0b">S/ ${parseFloat(c.deuda_total).toFixed(2)}</span>` : ''}
            </div>
          </div>
          <div style="
            font-size:10px;color:#888;
            background:rgba(255,255,255,.05);
            border:1px solid var(--border,#2a2a3a);
            padding:3px 8px;border-radius:4px;white-space:nowrap">
            ${c.descripcion_caso}
          </div>
          <div style="color:#f59e0b;font-size:16px">›</div>
        </div>
      `).join('');

      // Paginación
      const pag = document.getElementById('corr-paginacion');
      const hayMas = d.casos.length === d.limit;
      pag.innerHTML = `
        ${_page > 1 ? `<button onclick="CorrPanel.irPagina(${_page-1})"
          style="padding:6px 14px;background:rgba(255,255,255,.05);
                 border:1px solid var(--border,#2a2a3a);color:#888;
                 border-radius:6px;cursor:pointer;font-size:12px">← Anterior</button>` : ''}
        <span style="font-size:12px;color:#888;align-self:center">Página ${_page}</span>
        ${hayMas ? `<button onclick="CorrPanel.irPagina(${_page+1})"
          style="padding:6px 14px;background:rgba(255,255,255,.05);
                 border:1px solid var(--border,#2a2a3a);color:#888;
                 border-radius:6px;cursor:pointer;font-size:12px">Siguiente →</button>` : ''}
      `;

    } catch(e) {
      lista.innerHTML = `<div style="color:#ef4444;text-align:center;padding:20px;font-size:13px">Error al cargar: ${e.message}</div>`;
    }
  }

  function irPagina(p) {
    _page = p;
    cargarCasos();
  }

  // ── Abrir edición de un colegiado ────────────────────────────
  async function abrirEdicion(colId) {
    _editId = colId;
    _cambiosDeuda = {};
    _condNueva = null;

    const modal = document.getElementById('modalCorrEdit');
    modal.style.display = 'flex';
    document.getElementById('corr-deudas-lista').innerHTML =
      '<div style="color:#888;font-size:12px;text-align:center;padding:20px">Cargando...</div>';
    document.getElementById('corr-motivo').value = '';

    // Buscar datos del colegiado en la lista ya cargada
    const lista = document.getElementById('corr-lista');
    const cards = lista.querySelectorAll('[onclick]');
    // Buscar en DOM o usar fetch separado
    try {
      const r = await fetch(`/caja/correccion/casos?tipo=todos&page=1`);
      const d = await r.json();
      const col = d.casos.find(c => c.id === colId);
      if (col) {
        document.getElementById('corr-edit-nombre').textContent    = col.apellidos_nombres;
        document.getElementById('corr-edit-matricula').textContent = col.codigo_matricula;
        document.getElementById('corr-edit-id').value              = col.id;
        document.getElementById('corr-edit-cond-actual').value     = col.condicion;
        // Marcar condición actual
        corrSelCondUI(col.condicion);
      }
    } catch(e) {}

    // Cargar deudas corregibles
    try {
      const r2 = await fetch(`/caja/correccion/deudas/${colId}`);
      _deudas = await r2.json();
      renderDeudas();
    } catch(e) {
      document.getElementById('corr-deudas-lista').innerHTML =
        '<div style="color:#ef4444;font-size:12px;text-align:center;padding:10px">Error al cargar deudas</div>';
    }
  }

  function renderDeudas() {
    const lista = document.getElementById('corr-deudas-lista');
    if (!_deudas.length) {
      lista.innerHTML = '<div style="color:#888;font-size:12px;text-align:center;padding:20px">Sin deudas corregibles (anteriores al 01/04/2026)</div>';
      return;
    }

    const ESTADOS = ['vigente','condonada','exonerada','en_cobranza'];
    const COLORES = { vigente:'#f59e0b', condonada:'#22c55e', exonerada:'#60a5fa', en_cobranza:'#ef4444' };

    lista.innerHTML = _deudas.map(d => {
      const egActual = _cambiosDeuda[d.id] || d.estado_gestion;
      return `
        <div style="
          display:flex;align-items:center;gap:10px;
          padding:8px 10px;border-radius:7px;
          background:rgba(255,255,255,.02);
          border:1px solid var(--border,#2a2a3a);font-size:12px">
          <div style="flex:1;min-width:0">
            <div style="color:#eee;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">
              ${d.period_label || d.concept}
            </div>
            <div style="color:#888;font-size:10px;margin-top:1px">
              ${d.periodo || ''} · S/ ${d.balance.toFixed(2)}
              · <span style="color:${COLORES[egActual]||'#888'}">${egActual}</span>
            </div>
          </div>
          <select data-id="${d.id}"
                  onchange="CorrPanel.cambiarEstadoDeuda(${d.id},this.value)"
                  style="background:rgba(0,0,0,.3);border:1px solid var(--border,#2a2a3a);
                         color:#eee;border-radius:6px;padding:4px 6px;font-size:11px;cursor:pointer">
            ${ESTADOS.map(e => `<option value="${e}" ${e===egActual?'selected':''}>${e}</option>`).join('')}
          </select>
        </div>`;
    }).join('');
  }

  function cambiarEstadoDeuda(debtId, nuevoEstado) {
    _cambiosDeuda[debtId] = nuevoEstado;
    renderDeudas();
  }

  // ── Selección de condición ───────────────────────────────────
  function corrSelCond(val, btn) {
    _condNueva = val;
    corrSelCondUI(val);
  }

  function corrSelCondUI(val) {
    document.querySelectorAll('.corr-cond-btn').forEach(b => {
      const isActive = b.dataset.val === val;
      b.style.background = isActive ? 'rgba(245,158,11,.15)' : 'rgba(255,255,255,.03)';
      b.style.borderColor = isActive ? '#f59e0b' : 'var(--border,#2a2a3a)';
      b.style.color = isActive ? '#f59e0b' : '#888';
    });
    _condNueva = val;
  }

  function cerrarModalEdit() {
    document.getElementById('modalCorrEdit').style.display = 'none';
    _editId = null;
    _deudas = [];
    _cambiosDeuda = {};
    _condNueva = null;
  }

  // ── Guardar ──────────────────────────────────────────────────
  async function guardar() {
    const motivo = (document.getElementById('corr-motivo')?.value || '').trim();
    if (!motivo) {
      alert('El motivo de corrección es obligatorio.');
      document.getElementById('corr-motivo')?.focus();
      return;
    }

    const condActual = document.getElementById('corr-edit-cond-actual')?.value;
    const condicion  = _condNueva && _condNueva !== condActual ? _condNueva : undefined;

    const deudas = Object.entries(_cambiosDeuda).map(([id, eg]) => ({
      id: parseInt(id), estado_gestion: eg
    }));

    if (!condicion && deudas.length === 0) {
      alert('No hay cambios que guardar.');
      return;
    }

    try {
      const r = await fetch('/caja/correccion/aplicar', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          colegiado_id: _editId,
          condicion,
          motivo_nota: motivo,
          deudas,
        }),
      });
      const d = await r.json();
      if (d.ok) {
        cerrarModalEdit();
        // Mostrar confirmación
        const toast = document.getElementById('toastBox');
        if (toast) {
          toast.innerHTML = `<div class="toast toast-success">✅ ${d.mensaje}</div>`;
          setTimeout(() => { toast.innerHTML = ''; }, 3000);
        } else {
          alert(`✅ ${d.mensaje}`);
        }
        cargarCasos();  // Recargar lista
      } else {
        alert(`Error: ${d.error || d.mensaje}`);
      }
    } catch(e) {
      alert(`Error de conexión: ${e.message}`);
    }
  }

  // ── Log de cambios ───────────────────────────────────────────
  async function cargarLog() {
    const lista = document.getElementById('corr-lista');
    lista.innerHTML = '<div style="text-align:center;color:#888;padding:40px;font-size:13px">Cargando log...</div>';
    try {
      const r = await fetch('/caja/correccion/log');
      const rows = await r.json();
      if (!rows.length) {
        lista.innerHTML = '<div style="text-align:center;color:#888;padding:40px;font-size:13px">Sin correcciones registradas aún</div>';
        return;
      }
      lista.innerHTML = rows.map(r => `
        <div style="
          padding:10px 12px;border-radius:8px;margin-bottom:6px;
          background:rgba(255,255,255,.02);
          border:1px solid var(--border,#2a2a3a);font-size:12px">
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px">
            <span style="font-weight:600;color:#eee">
              ${r.apellidos_nombres} · ${r.codigo_matricula}
            </span>
            <span style="color:#888;font-size:10px">
              ${r.operador_nombre} · ${(r.created_at||'').substring(0,16)}
            </span>
          </div>
          <div style="color:#f59e0b;margin-bottom:4px;font-size:11px">
            📝 ${r.motivo}
          </div>
          <div style="color:#888;font-size:10px;white-space:pre-line">
            ${r.cambios}
          </div>
        </div>
      `).join('');
    } catch(e) {
      lista.innerHTML = `<div style="color:#ef4444;text-align:center;padding:20px">Error: ${e.message}</div>`;
    }
  }

  return {
    abrir, cerrar,
    cambiarTipo, irPagina,
    abrirEdicion,
    cambiarEstadoDeuda,
    corrSelCond,
    cerrarModalEdit,
    guardar,
  };
})();

// Funciones globales para onclick en HTML
function abrirCorreccion()     { CorrPanel.abrir(); }
function cerrarCorreccion()    { CorrPanel.cerrar(); }
function corrCambiarTipo(t,b)  { CorrPanel.cambiarTipo(t,b); }
function cerrarModalCorrEdit() { CorrPanel.cerrarModalEdit(); }
function corrGuardar()         { CorrPanel.guardar(); }
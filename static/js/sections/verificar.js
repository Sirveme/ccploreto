/* ═══════════════════════════════════════════
   verificar.js
   REGLA: funciones llamadas desde onclick="" 
   deben estar en scope global (fuera de DOMContentLoaded)
═══════════════════════════════════════════ */

/* ── Estado compartido (módulo simple) ──── */
var Verificar = (function () {

  var verifyBar   = null;
  var verifyInput = null;
  var dropdown    = null;
  var debTimer    = null;
  var ultimaQ     = '';

  /* ── Init ─────────────────────────────── */
  function init() {
    verifyBar   = document.getElementById('verifyBar');
    verifyInput = document.getElementById('verifyInput');
    if (!verifyInput) return;

    verifyInput.addEventListener('input',  onInput);
    verifyInput.addEventListener('keyup',   onInput);   // respaldo para teclados móviles
    verifyInput.addEventListener('keydown', onKeydown);
    document.addEventListener('click', function (e) {
      if (verifyBar && !verifyBar.contains(e.target)) cerrarDropdown();
    });
  }

  /* ── Toggle barra ──────────────────────── */
  function toggle() {
    if (!verifyBar) verifyBar = document.getElementById('verifyBar');
    if (!verifyInput) verifyInput = document.getElementById('verifyInput');
    if (!verifyBar) return;

    var abriendo = verifyBar.classList.toggle('open');
    if (abriendo && verifyInput) {
      setTimeout(function () { verifyInput.focus(); }, 350);
    } else {
      cerrarDropdown();
    }
  }

  /* ── Input handler ─────────────────────── */
  function onInput() {
    var q = verifyInput.value.trim();
    clearTimeout(debTimer);
    var esDni  = /^\d+$/.test(q);
    var minLen = esDni ? 5 : 3;
    if (q.length < minLen) { cerrarDropdown(); return; }
    debTimer = setTimeout(function () { buscarAuto(q); }, 280);
  }

  /* ── Keydown handler ───────────────────── */
  function onKeydown(e) {
    if (e.key === 'Escape') { cerrarDropdown(); return; }
    if (dropdown && dropdown.style.display !== 'none') {
      var items  = dropdown.querySelectorAll('.vd-item');
      var activo = dropdown.querySelector('.vd-item.activo');
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        var sig = activo ? activo.nextElementSibling : items[0];
        if (sig) { activo && activo.classList.remove('activo'); sig.classList.add('activo'); sig.scrollIntoView({block:'nearest'}); }
        return;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        var ant = activo ? activo.previousElementSibling : items[items.length - 1];
        if (ant) { activo && activo.classList.remove('activo'); ant.classList.add('activo'); ant.scrollIntoView({block:'nearest'}); }
        return;
      }
      if (e.key === 'Enter' && activo) { e.preventDefault(); activo.click(); return; }
    }
    if (e.key === 'Enter') consultar();
  }

  /* ── Dropdown ──────────────────────────── */
  function crearDropdown() {
    if (dropdown) return;
    // Inyectar estilo hover una sola vez
    if (!document.getElementById('vd-style')) {
      var s = document.createElement('style');
      s.id  = 'vd-style';
      s.textContent = '.vd-item:hover,.vd-item.activo{background:#f0f8f4!important}';
      document.head.appendChild(s);
    }
    dropdown = document.createElement('div');
    dropdown.id = 'verifyDropdown';
    dropdown.style.cssText =
      'position:absolute;top:100%;left:0;right:0;background:#fff;' +
      'border-radius:0 0 10px 10px;box-shadow:0 8px 24px rgba(0,0,0,.18);' +
      'z-index:500;overflow:hidden;max-height:320px;overflow-y:auto;display:none';
    verifyBar.style.position = 'relative';
    verifyBar.style.overflow = 'visible';
    verifyBar.appendChild(dropdown);
  }

  function abrirDropdown(html) {
    crearDropdown();
    dropdown.innerHTML = html;
    dropdown.style.display = 'block';
  }

  function cerrarDropdown() {
    if (dropdown) dropdown.style.display = 'none';
  }

  /* ── Autocomplete fetch ─────────────────── */
  async function buscarAuto(q) {
    ultimaQ = q;
    try {
      var res  = await fetch('/consulta/habilidad/buscar?q=' + encodeURIComponent(q));

      // Si el endpoint no existe o da error, mostrarlo en el dropdown
      if (!res.ok) {
        abrirDropdown(
          '<div style="padding:14px 16px;font-size:12px;color:#c62828;text-align:center">' +
          'Endpoint no disponible (' + res.status + '). Verifica que /consulta/habilidad/buscar existe.</div>'
        );
        return;
      }

      var data = await res.json();

      if (!data.resultados || data.resultados.length === 0) {
        abrirDropdown(
          '<div style="padding:14px 16px;font-size:13px;color:#999;text-align:center">' +
          'Sin resultados para <em>"' + esc(q) + '"</em></div>'
        );
        return;
      }

      var html = '<div style="padding:6px 0">';
      html += '<div style="padding:4px 16px 6px;font-size:10px;font-weight:700;' +
              'letter-spacing:1px;text-transform:uppercase;color:#aaa">' +
              data.resultados.length + ' resultado' +
              (data.resultados.length !== 1 ? 's' : '') + '</div>';

      data.resultados.forEach(function (r) {
        var esHabil  = r.es_habil;
        var dotC  = esHabil ? '#4caf50' : '#e57373';
        var badBg = esHabil ? '#e8f5e9' : '#fce4ec';
        var badTx = esHabil ? '#2e7d32' : '#c62828';
        html +=
          '<div class="vd-item" data-matricula="' + esc(r.codigo_matricula) + '" ' +
          'style="padding:10px 16px;cursor:pointer;display:flex;align-items:center;' +
          'gap:10px;border-bottom:1px solid #f5f5f5">' +
            '<span style="width:8px;height:8px;border-radius:50%;background:' + dotC + ';flex-shrink:0"></span>' +
            '<div style="flex:1;min-width:0">' +
              '<div style="font-size:13px;font-weight:600;color:#1a2e22;' +
                   'white-space:nowrap;overflow:hidden;text-overflow:ellipsis">' +
                esc(r.apellidos_nombres) +
              '</div>' +
              '<div style="font-size:11px;color:#999;margin-top:1px">' +
                'Mat. ' + esc(r.codigo_matricula) +
                (r.dni ? ' · DNI ' + esc(r.dni) : '') +
              '</div>' +
            '</div>' +
            '<span style="font-size:10px;font-weight:700;padding:3px 8px;border-radius:4px;' +
                 'white-space:nowrap;background:' + badBg + ';color:' + badTx + '">' +
              r.condicion_texto +
            '</span>' +
          '</div>';
      });
      html += '</div>';
      abrirDropdown(html);

      dropdown.querySelectorAll('.vd-item').forEach(function (item) {
        item.addEventListener('click', function () {
          cerrarDropdown();
          verifyInput.value = item.dataset.matricula;
          consultarPorMatricula(item.dataset.matricula);
        });
      });

    } catch (e) {
      abrirDropdown(
        '<div style="padding:14px 16px;font-size:12px;color:#c62828;text-align:center">' +
        'Error al conectar con el servidor. Verifique su conexión.</div>'
      );
    }
  }

  /* ── Consulta por matrícula (al seleccionar) */
  async function consultarPorMatricula(matricula) {
    var btn = document.querySelector('.btn-consultar');
    if (btn) btn.disabled = true;
    try {
      var res  = await fetch('/consulta/habilidad/verificar?q=' + encodeURIComponent(matricula));
      var data = await res.json();
      if (!res.ok || !data.encontrado) {
        mostrarModal(null, (data && (data.detail || data.mensaje)) || 'No encontrado.');
      } else {
        mostrarModal(data.datos);
      }
    } catch (e) {
      mostrarModal(null, 'Error de conexión.');
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  /* ── Consulta manual (botón / Enter) ─────── */
  async function consultar() {
    if (!verifyInput) verifyInput = document.getElementById('verifyInput');
    var q = verifyInput ? verifyInput.value.trim() : '';
    if (q.length < 3) return;
    cerrarDropdown();

    var btn = document.querySelector('.btn-consultar');
    if (btn) { btn.textContent = '…'; btn.disabled = true; }

    try {
      var res  = await fetch('/consulta/habilidad/verificar?q=' + encodeURIComponent(q));
      var data = await res.json();
      if (!res.ok || !data.encontrado) {
        mostrarModal(null, (data && (data.detail || data.mensaje)) || 'No encontrado.');
      } else {
        mostrarModal(data.datos);
      }
    } catch (e) {
      mostrarModal(null, 'Error de conexión. Intente de nuevo.');
    } finally {
      if (btn) {
        btn.innerHTML = '<span class="mi sm">search</span> Consultar';
        btn.disabled = false;
      }
    }
  }

  /* ── Mostrar modal resultado ─────────────── */
  function mostrarModal(d, errorMsg) {
    var st = document.getElementById('habStatus');
    var wb = document.getElementById('habWeb');
    if (!st) return;

    if (!d) {
      document.getElementById('habNombre').textContent    = 'Sin resultado';
      document.getElementById('habMatricula').textContent = errorMsg || 'No encontrado.';
      st.className = 'hab-status inhabil';
      st.querySelector('.mi').textContent = 'search_off';
      document.getElementById('habLabel').textContent = 'NO ENCONTRADO';
      if (wb) wb.style.display = 'none';
    } else {
      document.getElementById('habNombre').textContent    = d.apellidos_nombres;
      document.getElementById('habMatricula').textContent = 'Matrícula ' + d.codigo_matricula;
      var esHabil = d.es_habil;
      st.className = 'hab-status ' + (esHabil ? 'habil' : 'inhabil');
      st.querySelector('.mi').textContent = esHabil ? 'verified' : 'cancel';
      document.getElementById('habLabel').textContent = d.condicion_texto;
      if (wb) {
        if (d.autorizo_web && d.url_web) {
          document.getElementById('habFoto').src = d.foto_url || '/static/img/default-avatar.png';
          document.getElementById('habUrl').href = d.url_web;
          document.getElementById('habEspecialidad').textContent = d.especialidad || 'Contador Público';
          wb.style.display = 'flex';
        } else {
          wb.style.display = 'none';
        }
      }
      var pl = document.getElementById('habPerfilLink');
      if (pl) {
        pl.style.display = (esHabil && d.autorizo_perfil_publico) ? 'inline-flex' : 'none';
        if (esHabil && d.autorizo_perfil_publico)
          pl.href = '/colegiado/' + d.codigo_matricula;
      }
    }
    if (window.openModal) window.openModal('modalHab');
  }

  function esc(s) {
    return String(s || '')
      .replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  /* ── API pública del módulo ─────────────── */
  return {
    init:    init,
    toggle:  toggle,
    consultar: consultar,
    cerrarModal: function () { if (window.closeModal) window.closeModal('modalHab'); }
  };

})();

/* ══════════════════════════════════════════
   FUNCIONES GLOBALES — las llaman los onclick=""
   Deben estar FUERA de DOMContentLoaded
══════════════════════════════════════════ */
function toggleVerify()        { Verificar.toggle(); }
function consultarHabilidad()  { Verificar.consultar(); }
function closeModalHab()       { Verificar.cerrarModal(); }

/* Inicializar cuando el DOM esté listo */
document.addEventListener('DOMContentLoaded', function () {
  Verificar.init();
});
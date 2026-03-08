/* ═══════════════════════════════════════════
   verificar.js
   - Barra desplegable con autocomplete en tiempo real
   - DNI: activa desde el 5to dígito
   - Apellidos: activa desde la 3ra letra
   - Al seleccionar fila → llama endpoint completo → modal
═══════════════════════════════════════════ */
document.addEventListener('DOMContentLoaded', function () {

  var verifyBar     = document.getElementById('verifyBar');
  var verifyInput   = document.getElementById('verifyInput');
  var dropdown      = null;
  var debounceTimer = null;
  var ultimaQuery   = '';

  /* ── Toggle barra ──────────────────────── */
  window.toggleVerify = function () {
    if (!verifyBar) return;
    var abriendo = verifyBar.classList.toggle('open');
    if (abriendo && verifyInput) {
      setTimeout(function () { verifyInput.focus(); }, 350);
    } else {
      cerrarDropdown();
    }
  };

  /* ── Dropdown ──────────────────────────── */
  function crearDropdown() {
    if (dropdown) return;
    dropdown = document.createElement('div');
    dropdown.id = 'verifyDropdown';
    dropdown.style.cssText =
      'position:absolute;top:100%;left:0;right:0;background:white;' +
      'border-radius:0 0 10px 10px;box-shadow:0 8px 24px rgba(0,0,0,.18);' +
      'z-index:500;overflow:hidden;max-height:320px;overflow-y:auto;display:none';
    verifyBar.style.position = 'relative';
    verifyBar.style.overflow = 'visible';
    verifyBar.appendChild(dropdown);

    // Estilo hover
    var s = document.createElement('style');
    s.textContent = '.vd-item:hover,.vd-item.activo{background:#f0f8f4!important}';
    document.head.appendChild(s);
  }

  function abrirDropdown(html) {
    crearDropdown();
    dropdown.innerHTML = html;
    dropdown.style.display = 'block';
  }

  function cerrarDropdown() {
    if (dropdown) dropdown.style.display = 'none';
  }

  /* ── Eventos del input ─────────────────── */
  if (verifyInput) {

    verifyInput.addEventListener('input', function () {
      var q = verifyInput.value.trim();
      clearTimeout(debounceTimer);
      var esDni  = /^\d+$/.test(q);
      var minLen = esDni ? 5 : 3;
      if (q.length < minLen) { cerrarDropdown(); return; }
      if (q === ultimaQuery)  return;
      debounceTimer = setTimeout(function () { buscarAutocomplete(q); }, 280);
    });

    verifyInput.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { cerrarDropdown(); return; }

      // Navegación con flechas dentro del dropdown
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

      if (e.key === 'Enter') consultarHabilidad();
    });
  }

  document.addEventListener('click', function (e) {
    if (verifyBar && !verifyBar.contains(e.target)) cerrarDropdown();
  });

  /* ── Autocomplete fetch ────────────────── */
  async function buscarAutocomplete(q) {
    ultimaQuery = q;
    try {
      var res  = await fetch('/consulta/habilidad/buscar?q=' + encodeURIComponent(q));
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
              data.resultados.length + ' resultado' + (data.resultados.length !== 1 ? 's' : '') + '</div>';

      data.resultados.forEach(function (r) {
        var esHabil  = r.es_habil;
        var dotColor = esHabil ? '#4caf50' : '#e57373';
        var badgeBg  = esHabil ? '#e8f5e9' : '#fce4ec';
        var badgeTxt = esHabil ? '#2e7d32' : '#c62828';

        html +=
          '<div class="vd-item" data-matricula="' + esc(r.codigo_matricula) + '" ' +
          'style="padding:10px 16px;cursor:pointer;display:flex;align-items:center;' +
          'gap:10px;border-bottom:1px solid #f5f5f5">' +
            '<span style="width:8px;height:8px;border-radius:50%;background:' + dotColor + ';flex-shrink:0"></span>' +
            '<div style="flex:1;min-width:0">' +
              '<div style="font-size:13px;font-weight:600;color:#1a2e22;' +
                   'white-space:nowrap;overflow:hidden;text-overflow:ellipsis">' + esc(r.apellidos_nombres) + '</div>' +
              '<div style="font-size:11px;color:#999;margin-top:1px">' +
                'Mat. ' + esc(r.codigo_matricula) + (r.dni ? ' · DNI ' + esc(r.dni) : '') +
              '</div>' +
            '</div>' +
            '<span style="font-size:10px;font-weight:700;padding:3px 8px;border-radius:4px;' +
                 'background:' + badgeBg + ';color:' + badgeTxt + ';white-space:nowrap">' +
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

    } catch (err) {
      cerrarDropdown();
    }
  }

  /* ── Consulta completa al seleccionar ──── */
  async function consultarPorMatricula(matricula) {
    var btn = document.querySelector('.btn-consultar');
    if (btn) btn.disabled = true;
    try {
      var res  = await fetch('/consulta/habilidad/verificar?q=' + encodeURIComponent(matricula));
      var data = await res.json();
      if (!res.ok || !data.encontrado) {
        mostrarResultadoHabilidad(null, (data && data.mensaje) || 'No se pudo consultar.');
      } else {
        mostrarResultadoHabilidad(data.datos);
      }
    } catch (e) {
      mostrarResultadoHabilidad(null, 'Error de conexión.');
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  /* ── Consulta manual (botón / Enter) ───── */
  window.consultarHabilidad = async function () {
    var q = verifyInput ? verifyInput.value.trim() : '';
    if (q.length < 3) return;
    cerrarDropdown();
    var btn = document.querySelector('.btn-consultar');
    if (btn) { btn.textContent = '…'; btn.disabled = true; }
    try {
      var res  = await fetch('/consulta/habilidad/verificar?q=' + encodeURIComponent(q));
      var data = await res.json();
      if (!res.ok || !data.encontrado) {
        mostrarResultadoHabilidad(null, (data && (data.detail || data.mensaje)) || 'No encontrado.');
      } else {
        mostrarResultadoHabilidad(data.datos);
      }
    } catch (e) {
      mostrarResultadoHabilidad(null, 'Error de conexión.');
    } finally {
      if (btn) { btn.innerHTML = '<span class="mi sm">search</span> Consultar'; btn.disabled = false; }
    }
  };

  /* ── Modal resultado ───────────────────── */
  window.mostrarResultadoHabilidad = function (d, errorMsg) {
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

      // Link al perfil público (solo hábiles que autorizaron)
      var perfilLink = document.getElementById('habPerfilLink');
      if (perfilLink) {
        if (esHabil && d.autorizo_perfil_publico) {
          perfilLink.href = '/colegiado/' + d.codigo_matricula;
          perfilLink.style.display = 'inline-flex';
        } else {
          perfilLink.style.display = 'none';
        }
      }
    }

    window.openModal('modalHab');
  };

  window.closeModalHab = function () { window.closeModal('modalHab'); };

  function esc(s) {
    return String(s || '')
      .replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

});
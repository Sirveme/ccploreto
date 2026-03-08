/* ═══════════════════════════════════════════
   verificar.js — Verificar Habilidad
   Barra desplegable en header + modal resultado
═══════════════════════════════════════════ */
document.addEventListener('DOMContentLoaded', function () {

  /* ── Barra desplegable ─────────────────── */
  var verifyBar   = document.getElementById('verifyBar');
  var verifyInput = document.getElementById('verifyInput');

  window.toggleVerify = function () {
    if (!verifyBar) return;
    var isOpen = verifyBar.classList.toggle('open');
    if (isOpen && verifyInput) {
      setTimeout(function () { verifyInput.focus(); }, 350);
    }
  };

  if (verifyInput) {
    verifyInput.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') consultarHabilidad();
    });
  }

  /* ── Consulta al endpoint ──────────────── */
  window.consultarHabilidad = async function () {
    var q = verifyInput ? verifyInput.value.trim() : '';
    if (q.length < 3) return;

    var btn = document.querySelector('.btn-consultar');
    if (btn) { btn.textContent = '…'; btn.disabled = true; }

    try {
      var res  = await fetch('/consulta/habilidad/verificar?q=' + encodeURIComponent(q));
      var data = await res.json();

      if (!res.ok) {
        mostrarResultadoHabilidad(null, data.detail || 'No se pudo consultar.');
      } else if (!data.encontrado) {
        mostrarResultadoHabilidad(null, data.mensaje);
      } else {
        mostrarResultadoHabilidad(data.datos);
      }
    } catch (err) {
      mostrarResultadoHabilidad(null, 'Error de conexión. Intente de nuevo.');
    } finally {
      if (btn) { btn.innerHTML = '<span class="mi sm">search</span> Consultar'; btn.disabled = false; }
    }
  };

  /* ── Mostrar resultado en modal ───────── */
  window.mostrarResultadoHabilidad = function (d, errorMsg) {
    var st  = document.getElementById('habStatus');
    var wb  = document.getElementById('habWeb');
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
          document.getElementById('habUrl').href  = d.url_web;
          document.getElementById('habEspecialidad').textContent = d.especialidad || 'Contador Público';
          wb.style.display = 'flex';
        } else {
          wb.style.display = 'none';
        }
      }
    }
    window.openModal('modalHab');
  };

  window.closeModalHab = function () { window.closeModal('modalHab'); };

});
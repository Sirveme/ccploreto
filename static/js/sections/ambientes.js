/* ═══════════════════════════════════════════
   ambientes.js — Reserva de ambientes
   TODO: conectar modal con endpoint de disponibilidad
═══════════════════════════════════════════ */
document.addEventListener('DOMContentLoaded', function () {

  window.abrirReserva = function (ambiente) {
    // TODO: fetch('/ambientes/disponibilidad?ambiente=' + encodeURIComponent(ambiente))
    //       y poblar el modal con horarios disponibles
    alert('Reserva de "' + ambiente + '" — próximamente con calendario en tiempo real.');
  };

});
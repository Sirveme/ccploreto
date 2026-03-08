/* ═══════════════════════════════════════════
   nav.js — Dropdowns del desktop nav
   Funciones globales para onclick=""
═══════════════════════════════════════════ */

/* ── Toggle dropdown desktop ──────────────
   Uso: onclick="navToggle('institucional')"
──────────────────────────────────────────── */
function navToggle(id) {
  var grupo   = document.getElementById('nav-' + id);
  var estaAbierto = grupo && grupo.classList.contains('open');

  // Cerrar todos primero
  document.querySelectorAll('.dns-group.open').forEach(function (g) {
    g.classList.remove('open');
  });

  // Abrir el pedido (si estaba cerrado)
  if (!estaAbierto && grupo) {
    grupo.classList.add('open');
  }
}

/* Cerrar dropdowns al click fuera */
document.addEventListener('click', function (e) {
  if (!e.target.closest('.dns-group')) {
    document.querySelectorAll('.dns-group.open').forEach(function (g) {
      g.classList.remove('open');
    });
  }
});

/* Cerrar dropdowns al hacer Escape */
document.addEventListener('keydown', function (e) {
  if (e.key === 'Escape') {
    document.querySelectorAll('.dns-group.open').forEach(function (g) {
      g.classList.remove('open');
    });
  }
});

/* ── Toggle grupos del drawer ──────────────
   Uso: onclick="drawerGrupo(this)"
──────────────────────────────────────────── */
function drawerGrupo(btn) {
  var grupo = btn.closest('.drawer-group');
  if (grupo) grupo.classList.toggle('open');
}
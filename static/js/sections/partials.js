/* ═══════════════════════════════════════════
   partials.js
   Modal universal que carga plantillas parciales
   via fetch() sin abrir pestañas nuevas.

   Uso desde HTML:
     onclick="abrirPartial('institucional','Institucional','account_balance')"
     onclick="abrirPartial('transparencia','Transparencia','folder_open')"
═══════════════════════════════════════════ */

/* Cache de partials ya cargados */
var _partialCache = {};

/* Mapa de partials disponibles */
var PARTIALS = {
  'institucional': {
    titulo: 'Institucional',
    icono:  'account_balance',
    url:    '/partials/institucional'
  },
  'transparencia': {
    titulo: 'Transparencia',
    icono:  'folder_open',
    url:    '/partials/transparencia'
  }
  /* Agregar aquí los próximos:
  'colegiados':    { titulo: 'Colegiados',    icono: 'badge',          url: '/partials/colegiados'    },
  'reglamento':    { titulo: 'Reglamento',    icono: 'gavel',          url: '/partials/reglamento'    },
  'convenios':     { titulo: 'Convenios',     icono: 'handshake',      url: '/partials/convenios'     },
  */
};

/* ── Abrir modal con partial ──────────────── */
async function abrirPartial(key, tituloOverride, iconoOverride) {
  var cfg     = PARTIALS[key] || {};
  var titulo  = tituloOverride || cfg.titulo || key;
  var icono   = iconoOverride  || cfg.icono  || 'info';
  var url     = cfg.url || ('/partials/' + key);

  var modal   = document.getElementById('modalPartial');
  var content = document.getElementById('modalPartialContent');
  var titleEl = document.getElementById('modalPartialTitle');
  var iconEl  = document.getElementById('modalPartialIcon');

  if (!modal) return;

  // Actualizar header
  titleEl.textContent = titulo;
  iconEl.textContent  = icono;

  // Mostrar spinner mientras carga
  content.innerHTML =
    '<div style="padding:40px;text-align:center;color:#5a7060">' +
    '<span class="mi" style="font-size:36px;color:#d8e8dc;display:block;margin-bottom:12px">hourglass_empty</span>' +
    'Cargando ' + titulo.toLowerCase() + '…</div>';

  modal.classList.add('open');
  document.body.style.overflow = 'hidden';

  // Scroll al tope del contenido
  content.scrollTop = 0;

  // Usar cache si ya se cargó antes
  if (_partialCache[key]) {
    content.innerHTML = _partialCache[key];
    _reejecutarScripts(content);
    return;
  }

  // Fetch del partial
  try {
    var res = await fetch(url, { credentials: 'same-origin' });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    var html = await res.text();
    _partialCache[key] = html;
    content.innerHTML  = html;
    _reejecutarScripts(content);
  } catch (err) {
    content.innerHTML =
      '<div style="padding:32px 24px;text-align:center">' +
      '<span class="mi" style="font-size:40px;color:#e57373;display:block;margin-bottom:12px">error_outline</span>' +
      '<p style="font-size:14px;color:#c62828;font-weight:600">No se pudo cargar el contenido</p>' +
      '<p style="font-size:12px;color:#888;margin-top:6px">' + err.message + '</p>' +
      '</div>';
  }
}

/* ── Cerrar modal ─────────────────────────── */
function cerrarPartial() {
  var modal = document.getElementById('modalPartial');
  if (modal) {
    modal.classList.remove('open');
    document.body.style.overflow = '';
  }
}

/* ── Re-ejecutar <script> dentro del partial ─
   Los scripts inyectados via innerHTML no se ejecutan
   automáticamente — hay que recrearlos.
──────────────────────────────────────────── */
function _reejecutarScripts(container) {
  container.querySelectorAll('script').forEach(function (oldScript) {
    var newScript = document.createElement('script');
    Array.from(oldScript.attributes).forEach(function (attr) {
      newScript.setAttribute(attr.name, attr.value);
    });
    newScript.textContent = oldScript.textContent;
    oldScript.parentNode.replaceChild(newScript, oldScript);
  });
}

/* ── Cerrar al click fuera del modal ─────── */
document.addEventListener('DOMContentLoaded', function () {
  var modal = document.getElementById('modalPartial');
  if (modal) {
    modal.addEventListener('click', function (e) {
      if (e.target === modal) cerrarPartial();
    });
  }

  /* Swipe down para cerrar (mobile) */
  var box      = document.getElementById('modalPartialBox');
  var startY   = 0;
  var dragging = false;

  if (box) {
    box.addEventListener('touchstart', function (e) {
      startY   = e.touches[0].clientY;
      dragging = true;
    }, { passive: true });

    box.addEventListener('touchmove', function (e) {
      if (!dragging) return;
      var dy = e.touches[0].clientY - startY;
      if (dy > 0) box.style.transform = 'translateY(' + dy + 'px)';
    }, { passive: true });

    box.addEventListener('touchend', function (e) {
      dragging = false;
      var dy = e.changedTouches[0].clientY - startY;
      if (dy > 80) {
        cerrarPartial();
      }
      box.style.transform = '';
    }, { passive: true });
  }
});
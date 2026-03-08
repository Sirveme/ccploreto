/* ═══════════════════════════════════════════
   videos.js — Modal de video
═══════════════════════════════════════════ */
document.addEventListener('DOMContentLoaded', function () {

  var vidModal     = document.getElementById('vidModal');
  var vidContainer = document.getElementById('vidContainer');
  var vidTitleEl   = document.getElementById('vidTitle');

  window.openVideo = function (url, title) {
    if (!vidModal) return;
    // Actualizar título
    if (vidTitleEl) {
      var span = vidTitleEl.querySelector('span');
      vidTitleEl.childNodes[0].textContent = title + ' ';
      if (span) span.textContent = 'CCPL · Guías del sistema';
    }

    // Inyectar iframe si hay URL real
    if (vidContainer) {
      if (url && !url.startsWith('VIDEO_URL')) {
        vidContainer.innerHTML = '<iframe src="' + url + '" allow="autoplay;encrypted-media" allowfullscreen></iframe>';
      } else {
        vidContainer.innerHTML =
          '<div class="vid-placeholder">' +
          '<span class="mi">play_circle</span>' +
          '<span style="color:rgba(255,255,255,.4);font-size:14px">Video próximamente disponible</span>' +
          '</div>';
      }
    }

    vidModal.classList.add('open');
    document.body.style.overflow = 'hidden';
  };

  window.closeVideo = function () {
    if (!vidModal) return;
    vidModal.classList.remove('open');
    if (vidContainer) vidContainer.innerHTML = '';
    document.body.style.overflow = '';
  };

  // Cerrar al click fuera
  if (vidModal) {
    vidModal.addEventListener('click', function (e) {
      if (e.target === vidModal) window.closeVideo();
    });
  }

});
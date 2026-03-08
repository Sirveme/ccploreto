/* ═══════════════════════════════════════════
   ccp-loreto.js — Base: Carrusel + Drawer
   Sin inline scripts en el HTML
═══════════════════════════════════════════ */
document.addEventListener('DOMContentLoaded', function () {

  /* ── CARRUSEL ─────────────────────────── */
  var track  = document.getElementById('carTrack');
  if (track) {
    var slides = track.querySelectorAll('.carousel-slide');
    var dots   = document.querySelectorAll('.car-dot');
    var ci     = 0;
    var timer;

    function goTo(n) {
      slides[ci].classList.remove('active');
      dots[ci] && dots[ci].classList.remove('car-dot-active');
      ci = (n + slides.length) % slides.length;
      slides[ci].classList.add('active');
      dots[ci] && dots[ci].classList.add('car-dot-active');
      track.style.transform = 'translateX(-' + (ci * 100) + '%)';
    }

    function next() { goTo(ci + 1); }
    function prev() { goTo(ci - 1); }

    function resetTimer() {
      clearInterval(timer);
      timer = setInterval(next, 5000);
    }

    // Botones prev / next del HTML (onclick="carMove()")
    window.carMove = function (d) { goTo(ci + d); resetTimer(); };

    // Dots
    dots.forEach(function (d, i) {
      d.addEventListener('click', function () { goTo(i); resetTimer(); });
    });

    // Swipe táctil
    var touchX = 0;
    track.addEventListener('touchstart', function (e) {
      touchX = e.touches[0].clientX;
    }, { passive: true });
    track.addEventListener('touchend', function (e) {
      var dx = e.changedTouches[0].clientX - touchX;
      if (Math.abs(dx) > 40) { dx < 0 ? next() : prev(); resetTimer(); }
    }, { passive: true });

    // Botones del DOM con clase
    var btnPrev = document.querySelector('.carousel-ctrl.prev');
    var btnNext = document.querySelector('.carousel-ctrl.next');
    if (btnPrev) btnPrev.addEventListener('click', function () { prev(); resetTimer(); });
    if (btnNext) btnNext.addEventListener('click', function () { next(); resetTimer(); });

    resetTimer();
  }

  /* ── DRAWER ───────────────────────────── */
  var drawer        = document.getElementById('drawer');
  var drawerOverlay = document.getElementById('drawerOverlay');
  var menuBtn       = document.getElementById('menuBtn');

  function openDrawer() {
    if (!drawer) return;
    drawer.classList.add('open');
    drawerOverlay.classList.add('open');
    document.body.style.overflow = 'hidden';
  }

  function closeDrawer() {
    if (!drawer) return;
    drawer.classList.remove('open');
    drawerOverlay.classList.remove('open');
    document.body.style.overflow = '';
  }

  if (menuBtn)       menuBtn.addEventListener('click', openDrawer);
  if (drawerOverlay) drawerOverlay.addEventListener('click', closeDrawer);

  // Exponer para botón del HTML
  window.openDrawer  = openDrawer;
  window.closeDrawer = closeDrawer;

  /* ── MODAL BASE (compartido) ─────────── */
  window.openModal = function (id) {
    var m = document.getElementById(id);
    if (m) { m.classList.add('open'); document.body.style.overflow = 'hidden'; }
  };
  window.closeModal = function (id) {
    var m = document.getElementById(id);
    if (m) { m.classList.remove('open'); document.body.style.overflow = ''; }
  };

  // Cerrar modal al hacer click fuera
  document.querySelectorAll('.modal-overlay').forEach(function (m) {
    m.addEventListener('click', function (e) {
      if (e.target === m) { m.classList.remove('open'); document.body.style.overflow = ''; }
    });
  });

});
/* ═══════════════════════════════════════════
   convenios.js — Tabs de filtro por categoría
═══════════════════════════════════════════ */
document.addEventListener('DOMContentLoaded', function () {

  var tabs = document.querySelectorAll('#convTabs .tab-btn');
  var cards = document.querySelectorAll('#convGrid .conv-card');

  tabs.forEach(function (btn) {
    btn.addEventListener('click', function () {
      tabs.forEach(function (b) { b.classList.remove('active'); });
      btn.classList.add('active');

      var cat = btn.dataset.cat;
      cards.forEach(function (card) {
        var match = cat === 'todos' || card.dataset.cat === cat;
        card.classList.toggle('visible', match);
      });
    });
  });

});
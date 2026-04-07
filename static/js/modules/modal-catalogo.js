/**
 * modal-catalogo.js — CCPL
 * Módulo compartido: window.Modales.catalogo
 * Fuente de datos: GET /api/publico/catalogo  (api_tienda.py)
 *
 * Uso:
 *   <link> (no requiere CSS propio; estilos heredados del portal)
 *   <script src="/static/js/modules/modal-catalogo.js"></script>
 *   Modales.catalogo.abrir()
 *
 * Acciones "Pagar con Tarjeta" / "Ya pagué" delegan en:
 *   - Modales.pagoLinea   (si existe)
 *   - Modales.reportarPago (si existe)
 * Si el host no los define, guarda el carrito en sessionStorage
 * y navega a /reactivarse (fallback seguro).
 */

(function () {
  'use strict';

  const $ = (id) => document.getElementById(id);

  // Fallback emoji por código cuando el item no trae imagen_url
  function _iconoPorCodigo(codigo) {
    const map = {
      'MERC-GOR': '🧢',
      'MERC-POL': '👕',
      'MERC-LAP': '✏️',
      'MERC-PIN': '📌',
      'MERC-MED': '🥇',
      'MERC-TAS': '☕',
      'MERC-FOL': '📁',
    };
    return map[codigo] || '🛍️';
  }

  // Estilos del modal catálogo — autocontenidos (no dependen de Material Icons
  // ni de CSS externo). Inyectados una sola vez al cargar el módulo.
  (function _injectStyles() {
    if (document.getElementById('modal-catalogo-styles')) return;
    const s = document.createElement('style');
    s.id = 'modal-catalogo-styles';
    s.textContent = `
      /* ── Overlay (scope aislado — no hereda de .modal-overlay global) ── */
      #modal-catalogo {
        position: fixed !important;
        inset: 0 !important;
        background: rgba(0,0,0,.65) !important;
        backdrop-filter: blur(4px);
        -webkit-backdrop-filter: blur(4px);
        display: none !important;
        align-items: center !important;
        justify-content: center !important;
        z-index: 9999 !important;
        padding: 16px !important;
        opacity: 1 !important;
        pointer-events: none;
        transition: none !important;
      }
      #modal-catalogo.open {
        display: flex !important;
        pointer-events: auto !important;
      }

      /* ── Caja del modal — tamaño fijo ── */
      #modal-catalogo .mc-box {
        width: min(560px, 95vw) !important;
        height: min(680px, 92vh) !important;
        max-width: none !important;
        max-height: none !important;
        display: flex !important;
        flex-direction: column !important;
        overflow: hidden !important;
        background: linear-gradient(180deg, #0f172a 0%, #0b1120 100%) !important;
        border: 1px solid rgba(255,255,255,.08) !important;
        border-radius: 18px !important;
        box-shadow: 0 30px 80px rgba(0,0,0,.55) !important;
        color: #e2e8f0 !important;
        font-family: system-ui, -apple-system, 'Inter', sans-serif !important;
        transform: none !important;
        margin: 0 !important;
      }

      /* ── Header fijo ── */
      #modal-catalogo .mc-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 16px 20px;
        border-bottom: 1px solid rgba(255,255,255,.08);
        flex-shrink: 0;
      }
      #modal-catalogo .mc-icon {
        font-size: 28px;
        line-height: 1;
      }
      #modal-catalogo .mc-title {
        font-size: 16px;
        font-weight: 700;
        color: #f1f5f9;
      }
      #modal-catalogo .mc-sub {
        font-size: 12px;
        color: #94a3b8;
        margin-top: 2px;
      }
      #modal-catalogo .mc-close {
        width: 32px; height: 32px;
        border-radius: 50%;
        border: 1px solid rgba(255,255,255,.15);
        background: rgba(255,255,255,.06);
        color: #94a3b8;
        cursor: pointer;
        font-size: 14px;
        display: flex; align-items: center; justify-content: center;
        flex-shrink: 0;
        font-family: inherit;
      }
      #modal-catalogo .mc-close:hover {
        background: rgba(239,68,68,.2);
        color: #f87171;
      }

      /* ── Filtros (pills) ── */
      #modal-catalogo #cat-filtros {
        flex-shrink: 0;
        display: flex;
        gap: 6px;
        overflow-x: auto;
        padding: 10px 16px;
        border-bottom: 1px solid rgba(255,255,255,.06);
        scrollbar-width: none;
      }
      #modal-catalogo #cat-filtros::-webkit-scrollbar { display: none; }
      #modal-catalogo .cat-pill {
        padding: 4px 14px;
        border-radius: 20px;
        border: 1px solid rgba(255,255,255,.15);
        background: rgba(255,255,255,.05);
        color: #94a3b8;
        font-size: 12px;
        cursor: pointer;
        white-space: nowrap;
        transition: all .2s;
        font-family: inherit;
      }
      #modal-catalogo .cat-pill:hover {
        border-color: rgba(16,185,129,.4);
        color: #d1fae5;
      }
      #modal-catalogo .cat-pill.activo {
        background: linear-gradient(135deg,#10b981,#059669);
        color: #fff;
        border-color: transparent;
      }

      /* ── Lista de items (scroll) ── */
      #modal-catalogo #cat-lista {
        flex: 1;
        overflow-y: auto;
        padding: 12px 16px;
        display: flex;
        flex-direction: column;
        gap: 8px;
        scrollbar-width: thin;
        scrollbar-color: rgba(16,185,129,.4) transparent;
      }
      #modal-catalogo #cat-lista::-webkit-scrollbar { width: 4px; }
      #modal-catalogo #cat-lista::-webkit-scrollbar-thumb {
        background: rgba(16,185,129,.4);
        border-radius: 4px;
      }
      #modal-catalogo #cat-lista::-webkit-scrollbar-track { background: transparent; }

      /* ── Cards de items ── */
      #modal-catalogo .cat-item {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 10px 12px;
        border-radius: 10px;
        background: rgba(255,255,255,.04);
        border: 1px solid rgba(255,255,255,.07);
        transition: border-color .2s;
      }
      #modal-catalogo .cat-item:hover { border-color: rgba(16,185,129,.3); }
      #modal-catalogo .cat-item.cat-sel { border-color: rgba(16,185,129,.5); }
      #modal-catalogo .cat-item.cat-agotado { opacity: .55; }
      #modal-catalogo .cat-item-img,
      #modal-catalogo .cat-item-noimg {
        width: 48px; height: 48px;
        border-radius: 8px;
        object-fit: cover;
        flex-shrink: 0;
        background: rgba(255,255,255,.06);
        display: flex; align-items: center; justify-content: center;
        font-size: 1.6rem;
      }
      #modal-catalogo .cat-item-body {
        flex: 1;
        min-width: 0;
        display: flex;
        flex-direction: column;
        gap: 2px;
      }
      #modal-catalogo .cat-item-nombre {
        font-size: 13px;
        color: #e2e8f0;
        font-weight: 500;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      #modal-catalogo .cat-item-desc {
        font-size: 11px;
        color: #64748b;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      #modal-catalogo .cat-item-stock {
        font-size: 11px;
        color: #10b981;
      }
      #modal-catalogo .cat-item-stock.sin {
        color: #ef4444;
      }
      #modal-catalogo .cat-item-right {
        display: flex;
        flex-direction: column;
        align-items: flex-end;
        gap: 6px;
        flex-shrink: 0;
      }
      #modal-catalogo .cat-item-precio {
        font-size: 15px;
        font-weight: 700;
        color: #10b981;
        min-width: 52px;
        text-align: right;
      }
      #modal-catalogo .cat-item-precio.sin {
        font-size: 12px;
        font-weight: 500;
        color: #64748b;
      }

      /* ── Controles cantidad ── */
      #modal-catalogo .cat-qty {
        display: flex; align-items: center; gap: 6px;
      }
      #modal-catalogo .cat-qty-btn {
        width: 24px; height: 24px;
        border-radius: 50%;
        border: 1px solid rgba(255,255,255,.2);
        background: rgba(255,255,255,.06);
        color: #e2e8f0;
        cursor: pointer;
        font-size: 14px;
        display: flex; align-items: center; justify-content: center;
        font-family: inherit;
      }
      #modal-catalogo .cat-qty-btn:hover { background: rgba(16,185,129,.2); }
      #modal-catalogo .cat-qty-btn:disabled {
        opacity: .3;
        cursor: not-allowed;
      }
      #modal-catalogo .cat-qty-num {
        width: 22px;
        text-align: center;
        font-size: 13px;
        font-weight: 700;
        color: #f1f5f9;
      }

      /* ── Toggle check para servicios no-mercadería ── */
      #modal-catalogo .cat-toggle {
        width: 22px; height: 22px;
        border-radius: 50%;
        border: 2px solid rgba(255,255,255,.2);
        background: rgba(255,255,255,.04);
        display: flex; align-items: center; justify-content: center;
        color: transparent;
        font-size: 13px;
        font-weight: 900;
      }
      #modal-catalogo .cat-toggle.on {
        background: #22c55e;
        border-color: #22c55e;
        color: #fff;
      }

      /* ── Footer fijo ── */
      #modal-catalogo #cat-footer {
        flex-shrink: 0;
        padding: 12px 16px;
        border-top: 1px solid rgba(255,255,255,.08);
        display: flex;
        flex-direction: column;
        gap: 8px;
        background: rgba(0,0,0,.2);
      }
      #modal-catalogo .mc-total-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
      }
      #modal-catalogo .mc-total-label {
        font-size: 13px;
        color: #94a3b8;
      }
      #modal-catalogo .mc-total-value {
        font-size: 18px;
        font-weight: 800;
        color: #22c55e;
      }
      #modal-catalogo .mc-actions {
        display: flex;
        gap: 8px;
      }
      #modal-catalogo .mc-btn {
        flex: 1;
        padding: 10px 14px;
        border-radius: 10px;
        font-size: 13px;
        font-weight: 700;
        cursor: pointer;
        border: none;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 6px;
        font-family: inherit;
      }
      #modal-catalogo .mc-btn-primary {
        background: linear-gradient(135deg,#10b981,#059669);
        color: #fff;
      }
      #modal-catalogo .mc-btn-primary:hover { opacity: .9; }
      #modal-catalogo .mc-btn-ghost {
        background: transparent;
        border: 1px solid rgba(245,158,11,.35);
        color: #f59e0b;
      }
      #modal-catalogo .mc-btn-ghost:hover { background: rgba(245,158,11,.08); }

      /* ── Loader ── */
      #modal-catalogo .mc-loading {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: 10px;
        padding: 40px 12px;
        color: #64748b;
        font-size: 13px;
      }
      #modal-catalogo .mc-spinner {
        width: 28px; height: 28px;
        border: 3px solid rgba(255,255,255,.1);
        border-top-color: #10b981;
        border-radius: 50%;
        animation: mc-spin .8s linear infinite;
      }
      @keyframes mc-spin { to { transform: rotate(360deg); } }

      /* ── Empty ── */
      #modal-catalogo .mc-empty {
        text-align: center;
        color: #64748b;
        font-size: 13px;
        padding: 40px 12px;
      }

      /* ── Campos con feedback inline (DNI/RUC autocompletado) ── */
      #modal-catalogo .mc-field {
        position: relative;
        margin-bottom: 8px;
      }
      #modal-catalogo .mc-field-spinner {
        position: absolute;
        right: 10px;
        top: 10px;
        font-size: 14px;
        color: #94a3b8;
      }
      #modal-catalogo .mc-field-hint {
        font-size: 11px;
        color: #64748b;
        margin-top: 2px;
        display: block;
      }
      #modal-catalogo .mc-field-err {
        font-size: 11px;
        color: #fca5a5;
        margin-top: 2px;
        display: block;
      }

      /* ── Upload voucher (Yape/Plin/Transferencia) ── */
      #modal-catalogo .mc-voucher-label {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 10px 14px;
        border: 1px dashed rgba(148,163,184,.3);
        border-radius: 8px;
        cursor: pointer;
        color: #94a3b8;
        font-size: 12px;
        transition: border-color .2s, color .2s;
        margin-top: 6px;
      }
      #modal-catalogo .mc-voucher-label:hover {
        border-color: rgba(16,185,129,.4);
        color: #10b981;
      }
      #modal-catalogo .mc-voucher-analizar {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        margin-top: 8px;
        padding: 8px 14px;
        background: rgba(99,102,241,.12);
        border: 1px solid rgba(99,102,241,.35);
        color: #a78bfa;
        border-radius: 8px;
        font-size: 12px;
        font-weight: 600;
        cursor: pointer;
        font-family: inherit;
      }
      #modal-catalogo .mc-voucher-analizar:hover {
        background: rgba(99,102,241,.2);
      }
      #modal-catalogo .mc-voucher-resumen {
        margin-top: 8px;
        padding: 10px 12px;
        background: rgba(16,185,129,.08);
        border: 1px solid rgba(16,185,129,.3);
        border-radius: 8px;
        font-size: 12px;
        color: #86efac;
        line-height: 1.5;
      }

      /* ── Nota IGV bajo el total ── */
      #modal-catalogo .mc-igv-note {
        font-size: 10px;
        color: #64748b;
        text-align: right;
        margin-top: 2px;
      }
    `;
    document.head.appendChild(s);
  })();

  window.Modales = window.Modales || {};

  window.Modales.catalogo = {
    items:        [],
    seleccion:    [],   // [{id, nombre, monto, es_mercaderia, cantidad}]
    filtroActual: null,

    async abrir() {
      $('modal-catalogo')?.classList.add('open');
      if (this.items.length === 0) await this._cargar();
      this._renderFiltros();
      this._renderItems(this.filtroActual);
    },

    cerrar() {
      $('modal-catalogo')?.classList.remove('open');
      this.seleccion = [];
      this._actualizarFooter();
    },

    async _cargar() {
      try {
        const r = await fetch('/api/publico/catalogo');
        if (!r.ok) { console.error('[Catalogo] HTTP', r.status); return; }
        const d = await r.json();
        // Aplanar categorías en lista plana
        this.items = (d.categorias || []).flatMap(cat =>
          cat.items.map(i => ({ ...i, es_mercaderia: i.categoria === 'mercaderia' }))
        );
        console.log('[Catalogo] items:', this.items.length);
      } catch (e) {
        console.error('[Catalogo]', e);
      }
    },

    // Devuelve el precio numérico efectivo de un item (0 si no tiene precio válido)
    _precioItem(item) {
      const p = Number(item?.precio ?? item?.monto_base ?? 0);
      return Number.isFinite(p) && p > 0 ? p : 0;
    },

    _renderFiltros() {
      const el = $('cat-filtros');
      if (!el) return;
      const cats = [...new Set(this.items.map(i => i.categoria))];
      const labels = {
        mercaderia:   '🛍 Productos',
        constancias:  '📜 Constancias',
        capacitacion: '🎓 Capacitación',
        derechos:     '📋 Derechos',
        alquileres:   '🏛 Alquileres',
        eventos:      '🎉 Eventos',
        recreacion:   '⚽ Recreación',
        otros:        '📦 Otros',
      };
      el.innerHTML = `
        <button class="cat-pill ${!this.filtroActual ? 'activo' : ''}"
                onclick="Modales.catalogo._renderItems(null)">
          Todos (${this.items.length})
        </button>
        ${cats.map(c => `
          <button class="cat-pill ${this.filtroActual === c ? 'activo' : ''}"
                  onclick="Modales.catalogo._renderItems('${c}')">
            ${labels[c] || c} (${this.items.filter(i => i.categoria === c).length})
          </button>`).join('')}`;
    },

    _renderItems(filtro) {
      this.filtroActual = filtro;
      // Actualizar pills activos
      document.querySelectorAll('#modal-catalogo .cat-pill').forEach(p => {
        p.classList.toggle('activo',
          (!filtro && p.textContent.trim().startsWith('Todos')) ||
          p.getAttribute('onclick')?.includes(`'${filtro}'`));
      });

      const lista = $('cat-lista');
      const items = filtro ? this.items.filter(i => i.categoria === filtro) : this.items;

      if (!items.length) {
        lista.innerHTML = `<div class="mc-empty">Sin items disponibles</div>`;
        return;
      }

      lista.innerHTML = items.map(item => {
        const sel      = this.seleccion.find(s => s.id === item.id);
        const precio   = this._precioItem(item);
        const sinPrecio = precio <= 0;
        const sinStock = item.maneja_stock && (item.stock === 0 || item.agotado);
        const cantidad = sel ? sel.cantidad : 0;

        // Imagen
        const imgHtml = item.imagen_url
          ? `<img src="${item.imagen_url}" alt="${item.nombre}" class="cat-item-img">`
          : `<div class="cat-item-noimg">${_iconoPorCodigo(item.codigo)}</div>`;

        // Bloque de precio (o "A consultar" si sin precio)
        const precioHtml = sinPrecio
          ? `<div class="cat-item-precio sin">A consultar</div>`
          : `<div class="cat-item-precio">S/ ${Math.round(precio)}</div>`;

        // Acciones (cantidad / toggle / nada) — deshabilitadas si sinStock o sinPrecio
        let accionHtml = '';
        if (sinStock) {
          accionHtml = `<div class="cat-item-stock sin">Sin stock</div>`;
        } else if (sinPrecio) {
          // Sin precio → solo label, sin controles
          accionHtml = '';
        } else if (item.es_mercaderia) {
          accionHtml = `
            <div class="cat-qty">
              <button class="cat-qty-btn" type="button"
                      onclick="event.stopPropagation();Modales.catalogo._cambiarCantidad(${item.id},-1)"
                      ${cantidad <= 0 ? 'disabled' : ''}>−</button>
              <span class="cat-qty-num">${cantidad}</span>
              <button class="cat-qty-btn" type="button"
                      onclick="event.stopPropagation();Modales.catalogo._cambiarCantidad(${item.id},1)">+</button>
            </div>`;
        } else {
          accionHtml = `<div class="cat-toggle ${sel ? 'on' : ''}">${sel ? '✓' : ''}</div>`;
        }

        const clickHandler = (!sinStock && !sinPrecio && !item.es_mercaderia)
          ? `onclick="Modales.catalogo._toggle(${item.id})"`
          : '';

        const stockLine = item.maneja_stock && !sinStock
          ? `<div class="cat-item-stock">Stock: ${item.stock}</div>`
          : '';
        const descLine = item.descripcion
          ? `<div class="cat-item-desc">${item.descripcion}</div>`
          : '';

        return `
          <div class="cat-item ${sel ? 'cat-sel' : ''} ${sinStock ? 'cat-agotado' : ''}"
               ${clickHandler}
               style="cursor:${(sinStock || sinPrecio || item.es_mercaderia) ? 'default' : 'pointer'}">
            ${imgHtml}
            <div class="cat-item-body">
              <div class="cat-item-nombre">${item.nombre}</div>
              ${descLine}
              ${stockLine}
            </div>
            <div class="cat-item-right">
              ${precioHtml}
              ${accionHtml}
            </div>
          </div>`;
      }).join('');
    },

    _toggle(id) {
      // Para servicios (no mercadería) — selección simple
      const item = this.items.find(i => i.id === id);
      if (!item) return;
      const precio = this._precioItem(item);
      if (precio <= 0) return;   // sin precio → no seleccionable
      const idx = this.seleccion.findIndex(s => s.id === id);
      if (idx >= 0) {
        this.seleccion.splice(idx, 1);
      } else {
        this.seleccion.push({
          id,
          nombre:        item.nombre,
          monto:         precio,
          es_mercaderia: false,
          cantidad:      1,
        });
      }
      this._renderItems(this.filtroActual);
      this._actualizarFooter();
    },

    _cambiarCantidad(id, delta) {
      // Para mercadería — selector +/−
      const item = this.items.find(i => i.id === id);
      if (!item) return;
      const precio = this._precioItem(item);
      if (precio <= 0) return;   // sin precio → no modificable
      const idx     = this.seleccion.findIndex(s => s.id === id);
      const actual  = idx >= 0 ? this.seleccion[idx].cantidad : 0;
      const nueva   = actual + delta;

      if (nueva <= 0) {
        if (idx >= 0) this.seleccion.splice(idx, 1);
      } else {
        // Verificar stock
        if (item.maneja_stock && nueva > item.stock) return;
        if (idx >= 0) {
          this.seleccion[idx].cantidad = nueva;
        } else {
          this.seleccion.push({
            id,
            nombre:        item.nombre,
            monto:         precio,
            es_mercaderia: true,
            cantidad:      nueva,
          });
        }
      }
      this._renderItems(this.filtroActual);
      this._actualizarFooter();
    },

    _actualizarFooter() {
      // Excluye items con monto inválido o <= 0
      const total = this.seleccion.reduce((s, i) => {
        const m = Number(i.monto);
        return s + (Number.isFinite(m) && m > 0 ? m * i.cantidad : 0);
      }, 0);
      const footer = $('cat-footer');
      if ($('cat-total')) $('cat-total').textContent = 'S/ ' + Math.round(total);
      if (footer) footer.style.display = (this.seleccion.length > 0 && total > 0) ? 'flex' : 'none';

      // Nota IGV bajo el total — se inyecta una sola vez
      if (footer && !$('mc-igv-note')) {
        const note = document.createElement('div');
        note.id = 'mc-igv-note';
        note.className = 'mc-igv-note';
        note.textContent = 'Precios exonerados de IGV · Ley de la Amazonía 27037';
        const totalRow = footer.querySelector('.mc-total-row');
        if (totalRow) totalRow.insertAdjacentElement('afterend', note);
      }
    },

    _hayMercaderia() {
      return this.seleccion.some(i => i.es_mercaderia);
    },

    _total() {
      return Math.round(this.seleccion.reduce((s, i) => {
        const m = Number(i.monto);
        return s + (Number.isFinite(m) && m > 0 ? m * i.cantidad : 0);
      }, 0));
    },

    _itemsParaApi() {
      return this.seleccion.map(i => ({
        concepto_id: i.id,
        cantidad:    i.cantidad,
      }));
    },

    _conceptoCarrito() {
      return this.seleccion.map(i =>
        i.cantidad > 1 ? `${i.cantidad}x ${i.nombre}` : i.nombre
      ).join(', ');
    },

    _persistirSession(total) {
      if (this._hayMercaderia()) {
        sessionStorage.setItem('hay_mercaderia', '1');
        sessionStorage.setItem('items_mercaderia', JSON.stringify(
          this.seleccion.filter(i => i.es_mercaderia).map(i => i.nombre)
        ));
      }
      // Items para /api/publico/comprar (portal_inactivo) o auditoría
      sessionStorage.setItem('carrito_items', JSON.stringify(this._itemsParaApi()));
      sessionStorage.setItem('carrito_total', String(total));
    },

    pagarTarjeta() {
      if (!this.seleccion.length) return;
      const total    = this._total();
      const concepto = this._conceptoCarrito();

      // ── Contexto portal_inactivo → Modales.pagoLinea
      if (window.Modales && typeof window.Modales.pagoLinea !== 'undefined') {
        this._persistirSession(total);
        this.cerrar();
        if ($('pl-monto')) $('pl-monto').value = total;
        window.Modales.pagoLinea.recalcular?.();
        window.Modales.pagoLinea.abrir();
        return;
      }

      // ── Contexto dashboard_colegiado (colegiado hábil) → PagoFlowHabil online
      if (typeof window.PagoFlowHabil !== 'undefined') {
        this._persistirSession(total);
        this.cerrar();
        window.PagoFlowHabil.iniciarOnline({
          deudaIds: [],
          monto:    total,
          concepto: concepto,
        });
        return;
      }

      // ── Contexto público → formulario interno dentro del mismo modal
      // (NO cerrar: mantenemos this.seleccion para renderizar el resumen)
      this._mostrarFormPago('tarjeta');
    },

    reportar() {
      if (!this.seleccion.length) return;
      const total    = this._total();
      const hayMerc  = this._hayMercaderia();
      const concepto = this._conceptoCarrito();

      // ── Contexto portal_inactivo → Modales.reportarPago
      if (window.Modales && typeof window.Modales.reportarPago !== 'undefined') {
        this._persistirSession(total);
        this.cerrar();
        if ($('rp-monto'))    $('rp-monto').value    = total;
        if ($('rp-concepto')) $('rp-concepto').value = hayMerc ? 'mercaderia' : 'otro';

        const aviso = $('rp-aviso-producto');
        if (aviso) aviso.style.display = hayMerc ? 'block' : 'none';

        window.Modales.reportarPago.abrir();
        return;
      }

      // ── Contexto dashboard_colegiado → PagoFlowHabil reportar
      if (typeof window.PagoFlowHabil !== 'undefined') {
        this._persistirSession(total);
        this.cerrar();
        window.PagoFlowHabil.iniciar({
          deudaIds: [],
          monto:    total,
          concepto: concepto,
        });
        return;
      }

      // ── Contexto público → formulario interno (Yape/Plin default)
      this._mostrarFormPago('yape');
    },

    // ═══════════════════════════════════════════════════════════
    //  FORMULARIO DE PAGO PÚBLICO (contexto ccp-loreto / visitante)
    // ═══════════════════════════════════════════════════════════
    _mostrarFormPago(metodoInicial) {
      // Guardar el estado del carrito para poder volver
      // (se mantienen this.seleccion, this.items, this.filtroActual intactos)
      const modal = $('modal-catalogo');
      if (!modal) return;

      // Reabrir el modal si venimos de una llamada que ya hizo this.cerrar()
      modal.classList.add('open');

      const filtros = $('cat-filtros');
      const footer  = $('cat-footer');
      const lista   = $('cat-lista');
      if (filtros) filtros.style.display = 'none';
      if (footer)  footer.style.display  = 'none';

      const total = this._total();
      const resumenItems = this.seleccion.map(i =>
        `<div style="display:flex;justify-content:space-between;font-size:12px;color:#94a3b8;padding:3px 0">
           <span>${i.cantidad}× ${i.nombre}</span>
           <span>S/ ${Math.round(i.monto * i.cantidad)}</span>
         </div>`
      ).join('');

      lista.innerHTML = `
        <div id="cat-form-pago" style="padding:4px 0">

          <!-- Resumen del carrito -->
          <div style="background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.06);
                      border-radius:10px;padding:12px;margin-bottom:14px">
            <div style="font-size:11px;text-transform:uppercase;letter-spacing:.08em;
                        color:#64748b;margin-bottom:6px">Tu compra</div>
            ${resumenItems}
            <div style="display:flex;justify-content:space-between;margin-top:8px;
                        padding-top:8px;border-top:1px solid rgba(255,255,255,.06);
                        font-size:14px;font-weight:700;color:#e2eaf7">
              <span>Total</span>
              <span style="color:#22c55e">S/ ${total}</span>
            </div>
          </div>

          <!-- ═════ Sección A: Datos del comprador ═════ -->
          <div style="margin-bottom:14px">
            <div style="font-size:12px;font-weight:700;text-transform:uppercase;
                        letter-spacing:.08em;color:#e2eaf7;margin-bottom:8px">
              1. Tus datos
            </div>

            <!-- DNI primero para autocompletar nombre -->
            <div class="mc-field">
              <input id="cat-dni" type="text" inputmode="numeric" autocomplete="off"
                     placeholder="DNI (8 dígitos)" maxlength="8" required
                     onblur="Modales.catalogo._onBlurDni()"
                     oninput="if(this.value.length===8) Modales.catalogo._onBlurDni()"
                     style="${this._inputStyle()}">
              <span id="cat-dni-spinner" class="mc-field-spinner" style="display:none">⏳</span>
              <small id="cat-dni-hint" class="mc-field-hint" style="display:none"></small>
            </div>

            <div class="mc-field">
              <input id="cat-nombre" type="text" placeholder="Nombre completo" required
                     style="${this._inputStyle()}">
            </div>

            <div class="mc-field">
              <input id="cat-email" type="email" placeholder="Correo electrónico"
                     style="${this._inputStyle()}">
              <small class="mc-field-hint">Opcional · si lo ingresas te enviaremos el comprobante</small>
            </div>

            <div style="display:flex;gap:8px;margin:10px 0 6px">
              <label style="flex:1;display:flex;align-items:center;gap:6px;padding:8px 12px;
                            background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);
                            border-radius:8px;cursor:pointer;font-size:13px;color:#e2eaf7">
                <input type="radio" name="cat-tipo-comp" value="boleta" checked
                       onchange="Modales.catalogo._toggleFactura(false)">
                Boleta
              </label>
              <label style="flex:1;display:flex;align-items:center;gap:6px;padding:8px 12px;
                            background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);
                            border-radius:8px;cursor:pointer;font-size:13px;color:#e2eaf7">
                <input type="radio" name="cat-tipo-comp" value="factura"
                       onchange="Modales.catalogo._toggleFactura(true)">
                Factura
              </label>
            </div>

            <div id="cat-factura-box" style="display:none;margin-top:6px">
              <div class="mc-field">
                <input id="cat-ruc" type="text" inputmode="numeric" autocomplete="off"
                       placeholder="RUC (11 dígitos)" maxlength="11"
                       onblur="Modales.catalogo._onBlurRuc()"
                       oninput="if(this.value.length===11) Modales.catalogo._onBlurRuc()"
                       style="${this._inputStyle()}">
                <span id="cat-ruc-spinner" class="mc-field-spinner" style="display:none">⏳</span>
                <small id="cat-ruc-hint" class="mc-field-hint" style="display:none"></small>
              </div>
              <div class="mc-field">
                <input id="cat-razon" type="text" placeholder="Razón social"
                       style="${this._inputStyle()}">
              </div>
              <div class="mc-field">
                <input id="cat-direccion" type="text" placeholder="Dirección fiscal"
                       style="${this._inputStyle()}">
              </div>
            </div>
          </div>

          <!-- ═════ Sección B: Método de pago ═════ -->
          <div style="margin-bottom:14px">
            <div style="font-size:12px;font-weight:700;text-transform:uppercase;
                        letter-spacing:.08em;color:#e2eaf7;margin-bottom:8px">
              2. Método de pago
            </div>

            <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-bottom:12px">
              <button type="button" data-cat-metodo="tarjeta"
                      onclick="Modales.catalogo._seleccionarMetodo('tarjeta')"
                      style="${this._botonMetodoStyle(metodoInicial === 'tarjeta')}">
                <span class="mi" style="font-size:18px">credit_card</span>
                <span style="font-size:11px;margin-top:2px">Tarjeta</span>
              </button>
              <button type="button" data-cat-metodo="yape"
                      onclick="Modales.catalogo._seleccionarMetodo('yape')"
                      style="${this._botonMetodoStyle(metodoInicial === 'yape')}">
                <span class="mi" style="font-size:18px">smartphone</span>
                <span style="font-size:11px;margin-top:2px">Yape/Plin</span>
              </button>
              <button type="button" data-cat-metodo="transferencia"
                      onclick="Modales.catalogo._seleccionarMetodo('transferencia')"
                      style="${this._botonMetodoStyle(metodoInicial === 'transferencia')}">
                <span class="mi" style="font-size:18px">account_balance</span>
                <span style="font-size:11px;margin-top:2px">Transferencia</span>
              </button>
            </div>

            <div id="cat-datos-banco"></div>
          </div>

          <!-- Mensaje de resultado -->
          <div id="cat-resultado" style="display:none;padding:12px;border-radius:10px;
                                         margin-bottom:12px;font-size:13px"></div>

          <!-- Botones -->
          <div style="display:flex;gap:8px;margin-top:4px">
            <button type="button" onclick="Modales.catalogo._volverCarrito()"
                    style="padding:11px 14px;background:transparent;
                           border:1px solid rgba(255,255,255,.15);
                           color:#94a3b8;border-radius:8px;cursor:pointer;
                           font-size:13px;font-weight:600">
              ← Volver
            </button>
            <button id="cat-btn-confirmar" type="button"
                    onclick="Modales.catalogo._confirmarPago()"
                    style="flex:1;padding:11px 14px;
                           background:linear-gradient(135deg,#10b981,#059669);
                           border:none;color:#fff;border-radius:8px;cursor:pointer;
                           font-size:14px;font-weight:700">
              Confirmar pago
            </button>
          </div>
        </div>
      `;

      this._metodoPago = metodoInicial;
      this._renderDatosBanco(metodoInicial);
    },

    _inputStyle() {
      return `width:100%;padding:10px 12px;margin-bottom:8px;
              background:rgba(255,255,255,.04);
              border:1px solid rgba(255,255,255,.1);
              border-radius:8px;color:#e2eaf7;font-size:13px;
              font-family:inherit;outline:none`;
    },

    _botonMetodoStyle(activo) {
      return `display:flex;flex-direction:column;align-items:center;justify-content:center;
              padding:10px 6px;cursor:pointer;border-radius:10px;
              background:${activo ? 'rgba(16,185,129,.12)' : 'rgba(255,255,255,.04)'};
              border:1px solid ${activo ? 'rgba(16,185,129,.4)' : 'rgba(255,255,255,.08)'};
              color:${activo ? '#22c55e' : '#94a3b8'};
              font-family:inherit`;
    },

    _toggleFactura(mostrar) {
      const box = $('cat-factura-box');
      if (box) box.style.display = mostrar ? 'block' : 'none';

      // Factura: DNI/Nombre opcionales — se llena del RUC
      const dniInput    = $('cat-dni');
      const nombreInput = $('cat-nombre');
      if (dniInput) {
        dniInput.required    = !mostrar;
        dniInput.placeholder = mostrar ? 'DNI (opcional para factura)' : 'DNI (8 dígitos)';
      }
      if (nombreInput) {
        nombreInput.required    = !mostrar;
        nombreInput.placeholder = mostrar ? 'Nombre / Razón Social' : 'Nombre completo';
      }
    },

    _seleccionarMetodo(metodo) {
      this._metodoPago = metodo;
      // Refrescar estilos de los 3 botones
      document.querySelectorAll('[data-cat-metodo]').forEach(b => {
        const activo = b.dataset.catMetodo === metodo;
        b.setAttribute('style', this._botonMetodoStyle(activo));
      });
      this._renderDatosBanco(metodo);
    },

    _renderDatosBanco(metodo) {
      const box = $('cat-datos-banco');
      if (!box) return;

      if (metodo === 'tarjeta') {
        box.innerHTML = `
          <div style="background:rgba(59,130,246,.08);border:1px solid rgba(59,130,246,.25);
                      border-radius:10px;padding:12px;font-size:12px;color:#93c5fd">
            <div style="font-weight:700;color:#dbeafe;margin-bottom:4px">
              Pago con tarjeta vía OpenPay
            </div>
            Al confirmar, serás redirigido al checkout seguro de OpenPay
            para ingresar los datos de tu tarjeta. El comprobante se emitirá
            automáticamente al aprobarse el pago.
          </div>
        `;
        return;
      }

      // Yape/Plin o Transferencia — mostrar datos bancarios + número de operación
      const esYape = metodo === 'yape';
      box.innerHTML = `
        <div style="background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.08);
                    border-radius:10px;padding:12px;margin-bottom:10px;font-size:12px">
          <div style="font-weight:700;color:#e2eaf7;margin-bottom:8px">
            ${esYape ? 'Paga con Yape o Plin' : 'Transferencia bancaria'}
          </div>

          <!-- ══════════════════════════════════════════════════════
               REEMPLAZAR CON DATOS REALES DEL CCPL
          ══════════════════════════════════════════════════════ -->
          ${esYape ? `
            <div style="color:#94a3b8;line-height:1.9">
              <div><strong style="color:#e2eaf7">Yape / Plin:</strong> 9XX XXX XXX <em style="color:#f59e0b">&lt;reemplazar&gt;</em></div>
              <div><strong style="color:#e2eaf7">Titular:</strong> Colegio de Contadores Públicos de Loreto</div>
            </div>
          ` : `
            <div style="color:#94a3b8;line-height:1.9">
              <div><strong style="color:#e2eaf7">BCP Cuenta:</strong> XXX-XXXXXXXX-X-XX <em style="color:#f59e0b">&lt;reemplazar&gt;</em></div>
              <div><strong style="color:#e2eaf7">BCP CCI:</strong> 00XXXXXXXXXXXXXXXXXXXXX <em style="color:#f59e0b">&lt;reemplazar&gt;</em></div>
              <div><strong style="color:#e2eaf7">Titular:</strong> Colegio de Contadores Públicos de Loreto</div>
            </div>
          `}
          <!-- ══════════════════════════════════════════════════════ -->
        </div>

        <input id="cat-nrop" type="text" placeholder="N° de operación (obligatorio)"
               style="${this._inputStyle()}">

        <!-- Upload voucher (opcional) con análisis IA -->
        <label class="mc-voucher-label" for="mc-voucher-file">
          📎 <span id="mc-voucher-txt">Adjuntar voucher (opcional)</span>
          <input type="file" id="mc-voucher-file" accept="image/*"
                 style="display:none"
                 onchange="Modales.catalogo._onChangeVoucher(event)">
        </label>
        <div id="mc-voucher-ia" style="display:none"></div>
      `;
    },

    _volverCarrito() {
      const filtros = $('cat-filtros');
      const footer  = $('cat-footer');
      if (filtros) filtros.style.display = 'flex';
      if (footer && this.seleccion.length) footer.style.display = 'flex';
      this._renderFiltros();
      this._renderItems(this.filtroActual);
      this._actualizarFooter();
    },

    // ─── Autocompletado DNI (apis.net.pe vía /api/publico/dni) ───
    async _onBlurDni() {
      const dniInput = $('cat-dni');
      if (!dniInput) return;
      const dni = dniInput.value.trim();
      const hint = $('cat-dni-hint');
      const sp   = $('cat-dni-spinner');

      if (hint) { hint.style.display = 'none'; hint.textContent = ''; hint.className = 'mc-field-hint'; }
      if (!/^\d{8}$/.test(dni)) return;

      if (sp) sp.style.display = 'inline';
      try {
        const r = await fetch(`/api/publico/dni/${dni}`);
        const d = await r.json();
        if (d && d.ok && d.nombre) {
          const nombreInput = $('cat-nombre');
          if (nombreInput && !nombreInput.value.trim()) nombreInput.value = d.nombre;
          if (hint) {
            hint.textContent = '✓ Verificado en RENIEC (editable)';
            hint.className = 'mc-field-hint';
            hint.style.color = '#86efac';
            hint.style.display = 'block';
          }
        } else {
          if (hint) {
            hint.textContent = 'No pudimos verificar el DNI — ingresa tu nombre manualmente.';
            hint.className = 'mc-field-err';
            hint.style.display = 'block';
          }
        }
      } catch (e) {
        if (hint) {
          hint.textContent = 'Sin conexión con RENIEC — ingresa tu nombre manualmente.';
          hint.className = 'mc-field-err';
          hint.style.display = 'block';
        }
      } finally {
        if (sp) sp.style.display = 'none';
      }
    },

    // ─── Autocompletado RUC (apis.net.pe vía /api/portal/ruc) ───
    async _onBlurRuc() {
      const rucInput = $('cat-ruc');
      if (!rucInput) return;
      const ruc = rucInput.value.trim();
      const hint = $('cat-ruc-hint');
      const sp   = $('cat-ruc-spinner');

      if (hint) { hint.style.display = 'none'; hint.textContent = ''; hint.className = 'mc-field-hint'; }
      if (!/^\d{11}$/.test(ruc)) return;

      if (sp) sp.style.display = 'inline';
      try {
        const r = await fetch(`/api/portal/ruc/${ruc}`);
        const d = await r.json();
        if (d && d.ok) {
          const razon = $('cat-razon');
          const dire  = $('cat-direccion');
          if (razon && !razon.value.trim() && d.nombre)    razon.value = d.nombre;
          if (dire  && !dire.value.trim()  && d.direccion) dire.value  = d.direccion;
          if (hint) {
            hint.textContent = '✓ RUC verificado (editable)';
            hint.className = 'mc-field-hint';
            hint.style.color = '#86efac';
            hint.style.display = 'block';
          }
        } else {
          if (hint) {
            hint.textContent = d?.msg || 'No pudimos verificar el RUC — ingresa los datos manualmente.';
            hint.className = 'mc-field-err';
            hint.style.display = 'block';
          }
        }
      } catch (e) {
        if (hint) {
          hint.textContent = 'Sin conexión con SUNAT — ingresa los datos manualmente.';
          hint.className = 'mc-field-err';
          hint.style.display = 'block';
        }
      } finally {
        if (sp) sp.style.display = 'none';
      }
    },

    // ─── Voucher: selección del archivo ────────────────────────
    _onChangeVoucher(event) {
      const file = event?.target?.files?.[0];
      const txt  = $('mc-voucher-txt');
      if (!file) return;

      this._voucherFile = file;
      if (txt) txt.innerHTML = `✅ ${file.name}`;

      // Lanzar análisis IA directamente (sin botón intermedio)
      this._analizarVoucherIA();
    },

    // ─── Voucher: análisis IA (POST /api/publico/analizar-voucher) ───
    async _analizarVoucherIA() {
      const box  = $('mc-voucher-ia');
      const file = this._voucherFile;
      if (!file || !box) return;
      box.innerHTML = `<div style="color:#94a3b8;font-size:12px;padding:8px 0">⏳ Analizando imagen...</div>`;

      try {
        const fd = new FormData();
        fd.append('voucher', file);   // mismo nombre que UploadFile voucher del endpoint

        const r = await fetch('/api/publico/analizar-voucher', {
          method: 'POST',
          body:   fd,
        });
        const d = await r.json();

        if (!d || !d.ok) {
          box.innerHTML = `<div class="mc-field-err" style="display:block">
            ${d?.msg || 'La IA no pudo leer el voucher. Completa manualmente.'}
          </div>`;
          return;
        }

        // Campos del endpoint: amount, operation_code, date, bank, app_emisora
        const opCode = d.operation_code || '';
        if (opCode) {
          const nrop = $('cat-nrop');
          if (nrop && !nrop.value.trim()) nrop.value = opCode;
        }

        const monto = d.amount ?? '';
        const banco = d.app_emisora || d.bank || '';
        const fecha = d.date || '';

        box.innerHTML = `
          <div class="mc-voucher-resumen">
            <strong>IA detectó:</strong><br>
            ${monto !== '' ? `S/ ${monto}` : ''}${banco ? ` · ${banco}` : ''}${fecha ? ` · ${fecha}` : ''}
            ${opCode ? `<br>Op: ${opCode}` : ''}
          </div>
        `;
      } catch (e) {
        box.innerHTML = `<div class="mc-field-err" style="display:block">
          Error al analizar el voucher. Completa manualmente.
        </div>`;
      }
    },

    _leerForm() {
      const nombre = $('cat-nombre')?.value.trim() || '';
      const dni    = $('cat-dni')?.value.trim()    || '';
      const email  = $('cat-email')?.value.trim()  || '';
      const tipo   = document.querySelector('input[name="cat-tipo-comp"]:checked')?.value || 'boleta';

      const factura = tipo === 'factura' ? {
        ruc:          $('cat-ruc')?.value.trim()       || '',
        razon_social: $('cat-razon')?.value.trim()     || '',
        direccion:    $('cat-direccion')?.value.trim() || '',
      } : null;

      return { nombre, dni, email, tipo, factura };
    },

    _mostrarMensaje(texto, tipo) {
      const box = $('cat-resultado');
      if (!box) return;
      const colores = {
        error:   { bg:'rgba(239,68,68,.08)', bd:'rgba(239,68,68,.3)', fg:'#fca5a5' },
        ok:      { bg:'rgba(34,197,94,.08)', bd:'rgba(34,197,94,.3)', fg:'#86efac' },
        info:    { bg:'rgba(59,130,246,.08)', bd:'rgba(59,130,246,.3)', fg:'#93c5fd' },
      };
      const c = colores[tipo] || colores.info;
      box.style.display      = 'block';
      box.style.background   = c.bg;
      box.style.border       = `1px solid ${c.bd}`;
      box.style.color        = c.fg;
      box.innerHTML          = texto;
    },

    // ─── Pantalla de éxito tras Yape/Transferencia ───
    _mostrarExito(data) {
      const lista    = $('cat-lista');
      const filtros  = $('cat-filtros');
      const footer   = $('cat-footer');
      if (filtros) filtros.style.display = 'none';
      if (footer)  footer.style.display  = 'none';

      const numero = data?.comprobante?.numero_formato;
      const pdfUrl = data?.comprobante?.pdf_url;
      const mensaje = data?.mensaje || 'El comprobante se emitirá al validar tu pago.';

      if (lista) {
        lista.innerHTML = `
          <div style="text-align:center;padding:40px 20px">
            <div style="font-size:3rem;margin-bottom:16px">✅</div>
            <div style="font-size:18px;font-weight:700;color:#10b981;margin-bottom:8px">
              ¡Compra registrada!
            </div>
            <div style="font-size:13px;color:#94a3b8;margin-bottom:20px">
              ${mensaje}
            </div>
            ${numero ? `<div style="font-size:13px;color:#e2e8f0;margin-bottom:8px">
              Comprobante: <b>${numero}</b></div>` : ''}
            ${pdfUrl ? `<a href="${pdfUrl}" target="_blank"
              class="mc-btn mc-btn-primary"
              style="display:inline-flex;margin-top:12px;text-decoration:none">
              📄 Descargar comprobante</a>` : ''}
            <button onclick="Modales.catalogo._volverCarrito()"
              class="mc-btn mc-btn-ghost"
              style="margin-top:12px;width:100%">
              Seguir comprando
            </button>
          </div>
        `;
      }
    },

    async _confirmarPago() {
      const datos = this._leerForm();
      const metodo = this._metodoPago || 'tarjeta';

      // ── Validaciones según tipo de comprobante ──
      if (datos.tipo === 'factura') {
        // Factura: RUC + Razón Social requeridos; DNI/Nombre opcionales
        if (!datos.factura?.ruc || !/^\d{11}$/.test(datos.factura.ruc)) {
          this._mostrarMensaje('RUC inválido (11 dígitos).', 'error');
          return;
        }
        if (!datos.factura.razon_social) {
          this._mostrarMensaje('Razón social requerida para factura.', 'error');
          return;
        }
        // DNI opcional para factura — solo validar formato si lo ingresó
        if (datos.dni && !/^\d{8}$/.test(datos.dni)) {
          this._mostrarMensaje('DNI inválido (8 dígitos).', 'error');
          return;
        }
      } else {
        // Boleta: DNI + Nombre requeridos
        if (!datos.nombre) {
          this._mostrarMensaje('Ingresa tu nombre completo.', 'error');
          return;
        }
        if (!datos.dni || !/^\d{8}$/.test(datos.dni)) {
          this._mostrarMensaje('DNI inválido (8 dígitos).', 'error');
          return;
        }
      }
      // Email: opcional siempre — si lo ingresa, validar formato
      if (datos.email && !/^\S+@\S+\.\S+$/.test(datos.email)) {
        this._mostrarMensaje('El correo tiene formato inválido.', 'error');
        return;
      }

      const btn = $('cat-btn-confirmar');
      if (btn) { btn.disabled = true; btn.textContent = 'Procesando...'; }

      const body = {
        items:            this._itemsParaApi(),
        tipo_comprobante: datos.tipo,
        comprador:        { nombre: datos.nombre, dni: datos.dni, email: datos.email },
      };
      if (datos.factura) body.factura = datos.factura;

      try {
        if (metodo === 'tarjeta') {
          // ── Vía OpenPay redirect ─────────────────────────────
          const r = await fetch('/api/publico/openpay/iniciar', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify(body),
          });
          const data = await r.json();
          if (!r.ok || !data.redirect_url) {
            throw new Error(data.error || 'No se pudo iniciar el pago con tarjeta');
          }
          this._mostrarMensaje('Redirigiendo a OpenPay...', 'info');
          window.location.href = data.redirect_url;
          return;
        }

        // ── Yape/Plin/Transferencia → /api/publico/comprar ─────
        const nrop = $('cat-nrop')?.value.trim();
        if (!nrop) {
          this._mostrarMensaje('Ingresa el N° de operación.', 'error');
          if (btn) { btn.disabled = false; btn.textContent = 'Confirmar pago'; }
          return;
        }
        body.metodo_pago   = metodo;
        body.nro_operacion = nrop;

        const r = await fetch('/api/publico/comprar', {
          method:  'POST',
          headers: { 'Content-Type': 'application/json' },
          body:    JSON.stringify(body),
        });
        const data = await r.json();
        if (!r.ok || !data.ok) {
          throw new Error(data.error || 'No se pudo registrar la compra');
        }

        // Limpiar selección y mostrar pantalla de éxito
        this.seleccion = [];
        this._mostrarExito(data);
      } catch (e) {
        this._mostrarMensaje(`Error: ${e.message || e}`, 'error');
        if (btn) { btn.disabled = false; btn.textContent = 'Confirmar pago'; }
      }
    },
  };
})();

// static/service-worker.js
// v2 — PWA instalable + push comunicados + push pánico

const CACHE_NAME = 'ccpl-v5';
const ASSETS_TO_CACHE = [
  '/static/css/pages/dashboard_colegiado.css',
  '/static/js/pages/dashboard_colegiado.js',
  '/static/img/icon-192.png',
  '/static/img/icon-512.png',
  '/static/img/logo-ccpl.png',
  '/manifest.json',
];

// ── Instalación — cachear assets esenciales ───────────────
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return cache.addAll(ASSETS_TO_CACHE).catch(err => {
        console.warn('[SW] Algunos assets no se cachearon:', err);
      });
    })
  );
  self.skipWaiting();
});

// ── Activación — limpiar caches antiguas ──────────────────
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

// ── Fetch — cache first para assets estáticos ─────────────
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET') return;

  // SOLO interceptar assets estáticos (cache-first). TODO lo demás — páginas,
  // descargas y endpoints autenticados (p. ej. /admin/aportes-junta/.../pdf y /excel,
  // dashboards) — pasa DIRECTO al network, sin tocar el SW. Antes el SW interceptaba
  // todo salvo /api/ y /auth/, y su `.catch(()=>cached)` devolvía undefined para esos
  // documentos dinámicos → "no se puede obtener acceso a esta página" en el PDF.
  const esEstatico = url.pathname.startsWith('/static/') || url.pathname === '/manifest.json';
  if (!esEstatico) return;

  event.respondWith(
    caches.match(event.request).then(cached => {
      return cached || fetch(event.request).then(response => {
        const clone = response.clone();
        caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
        return response;
      }).catch(() => cached);
    })
  );
});

// ── Push notifications ────────────────────────────────────
self.addEventListener('push', event => {
  let data = {
    type:  'info',
    title: 'CCPL',
    body:  'Nueva notificación',
    url:   '/dashboard',
    icon:  '/static/img/icon-192.png',
  };

  if (event.data) {
    try { Object.assign(data, event.data.json()); }
    catch(e) { data.body = event.data.text(); }
  }

  // zClaude-97o: aceptar también titulo/mensaje (nomenclatura del diseño v3),
  // manteniendo compatibilidad con el payload title/body existente.
  if (data.titulo) data.title = data.titulo;
  if (data.mensaje) data.body = data.mensaje;

  // Configuración según tipo de notificación
  const configs = {
    panico: {
      vibrate:         [1000, 500, 1000, 500, 1000],
      requireInteraction: true,
      renotify:        true,
      tag:             'alerta-panico',
      actions:         [{ action: 'open_url', title: '🔴 VER ALERTA' }],
      badge:           '/static/img/icon-192.png',
    },
    comunicado: {
      vibrate:         [200, 100, 200],
      requireInteraction: false,
      renotify:        false,
      tag:             `comunicado-${Date.now()}`,
      actions:         [{ action: 'open_url', title: '📢 Ver comunicado' }],
      badge:           '/static/img/icon-192.png',
    },
    pago: {
      vibrate:         [300, 100, 300],
      requireInteraction: false,
      renotify:        false,
      tag:             `pago-${Date.now()}`,
      actions:         [{ action: 'open_url', title: '✅ Ver detalle' }],
      badge:           '/static/img/icon-192.png',
    },
    info: {
      vibrate:         [100],
      requireInteraction: false,
      renotify:        false,
      tag:             `info-${Date.now()}`,
      badge:           '/static/img/icon-192.png',
    },
  };

  const cfg = configs[data.type] || configs.info;

  const options = {
    body:    data.body,
    icon:    data.icon || '/static/img/icon-192.png',
    image:   data.image || null,   // imagen grande (comunicados con foto)
    data:    { url: data.url, sonido: data.sonido || null, nivel: data.nivel || 'N3' },
    ...cfg,
  };

  // zClaude-97o: los avisos críticos N4 quedan "sticky" (requireInteraction)
  // aunque su 'type' no lo fuera. No debilita los configs existentes.
  if (data.nivel === 'N4') options.requireInteraction = true;

  // Limpiar nulls
  if (!options.image) delete options.image;

  event.waitUntil(
    self.registration.showNotification(data.title, options)
  );
});

// ── Click en notificación ─────────────────────────────────
self.addEventListener('notificationclick', event => {
  event.notification.close();
  const targetUrl = event.notification.data?.url || '/dashboard';

  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(list => {
      for (const client of list) {
        if (client.url.includes(self.location.origin) && 'focus' in client) {
          client.focus();
          // zClaude-97o: navegar la ventana ya abierta al destino del aviso.
          if ('navigate' in client) { client.navigate(targetUrl).catch(() => {}); }
          client.postMessage({ type: 'navigate', url: targetUrl });
          return;
        }
      }
      if (clients.openWindow) return clients.openWindow(targetUrl);
    })
  );
});
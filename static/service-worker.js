// static/service-worker.js
// v2 — PWA instalable + push comunicados + push pánico

const CACHE_NAME = 'ccpl-v3';
const ASSETS_TO_CACHE = [
  '/',
  '/dashboard',
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

  // Solo cachear GET de assets estáticos
  if (event.request.method !== 'GET') return;
  if (url.pathname.startsWith('/api/')) return;
  if (url.pathname.startsWith('/auth/')) return;

  event.respondWith(
    caches.match(event.request).then(cached => {
      return cached || fetch(event.request).then(response => {
        // Cachear solo assets estáticos
        if (url.pathname.startsWith('/static/')) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
        }
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
    data:    { url: data.url },
    ...cfg,
  };

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
        if (client.url.includes(targetUrl) && 'focus' in client) {
          return client.focus();
        }
      }
      if (clients.openWindow) return clients.openWindow(targetUrl);
    })
  );
});
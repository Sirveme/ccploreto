// static/service-worker.js

self.addEventListener('push', function(event) {
  console.log('Push Recibido:', event);

  let data = { title: 'Alerta', body: 'Nueva notificación', url: '/dashboard' };

  if (event.data) {
    data = event.data.json();
  }

  const options = {
    body: data.body,
    icon: data.icon || '/static/images/icon-192.png',
    badge: '/static/images/icon-192.png', // Icono pequeño en barra de estado (Android)
    vibrate: [1000, 500, 1000, 500, 1000], // Patrón de vibración agresivo (SOS)
    data: { 
        url: data.url 
    },
    tag: 'alerta-panico', // Agrupa notificaciones para no llenar la barra
    renotify: true, // Vuelve a vibrar aunque ya haya una notificación ahí (CRÍTICO)
    requireInteraction: true, // No desaparece sola, el usuario debe tocarla
    actions: [
        { action: 'open_url', title: '🔴 VER ALERTA' }
    ]
  };

  event.waitUntil(
    self.registration.showNotification(data.title, options)
  );
});

// Cuando el usuario toca la notificación
self.addEventListener('notificationclick', function(event) {
  event.notification.close();

  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function(clientList) {
      // Si la app ya está abierta, ponle foco
      for (let i = 0; i < clientList.length; i++) {
        let client = clientList[i];
        if (client.url.includes(event.notification.data.url) && 'focus' in client) {
          return client.focus();
        }
      }
      // Si no, abre una ventana nueva
      if (clients.openWindow) {
        return clients.openWindow(event.notification.data.url);
      }
    })
  );
});
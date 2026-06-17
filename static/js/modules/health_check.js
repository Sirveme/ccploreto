document.addEventListener("DOMContentLoaded", async () => {
    // 1. Diagnóstico Rápido
    checkHealthAndReport();

    // 2. Escuchar evento de instalación (PWA)
    window.addEventListener('appinstalled', () => {
        console.log("📲 App instalada. Actualizando registro...");
        setTimeout(checkHealthAndReport, 500); // Actualizar casi inmediato
    });
});

async function checkHealthAndReport() {
    const isPWA = window.matchMedia('(display-mode: standalone)').matches || 
                  window.navigator.standalone === true;

    const status = {
        online: navigator.onLine,
        permission: Notification.permission,
        userAgent: navigator.userAgent,
        pwa: isPWA,
        platform: navigator.platform || 'Desconocido',
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone
    };

    // Alerta Visual si está bloqueado
    if (status.permission === 'denied') {
        mostrarAlertaBloqueo();
    }

    // Reportar al Backend (Espero 1s para no competir con la carga de imágenes)
    if(window.APP_CONFIG && window.APP_CONFIG.user) {
        setTimeout(() => reportarSalud(status), 1000);
    }
}

async function reportarSalud(status) {
    try {
        const response = await fetch('/api/health/report', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(status)
        });
        
        // Feedback Transparente (Solo si cambió algo o es la primera vez)
        // Podríamos hacer que el backend devuelva "updated": true
        if (response.ok) {
            console.log("✅ Dispositivo Sincronizado");
            // Opcional: Mostrar Toast sutil para que el usuario sepa que está conectado
            // if(window.Toast) window.Toast.show("Dispositivo sincronizado", "info");
        }
    } catch (e) { 
        console.warn("Fallo reporte salud", e); 
    }
}

function mostrarAlertaBloqueo() {
  if (document.getElementById('alert-block-push')) return;

  const div = document.createElement('div');
  div.id = 'alert-block-push';
  div.className = "bg-red-600 text-white text-xs font-bold text-center p-2 fixed top-0 w-full z-[100] cursor-pointer hover:bg-red-700 transition-colors shadow-lg";
  div.innerHTML = "⚠️ NOTIFICACIONES BLOQUEADAS. No recibirás alertas. <u>Cómo activarlas</u>";
  div.onclick = window.guiarDesbloqueo;
  document.body.prepend(div);
}

window.guiarDesbloqueo = function() {
  if (document.getElementById('modal-guia-desbloqueo')) return;

  const info = detectarDispositivoHealth();

  const modal = document.createElement('div');
  modal.id = 'modal-guia-desbloqueo';
  modal.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.85);z-index:99999;display:flex;align-items:center;justify-content:center;';

  modal.innerHTML = `
    <div style="background:linear-gradient(135deg, #1e293b, #0f172a); border-radius:16px;
         padding:28px; max-width:480px; width:90%; color:#e2e8f0;
         box-shadow:0 20px 60px rgba(0,0,0,0.5);">

      <div style="text-align:center; margin-bottom:18px;">
        <div style="font-size:48px;">🔓</div>
        <h2 style="margin:8px 0 0; font-size:20px; color:#fbbf24;">
          Activar notificaciones en ${info.label}
        </h2>
      </div>

      <ol style="margin:0 0 20px; padding-left:24px; font-size:14px; color:#cbd5e1; line-height:1.8;">
        ${info.pasos.map(p => `<li>${p}</li>`).join('')}
      </ol>

      <div style="display:flex; gap:10px; justify-content:center; flex-wrap:wrap;">
        <button id="btn-guia-desbloqueo-recargar" style="
          background:linear-gradient(135deg, #10b981, #059669); color:white;
          padding:10px 20px; border:none; border-radius:8px; font-weight:600;
          font-size:14px; cursor:pointer; flex:1; min-width:130px;">
          🔄 Ya lo activé
        </button>
        <button id="btn-guia-desbloqueo-cerrar" style="
          background:#475569; color:white;
          padding:10px 20px; border:none; border-radius:8px; font-weight:600;
          font-size:14px; cursor:pointer; flex:1; min-width:130px;">
          Cerrar
        </button>
      </div>
    </div>
  `;

  document.body.appendChild(modal);

  document.getElementById('btn-guia-desbloqueo-recargar').addEventListener('click', () => {
    window.location.reload();
  });
  document.getElementById('btn-guia-desbloqueo-cerrar').addEventListener('click', () => {
    modal.remove();
  });
};

function detectarDispositivoHealth() {
  const ua = navigator.userAgent;
  const isIOS = /iPhone|iPad|iPod/.test(ua);
  const isAndroid = /Android/.test(ua);
  const isFirefox = /Firefox/.test(ua);

  if (isIOS) {
    return {
      label: 'iPhone/iPad',
      pasos: [
        'Abre <strong>Configuración</strong> del iPhone',
        'Busca <strong>Safari</strong> (o el navegador que usas)',
        'Toca <strong>Notificaciones de sitios web</strong>',
        'Busca <strong>ccploreto.org.pe</strong>',
        'Cambia a <strong>"Permitir"</strong>',
        'Vuelve y toca <strong>"Ya lo activé"</strong>',
      ],
    };
  }
  if (isAndroid) {
    return {
      label: 'Android',
      pasos: [
        'Toca el menú <strong>⋮</strong> arriba a la derecha del navegador',
        'Selecciona <strong>"Configuración del sitio"</strong> o <strong>"Información del sitio"</strong>',
        'Busca <strong>"Notificaciones"</strong>',
        'Cambia de <strong>"Bloqueado"</strong> a <strong>"Permitir"</strong>',
        'Vuelve y toca <strong>"Ya lo activé"</strong>',
      ],
    };
  }
  if (isFirefox) {
    return {
      label: 'Firefox',
      pasos: [
        'Toca el ícono <strong>🛡️</strong> a la izquierda de la barra de direcciones',
        'Click en <strong>"Borrar permisos y recargar"</strong>',
        'Al cargar la página, acepta las notificaciones cuando aparezca el popup',
      ],
    };
  }
  return {
    label: 'Chrome/Edge',
    pasos: [
      'Toca el ícono <strong>🔒</strong> a la izquierda de la barra de direcciones',
      'Selecciona <strong>"Configuración del sitio"</strong>',
      'Busca <strong>"Notificaciones"</strong>',
      'Cambia de <strong>"Bloquear"</strong> a <strong>"Preguntar"</strong> o <strong>"Permitir"</strong>',
      'Recarga esta página',
    ],
  };
}

// zClaude-97o-b: al volver a la pestaña, si el usuario ya activó el permiso,
// retirar la cinta y el modal automáticamente.
window.addEventListener('focus', () => {
  if (Notification.permission === 'granted') {
    document.getElementById('alert-block-push')?.remove();
    document.getElementById('modal-guia-desbloqueo')?.remove();
  }
});
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
    div.innerHTML = "⚠️ NOTIFICACIONES BLOQUEADAS. No recibirá alertas. <u>Ver solución</u>";
    div.onclick = window.guiarDesbloqueo;
    document.body.prepend(div);
}

// Global
window.guiarDesbloqueo = function() {
    alert("🔒 ACTIVAR ALERTAS:\n\n1. Toca el candado 🔒 en la barra de dirección.\n2. Ve a 'Permisos' o 'Configuración'.\n3. Permite 'Notificaciones'.\n4. Recarga la página.");
};
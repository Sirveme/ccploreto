document.addEventListener('DOMContentLoaded', () => {
    // --- 1. CONFIGURACIÓN INICIAL ---
    const config = window.APP_CONFIG;
    const sirena = new Audio('/static/sounds/sirena.mp3');
    sirena.loop = true;

    let socket;
    let isAlertActive = false;

    // --- 2. WEBSOCKET ---
    function updateConnectionUI(status) {
        const el = document.getElementById('connection-status');
        if (!el) return;

        if (status === 'connected') {
            el.innerHTML = '<span class="w-2 h-2 rounded-full bg-green-500 animate-pulse"></span> Online';
            el.classList.remove('text-red-400', 'bg-red-900/30');
            el.classList.add('text-green-400', 'bg-green-900/30');
        } else if (status === 'disconnected') {
            el.innerHTML = '<span class="w-2 h-2 rounded-full bg-red-500"></span> Offline';
            el.classList.remove('text-green-400', 'bg-green-900/30');
            el.classList.add('text-red-400', 'bg-red-900/30');
        } else {
            el.innerHTML = '<span class="w-2 h-2 rounded-full bg-yellow-500 animate-ping"></span> ...';
        }
    }

    function connectWebSocket() {
        if (socket && socket.readyState === WebSocket.OPEN) return;

        updateConnectionUI('connecting');
        socket = new WebSocket(config.wsUrl);

        socket.onopen = () => {
            console.log("🟢 WS Conectado");
            updateConnectionUI('connected');
        };

        socket.onmessage = (event) => {
            const data = JSON.parse(event.data);
            
            if (data.type === "ALERTA_CRITICA") {
                mostrarAlerta(data);
            }
            else if (data.type === "BULLETIN") {
                // NUEVO: Agregar globo en tiempo real
                agregarGloboBoletin(data);
            }

            // NUEVO: ACTUALIZACIÓN DE PAGO (Aprobado o Rechazado)
            else if (data.type === "PAYMENT_UPDATE") {
                // 1. Sonido
                const sound = new Audio('/static/sounds/ding-dong.mp3'); 
                sound.play().catch(e=>{});

                // 2. Notificación Visual (Toast)
                if (data.status === 'approved') {
                    if(window.Toast) window.Toast.show(data.msg, 'success', 5000);
                } else {
                    if(window.Toast) window.Toast.show(data.msg, 'error', 8000); 
                }

                // 3. RECARGA ROBUSTA (La Solución)
                // Disparamos un evento global. El HTML lo escuchará y se recargará solo.
                document.body.dispatchEvent(new Event('update_debt'));
                
                // 4. Recargar lista de detalles (si está abierta)
                const detail = document.getElementById('debt-details-container');
                if(detail && detail.innerHTML.trim() !== "") {
                     htmx.ajax('GET', '/finance/my-debts-detail', {target: '#debt-details-container', swap: 'innerHTML'});
                }
            }

        };

        socket.onclose = () => {
            console.log("🔴 WS Desconectado. Reintentando...");
            updateConnectionUI('disconnected');
            setTimeout(connectWebSocket, 3000);
        };
        
        socket.onerror = (err) => {
            console.error("WS Error", err);
            socket.close();
        };
    }
    
    // Iniciar conexión
    connectWebSocket();

    // --- NUEVAS FUNCIONES PARA LOS GLOBOS ---

    // 1. Ver Detalle (Lee los data-attributes del elemento clickeado)
    // VER DETALLE BOLETÍN (Corregido visualmente)
    window.verDetalleBoletin = function(element) {
        const d = element.dataset;
        const modal = document.getElementById('modal-bulletin');
        
        // Inyectamos HTML estructurado para evitar superposición
        const headerHTML = `
            <div class="flex justify-between items-start mb-2">
                <h3 id="bulletin-title" class="text-2xl font-bold leading-tight pr-4 text-white">${d.title}</h3>
                <button onclick="document.getElementById('modal-bulletin').close()" class="text-white/70 hover:text-white p-1 -mt-1 -mr-2">
                    <i class="ph ph-x text-2xl"></i>
                </button>
            </div>
            <div class="flex items-center gap-2 text-xs font-mono text-white/80">
                <span id="bulletin-priority" class="uppercase font-bold px-2 py-0.5 rounded bg-black/20">INFO</span>
                <span>•</span>
                <span id="bulletin-date">--</span>
            </div>
        `;
        
        const header = document.getElementById('bulletin-header');
        header.innerHTML = headerHTML;

        // Contenido
        document.getElementById('bulletin-content').innerText = d.content;
        
        // Fecha
        if(d.date) {
            const dateObj = new Date(d.date.endsWith('Z') ? d.date : d.date + 'Z');
            document.getElementById('bulletin-date').innerText = dateObj.toLocaleString('es-PE', {
                day: 'numeric', month: 'numeric', hour: '2-digit', minute:'2-digit'
            });
        }
        
        // Colores
        header.className = "p-6 transition-colors duration-300"; 
        const badge = document.getElementById('bulletin-priority');
        
        if (d.priority === 'alert') {
            header.classList.add('bg-red-600');
            if(badge) badge.innerText = "URGENTE";
        } else if (d.priority === 'warning') {
            header.classList.add('bg-yellow-600');
            if(badge) badge.innerText = "AVISO";
        } else {
            header.classList.add('bg-indigo-600');
            if(badge) badge.innerText = "INFO";
        }

        modal.showModal();
    };

        // *******************************************************************************
    // COMPAIRTE BOLETÍN
    // *******************************************************************************
    // --- FUNCIÓN COMPARTIR BOLETÍN INTELIGENTE ---
    window.compartirBoletin = function() {
        const title = document.getElementById('bulletin-title').innerText;
        const content = document.getElementById('bulletin-content').innerText;
        const date = document.getElementById('bulletin-date').innerText;
        
        const textToShare = `📢 *${title}*\n📅 ${date}\n\n${content}\n\n_Vía LeAvisamos.pro_`;

        if (navigator.share && /Android|iPhone|iPad/i.test(navigator.userAgent)) {
            navigator.share({ title: title, text: textToShare }).catch(console.error);
        } else {
            navigator.clipboard.writeText(textToShare).then(() => {
                alert("📋 Texto copiado. Puedes pegarlo en WhatsApp Web.");
            });
        }
    };

    // 2. Agregar Globo Dinámico (Cuando llega WebSocket)
    function agregarGloboBoletin(data) {
        const board = document.getElementById('bulletin-board');
        
        // Definir colores según prioridad
        let classes = "bg-indigo-900/40 border-indigo-500 text-indigo-100";
        let icon = "ph-info";
        
        if (data.priority === 'alert') {
            classes = "bg-red-900/40 border-red-500 text-red-100";
            icon = "ph-warning-octagon";
        } else if (data.priority === 'warning') {
            classes = "bg-yellow-900/40 border-yellow-500 text-yellow-100";
            icon = "ph-warning";
        }

        // Limpieza de comillas para el data-attribute
        const safeContent = data.body.replace(/"/g, '&quot;');

        // Crear HTML
        const html = `
        <div onclick="verDetalleBoletin(this)"
             data-title="${data.title}"
             data-content="${safeContent}" 
             data-priority="${data.priority}"
             data-date="${new Date().toISOString()}"
             class="shrink-0 flex items-center gap-3 px-4 py-3 rounded-2xl cursor-pointer shadow-lg transition-transform active:scale-95 border-l-4 ${classes} animate-pulse">
            
            <div class="bg-black/20 p-2 rounded-full">
                <i class="ph ${icon} text-xl"></i>
            </div>
            
            <div>
                <p class="font-bold text-sm leading-none mb-1 whitespace-nowrap">${data.title}</p>
                <p class="text-[10px] opacity-70 uppercase tracking-wide">Toca para leer</p>
            </div>
        </div>
        `;
        
        // Insertar al principio
        board.insertAdjacentHTML('afterbegin', html);
        
        // Sonido suave
        const soundNews = new Audio('/static/sounds/ding-dong.mp3'); 
        soundNews.play().catch(e=>{});
    }


    // --- 4. BOTONES FLOTANTES (Pánico / Llegada / Check-in) ---

    // A. Botón Rojo (Pánico) - Siempre activo
    const btnPanico = document.getElementById('btn-panico');
    if (btnPanico) {
        btnPanico.addEventListener('click', () => {
            sirena.currentTime = 0;
            sirena.play().catch(e => {});

            // Confirmación visual rápida (Vibración)
            if (navigator.vibrate) navigator.vibrate([500, 200, 500]);

            // Enviar WebSocket
            socket.send(JSON.stringify({
                type: "PANIC_BUTTON",
                user: `${config.user.name} (${config.user.unit})`,
                location: "Ubicación pendiente...",
                coords: null,
                user_id: config.user.id
            }));

            // GPS en segundo plano... (tu código existente de GPS)
            if ("geolocation" in navigator) {
                navigator.geolocation.getCurrentPosition(pos => {
                    if (socket.readyState === WebSocket.OPEN) {
                        socket.send(JSON.stringify({
                            type: "GPS_UPDATE",
                            coords: { lat: pos.coords.latitude, lon: pos.coords.longitude }
                        }));
                    }
                });
            }
        });
    }

    // B. Botón Amarillo (Llegando)
    const btnLlegando = document.getElementById('btn-llegando');
    if (btnLlegando) {
        btnLlegando.addEventListener('click', () => {
            // Sonido suave
            const soundDing = new Audio('/static/sounds/ding-dong.mp3');
            soundDing.play().catch(e => {});

            if (confirm("¿Avisar a portería que estás llegando?")) {
                socket.send(JSON.stringify({
                    type: "PRE_ARRIVAL",
                    user: config.user.name,
                    unit: config.user.unit,
                    user_id: config.user.id
                }));
                
                // LÓGICA DE INTERFAZ: Mostrar botón verde
                const btnGreen = document.getElementById('btn-checkin-container');
                btnGreen.classList.remove('hidden');
                
                // Opcional: Ocultarlo automáticamente después de 10 minutos si no lo usa
                setTimeout(() => {
                    btnGreen.classList.add('hidden');
                }, 600000); 
            }
        });
    }

    // C. Botón Verde (Check-in WiFi)
    const btnCheckin = document.getElementById('btn-checkin');
    if (btnCheckin) {
        btnCheckin.addEventListener('click', async () => {
            // Feedback inmediato: Ocultar botón para que no le den doble clic
            document.getElementById('btn-checkin-container').classList.add('hidden');

            try {
                const response = await fetch('/api/proximity/check-in', { method: 'POST' });
                const result = await response.json();
                
                if (result.status === 'ok') {
                    // Sonido éxito
                    const soundOk = new Audio('/static/sounds/ding-dong.mp3');
                    soundOk.play().catch(e => {});
                    alert("✅ Ingreso registrado. Bienvenido a casa.");
                }
            } catch (error) {
                console.error("Error en check-in", error);
                alert("Error de conexión, pero el aviso fue intentado.");
                // Si falla, volver a mostrar el botón
                document.getElementById('btn-checkin-container').classList.remove('hidden');
            }
        });
    }
    
    // Función placeholder para el micro (futuro)
    window.activarNeural = function() {
        alert("Asistente de voz en construcción 🚧");
    };

    // --- 5. PANTALLA ROJA (Alerta Visual) ---
    function mostrarAlerta(data) {
        if (isAlertActive) return;
        isAlertActive = true;

        const overlay = document.getElementById('alerta-overlay');
        const msg = document.getElementById('alerta-msg');

        if (overlay && msg) {
            msg.innerHTML = `
                <strong style="display:block; margin-bottom:5px; font-size:1.5rem;">${data.user}</strong>
                <span>${data.msg}</span>
            `;
            
            // FORZAR VISIBILIDAD (La clave del éxito)
            overlay.style.display = 'flex'; 
        }
        
        if (navigator.vibrate) navigator.vibrate([1000, 500, 1000, 500, 1000]);
        sirena.currentTime = 0;
        sirena.play().catch(e => console.log("Audio:", e));
    }

    // HACER GLOBAL para que el botón HTML la encuentre
    window.cerrarAlerta = function() {
        console.log("Cerrando alerta desde el Dashboard...");
        sirena.pause();
        sirena.currentTime = 0;
        isAlertActive = false;
        
        const overlay = document.getElementById('alerta-overlay');
        if (overlay) {
            overlay.style.display = 'none';
        }
    };

    // --- 6. PUSH NOTIFICATIONS (Suscripción Robusta) ---
    window.activarNotificaciones = async function() {
        
        // 1. Verificaciones Iniciales
        if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
            alert("Tu navegador no soporta notificaciones push.");
            return;
        }

        if (!config.vapidPublicKey) {
            console.error("Falta VAPID Public Key en la configuración");
            alert("Error de configuración del sistema (VAPID Missing).");
            return;
        }

        // 2. Pedir permiso (Manejo explícito de estados)
        const permission = await Notification.requestPermission();
        
        // CASO A: Bloqueado por el usuario
        if (permission === 'denied') {
            alert("🚫 Notificaciones Bloqueadas.\n\nPara recibir alertas de seguridad, debes desbloquearlas manualmente:\n1. Toca el ícono de Candado 🔒 o Ajustes en la barra de dirección.\n2. Busca 'Notificaciones'.\n3. Selecciona 'Permitir'.\n4. Recarga la página.");
            return;
        }
        
        // CASO B: Usuario cerró la ventana sin decidir
        if (permission === 'default') {
            console.log("El usuario cerró el diálogo de permisos.");
            return;
        }

        // CASO C: Aceptado ('granted') - Procedemos a suscribir
        try {
            const registration = await navigator.serviceWorker.ready;
            
            // Intentar suscribir
            let subscription = await registration.pushManager.getSubscription();
            if (!subscription) {
                subscription = await registration.pushManager.subscribe({
                    userVisibleOnly: true,
                    applicationServerKey: urlBase64ToUint8Array(config.vapidPublicKey)
                });
            }

            // Datos del dispositivo
            const fingerprint = {
                timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
                platform: navigator.platform || 'Desconocido',
                is_pwa: window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true
            };

            // Enviar al Backend
            const response = await fetch('/api/push/subscribe', {
                method: 'POST',
                body: JSON.stringify({
                    subscription: subscription,
                    details: fingerprint
                }),
                headers: { 'Content-Type': 'application/json' }
            });

            if (response.ok) {
                alert("✅ Notificaciones activadas y dispositivo registrado.");
            } else {
                console.error("Error respuesta servidor:", await response.text());
                alert("Permiso concedido, pero hubo un error registrando el dispositivo en el servidor.");
            }

        } catch (error) {
            console.error("Error Técnico Push:", error);
            alert("Ocurrió un error técnico al activar las alertas: " + error.message);
        }
    };

    function urlBase64ToUint8Array(base64String) {
        const padding = '='.repeat((4 - base64String.length % 4) % 4);
        const base64 = (base64String + padding).replace(/\-/g, '+').replace(/_/g, '/');
        const rawData = window.atob(base64);
        const outputArray = new Uint8Array(rawData.length);
        for (let i = 0; i < rawData.length; ++i) {
            outputArray[i] = rawData.charCodeAt(i);
        }
        return outputArray;
    }

    // *******************************************************************************
    // --- BOLETÍN DE ÚLTIMO MINUTO (Modal) --- El que apace al hacer clic en la cinta
    // *******************************************************************************

    // Acción al hacer clic en la cinta
    window.verUltimoBoletin = async function() {
        // Mostrar carga
        const modal = document.getElementById('modal-bulletin');
        
        try {
            // Pedir datos frescos al servidor
            const response = await fetch('/api/bulletins/latest');
            const data = await response.json();
            
            if (data.status === 'ok') {
                // Llenar Modal
                document.getElementById('bulletin-title').innerText = data.title;
                document.getElementById('bulletin-content').innerText = data.content;
                
                // Formatear Fecha
                const dateObj = new Date(data.date);
                document.getElementById('bulletin-date').innerText = dateObj.toLocaleString();
                
                // Color de Cabecera según prioridad
                const header = document.getElementById('bulletin-header');
                const badge = document.getElementById('bulletin-priority');
                
                header.className = "p-6 transition-colors duration-300 flex justify-between items-start"; // Reset
                if (data.priority === 'alert') {
                    header.classList.add('bg-red-600');
                    badge.innerText = "🚨 URGENTE";
                } else if (data.priority === 'warning') {
                    header.classList.add('bg-yellow-600', 'text-black'); // Amarillo con texto negro lee mejor
                    badge.innerText = "⚠️ AVISO";
                } else {
                    header.classList.add('bg-indigo-600');
                    badge.innerText = "ℹ️ INFO";
                }

                modal.showModal();
            }
        } catch (e) {
            console.error("Error cargando boletín:", e);
        }
    };

    window.marcarLeido = function() {
        // Aquí podrías llamar al backend para registrar "Visto" en bulletin_events
        document.getElementById('modal-bulletin').close();
    };



    // Función auxiliar visual para copiar
    function copiarAlPortapapeles(texto) {
        navigator.clipboard.writeText(texto).then(() => {
            const btn = document.querySelector('button[onclick="compartirBoletin()"]');
            const originalHTML = btn.innerHTML;
            const originalClasses = btn.className; // Guardar clases originales
            
            // Cambio Visual: Éxito Verde
            btn.innerHTML = '<i class="ph ph-check text-xl"></i> <span>¡COPIADO!</span>';
            btn.classList.remove('border-slate-500', 'text-slate-300');
            btn.classList.add('border-green-500', 'text-green-400', 'bg-green-900/20');
            
            // Alerta flotante no intrusiva (Toast) o Alert simple
            // Usamos un alert simple como pediste para ser claros
            alert("✅ Texto copiado.\n\nAhora abre WhatsApp Web o tu correo y pégalo (Ctrl + V).");

            // Restaurar botón después de 3 segundos
            setTimeout(() => {
                btn.innerHTML = originalHTML;
                btn.className = originalClasses;
            }, 3000);
            
        }).catch(err => {
            console.error('Error al copiar', err);
            alert("No se pudo copiar automáticamente. Por favor selecciona el texto y cópialo.");
        });
    }


    // --- 7. IA: LECTOR DE VOUCHERS ---
    window.analizarVoucher = async function(input) {
        if (!input.files || !input.files[0]) return;

        // 1. MOSTRAR LOADING INMEDIATAMENTE
        const loader = document.getElementById('ai-analyzing');
        if(loader) {
            loader.classList.remove('hidden');
            loader.style.display = 'flex'; // Forzar display
        }

        const file = input.files[0];
        const formData = new FormData();
        formData.append('voucher', file);

        
        try {
            const response = await fetch('/finance/payment/analyze-voucher', {
                method: 'POST',
                body: formData
            });
            const result = await response.json();

            if (result.status === 'ok') {
                const data = result.data;
                console.log("IA Data:", data);

                // Llenar Monto
                if (data.amount) {
                    const el = document.getElementById('input-amount');
                    if(el) {
                        el.value = data.amount;
                        el.classList.add('border-green-500', 'bg-green-900/20'); // Feedback éxito
                    }
                }
                
                // Llenar Operación
                if (data.operation_code) {
                    const el = document.getElementById('input-operation');
                    if(el) {
                        el.value = data.operation_code;
                        el.classList.add('border-green-500', 'bg-green-900/20');
                    }
                }
                
                // Opcional: Sonido de éxito suave
                const s = new Audio('/static/sounds/ding-dong.mp3'); s.play().catch(e=>{});
            } else {
                console.warn("IA no pudo leer datos:", result.msg);
            }
        } catch (e) {
            console.error("Error analizando:", e);
        } finally {
            // OCULTAR AL TERMINAR
            if(loader) {
                loader.classList.add('hidden');
                loader.style.display = 'none';
            }
        }
    };


});
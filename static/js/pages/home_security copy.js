document.addEventListener('DOMContentLoaded', () => {
    // --- 1. CONFIGURACIÓN DE SONIDOS ---
    const radioSiren = new Audio('/static/sounds/sirena.mp3');
    const soundDing = new Audio('/static/sounds/ding-dong.mp3'); 
    
    // Configuración inicial de audio
    radioSiren.loop = true;   // La sirena no para hasta que el guardia atienda
    soundDing.loop = false;   // El timbre suena una sola vez

    // Estado de Zoom
    let currentFontSize = 12; // px
    const synth = window.speechSynthesis;

    // --- 2. VARIABLES GLOBALES ---
    let socket = null;
    let selectedUsers = {}; // CAMBIO: Ahora es un Objeto { id: {name, unit} }
    
    // URL dinámica segura
    const wsUrl = window.APP_CONFIG ? window.APP_CONFIG.wsUrl : 
                  (window.location.protocol === 'https:' ? 'wss:' : 'ws:') + '//' + window.location.host + '/ws/alerta';

    // --- 3. GESTIÓN DE CONEXIÓN (El Semáforo) ---
    function updateConnectionStatus(isOnline) {
        const statusText = document.getElementById('status-text');
        const box = document.getElementById('status-box');
        
        if (isOnline) {
            statusText.innerHTML = '<span class="text-green-400">●</span> Sistema Online';
            box.classList.remove('border-red-500', 'opacity-50');
        } else {
            statusText.innerHTML = '<span class="text-red-500 animate-pulse">●</span> DESCONECTADO - Reintentando...';
            box.classList.add('border-red-500', 'opacity-50');
        }
    }

    function connect() {
        if (socket && socket.readyState === WebSocket.OPEN) return;

        console.log("🔄 Conectando a:", wsUrl);
        socket = new WebSocket(wsUrl);
        
        socket.onopen = () => {
            console.log("🟢 WS Conectado");
            updateConnectionStatus(true);
            logSystem("Conexión Centinela Establecida.", "text-green-500");
        };
        
        socket.onmessage = (e) => {
            const data = JSON.parse(e.data);
            handleMessage(data);
        };
        
        socket.onclose = () => {
            console.log("🔴 WS Cerrado");
            updateConnectionStatus(false);
            // Reintentar en 3 segundos
            setTimeout(connect, 3000);
        };

        socket.onerror = (err) => {
            console.error("WS Error:", err);
            socket.close();
        };
    }

    // --- 4. MANEJO DE MENSAJES (El Cerebro) ---
    function handleMessage(data) {
        if (data.type === "ALERTA_CRITICA") {
            // ROJO: Pánico
            triggerVisual(data, "bg-red-600", "⚠️ PÁNICO", radioSiren, true);
        } 
        else if (data.type === "PRE_ARRIVAL") {
            // AMARILLO: Llegada
            triggerVisual(data, "bg-yellow-600", "🚶 LLEGANDO", soundDing, false);
        }
        else if (data.type === "INFO_ACCESS") {
            // VERDE: Transición inteligente (Actualiza la tarjeta amarilla si existe)
            actualizarLlegada(data);
        }
        else if (data.type === "GPS_UPDATE") {
            updateLogWithGPS(data);
        }
    }

    // --- 5. FUNCIONES VISUALES Y DE LOG ---

    // A. Lógica visual principal (Colores y Sonidos)
    function triggerVisual(data, colorClass, titlePrefix, soundObj, isLoop) {
        const box = document.getElementById('status-box');
        const statusText = document.getElementById('status-text');

        const time = new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
        
        // A. CAMBIO DE COLOR FORZADO
        if (colorClass.includes('red')) {
            box.style.backgroundColor = '#dc2626'; 
            box.style.borderColor = '#fee2e2';
            statusText.style.color = '#ffffff';
            document.getElementById('btn-silenciar').classList.remove('hidden');
        } 
        else if (colorClass.includes('yellow')) {
            box.style.backgroundColor = '#ca8a04';
            box.style.borderColor = '#fef08a';
            statusText.style.color = '#ffffff';
        }
        else {
            box.style.backgroundColor = ''; 
            box.style.borderColor = '';
            statusText.style.color = '';
        }
        
        box.classList.add('animate-pulse');
        statusText.innerText = `${titlePrefix}: ${data.user}`;

        // B. CREAR TARJETA DE LOG
        const divId = data.user_id ? `id="log-user-${data.user_id}"` : '';
        
        // Colores
        let logBg = 'rgba(255,255,255,0.1)';
        let logBorder = '#64748b'; 
        if (colorClass.includes('red')) { logBg = 'rgba(220, 38, 38, 0.3)'; logBorder = '#ef4444'; }
        if (colorClass.includes('yellow')) { logBg = 'rgba(202, 138, 4, 0.3)'; logBorder = '#eab308'; }

        // Texto para leer
        const readText = `${titlePrefix}. ${data.user}. ${data.msg || ''}`.replace(/'/g, "\\'");

        const html = `
            <div ${divId} style="background: ${logBg}; border-left: 4px solid ${logBorder}; padding: 8px; margin-bottom: 8px; color: white; display: flex; justify-content: space-between; align-items: start;" class="fade-me-in cursor-pointer">
                <div>
                    <strong>${titlePrefix}: ${data.user} (${data.unit || ''})</strong><br>
                    <span style="font-size: 0.75rem; opacity: 0.9;">${data.msg || ''}</span>
                </div>
                <div style="display: flex; flex-direction: column; align-items: end; gap: 5px;">
                    <span style="font-family: monospace; font-size: 1rem; font-weight: bold; opacity: 0.8;">${time}</span>
                    <button onclick="event.stopPropagation(); speakText('${readText}')" class="text-white/70 hover:text-white" title="Leer">
                        <i class="ph ph-speaker-high text-lg"></i>
                    </button>
                </div>
            </div>
        `;
        appendToLog(html);

        // C. SONIDO
        if (soundObj) {
            soundObj.currentTime = 0;
            soundObj.loop = isLoop;
            soundObj.play().catch(e => console.log("Audio bloqueado:", e));
        }
        
        if (navigator.vibrate) navigator.vibrate([500, 200, 500]);
    }

    // B. Transición de Amarillo a Verde
    function actualizarLlegada(data) {
        // Reset cabecera
        const headerText = document.getElementById('status-text').innerText;
        if (headerText.includes("LLEGANDO") || headerText.includes(data.user)) {
            window.silenciarAlarma(); 
        }

        const existingLog = document.getElementById(`log-user-${data.user_id}`);
        const time = new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
        
        // Texto para leer
        const readText = `Ya llegó: ${data.user}. Confirmado por ${data.method || 'Sistema'}.`.replace(/'/g, "\\'");

        if (existingLog) {
            // Actualizar tarjeta existente
            existingLog.style.background = 'rgba(22, 163, 74, 0.3)'; 
            existingLog.style.borderLeftColor = '#22c55e';
            
            existingLog.innerHTML = `
                <div style="display:flex; justify-content:space-between; align-items:start;">
                    <div>
                        <strong style="color:#4ade80;">✔ YA LLEGÓ: ${data.user}</strong>
                        <div style="font-size:0.75rem; color:#cbd5e1; margin-top:2px;">
                            Confirmado por: <strong>${data.method || 'Sistema'}</strong>
                        </div>
                    </div>
                    <div style="display: flex; flex-direction: column; align-items: end; gap: 5px;">
                        <span style="font-size:1.2rem; color:#4ade80; font-family:monospace; font-weight:bold;">${time}</span>
                        <button onclick="event.stopPropagation(); speakText('${readText}')" class="text-green-400 hover:text-white" title="Leer">
                            <i class="ph ph-speaker-high text-lg"></i>
                        </button>
                    </div>
                </div>
            `;
            const soundOk = new Audio('/static/sounds/ding-dong.mp3');
            soundOk.play().catch(e=>{});
        } else {
            // Si no había tarjeta previa
            logSystem(`✅ INGRESO: ${data.user} (${data.unit || ''})`, "text-green-400 font-bold");
            // Nota: logSystem ya incluye su propio botón de lectura
        }
    }

    // C. Resetear Alarma / Cabecera (Global)
    window.silenciarAlarma = function() {
        radioSiren.pause();
        radioSiren.currentTime = 0;
        
        // Reset Visual Cabecera
        const box = document.getElementById('status-box');
        box.style.backgroundColor = ''; // Quitar color inline
        box.style.borderColor = '';
        box.classList.remove('animate-pulse'); // Quitar animación
        
        document.getElementById('status-text').innerText = "Sistema Online";
        document.getElementById('status-text').style.color = '';
        
        document.getElementById('btn-silenciar').classList.add('hidden');
        logSystem("Alerta atendida/reseteada.", "text-blue-400");
    };

    // --- 6. BOTÓN PÁNICO DEL GUARDIA ---
    const btnPanicoGuardia = document.getElementById('btn-panico-centinela');
    
    if (btnPanicoGuardia) {
        btnPanicoGuardia.addEventListener('click', () => {
            // Verificar conexión antes de confirmar
            if (!socket || socket.readyState !== WebSocket.OPEN) {
                alert("⚠️ SIN CONEXIÓN: Intentando reconectar...");
                connect(); 
                return;
            }

            if(!confirm("¿ACTIVAR ALERTA GENERAL?")) return;

            // Enviar señal
            socket.send(JSON.stringify({
                type: "PANIC_BUTTON",
                user: "SEGURIDAD",
                location: "Activado por Guardia",
                coords: null,
                user_id: 0
            }));
            
            // Feedback Visual Inmediato (Local)
            triggerVisual(
                {user: 'SEGURIDAD', msg: 'Activación Manual'}, 
                'bg-red-600', '⚠️ PÁNICO', radioSiren, true
            );
        });
    }

    // --- 7. FUNCIONES DEL BUSCADOR (Cards de Vecinos) ---

    // Toggle Selección (Click en tarjeta)
    // A. Toggle Selección (Ahora acepta 'position')
    // A. Toggle Selección (AHORA ACEPTA POSITION)
    window.toggleSelection = function(id, name, unit, position) {

        console.log("Click en:", name, "Cargo:", position);

        const card = document.getElementById(`card-${id}`);
        const check = document.getElementById(`check-${id}`);
        const actionBar = document.getElementById('action-bar');
        
        if (selectedUsers[id]) {
            // Deseleccionar
            delete selectedUsers[id];
            if (card) {
                card.classList.remove('ring-2', 'ring-green-500', 'bg-slate-800');
                card.classList.add('bg-slate-900');
            }
            if (check) check.classList.add('hidden');
        } else {
            // Seleccionar (GUARDAMOS EL CARGO AQUÍ)
            // Si position viene vacío o null, usamos 'Residente'
            const cargo = position && position !== 'None' ? position : 'Residente';
            alert("El cao es: " + cargo);

            selectedUsers[id] = { 
                name: name, 
                unit: unit, 
                position: cargo // <--- Guardamos el dato
            }; 
            
            if (card) {
                card.classList.add('ring-2', 'ring-green-500', 'bg-slate-800');
                card.classList.remove('bg-slate-900');
            }
            if (check) check.classList.remove('hidden');
        }

        // Actualizar UI
        const counter = document.getElementById('count-selected');
        if(counter) counter.innerText = Object.keys(selectedUsers).length;
        
        if (actionBar) {
            if (Object.keys(selectedUsers).length > 0) actionBar.classList.remove('hidden');
            else actionBar.classList.add('hidden');
        }
    };

    // B. Registrar Seleccionados (PASA EL CARGO AL ENVÍO)
    window.registrarSeleccionados = async function() {
        alert("Registrando con cargos dinámicos");
        const ids = Object.keys(selectedUsers);
        if (ids.length === 0) return;

        const btn = document.querySelector('#action-bar button');
        if(btn) {
            btn.innerHTML = '<i class="ph ph-spinner animate-spin"></i> Procesando...';
            btn.disabled = true;
        }

        for (const id of ids) {
            const user = selectedUsers[id];

            // DEBUG: Ver qué estamos enviando
            console.log("Enviando:", user.name, user.position);
            alert("Enviando: " + user.name + " con cargo: " + user.position);
            // AQUÍ ESTABA EL ERROR ANTES:
            // Pasamos user.position (convertido a mayúsculas para que se vea bien)
            await enviarRegistroBackend(id, user.name, user.position.toUpperCase());
        }

        // Limpieza
        selectedUsers = {};
        const resultsContainer = document.getElementById('search-results');
        if(resultsContainer) {
            resultsContainer.innerHTML = `<div class="text-center text-green-500 py-10 font-bold">✅ Registrado</div>`;
        }
        
        document.querySelector('input[name="query"]').value = "";
        document.getElementById('action-bar').classList.add('hidden');
        
        setTimeout(() => {
            if(resultsContainer) resultsContainer.innerHTML = "";
            document.querySelector('input[name="query"]').focus();
        }, 1500);
    };

    // C. Enviar al Backend (RECIBE EL TIPO DINÁMICO)
    async function enviarRegistroBackend(id, nombreReal, tipoRelacion) {
        const formData = new FormData();
        // USAMOS LA VARIABLE tipoRelacion EN LUGAR DE 'RESIDENTE' FIJO
        formData.append('tipo', tipoRelacion); 
        formData.append('detalle', nombreReal);
        formData.append('member_id', id);

        try {
            const response = await fetch('/centinela/log', { method: 'POST', body: formData });
            if (response.ok) {
                const html = await response.text();
                const log = document.getElementById('security-log');
                if(log) log.insertAdjacentHTML('afterbegin', html);
            }
        } catch (e) { console.error(e); }
    }

    // Registrar Seleccionados
    // B. Registrar Masivo (Corregido)
    window.registrarSeleccionados = async function() {
        const ids = Object.keys(selectedUsers);
        if (ids.length === 0) return;

        const btn = document.querySelector('#action-bar button');
        if(btn) {
            btn.innerHTML = '<i class="ph ph-spinner animate-spin"></i> Procesando...';
            btn.disabled = true;
        }

        // Iterar y enviar datos REALES
        for (const id of ids) {
            const user = selectedUsers[id];
            // Enviamos el nombre real, no "Validado por Centinela"
            await enviarRegistroBackend(id, user.name); 
        }

        // Limpieza
        selectedUsers = {};
        
        // Mensaje Éxito
        const resultsContainer = document.getElementById('search-results');
        if(resultsContainer) {
            resultsContainer.innerHTML = `
                <div class="flex flex-col items-center justify-center h-full text-green-500 fade-in-up mt-10">
                    <i class="ph ph-check-circle text-8xl mb-4 drop-shadow-lg scale-in"></i>
                    <p class="text-2xl font-bold">Ingreso Registrado</p>
                </div>
            `;
        }
        
        const inputQuery = document.querySelector('input[name="query"]');
        if(inputQuery) inputQuery.value = "";
        
        const actionBar = document.getElementById('action-bar');
        if(actionBar) actionBar.classList.add('hidden');
        
        setTimeout(() => {
            if(resultsContainer) resultsContainer.innerHTML = "";
            if(inputQuery) inputQuery.focus();
        }, 1500);
    };

    // C. Enviar al Backend (Corregido Error 422)
    // C. Enviar al Backend (CORREGIDO: Ahora recibe y usa 'tipoRelacion')
    async function enviarRegistroBackend(id, nombreReal, tipoRelacion) {
        const formData = new FormData();
        
        // AQUÍ ESTABA EL ERROR: Antes decía 'RESIDENTE', ahora usa la variable
        // Si tipoRelacion viene vacío, usamos 'RESIDENTE' por defecto
        formData.append('tipo', tipoRelacion || 'RESIDENTE'); 
        alert("tiPO rELACIÓN: " + tipoRelacion);
        formData.append('detalle', nombreReal);
        formData.append('member_id', id);

        try {
            const response = await fetch('/centinela/log', { 
                method: 'POST', 
                body: formData 
            });
            
            if (response.ok) {
                const html = await response.text();
                const log = document.getElementById('security-log');
                if(log) log.insertAdjacentHTML('afterbegin', html);
            } else {
                console.error("Error servidor:", await response.text());
            }
        } catch (e) { console.error(e); }
    }

    // --- 8. HELPERS ---
    function updateLogWithGPS(data) {
        const html = `
            <div class="bg-blue-900/30 border-l-4 border-blue-500 p-2 text-blue-300 ml-4 mb-2 text-[10px] fade-me-in">
                📡 GPS RECIBIDO <a href="https://maps.google.com/?q=${data.coords.lat},${data.coords.lon}" target="_blank" class="underline text-white ml-2 font-bold cursor-pointer">VER MAPA</a>
            </div>
        `;
        appendToLog(html);
    }

    function logSystem(text, colorClass) {
        const time = new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
        
        // Mapeo simple de color
        let colorStyle = 'color: #94a3b8;'; 
        if (colorClass.includes('green')) colorStyle = 'color: #4ade80;';
        if (colorClass.includes('red')) colorStyle = 'color: #ef4444;';
        if (colorClass.includes('orange')) colorStyle = 'color: #fb923c;';
        
        // Ahora (Incluyendo hora en la lectura):
        const fullText = `A las ${time}. ${text}`;

        // Preparar texto para lectura (Escapar comillas simples)
        const safeText = fullText.replace(/'/g, "\\'");
        
        // Botón Parlante
        const speakBtn = `
            <button onclick="event.stopPropagation(); speakText('${safeText}')" 
                    class="ml-2 text-slate-500 hover:text-white transition-colors" 
                    title="Leer">
                <i class="ph ph-speaker-high"></i>
            </button>
        `;
        
        const html = `<div style="border-left: 2px solid #334155; padding-left: 8px; margin-bottom: 4px; font-size: 10px; color: #64748b; display: flex; align-items: center;">
            <span style="${colorStyle} margin-right: 5px;">●</span> [${time}] ${text} ${speakBtn}
        </div>`;
        appendToLog(html);
    }

    function appendToLog(htmlString) {
        const log = document.getElementById('security-log');
        log.insertAdjacentHTML('afterbegin', htmlString);
    }

    // Función global para el buscador (limpiar)
    window.limpiarForm = function() {
        setTimeout(() => {
            document.getElementById('input-detalle').value = "";
            document.getElementById('input-unidad').value = "";
            document.getElementById('search-results').innerHTML = "";
        }, 100);
    };


    // --- 9. ACCESIBILIDAD e IA ---

    // A. Lectura de Texto (TTS)
    window.speakText = function(text) {
        if (synth.speaking) synth.cancel();
        
        // 1. Limpiar Emojis (Los reemplaza por vacío)
        let cleanText = text.replace(/([\u2700-\u27BF]|[\uE000-\uF8FF]|\uD83C[\uDC00-\uDFFF]|\uD83D[\uDC00-\uDFFF]|[\u2011-\u26FF]|\uD83E[\uDD10-\uDDFF])/g, '');
        
        // 2. Mejorar lectura de hora (Si encuentra formato HH:MM)
        // Ejemplo: Convierte "14:30" en "14 horas y 30 minutos" para que suene natural
        cleanText = cleanText.replace(/(\d{1,2}):(\d{2})/g, "$1 horas $2");

        // 3. Quitar caracteres raros del log visual
        cleanText = cleanText.replace(/[●\[\]]/g, ""); 

        console.log("Leyendo:", cleanText); // Debug

        const utter = new SpeechSynthesisUtterance(cleanText);
        const voices = synth.getVoices();
        const esVoice = voices.find(v => v.lang.includes('es-PE')) || voices.find(v => v.lang.includes('es'));
        if (esVoice) utter.voice = esVoice;
        
        utter.rate = 1.1;
        synth.speak(utter);
    };

    // B. Resumen Inteligente (Briefing)
    window.playBriefing = async function() {
        const btn = document.querySelector('button[onclick="playBriefing()"]');
        const original = btn.innerHTML;
        btn.innerHTML = '<i class="ph ph-spinner animate-spin"></i> ...';
        
        try {
            const res = await fetch('/api/brain/briefing');
            const data = await res.json();
            
            if (data.status === 'ok') {
                logSystem("🤖 IA: " + data.text, "text-indigo-400");
                window.speakText(data.text);
            }
        } catch (e) {
            console.error(e);
        } finally {
            btn.innerHTML = original;
        }
    };

    // C. Control de Tamaño de Fuente
    window.changeFontSize = function(delta) {
        currentFontSize += delta;
        if (currentFontSize < 10) currentFontSize = 10;
        if (currentFontSize > 24) currentFontSize = 24;
        
        document.getElementById('security-log').style.fontSize = `${currentFontSize}px`;
    };

    // --- INICIAR ---
    connect();
});
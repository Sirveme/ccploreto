// ==========================================
// 1. VARIABLES Y CONFIGURACIÓN GLOBAL
// ==========================================
let currentFontSize = 12;
let socket = null;
let selectedUsers = {}; 

// Sonidos
const radioSiren = new Audio('/static/sounds/sirena.mp3');
const soundDing = new Audio('/static/sounds/ding-dong.mp3'); 
radioSiren.loop = true;
soundDing.loop = false;

const synth = window.speechSynthesis;

// ==========================================
// 2. FUNCIONES DE UTILIDAD (HELPERS) - GLOBALES
// ==========================================

// A. Insertar en el Log (DOM)
function appendToLog(htmlString) {
    const log = document.getElementById('security-log');
    if (log) log.insertAdjacentHTML('afterbegin', htmlString);
}

// B. Generar Log del Sistema
window.logSystem = function(text, colorClass) {
    const time = new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
    
    let colorStyle = 'color: #94a3b8;'; 
    if (colorClass && colorClass.includes('green')) colorStyle = 'color: #4ade80;';
    if (colorClass && colorClass.includes('red')) colorStyle = 'color: #ef4444;';
    if (colorClass && colorClass.includes('indigo')) colorStyle = 'color: #818cf8;';
    
    // Limpieza para TTS
    const safeText = text.replace(/'/g, "\\'");
    
    // Botón Parlante pequeño
    const speakBtn = `<button onclick="event.stopPropagation(); window.speakText('${safeText}')" class="ml-2 text-slate-500 hover:text-white" title="Leer"><i class="ph ph-speaker-high"></i></button>`;
    
    const html = `<div style="border-left: 2px solid #334155; padding-left: 8px; margin-bottom: 4px; font-size: 10px; color: #64748b; display: flex; align-items: center;">
        <span style="${colorStyle} margin-right: 5px;">●</span> [${time}] ${text} ${speakBtn}
    </div>`;
    appendToLog(html);
};

// C. Texto a Voz (TTS)
window.speakText = function(text) {
    if (synth.speaking) synth.cancel();
    
    // Limpieza de texto para lectura natural
    let clean = text.replace(/([\u2700-\u27BF]|[\uE000-\uF8FF]|\uD83C[\uDC00-\uDFFF]|\uD83D[\uDC00-\uDFFF]|[\u2011-\u26FF]|\uD83E[\uDD10-\uDDFF])/g, '');
    clean = clean.replace(/[●\[\]]/g, "");
    clean = clean.replace(/(\d{1,2}):(\d{2})/g, "$1 horas $2"); // Leer hora bien

    const utter = new SpeechSynthesisUtterance(clean);
    const voices = synth.getVoices();
    // Priorizar español
    const esVoice = voices.find(v => v.lang.includes('es-PE')) || voices.find(v => v.lang.includes('es'));
    if (esVoice) utter.voice = esVoice;
    
    utter.rate = 1.1;
    synth.speak(utter);
};

// ==========================================
// 3. FUNCIONES DE ACCIÓN (BOTONES)
// ==========================================

// A. Zoom (A+ / A-)
window.changeFontSize = function(delta) {
    currentFontSize += delta;
    if (currentFontSize < 10) currentFontSize = 10;
    if (currentFontSize > 24) currentFontSize = 24;
    
    const log = document.getElementById('security-log');
    if(log) log.style.fontSize = `${currentFontSize}px`;
};

// B. Resumen IA (Briefing)
window.playBriefing = async function() {
    const btn = document.querySelector('button[onclick="playBriefing()"]');
    const original = btn ? btn.innerHTML : '';
    if(btn) btn.innerHTML = '<i class="ph ph-spinner animate-spin"></i>';
    
    try {
        const res = await fetch('/api/brain/briefing');
        const data = await res.json();
        
        // Usamos logSystem que AHORA SÍ es global
        if (data.status === 'ok') {
            window.logSystem("🤖 RESUMEN: " + data.text, "text-indigo-400");
            window.speakText(data.text);
        } else {
            window.logSystem("⚠️ Error IA: " + data.text, "text-red-400");
        }
    } catch(e) { 
        console.error(e);
        window.logSystem("Error de conexión con IA", "text-red-400");
    } 
    finally { if(btn) btn.innerHTML = original; }
};

// C. Silenciar Alarma
window.silenciarAlarma = function() {
    radioSiren.pause();
    radioSiren.currentTime = 0;
    const box = document.getElementById('status-box');
    if(box) {
        box.style.backgroundColor = ''; 
        box.style.borderColor = '';
        box.classList.remove('animate-pulse');
    }
    document.getElementById('status-text').innerText = "Sistema Online";
    document.getElementById('status-text').style.color = '';
    document.getElementById('btn-silenciar').classList.add('hidden');
    window.logSystem("Alerta atendida manualmente.", "text-blue-400");
};

// D. Toggle Selección (Click en tarjeta)
window.toggleSelection = function(id, name, unit, position) {
    const card = document.getElementById(`card-${id}`);
    const check = document.getElementById(`check-${id}`);
    const actionBar = document.getElementById('action-bar');
    const counter = document.getElementById('count-selected');
    
    if (selectedUsers[id]) {
        delete selectedUsers[id];
        if(card) { card.classList.remove('ring-2', 'ring-green-500', 'bg-slate-800'); card.classList.add('bg-slate-900'); }
        if(check) check.classList.add('hidden');
    } else {
        const cargoFinal = (position && position !== 'None') ? position : 'Residente';
        selectedUsers[id] = { name: name, unit: unit, position: cargoFinal };
        if(card) { card.classList.add('ring-2', 'ring-green-500', 'bg-slate-800'); card.classList.remove('bg-slate-900'); }
        if(check) check.classList.remove('hidden');
    }

    if(counter) counter.innerText = Object.keys(selectedUsers).length;
    if (actionBar) actionBar.classList.toggle('hidden', Object.keys(selectedUsers).length === 0);
};

// E. Registrar Masivo
window.registrarSeleccionados = async function() {
        const ids = Object.keys(selectedUsers);
        if (ids.length === 0) return;

        const btn = document.querySelector('#action-bar button');
        if(btn) { 
            btn.innerHTML = '<i class="ph ph-spinner animate-spin"></i> ...'; 
            btn.disabled = true; 
        }

        for (const id of ids) {
            const user = selectedUsers[id];
            const cargo = user.position ? user.position.toUpperCase() : 'RESIDENTE';
            await enviarRegistroBackend(id, user.name, cargo);
        }

        // Limpieza de datos
        selectedUsers = {};
        
        // UI: Mensaje de Éxito (Sin rebote infinito)
        const results = document.getElementById('search-results');
        if(results) {
            // Usamos 'fade-in-up' (una sola vez) en lugar de 'animate-bounce'
            results.innerHTML = `<div class="flex flex-col items-center justify-center h-full text-green-500 fade-in-up mt-10">
                <i class="ph ph-check-circle text-8xl mb-4 drop-shadow-lg"></i>
                <p class="text-2xl font-bold">Ingreso Registrado</p>
            </div>`;
        }
        
        // Limpiar input
        const inputQuery = document.querySelector('input[name="query"]');
        if(inputQuery) inputQuery.value = "";
        
        // Ocultar barra de acción (CON PROTECCIÓN CONTRA NULL)
        const actionBar = document.getElementById('action-bar');
        if(actionBar) {
            actionBar.classList.add('hidden');
        }
        
        // Resetear vista
        setTimeout(() => {
            if(results) results.innerHTML = "";
            if(inputQuery) inputQuery.focus();
        }, 1500);
    };

async function enviarRegistroBackend(id, nombreReal, tipoRelacion) {
    const formData = new FormData();
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

// ==========================================
// 4. INICIALIZACIÓN (WEBSOCKETS)
// ==========================================
document.addEventListener('DOMContentLoaded', () => {
    
    const wsUrl = window.APP_CONFIG ? window.APP_CONFIG.wsUrl : 
                  (window.location.protocol === 'https:' ? 'wss:' : 'ws:') + '//' + window.location.host + '/ws/alerta';

    function connect() {
        if (socket && socket.readyState === WebSocket.OPEN) return;
        socket = new WebSocket(wsUrl);
        
        socket.onopen = () => {
            updateConnectionStatus(true);
            window.logSystem("Centinela Online.", "text-green-500");
        };
        socket.onmessage = (e) => handleMessage(JSON.parse(e.data));
        socket.onclose = () => {
            updateConnectionStatus(false);
            setTimeout(connect, 3000);
        };
    }

    function updateConnectionStatus(isOnline) {
        const statusText = document.getElementById('status-text');
        const box = document.getElementById('status-box');
        if(!statusText) return;

        if (isOnline) {
            statusText.innerHTML = '<span class="text-green-400">●</span> Sistema Online';
            if(box) box.classList.remove('border-red-500', 'opacity-50');
        } else {
            statusText.innerHTML = '<span class="text-red-500 animate-pulse">●</span> DESCONECTADO';
            if(box) box.classList.add('border-red-500', 'opacity-50');
        }
    }

    function handleMessage(data) {
        if (data.type === "ALERTA_CRITICA") triggerVisual(data, "bg-red-600", "⚠️ PÁNICO", radioSiren, true);
        else if (data.type === "PRE_ARRIVAL") triggerVisual(data, "bg-yellow-600", "🚶 LLEGANDO", soundDing, false);
        else if (data.type === "INFO_ACCESS") actualizarLlegada(data);
    }

    // Funciones Visuales Internas (Usan variables globales)
    function triggerVisual(data, colorClass, titlePrefix, soundObj, isLoop) {
        const box = document.getElementById('status-box');
        const statusText = document.getElementById('status-text');
        
        // Estilos
        if (colorClass.includes('red')) {
            box.style.backgroundColor = '#dc2626'; box.style.borderColor = '#fee2e2'; statusText.style.color = '#fff';
            document.getElementById('btn-silenciar').classList.remove('hidden');
        } else if (colorClass.includes('yellow')) {
            box.style.backgroundColor = '#ca8a04'; box.style.borderColor = '#fef08a'; statusText.style.color = '#fff';
        }
        
        box.classList.add('animate-pulse');
        statusText.innerText = `${titlePrefix}: ${data.user}`;

        // Log Card
        const divId = data.user_id ? `id="log-user-${data.user_id}"` : '';
        const time = new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
        const readText = `${titlePrefix}. ${data.user}. ${data.msg || ''}`.replace(/'/g, "\\'");

        let logBg = 'rgba(255,255,255,0.1)';
        let logBorder = '#64748b'; 
        if (colorClass.includes('red')) { logBg = 'rgba(220, 38, 38, 0.3)'; logBorder = '#ef4444'; }
        if (colorClass.includes('yellow')) { logBg = 'rgba(202, 138, 4, 0.3)'; logBorder = '#eab308'; }

        const html = `
            <div ${divId} class="${colorClass}/30 p-2 text-white mb-2 fade-me-in" style="background: ${logBg}; border-left: 4px solid ${logBorder};">
                <div style="display:flex; justify-content:space-between;">
                    <div>
                        <strong>${titlePrefix}: ${data.user} (${data.unit || ''})</strong><br>
                        <span class="text-xs opacity-90">${data.msg || ''}</span>
                    </div>
                    <div style="text-align:right">
                        <span style="font-family: monospace; font-size: 1rem;">${time}</span>
                        <button onclick="event.stopPropagation(); window.speakText('${readText}')" class="text-white/70 hover:text-white ml-2" title="Leer"><i class="ph ph-speaker-high"></i></button>
                    </div>
                </div>
            </div>`;
        appendToLog(html);

        if (soundObj) { soundObj.currentTime = 0; soundObj.loop = isLoop; soundObj.play().catch(e=>{}); }
        if (navigator.vibrate) navigator.vibrate([500, 200]);
    }

    function actualizarLlegada(data) {
        const headerText = document.getElementById('status-text').innerText;
        if (headerText.includes("LLEGANDO") || headerText.includes(data.user)) window.silenciarAlarma();

        const existingLog = document.getElementById(`log-user-${data.user_id}`);
        const time = new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
        const readText = `Ya llegó: ${data.user}`;

        if(existingLog) {
            existingLog.style.background = 'rgba(22, 163, 74, 0.3)';
            existingLog.style.borderLeftColor = '#22c55e';
            existingLog.innerHTML = `
                <div style="display:flex; justify-content:space-between; align-items:start;">
                    <div><strong style="color:#4ade80">✔ YA LLEGÓ: ${data.user}</strong><div style="font-size:0.75rem; color:#cbd5e1;">Confirmado</div></div>
                    <div style="display: flex; flex-direction: column; align-items: end; gap: 5px;">
                        <span style="font-size:1.2rem; color:#4ade80; font-family:monospace; font-weight:bold;">${time}</span>
                        <button onclick="event.stopPropagation(); window.speakText('${readText}')" class="text-green-400 hover:text-white"><i class="ph ph-speaker-high"></i></button>
                    </div>
                </div>`;
            const s = new Audio('/static/sounds/ding-dong.mp3'); s.play().catch(e=>{});
        } else {
            window.logSystem(`✅ INGRESO: ${data.user} (${data.unit || ''})`, "text-green-400 font-bold");
        }
    }

    // Botón Pánico Guardia
    const btnPanicoGuardia = document.getElementById('btn-panico-centinela');
    if (btnPanicoGuardia) {
        btnPanicoGuardia.addEventListener('click', () => {
            if(!confirm("¿ACTIVAR ALERTA GENERAL?")) return;
            if (socket && socket.readyState === WebSocket.OPEN) {
                socket.send(JSON.stringify({ type: "PANIC_BUTTON", user: "SEGURIDAD", location: "Activado por Guardia", coords: null, user_id: 0 }));
                triggerVisual({user: 'SEGURIDAD', msg: 'Activación Manual'}, 'bg-red-600', '⚠️ PÁNICO', radioSiren, true);
            } else {
                alert("Error: Sin conexión.");
            }
        });
    }

    // Iniciar
    connect();
});
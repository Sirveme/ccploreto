if (typeof NeuralCore === 'undefined') {
    
    class NeuralCore {
        constructor() {
            this.synth = window.speechSynthesis;
            this.recognition = null;
            this.isListening = false;
            
            // UI
            this.orb = document.getElementById('dock-mic') || document.getElementById('btn-neural-orb');
            this.uiContainer = document.getElementById('sdui-viewport');
            this.uiContent = document.getElementById('sdui-content');
            
            this.bubbleContainer = document.getElementById('ai-thought-bubble');
            this.bubbleMain = document.getElementById('ai-text-main');
            this.bubbleSub = document.getElementById('ai-text-sub');
            
            this.silenceTimer = null;
            this.lastTranscript = ""; // Guardar lo último escuchado
            
            this.initVoice();
            this.initRecognition();
        }

        // --- 1. CONFIGURACIÓN ---
        initVoice() {
            const loadVoices = () => {
                const voices = this.synth.getVoices();
                this.voice = voices.find(v => v.lang.includes('es-PE')) || 
                             voices.find(v => v.lang.includes('es-MX')) || 
                             voices.find(v => v.lang.includes('es'));
            };
            if (this.synth.onvoiceschanged !== undefined) {
                this.synth.onvoiceschanged = loadVoices;
            }
            loadVoices();
        }

        initRecognition() {
            const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
            if (!SpeechRecognition) return;
            
            this.recognition = new SpeechRecognition();
            this.recognition.lang = 'es-PE';
            this.recognition.continuous = true; 
            this.recognition.interimResults = true;

            this.recognition.onstart = () => {
                this.isListening = true;
                this.lastTranscript = ""; // Reset
                this.showBubble("Escuchando...", "Dicta tu orden...", "info");
                if(this.orb) this.orb.classList.add('listening-mode');
            };

            this.recognition.onend = () => {
                if (this.isListening) { 
                    this.isListening = false;
                    if(this.orb) this.orb.classList.remove('listening-mode');
                }
            };

            this.recognition.onresult = (event) => {
                clearTimeout(this.silenceTimer);
                
                let interim = "";
                for (let i = event.resultIndex; i < event.results.length; ++i) {
                   if (event.results[i].isFinal) {
                       this.lastTranscript += event.results[i][0].transcript;
                   } else {
                       interim += event.results[i][0].transcript;
                   }
                }
                
                // Mostrar en pantalla lo que escucha
                const fullText = this.lastTranscript + interim;
                if(this.bubbleSub) this.bubbleSub.innerText = fullText;
                
                // Si hay texto, programar el envío automático tras 2.5 seg de silencio
                if (fullText.trim().length > 0) {
                    this.silenceTimer = setTimeout(() => {
                        this.stopAndProcess(fullText);
                    }, 2500);
                }
            };
            
            this.recognition.onerror = (e) => {
                // Ignorar si es no-speech (ruido)
                if (e.error !== 'no-speech') {
                    console.error("Error Voz:", e.error);
                    this.speak("Hubo un problema con el micrófono.");
                    this.hideBubble();
                }
            };
        }

        // Función clave: Detiene y envía lo que tenga
        stopAndProcess(textOverride = null) {
            this.recognition.stop();
            this.isListening = false;
            if(this.orb) this.orb.classList.remove('listening-mode');
            
            // Usar el texto pasado O lo último guardado en memoria
            const textToSend = textOverride || this.lastTranscript;

            if (textToSend && textToSend.trim().length > 0) {
                this.processCommand(textToSend);
            } else {
                this.hideBubble(); // Se cancela si no hay texto
            }
        }

        toggleListen() {
            if (this.isListening) {
                // CLIC MANUAL PARA DETENER: Fuerza el envío inmediato
                clearTimeout(this.silenceTimer);
                // Pasamos el texto acumulado hasta el momento (incluyendo interim que esté en el DOM)
                const currentText = this.bubbleSub ? this.bubbleSub.innerText : this.lastTranscript;
                this.stopAndProcess(currentText);
            } else {
                this.recognition.start();
            }
        }

        // --- 2. CEREBRO ---
        async processCommand(text) {
            this.showBubble("Pensando...", text, "info");
            console.log("🧠 Enviando:", text);

            try {
                const response = await fetch('/api/ai/chat', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ message: text })  // ← "message", no "command"
                });
                const result = await response.json();
                
                // El endpoint retorna: { response, action, colegiado }
                if (result.response) {
                    // Hablar la respuesta
                    const mensaje = result.response.title || result.response.description || "Procesando";
                    this.speak(mensaje);
                    
                    // Ejecutar acción si existe
                    if (result.action) {
                        setTimeout(() => {
                            this.executeAIAction(result.action, result.colegiado);
                        }, 1500);
                    } else {
                        setTimeout(() => this.hideBubble(), 3000);
                    }
                } else {
                    this.showBubble("Error", "No entendí", "error");
                    this.speak("No pude procesar la orden.");
                    setTimeout(() => this.hideBubble(), 3000);
                }
            } catch (e) {
                console.error(e);
                this.showBubble("Error", "Conexión fallida", "error");
                setTimeout(() => this.hideBubble(), 3000);
            }
        }


        // --- NUEVA FUNCIÓN para acciones del AI Chat ---
        executeAIAction(action, colegiado = null) {
            console.log("⚡ AI Action:", action, colegiado ? colegiado.nombre : 'Sin sesión');
            
            switch(action) {
                case 'open_pago_form':
                    if (colegiado && colegiado.deuda && colegiado.deuda.total > 0) {
                        // Con sesión → Cargar formulario pre-llenado
                        const params = new URLSearchParams({
                            colegiado_id: colegiado.id,
                            nombre: colegiado.nombre,
                            monto: colegiado.deuda.total
                        }).toString();
                        this.loadServerUI(`/finance/payment/form?${params}`);
                    } else {
                        // Sin sesión → Modal público
                        const modal = document.getElementById('reactivacionModal');
                        if (modal) {
                            if (typeof openModal === 'function') openModal(modal);
                            else modal.classList.add('active');
                            // Activar tab Pagar
                            setTimeout(() => {
                                const tabs = modal.querySelectorAll('.tab-btn, .modal-tab');
                                if (tabs[2]) tabs[2].click();
                            }, 100);
                        }
                    }
                    this.hideBubble();
                    break;
                    
                case 'open_estado_cuenta':
                    if (typeof ModalPagos !== 'undefined') {
                        ModalPagos.open();
                    }
                    this.hideBubble();
                    break;
                    
                case 'open_certificados':
                    if (typeof ModalCertificados !== 'undefined') {
                        ModalCertificados.open();
                    } else if (typeof abrirModalLazy === 'function') {
                        abrirModalLazy('modal-certificados');
                    }
                    this.hideBubble();
                    break;
                    
                default:
                    this.hideBubble();
            }
        }

        // --- 3. EJECUCIÓN SDUI ---
        // --- 4. EJECUCIÓN SDUI ---
        executeAction(actionData) {
            console.log("⚡ Ejecutando:", actionData);
            
            const type = actionData.type;
            const target = actionData.target; // Aquí viene 'modal-payment'
            const payload = actionData.payload || {};
            const data = payload.data || {};

            // A. Feedback Voz
            if (actionData.message) this.speak(actionData.message);

            // B. RENDERIZAR COMPONENTE O MODAL DE PAGO
            // CORRECCIÓN: Verificamos 'target' O 'payload.id'
            if (type === 'render_component' || (type === 'open_modal' && (target === 'modal-payment' || payload.id === 'modal-payment'))) {
                
                // Construir URL
                let url = payload.url;
                
                // Si es el caso de pago y no viene URL explícita, la construimos
                if (!url) {
                    const params = new URLSearchParams(data).toString();
                    url = `/finance/payment/form?${params}`;
                }

                this.loadServerUI(url);
            }
            
            // C. OTROS MODALES (Estáticos)
            else if (type === 'open_modal') {
                const el = document.getElementById(target);
                if(el) el.showModal();
            }
            
            // D. CLICKS
            else if (type === 'click') {
                const el = document.getElementById(target);
                if(el) el.click();
            }
            
            // E. NAVEGACIÓN
            else if (type === 'navigate') {
                setTimeout(() => window.location.href = target, 1500);
            }
            
            // F. FORMS ADMIN
            else if (type === 'fill_form') {
                 this.fillForm(payload);
            }

            // Ocultar burbuja
            if (type !== 'render_component' && target !== 'modal-payment') {
                setTimeout(() => this.hideBubble(), 2500);
            }
        }

        // --- 4. GESTOR UI ---
        async loadServerUI(url) {
            console.log("🔍 Buscando contenedor SDUI...");
            
            // Buscar elementos frescos del DOM
            this.uiContainer = document.getElementById('sdui-viewport');
            this.uiContent = document.getElementById('sdui-content');

            // VALIDACIÓN CRÍTICA
            if (!this.uiContainer || !this.uiContent) {
                console.error("❌ ERROR FATAL: No se encontró <div id='sdui-viewport'> en base.html");
                alert("Error de Sistema: Falta el contenedor de interfaz (sdui-viewport).");
                this.hideBubble();
                return;
            }

            try {
                console.log("🔄 Iniciando Fetch a:", url);
                
                // Petición al servidor
                const response = await fetch(url);
                
                if (!response.ok) {
                    throw new Error(`Error del Servidor: ${response.status} ${response.statusText}`);
                }
                
                const html = await response.text();
                console.log("✅ HTML Recibido (" + html.length + " chars)");

                // 1. Inyectar HTML
                this.uiContent.innerHTML = html;
                
                // 2. Activar HTMX (si existe)
                if (window.htmx) htmx.process(this.uiContent);

                // 3. Mostrar Contenedor (CSS)
                this.uiContainer.classList.remove('hidden');
                this.uiContainer.style.display = 'flex'; // Forzar display
                
                // 4. Animación suave
                setTimeout(() => {
                    this.uiContainer.classList.remove('opacity-0');
                    this.uiContent.classList.remove('scale-95', 'opacity-0');
                    this.uiContent.classList.add('scale-100', 'opacity-100');
                }, 50);

                // 5. Apagar burbuja de pensamiento
                this.hideBubble(); 

                // 6. Configurar cierre al hacer clic fuera
                this.uiContainer.onclick = (e) => {
                    if (e.target === this.uiContainer) this.closeServerUI();
                };
                
                // 7. Auto-focus (Mejora UX)
                const input = this.uiContent.querySelector('input:not([type="hidden"])');
                if (input) input.focus();

            } catch (e) {
                console.error("🚨 SDUI Error:", e);
                this.speak("Ocurrió un error al cargar la pantalla.");
                this.hideBubble();
                alert("Error técnico: " + e.message);
            }
        }

        closeServerUI() {
            // Búsqueda dinámica también aquí
            const viewport = document.getElementById('sdui-viewport');
            const content = document.getElementById('sdui-content');
            
            if (!viewport || !content) return;

            // Animación salida
            content.classList.remove('scale-100');
            content.classList.add('scale-95');
            viewport.classList.add('opacity-0');
            
            setTimeout(() => {
                viewport.classList.add('hidden');
                viewport.style.display = 'none';
                content.innerHTML = ""; // Limpiar memoria
            }, 300);
        }


        fillForm(payload) {
            const data = payload.data;
            if (data) {
                for (const [key, value] of Object.entries(data)) {
                    const fields = document.querySelectorAll(`[name="${key}"]`);
                    fields.forEach(field => {
                        if (field.type === 'radio') {
                            if (field.value === value) field.checked = true;
                        } else {
                            field.value = value;
                            field.style.transition = "background-color 0.5s";
                            field.style.backgroundColor = "rgba(79, 70, 229, 0.2)";
                            setTimeout(() => field.style.backgroundColor = "", 1000);
                        }
                    });
                }
                if (payload.submit) {
                    const form = document.querySelector('form'); 
                    if (form) setTimeout(() => form.requestSubmit(), 1000);
                }
            }
        }

        // --- 5. UTILIDADES ---
        showBubble(main, sub, type) {
            if(!this.bubbleContainer) return;
            this.bubbleMain.innerText = main;
            this.bubbleSub.innerText = sub || "";
            this.bubbleContainer.classList.remove('hidden');
            
            const content = document.getElementById('ai-bubble-content');
            content.className = "px-8 py-6 rounded-3xl shadow-2xl flex flex-col items-center text-center border-2 backdrop-blur-xl transition-all";
            
            if (type === 'success') content.classList.add('bg-green-900/90', 'border-green-500', 'text-white');
            else if (type === 'error') content.classList.add('bg-red-900/90', 'border-red-500', 'text-white');
            else content.classList.add('bg-slate-900/90', 'border-indigo-500', 'text-white');
            
            setTimeout(() => this.bubbleContainer.classList.add('bubble-active'), 10);
        }

        hideBubble() {
            if(!this.bubbleContainer) return;
            this.bubbleContainer.classList.remove('bubble-active');
            setTimeout(() => this.bubbleContainer.classList.add('hidden'), 300);
        }

        speak(text) {
            if (this.synth.speaking) this.synth.cancel();
            const utter = new SpeechSynthesisUtterance(text);
            if (this.voice) utter.voice = this.voice;
            utter.rate = 1.1;
            this.synth.speak(utter);
        }
    }

    window.Neural = new NeuralCore();
    window.closeNeuralUI = () => window.Neural.closeServerUI();
}
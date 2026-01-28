if (typeof NeuralCore === 'undefined') {
    
    class NeuralCore {
        constructor() {
            // Configuración inicial
            this.synth = window.speechSynthesis;
            this.recognition = null;
            this.isListening = false;
            this.voice = null;
            
            // Temporizador para el "Oído Paciente"
            this.silenceTimer = null;
            
            // Elementos UI (Busca ambos tipos de botón de micrófono)
            this.orb = document.getElementById('dock-mic') || document.getElementById('btn-neural-orb');
            
            // Elementos de la Burbuja de Pensamiento
            this.bubbleContainer = document.getElementById('ai-thought-bubble');
            this.bubbleMain = document.getElementById('ai-text-main');
            this.bubbleSub = document.getElementById('ai-text-sub');
            
            this.initVoice();
            this.initRecognition();
        }

        // --- 1. CONFIGURACIÓN DE VOZ (TTS) ---
        initVoice() {
            const loadVoices = () => {
                const voices = this.synth.getVoices();
                // Prioridad: Español Perú -> Español México -> Español España -> Cualquiera con 'es'
                this.voice = voices.find(v => v.lang.includes('es-PE')) || 
                             voices.find(v => v.lang.includes('es-MX')) || 
                             voices.find(v => v.lang.includes('es-ES')) ||
                             voices.find(v => v.lang.includes('es'));
                
                if (this.voice) {
                    console.log("🗣️ Voz configurada:", this.voice.name);
                }
            };

            if (this.synth.onvoiceschanged !== undefined) {
                this.synth.onvoiceschanged = loadVoices;
            }
            loadVoices();
        }

        // --- 2. RECONOCIMIENTO DE VOZ (STT) ---
        initRecognition() {
            const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
            
            if (!SpeechRecognition) {
                console.warn("⚠️ Reconocimiento de voz no soportado en este navegador.");
                if(this.orb) this.orb.style.display = 'none'; 
                return;
            }
            
            this.recognition = new SpeechRecognition();
            this.recognition.lang = 'es-PE';
            this.recognition.continuous = true; // Escucha continua
            this.recognition.interimResults = true; // Resultados parciales mientras hablas

            this.recognition.onstart = () => {
                this.isListening = true;
                this.showBubble("Escuchando...", "Dicta tu orden...", "info");
                if(this.orb) this.orb.classList.add('listening-mode'); // Clase para animar
            };

            this.recognition.onend = () => {
                // Si el reconocimiento se apaga solo pero no hemos terminado lógicamente
                if (this.isListening) {
                    this.isListening = false;
                    if(this.orb) this.orb.classList.remove('listening-mode');
                }
            };

            this.recognition.onresult = (event) => {
                // Cada vez que detecta voz, reiniciamos el temporizador de silencio
                clearTimeout(this.silenceTimer);

                let finalTranscript = '';
                let interimTranscript = '';

                for (let i = event.resultIndex; i < event.results.length; ++i) {
                    if (event.results[i].isFinal) {
                        finalTranscript += event.results[i][0].transcript;
                    } else {
                        interimTranscript += event.results[i][0].transcript;
                    }
                }

                // Feedback visual en tiempo real
                if (this.bubbleSub) {
                    this.bubbleSub.innerText = finalTranscript || interimTranscript;
                }

                // Lógica de "Silencio = Enviar"
                // Esperamos 2.5 segundos de silencio para procesar el comando
                if (finalTranscript.trim().length > 0 || interimTranscript.trim().length > 0) {
                    this.silenceTimer = setTimeout(() => {
                        const fullText = finalTranscript || interimTranscript;
                        this.stopAndProcess(fullText);
                    }, 2500); 
                }
            };
            
            this.recognition.onerror = (e) => {
                if (e.error !== 'no-speech') {
                    console.error("Error Voz:", e.error);
                    this.speak("Hubo un error con el micrófono.");
                    this.hideBubble();
                }
            };
        }

        // --- 3. CONTROL Y PROCESAMIENTO ---
        
        toggleListen() {
            if (!this.recognition) return alert("Navegador no compatible");
            
            if (this.isListening) {
                // Parada manual
                this.recognition.stop();
                this.isListening = false;
                clearTimeout(this.silenceTimer);
                this.hideBubble();
            } else {
                // Inicio manual
                this.recognition.start();
            }
        }

        stopAndProcess(text) {
            this.recognition.stop();
            this.isListening = false;
            if(this.orb) this.orb.classList.remove('listening-mode');
            
            if (text) {
                this.processCommand(text);
            }
        }

        async processCommand(text) {
            this.showBubble("Pensando...", text, "info");
            console.log("🧠 Enviando al cerebro:", text);

            try {
                // Llamada al Backend (api.py)
                const response = await fetch('/api/brain/process-command', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ 
                        command: text, 
                        url: window.location.pathname 
                    })
                });
                
                const result = await response.json();
                
                if (result.status === 'ok') {
                    // ÉXITO: Ejecutar la acción devuelta por la IA
                    this.executeAction(result.action);
                } else {
                    // ERROR CONTROLADO
                    this.showBubble("Error", result.msg || "No entendí", "error");
                    this.speak(result.action?.message || "Lo siento, hubo un problema.");
                    setTimeout(() => this.hideBubble(), 3000);
                }

            } catch (e) {
                console.error("Error de Red/Servidor:", e);
                this.showBubble("Error de Conexión", "Verifica tu internet", "error");
                this.speak("No puedo conectar con el servidor.");
                setTimeout(() => this.hideBubble(), 3000);
            }
        }

        // --- 4. EJECUCIÓN DE ACCIONES (El Brazo Ejecutor) ---
        executeAction(actionData) {
            if (!actionData || !actionData.type) {
                console.warn("Acción vacía recibida");
                return;
            }

            console.log("⚡ Ejecutando Acción:", actionData);
            const type = actionData.type;
            const payload = actionData.payload || {};
            const target = actionData.target;

            // A. Feedback de Voz (Prioridad 1)
            if (actionData.message) {
                this.speak(actionData.message);
                // Mostrar mensaje en la burbuja verde
                this.showBubble("Entendido", actionData.message, "success");
                setTimeout(() => this.hideBubble(), 4000); // Ocultar después de hablar
            }

            // B. NAVEGACIÓN
            if (type === 'navigate') {
                setTimeout(() => window.location.href = target, 1500);
            }

            // C. ABRIR MODAL (Dinámico)
            else if (type === 'open_modal') {
                const modalId = target || payload.id;
                const modal = document.getElementById(modalId);
                
                if (modal) {
                    modal.showModal();
                    
                    // Lógica especial para el modal de pagos (Carga HTMX)
                    if (modalId === 'modal-payment') {
                        // Cargar el formulario limpio desde el servidor
                        fetch('/finance/payment/form')
                            .then(r => r.text())
                            .then(html => {
                                modal.innerHTML = html;
                                // Reactivar HTMX en el contenido inyectado
                                if(window.htmx) htmx.process(modal);
                                
                                // AUTO-LLENADO DE DATOS (Si la IA extrajo info)
                                if (payload.data && payload.data.amount) {
                                    setTimeout(() => {
                                        const inputAmount = document.getElementById('input-amount');
                                        if(inputAmount) {
                                            inputAmount.value = payload.data.amount;
                                            // Efecto visual
                                            inputAmount.style.transition = "background 0.5s";
                                            inputAmount.style.backgroundColor = "rgba(74, 222, 128, 0.2)";
                                        }
                                    }, 200);
                                }
                            });
                    }
                } else {
                    console.warn(`Modal ${modalId} no encontrado en esta página.`);
                    this.speak("No puedo abrir esa ventana aquí.");
                }
            }
            
            // D. CLICKS EN BOTONES (Pánico / Llegada)
            else if (type === 'click') {
                const el = document.getElementById(target);
                if (el) {
                    el.click();
                } else {
                    console.warn(`Botón ${target} no encontrado.`);
                }
            }

            // E. LLENADO DE FORMULARIOS (Para Admin)
            else if (type === 'fill_form') {
                const data = payload.data;
                if (data) {
                    for (const [key, value] of Object.entries(data)) {
                        const fields = document.querySelectorAll(`[name="${key}"]`);
                        fields.forEach(field => {
                            if (field.type === 'radio') {
                                if (field.value === value) field.checked = true;
                            } else {
                                field.value = value;
                                // Efecto visual
                                field.style.backgroundColor = "rgba(79, 70, 229, 0.2)";
                                setTimeout(() => field.style.backgroundColor = "", 1500);
                            }
                        });
                    }
                    
                    // Auto-envío
                    if (payload.submit === true) {
                        const form = document.getElementById(actionData.target);
                        if (form) {
                            setTimeout(() => {
                                if (window.htmx) htmx.trigger(form, 'submit');
                                else form.requestSubmit();
                            }, 1000);
                        }
                    }
                }
            }
        }

        // --- 5. UTILIDADES DE INTERFAZ ---
        showBubble(mainText, subText, type) {
            if(!this.bubbleContainer) return;
            
            this.bubbleMain.innerText = mainText;
            this.bubbleSub.innerText = subText || "";
            
            this.bubbleContainer.classList.remove('hidden');
            // Timeout pequeño para permitir la transición CSS
            requestAnimationFrame(() => {
                this.bubbleContainer.classList.add('bubble-active');
            });

            const content = document.getElementById('ai-bubble-content');
            // Reset clases
            content.className = "px-8 py-6 rounded-3xl shadow-2xl flex flex-col items-center text-center transform transition-all duration-300 scale-90 opacity-0 border-2 backdrop-blur-xl";
            
            if (type === 'success') {
                content.classList.add('bg-green-900/90', 'border-green-500', 'text-white');
            } else if (type === 'error') {
                content.classList.add('bg-red-900/90', 'border-red-500', 'text-white');
            } else {
                content.classList.add('bg-slate-900/90', 'border-indigo-500', 'text-white');
            }
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

    // Instancia Global
    window.Neural = new NeuralCore();
    console.log("🧠 NeuralCore v2.0 Cargado");
}
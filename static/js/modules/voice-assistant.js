/**
 * Voice Assistant Module
 * =====================
 * Motor de comandos de voz para el CCPL
 * 
 * Características:
 * - Speech-to-Text (STT) con Web Speech API
 * - Text-to-Speech (TTS) con voces en español
 * - Gestión de estado de conversación
 * - Callbacks para integración con UI
 * 
 * Uso:
 *   const assistant = new VoiceAssistant({
 *       onListeningStart: () => {},
 *       onListeningEnd: () => {},
 *       onResult: (transcript) => {},
 *       onError: (error) => {}
 *   });
 *   assistant.startListening();
 *   assistant.speak("Hola, ¿en qué puedo ayudarte?");
 */

class VoiceAssistant {
    constructor(options = {}) {
        this.options = {
            lang: 'es-PE',
            continuous: false,
            interimResults: false,
            onListeningStart: () => {},
            onListeningEnd: () => {},
            onResult: () => {},
            onInterimResult: () => {},
            onError: () => {},
            onSpeakStart: () => {},
            onSpeakEnd: () => {},
            ...options
        };
        
        this.isListening = false;
        this.isSpeaking = false;
        this.recognition = null;
        this.synthesis = window.speechSynthesis;
        this.preferredVoice = null;
        
        this._initRecognition();
        this._initVoices();
    }
    
    // ==========================================
    // INICIALIZACIÓN
    // ==========================================
    
    _initRecognition() {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        
        if (!SpeechRecognition) {
            console.warn('VoiceAssistant: Speech Recognition no soportado');
            return;
        }
        
        this.recognition = new SpeechRecognition();
        this.recognition.lang = this.options.lang;
        this.recognition.continuous = this.options.continuous;
        this.recognition.interimResults = this.options.interimResults;
        
        this.recognition.onstart = () => {
            this.isListening = true;
            this.options.onListeningStart();
        };
        
        this.recognition.onend = () => {
            this.isListening = false;
            this.options.onListeningEnd();
        };
        
        this.recognition.onresult = (event) => {
            const result = event.results[event.results.length - 1];
            const transcript = result[0].transcript.trim();
            const confidence = result[0].confidence;
            
            if (result.isFinal) {
                this.options.onResult(transcript, confidence);
            } else {
                this.options.onInterimResult(transcript);
            }
        };
        
        this.recognition.onerror = (event) => {
            this.isListening = false;
            this.options.onListeningEnd();
            
            const errorMessages = {
                'no-speech': 'No se detectó voz. Intenta de nuevo.',
                'audio-capture': 'No se pudo acceder al micrófono.',
                'not-allowed': 'Permiso de micrófono denegado.',
                'network': 'Error de red. Verifica tu conexión.',
                'aborted': 'Escucha cancelada.',
                'language-not-supported': 'Idioma no soportado.'
            };
            
            const message = errorMessages[event.error] || `Error: ${event.error}`;
            this.options.onError(event.error, message);
        };
    }
    
    _initVoices() {
        // Las voces se cargan de forma asíncrona
        const loadVoices = () => {
            const voices = this.synthesis.getVoices();
            
            // Buscar voz en español preferida
            this.preferredVoice = voices.find(v => 
                v.lang === 'es-PE' || 
                v.lang === 'es-MX' || 
                v.lang.startsWith('es')
            );
            
            // Fallback a cualquier voz disponible
            if (!this.preferredVoice && voices.length > 0) {
                this.preferredVoice = voices[0];
            }
        };
        
        loadVoices();
        
        // Chrome carga voces de forma asíncrona
        if (this.synthesis.onvoiceschanged !== undefined) {
            this.synthesis.onvoiceschanged = loadVoices;
        }
    }
    
    // ==========================================
    // SPEECH-TO-TEXT
    // ==========================================
    
    get isSupported() {
        return this.recognition !== null;
    }
    
    startListening() {
        if (!this.recognition) {
            this.options.onError('not-supported', 'Reconocimiento de voz no soportado');
            return false;
        }
        
        if (this.isListening) {
            return true;
        }
        
        // Detener TTS si está hablando
        if (this.isSpeaking) {
            this.stopSpeaking();
        }
        
        try {
            this.recognition.start();
            return true;
        } catch (error) {
            console.error('VoiceAssistant: Error al iniciar', error);
            return false;
        }
    }
    
    stopListening() {
        if (this.recognition && this.isListening) {
            this.recognition.stop();
        }
    }
    
    // ==========================================
    // TEXT-TO-SPEECH
    // ==========================================
    
    speak(text, options = {}) {
        return new Promise((resolve, reject) => {
            if (!this.synthesis) {
                reject(new Error('TTS no soportado'));
                return;
            }
            
            // Cancelar cualquier speech anterior
            this.synthesis.cancel();
            
            const utterance = new SpeechSynthesisUtterance(text);
            utterance.lang = options.lang || this.options.lang;
            utterance.rate = options.rate || 1.0;
            utterance.pitch = options.pitch || 1.0;
            utterance.volume = options.volume || 1.0;
            
            if (this.preferredVoice) {
                utterance.voice = this.preferredVoice;
            }
            
            utterance.onstart = () => {
                this.isSpeaking = true;
                this.options.onSpeakStart();
            };
            
            utterance.onend = () => {
                this.isSpeaking = false;
                this.options.onSpeakEnd();
                resolve();
            };
            
            utterance.onerror = (event) => {
                this.isSpeaking = false;
                this.options.onSpeakEnd();
                reject(event);
            };
            
            this.synthesis.speak(utterance);
        });
    }
    
    stopSpeaking() {
        if (this.synthesis) {
            this.synthesis.cancel();
            this.isSpeaking = false;
        }
    }
    
    // ==========================================
    // UTILIDADES
    // ==========================================
    
    /**
     * Escucha y retorna el resultado como promesa
     */
    listen() {
        return new Promise((resolve, reject) => {
            const originalOnResult = this.options.onResult;
            const originalOnError = this.options.onError;
            
            this.options.onResult = (transcript, confidence) => {
                this.options.onResult = originalOnResult;
                this.options.onError = originalOnError;
                originalOnResult(transcript, confidence);
                resolve({ transcript, confidence });
            };
            
            this.options.onError = (error, message) => {
                this.options.onResult = originalOnResult;
                this.options.onError = originalOnError;
                originalOnError(error, message);
                reject(new Error(message));
            };
            
            this.startListening();
        });
    }
    
    /**
     * Pregunta algo y espera respuesta
     */
    async ask(question, options = {}) {
        await this.speak(question, options);
        return this.listen();
    }
}

// Exportar para uso global
window.VoiceAssistant = VoiceAssistant;
/**
 * AI FAB - Asistente de Inteligencia Artificial
 * static/js/components/ai-fab.js
 * 
 * Componente autónomo que:
 * - Inyecta su propio HTML
 * - Muestra presencia constante de IA
 * - Muestra consumo institucional (propaganda)
 * - Permite seleccionar modelo (Claude, GPT, Gemini)
 * - Chat integrado
 */

const AIFab = {
    isOpen: false,
    chatOpen: false,
    currentModel: 'claude',
    
    // Configuración
    config: {
        showTooltipDelay: 2000,
        hideTooltipDelay: 12000,
        apiEndpoint: '/api/ai',
        models: {
            claude: {
                name: 'Claude',
                provider: 'Anthropic',
                modelo: 'claude-3-5-sonnet',
                color: '#f59e0b',
                recomendado: true,
                disponible: true
            },
            gpt: {
                name: 'ChatGPT',
                provider: 'OpenAI', 
                modelo: 'gpt-4o-mini',
                color: '#10a37f',
                recomendado: false,
                disponible: true
            },
            gemini: {
                name: 'Gemini',
                provider: 'Google',
                modelo: 'gemini-pro',
                color: '#4285f4',
                recomendado: false,
                disponible: true
            },
            grok: {
                name: 'Grok',
                provider: 'xAI',
                modelo: 'grok-1',
                color: '#000000',
                recomendado: false,
                disponible: false  // Próximamente
            }
        }
    },
    
    // Estadísticas institucionales (se cargan del servidor)
    stats: {
        consultasMes: 0,
        costoMes: 0,
        limiteMes: 10,
        ahorroEstimado: 0
    },
    
    // Historial del chat actual
    chatHistory: [],
    
    /**
     * Inicializa el componente
     */
    init() {
        console.log('[AI FAB] Inicializando asistente IA...');
        this.injectHTML();
        this.bindEvents();
        this.loadStats();
        this.showInitialTooltip();
    },
    
    /**
     * Inyecta todo el HTML necesario
     */
    injectHTML() {
        // Buscar o crear container
        let container = document.getElementById('ai-fab-root');
        if (!container) {
            container = document.createElement('div');
            container.id = 'ai-fab-root';
            document.body.appendChild(container);
        }
        
        container.innerHTML = `
            <div class="ai-fab-container">
                <!-- Tooltip de bienvenida -->
                <div class="ai-fab-tooltip" id="ai-fab-tooltip">
                    <button class="ai-fab-tooltip-close" onclick="AIFab.hideTooltip()">
                        <i class="ph ph-x"></i>
                    </button>
                    <div class="ai-fab-tooltip-header">
                        <i class="ph ph-sparkle"></i>
                        Asistente IA Disponible
                    </div>
                    <p>Resuelve tus dudas al instante. Consulta sobre trámites, cuotas, certificados y más.</p>
                    <div class="ai-fab-usage">
                        <span class="ai-fab-usage-label">
                            <i class="ph ph-chart-line-up"></i>
                            Tu colegio invierte en IA:
                        </span>
                        <div class="ai-fab-usage-bar">
                            <div class="ai-fab-usage-fill" id="ai-usage-fill" style="width: 35%;"></div>
                        </div>
                        <span id="ai-usage-text">$3.50</span>
                    </div>
                </div>
                
                <!-- Menú de selección de modelo -->
                <div class="ai-fab-menu" id="ai-fab-menu">
                    <button class="ai-fab-option" onclick="AIFab.selectModel('claude')">
                        <div class="ai-provider-icon claude">A</div>
                        <span>Claude</span>
                        <span class="ai-option-badge recomendado">Recomendado</span>
                    </button>
                    <button class="ai-fab-option" onclick="AIFab.selectModel('gpt')">
                        <div class="ai-provider-icon gpt"><i class="ph ph-openai-logo"></i></div>
                        <span>ChatGPT</span>
                    </button>
                    <button class="ai-fab-option" onclick="AIFab.selectModel('gemini')">
                        <div class="ai-provider-icon gemini">G</div>
                        <span>Gemini</span>
                        <span class="ai-option-badge gratis">Gratis</span>
                    </button>
                    <div class="ai-fab-separator"></div>
                    <button class="ai-fab-option" onclick="AIFab.selectModel('grok')" style="opacity:0.5;">
                        <div class="ai-provider-icon grok">X</div>
                        <span>Grok</span>
                        <span class="ai-option-badge pronto">Pronto</span>
                    </button>
                </div>
                
                <!-- Botón principal -->
                <button class="ai-fab" id="ai-fab-button" onclick="AIFab.toggle()">
                    <i class="ph ph-brain" id="ai-fab-icon"></i>
                    <span class="ai-fab-status" id="ai-fab-status"></span>
                    <span class="ai-fab-label">IA Institucional</span>
                </button>
            </div>
            
            <!-- Modal de Chat -->
            <div class="ai-chat-modal" id="ai-chat-modal">
                <div class="ai-chat-header">
                    <div class="ai-chat-avatar claude" id="ai-chat-avatar">A</div>
                    <div class="ai-chat-info">
                        <h3 class="ai-chat-name" id="ai-chat-name">Claude</h3>
                        <div class="ai-chat-model" id="ai-chat-model">claude-3-5-sonnet</div>
                    </div>
                    <span class="ai-chat-status">En línea</span>
                    <button class="ai-chat-close" onclick="AIFab.closeChat()">
                        <i class="ph ph-x"></i>
                    </button>
                </div>
                
                <div class="ai-chat-messages" id="ai-chat-messages">
                    <div class="ai-chat-message bot">
                        ¡Hola! 👋 Soy el asistente del colegio. Puedo ayudarte con:
                        <br><br>
                        • Consultar tu estado de cuenta<br>
                        • Información sobre trámites<br>
                        • Requisitos para certificados<br>
                        • Fechas y eventos importantes
                        <br><br>
                        ¿En qué puedo ayudarte?
                    </div>
                </div>
                
                <div class="ai-chat-typing" id="ai-chat-typing">
                    <span></span><span></span><span></span>
                </div>
                
                <div class="ai-chat-input-area">
                    <input type="text" 
                           class="ai-chat-input" 
                           id="ai-chat-input"
                           placeholder="Escribe tu pregunta..."
                           onkeypress="AIFab.handleInputKeypress(event)">
                    <button class="ai-chat-send" id="ai-chat-send" onclick="AIFab.sendMessage()">
                        <i class="ph ph-paper-plane-tilt"></i>
                    </button>
                </div>
                
                <div class="ai-chat-footer">
                    <span>
                        <i class="ph ph-info"></i>
                        Consumo institucional: <strong id="ai-footer-cost">$0.00</strong> este mes
                    </span>
                    <a href="/mi-cuenta#ia" onclick="AIFab.closeChat()">Ver mi uso</a>
                </div>
            </div>
        `;
    },
    
    /**
     * Bindea eventos globales
     */
    bindEvents() {
        // Cerrar menú al hacer clic fuera
        document.addEventListener('click', (e) => {
            const container = document.querySelector('.ai-fab-container');
            const modal = document.getElementById('ai-chat-modal');
            
            if (this.isOpen && container && !container.contains(e.target)) {
                this.closeMenu();
            }
        });
        
        // Tecla Escape
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                if (this.chatOpen) {
                    this.closeChat();
                } else if (this.isOpen) {
                    this.closeMenu();
                }
            }
        });
    },
    
    /**
     * Carga estadísticas del servidor
     */
    async loadStats() {
        try {
            const response = await fetch('/api/ai/stats');
            if (response.ok) {
                this.stats = await response.json();
                this.updateStatsDisplay();
            }
        } catch (error) {
            console.log('[AI FAB] Usando stats de ejemplo');
            // Stats de ejemplo para demo
            this.stats = {
                consultasMes: 127,
                costoMes: 3.50,
                limiteMes: 10,
                ahorroEstimado: 850
            };
            this.updateStatsDisplay();
        }
    },
    
    /**
     * Actualiza visualización de estadísticas
     */
    updateStatsDisplay() {
        const percent = Math.round((this.stats.costoMes / this.stats.limiteMes) * 100);
        
        const fill = document.getElementById('ai-usage-fill');
        const text = document.getElementById('ai-usage-text');
        const footerCost = document.getElementById('ai-footer-cost');
        
        if (fill) fill.style.width = `${percent}%`;
        if (text) text.textContent = `$${this.stats.costoMes.toFixed(2)}`;
        if (footerCost) footerCost.textContent = `$${this.stats.costoMes.toFixed(2)}`;
    },
    
    /**
     * Muestra tooltip inicial
     */
    showInitialTooltip() {
        if (sessionStorage.getItem('ai-tooltip-seen')) return;
        
        setTimeout(() => {
            if (!this.isOpen && !this.chatOpen) {
                const tooltip = document.getElementById('ai-fab-tooltip');
                if (tooltip) tooltip.classList.add('show');
                
                setTimeout(() => this.hideTooltip(), this.config.hideTooltipDelay);
            }
        }, this.config.showTooltipDelay);
    },
    
    /**
     * Oculta tooltip
     */
    hideTooltip() {
        const tooltip = document.getElementById('ai-fab-tooltip');
        if (tooltip) tooltip.classList.remove('show');
        sessionStorage.setItem('ai-tooltip-seen', 'true');
    },
    
    /**
     * Toggle del menú principal
     */
    toggle() {
        if (this.chatOpen) {
            this.closeChat();
            return;
        }
        
        if (this.isOpen) {
            this.closeMenu();
        } else {
            this.openMenu();
        }
    },
    
    /**
     * Abre menú de selección
     */
    openMenu() {
        this.isOpen = true;
        this.hideTooltip();
        
        const menu = document.getElementById('ai-fab-menu');
        const button = document.getElementById('ai-fab-button');
        const icon = document.getElementById('ai-fab-icon');
        
        if (menu) menu.classList.add('open');
        if (button) button.classList.add('open');
        if (icon) icon.className = 'ph ph-x';
    },
    
    /**
     * Cierra menú
     */
    closeMenu() {
        this.isOpen = false;
        
        const menu = document.getElementById('ai-fab-menu');
        const button = document.getElementById('ai-fab-button');
        const icon = document.getElementById('ai-fab-icon');
        
        if (menu) menu.classList.remove('open');
        if (button) button.classList.remove('open');
        if (icon) icon.className = 'ph ph-brain';
    },
    
    /**
     * Selecciona un modelo y abre el chat
     */
    selectModel(modelId) {
        const model = this.config.models[modelId];
        
        if (!model || !model.disponible) {
            this.showToast('Este modelo estará disponible próximamente', 'info');
            return;
        }
        
        this.currentModel = modelId;
        this.closeMenu();
        this.openChat();
        
        // Actualizar UI del chat con el modelo seleccionado
        const avatar = document.getElementById('ai-chat-avatar');
        const name = document.getElementById('ai-chat-name');
        const modelText = document.getElementById('ai-chat-model');
        
        if (avatar) {
            avatar.className = `ai-chat-avatar ${modelId}`;
            avatar.textContent = model.name[0];
        }
        if (name) name.textContent = model.name;
        if (modelText) modelText.textContent = `${model.provider} · ${model.modelo}`;
    },
    
    /**
     * Abre el modal de chat
     */
    openChat() {
        this.chatOpen = true;
        const modal = document.getElementById('ai-chat-modal');
        const icon = document.getElementById('ai-fab-icon');
        const button = document.getElementById('ai-fab-button');
        
        if (modal) modal.classList.add('open');
        if (icon) icon.className = 'ph ph-chat-teardrop-dots';
        if (button) button.classList.add('open');
        
        // Focus en el input
        setTimeout(() => {
            const input = document.getElementById('ai-chat-input');
            if (input) input.focus();
        }, 300);
    },
    
    /**
     * Cierra el chat
     */
    closeChat() {
        this.chatOpen = false;
        const modal = document.getElementById('ai-chat-modal');
        const icon = document.getElementById('ai-fab-icon');
        const button = document.getElementById('ai-fab-button');
        
        if (modal) modal.classList.remove('open');
        if (icon) icon.className = 'ph ph-brain';
        if (button) button.classList.remove('open');
    },
    
    /**
     * Maneja keypress en el input
     */
    handleInputKeypress(event) {
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            this.sendMessage();
        }
    },
    
    /**
     * Envía mensaje al chat
     */
    async sendMessage() {
        const input = document.getElementById('ai-chat-input');
        const message = input?.value?.trim();
        
        if (!message) return;
        
        // Limpiar input
        input.value = '';
        
        // Agregar mensaje del usuario
        this.addMessage(message, 'user');
        
        // Mostrar typing
        this.showTyping();
        
        try {
            // Enviar al backend
            const response = await fetch(`${this.config.apiEndpoint}/chat`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message,
                    model: this.currentModel,
                    history: this.chatHistory.slice(-10) // Últimos 10 mensajes
                })
            });
            
            if (response.ok) {
                const data = await response.json();
                this.hideTyping();
                this.addMessage(data.response, 'bot');
                
                // Actualizar costo si viene
                if (data.cost) {
                    this.stats.costoMes += data.cost;
                    this.updateStatsDisplay();
                }
            } else {
                throw new Error('Error en la respuesta');
            }
        } catch (error) {
            console.error('[AI FAB] Error:', error);
            this.hideTyping();
            
            // Respuesta de fallback simulada
            setTimeout(() => {
                this.addMessage(this.getFallbackResponse(message), 'bot');
            }, 500);
        }
    },
    
    /**
     * Agrega mensaje al chat
     */
    addMessage(text, type) {
        const container = document.getElementById('ai-chat-messages');
        if (!container) return;
        
        const div = document.createElement('div');
        div.className = `ai-chat-message ${type}`;
        div.innerHTML = text.replace(/\n/g, '<br>');
        
        container.appendChild(div);
        container.scrollTop = container.scrollHeight;
        
        // Guardar en historial
        this.chatHistory.push({ role: type === 'user' ? 'user' : 'assistant', content: text });
    },
    
    /**
     * Muestra indicador de typing
     */
    showTyping() {
        const typing = document.getElementById('ai-chat-typing');
        const container = document.getElementById('ai-chat-messages');
        if (typing) {
            typing.classList.add('show');
            if (container) container.scrollTop = container.scrollHeight;
        }
    },
    
    /**
     * Oculta typing
     */
    hideTyping() {
        const typing = document.getElementById('ai-chat-typing');
        if (typing) typing.classList.remove('show');
    },
    
    /**
     * Respuesta de fallback cuando no hay API
     */
    getFallbackResponse(message) {
        const msg = message.toLowerCase();
        
        if (msg.includes('cuota') || msg.includes('pago') || msg.includes('deuda')) {
            return 'Para consultar tu estado de cuenta y cuotas pendientes, ve a la sección "Mis Pagos" en tu dashboard. Allí podrás ver el detalle de tus aportes y realizar pagos.';
        }
        
        if (msg.includes('certificado') || msg.includes('constancia') || msg.includes('habilidad')) {
            return 'Los certificados de habilidad se generan automáticamente cuando estás al día en tus cuotas. Puedes descargarlos desde la sección "Certificados" en tu dashboard.';
        }
        
        if (msg.includes('horario') || msg.includes('atencion') || msg.includes('oficina')) {
            return 'La atención en oficina es de Lunes a Viernes de 8:00am a 1:00pm y de 3:00pm a 6:00pm. También puedes realizar la mayoría de trámites desde esta plataforma.';
        }
        
        if (msg.includes('dato') || msg.includes('actualizar') || msg.includes('perfil')) {
            return 'Puedes actualizar tus datos personales desde la sección "Mi Perfil" en el dashboard. Para cambios en tu información profesional (especialidad, centro laboral), contacta a secretaría.';
        }
        
        return 'Entiendo tu consulta. Para darte información más precisa, te sugiero:\n\n1. Revisar las secciones de tu dashboard\n2. Consultar la sección de preguntas frecuentes\n3. Contactar a secretaría al teléfono que aparece en el pie de página\n\n¿Hay algo más específico en lo que pueda ayudarte?';
    },
    
    /**
     * Muestra toast notification
     */
    showToast(message, type = 'info') {
        if (typeof Toast !== 'undefined') {
            Toast.show(message, type);
        } else {
            console.log(`[Toast ${type}]:`, message);
        }
    }
};

// Auto-inicializar
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => AIFab.init());
} else {
    AIFab.init();
}

// Exponer globalmente
window.AIFab = AIFab;
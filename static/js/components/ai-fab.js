/**
 * AI FAB - Asistente de Inteligencia Artificial
 * static/js/components/ai-fab.js
 * 
 * Componente autónomo que:
 * - Inyecta su propio HTML
 * - Muestra presencia constante de IA
 * - Muestra consumo institucional (propaganda)
 * - Permite seleccionar modelo (Claude, GPT, Gemini)
 * - Chat integrado con Knowledge Cards
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
                
                // Ejecutar acción si viene (con datos del colegiado si existen)
                if (data.action) {
                    console.log('[DEBUG] action:', data.action);
                    console.log('[DEBUG] colegiado del backend:', JSON.stringify(data.colegiado));

                    setTimeout(() => {
                        this.executeAction(data.action, data.colegiado);
                    }, 1500);
                }
                
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
     * Ejecuta una acción del chatbot
     * @param {string} action - Nombre de la acción
     * @param {object|null} colegiado - Datos del colegiado (si hay sesión válida)
     */
    executeAction(action, colegiado = null) {
        console.log('[AI FAB] Ejecutando acción:', action, 'Colegiado:', colegiado ? colegiado.nombre : 'Sin sesión');
        this.closeChat();
        
        switch(action) {
            case 'open_pago_form':
                if (colegiado && colegiado.deuda && (colegiado.deuda.total > 0 || colegiado.deuda.deuda_total > 0)) {
                    // Con sesión válida y tiene deuda → Modal pre-llenado
                    this.openPagoFormPrellenado(colegiado);
                } else {
                    // Sin sesión o sin deuda → Modal público
                    this.openModalPublico('reactivacionModal', 2); // Tab índice 2 = Pagar
                }
                break;
                
            case 'open_estado_cuenta':
                if (colegiado) {
                    // Con sesión → Modal Mis Pagos
                    if (typeof ModalPagos !== 'undefined') {
                        ModalPagos.open();
                    }
                } else {
                    // Sin sesión → Modal público consulta
                    this.openModalPublico('reactivacionModal', 2);
                }
                break;
                
            case 'open_certificados':
                if (typeof ModalCertificados !== 'undefined') {
                    ModalCertificados.open();
                } else if (typeof abrirModalLazy === 'function') {
                    abrirModalLazy('modal-certificados');
                } else {
                    // Fallback: modal constancia
                    this.openModalPublico('modal-constancia');
                }
                break;
                
            case 'open_consulta_habilidad':
                // Abrir modal de consultas
                this.openModalPublico('consultasModal');
                break;
                
            // Acciones legacy (compatibilidad)
            case 'open_modal_pagos':
                if (typeof ModalPagos !== 'undefined') {
                    ModalPagos.open();
                }
                break;
                
            default:
                console.log('[AI FAB] Acción no reconocida:', action);
        }
    },
    
    /**
     * Abre un modal público (para usuarios sin sesión)
     * @param {string} modalId - ID del modal
     * @param {number} tabIndex - Índice del tab a activar (opcional)
     */
    openModalPublico(modalId, tabIndex = null) {
        // Intentar diferentes métodos de apertura
        if (typeof openModal === 'function') {
            openModal(modalId);
        } else {
            const modal = document.getElementById(modalId);
            if (modal) {
                modal.classList.add('active');
                document.body.style.overflow = 'hidden';
            }
        }
        
        // Activar tab específico si se indica
        if (tabIndex !== null) {
            setTimeout(() => {
                const tabs = document.querySelectorAll(`#${modalId} .tab-btn, #${modalId} .modal-tab`);
                if (tabs[tabIndex]) {
                    tabs[tabIndex].click();
                }
            }, 100);
        }
    },
    
    /**
     * Abre formulario de pago pre-llenado para usuario logueado
     * @param {object} colegiado - Datos del colegiado con deuda
     */
    openPagoFormPrellenado(colegiado) {
        console.log('[AI FAB] Abriendo formulario pre-llenado para:', colegiado.nombre);
        
        // Verificar si existe el modal de pago rápido, si no, crearlo
        let modal = document.getElementById('modal-pago-rapido');
        if (!modal) {
            modal = this.crearModalPagoRapido();
            document.body.appendChild(modal);
        }
        
        // Llenar datos
        this.llenarFormularioPago(colegiado);
        
        // Abrir modal
        modal.style.display = 'flex';
        modal.classList.add('active');
        document.body.style.overflow = 'hidden';
    },
    
    /**
     * Crea el modal de pago rápido para usuarios logueados
     */
    crearModalPagoRapido() {
        const modal = document.createElement('div');
        modal.id = 'modal-pago-rapido';
        modal.className = 'modal-overlay';
        modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.8);display:flex;align-items:center;justify-content:center;z-index:9999;';
        modal.innerHTML = `
            <div class="modal-container" style="background:var(--surface,#1a1a2e);border-radius:16px;max-width:420px;width:90%;max-height:90vh;overflow-y:auto;position:relative;">
                <div style="display:flex;justify-content:space-between;align-items:center;padding:20px;border-bottom:1px solid rgba(255,255,255,0.1);">
                    <h2 style="color:var(--texto-claro,#fff);margin:0;font-size:18px;">💳 Registrar Pago</h2>
                    <button id="btn-cerrar-pago-rapido" style="background:none;border:none;color:var(--texto-gris,#888);font-size:24px;cursor:pointer;padding:0;line-height:1;">×</button>
                </div>
                <div class="modal-body" id="pago-rapido-content" style="padding:20px;"></div>
            </div>
        `;
        
        // Cerrar con X
        modal.querySelector('#btn-cerrar-pago-rapido').onclick = () => this.cerrarModalPagoRapido();
        
        // Cerrar al hacer clic fuera
        modal.onclick = (e) => {
            if (e.target === modal) this.cerrarModalPagoRapido();
        };
        
        // Cerrar con ESC
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && modal.classList.contains('active')) {
                this.cerrarModalPagoRapido();
            }
        });
        
        return modal;
    },

    cerrarModalPagoRapido() {
        const modal = document.getElementById('modal-pago-rapido');
        if (modal) {
            modal.classList.remove('active');
            modal.style.display = 'none';
            document.body.style.overflow = '';
        }
    },
    
    /**
     * Llena el formulario de pago con datos del colegiado
     */
    llenarFormularioPago(colegiado) {
        const container = document.getElementById('pago-rapido-content');
        if (!container) return;
        
        const deuda = colegiado.deuda || {};
        const cantCuotas = deuda.cantidad_cuotas || 0;
        const montoDeuda = (deuda.deuda_total || deuda.total || 0);
        const enRevision = deuda.en_revision || 0;
        const inicial = colegiado.nombre?.charAt(0) || '?';
        
        container.innerHTML = `
            <form id="form-pago-rapido" onsubmit="window.AIFab.enviarPagoRapido(event)">
                <input type="hidden" name="colegiado_id" value="${colegiado.id || ''}">
                ${colegiado.deuda?.mes_hasta ? `<input type="hidden" name="meta_cuotas" value='${JSON.stringify({
                    mes_desde:     colegiado.deuda.mes_desde     || 1,
                    mes_hasta:     colegiado.deuda.mes_hasta,
                    anio:          colegiado.deuda.anio          || new Date().getFullYear(),
                    descuento_pct: colegiado.deuda.descuento_pct || 0,
                    n_cuotas:      colegiado.deuda.cantidad_cuotas || 1,
                })}'>` : ''}

                ${colegiado.deuda?.fraccionamiento_id != null ? `<input type="hidden" name="meta_fracc" value='${JSON.stringify({
                    fraccionamiento_id: colegiado.deuda.fraccionamiento_id,
                    numero_cuota:       colegiado.deuda.numero_cuota ?? 0,
                })}'>` : ''}
                
                <!-- Header con avatar -->
                <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 15px; padding-bottom: 15px; border-bottom: 1px solid rgba(255,255,255,0.08);">
                    <div style="width: 48px; height: 48px; background: linear-gradient(135deg, #8b5cf6, #6366f1); border-radius: 50%; display: flex; align-items: center; justify-content: center; color: #fff; font-weight: 700; font-size: 18px; flex-shrink: 0; box-shadow: 0 4px 15px rgba(139, 92, 246, 0.3);">
                        ${inicial}
                    </div>
                    <div style="flex: 1; min-width: 0;">
                        <p style="color: #fff; font-weight: 600; margin: 0; font-size: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${colegiado.nombre || 'Colegiado'}</p>
                        <p style="color: #64748b; font-size: 11px; margin: 3px 0 0 0;">Mat: ${colegiado.matricula || '-'} • DNI: ${colegiado.dni || '-'}</p>
                    </div>
                    <div style="text-align: right; flex-shrink: 0;">
                        <p style="color: #22c55e; font-size: 22px; font-weight: 800; margin: 0;">S/ ${montoDeuda.toFixed(2)}</p>
                        <p style="color: #64748b; font-size: 10px; margin: 2px 0 0 0;">${cantCuotas} cuota${cantCuotas !== 1 ? 's' : ''} pend.</p>
                    </div>
                </div>
                
                ${enRevision > 0 ? `<div style="background: rgba(245,158,11,0.1); border: 1px solid rgba(245,158,11,0.2); border-radius: 8px; padding: 8px 12px; margin-bottom: 12px; text-align: center;"><span style="color: #f59e0b; font-size: 12px;">⏳ S/ ${enRevision.toFixed(2)} en revisión</span></div>` : ''}
                
                <!-- Monto y Operación -->
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 14px;">
                    <div>
                        <label style="display: block; color: #94a3b8; font-size: 10px; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px; font-weight: 600;">Monto (S/)</label>
                        <input type="number" name="monto" step="0.01" min="1" required value="${montoDeuda.toFixed(2)}"
                            style="width: 100%; background: rgba(15,23,42,0.6); border: 1px solid rgba(148,163,184,0.2); border-radius: 10px; padding: 12px 14px; color: #fff; font-size: 18px; font-weight: 700; outline: none; transition: border-color 0.2s;"
                            onfocus="this.style.borderColor='#8b5cf6'" onblur="this.style.borderColor='rgba(148,163,184,0.2)'">
                    </div>
                    <div>
                        <label style="display: block; color: #94a3b8; font-size: 10px; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px; font-weight: 600;">Nº Operación</label>
                        <input type="text" name="numero_operacion" placeholder="123456789"
                            style="width: 100%; background: rgba(15,23,42,0.6); border: 1px solid rgba(148,163,184,0.2); border-radius: 10px; padding: 12px 14px; color: #fff; font-family: monospace; font-size: 14px; outline: none; transition: border-color 0.2s;"
                            onfocus="this.style.borderColor='#8b5cf6'" onblur="this.style.borderColor='rgba(148,163,184,0.2)'">
                    </div>
                </div>
                
                <!-- Método de pago -->
                <div style="margin-bottom: 14px;">
                    <label style="display: block; color: #94a3b8; font-size: 10px; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px; font-weight: 600;">Método de pago</label>
                    <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px;" id="metodos-pago">
                        <label class="metodo-btn active" data-metodo="Yape" style="display: flex; align-items: center; justify-content: center; gap: 6px; background: #7c3aed; padding: 10px 8px; border-radius: 10px; cursor: pointer; transition: all 0.2s; border: 2px solid #7c3aed;">
                            <input type="radio" name="metodo_pago" value="Yape" checked style="display: none;">
                            <span style="color: #fff; font-size: 12px; font-weight: 600;">💜 Yape</span>
                        </label>
                        <label class="metodo-btn" data-metodo="Plin" style="display: flex; align-items: center; justify-content: center; gap: 6px; background: rgba(15,23,42,0.6); padding: 10px 8px; border-radius: 10px; cursor: pointer; transition: all 0.2s; border: 2px solid transparent;">
                            <input type="radio" name="metodo_pago" value="Plin" style="display: none;">
                            <span style="color: #94a3b8; font-size: 12px; font-weight: 600;">💚 Plin</span>
                        </label>
                        <label class="metodo-btn" data-metodo="Transferencia" style="display: flex; align-items: center; justify-content: center; gap: 6px; background: rgba(15,23,42,0.6); padding: 10px 8px; border-radius: 10px; cursor: pointer; transition: all 0.2s; border: 2px solid transparent;">
                            <input type="radio" name="metodo_pago" value="Transferencia" style="display: none;">
                            <span style="color: #94a3b8; font-size: 12px; font-weight: 600;">🏦 Transf.</span>
                        </label>
                    </div>
                </div>
                
                <!-- Voucher -->
                <div style="margin-bottom: 14px;">
                    <label id="voucher-label" style="display: flex; align-items: center; gap: 10px; padding: 12px 15px; background: rgba(15,23,42,0.6); border: 1px dashed rgba(148,163,184,0.3); border-radius: 10px; cursor: pointer; transition: all 0.2s;"
                        onmouseover="this.style.borderColor='#8b5cf6'" onmouseout="this.style.borderColor='rgba(148,163,184,0.3)'">
                        <input type="file" name="voucher" accept="image/*" style="display: none;" onchange="document.getElementById('voucher-text').textContent = this.files[0]?.name || 'Adjuntar voucher (opcional)'">
                        <span style="font-size: 18px;">📷</span>
                        <span id="voucher-text" style="color: #94a3b8; font-size: 12px;">Adjuntar voucher (opcional)</span>
                    </label>
                </div>
                
                <!-- Comprobante y Certificado -->
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 16px;">
                    <!-- Comprobante -->
                    <div style="background: rgba(15,23,42,0.4); border-radius: 12px; padding: 14px;">
                        <p style="color: #94a3b8; font-size: 10px; text-transform: uppercase; letter-spacing: 0.5px; margin: 0 0 10px 0; font-weight: 600;">📄 Comprobante</p>
                        <div style="display: flex; flex-direction: column; gap: 8px;">
                            <label style="display: flex; align-items: center; gap: 8px; cursor: pointer;">
                                <input type="radio" name="tipo_comprobante" value="recibo" checked style="width: 16px; height: 16px; accent-color: #8b5cf6;">
                                <span style="color: #e2e8f0; font-size: 12px;">Recibo</span>
                            </label>
                            <label style="display: flex; align-items: center; gap: 8px; cursor: pointer;">
                                <input type="radio" name="tipo_comprobante" value="boleta" style="width: 16px; height: 16px; accent-color: #8b5cf6;">
                                <span style="color: #e2e8f0; font-size: 12px;">Boleta</span>
                            </label>
                            <label style="display: flex; align-items: center; gap: 8px; cursor: pointer;">
                                <input type="radio" name="tipo_comprobante" value="factura" style="width: 16px; height: 16px; accent-color: #8b5cf6;">
                                <span style="color: #e2e8f0; font-size: 12px;">Factura</span>
                            </label>
                        </div>
                    </div>
                    
                    <!-- Certificado -->
                    <div style="background: rgba(15,23,42,0.4); border-radius: 12px; padding: 14px; display: flex; flex-direction: column; justify-content: center;">
                        <label style="display: flex; align-items: flex-start; gap: 10px; cursor: pointer;">
                            <input type="checkbox" name="requiere_certificado" value="1" style="width: 18px; height: 18px; accent-color: #8b5cf6; margin-top: 2px;">
                            <div>
                                <span style="color: #e2e8f0; font-size: 12px; font-weight: 600; display: block;">📜 Certificado</span>
                                <span style="color: #64748b; font-size: 10px;">Habilidad profesional</span>
                            </div>
                        </label>
                    </div>
                </div>
                
                <!-- Campo RUC (oculto) -->
                <div id="campo-ruc" style="display: none; margin-bottom: 14px;">
                    <div style="display: grid; grid-template-columns: 130px 1fr; gap: 10px;">
                        <input type="text" name="ruc_factura" placeholder="RUC" maxlength="11" pattern="[0-9]{11}"
                            style="background: rgba(15,23,42,0.6); border: 1px solid rgba(148,163,184,0.2); border-radius: 8px; padding: 10px 12px; color: #fff; font-family: monospace; font-size: 13px;">
                        <input type="text" name="razon_social" placeholder="Razón Social"
                            style="background: rgba(15,23,42,0.6); border: 1px solid rgba(148,163,184,0.2); border-radius: 8px; padding: 10px 12px; color: #fff; font-size: 13px;">
                    </div>
                </div>
                
                <!-- Resultado -->
                <div id="pago-rapido-resultado"></div>

                <!-- Botón Submit -->
                <button type="submit" id="btn-pago-rapido" 
                        style="width: 100%; background: linear-gradient(135deg, #8b5cf6, #6366f1); color: #fff; border: none; padding: 14px; border-radius: 12px; font-weight: 700; font-size: 14px; cursor: pointer; transition: all 0.2s; box-shadow: 0 4px 15px rgba(139, 92, 246, 0.3);"
                        onmouseover="this.style.transform='translateY(-1px)'; this.style.boxShadow='0 6px 20px rgba(139, 92, 246, 0.4)'"
                        onmouseout="this.style.transform='translateY(0)'; this.style.boxShadow='0 4px 15px rgba(139, 92, 246, 0.3)'">
                    ✓ REGISTRAR PAGO
                </button>
            </form>
        `;
        
        // Colores de métodos de pago
        const colores = {
            Yape: { bg: '#7c3aed', border: '#7c3aed' },
            Plin: { bg: '#06b6d4', border: '#06b6d4' },
            Transferencia: { bg: '#f59e0b', border: '#f59e0b' }
        };
        
        // Event: Método de pago
        container.querySelectorAll('.metodo-btn').forEach(label => {
            label.addEventListener('click', function() {
                // Reset todos
                container.querySelectorAll('.metodo-btn').forEach(l => {
                    l.style.background = 'rgba(15,23,42,0.6)';
                    l.style.borderColor = 'transparent';
                    l.querySelector('span').style.color = '#94a3b8';
                });
                // Activar seleccionado
                const metodo = this.dataset.metodo;
                const color = colores[metodo];
                this.style.background = color.bg;
                this.style.borderColor = color.border;
                this.querySelector('span').style.color = '#fff';
            });
        });
        
        // Event: Toggle RUC
        container.querySelectorAll('input[name="tipo_comprobante"]').forEach(radio => {
            radio.addEventListener('change', (e) => {
                document.getElementById('campo-ruc').style.display = e.target.value === 'factura' ? 'block' : 'none';
            });
        });
    },

    cerrarModal() {
        const modal = document.getElementById('modal-pago-rapido');
        if (modal) {
            modal.classList.remove('active');
            document.body.style.overflow = '';
        }
    },
    
    /**
     * Envía el pago desde el formulario rápido
     */
    async enviarPagoRapido(event) {
        event.preventDefault();
        
        const form = document.getElementById('form-pago-rapido');
        const formData = new FormData(form);
        const resultadoDiv = document.getElementById('pago-rapido-resultado');
        const btnSubmit = document.getElementById('btn-pago-rapido');
        
        btnSubmit.disabled = true;
        btnSubmit.innerHTML = '⏳ Procesando...';
        
        try {
            const response = await fetch('/pagos/registrar', {
                method: 'POST',
                body: formData
            });
            
            const html = await response.text();
            
            if (response.ok && !html.includes('❌')) {
                const container = document.getElementById('pago-rapido-content');
                container.innerHTML = html;
                
                // Refrescar datos de MIS PAGOS si está abierto
                if (typeof ModalPagos !== 'undefined' && ModalPagos.cargarDatos) {
                    setTimeout(() => ModalPagos.cargarDatos(), 500);
                }
            } else {
                resultadoDiv.innerHTML = html;
                btnSubmit.disabled = false;
                btnSubmit.innerHTML = '✓ REGISTRAR PAGO';
            }
        } catch (error) {
            console.error('[AI FAB] Error:', error);
            resultadoDiv.innerHTML = `
                <div style="background: rgba(239,68,68,0.1); border: 1px solid rgba(239,68,68,0.3); color: #ef4444; padding: 10px; border-radius: 8px; font-size: 12px;">
                    ❌ Error de conexión. Intenta de nuevo.
                </div>
            `;
            btnSubmit.disabled = false;
            btnSubmit.innerHTML = '✓ REGISTRAR PAGO';
        }
    },
    
    /**
     * Agrega mensaje al chat
     */
    addMessage(content, type) {
        const container = document.getElementById('ai-chat-messages');
        if (!container) return;
        
        // Si es respuesta del bot y viene como card/objeto
        if (type === 'bot' && typeof content === 'object') {
            const cardHTML = this.renderCard(content);
            const wrapper = document.createElement('div');
            wrapper.className = 'ai-chat-response';
            wrapper.innerHTML = cardHTML;
            container.appendChild(wrapper);
        } else {
            // Mensaje de texto normal
            this.addTextMessage(content, type);
        }
        
        container.scrollTop = container.scrollHeight;
        
        // Guardar en historial
        const historyContent = typeof content === 'object' 
            ? (content.description || content.text || '')
            : content;
        this.chatHistory.push({ 
            role: type === 'user' ? 'user' : 'assistant', 
            content: historyContent 
        });
    },
    
    /**
     * Renderiza una card según su tipo
     */
    renderCard(card) {
        if (!card) return '';
        
        // Si tiene múltiples cards
        if (card.cards) {
            return card.cards.map(c => this.renderCard(c)).join('');
        }
        
        switch(card.type) {
            case 'steps':
                return this.renderStepsCard(card);
            case 'article':
                return this.renderArticleCard(card);
            case 'featured':
                return this.renderFeaturedCard(card);
            case 'metric':
                return this.renderMetricCard(card);
            default:
                return this.renderArticleCard(card);
        }
    },
    
    /**
     * Card tipo pasos
     */
    renderStepsCard(card) {
        const stepsHTML = (card.steps || []).map((step, i) => `
            <div class="kc-step">
                <div class="kc-step-num">${i + 1}</div>
                <div class="kc-step-content">
                    <strong>${step.title}</strong>
                    ${step.description ? `<p>${step.description}</p>` : ''}
                </div>
            </div>
        `).join('');
        
        return `
            <div class="kc-card kc-steps">
                ${card.category ? `<div class="kc-category"><i class="ph ph-tag"></i> ${card.category}</div>` : ''}
                <h3 class="kc-title">${card.title}</h3>
                ${card.description ? `<p class="kc-desc">${card.description}</p>` : ''}
                <div class="kc-steps-list">${stepsHTML}</div>
                ${card.tip ? this.renderTip(card.tip) : ''}
                ${card.source ? this.renderSource(card.source) : ''}
            </div>
        `;
    },
    
    /**
     * Card tipo artículo
     */
    renderArticleCard(card) {
        return `
            <div class="kc-card kc-article">
                <div class="kc-content">
                    ${card.category ? `<div class="kc-category"><i class="ph ph-tag"></i> ${card.category}</div>` : ''}
                    <h3 class="kc-title">${card.title}</h3>
                    ${card.description ? `<p class="kc-desc">${card.description}</p>` : ''}
                    ${card.citation ? this.renderCitation(card.citation) : ''}
                    ${card.tip ? this.renderTip(card.tip) : ''}
                    ${card.source ? this.renderSource(card.source) : ''}
                    ${card.related ? this.renderRelated(card.related) : ''}
                </div>
                <div class="kc-icon-box">
                    <i class="ph ph-${card.icon || 'article'}"></i>
                </div>
            </div>
        `;
    },
    
    /**
     * Card tipo destacado
     */
    renderFeaturedCard(card) {
        const stepsHTML = card.steps ? (card.steps || []).map((step, i) => `
            <div class="kc-step">
                <div class="kc-step-num">${i + 1}</div>
                <div class="kc-step-content">
                    <strong>${step.title}</strong>
                    ${step.description ? `<p>${step.description}</p>` : ''}
                </div>
            </div>
        `).join('') : '';
        
        return `
            <div class="kc-card kc-featured">
                <div class="kc-banner">
                    <i class="ph ph-${card.icon || 'sparkle'}"></i>
                </div>
                <div class="kc-content">
                    ${card.category ? `<div class="kc-category"><i class="ph ph-star"></i> ${card.category}</div>` : ''}
                    <h3 class="kc-title">${card.title}</h3>
                    ${card.description ? `<p class="kc-desc">${card.description}</p>` : ''}
                    ${stepsHTML ? `<div class="kc-steps-list">${stepsHTML}</div>` : ''}
                    ${card.warning ? `<div class="kc-warning"><i class="ph ph-warning"></i> ${card.warning}</div>` : ''}
                    ${card.tip ? this.renderTip(card.tip) : ''}
                    ${card.source ? this.renderSource(card.source) : ''}
                </div>
            </div>
        `;
    },
    
    /**
     * Card tipo métrica
     */
    renderMetricCard(card) {
        return `
            <div class="kc-card kc-metric">
                <div class="kc-metric-icon ${card.color || 'purple'}">
                    <i class="ph ph-${card.icon || 'chart-line-up'}"></i>
                </div>
                <div class="kc-metric-data">
                    <div class="kc-metric-value">${card.value}</div>
                    <div class="kc-metric-label">${card.label}</div>
                </div>
            </div>
        `;
    },
    
    /**
     * Renderiza tip
     */
    renderTip(tip) {
        const text = typeof tip === 'string' ? tip : tip.text;
        const label = typeof tip === 'object' && tip.label ? tip.label : 'Tip';
        return `
            <div class="kc-tip">
                <i class="ph ph-lightbulb"></i>
                <div>
                    <span class="kc-tip-label">${label}</span>
                    <span class="kc-tip-text">${text}</span>
                </div>
            </div>
        `;
    },
    
    /**
     * Renderiza cita/base legal
     */
    renderCitation(citation) {
        const text = typeof citation === 'string' ? citation : citation.text;
        const source = typeof citation === 'object' ? citation.source : null;
        return `
            <div class="kc-citation">
                <i class="ph ph-quotes"></i>
                <div>
                    <span class="kc-citation-text">${text}</span>
                    ${source ? `<span class="kc-citation-source">— ${source}</span>` : ''}
                </div>
            </div>
        `;
    },
    
    /**
     * Renderiza fuente
     */
    renderSource(source) {
        const name = typeof source === 'string' ? source : source.name;
        const verified = typeof source === 'object' && source.verified;
        return `
            <div class="kc-source">
                <i class="ph ph-book-open"></i>
                <span>${name}</span>
                ${verified ? '<span class="kc-verified">✓ Verificado</span>' : ''}
            </div>
        `;
    },
    
    /**
     * Renderiza relacionados
     */
    renderRelated(related) {
        if (!related || !related.length) return '';
        const items = related.slice(0, 4).map(r => `
            <div class="kc-related-item">
                <i class="ph ph-${r.icon || 'link'}"></i>
                <span>${r.title}</span>
            </div>
        `).join('');
        return `<div class="kc-related">${items}</div>`;
    },
    
    /**
     * Agrega mensaje de texto simple
     */
    addTextMessage(text, type) {
        const container = document.getElementById('ai-chat-messages');
        if (!container) return;
        
        const div = document.createElement('div');
        div.className = `ai-chat-message ${type}`;
        div.innerHTML = text.replace(/\n/g, '<br>');
        container.appendChild(div);
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
     * Retorna objetos card para demo visual
     */
    getFallbackResponse(message) {
        const msg = message.toLowerCase();
        
        // ACCIÓN: QUIERO PAGAR → Abrir modal de pagos
        if (msg.includes('quiero pagar') || msg.includes('deseo pagar') || msg.includes('voy a pagar') || msg.includes('realizar pago') || msg.includes('hacer un pago')) {
            // Cerrar chat y abrir modal de pagos
            setTimeout(() => {
                this.closeChat();
                if (typeof ModalPagos !== 'undefined') {
                    ModalPagos.open();
                }
            }, 1500);
            
            return {
                "type": "article",
                "category": "Acción",
                "title": "¡Perfecto! Abriendo el módulo de pagos...",
                "description": "Te llevo al formulario de pago donde podrás registrar tu pago con Yape, Plin o transferencia.",
                "icon": "credit-card",
                "tip": {
                    "label": "Recuerda",
                    "text": "Ten a la mano tu voucher o captura del pago para subirlo."
                }
            };
        }
        
        // CONSULTA SOBRE PAGOS / CUOTAS (informativo)
        if (msg.includes('cuota') || msg.includes('pago') || msg.includes('pagar') || msg.includes('deuda')) {
            return {
                "type": "steps",
                "category": "Pagos",
                "title": "¿Cómo pagar mis cuotas?",
                "description": "Tienes varias opciones para ponerte al día:",
                "steps": [
                    {
                        "title": "Yape o Plin",
                        "description": "Escanea el QR o transfiere al 987-654-321. Sube tu voucher en el sistema."
                    },
                    {
                        "title": "Transferencia Bancaria",
                        "description": "BCP Cta. Cte. 123-456789-0-12. Envía el comprobante por el sistema."
                    },
                    {
                        "title": "Presencial",
                        "description": "En oficinas de Lunes a Viernes, 8am-1pm y 3pm-6pm."
                    }
                ],
                "tip": {
                    "label": "Tip rápido",
                    "text": "Los pagos por Yape/Plin se validan en menos de 24 horas. ¡Es la forma más rápida!"
                },
                "source": {
                    "name": "Tesorería CCPL",
                    "icon": "wallet",
                    "verified": true
                }
            };
        }
        
        // CONSULTA SOBRE CERTIFICADOS / CONSTANCIAS
        if (msg.includes('certificado') || msg.includes('constancia') || msg.includes('habilidad') || msg.includes('habil')) {
            return {
                "type": "article",
                "category": "Trámites",
                "title": "Constancia de Habilidad Profesional",
                "description": "La constancia certifica que estás habilitado para ejercer. Se genera automáticamente cuando estás al día en tus cuotas.",
                "icon": "certificate",
                "source": {
                    "name": "Reglamento CCPL",
                    "icon": "book-open",
                    "verified": true
                },
                "citation": {
                    "text": "Todo colegiado en ejercicio deberá mantener su condición de hábil, acreditada mediante la constancia correspondiente.",
                    "source": "Estatuto CCPL, Art. 45"
                },
                "tip": {
                    "label": "Acceso rápido",
                    "text": "Descarga tu constancia desde Dashboard → Certificados. Incluye código QR de verificación."
                }
            };
        }
        
        // CONSULTA SOBRE HORARIOS / ATENCIÓN
        if (msg.includes('horario') || msg.includes('atencion') || msg.includes('oficina') || msg.includes('donde')) {
            return {
                "type": "featured",
                "category": "Información",
                "title": "Horarios y Ubicación",
                "description": "Nuestras oficinas están ubicadas en Jr. Putumayo 123, Iquitos.",
                "icon": "map-pin",
                "steps": [
                    {
                        "title": "Lunes a Viernes",
                        "description": "8:00 AM - 1:00 PM / 3:00 PM - 6:00 PM"
                    },
                    {
                        "title": "Sábados",
                        "description": "9:00 AM - 12:00 PM (solo trámites urgentes)"
                    }
                ],
                "tip": "La mayoría de trámites puedes realizarlos desde esta plataforma, sin necesidad de ir presencialmente."
            };
        }
        
        // CONSULTA SOBRE ACTUALIZAR DATOS
        if (msg.includes('dato') || msg.includes('actualizar') || msg.includes('perfil') || msg.includes('cambiar')) {
            return {
                "type": "article",
                "category": "Mi Cuenta",
                "title": "Actualización de Datos",
                "description": "Puedes actualizar tu información personal directamente desde el Dashboard.",
                "icon": "user-gear",
                "steps": [
                    {
                        "title": "Datos de contacto",
                        "description": "Email, teléfono, dirección → Mi Perfil → Editar"
                    },
                    {
                        "title": "Información profesional",
                        "description": "Especialidad, centro laboral → Contactar a Secretaría"
                    }
                ],
                "tip": "Mantén tu email actualizado para recibir notificaciones importantes y alertas de vencimiento."
            };
        }
        
        // CONSULTA SOBRE DESCUENTOS / BENEFICIOS
        if (msg.includes('descuento') || msg.includes('beneficio') || msg.includes('promocion') || msg.includes('aniversario')) {
            return {
                "type": "featured",
                "category": "🎉 Beneficio Activo",
                "title": "60 Aniversario CCPL - 50% de Descuento",
                "description": "Por nuestro aniversario, todos los colegiados con deuda pueden regularizarse con 50% de descuento en cuotas atrasadas.",
                "icon": "confetti",
                "source": {
                    "name": "Junta Directiva",
                    "verified": true
                },
                "tip": {
                    "label": "¿Cómo aprovecharlo?",
                    "text": "El descuento se aplica automáticamente. Solo paga el monto con descuento y sube tu voucher."
                },
                "warning": "Válido hasta el 28 de febrero. Solo para cuotas generadas antes del 2024."
            };
        }
        
        // CONSULTA SOBRE CURSOS
        if (msg.includes('curso') || msg.includes('capacitacion') || msg.includes('seminario') || msg.includes('taller')) {
            return {
                "type": "featured",
                "category": "Capacitación",
                "title": "Próximos Cursos y Seminarios",
                "description": "Mantente actualizado con nuestra oferta de capacitación continua.",
                "icon": "graduation-cap",
                "steps": [
                    {
                        "title": "Actualización NIIF 2025",
                        "description": "20 horas certificadas. Inicio: 15 de febrero"
                    },
                    {
                        "title": "Cierre Contable 2024",
                        "description": "Taller práctico. 10 de febrero, 6pm"
                    },
                    {
                        "title": "Excel Financiero Avanzado",
                        "description": "Curso virtual. Inscripciones abiertas"
                    }
                ],
                "tip": {
                    "label": "Beneficio para colegiados hábiles",
                    "text": "30% de descuento en todos los cursos. ¡Ponte al día y aprovecha!"
                }
            };
        }
        
        // RESPUESTA GENÉRICA
        return {
            "type": "article",
            "category": "Asistente IA",
            "title": "¿En qué más puedo ayudarte?",
            "description": "Puedo asistirte con información sobre trámites, pagos, certificados, cursos y más. Intenta preguntar de forma específica.",
            "icon": "robot",
            "related": [
                {"title": "¿Cómo pago mis cuotas?", "icon": "credit-card"},
                {"title": "Obtener constancia", "icon": "certificate"},
                {"title": "Horarios de atención", "icon": "clock"},
                {"title": "Cursos disponibles", "icon": "graduation-cap"}
            ],
            "tip": "También puedes navegar por las secciones del Dashboard para encontrar lo que necesitas."
        };
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
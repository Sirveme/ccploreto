/**
 * ColegiosPro - Sistema de Sonidos y UX
 * Sonidos sutiles para mejorar la experiencia de usuario
 */

const SoundFX = {
    // Configuración
    enabled: true,
    volume: 0.3,
    
    // Rutas de audio (usamos Web Audio API con tonos generados)
    sounds: {},
    audioContext: null,
    
    // Inicializar
    init() {
        // Verificar si el usuario ha interactuado (requerido para Web Audio)
        document.addEventListener('click', () => {
            if (!this.audioContext) {
                this.audioContext = new (window.AudioContext || window.webkitAudioContext)();
            }
        }, { once: true });
        
        // Cargar preferencia guardada
        const saved = localStorage.getItem('soundfx_enabled');
        if (saved !== null) this.enabled = saved === 'true';
    },
    
    // Toggle sonidos
    toggle() {
        this.enabled = !this.enabled;
        localStorage.setItem('soundfx_enabled', this.enabled);
        if (this.enabled) this.play('click');
        return this.enabled;
    },
    
    // Reproducir sonido generado
    play(type) {
        if (!this.enabled || !this.audioContext) return;
        
        try {
            const ctx = this.audioContext;
            const oscillator = ctx.createOscillator();
            const gainNode = ctx.createGain();
            
            oscillator.connect(gainNode);
            gainNode.connect(ctx.destination);
            
            // Configurar según tipo de sonido
            switch(type) {
                case 'open':
                    // Pop suave ascendente
                    oscillator.frequency.setValueAtTime(400, ctx.currentTime);
                    oscillator.frequency.exponentialRampToValueAtTime(600, ctx.currentTime + 0.1);
                    gainNode.gain.setValueAtTime(this.volume * 0.3, ctx.currentTime);
                    gainNode.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.15);
                    oscillator.type = 'sine';
                    oscillator.start(ctx.currentTime);
                    oscillator.stop(ctx.currentTime + 0.15);
                    break;
                    
                case 'close':
                    // Swoosh descendente
                    oscillator.frequency.setValueAtTime(500, ctx.currentTime);
                    oscillator.frequency.exponentialRampToValueAtTime(200, ctx.currentTime + 0.1);
                    gainNode.gain.setValueAtTime(this.volume * 0.2, ctx.currentTime);
                    gainNode.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.1);
                    oscillator.type = 'sine';
                    oscillator.start(ctx.currentTime);
                    oscillator.stop(ctx.currentTime + 0.1);
                    break;
                    
                case 'success':
                    // Ding doble positivo
                    oscillator.frequency.setValueAtTime(523.25, ctx.currentTime); // C5
                    oscillator.frequency.setValueAtTime(659.25, ctx.currentTime + 0.1); // E5
                    gainNode.gain.setValueAtTime(this.volume * 0.4, ctx.currentTime);
                    gainNode.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.3);
                    oscillator.type = 'sine';
                    oscillator.start(ctx.currentTime);
                    oscillator.stop(ctx.currentTime + 0.3);
                    break;
                    
                case 'error':
                    // Bonk grave
                    oscillator.frequency.setValueAtTime(200, ctx.currentTime);
                    oscillator.frequency.exponentialRampToValueAtTime(100, ctx.currentTime + 0.15);
                    gainNode.gain.setValueAtTime(this.volume * 0.3, ctx.currentTime);
                    gainNode.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.2);
                    oscillator.type = 'triangle';
                    oscillator.start(ctx.currentTime);
                    oscillator.stop(ctx.currentTime + 0.2);
                    break;
                    
                case 'notification':
                    // Bubble
                    oscillator.frequency.setValueAtTime(800, ctx.currentTime);
                    oscillator.frequency.exponentialRampToValueAtTime(1200, ctx.currentTime + 0.05);
                    oscillator.frequency.exponentialRampToValueAtTime(800, ctx.currentTime + 0.1);
                    gainNode.gain.setValueAtTime(this.volume * 0.25, ctx.currentTime);
                    gainNode.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.15);
                    oscillator.type = 'sine';
                    oscillator.start(ctx.currentTime);
                    oscillator.stop(ctx.currentTime + 0.15);
                    break;
                    
                case 'click':
                    // Click sutil
                    oscillator.frequency.setValueAtTime(1000, ctx.currentTime);
                    gainNode.gain.setValueAtTime(this.volume * 0.15, ctx.currentTime);
                    gainNode.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.05);
                    oscillator.type = 'square';
                    oscillator.start(ctx.currentTime);
                    oscillator.stop(ctx.currentTime + 0.05);
                    break;
                    
                case 'typing':
                    // Tecleo suave
                    oscillator.frequency.setValueAtTime(800 + Math.random() * 400, ctx.currentTime);
                    gainNode.gain.setValueAtTime(this.volume * 0.08, ctx.currentTime);
                    gainNode.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.03);
                    oscillator.type = 'square';
                    oscillator.start(ctx.currentTime);
                    oscillator.stop(ctx.currentTime + 0.03);
                    break;
            }
        } catch (e) {
            console.warn('SoundFX error:', e);
        }
    }
};

// Inicializar al cargar
document.addEventListener('DOMContentLoaded', () => SoundFX.init());

/**
 * Sistema de Modales Mejorado
 */
const Modal = {
    // Abrir modal con efectos
    open(id, options = {}) {
        const modal = document.getElementById(id);
        if (!modal) return;
        
        SoundFX.play('open');
        modal.showModal();
        
        // Callback después de abrir
        if (options.onOpen) setTimeout(options.onOpen, 250);
    },
    
    // Cerrar modal con efectos
    close(id) {
        const modal = document.getElementById(id);
        if (!modal) return;
        
        SoundFX.play('close');
        modal.classList.add('closing');
        
        setTimeout(() => {
            modal.close();
            modal.classList.remove('closing');
        }, 150);
    },
    
    // Cerrar al hacer click en backdrop
    initBackdropClose() {
        document.querySelectorAll('dialog').forEach(dialog => {
            dialog.addEventListener('click', (e) => {
                if (e.target === dialog) {
                    Modal.close(dialog.id);
                }
            });
        });
    }
};

/**
 * Toast Notifications
 */
const Toast = {
    container: null,
    
    init() {
        if (this.container) return;
        this.container = document.createElement('div');
        this.container.id = 'toast-container';
        this.container.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            z-index: 9999;
            display: flex;
            flex-direction: column;
            gap: 10px;
            pointer-events: none;
        `;
        document.body.appendChild(this.container);
    },
    
    show(message, type = 'info', duration = 3000) {
        this.init();
        
        const toast = document.createElement('div');
        toast.style.cssText = `
            padding: 14px 20px;
            border-radius: 12px;
            font-size: 14px;
            font-weight: 500;
            color: white;
            backdrop-filter: blur(10px);
            box-shadow: 0 4px 20px rgba(0,0,0,0.3);
            animation: toastIn 0.3s ease-out;
            pointer-events: auto;
            display: flex;
            align-items: center;
            gap: 10px;
            max-width: 320px;
        `;
        
        // Color según tipo
        const colors = {
            success: 'rgba(16, 185, 129, 0.95)',
            error: 'rgba(239, 68, 68, 0.95)',
            warning: 'rgba(245, 158, 11, 0.95)',
            info: 'rgba(99, 102, 241, 0.95)'
        };
        toast.style.background = colors[type] || colors.info;
        
        // Icono
        const icons = {
            success: 'ph-check-circle',
            error: 'ph-x-circle',
            warning: 'ph-warning',
            info: 'ph-info'
        };
        
        toast.innerHTML = `
            <i class="ph ${icons[type] || icons.info}" style="font-size:20px;"></i>
            <span>${message}</span>
        `;
        
        this.container.appendChild(toast);
        
        // Sonido
        SoundFX.play(type === 'error' ? 'error' : type === 'success' ? 'success' : 'notification');
        
        // Auto-remove
        setTimeout(() => {
            toast.style.animation = 'toastOut 0.3s ease-out forwards';
            setTimeout(() => toast.remove(), 300);
        }, duration);
    }
};

// CSS para animaciones de toast
const toastStyles = document.createElement('style');
toastStyles.textContent = `
    @keyframes toastIn {
        from { opacity: 0; transform: translateX(100px); }
        to { opacity: 1; transform: translateX(0); }
    }
    @keyframes toastOut {
        from { opacity: 1; transform: translateX(0); }
        to { opacity: 0; transform: translateX(100px); }
    }
`;
document.head.appendChild(toastStyles);

// Exponer globalmente
window.SoundFX = SoundFX;
window.Modal = Modal;
window.Toast = Toast;
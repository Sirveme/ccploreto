/**
 * ColegiosPro - Dashboard del Colegiado
 * Orquestador principal con carga lazy de módulos
 * 
 * Arquitectura:
 *   dashboard_colegiado.js (este archivo) = ~100 líneas, carga siempre
 *   /js/modules/modal-*.js = módulos individuales, carga bajo demanda
 *   /js/modules/ux-system.js = SoundFX, Modal, Toast (carga siempre)
 */

// ============================================
// CONFIG GLOBAL (inyectada desde template)
// ============================================
window.APP_CONFIG = window.APP_CONFIG || {};

// ============================================
// SISTEMA DE CARGA LAZY DE MÓDULOS
// ============================================
const ModuleLoader = {
    // Cache de módulos ya cargados
    _loaded: new Set(),
    _loading: new Map(), // promesas en curso

    /**
     * Registra qué módulo JS necesita cada modal
     * key = id del <dialog>, value = path relativo al JS
     */
    registry: {
        'modal-perfil':          '/static/js/modules/modal-perfil.js',
        'modal-pagos':           '/static/js/modules/modal-pagos.js',
        'modal-constancia':      '/static/js/modules/modal-constancia.js',
        'modal-certificados':    '/static/js/modules/modal-certificados.js',
        'modal-herramientas':    '/static/js/modules/modal-herramientas.js',
        'modal-mi-sitio':        '/static/js/modules/modal-mi-sitio.js',
        'modal-avisos':          '/static/js/modules/modal-avisos.js',
        'modal-calculadora':     '/static/js/modules/modal-calculadora.js',
        'modal-normas':          '/static/js/modules/modal-normas.js',
        'modal-directorio':      '/static/js/modules/modal-directorio.js',
        'modal-capacitaciones':  '/static/js/modules/modal-capacitaciones.js',
        'modal-convenios':       '/static/js/modules/modal-convenios.js',
        'modal-votaciones':      '/static/js/modules/modal-votaciones.js',
        'modal-bolsa-trabajo':   '/static/js/modules/modal-bolsa-trabajo.js',
        'modal-chat':            '/static/js/modules/modal-chat.js',
        'modal-estadisticas':    '/static/js/modules/modal-estadisticas.js',
        // Modales simples sin JS propio (no necesitan lazy load)
        // 'modal-aviso': null  → se maneja inline
    },

    /**
     * Carga un módulo JS por id de modal
     * Retorna Promise que resuelve cuando el script está listo
     */
    async load(modalId) {
        const src = this.registry[modalId];
        
        // Sin módulo registrado → no necesita carga
        if (!src) return Promise.resolve();

        // Ya cargado → resolver inmediatamente
        if (this._loaded.has(modalId)) return Promise.resolve();

        // En proceso de carga → retornar promesa existente
        if (this._loading.has(modalId)) return this._loading.get(modalId);

        // Crear promesa de carga
        const promise = new Promise((resolve, reject) => {
            const script = document.createElement('script');
            script.src = src;
            script.async = true;

            script.onload = () => {
                this._loaded.add(modalId);
                this._loading.delete(modalId);
                console.log(`[ModuleLoader] ✓ ${modalId}`);
                resolve();
            };

            script.onerror = () => {
                this._loading.delete(modalId);
                console.error(`[ModuleLoader] ✗ ${modalId}: ${src}`);
                reject(new Error(`No se pudo cargar el módulo: ${src}`));
            };

            document.head.appendChild(script);
        });

        this._loading.set(modalId, promise);
        return promise;
    },

    /**
     * Precarga módulos en idle time (conexiones rápidas)
     * Solo precarga si la conexión no es lenta
     */
    preloadWhenIdle(modalIds) {
        // Detectar conexión lenta
        const conn = navigator.connection || navigator.mozConnection;
        if (conn && (conn.saveData || conn.effectiveType === '2g' || conn.effectiveType === 'slow-2g')) {
            console.log('[ModuleLoader] Conexión lenta detectada, sin precarga');
            return;
        }

        const load = () => {
            modalIds.forEach(id => {
                if (!this._loaded.has(id) && this.registry[id]) {
                    // Usar <link rel="prefetch"> para no bloquear
                    const link = document.createElement('link');
                    link.rel = 'prefetch';
                    link.href = this.registry[id];
                    link.as = 'script';
                    document.head.appendChild(link);
                }
            });
        };

        if ('requestIdleCallback' in window) {
            requestIdleCallback(load, { timeout: 5000 });
        } else {
            setTimeout(load, 3000);
        }
    },

    /**
     * Verifica si un módulo ya está cargado
     */
    isLoaded(modalId) {
        return this._loaded.has(modalId);
    }
};

// Exponer globalmente
window.ModuleLoader = ModuleLoader;

// ============================================
// FUNCIÓN PRINCIPAL: ABRIR MODAL CON LAZY LOAD
// ============================================

/**
 * Abre un modal, cargando su módulo JS si es necesario.
 * Muestra spinner mientras carga en conexiones lentas.
 * 
 * Uso en HTML: onclick="abrirModalLazy('modal-pagos')"
 * 
 * @param {string} modalId - ID del elemento <dialog>
 * @param {object} options - { onOpen: callback, data: {} }
 */
async function abrirModalLazy(modalId, options = {}) {
    const modal = document.getElementById(modalId);
    if (!modal) {
        console.error(`Modal no encontrado: ${modalId}`);
        Toast.show('Sección no disponible', 'warning');
        return;
    }

    const needsLoad = ModuleLoader.registry[modalId] && !ModuleLoader.isLoaded(modalId);

    // Mostrar modal inmediatamente con spinner si necesita carga
    if (needsLoad) {
        _showModalLoading(modal);
    }

    try {
        // Cargar módulo (no-op si ya está cargado o no tiene módulo)
        await ModuleLoader.load(modalId);

        // Quitar spinner
        if (needsLoad) {
            _hideModalLoading(modal);
        }

        // Abrir con efecto
        Modal.open(modalId, options);

        // Disparar evento custom para que el módulo inicialice
        modal.dispatchEvent(new CustomEvent('modal:opened', { 
            detail: options.data || {} 
        }));

    } catch (err) {
        _hideModalLoading(modal);
        Toast.show('Error al cargar. Intenta de nuevo.', 'error');
        SoundFX.play('error');
    }
}

// Alias corto para uso en templates
window.abrirModalLazy = abrirModalLazy;

// También mantener compatibilidad con modales simples
window.abrirModal = function(modalId) {
    // Modal-aviso y otros simples → abrir directo
    if (!ModuleLoader.registry[modalId]) {
        Modal.open(modalId);
    } else {
        abrirModalLazy(modalId);
    }
};

// ============================================
// HELPERS DE LOADING STATE
// ============================================

function _showModalLoading(modal) {
    // Guardar contenido original del body
    const body = modal.querySelector('.modal-body');
    if (body && !body.dataset.originalContent) {
        body.dataset.originalContent = body.innerHTML;
        body.innerHTML = `
            <div class="modal-loading-state" style="text-align:center; padding:48px 20px; color:#94a3b8;">
                <div class="loading-spinner" style="
                    width:40px; height:40px; margin:0 auto 16px;
                    border:3px solid rgba(255,255,255,0.1);
                    border-top-color:#6366f1;
                    border-radius:50%;
                    animation: spin 0.8s linear infinite;
                "></div>
                <p style="margin:0; font-size:14px;">Cargando módulo...</p>
            </div>
        `;
    }
    modal.showDialog ? modal.showDialog() : modal.showModal();
}

function _hideModalLoading(modal) {
    const body = modal.querySelector('.modal-body');
    if (body && body.dataset.originalContent) {
        body.innerHTML = body.dataset.originalContent;
        delete body.dataset.originalContent;
    }
}

// ============================================
// FUNCIONES DEL DASHBOARD (siempre disponibles)
// ============================================

// Ver Aviso (modal simple, sin lazy load)
function verAviso(el) {
    document.getElementById('aviso-titulo').textContent = el.dataset.title;
    document.getElementById('aviso-contenido').textContent = el.dataset.content;
    Modal.open('modal-aviso');
}

// Toggle Accordion
function toggleAccordion(id) {
    const acc = document.getElementById(id);
    const wasOpen = acc.classList.contains('open');
    document.querySelectorAll('.accordion').forEach(a => a.classList.remove('open'));
    if (!wasOpen) {
        acc.classList.add('open');
        SoundFX.play('click');
    }
}

// Calcular progreso de ficha
function calcularProgreso() {
    const form = document.getElementById('form-perfil-completo');
    if (!form) return;

    const camposRequeridos = form.querySelectorAll('[required]');
    let completados = 0;
    camposRequeridos.forEach(campo => {
        if (campo.value && campo.value.trim() !== '') completados++;
    });

    const porcentaje = Math.round((completados / camposRequeridos.length) * 100);
    const percentEl = document.getElementById('progress-percent');
    const fillEl = document.getElementById('progress-fill');
    if (percentEl) percentEl.textContent = porcentaje + '%';
    if (fillEl) fillEl.style.width = porcentaje + '%';

    actualizarEstadoSeccion('personal', ['email', 'telefono', 'direccion', 'fecha_nacimiento']);
    actualizarEstadoSeccion('estudios', ['universidad']);
    actualizarEstadoSeccion('laboral', ['situacion_laboral']);
    actualizarEstadoSeccion('familiar', ['contacto_emergencia_nombre', 'contacto_emergencia_telefono']);
}

function actualizarEstadoSeccion(seccion, campos) {
    const form = document.getElementById('form-perfil-completo');
    if (!form) return;
    let completo = true;
    campos.forEach(nombre => {
        const campo = form.querySelector(`[name="${nombre}"]`);
        if (!campo || !campo.value || campo.value.trim() === '') completo = false;
    });
    const statusEl = document.getElementById(`status-${seccion}`);
    if (statusEl) {
        statusEl.textContent = completo ? 'Completo' : 'Pendiente';
        statusEl.className = 'accordion-status ' + (completo ? 'complete' : 'incomplete');
    }
}

// Escuchar cambios en formulario de perfil
document.getElementById('form-perfil-completo')?.addEventListener('input', calcularProgreso);

// Previsualizar foto
function previsualizarFoto(input) {
    if (input.files && input.files[0]) {
        const reader = new FileReader();
        reader.onload = function(e) {
            const placeholder = document.getElementById('preview-foto-placeholder');
            if (placeholder) {
                placeholder.outerHTML = `<img src="${e.target.result}" alt="Foto" id="preview-foto">`;
            } else {
                document.getElementById('preview-foto').src = e.target.result;
            }
        };
        reader.readAsDataURL(input.files[0]);
        SoundFX.play('success');
    }
}

// Guardar perfil completo
async function guardarPerfilCompleto(e) {
    e.preventDefault();
    const btn = document.getElementById('btn-guardar-perfil');
    const originalText = btn.innerHTML;
    btn.innerHTML = '<i class="ph ph-spinner spinner"></i> Guardando...';
    btn.disabled = true;

    const form = e.target;
    const formData = new FormData(form);
    const fotoInput = document.getElementById('input-foto-perfil');
    if (fotoInput?.files.length > 0) {
        formData.append('foto', fotoInput.files[0]);
    }

    try {
        const response = await fetch('/api/colegiado/actualizar', {
            method: 'POST',
            body: formData
        });
        const data = await response.json();
        if (response.ok) {
            SoundFX.play('success');
            Toast.show('Datos actualizados correctamente', 'success');
            setTimeout(() => location.reload(), 1500);
        } else {
            throw new Error(data.detail || 'Error al guardar');
        }
    } catch (err) {
        SoundFX.play('error');
        Toast.show(err.message || 'Error al guardar los datos', 'error');
        btn.innerHTML = originalText;
        btn.disabled = false;
    }
}

// Toggle Sonidos
function toggleSonidos() {
    const enabled = SoundFX.toggle();
    const btn = document.getElementById('btn-sound');
    if (btn) btn.innerHTML = enabled ? '<i class="ph ph-speaker-high"></i>' : '<i class="ph ph-speaker-slash"></i>';
    Toast.show(enabled ? 'Sonidos activados' : 'Sonidos desactivados', 'info', 2000);
}

async function abrirFormularioPago() {
    // Obtener datos del colegiado desde el endpoint
    try {
        const response = await fetch('/api/colegiado/mis-pagos');
        const data = await response.json();
        
        if (data && typeof AIFab !== 'undefined') {
            const colegiado = {
                id: data.colegiado?.id,
                nombre: data.colegiado?.nombre,
                dni: data.colegiado?.dni || '',
                matricula: data.colegiado?.matricula,
                condicion: data.colegiado?.condicion,
                deuda: data.resumen
            };
            AIFab.openPagoFormPrellenado(colegiado);
        }
    } catch (e) {
        console.error('Error:', e);
        if (typeof Toast !== 'undefined') Toast.show('Error al cargar datos', 'error');
    }
}


// ============================================
// INICIALIZACIÓN
// ============================================
document.addEventListener('DOMContentLoaded', () => {
    Modal.initBackdropClose();
    calcularProgreso();

    // Precarga inteligente: módulos más usados primero
    // Solo en conexiones buenas, con prefetch (no bloquea)
    ModuleLoader.preloadWhenIdle([
        'modal-pagos',
        'modal-constancia',
        'modal-certificados'
    ]);
});
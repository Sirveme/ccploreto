/**
 * Dashboard Colegiado — Shell + Lazy Modal Loader
 * ColegiosPro CCPL
 */

/* ═══ APP CONFIG (Jinja2 inyecta valores) ═══ */
window.APP_CONFIG = {
    user: {
        id: "{{ user.id }}",
        name: "{{ colegiado.apellidos_nombres if colegiado else user.user.name }}",
        matricula: "{{ colegiado.codigo_matricula if colegiado else user.public_id }}"
    },
    vapidPublicKey: "{{ vapid_public_key }}",
    wsUrl: (window.location.protocol === 'https:' ? 'wss://' : 'ws://') +
           window.location.host + '/ws/{{ user.id }}'
};

/* ═══ MODAL BASE (open/close para dialogs) ═══ */
window.Modal = {
    open(id) {
        const el = document.getElementById(id);
        if (!el) return;
        el.classList.remove('closing');
        el.showModal();
    },

    close(id) {
        const el = document.getElementById(id);
        if (!el) return;
        el.classList.add('closing');
        setTimeout(() => {
            el.close();
            el.classList.remove('closing');
        }, 150);
    }
};

/* ═══ LAZY MODAL LOADER ═══ */
window.ModalLazy = {
    loaded: {},
    loading: {},

    /**
     * Mapa de modales lazy con sus assets
     * fragment: nombre del endpoint /fragments/{fragment}
     * css/js: rutas relativas a /static/
     */
    registry: {
        'modal-perfil': {
            fragment: 'modal_perfil',
            css: '/static/css/pages/modal_perfil.css',
            js:  '/static/js/pages/modal_perfil.js'
        },
        'modal-herramientas': {
            fragment: 'modal_herramientas',
            css: '/static/css/pages/modal_herramientas.css',
            js:  '/static/js/pages/modal_herramientas.js'
        },
        'modal-mi-sitio': {
            fragment: 'modal_mi_sitio',
            css: '/static/css/pages/modal_mi_sitio.css',
            js:  '/static/js/pages/modal_mi_sitio.js'
        },
        'modal-avisos': {
            fragment: 'modal_avisos',
            css: '/static/css/pages/modal_avisos.css',
            js:  '/static/js/pages/modal_avisos.js'
        }
    },

    async open(modalId) {
        // Si ya está en DOM (inline o ya cargado), solo abrir
        if (document.getElementById(modalId)) {
            Modal.open(modalId);
            return;
        }

        // Si está en registro lazy, cargar
        const config = this.registry[modalId];
        if (!config) {
            console.warn(`[ModalLazy] Modal "${modalId}" no registrado`);
            return;
        }

        // Evitar doble carga
        if (this.loading[modalId]) {
            await this.loading[modalId];
            Modal.open(modalId);
            return;
        }

        // Mostrar indicador de carga
        this._showLoading();

        try {
            this.loading[modalId] = this._load(modalId, config);
            await this.loading[modalId];
            delete this.loading[modalId];
            this.loaded[modalId] = true;

            // Abrir después de cargar
            Modal.open(modalId);
        } catch (err) {
            console.error(`[ModalLazy] Error cargando "${modalId}":`, err);
            this._showError(modalId);
        } finally {
            this._hideLoading();
        }
    },

    async _load(modalId, config) {
        // 1. Cargar CSS (no bloqueante)
        if (config.css && !document.querySelector(`link[href="${config.css}"]`)) {
            const link = document.createElement('link');
            link.rel = 'stylesheet';
            link.href = config.css;
            document.head.appendChild(link);
        }

        // 2. Fetch HTML fragment
        const res = await fetch(`/fragments/${config.fragment}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const html = await res.text();

        // 3. Inyectar en DOM
        const container = document.getElementById('modal-container');
        container.insertAdjacentHTML('beforeend', html);

        // 4. Cargar JS (después de que el HTML esté en DOM)
        if (config.js && !document.querySelector(`script[src="${config.js}"]`)) {
            await new Promise((resolve, reject) => {
                const script = document.createElement('script');
                script.src = config.js;
                script.onload = resolve;
                script.onerror = () => reject(new Error(`Failed to load ${config.js}`));
                document.body.appendChild(script);
            });
        }
    },

    _showLoading() {
        // Mini spinner overlay
        if (document.getElementById('lazy-loader')) return;
        const div = document.createElement('div');
        div.id = 'lazy-loader';
        div.innerHTML = '<div class="spinner" style="width:28px;height:28px;border:3px solid rgba(255,255,255,0.1);border-top-color:var(--gold);border-radius:50%;"></div>';
        Object.assign(div.style, {
            position: 'fixed', inset: '0', display: 'flex',
            alignItems: 'center', justifyContent: 'center',
            background: 'rgba(0,0,0,0.5)', zIndex: '9999'
        });
        document.body.appendChild(div);
    },

    _hideLoading() {
        document.getElementById('lazy-loader')?.remove();
    },

    _showError(modalId) {
        if (typeof Toast !== 'undefined') {
            Toast.show('Error cargando módulo. Intenta de nuevo.', 'error');
        }
    }
};

/* Función global compatible con onclick="abrirModalLazy('...')" */
window.abrirModalLazy = function(modalId) {
    ModalLazy.open(modalId);
};

/* ═══ SHELL FUNCTIONS ═══ */

// Ver aviso en modal
function verAviso(el) {
    const titulo = el.dataset.title;
    const contenido = el.dataset.content;
    document.getElementById('aviso-titulo').textContent = titulo;
    document.getElementById('aviso-contenido').innerHTML = contenido;
    Modal.open('modal-aviso');
}

// Solicitar Constancia de Habilidad (TIENE COSTO — CONST-HAB en catálogo)
async function solicitarConstancia() {
    const btn = document.querySelector('.dock-btn.primary');
    const originalHTML = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<i class="ph ph-spinner spinner"></i>';

    try {
        // Verificar si ya tiene constancia pagada pendiente de descarga
        const res = await fetch('/api/colegiado/constancia/estado');
        if (res.ok) {
            const data = await res.json();
            if (data.pagada && data.url) {
                window.open(data.url, '_blank');
                if (typeof Toast !== 'undefined') Toast.show('Descargando constancia', 'success');
                return;
            }
        }
    } catch (err) {
        // Endpoint aún no existe → ir al catálogo
    } finally {
        btn.disabled = false;
        btn.innerHTML = originalHTML;
    }

    // Abrir Mis Pagos → tab Servicios → CONST-HAB preseleccionado
    ModalPagos.open({ concepto_preseleccionado: 'CONST-HAB' });
}

// === DOCK ESTACIONAL: Descuentos por pago anticipado ===
// Ene-Feb: 20% dto | Mar: 10% dto | Abr-Dic: sin botón descuento
// Solo aplica a cuotas FUTURAS, no a deuda atrasada.

function initDockEstacional() {
    const mes = new Date().getMonth() + 1; // 1-12
    const btn = document.getElementById('dock-descuento');
    const label = document.getElementById('dock-descuento-label');
    if (!btn || !label) return;

    if (mes <= 2) {
        label.textContent = '20% Dto.';
        btn.dataset.porcentaje = '20';
        btn.style.display = '';
    } else if (mes === 3) {
        label.textContent = '10% Dto.';
        btn.dataset.porcentaje = '10';
        btn.style.display = '';
    }
    // Abr-Dic: botón permanece oculto (display:none del HTML)
}

// Abre Mis Pagos con cuotas futuras del año y descuento aplicado
function abrirDescuentoAnual() {
    const btn = document.getElementById('dock-descuento');
    const porcentaje = parseInt(btn?.dataset.porcentaje || '0');
    ModalPagos.open({ descuento_anual: porcentaje });
}

// Inicializar dock al cargar
document.addEventListener('DOMContentLoaded', initDockEstacional);

// Toggle sonidos
let sonidosActivos = localStorage.getItem('sonidos') !== 'false';

function toggleSonidos() {
    sonidosActivos = !sonidosActivos;
    localStorage.setItem('sonidos', sonidosActivos);
    const icon = document.querySelector('#btn-sound i');
    icon.className = sonidosActivos ? 'ph ph-speaker-high' : 'ph ph-speaker-slash';
    if (typeof Toast !== 'undefined') {
        Toast.show(sonidosActivos ? 'Sonidos activados' : 'Sonidos silenciados', 'info');
    }
}

// Inicializar estado del botón de sonido
document.addEventListener('DOMContentLoaded', () => {
    if (!sonidosActivos) {
        const icon = document.querySelector('#btn-sound i');
        if (icon) icon.className = 'ph ph-speaker-slash';
    }
});
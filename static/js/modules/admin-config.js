/**
 * Panel de Configuración Admin
 * Manejo de secciones, formularios y guardado
 */

const ConfigAdmin = {
    currentSection: 'identidad',
    unsavedChanges: false,
    
    /**
     * Inicializa el panel
     */
    init() {
        console.log('[ConfigAdmin] Inicializando...');
        this.bindNavigation();
        this.bindFormChanges();
        this.bindToggles();
        this.loadFromHash();
    },
    
    /**
     * Bindea navegación lateral
     */
    bindNavigation() {
        document.querySelectorAll('.config-nav-item:not(.disabled)').forEach(item => {
            item.addEventListener('click', () => {
                const section = item.dataset.section;
                if (section) {
                    this.switchSection(section);
                }
            });
        });
    },
    
    /**
     * Cambia de sección
     */
    switchSection(sectionId) {
        // Verificar cambios sin guardar
        if (this.unsavedChanges) {
            if (!confirm('Tienes cambios sin guardar. ¿Deseas continuar?')) {
                return;
            }
        }
        
        // Actualizar navegación
        document.querySelectorAll('.config-nav-item').forEach(item => {
            item.classList.remove('active');
        });
        document.querySelector(`.config-nav-item[data-section="${sectionId}"]`)?.classList.add('active');
        
        // Actualizar paneles
        document.querySelectorAll('.config-section-panel').forEach(panel => {
            panel.classList.remove('active');
        });
        document.getElementById(`section-${sectionId}`)?.classList.add('active');
        
        // Actualizar estado
        this.currentSection = sectionId;
        this.unsavedChanges = false;
        
        // Actualizar URL
        history.replaceState(null, '', `#${sectionId}`);
        
        // Scroll suave al inicio del panel
        document.querySelector('.config-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    },
    
    /**
     * Carga sección desde hash de URL
     */
    loadFromHash() {
        const hash = window.location.hash.slice(1);
        if (hash && document.getElementById(`section-${hash}`)) {
            this.switchSection(hash);
        }
    },
    
    /**
     * Detecta cambios en formularios
     */
    bindFormChanges() {
        document.querySelectorAll('.config-input, .config-select, .config-textarea').forEach(input => {
            input.addEventListener('change', () => {
                this.unsavedChanges = true;
            });
        });
    },
    
    /**
     * Toggle switches
     */
    toggle(element, fieldName) {
        element.classList.toggle('active');
        const input = element.querySelector(`input[name="${fieldName}"]`);
        if (input) {
            input.value = element.classList.contains('active') ? 'true' : 'false';
        }
        this.unsavedChanges = true;
    },
    
    /**
     * Manejo de toggles
     */
    bindToggles() {
        // Los toggles ya están bindeados via onclick en el HTML
    },
    
    /**
     * Guarda configuración de una sección
     */
    async guardar(seccion) {
        const panel = document.getElementById(`section-${seccion}`);
        if (!panel) return;
        
        // Recopilar datos del formulario
        const data = {};
        
        // Inputs y selects
        panel.querySelectorAll('.config-input, .config-select, .config-textarea').forEach(input => {
            if (input.name) {
                data[input.name] = input.value;
            }
        });
        
        // Checkboxes (arrays)
        panel.querySelectorAll('input[type="checkbox"]').forEach(cb => {
            if (cb.name) {
                if (!data[cb.name]) data[cb.name] = [];
                if (cb.checked) {
                    data[cb.name].push(cb.value);
                }
            }
        });
        
        // Hiddens (toggles)
        panel.querySelectorAll('input[type="hidden"]').forEach(hidden => {
            if (hidden.name) {
                data[hidden.name] = hidden.value === 'true';
            }
        });
        
        console.log('[ConfigAdmin] Guardando:', seccion, data);
        
        // Mostrar loading en botón
        const btn = panel.querySelector('.btn-admin-primary');
        const originalText = btn.innerHTML;
        btn.innerHTML = '<i class="ph ph-spinner ph-spin"></i> Guardando...';
        btn.disabled = true;
        
        try {
            const response = await fetch('/api/admin/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    seccion: seccion,
                    config: data
                })
            });
            
            if (response.ok) {
                Toast.show('Configuración guardada correctamente', 'success');
                this.unsavedChanges = false;
            } else {
                const error = await response.json();
                Toast.show(error.detail || 'Error al guardar', 'error');
            }
        } catch (error) {
            console.error('[ConfigAdmin] Error:', error);
            Toast.show('Error de conexión', 'error');
        } finally {
            btn.innerHTML = originalText;
            btn.disabled = false;
        }
    },
    
    /**
     * Subir archivo (logo, firma)
     */
    uploadFile(tipo) {
        const input = document.getElementById(`input-${tipo}`);
        if (!input) return;
        
        input.click();
        
        input.onchange = async () => {
            const file = input.files[0];
            if (!file) return;
            
            // Validar tipo
            if (!file.type.startsWith('image/')) {
                Toast.show('Solo se permiten imágenes', 'error');
                return;
            }
            
            // Validar tamaño (max 2MB)
            if (file.size > 2 * 1024 * 1024) {
                Toast.show('La imagen no debe superar 2MB', 'error');
                return;
            }
            
            // Preview inmediato
            const preview = document.getElementById(`preview-${tipo}`);
            if (preview) {
                preview.src = URL.createObjectURL(file);
            }
            
            // Subir
            const formData = new FormData();
            formData.append('file', file);
            formData.append('tipo', tipo);
            
            try {
                const response = await fetch('/api/admin/upload', {
                    method: 'POST',
                    body: formData
                });
                
                if (response.ok) {
                    const result = await response.json();
                    Toast.show('Archivo subido correctamente', 'success');
                    this.unsavedChanges = true;
                } else {
                    Toast.show('Error al subir archivo', 'error');
                }
            } catch (error) {
                console.error('[ConfigAdmin] Upload error:', error);
                Toast.show('Error de conexión', 'error');
            }
        };
    }
};

// Inicializar cuando cargue el DOM
document.addEventListener('DOMContentLoaded', () => {
    ConfigAdmin.init();
});

// Advertir antes de salir con cambios sin guardar
window.addEventListener('beforeunload', (e) => {
    if (ConfigAdmin.unsavedChanges) {
        e.preventDefault();
        e.returnValue = '';
    }
});

// Exponer globalmente
window.ConfigAdmin = ConfigAdmin;
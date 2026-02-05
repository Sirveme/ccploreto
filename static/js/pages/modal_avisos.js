/**
 * ============================================
 * AVISOS APP - Sistema de Alertas Tributarias
 * /static/js/pages/modal_avisos.js
 * ============================================
 */

const AvisosApp = {
    // Configuración
    config: {
        // Configuración global (aplica a todas las obligaciones)
        dias_antes: [5, 3],
        horas: [8, 14, 19],
        
        // Obligaciones activas
        obligaciones: {
            pdt621: true,
            plame: true,
            afp: true,
            cts: false,
            grati: false,
            renta: false
        },
        
        // RUCs monitoreados
        rucs: []
    },

    // Grupos RUC según SUNAT
    getGrupoRuc(ultimoDigito) {
        const d = String(ultimoDigito);
        if (d === '0') return '0';
        if (d === '1') return '1';
        if (d === '2' || d === '3') return '2-3';
        if (d === '4' || d === '5') return '4-5';
        if (d === '6' || d === '7') return '6-7';
        if (d === '8' || d === '9') return '8-9';
        return d;
    },

    // ============================================
    // INICIALIZACIÓN
    // ============================================
    init() {
        this.cargarConfiguracion();
        this.bindEvents();
        this.aplicarConfigUI();
        this.renderRucs();
        this.renderProximos();
    },

    // ============================================
    // TABS
    // ============================================
    switchTab(tabId) {
        // Desactivar todos
        document.querySelectorAll('.avisos-tabs .tab-btn').forEach(btn => btn.classList.remove('active'));
        document.querySelectorAll('#modal-avisos .tab-content').forEach(tab => tab.classList.remove('active'));
        
        // Activar el seleccionado
        document.querySelector(`.avisos-tabs [onclick="AvisosApp.switchTab('${tabId}')"]`)?.classList.add('active');
        document.getElementById(`tab-${tabId}`)?.classList.add('active');
        
        // Refrescar próximos al entrar
        if (tabId === 'proximos') {
            this.renderProximos();
        }
    },

    // ============================================
    // EVENTOS
    // ============================================
    bindEvents() {
        // Días - múltiple selección
        const diasSelector = document.getElementById('dias-global');
        if (diasSelector) {
            diasSelector.addEventListener('click', (e) => {
                const btn = e.target.closest('.dia-btn');
                if (btn) btn.classList.toggle('active');
            });
        }

        // Horas - máximo 3
        const horasSelector = document.getElementById('horarios-global');
        if (horasSelector) {
            horasSelector.addEventListener('click', (e) => {
                const btn = e.target.closest('.hora-btn');
                if (!btn) return;
                
                const activos = horasSelector.querySelectorAll('.hora-btn.active').length;
                
                if (btn.classList.contains('active')) {
                    btn.classList.remove('active');
                } else if (activos < 3) {
                    btn.classList.add('active');
                } else {
                    this.showToast('Máximo 3 horarios', 'warning');
                }
            });
        }
    },

    // ============================================
    // CONFIGURACIÓN
    // ============================================
    aplicarConfigUI() {
        // Aplicar días
        const diasSelector = document.getElementById('dias-global');
        if (diasSelector) {
            diasSelector.querySelectorAll('.dia-btn').forEach(btn => {
                const dias = parseInt(btn.dataset.dias);
                btn.classList.toggle('active', this.config.dias_antes.includes(dias));
            });
        }

        // Aplicar horas
        const horasSelector = document.getElementById('horarios-global');
        if (horasSelector) {
            horasSelector.querySelectorAll('.hora-btn').forEach(btn => {
                const hora = parseInt(btn.dataset.hora);
                btn.classList.toggle('active', this.config.horas.includes(hora));
            });
        }

        // Aplicar toggles de obligaciones
        Object.keys(this.config.obligaciones).forEach(tipo => {
            const toggle = document.getElementById(`toggle-${tipo}`);
            if (toggle) {
                toggle.checked = this.config.obligaciones[tipo];
            }
        });
    },

    guardarConfiguracion() {
        // Recopilar días
        const diasSelector = document.getElementById('dias-global');
        if (diasSelector) {
            this.config.dias_antes = Array.from(diasSelector.querySelectorAll('.dia-btn.active'))
                .map(btn => parseInt(btn.dataset.dias))
                .sort((a, b) => b - a);
        }

        // Recopilar horas
        const horasSelector = document.getElementById('horarios-global');
        if (horasSelector) {
            this.config.horas = Array.from(horasSelector.querySelectorAll('.hora-btn.active'))
                .map(btn => parseInt(btn.dataset.hora))
                .sort((a, b) => a - b);
        }

        // Recopilar toggles
        ['pdt621', 'plame', 'afp', 'cts', 'grati', 'renta'].forEach(tipo => {
            const toggle = document.getElementById(`toggle-${tipo}`);
            if (toggle) {
                this.config.obligaciones[tipo] = toggle.checked;
            }
        });

        // Guardar en localStorage
        localStorage.setItem('avisos_config', JSON.stringify(this.config));

        // Guardar en backend
        this.guardarEnBackend();

        this.showToast('Configuración guardada', 'success');
    },

    async guardarEnBackend() {
        try {
            await fetch('/api/avisos/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    rucs: this.config.rucs.map(r => ({ 
                        numero: r.ruc, 
                        nombre: r.nombre 
                    })),
                    config: {
                        dias_antes: this.config.dias_antes,
                        horas: this.config.horas,
                        pdt621: this.config.obligaciones.pdt621,
                        plame: this.config.obligaciones.plame,
                        afp: this.config.obligaciones.afp,
                        cts: this.config.obligaciones.cts,
                        gratificacion: this.config.obligaciones.grati,
                        renta_anual: this.config.obligaciones.renta
                    }
                })
            });
        } catch (e) {
            console.log('Backend no disponible:', e);
        }
    },

    cargarConfiguracion() {
        const saved = localStorage.getItem('avisos_config');
        if (saved) {
            try {
                const parsed = JSON.parse(saved);
                this.config = { ...this.config, ...parsed };
            } catch (e) {
                console.error('Error cargando configuración:', e);
            }
        }
    },

    // ============================================
    // RUCs
    // ============================================
    async agregarRuc() {
        const input = document.getElementById('input-nuevo-ruc');
        const ruc = input.value.trim();
        
        if (ruc.length !== 11 || !/^\d+$/.test(ruc)) {
            this.showToast('El RUC debe tener 11 dígitos', 'error');
            return;
        }
        
        if (this.config.rucs.find(r => r.ruc === ruc)) {
            this.showToast('Este RUC ya está registrado', 'warning');
            return;
        }
        
        // Consultar razón social
        let nombre = `Contribuyente ${ruc.slice(-4)}`;
        try {
            const resp = await fetch(`/api/sunat/ruc/${ruc}`);
            if (resp.ok) {
                const data = await resp.json();
                if (data.nombre) nombre = data.nombre;
            }
        } catch (e) {
            console.log('No se pudo consultar RUC');
        }
        
        this.config.rucs.push({
            ruc: ruc,
            nombre: nombre,
            ultimoDigito: parseInt(ruc.slice(-1))
        });
        
        input.value = '';
        this.renderRucs();
        this.showToast('RUC agregado', 'success');
        
        // Guardar
        localStorage.setItem('avisos_config', JSON.stringify(this.config));
        this.guardarEnBackend();
    },

    eliminarRuc(ruc) {
        if (!confirm('¿Eliminar este RUC?')) return;
        
        this.config.rucs = this.config.rucs.filter(r => r.ruc !== ruc);
        this.renderRucs();
        this.renderProximos();
        this.showToast('RUC eliminado', 'info');
        
        localStorage.setItem('avisos_config', JSON.stringify(this.config));
        this.guardarEnBackend();
    },

    renderRucs() {
        const lista = document.getElementById('lista-rucs');
        const empty = document.getElementById('empty-rucs');
        
        if (!lista) return;
        
        if (this.config.rucs.length === 0) {
            lista.innerHTML = '';
            if (empty) empty.style.display = 'block';
            return;
        }
        
        if (empty) empty.style.display = 'none';
        
        lista.innerHTML = this.config.rucs.map(r => {
            const grupo = this.getGrupoRuc(r.ultimoDigito);
            return `
            <div class="ruc-card">
                <div class="ruc-grupo" title="Grupo SUNAT">${grupo}</div>
                <div class="ruc-data">
                    <div class="ruc-numero">${r.ruc}</div>
                    <div class="ruc-nombre">${r.nombre}</div>
                </div>
                <button class="btn-delete-ruc" onclick="AvisosApp.eliminarRuc('${r.ruc}')">
                    <i class="ph ph-trash"></i>
                </button>
            </div>
        `}).join('');
    },

    // ============================================
    // PRÓXIMOS VENCIMIENTOS
    // ============================================
    renderProximos() {
        const lista = document.getElementById('lista-proximos');
        const empty = document.getElementById('empty-proximos');
        
        if (!lista) return;
        
        if (this.config.rucs.length === 0) {
            lista.innerHTML = '';
            if (empty) empty.style.display = 'block';
            return;
        }
        
        if (empty) empty.style.display = 'none';
        
        const vencimientos = this.calcularVencimientos();
        
        if (vencimientos.length === 0) {
            lista.innerHTML = `
                <div class="empty-state">
                    <i class="ph ph-check-circle"></i>
                    <p>No hay vencimientos próximos</p>
                </div>
            `;
            return;
        }
        
        lista.innerHTML = vencimientos.map(v => {
            let urgencia = '';
            let diasClass = 'ok';
            if (v.dias <= 2) { urgencia = 'urgente'; diasClass = 'urgente'; }
            else if (v.dias <= 5) { urgencia = 'pronto'; diasClass = 'pronto'; }
            
            return `
                <div class="proximo-card ${urgencia}">
                    <span class="proximo-icon ${v.color}"><i class="ph ph-${v.icon}"></i></span>
                    <div class="proximo-info">
                        <strong>${v.tipo}</strong>
                        <small>${v.detalle}</small>
                    </div>
                    <div class="proximo-dias">
                        <div class="dias-numero ${diasClass}">${v.dias}</div>
                        <div class="dias-texto">días</div>
                    </div>
                </div>
            `;
        }).join('');
    },

    calcularVencimientos() {
        const hoy = new Date();
        hoy.setHours(0, 0, 0, 0);
        const vencimientos = [];
        
        // Días base según grupo SUNAT (simplificado)
        const cronogramaBase = {
            '0': 16, '1': 17, '2-3': 18, '4-5': 19, '6-7': 20, '8-9': 23
        };
        
        // Para cada RUC
        this.config.rucs.forEach(ruc => {
            const grupo = this.getGrupoRuc(ruc.ultimoDigito);
            const diaVence = cronogramaBase[grupo] || 15;
            
            // Fecha de vencimiento
            let fechaVence = new Date(hoy.getFullYear(), hoy.getMonth(), diaVence);
            if (fechaVence <= hoy) {
                fechaVence = new Date(hoy.getFullYear(), hoy.getMonth() + 1, diaVence);
            }
            
            const dias = Math.ceil((fechaVence - hoy) / (1000 * 60 * 60 * 24));
            
            // PDT 621
            if (this.config.obligaciones.pdt621) {
                vencimientos.push({
                    tipo: 'PDT 621',
                    detalle: `${ruc.ruc.slice(-4)} - ${ruc.nombre.substring(0, 25)}`,
                    dias: dias,
                    icon: 'file-text',
                    color: 'blue'
                });
            }
            
            // PLAME
            if (this.config.obligaciones.plame) {
                vencimientos.push({
                    tipo: 'PLAME',
                    detalle: `${ruc.ruc.slice(-4)} - ${ruc.nombre.substring(0, 25)}`,
                    dias: dias,
                    icon: 'users',
                    color: 'green'
                });
            }
        });
        
        // AFP (5to día del mes)
        if (this.config.obligaciones.afp && this.config.rucs.length > 0) {
            let fechaAFP = new Date(hoy.getFullYear(), hoy.getMonth(), 5);
            if (fechaAFP <= hoy) {
                fechaAFP = new Date(hoy.getFullYear(), hoy.getMonth() + 1, 5);
            }
            const diasAFP = Math.ceil((fechaAFP - hoy) / (1000 * 60 * 60 * 24));
            
            vencimientos.push({
                tipo: 'AFP / ONP',
                detalle: '⚠️ Vence ANTES que PDT/PLAME',
                dias: diasAFP,
                icon: 'piggy-bank',
                color: 'orange'
            });
        }
        
        // CTS
        if (this.config.obligaciones.cts) {
            const mesActual = hoy.getMonth();
            let fechaCTS;
            if (mesActual < 4) { // Antes de mayo
                fechaCTS = new Date(hoy.getFullYear(), 4, 15); // 15 mayo
            } else if (mesActual < 10) { // Mayo-Octubre
                fechaCTS = new Date(hoy.getFullYear(), 10, 15); // 15 noviembre
            } else {
                fechaCTS = new Date(hoy.getFullYear() + 1, 4, 15); // 15 mayo próximo año
            }
            const diasCTS = Math.ceil((fechaCTS - hoy) / (1000 * 60 * 60 * 24));
            
            if (diasCTS <= 30) {
                vencimientos.push({
                    tipo: 'CTS',
                    detalle: 'Depósito semestral',
                    dias: diasCTS,
                    icon: 'wallet',
                    color: 'purple'
                });
            }
        }
        
        // Gratificaciones
        if (this.config.obligaciones.grati) {
            const mesActual = hoy.getMonth();
            let fechaGrati;
            if (mesActual < 6) { // Antes de julio
                fechaGrati = new Date(hoy.getFullYear(), 6, 15); // 15 julio
            } else if (mesActual < 11) {
                fechaGrati = new Date(hoy.getFullYear(), 11, 15); // 15 diciembre
            } else {
                fechaGrati = new Date(hoy.getFullYear() + 1, 6, 15); // 15 julio próximo año
            }
            const diasGrati = Math.ceil((fechaGrati - hoy) / (1000 * 60 * 60 * 24));
            
            if (diasGrati <= 30) {
                vencimientos.push({
                    tipo: 'Gratificación',
                    detalle: mesActual < 6 ? 'Fiestas Patrias' : 'Navidad',
                    dias: diasGrati,
                    icon: 'gift',
                    color: 'pink'
                });
            }
        }
        
        // Ordenar por días
        vencimientos.sort((a, b) => a.dias - b.dias);
        
        return vencimientos.slice(0, 20);
    },

    // ============================================
    // UTILIDADES
    // ============================================
    showToast(mensaje, tipo = 'info') {
        if (window.Toast && typeof Toast.show === 'function') {
            Toast.show(mensaje, tipo);
        } else {
            console.log(`[${tipo}] ${mensaje}`);
        }
    }
};

// ============================================
// INICIALIZACIÓN
// ============================================
(function() {
    const modal = document.getElementById('modal-avisos');
    if (modal) {
        const observer = new MutationObserver((mutations) => {
            mutations.forEach((mutation) => {
                if (mutation.attributeName === 'open' && modal.hasAttribute('open')) {
                    AvisosApp.init();
                }
            });
        });
        observer.observe(modal, { attributes: true });
    }

    // Pre-cargar configuración
    document.addEventListener('DOMContentLoaded', () => {
        AvisosApp.cargarConfiguracion();
    });
})();
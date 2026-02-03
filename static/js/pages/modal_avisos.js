// ============================================
// AVISOS APP - Lógica del módulo
// ============================================

const AvisosApp = {
    // Cronograma SUNAT 2026 simplificado (último dígito -> día del mes)
    // El vencimiento es en el mes SIGUIENTE al periodo declarado
    cronogramaBase: { 0: 13, 1: 14, 2: 15, 3: 16, 4: 17, 5: 18, 6: 19, 7: 20, 8: 21, 9: 22 },
    
    // Configuración
    config: {
        rucs: [],
        alertas: {
            pdt621: { activo: true, dias: [3], horas: ['08:00', '14:00', '19:00'] },
            plame: { activo: true, dias: [3], horas: ['08:00', '14:00'] },
            afp: { activo: true, dias: [3], horas: ['08:00', '14:00'] },
            cts: { activo: false, dias: [3], horas: ['08:00', '14:00'] },
            grati: { activo: false, dias: [3], horas: ['08:00', '14:00'] },
            'renta-anual': { activo: false, dias: [5], horas: ['08:00', '14:00', '19:00'] }
        }
    },

    init() {
        this.cargarConfiguracion();
        this.renderProximos();
        this.renderRucs();
        this.aplicarConfigUI();
        this.bindEvents();
    },

    // Cambiar tab
    switchTab(tabId) {
        document.querySelectorAll('.avisos-tabs .tab-btn').forEach(btn => btn.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(tab => tab.classList.remove('active'));
        
        document.querySelector(`.avisos-tabs [onclick="AvisosApp.switchTab('${tabId}')"]`)?.classList.add('active');
        document.getElementById(`tab-${tabId}`)?.classList.add('active');
    },

    // Toggle obligación expandir/colapsar
    toggleObligacion(tipo) {
        const config = document.getElementById(`config-${tipo}`);
        if (config) {
            config.classList.toggle('collapsed');
        }
    },

    // Toggle alerta activa/inactiva
    toggleAlerta(tipo) {
        const checkbox = document.getElementById(`toggle-${tipo}`);
        if (this.config.alertas[tipo]) {
            this.config.alertas[tipo].activo = checkbox?.checked || false;
        }
    },

    // Agregar RUC
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
        
        // Intentar consultar razón social
        let nombre = `Contribuyente ${ruc.slice(-4)}`;
        try {
            const resp = await fetch(`/api/sunat/ruc/${ruc}`);
            if (resp.ok) {
                const data = await resp.json();
                if (data.nombre) nombre = data.nombre;
            }
        } catch (e) {
            console.log('No se pudo consultar RUC, usando nombre genérico');
        }
        
        this.config.rucs.push({
            ruc: ruc,
            nombre: nombre,
            ultimoDigito: parseInt(ruc.slice(-1))
        });
        
        input.value = '';
        this.renderRucs();
        this.renderProximos();
        this.showToast('RUC agregado correctamente', 'success');
    },

    // Eliminar RUC
    eliminarRuc(ruc) {
        if (!confirm('¿Eliminar este RUC de tus alertas?')) return;
        
        this.config.rucs = this.config.rucs.filter(r => r.ruc !== ruc);
        this.renderRucs();
        this.renderProximos();
        this.showToast('RUC eliminado', 'info');
    },

    // Renderizar lista de RUCs
    // Obtener grupo RUC según último dígito (como agrupa SUNAT)
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
                <div class="ruc-digito" title="Grupo SUNAT: ${grupo}">${grupo}</div>
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

    // Renderizar próximos vencimientos
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
        
        const hoy = new Date();
        const vencimientos = [];
        
        // Para cada RUC, calcular vencimientos
        this.config.rucs.forEach(ruc => {
            // PDT 621
            if (this.config.alertas.pdt621.activo) {
                const fechaPDT = this.calcularVencimientoPDT(ruc.ultimoDigito);
                const dias = this.diasHasta(fechaPDT);
                if (dias >= 0 && dias <= 30) {
                    vencimientos.push({
                        tipo: 'PDT 621',
                        ruc: ruc.ruc,
                        nombre: ruc.nombre,
                        fecha: fechaPDT,
                        dias: dias,
                        icon: 'file-text',
                        color: 'blue'
                    });
                }
            }
            
            // PLAME (mismo día que PDT)
            if (this.config.alertas.plame.activo) {
                const fechaPLAME = this.calcularVencimientoPDT(ruc.ultimoDigito);
                const dias = this.diasHasta(fechaPLAME);
                if (dias >= 0 && dias <= 30) {
                    vencimientos.push({
                        tipo: 'PLAME',
                        ruc: ruc.ruc,
                        nombre: ruc.nombre,
                        fecha: fechaPLAME,
                        dias: dias,
                        icon: 'users',
                        color: 'green'
                    });
                }
            }
        });
        
        // AFP (fecha fija para todos - 5to día hábil)
        if (this.config.alertas.afp.activo && this.config.rucs.length > 0) {
            const fechaAFP = this.proximaFechaAFP();
            const dias = this.diasHasta(fechaAFP);
            if (dias >= 0 && dias <= 30) {
                vencimientos.push({
                    tipo: 'AFP/ONP',
                    ruc: 'Todos',
                    nombre: '⚠️ Vence ANTES que PLAME',
                    fecha: fechaAFP,
                    dias: dias,
                    icon: 'piggy-bank',
                    color: 'orange'
                });
            }
        }
        
        // Ordenar por días restantes
        vencimientos.sort((a, b) => a.dias - b.dias);
        
        // Renderizar
        lista.innerHTML = vencimientos.slice(0, 15).map(v => {
            let urgencia = '';
            let diasClass = 'ok';
            if (v.dias <= 1) { urgencia = 'urgente'; diasClass = 'urgente'; }
            else if (v.dias <= 3) { urgencia = 'pronto'; diasClass = 'pronto'; }
            
            return `
                <div class="proximo-card ${urgencia}">
                    <span class="proximo-icon ${v.color}"><i class="ph ph-${v.icon}"></i></span>
                    <div class="proximo-info">
                        <strong>${v.tipo}</strong>
                        <small>${v.ruc === 'Todos' ? v.nombre : `${v.ruc} - ${v.nombre}`}</small>
                    </div>
                    <div class="proximo-dias">
                        <div class="dias-numero ${diasClass}">${v.dias}</div>
                        <div class="dias-texto">días</div>
                    </div>
                </div>
            `;
        }).join('');
        
        if (vencimientos.length === 0) {
            lista.innerHTML = `
                <div class="empty-state">
                    <i class="ph ph-check-circle"></i>
                    <p>No hay vencimientos próximos</p>
                </div>
            `;
        }
    },

    // Calcular vencimiento PDT según último dígito
    calcularVencimientoPDT(ultimoDigito) {
        const hoy = new Date();
        const diaVence = this.cronogramaBase[ultimoDigito] || 15;
        
        // El vencimiento es en el mes actual (para el periodo del mes anterior)
        let fechaVence = new Date(hoy.getFullYear(), hoy.getMonth(), diaVence);
        
        // Si ya pasó, calcular para el próximo mes
        if (fechaVence <= hoy) {
            fechaVence = new Date(hoy.getFullYear(), hoy.getMonth() + 1, diaVence);
        }
        
        return fechaVence;
    },

    // Próxima fecha AFP (5to día hábil del mes)
    proximaFechaAFP() {
        const hoy = new Date();
        let fecha = new Date(hoy.getFullYear(), hoy.getMonth(), 5);
        
        // Si ya pasó el 5, ir al siguiente mes
        if (fecha <= hoy) {
            fecha = new Date(hoy.getFullYear(), hoy.getMonth() + 1, 5);
        }
        
        return fecha;
    },

    // Días hasta una fecha
    diasHasta(fecha) {
        const hoy = new Date();
        hoy.setHours(0, 0, 0, 0);
        const diff = fecha.getTime() - hoy.getTime();
        return Math.ceil(diff / (1000 * 60 * 60 * 24));
    },

    // Bind events para botones de días y horas
    bindEvents() {
        // Días - solo uno activo por obligación
        document.querySelectorAll('.dias-selector').forEach(selector => {
            selector.addEventListener('click', (e) => {
                const btn = e.target.closest('.dia-btn');
                if (!btn) return;
                
                selector.querySelectorAll('.dia-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
            });
        });

        // Horas - máximo 3
        document.querySelectorAll('.horarios-selector').forEach(selector => {
            selector.addEventListener('click', (e) => {
                const btn = e.target.closest('.hora-btn');
                if (!btn) return;
                
                const activos = selector.querySelectorAll('.hora-btn.active').length;
                
                if (btn.classList.contains('active')) {
                    btn.classList.remove('active');
                } else if (activos < 3) {
                    btn.classList.add('active');
                } else {
                    this.showToast('Máximo 3 horarios por obligación', 'warning');
                }
            });
        });
    },

    // Aplicar configuración guardada a la UI
    aplicarConfigUI() {
        Object.keys(this.config.alertas).forEach(tipo => {
            const alerta = this.config.alertas[tipo];
            
            // Toggle
            const toggle = document.getElementById(`toggle-${tipo}`);
            if (toggle) toggle.checked = alerta.activo;
            
            // Días
            const diasSelector = document.querySelector(`.dias-selector[data-tipo="${tipo}"]`);
            if (diasSelector && alerta.dias?.length) {
                diasSelector.querySelectorAll('.dia-btn').forEach(btn => {
                    btn.classList.toggle('active', alerta.dias.includes(parseInt(btn.dataset.dias)));
                });
            }
            
            // Horas
            const horasSelector = document.querySelector(`.horarios-selector[data-tipo="${tipo}"]`);
            if (horasSelector && alerta.horas?.length) {
                horasSelector.querySelectorAll('.hora-btn').forEach(btn => {
                    btn.classList.toggle('active', alerta.horas.includes(btn.dataset.hora));
                });
            }
        });
    },

    // Guardar configuración
    async guardarConfiguracion() {
        // Recopilar de la UI
        document.querySelectorAll('.obligacion-card').forEach(card => {
            const tipo = card.dataset.tipo;
            if (!this.config.alertas[tipo]) return;
            
            const toggle = card.querySelector(`#toggle-${tipo}`);
            const diasBtns = card.querySelectorAll('.dias-selector .dia-btn.active');
            const horasBtns = card.querySelectorAll('.horarios-selector .hora-btn.active');
            
            this.config.alertas[tipo].activo = toggle?.checked || false;
            this.config.alertas[tipo].dias = Array.from(diasBtns).map(b => parseInt(b.dataset.dias));
            this.config.alertas[tipo].horas = Array.from(horasBtns).map(b => b.dataset.hora);
        });
        
        // Guardar en localStorage
        localStorage.setItem('avisos_config', JSON.stringify(this.config));
        
        // Guardar en backend
        try {
            await fetch('/api/avisos/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    rucs: this.config.rucs.map(r => ({ numero: r.ruc, nombre: r.nombre })),
                    config: this.config.alertas
                })
            });
        } catch (e) {
            console.log('Error guardando en backend, usando localStorage');
        }
        
        this.showToast('Configuración guardada', 'success');
    },

    // Cargar configuración
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

    // Toast
    showToast(mensaje, tipo = 'info') {
        if (window.Toast && typeof Toast.show === 'function') {
            Toast.show(mensaje, tipo);
        } else {
            console.log(`[${tipo}] ${mensaje}`);
        }
    }
};

// Auto-init cuando se abra el modal
const modalAvisos = document.getElementById('modal-avisos');
if (modalAvisos) {
    // Observer para detectar cuando se abre
    const observer = new MutationObserver((mutations) => {
        mutations.forEach((mutation) => {
            if (mutation.attributeName === 'open' && modalAvisos.hasAttribute('open')) {
                AvisosApp.init();
            }
        });
    });
    observer.observe(modalAvisos, { attributes: true });
}

// También init en DOMContentLoaded por si acaso
document.addEventListener('DOMContentLoaded', () => {
    // Pre-cargar config aunque no esté abierto el modal
    AvisosApp.cargarConfiguracion();
});
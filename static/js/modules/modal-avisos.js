/**
 * modal-avisos.js
 * Módulo lazy: Sistema de Alertas Tributarias para Contadores
 * (Migrado de modal_avisos.js al patrón lazy)
 * 
 * Funcionalidades:
 *   - Configuración de alertas por obligación (PDT621, PLAME, AFP, CTS, Grati, Renta)
 *   - Gestión de RUCs monitoreados
 *   - Cálculo de próximos vencimientos según cronograma SUNAT
 *   - Persistencia en localStorage + backend
 */
(function() {
    'use strict';

    const MODAL_ID = 'modal-avisos';
    let initialized = false;

    // ============================================
    // CONFIGURACIÓN
    // ============================================
    const config = {
        dias_antes: [5, 3],
        horas: [8, 14, 19],
        obligaciones: {
            pdt621: true,
            plame: true,
            afp: true,
            cts: false,
            grati: false,
            renta: false
        },
        rucs: []
    };

    // ============================================
    // INICIALIZACIÓN
    // ============================================
    async function init() {
        if (initialized) return;
        initialized = true;

        await cargarConfiguracion();
        bindEvents();
        aplicarConfigUI();
        renderRucs();
        renderProximos();
    }

    // ============================================
    // GRUPOS RUC SEGÚN SUNAT
    // ============================================
    function getGrupoRuc(ultimoDigito) {
        const d = String(ultimoDigito);
        if (d === '0') return '0';
        if (d === '1') return '1';
        if (d === '2' || d === '3') return '2-3';
        if (d === '4' || d === '5') return '4-5';
        if (d === '6' || d === '7') return '6-7';
        if (d === '8' || d === '9') return '8-9';
        return d;
    }

    // ============================================
    // TABS
    // ============================================
    function switchTab(tabId) {
        document.querySelectorAll('.avisos-tabs .tab-btn').forEach(btn => btn.classList.remove('active'));
        document.querySelectorAll(`#${MODAL_ID} .tab-content`).forEach(tab => tab.classList.remove('active'));

        document.querySelector(`.avisos-tabs [data-tab="${tabId}"]`)?.classList.add('active');
        document.getElementById(`tab-${tabId}`)?.classList.add('active');

        if (tabId === 'proximos') renderProximos();
    }

    // ============================================
    // EVENTOS
    // ============================================
    function bindEvents() {
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
                    Toast.show('Máximo 3 horarios', 'warning');
                }
            });
        }

        // Tabs - delegación de eventos
        const modal = document.getElementById(MODAL_ID);
        if (modal) {
            modal.querySelectorAll('.avisos-tabs .tab-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    const tabId = btn.dataset.tab;
                    if (tabId) switchTab(tabId);
                });
            });
        }
    }

    // ============================================
    // CONFIGURACIÓN UI
    // ============================================
    function aplicarConfigUI() {
        // Aplicar días
        const diasSelector = document.getElementById('dias-global');
        if (diasSelector) {
            diasSelector.querySelectorAll('.dia-btn').forEach(btn => {
                const dias = parseInt(btn.dataset.dias);
                btn.classList.toggle('active', config.dias_antes.includes(dias));
            });
        }

        // Aplicar horas
        const horasSelector = document.getElementById('horarios-global');
        if (horasSelector) {
            horasSelector.querySelectorAll('.hora-btn').forEach(btn => {
                const hora = parseInt(btn.dataset.hora);
                btn.classList.toggle('active', config.horas.includes(hora));
            });
        }

        // Aplicar toggles de obligaciones
        Object.keys(config.obligaciones).forEach(tipo => {
            const toggle = document.getElementById(`toggle-${tipo}`);
            if (toggle) toggle.checked = config.obligaciones[tipo];
        });
    }

    function guardarConfiguracion() {
        // Recopilar días
        const diasSelector = document.getElementById('dias-global');
        if (diasSelector) {
            config.dias_antes = Array.from(diasSelector.querySelectorAll('.dia-btn.active'))
                .map(btn => parseInt(btn.dataset.dias))
                .sort((a, b) => b - a);
        }

        // Recopilar horas
        const horasSelector = document.getElementById('horarios-global');
        if (horasSelector) {
            config.horas = Array.from(horasSelector.querySelectorAll('.hora-btn.active'))
                .map(btn => parseInt(btn.dataset.hora))
                .sort((a, b) => a - b);
        }

        // Recopilar toggles
        ['pdt621', 'plame', 'afp', 'cts', 'grati', 'renta'].forEach(tipo => {
            const toggle = document.getElementById(`toggle-${tipo}`);
            if (toggle) config.obligaciones[tipo] = toggle.checked;
        });

        // Persistir
        localStorage.setItem('avisos_config', JSON.stringify(config));
        guardarEnBackend();
        Toast.show('Configuración guardada', 'success');
        SoundFX.play('success');
    }

    async function guardarEnBackend() {
        try {
            await fetch('/api/avisos/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    rucs: config.rucs.map(r => ({
                        numero: r.ruc,
                        nombre: r.nombre
                    })),
                    config: {
                        dias_antes: config.dias_antes,
                        horas: config.horas,
                        pdt621: config.obligaciones.pdt621,
                        plame: config.obligaciones.plame,
                        afp: config.obligaciones.afp,
                        cts: config.obligaciones.cts,
                        gratificacion: config.obligaciones.grati,
                        renta_anual: config.obligaciones.renta
                    }
                })
            });
        } catch (e) {
            // Silencioso - backend puede no estar disponible
        }
    }

    async function cargarConfiguracion() {
        // Fuente de verdad: backend (tabla alerta_config + colegiado_ruc)
        try {
            const res = await fetch('/api/avisos/config');
            if (res.ok) {
                const data = await res.json();

                // Mapear config del backend → formato interno JS
                if (data.config) {
                    config.obligaciones.pdt621 = data.config.pdt621 ?? true;
                    config.obligaciones.plame = data.config.plame ?? true;
                    config.obligaciones.afp = data.config.afp ?? true;
                    config.obligaciones.cts = data.config.cts ?? false;
                    config.obligaciones.grati = data.config.gratificacion ?? false;
                    config.obligaciones.renta = data.config.renta_anual ?? false;
                    config.dias_antes = data.config.dias_antes || [5, 3];
                    config.horas = data.config.horas || [8, 14, 19];
                }

                // Mapear RUCs del backend → formato interno JS
                if (data.rucs && data.rucs.length > 0) {
                    config.rucs = data.rucs.map(r => ({
                        ruc: r.numero || r.ruc,
                        nombre: r.nombre,
                        ultimoDigito: r.ultimoDigito ?? parseInt((r.numero || '0').slice(-1))
                    }));
                }

                // Sincronizar localStorage con BD
                localStorage.setItem('avisos_config', JSON.stringify(config));
                return;
            }
        } catch (e) {
            // Backend no disponible, fallback a localStorage
        }

        // Fallback: localStorage
        const saved = localStorage.getItem('avisos_config');
        if (saved) {
            try {
                const parsed = JSON.parse(saved);
                Object.assign(config, parsed);
            } catch (e) {
                // Config corrupta, usar defaults
            }
        }
    }

    // ============================================
    // RUCs
    // ============================================
    async function agregarRuc() {
        const input = document.getElementById('input-nuevo-ruc');
        if (!input) return;
        const ruc = input.value.trim();

        if (ruc.length !== 11 || !/^\d+$/.test(ruc)) {
            Toast.show('El RUC debe tener 11 dígitos', 'error');
            SoundFX.play('error');
            return;
        }

        if (config.rucs.find(r => r.ruc === ruc)) {
            Toast.show('Este RUC ya está registrado', 'warning');
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
            // Continuar con nombre genérico
        }

        config.rucs.push({
            ruc: ruc,
            nombre: nombre,
            ultimoDigito: parseInt(ruc.slice(-1))
        });

        input.value = '';
        renderRucs();
        SoundFX.play('success');
        Toast.show('RUC agregado', 'success');

        localStorage.setItem('avisos_config', JSON.stringify(config));
        guardarEnBackend();
    }

    function eliminarRuc(ruc) {
        if (!confirm('¿Eliminar este RUC?')) return;

        config.rucs = config.rucs.filter(r => r.ruc !== ruc);
        renderRucs();
        renderProximos();
        Toast.show('RUC eliminado', 'info');

        localStorage.setItem('avisos_config', JSON.stringify(config));
        guardarEnBackend();
    }

    function renderRucs() {
        const lista = document.getElementById('lista-rucs');
        const empty = document.getElementById('empty-rucs');
        if (!lista) return;

        if (config.rucs.length === 0) {
            lista.innerHTML = '';
            if (empty) empty.style.display = 'block';
            return;
        }

        if (empty) empty.style.display = 'none';

        lista.innerHTML = config.rucs.map(r => {
            const grupo = getGrupoRuc(r.ultimoDigito);
            return `
            <div class="ruc-card">
                <div class="ruc-grupo" title="Grupo SUNAT">${grupo}</div>
                <div class="ruc-data">
                    <div class="ruc-numero">${r.ruc}</div>
                    <div class="ruc-nombre">${r.nombre}</div>
                </div>
                <button class="btn-delete-ruc" onclick="window._avisosModule.eliminarRuc('${r.ruc}')">
                    <i class="ph ph-trash"></i>
                </button>
            </div>
            `;
        }).join('');
    }

    // ============================================
    // PRÓXIMOS VENCIMIENTOS
    // ============================================
    function renderProximos() {
        const lista = document.getElementById('lista-proximos');
        const empty = document.getElementById('empty-proximos');
        if (!lista) return;

        if (config.rucs.length === 0) {
            lista.innerHTML = '';
            if (empty) empty.style.display = 'block';
            return;
        }

        if (empty) empty.style.display = 'none';

        const vencimientos = calcularVencimientos();

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
    }

    function calcularVencimientos() {
        const hoy = new Date();
        hoy.setHours(0, 0, 0, 0);
        const vencimientos = [];

        const cronogramaBase = {
            '0': 16, '1': 17, '2-3': 18, '4-5': 19, '6-7': 20, '8-9': 23
        };

        // Para cada RUC
        config.rucs.forEach(ruc => {
            const grupo = getGrupoRuc(ruc.ultimoDigito);
            const diaVence = cronogramaBase[grupo] || 15;

            let fechaVence = new Date(hoy.getFullYear(), hoy.getMonth(), diaVence);
            if (fechaVence <= hoy) {
                fechaVence = new Date(hoy.getFullYear(), hoy.getMonth() + 1, diaVence);
            }

            const dias = Math.ceil((fechaVence - hoy) / (1000 * 60 * 60 * 24));

            if (config.obligaciones.pdt621) {
                vencimientos.push({
                    tipo: 'PDT 621',
                    detalle: `${ruc.ruc.slice(-4)} - ${ruc.nombre.substring(0, 25)}`,
                    dias, icon: 'file-text', color: 'blue'
                });
            }

            if (config.obligaciones.plame) {
                vencimientos.push({
                    tipo: 'PLAME',
                    detalle: `${ruc.ruc.slice(-4)} - ${ruc.nombre.substring(0, 25)}`,
                    dias, icon: 'users', color: 'green'
                });
            }
        });

        // AFP (5to día del mes)
        if (config.obligaciones.afp && config.rucs.length > 0) {
            let fechaAFP = new Date(hoy.getFullYear(), hoy.getMonth(), 5);
            if (fechaAFP <= hoy) {
                fechaAFP = new Date(hoy.getFullYear(), hoy.getMonth() + 1, 5);
            }
            vencimientos.push({
                tipo: 'AFP / ONP',
                detalle: '⚠️ Vence ANTES que PDT/PLAME',
                dias: Math.ceil((fechaAFP - hoy) / (1000 * 60 * 60 * 24)),
                icon: 'piggy-bank', color: 'orange'
            });
        }

        // CTS (mayo y noviembre)
        if (config.obligaciones.cts) {
            const mesActual = hoy.getMonth();
            let fechaCTS;
            if (mesActual < 4) fechaCTS = new Date(hoy.getFullYear(), 4, 15);
            else if (mesActual < 10) fechaCTS = new Date(hoy.getFullYear(), 10, 15);
            else fechaCTS = new Date(hoy.getFullYear() + 1, 4, 15);

            const diasCTS = Math.ceil((fechaCTS - hoy) / (1000 * 60 * 60 * 24));
            if (diasCTS <= 30) {
                vencimientos.push({
                    tipo: 'CTS', detalle: 'Depósito semestral',
                    dias: diasCTS, icon: 'wallet', color: 'purple'
                });
            }
        }

        // Gratificaciones (julio y diciembre)
        if (config.obligaciones.grati) {
            const mesActual = hoy.getMonth();
            let fechaGrati;
            if (mesActual < 6) fechaGrati = new Date(hoy.getFullYear(), 6, 15);
            else if (mesActual < 11) fechaGrati = new Date(hoy.getFullYear(), 11, 15);
            else fechaGrati = new Date(hoy.getFullYear() + 1, 6, 15);

            const diasGrati = Math.ceil((fechaGrati - hoy) / (1000 * 60 * 60 * 24));
            if (diasGrati <= 30) {
                vencimientos.push({
                    tipo: 'Gratificación',
                    detalle: mesActual < 6 ? 'Fiestas Patrias' : 'Navidad',
                    dias: diasGrati, icon: 'gift', color: 'pink'
                });
            }
        }

        vencimientos.sort((a, b) => a.dias - b.dias);
        return vencimientos.slice(0, 20);
    }

    // ============================================
    // AUTO-REGISTRO
    // ============================================
    const modal = document.getElementById(MODAL_ID);
    if (modal) {
        modal.addEventListener('modal:opened', () => {
            init();
            if (initialized) renderProximos(); // Refrescar vencimientos cada apertura
        });
    }

    // ============================================
    // API PÚBLICA
    // ============================================
    window._avisosModule = {
        switchTab,
        guardarConfiguracion,
        agregarRuc,
        eliminarRuc,
        recargar: renderProximos
    };

    // Alias para onclick existentes en HTML que usan AvisosApp.xxx
    window.AvisosApp = {
        switchTab,
        guardarConfiguracion,
        agregarRuc,
        eliminarRuc,
        renderProximos
    };

})();
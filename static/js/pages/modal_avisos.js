/**
 * Modal Avisos — Alertas Tributarias, RUCs, Próximos Vencimientos
 */

window.AvisosApp = {
    config: {
        dias: [5, 3],
        horarios: [8, 14, 19],
        obligaciones: {
            pdt621: true, plame: true, afp: true,
            cts: false, grati: false, renta: false
        }
    },
    rucs: [],

    init() {
        this.cargarConfig();
        this.bindEvents();
    },

    // ═══ Tabs ═══
    switchTab(tabId) {
        document.querySelectorAll('#modal-avisos .tab-content').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('#modal-avisos .tab-btn').forEach(b => b.classList.remove('active'));

        const tab = document.getElementById('tab-' + tabId);
        if (tab) tab.classList.add('active');

        // Activar botón
        const btns = document.querySelectorAll('#modal-avisos .tab-btn');
        const tabMap = { 'configurar': 0, 'mis-rucs': 1, 'proximos': 2 };
        if (btns[tabMap[tabId]]) btns[tabMap[tabId]].classList.add('active');

        if (tabId === 'mis-rucs') this.renderRucs();
        if (tabId === 'proximos') this.renderProximos();
    },

    // ═══ Events ═══
    bindEvents() {
        // Días selector
        document.querySelectorAll('#dias-global .dia-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                btn.classList.toggle('active');
            });
        });

        // Horarios selector (max 3)
        document.querySelectorAll('#horarios-global .hora-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const activos = document.querySelectorAll('#horarios-global .hora-btn.active');
                if (!btn.classList.contains('active') && activos.length >= 3) {
                    if (typeof Toast !== 'undefined') Toast.show('Máximo 3 horarios', 'warning');
                    return;
                }
                btn.classList.toggle('active');
            });
        });
    },

    // ═══ Configuración ═══
    cargarConfig() {
        try {
            const saved = localStorage.getItem('avisos_config');
            if (saved) this.config = JSON.parse(saved);

            const savedRucs = localStorage.getItem('avisos_rucs');
            if (savedRucs) this.rucs = JSON.parse(savedRucs);
        } catch (e) {
            console.warn('[Avisos] Error cargando config:', e);
        }
    },

    guardarConfiguracion() {
        // Recoger días
        this.config.dias = [];
        document.querySelectorAll('#dias-global .dia-btn.active').forEach(btn => {
            this.config.dias.push(parseInt(btn.dataset.dias));
        });

        // Recoger horarios
        this.config.horarios = [];
        document.querySelectorAll('#horarios-global .hora-btn.active').forEach(btn => {
            this.config.horarios.push(parseInt(btn.dataset.hora));
        });

        // Recoger obligaciones
        this.config.obligaciones = {
            pdt621: document.getElementById('toggle-pdt621')?.checked || false,
            plame: document.getElementById('toggle-plame')?.checked || false,
            afp: document.getElementById('toggle-afp')?.checked || false,
            cts: document.getElementById('toggle-cts')?.checked || false,
            grati: document.getElementById('toggle-grati')?.checked || false,
            renta: document.getElementById('toggle-renta')?.checked || false,
        };

        localStorage.setItem('avisos_config', JSON.stringify(this.config));
        if (typeof Toast !== 'undefined') Toast.show('Configuración guardada', 'success');
    },

    // ═══ RUCs ═══
    agregarRuc() {
        const input = document.getElementById('input-nuevo-ruc');
        const ruc = input?.value?.trim();

        if (!ruc || ruc.length !== 11 || !/^\d{11}$/.test(ruc)) {
            if (typeof Toast !== 'undefined') Toast.show('RUC inválido (11 dígitos)', 'error');
            return;
        }

        if (this.rucs.find(r => r.ruc === ruc)) {
            if (typeof Toast !== 'undefined') Toast.show('RUC ya registrado', 'warning');
            return;
        }

        this.rucs.push({ ruc, nombre: 'Cargando...', added: new Date().toISOString() });
        localStorage.setItem('avisos_rucs', JSON.stringify(this.rucs));
        input.value = '';
        this.renderRucs();

        if (typeof Toast !== 'undefined') Toast.show('RUC agregado', 'success');
    },

    eliminarRuc(ruc) {
        this.rucs = this.rucs.filter(r => r.ruc !== ruc);
        localStorage.setItem('avisos_rucs', JSON.stringify(this.rucs));
        this.renderRucs();
    },

    renderRucs() {
        const container = document.getElementById('lista-rucs');
        const empty = document.getElementById('empty-rucs');
        if (!container) return;

        if (this.rucs.length === 0) {
            container.innerHTML = '';
            if (empty) empty.style.display = '';
            return;
        }

        if (empty) empty.style.display = 'none';
        container.innerHTML = this.rucs.map(r => `
            <div class="ruc-card">
                <div class="ruc-info">
                    <strong>${r.ruc}</strong>
                    <span>${r.nombre}</span>
                </div>
                <button class="btn-delete-ruc" onclick="AvisosApp.eliminarRuc('${r.ruc}')">
                    <i class="ph ph-trash"></i>
                </button>
            </div>
        `).join('');
    },

    // ═══ Próximos Vencimientos ═══
    renderProximos() {
        const container = document.getElementById('lista-proximos');
        const empty = document.getElementById('empty-proximos');
        if (!container) return;

        if (this.rucs.length === 0) {
            container.innerHTML = '';
            if (empty) empty.style.display = '';
            return;
        }

        if (empty) empty.style.display = 'none';
        // TODO: Calcular vencimientos reales según último dígito del RUC
        container.innerHTML = '<div class="empty-state"><i class="ph ph-code"></i><p>Cálculo de vencimientos próximamente</p></div>';
    }
};

// Inicializar
if (document.getElementById('modal-avisos')) {
    AvisosApp.init();
} else {
    document.addEventListener('DOMContentLoaded', () => AvisosApp.init());
}

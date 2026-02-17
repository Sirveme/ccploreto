/**
 * Modal Perfil — Accordion, Progreso, Guardar Perfil
 */

// Toggle accordion
function toggleAccordion(id) {
    const acc = document.getElementById(id);
    if (!acc) return;
    acc.classList.toggle('open');
}

// Calcular progreso del formulario
function calcularProgreso() {
    const form = document.getElementById('form-perfil-completo');
    if (!form) return;

    const campos = form.querySelectorAll('input[required], select[required]');
    let total = campos.length;
    let completados = 0;

    campos.forEach(c => {
        if (c.value && c.value.trim()) completados++;
    });

    const pct = total > 0 ? Math.round((completados / total) * 100) : 0;
    const fill = document.getElementById('progress-fill');
    const text = document.getElementById('progress-percent');

    if (fill) fill.style.width = pct + '%';
    if (text) text.textContent = pct + '%';

    // Actualizar status de cada sección
    actualizarStatusSeccion('personal', ['email', 'telefono', 'direccion', 'fecha_nacimiento']);
    actualizarStatusSeccion('estudios', ['universidad']);
    actualizarStatusSeccion('laboral', ['situacion_laboral']);
    actualizarStatusSeccion('familiar', ['contacto_emergencia_nombre', 'contacto_emergencia_telefono']);
}

function actualizarStatusSeccion(seccion, camposRequeridos) {
    const form = document.getElementById('form-perfil-completo');
    if (!form) return;

    const todosLlenos = camposRequeridos.every(name => {
        const el = form.querySelector(`[name="${name}"]`);
        return el && el.value && el.value.trim();
    });

    const status = document.getElementById(`status-${seccion}`);
    if (status) {
        status.textContent = todosLlenos ? 'Completo' : 'Pendiente';
        status.className = `accordion-status ${todosLlenos ? 'complete' : 'incomplete'}`;
    }
}

// Guardar perfil
async function guardarPerfilCompleto(event) {
    event.preventDefault();

    const form = document.getElementById('form-perfil-completo');
    const btn = document.getElementById('btn-guardar-perfil');
    const originalHTML = btn.innerHTML;

    btn.disabled = true;
    btn.innerHTML = '<i class="ph ph-spinner spinner"></i> Guardando...';

    try {
        const formData = new FormData(form);
        const data = Object.fromEntries(formData.entries());

        // Construir experiencia laboral
        data.experiencia_laboral = [];
        for (let i = 1; i <= 3; i++) {
            const empresa = data[`exp_empresa_${i}`];
            const cargo = data[`exp_cargo_${i}`];
            const periodo = data[`exp_periodo_${i}`];
            if (empresa || cargo || periodo) {
                data.experiencia_laboral.push({ empresa, cargo, periodo });
            }
            delete data[`exp_empresa_${i}`];
            delete data[`exp_cargo_${i}`];
            delete data[`exp_periodo_${i}`];
        }

        const res = await fetch('/api/colegiado/perfil', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });

        if (!res.ok) throw new Error(`HTTP ${res.status}`);

        if (typeof Toast !== 'undefined') Toast.show('Perfil actualizado', 'success');
        calcularProgreso();
    } catch (err) {
        console.error('[Perfil] Error:', err);
        if (typeof Toast !== 'undefined') Toast.show('Error al guardar perfil', 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = originalHTML;
    }
}

// Previsualizar foto
function previsualizarFoto(input) {
    if (!input.files || !input.files[0]) return;
    const file = input.files[0];

    // Validar tamaño (max 2MB)
    if (file.size > 2 * 1024 * 1024) {
        if (typeof Toast !== 'undefined') Toast.show('La foto no debe superar 2MB', 'error');
        return;
    }

    const reader = new FileReader();
    reader.onload = function(e) {
        const preview = document.getElementById('preview-foto');
        const placeholder = document.getElementById('preview-foto-placeholder');
        if (preview) {
            preview.src = e.target.result;
        } else if (placeholder) {
            placeholder.outerHTML = `<img src="${e.target.result}" alt="Foto" id="preview-foto">`;
        }
        subirFoto(file);
    };
    reader.readAsDataURL(file);
}

// Subir foto al servidor
async function subirFoto(file) {
    try {
        const formData = new FormData();
        formData.append('foto', file);

        const res = await fetch('/api/colegiado/foto', {
            method: 'POST',
            body: formData
        });

        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        if (typeof Toast !== 'undefined') Toast.show('Foto actualizada', 'success');
    } catch (err) {
        console.error('[Foto] Error:', err);
        if (typeof Toast !== 'undefined') Toast.show('Error al subir foto', 'error');
    }
}

// Calcular progreso al cargar
document.addEventListener('DOMContentLoaded', () => {
    // Delay para que el form se renderice
    setTimeout(calcularProgreso, 100);

    // Recalcular al cambiar cualquier campo
    const form = document.getElementById('form-perfil-completo');
    if (form) {
        form.addEventListener('input', calcularProgreso);
        form.addEventListener('change', calcularProgreso);
    }
});

// Si el form ya está en DOM (carga lazy post-DOMContentLoaded)
if (document.getElementById('form-perfil-completo')) {
    setTimeout(calcularProgreso, 100);
    const form = document.getElementById('form-perfil-completo');
    form.addEventListener('input', calcularProgreso);
    form.addEventListener('change', calcularProgreso);
}

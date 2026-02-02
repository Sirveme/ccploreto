
window.APP_CONFIG = {
    user: {
        id: "{{ user.id }}",
        name: "{{ colegiado.apellidos_nombres if colegiado else user.user.name }}",
        matricula: "{{ colegiado.codigo_matricula if colegiado else user.public_id }}"
    },
    vapidPublicKey: "{{ vapid_public_key }}",
    wsUrl: (window.location.protocol === 'https:' ? 'wss:' : 'ws:') + '//' + window.location.host + '/ws/alerta'
};



// Inicializar
document.addEventListener('DOMContentLoaded', () => {
    Modal.initBackdropClose();
    calcularProgreso();
});

// Ver Aviso
function verAviso(el) {
    document.getElementById('aviso-titulo').textContent = el.dataset.title;
    document.getElementById('aviso-contenido').textContent = el.dataset.content;
    Modal.open('modal-aviso');
}

// Toggle Accordion
function toggleAccordion(id) {
    const acc = document.getElementById(id);
    const wasOpen = acc.classList.contains('open');
    
    // Cerrar todos
    document.querySelectorAll('.accordion').forEach(a => a.classList.remove('open'));
    
    // Abrir si estaba cerrado
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
        if (campo.value && campo.value.trim() !== '') {
            completados++;
        }
    });
    
    const porcentaje = Math.round((completados / camposRequeridos.length) * 100);
    
    document.getElementById('progress-percent').textContent = porcentaje + '%';
    document.getElementById('progress-fill').style.width = porcentaje + '%';
    
    // Actualizar estados de secciones
    actualizarEstadoSeccion('personal', ['email', 'telefono', 'direccion', 'fecha_nacimiento']);
    actualizarEstadoSeccion('estudios', ['universidad']);
    actualizarEstadoSeccion('laboral', ['situacion_laboral']);
    actualizarEstadoSeccion('familiar', ['contacto_emergencia_nombre', 'contacto_emergencia_telefono']);
}

function actualizarEstadoSeccion(seccion, campos) {
    const form = document.getElementById('form-perfil-completo');
    let completo = true;
    
    campos.forEach(nombre => {
        const campo = form.querySelector(`[name="${nombre}"]`);
        if (!campo || !campo.value || campo.value.trim() === '') {
            completo = false;
        }
    });
    
    const statusEl = document.getElementById(`status-${seccion}`);
    if (statusEl) {
        statusEl.textContent = completo ? 'Completo' : 'Pendiente';
        statusEl.className = 'accordion-status ' + (completo ? 'complete' : 'incomplete');
    }
}

// Escuchar cambios en el formulario
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
    
    // Agregar foto si hay
    const fotoInput = document.getElementById('input-foto-perfil');
    if (fotoInput.files.length > 0) {
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
            
            setTimeout(() => {
                location.reload();
            }, 1500);
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
    btn.innerHTML = enabled ? '<i class="ph ph-speaker-high"></i>' : '<i class="ph ph-speaker-slash"></i>';
    Toast.show(enabled ? 'Sonidos activados' : 'Sonidos desactivados', 'info', 2000);
}

// Generar Constancia
function generarConstancia() {
    SoundFX.play('click');
    Toast.show('Generando constancia...', 'info');
    setTimeout(() => {
        Toast.show('Función disponible próximamente', 'warning');
    }, 1000);
}

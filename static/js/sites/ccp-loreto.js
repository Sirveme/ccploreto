// ==========================================
// CCP LORETO - JAVASCRIPT PRINCIPAL
// ==========================================

// Inicialización
document.addEventListener('DOMContentLoaded', function() {    
    initParticles();
    initHeader();
    initSideMenu();
    initModals();
    initBottomNav();
    initVoiceSearch();
    initConvenios();
    initReservas();
    initTabs();
});

// ==========================================
// PARTÍCULAS CANVAS
// ==========================================

function initParticles() {
    const canvas = document.getElementById('particlesCanvas');
    if (!canvas) return;
    
    const ctx = canvas.getContext('2d');
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
    
    const particles = [];
    const particleCount = 80;
    
    class Particle {
        constructor() {
            this.x = Math.random() * canvas.width;
            this.y = Math.random() * canvas.height;
            this.size = Math.random() * 2 + 1;
            this.speedX = Math.random() * 0.5 - 0.25;
            this.speedY = Math.random() * 0.5 - 0.25;
            this.opacity = Math.random() * 0.5 + 0.2;
        }
        update() {
            this.x += this.speedX;
            this.y += this.speedY;
            if (this.x > canvas.width) this.x = 0;
            if (this.x < 0) this.x = canvas.width;
            if (this.y > canvas.height) this.y = 0;
            if (this.y < 0) this.y = canvas.height;
        }
        draw() {
            ctx.fillStyle = `rgba(212, 175, 55, ${this.opacity})`;
            ctx.beginPath();
            ctx.arc(this.x, this.y, this.size, 0, Math.PI * 2);
            ctx.fill();
        }
    }
    
    for (let i = 0; i < particleCount; i++) {
        particles.push(new Particle());
    }
    
    function animate() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        particles.forEach(particle => {
            particle.update();
            particle.draw();
        });
        
        // Conectar partículas cercanas
        for (let i = 0; i < particles.length; i++) {
            for (let j = i + 1; j < particles.length; j++) {
                const dx = particles[i].x - particles[j].x;
                const dy = particles[i].y - particles[j].y;
                const distance = Math.sqrt(dx * dx + dy * dy);
                if (distance < 120) {
                    ctx.strokeStyle = `rgba(212, 175, 55, ${0.15 * (1 - distance / 120)})`;
                    ctx.lineWidth = 1;
                    ctx.beginPath();
                    ctx.moveTo(particles[i].x, particles[i].y);
                    ctx.lineTo(particles[j].x, particles[j].y);
                    ctx.stroke();
                }
            }
        }
        requestAnimationFrame(animate);
    }
    
    animate();
    
    window.addEventListener('resize', () => {
        canvas.width = window.innerWidth;
        canvas.height = window.innerHeight;
    });
}

// ==========================================
// HEADER
// ==========================================

function initHeader() {
    const header = document.querySelector('.header');
    if (!header) return;
    
    window.addEventListener('scroll', () => {
        if (window.pageYOffset > 100) {
            header.classList.add('scrolled');
        } else {
            header.classList.remove('scrolled');
        }
    });
}

// ==========================================
// MENÚ LATERAL
// ==========================================

function initSideMenu() {
    const menuBtn = document.getElementById('menuBtn');
    const sideMenu = document.getElementById('sideMenu');
    const closeSideMenu = document.getElementById('closeSideMenu');
    const overlay = sideMenu?.querySelector('.side-menu-overlay');
    
    menuBtn?.addEventListener('click', () => {
        sideMenu?.classList.add('active');
    });
    
    closeSideMenu?.addEventListener('click', () => {
        sideMenu?.classList.remove('active');
    });
    
    overlay?.addEventListener('click', () => {
        sideMenu?.classList.remove('active');
    });
}

// ==========================================
// MODALES
// ==========================================

function initModals() {
    const modals = {
        consultas: document.getElementById('consultasModal'),
        directivos: document.getElementById('directivosModal'),
        transparencia: document.getElementById('transparenciaModal'),
        reactivacion: document.getElementById('reactivacionModal'),
        reserva: document.getElementById('reservaModal'),
        convenios: document.getElementById('conveniosModal')
    };
    
    // Botones para abrir modales
    document.querySelectorAll('[data-modal]').forEach(btn => {
        btn.addEventListener('click', () => {
            const modalName = btn.getAttribute('data-modal');
            if (modals[modalName]) {
                openModal(modals[modalName]);
            }
        });
    });
    
    // Botón consultas
    const consultasBtn = document.getElementById('consultasBtn');
    consultasBtn?.addEventListener('click', () => {
        openModal(modals.consultas);
    });
    
    // Botón reactivación hero
    const btnReactivaHero = document.getElementById('btnReactivaHero');
    btnReactivaHero?.addEventListener('click', () => {
        openModal(modals.reactivacion);
    });
    
    // Cerrar modales
    document.querySelectorAll('.modal-close-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            closeAllModals();
        });
    });
    
    // Cerrar al hacer clic en overlay
    document.querySelectorAll('.modal-overlay').forEach(overlay => {
        overlay.addEventListener('click', () => {
            closeAllModals();
        });
    });
    
    // Cerrar con ESC
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            closeAllModals();
        }
    });
}

function openModal(modal) {
    if (typeof modal === 'string') {
        modal = document.getElementById(modal);
    }
    if (modal) {
        modal.classList.add('active');
        document.body.style.overflow = 'hidden';
    }
}

function closeModal(modalId) {
    const modal = typeof modalId === 'string' ? document.getElementById(modalId) : modalId;
    if (modal) {
        modal.classList.remove('active');
        document.body.style.overflow = '';
    }
}

function closeAllModals() {
    document.querySelectorAll('.modal').forEach(modal => {
        modal.classList.remove('active');
    });
    document.body.style.overflow = '';
}

// ==========================================
// BOTTOM NAVIGATION
// ==========================================

function initBottomNav() {
    const reactivateBtn = document.getElementById('reactivateBtn');
    const reactivacionModal = document.getElementById('reactivacionModal');
    
    reactivateBtn?.addEventListener('click', () => {
        openModal(reactivacionModal);
    });
}

// ==========================================
// INTEGRACIÓN VOZ + BÚSQUEDA
// ==========================================

let voiceAssistant = null;
let searchEngine = null;

function initVoiceSearch() {
    const voiceBtn = document.getElementById('voiceBtn');
    const searchInput = document.querySelector('.search-input');
    const modalContent = document.querySelector('.modal-consultas');
    
    if (!modalContent) return;

    // Crear contenedor de resultados si no existe
    let resultsContainer = document.getElementById('searchResults');
    if (!resultsContainer) {
        resultsContainer = document.createElement('div');
        resultsContainer.id = 'searchResults';
        resultsContainer.className = 'search-results-container';
        modalContent.appendChild(resultsContainer);
    }

    // Inicializar motor de búsqueda
    if (typeof SearchEngine !== 'undefined') {
        searchEngine = new SearchEngine();
    } else {
        console.error('SearchEngine no está cargado');
        return;
    }

    // Inicializar asistente de voz
    if (typeof VoiceAssistant !== 'undefined') {
        voiceAssistant = new VoiceAssistant({
            onListeningStart: () => {
                if (voiceBtn) voiceBtn.classList.add('listening');
                showFeedback('Escuchando...');
            },
            onListeningEnd: () => {
                if (voiceBtn) voiceBtn.classList.remove('listening');
                hideFeedback();
            },
            onResult: (transcript) => {
                if (searchInput) searchInput.value = transcript;
                processVoiceQuery(transcript);
            },
            onError: (error, message) => {
                showFeedback(message, 'error');
                setTimeout(hideFeedback, 3000);
            }
        });

        // Event listener para botón de voz
        if (voiceBtn && voiceAssistant.isSupported) {
            voiceBtn.addEventListener('click', () => voiceAssistant.startListening());
        } else if (voiceBtn) {
            voiceBtn.style.opacity = '0.5';
            voiceBtn.title = 'Voz no soportada en este navegador';
        }
    }

    // Quick queries (chips)
    document.querySelectorAll('.query-chip').forEach(chip => {
        chip.addEventListener('click', () => {
            const query = chip.textContent;
            if (searchInput) searchInput.value = query;
            processVoiceQuery(query);
        });
    });

    // Enter en input
    if (searchInput) {
        searchInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                processVoiceQuery(searchInput.value);
            }
        });
    }
}

async function processVoiceQuery(query) {
    if (!query.trim() || !searchEngine) return;
    
    const intent = searchEngine.detectIntent(query);
    const resultsContainer = document.getElementById('searchResults');
    
    console.log('Query:', query);
    console.log('Intención detectada:', intent);
    
    switch (intent.type) {
        case 'direct_dni':
        case 'direct_matricula':
            // Búsqueda directa con DNI o matrícula
            await executeHabilidadSearch(intent.value);
            break;
            
        case 'consulta_habilidad':
            showDNIInput('Ingresa tu DNI o número de matrícula:');
            voiceAssistant?.speak('Por favor, ingresa tu DNI o número de matrícula.');
            break;
            
        case 'consulta_deuda':
            showDNIInput('Para consultar tu deuda, ingresa tu DNI o matrícula:');
            searchEngine.setConversationState('consulta_deuda', 'pedir_dni');
            voiceAssistant?.speak('Para consultar tu deuda, ingresa tu DNI.');
            break;
            
        case 'directivos':
            openModal('directivosModal');
            closeModal('consultasModal');
            break;
            
        case 'convenios':
            openModal('conveniosModal');
            closeModal('consultasModal');
            break;
            
        case 'requisitos_colegiarse':
        case 'alquiler':
            showStaticInfo(intent.type);
            break;
            
        default:
            showGenericResponse(query);
    }
    
    if (resultsContainer) {
        resultsContainer.classList.add('active');
    }
}

function showDNIInput(message) {
    const resultsContainer = document.getElementById('searchResults');
    if (!resultsContainer) return;
    
    resultsContainer.innerHTML = `
        <div class="dni-input-section">
            <p class="dni-prompt">${message}</p>
            <div class="dni-input-wrapper">
                <input type="text" id="dniInput" class="dni-input" 
                       placeholder="Ej: 12345678 o 10-0649" maxlength="15" autocomplete="off">
                <button id="btnBuscarDNI" class="btn-buscar-dni">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <circle cx="11" cy="11" r="8"></circle>
                        <path d="m21 21-4.35-4.35"></path>
                    </svg>
                </button>
            </div>
            <div id="dniResult"></div>
        </div>
    `;
    resultsContainer.classList.add('active');
    
    const dniInput = document.getElementById('dniInput');
    const btnBuscar = document.getElementById('btnBuscarDNI');
    
    setTimeout(() => dniInput?.focus(), 100);
    
    const handleSearch = () => {
        const value = dniInput?.value.trim();
        if (value) executeHabilidadSearch(value);
    };
    
    dniInput?.addEventListener('keypress', (e) => { 
        if (e.key === 'Enter') handleSearch(); 
    });
    btnBuscar?.addEventListener('click', handleSearch);
}

async function executeHabilidadSearch(query) {
    // Asegurar que existe el contenedor de resultados
    let resultsContainer = document.getElementById('searchResults');
    let dniResult = document.getElementById('dniResult');
    
    if (!dniResult) {
        // Crear estructura si no existe
        if (resultsContainer) {
            resultsContainer.innerHTML = `
                <div class="dni-input-section">
                    <div id="dniResult"></div>
                </div>
            `;
            resultsContainer.classList.add('active');
            dniResult = document.getElementById('dniResult');
        }
    }
    
    if (!dniResult) {
        console.error('No se pudo crear el contenedor de resultados');
        return;
    }
    
    // Mostrar loading
    dniResult.innerHTML = `
        <div class="search-loading">
            <div class="search-spinner"></div>
            <span>Consultando...</span>
        </div>
    `;
    
    // Ejecutar búsqueda
    const result = await searchEngine.searchHabilidad(query);
    console.log('Resultado de búsqueda:', result);
    
    if (!result.success) {
        dniResult.innerHTML = `
            <div class="result-card result-error">
                <div class="result-icon">⚠️</div>
                <p class="result-message">${result.error}</p>
            </div>
        `;
        voiceAssistant?.speak('Ocurrió un error. Intenta de nuevo.');
        return;
    }
    
    if (!result.found) {
        dniResult.innerHTML = `
            <div class="result-card result-not-found">
                <div class="result-icon">🔍</div>
                <p class="result-message">No se encontró ningún colegiado.</p>
                <p class="result-hint">Verifica el número e intenta nuevamente.</p>
            </div>
        `;
        voiceAssistant?.speak('No se encontró ningún colegiado con ese número.');
        return;
    }
    
    // Procesar resultado exitoso
    const d = result.data;
    const esHabil = d.condicion === 'habil' || d.condicion === 'vitalicio';
    const cardClass = esHabil ? 'result-habil' : 'result-inhabil';
    const icon = esHabil ? '✅' : '❌';
    
    // Determinar texto de estado
    let statusText = d.condicion_texto;
    let statusDetail = '';
    
    if (d.condicion === 'vitalicio') { 
        statusText = 'HÁBIL'; 
        statusDetail = '(Vitalicio)'; 
    } else if (d.condicion === 'fallecido') { 
        statusText = 'INHÁBIL'; 
        statusDetail = '(Fallecido)'; 
    }
    
    // Construir HTML del resultado
    dniResult.innerHTML = `
        <div class="result-card ${cardClass}">
            <div class="result-icon">${icon}</div>
            <div class="result-status">
                ${statusText}
                ${statusDetail ? `<span class="status-detail">${statusDetail}</span>` : ''}
            </div>
            <div class="result-data">
                <div class="data-row">
                    <span class="data-label">Matrícula</span>
                    <span class="data-value">${d.codigo_matricula}</span>
                </div>
                <div class="data-row">
                    <span class="data-label">Nombre</span>
                    <span class="data-value">${d.apellidos_nombres}</span>
                </div>
                ${d.fecha_actualizacion ? `
                <div class="data-row">
                    <span class="data-label">Actualizado</span>
                    <span class="data-value">${d.fecha_actualizacion}</span>
                </div>
                ` : ''}
            </div>
            ${!esHabil ? `
            <a href="#" class="btn-reactivar" onclick="openModal('reactivacionModal'); closeModal('consultasModal'); return false;">
                Reactiva tu matrícula →
            </a>
            ` : ''}
        </div>
    `;
    
    // Respuesta por voz
    const nombre = d.apellidos_nombres.split(' ').slice(0, 2).join(' ');
    if (esHabil) {
        voiceAssistant?.speak(`${nombre}, estás HÁBIL.`);
    } else {
        voiceAssistant?.speak(`${nombre}, actualmente estás INHÁBIL.`);
    }
}

function showStaticInfo(type) {
    const info = SearchEngine.INFO[type];
    const resultsContainer = document.getElementById('searchResults');
    
    if (!info || !resultsContainer) return;
    
    const itemsHtml = info.items.map(item => 
        typeof item === 'string' 
            ? `<li>${item}</li>` 
            : `<li><strong>${item.name}</strong> - ${item.capacity} personas</li>`
    ).join('');
    
    resultsContainer.innerHTML = `
        <div class="static-info-card">
            <h3>📋 ${info.title}</h3>
            <ul>${itemsHtml}</ul>
            <p class="info-note">Contacto: <strong>${info.contact}</strong></p>
        </div>
    `;
    resultsContainer.classList.add('active');
}

function showGenericResponse(query) {
    const resultsContainer = document.getElementById('searchResults');
    if (!resultsContainer) return;
    
    resultsContainer.innerHTML = `
        <div class="result-card result-info">
            <div class="result-icon">💬</div>
            <p class="result-message">No encontré información sobre "${query}".</p>
            <p class="result-hint">Prueba: "Estado de colegiatura", "Requisitos para colegiarse"</p>
        </div>
    `;
    resultsContainer.classList.add('active');
}

// Feedback visual (toast)
function showFeedback(message, type = 'info') {
    let feedback = document.querySelector('.voice-feedback');
    if (!feedback) {
        feedback = document.createElement('div');
        feedback.className = 'voice-feedback';
        document.body.appendChild(feedback);
    }
    feedback.textContent = message;
    feedback.classList.remove('hide');
}

function hideFeedback() {
    const feedback = document.querySelector('.voice-feedback');
    if (feedback) feedback.classList.add('hide');
}

// ==========================================
// CONVENIOS - FILTROS
// ==========================================

function initConvenios() {
    const tabBtns = document.querySelectorAll('.convenios-tabs .tab-btn');
    const convenioCards = document.querySelectorAll('.convenio-card');
    
    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const category = btn.getAttribute('data-category');
            
            // Actualizar botones activos
            tabBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            
            // Filtrar cards
            convenioCards.forEach(card => {
                const cardCategory = card.getAttribute('data-category');
                if (category === 'todos' || cardCategory === category) {
                    card.style.display = 'block';
                } else {
                    card.style.display = 'none';
                }
            });
        });
    });
}

// ==========================================
// RESERVAS
// ==========================================

function initReservas() {
    const reservarBtns = document.querySelectorAll('.btn-reservar');
    const reservaModal = document.getElementById('reservaModal');
    const ambienteSelect = document.getElementById('ambienteSelect');
    const duracionInput = document.getElementById('duracion');
    const totalReserva = document.getElementById('totalReserva');
    
    reservarBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const ambiente = btn.getAttribute('data-ambiente');
            openModal(reservaModal);
            
            // Seleccionar ambiente
            if (ambienteSelect) {
                ambienteSelect.value = ambiente;
                calcularTotal();
            }
        });
    });
    
    // Calcular total
    function calcularTotal() {
        const precios = {
            'piscina': 50,
            'futbol': 40,
            'voley': 35
        };
        
        const ambiente = ambienteSelect?.value || 'piscina';
        const duracion = parseInt(duracionInput?.value) || 1;
        const total = precios[ambiente] * duracion;
        
        if (totalReserva) {
            totalReserva.textContent = `S/ ${total}`;
        }
    }
    
    ambienteSelect?.addEventListener('change', calcularTotal);
    duracionInput?.addEventListener('input', calcularTotal);
    
    // Confirmar reserva
    const btnConfirmar = document.querySelector('.btn-confirmar-reserva');
    btnConfirmar?.addEventListener('click', () => {
        const fecha = document.getElementById('fechaReserva')?.value;
        const hora = document.getElementById('horaInicio')?.value;
        
        if (!fecha || !hora) {
            alert('Por favor completa todos los campos');
            return;
        }
        
        alert('Reserva confirmada. Te contactaremos pronto para confirmar el pago.');
        closeAllModals();
    });
}

// ==========================================
// TABS (Reactivación y Transparencia)
// ==========================================

function initTabs() {
    document.querySelectorAll('.tabs').forEach(tabsContainer => {
        const tabs = tabsContainer.querySelectorAll('.tab');
        const contents = tabsContainer.parentElement.querySelectorAll('.tab-content');
        
        tabs.forEach(tab => {
            tab.addEventListener('click', () => {
                const targetId = tab.getAttribute('data-tab');
                
                // Actualizar tabs activos
                tabs.forEach(t => t.classList.remove('active'));
                tab.classList.add('active');
                
                // Mostrar contenido correspondiente
                contents.forEach(content => {
                    if (content.id === targetId) {
                        content.classList.add('active');
                    } else {
                        content.classList.remove('active');
                    }
                });

                // Dentro del forEach de tabs, después de mostrar el contenido:
                if (targetId === 'pagar') {
                    console.log('Tab pagar clickeado');
                    const container = document.getElementById('formulario-pago-container');
                    console.log('Container:', container);
                    
                    if (container && !container.dataset.loaded) {
                        console.log('Iniciando fetch...');
                        fetch('/pagos/formulario')
                            .then(r => {
                                console.log('Response status:', r.status);
                                return r.text();
                            })
                            .then(html => {
                                console.log('HTML recibido, longitud:', html.length);
                                const pagarDiv = document.getElementById('pagar');
                                pagarDiv.innerHTML = html;
                                
                                // Ejecutar scripts inyectados
                                pagarDiv.querySelectorAll('script').forEach(oldScript => {
                                    const newScript = document.createElement('script');
                                    newScript.textContent = oldScript.textContent;
                                    oldScript.parentNode.replaceChild(newScript, oldScript);
                                });
                                
                                container.dataset.loaded = 'true';
                            })
                            .catch(e => {
                                console.error('Error fetch:', e);
                                container.innerHTML = '<p class="text-red-400">Error al cargar formulario</p>';
                            });
                    } else {
                        console.log('Ya cargado o container no existe');
                    }
                }

            });
        });
    });
}

// ==========================================
// SMOOTH SCROLL
// ==========================================

document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function (e) {
        const href = this.getAttribute('href');
        if (href === '#' || href.length <= 1) return;
        
        e.preventDefault();
        const target = document.querySelector(href);
        if (target) {
            target.scrollIntoView({
                behavior: 'smooth',
                block: 'start'
            });
        }
    });
});

// ==========================================
// LAZY LOADING VIDEOS
// ==========================================

document.querySelectorAll('.video-placeholder').forEach(placeholder => {
    placeholder.addEventListener('click', function() {
        const wrapper = this.parentElement;
        const iframe = wrapper.querySelector('iframe');
        const videoUrl = iframe.getAttribute('data-video-url');
        
        if (videoUrl) {
            iframe.src = videoUrl;
            this.style.display = 'none';
        } else {
            alert('URL del video no configurada');
        }
    });
});

// ==========================================
// FUNCIÓN GLOBAL PARA ABRIR MODALES
// ==========================================

window.abrirModal = function(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.add('active');
        document.body.style.overflow = 'hidden';
    } else {
        console.error("Modal no encontrado:", modalId);
        alert("Esta sección estará disponible muy pronto.");
    }
};

// Exponer funciones globalmente para uso en HTML
window.openModal = openModal;
window.closeModal = closeModal;
window.closeAllModals = closeAllModals;
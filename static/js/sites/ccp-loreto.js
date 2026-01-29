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

// Partículas Canvas
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

// Header
function initHeader() {
    const header = document.querySelector('.header');
    
    window.addEventListener('scroll', () => {
        if (window.pageYOffset > 100) {
            header.classList.add('scrolled');
        } else {
            header.classList.remove('scrolled');
        }
    });
}

// Menú Lateral
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

// Modals
function initModals() {
    const modals = {
        consultas: document.getElementById('consultasModal'),
        directivos: document.getElementById('directivosModal'),
        transparencia: document.getElementById('transparenciaModal'),
        reactivacion: document.getElementById('reactivacionModal'),
        reserva: document.getElementById('reservaModal')
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
    if (modal) {
        modal.classList.add('active');
        document.body.style.overflow = 'hidden';
    }
}

function closeAllModals() {
    document.querySelectorAll('.modal').forEach(modal => {
        modal.classList.remove('active');
    });
    document.body.style.overflow = '';
}

// Bottom Navigation
function initBottomNav() {
    const reactivateBtn = document.getElementById('reactivateBtn');
    const reactivacionModal = document.getElementById('reactivacionModal');
    
    reactivateBtn?.addEventListener('click', () => {
        openModal(reactivacionModal);
    });
}

// Voice Search
function initVoiceSearch() {
    const voiceBtn = document.getElementById('voiceBtn');
    const searchInput = document.querySelector('.search-input');
    
    if (!voiceBtn || !searchInput) return;

    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    
    if (!SpeechRecognition) {
        console.log('Reconocimiento de voz no soportado');
        return;
    }

    const recognition = new SpeechRecognition();
    recognition.lang = 'es-PE';
    recognition.continuous = false;
    recognition.interimResults = false;

    voiceBtn.addEventListener('click', () => {
        voiceBtn.classList.add('active');
        recognition.start();
    });

    recognition.onresult = (event) => {
        const transcript = event.results[0][0].transcript;
        searchInput.value = transcript;
        voiceBtn.classList.remove('active');
        processSearch(transcript);
    };

    recognition.onerror = () => {
        voiceBtn.classList.remove('active');
    };

    recognition.onend = () => {
        voiceBtn.classList.remove('active');
    };

    // Quick queries
    document.querySelectorAll('.query-chip').forEach(chip => {
        chip.addEventListener('click', () => {
            const query = chip.textContent;
            searchInput.value = query;
            processSearch(query);
        });
    });

    // Enter en input
    searchInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            processSearch(searchInput.value);
        }
    });
}

function processSearch(query) {
    const searchResults = {
        'estado de colegiatura': '/consulta-de-habilidad/',
        'requisitos para colegiarse': '/colegiados/',
        'alquiler de ambientes': '/alquiler-de-ambientes/',
        'próximos eventos': '/#eventos',
        'comunicados recientes': '/#comunicados',
        'directivos actuales': '/consejo-directivo/'
    };

    const queryLower = query.toLowerCase();
    
    for (const [key, url] of Object.entries(searchResults)) {
        if (queryLower.includes(key)) {
            window.location.href = url;
            return;
        }
    }
    
    alert(`Buscando: "${query}"`);
}

// Convenios - Filtros
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

// Reservas
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

// Tabs (Reactivación y Transparencia)
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
            });
        });
    });
}

// Smooth scroll
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

// Lazy loading para videos
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




/* --- LÓGICA CARRUSEL --- */
let currentSlide = 0;
const track = document.getElementById('carousel-track');
const slides = document.querySelectorAll('.carousel-slide'); // Selector más robusto
const totalSlides = slides.length;
const dots = document.querySelectorAll('.dot');
let autoPlayInterval;

function updateCarousel() {
    // Mover horizontalmente
    track.style.transform = `translateX(-${currentSlide * 100}%)`;
    
    // Actualizar puntos
    dots.forEach((dot, index) => {
        if (index === currentSlide) dot.classList.add('active');
        else dot.classList.remove('active');
    });
}

function moveSlide(direction) {
    currentSlide = (currentSlide + direction + totalSlides) % totalSlides;
    updateCarousel();
    resetTimer();
}

function goToSlide(index) {
    currentSlide = index;
    updateCarousel();
    resetTimer();
}

function startTimer() {
    autoPlayInterval = setInterval(() => moveSlide(1), 5000);
}

function resetTimer() {
    clearInterval(autoPlayInterval);
    startTimer();
}

// Función global unificada para abrir modales (Desde Slider o Botones)
window.abrirModal = function(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        // Usamos la misma lógica que initModals
        modal.classList.add('active');
        document.body.style.overflow = 'hidden';
    } else {
        console.error("Modal no encontrado:", modalId);
        // Fallback elegante
        alert("Esta sección estará disponible muy pronto.");
    }
};

// Iniciar al cargar
if(totalSlides > 0) {
    startTimer();
}
/**
 * Search Engine Module
 * ====================
 * Motor de búsqueda inteligente con detección de intenciones
 * Para el Colegio de Contadores Públicos de Loreto
 */

class SearchEngine {
    constructor(options = {}) {
        this.options = {
            baseUrl: '',
            orgId: null,
            ...options
        };
        
        this.conversationState = {
            action: null,
            step: null,
            data: {}
        };
    }
    
    // ==========================================
    // NORMALIZACIÓN DE INPUT HABLADO
    // ==========================================
    
    /**
     * Normaliza texto dictado a formato de búsqueda
     * "cero cinco dos cero nueve nueve uno ocho" → "05209918"
     * "052 099 18" → "05209918"
     */
    static normalizeSpokenInput(text) {
        if (!text) return '';
        
        let normalized = text.toLowerCase().trim();
        
        // Mapeo de palabras a números
        const wordToNumber = {
            'cero': '0', 'uno': '1', 'una': '1', 'dos': '2', 'tres': '3', 
            'cuatro': '4', 'cinco': '5', 'seis': '6', 'siete': '7', 
            'ocho': '8', 'nueve': '9'
        };
        
        // Reemplazar palabras por números
        for (const [word, num] of Object.entries(wordToNumber)) {
            normalized = normalized.replace(new RegExp(`\\b${word}\\b`, 'gi'), num);
        }
        
        // Si después de reemplazar palabras queda solo números y espacios
        if (/^[\d\s\-\.]+$/.test(normalized)) {
            // Eliminar espacios, guiones y puntos
            normalized = normalized.replace(/[\s\-\.]+/g, '');
            
            // Si parece DNI (7-8 dígitos), asegurar 8 dígitos
            if (/^\d{7,8}$/.test(normalized)) {
                return normalized.padStart(8, '0');
            }
            
            // Si parece matrícula sin guión (5-6 dígitos empezando con 10)
            if (/^10\d{3,4}$/.test(normalized)) {
                return normalized.slice(0, 2) + '-' + normalized.slice(2);
            }
        }
        
        return text.trim();
    }

    // ==========================================
    // DETECCIÓN DE INTENCIONES
    // ==========================================
    
    static INTENT_PATTERNS = {
        consulta_habilidad: {
            keywords: ['hábil', 'habil', 'estado', 'colegiatura', 'habilitado', 'verificar', 'activo', 'suspendido'],
            description: 'Consultar estado de habilidad'
        },
        consulta_deuda: {
            keywords: ['deuda', 'debo', 'pagar', 'cuota', 'pendiente', 'saldo', 'cuánto'],
            description: 'Consultar deuda pendiente'
        },
        registrar_pago: {
            keywords: ['pago', 'pagué', 'pague', 'voucher', 'deposité', 'transferí', 'yape', 'plin'],
            description: 'Registrar un pago'
        },
        requisitos_colegiarse: {
            keywords: ['requisitos', 'colegiar', 'inscribir', 'nuevo'],
            description: 'Requisitos para colegiarse'
        },
        directivos: {
            keywords: ['directivo', 'directiva', 'decano', 'junta', 'consejo', 'autoridades'],
            description: 'Ver directivos actuales'
        },
        eventos: {
            keywords: ['evento', 'actividad', 'capacitación', 'curso', 'taller', 'seminario'],
            description: 'Ver próximos eventos'
        },
        comunicados: {
            keywords: ['comunicado', 'aviso', 'noticia', 'anuncio', 'último'],
            description: 'Ver comunicados recientes'
        },
        convenios: {
            keywords: ['convenio', 'beneficio', 'descuento', 'alianza', 'promoción'],
            description: 'Ver convenios disponibles'
        },
        alquiler: {
            keywords: ['alquiler', 'ambiente', 'auditorio', 'sala', 'local', 'reservar'],
            description: 'Alquiler de ambientes'
        },
        // En search-engine.js, agregar a INTENT_PATTERNS:
        pagar: {
            keywords: ['pagar', 'pago', 'reactivar', 'cuota', 'deuda', 'debo'],
            description: 'Ir a formulario de pago'
        }
    };
    
    detectIntent(query) {
        const queryLower = query.toLowerCase().trim();
        const normalized = SearchEngine.normalizeSpokenInput(query);
        
        // Verificar si parece un DNI o matrícula directamente
        if (this.looksLikeDNI(normalized)) {
            return {
                type: 'direct_dni',
                value: normalized,
                confidence: 0.95
            };
        }
        
        if (this.looksLikeMatricula(normalized)) {
            return {
                type: 'direct_matricula',
                value: normalized,
                confidence: 0.95
            };
        }
        
        // Buscar coincidencias con patrones de intención
        const results = [];
        
        for (const [intentName, pattern] of Object.entries(SearchEngine.INTENT_PATTERNS)) {
            const matches = pattern.keywords.filter(kw => queryLower.includes(kw));
            
            if (matches.length > 0) {
                results.push({
                    type: intentName,
                    confidence: matches.length / pattern.keywords.length,
                    matches: matches,
                    pattern: pattern
                });
            }
        }
        
        results.sort((a, b) => b.confidence - a.confidence);
        
        if (results.length > 0) {
            return results[0];
        }
        
        return {
            type: 'unknown',
            query: query,
            confidence: 0
        };
    }
    
    // ==========================================
    // VALIDACIONES
    // ==========================================
    
    looksLikeDNI(text) {
        const cleaned = text.replace(/\s/g, '');
        return /^\d{7,8}$/.test(cleaned);
    }
    
    looksLikeMatricula(text) {
        const cleaned = text.replace(/\s/g, '').toUpperCase();
        return /^\d{2}-\d{3,4}$/.test(cleaned);
    }
    
    // ==========================================
    // EJECUCIÓN DE BÚSQUEDAS
    // ==========================================
    
    async searchHabilidad(query) {
        const normalizedQuery = SearchEngine.normalizeSpokenInput(query);
        
        try {
            const response = await fetch(`/consulta/habilidad/verificar?q=${encodeURIComponent(normalizedQuery)}`);
            const data = await response.json();
            
            if (!response.ok) {
                throw new Error(data.detail || 'Error en la consulta');
            }
            
            return {
                success: true,
                found: data.encontrado,
                data: data.datos || null,
                message: data.mensaje || null
            };
        } catch (error) {
            return {
                success: false,
                error: error.message
            };
        }
    }
    
    async searchDeuda(query) {
        return {
            success: true,
            found: false,
            message: 'Funcionalidad en desarrollo'
        };
    }
    
    // ==========================================
    // ESTADO DE CONVERSACIÓN
    // ==========================================
    
    setConversationState(action, step, data = {}) {
        this.conversationState = { action, step, data };
    }
    
    clearConversationState() {
        this.conversationState = { action: null, step: null, data: {} };
    }
    
    getConversationState() {
        return { ...this.conversationState };
    }
    
    // ==========================================
    // INFORMACIÓN ESTÁTICA
    // ==========================================
    
    static INFO = {
        requisitos_colegiarse: {
            title: 'Requisitos para Colegiarse',
            items: [
                'Título profesional de Contador Público',
                'Copia de DNI vigente',
                '2 fotos tamaño pasaporte',
                'Constancia de no adeudar a otro Colegio',
                'Pago de derecho de inscripción'
            ],
            contact: '979 169 813'
        },
        alquiler: {
            title: 'Alquiler de Ambientes',
            items: [
                { name: 'Auditorio Principal', capacity: 150 },
                { name: 'Sala de Reuniones', capacity: 30 },
                { name: 'Aulas', capacity: 40 }
            ],
            contact: '979 169 813'
        }
    };
    
    getStaticInfo(type) {
        return SearchEngine.INFO[type] || null;
    }
}

// Exportar para uso global
window.SearchEngine = SearchEngine;
"""
AI Knowledge Base - Sistema RAG para ColegiosPro
app/models/ai_knowledge.py

Modelos y utilidades para la base de conocimiento
"""

from sqlalchemy import Column, Integer, String, Text, Boolean, Float, JSON, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime, timezone

# Si usas el Base de tu app:
# from app.database import Base


# ============================================================
# MODELO: Base de Conocimiento
# ============================================================

"""
CREATE TABLE ai_knowledge_base (
    id SERIAL PRIMARY KEY,
    organization_id INTEGER REFERENCES organizations(id),
    
    -- Clasificación
    categoria VARCHAR(50) NOT NULL,      -- 'tramites', 'finanzas', 'normativa', 'faq', 'cursos'
    subcategoria VARCHAR(100),           -- 'constancias', 'cuotas', 'estatutos', etc.
    tags TEXT[],                         -- ['habilidad', 'certificado', 'pago']
    
    -- Contenido
    pregunta TEXT NOT NULL,              -- Pregunta o trigger que activa esta respuesta
    keywords TEXT[],                     -- Palabras clave para búsqueda
    respuesta_texto TEXT,                -- Respuesta en texto plano
    respuesta_card JSONB,                -- Respuesta en formato card (ver ejemplos abajo)
    
    -- Fuentes y referencias
    fuente VARCHAR(255),                 -- 'Estatuto Art. 15', 'Reglamento 2024'
    base_legal TEXT,                     -- Cita textual de la norma
    url_referencia VARCHAR(500),         -- Link a documento completo
    
    -- Metadatos
    prioridad INTEGER DEFAULT 5,         -- 1-10, mayor = más relevante
    veces_consultado INTEGER DEFAULT 0,
    rating_promedio FLOAT DEFAULT 0,
    
    -- Control
    activo BOOLEAN DEFAULT true,
    requiere_auth BOOLEAN DEFAULT false, -- Si requiere estar logueado
    solo_directivos BOOLEAN DEFAULT false,
    
    -- Auditoría
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    created_by INTEGER REFERENCES members(id)
);

CREATE INDEX idx_kb_org ON ai_knowledge_base(organization_id);
CREATE INDEX idx_kb_categoria ON ai_knowledge_base(categoria);
CREATE INDEX idx_kb_keywords ON ai_knowledge_base USING GIN(keywords);
CREATE INDEX idx_kb_tags ON ai_knowledge_base USING GIN(tags);
"""


# ============================================================
# EJEMPLOS DE RESPUESTAS EN FORMATO CARD
# ============================================================

EJEMPLO_CARDS = {
    
    # ========== CARD TIPO ARTÍCULO ==========
    "constancia_habilidad": {
        "type": "article",
        "category": "Trámites",
        "title": "Constancia de Habilidad Profesional",
        "description": "La constancia de habilidad certifica que el profesional está habilitado para ejercer. Se genera automáticamente cuando estás al día en tus cuotas.",
        "icon": "certificate",
        "source": {
            "name": "Reglamento CCPL",
            "icon": "book-open",
            "verified": True
        },
        "citation": {
            "text": "Todo colegiado en ejercicio deberá mantener su condición de hábil, la cual se acredita mediante la constancia correspondiente.",
            "source": "Estatuto CCPL, Art. 45"
        },
        "tip": {
            "label": "Tip rápido",
            "text": "Puedes descargar tu constancia directamente desde el Dashboard → Certificados. Se genera en PDF con código QR de verificación."
        },
        "related": [
            {"title": "¿Cómo pagar mis cuotas?", "icon": "credit-card"},
            {"title": "Vigencia del certificado", "icon": "calendar"}
        ]
    },
    
    # ========== CARD TIPO PASOS ==========
    "como_pagar": {
        "type": "steps",
        "category": "Pagos",
        "title": "¿Cómo pagar mis cuotas?",
        "description": "Tienes varias opciones para ponerte al día:",
        "steps": [
            {
                "title": "Yape o Plin",
                "description": "Escanea el QR o transfiere al 987-654-321. Sube tu voucher en el sistema."
            },
            {
                "title": "Transferencia Bancaria",
                "description": "BCP Cta. Cte. 123-456789-0-12. Envía el comprobante por el sistema."
            },
            {
                "title": "Presencial",
                "description": "En nuestras oficinas de Lunes a Viernes, 8am-1pm y 3pm-6pm."
            }
        ],
        "tip": "Los pagos por Yape/Plin se validan en menos de 24 horas. ¡Es la forma más rápida!",
        "source": "Tesorería CCPL"
    },
    
    # ========== CARD TIPO DESTACADO ==========
    "beneficio_aniversario": {
        "type": "featured",
        "category": "Beneficio Activo",
        "title": "🎉 60 Aniversario CCPL - 50% de Descuento",
        "description": "Por nuestro aniversario, todos los colegiados con deuda pueden regularizarse con 50% de descuento en cuotas atrasadas. ¡Válido hasta el 28 de febrero!",
        "icon": "confetti",
        "source": {
            "name": "Junta Directiva",
            "verified": True
        },
        "tip": {
            "label": "¿Cómo aprovecharlo?",
            "text": "El descuento se aplica automáticamente al generar tu estado de cuenta. Solo paga el monto con descuento y sube tu voucher."
        },
        "warning": "Promoción válida solo para cuotas generadas antes del 2024. No incluye multas ni inscripciones."
    },
    
    # ========== CARD TIPO MÉTRICA ==========
    "estado_cuenta": {
        "type": "metric",
        "icon": "wallet",
        "color": "orange",
        "value": "S/ 240.00",
        "label": "Tu deuda actual",
        "trend": None
    },
    
    # ========== CARD MINI (enlaces rápidos) ==========
    "link_pagar": {
        "type": "mini",
        "icon": "credit-card",
        "title": "Ir a Mis Pagos",
        "subtitle": "Ver deuda y pagar ahora",
        "url": "/dashboard#pagos"
    },
    
    # ========== RESPUESTA COMPUESTA (múltiples cards) ==========
    "consulta_deuda_completa": {
        "cards": [
            {
                "type": "metric",
                "icon": "wallet",
                "color": "red",
                "value": "S/ 480.00",
                "label": "Deuda total (6 meses)"
            },
            {
                "type": "article",
                "category": "Tu situación",
                "title": "Tienes 6 cuotas pendientes",
                "description": "Corresponden al periodo Agosto 2024 - Enero 2025. Con el beneficio de aniversario, podrías pagar solo S/ 240.00",
                "icon": "info",
                "tip": "Recomendación: Aprovecha el descuento del 50% antes del 28 de febrero."
            },
            {
                "type": "mini",
                "icon": "credit-card",
                "title": "Pagar ahora",
                "subtitle": "Con descuento de aniversario",
                "url": "/pagar"
            }
        ]
    },
    
    # ========== NORMATIVA / LEGAL ==========
    "que_es_inhabilidad": {
        "type": "featured",
        "category": "Normativa",
        "title": "¿Qué significa estar Inhábil?",
        "description": "La condición de inhábil impide ejercer la profesión de manera legal. Según nuestro estatuto, un colegiado pasa a inhábil cuando acumula más de 3 meses de cuotas impagas.",
        "icon": "warning-circle",
        "citation": {
            "icon": "scales",
            "text": "El colegiado que mantenga deudas por más de tres (3) meses consecutivos será declarado INHÁBIL, quedando suspendido en el ejercicio profesional hasta regularizar su situación.",
            "source": "Estatuto CCPL, Art. 52"
        },
        "warning": "Ejercer la profesión estando inhábil puede acarrear sanciones administrativas y legales.",
        "tip": {
            "label": "¿Cómo recuperar la habilidad?",
            "text": "Simplemente ponte al día con tus cuotas. El sistema actualiza tu estado automáticamente en 24 horas."
        }
    },
    
    # ========== CURSO / CAPACITACIÓN ==========
    "curso_niif": {
        "type": "featured",
        "category": "Capacitación",
        "title": "Curso: Actualización NIIF 2025",
        "description": "Domina los cambios en las Normas Internacionales de Información Financiera. 20 horas certificadas.",
        "image": "/static/img/cursos/niif-2025.jpg",
        "source": {
            "name": "Comisión de Capacitación",
            "verified": True
        },
        "citation": {
            "icon": "graduation-cap",
            "text": "Incluye certificado válido para horas de capacitación continua requeridas por SUNAT.",
            "source": "Resolución SMV N° 011-2012"
        },
        "tip": {
            "label": "Beneficio para colegiados",
            "text": "Colegiados hábiles tienen 30% de descuento. Precio regular S/180, tú pagas S/126."
        },
        "related": [
            {"title": "Ver todos los cursos", "icon": "books", "url": "/cursos"},
            {"title": "Mis certificados", "icon": "certificate", "url": "/dashboard#certificados"}
        ]
    }
}


# ============================================================
# FUNCIÓN: Buscar en base de conocimiento
# ============================================================

def buscar_conocimiento(db, org_id: int, query: str, limit: int = 5):
    """
    Busca en la base de conocimiento usando keywords
    Retorna las respuestas más relevantes
    """
    from sqlalchemy import text
    
    # Normalizar query
    query_normalized = query.lower().strip()
    words = query_normalized.split()
    
    # Buscar por keywords (simple, sin embeddings)
    sql = text("""
        SELECT 
            id,
            categoria,
            pregunta,
            respuesta_texto,
            respuesta_card,
            fuente,
            base_legal,
            prioridad,
            (
                -- Score simple basado en coincidencias
                CASE WHEN LOWER(pregunta) LIKE :query_like THEN 10 ELSE 0 END +
                CARDINALITY(ARRAY(SELECT unnest(keywords) INTERSECT SELECT unnest(:words::text[]))) * 5 +
                prioridad
            ) as score
        FROM ai_knowledge_base
        WHERE organization_id = :org_id
          AND activo = true
          AND (
              LOWER(pregunta) LIKE :query_like
              OR keywords && :words::text[]
              OR tags && :words::text[]
          )
        ORDER BY score DESC
        LIMIT :limit
    """)
    
    results = db.execute(sql, {
        "org_id": org_id,
        "query_like": f"%{query_normalized}%",
        "words": words,
        "limit": limit
    }).fetchall()
    
    return results


def obtener_respuesta_card(db, org_id: int, query: str):
    """
    Obtiene la mejor respuesta en formato card
    """
    resultados = buscar_conocimiento(db, org_id, query, limit=1)
    
    if resultados:
        resultado = resultados[0]
        if resultado.respuesta_card:
            return resultado.respuesta_card
        elif resultado.respuesta_texto:
            # Convertir texto a card básica
            return {
                "type": "article",
                "title": resultado.pregunta[:50] + "..." if len(resultado.pregunta) > 50 else resultado.pregunta,
                "description": resultado.respuesta_texto,
                "source": resultado.fuente,
                "citation": resultado.base_legal if resultado.base_legal else None
            }
    
    return None


# ============================================================
# DATOS INICIALES PARA CCPL
# ============================================================

CONOCIMIENTO_INICIAL_CCPL = [
    {
        "categoria": "tramites",
        "subcategoria": "constancias",
        "pregunta": "¿Cómo obtengo mi constancia de habilidad?",
        "keywords": ["constancia", "habilidad", "certificado", "habil"],
        "tags": ["tramites", "certificados"],
        "respuesta_card": EJEMPLO_CARDS["constancia_habilidad"],
        "fuente": "Reglamento CCPL",
        "prioridad": 9
    },
    {
        "categoria": "finanzas",
        "subcategoria": "pagos",
        "pregunta": "¿Cómo puedo pagar mis cuotas?",
        "keywords": ["pagar", "pago", "cuota", "cuotas", "yape", "transferencia", "deposito"],
        "tags": ["pagos", "finanzas"],
        "respuesta_card": EJEMPLO_CARDS["como_pagar"],
        "fuente": "Tesorería CCPL",
        "prioridad": 10
    },
    {
        "categoria": "normativa",
        "subcategoria": "habilidad",
        "pregunta": "¿Qué significa estar inhábil?",
        "keywords": ["inhabil", "inhabilitado", "suspension", "suspendido", "ejercer"],
        "tags": ["normativa", "habilidad"],
        "respuesta_card": EJEMPLO_CARDS["que_es_inhabilidad"],
        "fuente": "Estatuto CCPL",
        "base_legal": "Estatuto CCPL, Art. 52",
        "prioridad": 8
    },
    {
        "categoria": "beneficios",
        "subcategoria": "promociones",
        "pregunta": "¿Hay algún descuento o beneficio activo?",
        "keywords": ["descuento", "beneficio", "promocion", "oferta", "aniversario"],
        "tags": ["beneficios", "pagos"],
        "respuesta_card": EJEMPLO_CARDS["beneficio_aniversario"],
        "fuente": "Junta Directiva",
        "prioridad": 10
    },
    {
        "categoria": "cursos",
        "subcategoria": "capacitacion",
        "pregunta": "¿Qué cursos hay disponibles?",
        "keywords": ["curso", "cursos", "capacitacion", "seminario", "taller", "niif"],
        "tags": ["cursos", "capacitacion"],
        "respuesta_card": EJEMPLO_CARDS["curso_niif"],
        "fuente": "Comisión de Capacitación",
        "prioridad": 7
    }
]
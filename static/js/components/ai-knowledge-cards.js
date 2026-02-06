/**
 * AI Knowledge Cards - Sistema de tarjetas de conocimiento
 * static/js/components/ai-knowledge-cards.js
 * 
 * Renderiza respuestas del chatbot en formato de tarjetas atractivas
 * - Artículos con imagen
 * - Listas de pasos
 * - Métricas/datos
 * - Citas y referencias legales
 */

const AIKnowledgeCards = {
    
    /**
     * Renderiza una respuesta completa con múltiples cards
     */
    render(response) {
        if (typeof response === 'string') {
            return this.renderText(response);
        }
        
        const container = document.createElement('div');
        container.className = 'ai-response-cards';
        
        // Si es un array de cards
        if (Array.isArray(response.cards)) {
            response.cards.forEach(card => {
                container.appendChild(this.renderCard(card));
            });
        } 
        // Si es una sola card
        else if (response.type) {
            container.appendChild(this.renderCard(response));
        }
        // Texto plano con formato
        else if (response.text) {
            container.innerHTML = this.formatText(response.text);
        }
        
        return container.outerHTML;
    },
    
    /**
     * Renderiza una card individual según su tipo
     */
    renderCard(card) {
        switch(card.type) {
            case 'article':
                return this.renderArticleCard(card);
            case 'featured':
                return this.renderFeaturedCard(card);
            case 'list':
            case 'steps':
                return this.renderListCard(card);
            case 'metric':
                return this.renderMetricCard(card);
            case 'mini':
                return this.renderMiniCard(card);
            default:
                return this.renderArticleCard(card);
        }
    },
    
    /**
     * Card tipo Artículo (imagen a la derecha)
     */
    renderArticleCard(card) {
        const div = document.createElement('div');
        div.className = 'knowledge-card card-article';
        
        div.innerHTML = `
            <div class="card-content">
                ${card.source ? this.renderSource(card.source) : ''}
                ${card.category ? `<div class="card-category"><i class="ph ph-tag"></i> ${card.category}</div>` : ''}
                <h3 class="card-title">${card.title}</h3>
                <p class="card-description">${card.description || ''}</p>
                ${card.citation ? this.renderCitation(card.citation) : ''}
                ${card.tip ? this.renderTip(card.tip) : ''}
                ${card.actions !== false ? this.renderFooter(card) : ''}
            </div>
            <div class="card-image">
                ${card.image 
                    ? `<img src="${card.image}" alt="${card.title}">`
                    : `<i class="ph ph-${card.icon || 'article'}"></i>`
                }
            </div>
        `;
        
        return div;
    },
    
    /**
     * Card tipo Destacado (imagen grande arriba)
     */
    renderFeaturedCard(card) {
        const div = document.createElement('div');
        div.className = 'knowledge-card card-featured';
        
        div.innerHTML = `
            <div class="card-banner">
                ${card.image 
                    ? `<img src="${card.image}" alt="${card.title}">`
                    : `<i class="ph ph-${card.icon || 'sparkle'}"></i>`
                }
            </div>
            <div class="card-content">
                ${card.source ? this.renderSource(card.source) : ''}
                ${card.category ? `<div class="card-category"><i class="ph ph-tag"></i> ${card.category}</div>` : ''}
                <h3 class="card-title large">${card.title}</h3>
                <p class="card-description">${card.description || ''}</p>
                ${card.citation ? this.renderCitation(card.citation) : ''}
                ${card.tip ? this.renderTip(card.tip) : ''}
                ${card.warning ? this.renderWarning(card.warning) : ''}
                ${card.related ? this.renderRelated(card.related) : ''}
                ${card.actions !== false ? this.renderFooter(card) : ''}
            </div>
        `;
        
        return div;
    },
    
    /**
     * Card tipo Lista / Pasos
     */
    renderListCard(card) {
        const div = document.createElement('div');
        div.className = 'knowledge-card card-list';
        
        const stepsHTML = card.steps.map((step, index) => `
            <div class="card-step">
                <div class="card-step-number">${index + 1}</div>
                <div class="card-step-content">
                    <div class="card-step-title">${step.title}</div>
                    ${step.description ? `<div class="card-step-desc">${step.description}</div>` : ''}
                </div>
            </div>
        `).join('');
        
        div.innerHTML = `
            <div class="card-content">
                ${card.source ? this.renderSource(card.source) : ''}
                ${card.category ? `<div class="card-category"><i class="ph ph-list-numbers"></i> ${card.category}</div>` : ''}
                <h3 class="card-title">${card.title}</h3>
                ${card.description ? `<p class="card-description">${card.description}</p>` : ''}
                <div class="card-steps">${stepsHTML}</div>
                ${card.citation ? this.renderCitation(card.citation) : ''}
                ${card.tip ? this.renderTip(card.tip) : ''}
                ${card.actions !== false ? this.renderFooter(card) : ''}
            </div>
        `;
        
        return div;
    },
    
    /**
     * Card tipo Métrica / Dato
     */
    renderMetricCard(card) {
        const div = document.createElement('div');
        div.className = 'knowledge-card card-metric';
        
        div.innerHTML = `
            <div class="card-metric-icon ${card.color || 'purple'}">
                <i class="ph ph-${card.icon || 'chart-line-up'}"></i>
            </div>
            <div class="card-metric-data">
                <div class="card-metric-value">${card.value}</div>
                <div class="card-metric-label">${card.label}</div>
            </div>
            ${card.trend ? `
                <div class="card-metric-trend ${card.trend > 0 ? 'up' : 'down'}">
                    <i class="ph ph-trend-${card.trend > 0 ? 'up' : 'down'}"></i>
                    ${Math.abs(card.trend)}%
                </div>
            ` : ''}
        `;
        
        return div;
    },
    
    /**
     * Card Mini (para enlaces rápidos)
     */
    renderMiniCard(card) {
        const div = document.createElement('div');
        div.className = 'knowledge-card card-mini';
        if (card.url) div.style.cursor = 'pointer';
        if (card.url) div.onclick = () => window.location.href = card.url;
        
        div.innerHTML = `
            <div class="card-mini-icon">
                <i class="ph ph-${card.icon || 'link'}"></i>
            </div>
            <div class="card-mini-content">
                <div class="card-mini-title">${card.title}</div>
                ${card.subtitle ? `<div class="card-mini-subtitle">${card.subtitle}</div>` : ''}
            </div>
            <i class="ph ph-caret-right card-mini-arrow"></i>
        `;
        
        return div;
    },
    
    /**
     * Renderiza la fuente/origen
     */
    renderSource(source) {
        if (typeof source === 'string') {
            return `
                <div class="card-source">
                    <div class="card-source-icon"><i class="ph ph-book-open"></i></div>
                    <span class="card-source-name">${source}</span>
                </div>
            `;
        }
        
        return `
            <div class="card-source">
                <div class="card-source-icon"><i class="ph ph-${source.icon || 'book-open'}"></i></div>
                <span class="card-source-name">${source.name}</span>
                ${source.verified ? '<span class="card-source-badge">Verificado</span>' : ''}
            </div>
        `;
    },
    
    /**
     * Renderiza cita / base legal
     */
    renderCitation(citation) {
        if (typeof citation === 'string') {
            return `
                <div class="card-citation">
                    <i class="ph ph-quotes"></i>
                    <div>
                        <span class="card-citation-text">${citation}</span>
                    </div>
                </div>
            `;
        }
        
        return `
            <div class="card-citation">
                <i class="ph ph-${citation.icon || 'scales'}"></i>
                <div>
                    <span class="card-citation-text">${citation.text}</span>
                    ${citation.source ? `<span class="card-citation-source">— ${citation.source}</span>` : ''}
                </div>
            </div>
        `;
    },
    
    /**
     * Renderiza tip / consejo
     */
    renderTip(tip) {
        if (typeof tip === 'string') {
            return `
                <div class="card-tip">
                    <i class="ph ph-lightbulb"></i>
                    <div>
                        <span class="card-tip-label">Tip</span>
                        <span class="card-tip-text">${tip}</span>
                    </div>
                </div>
            `;
        }
        
        return `
            <div class="card-tip">
                <i class="ph ph-${tip.icon || 'lightbulb'}"></i>
                <div>
                    <span class="card-tip-label">${tip.label || 'Tip de implementación'}</span>
                    <span class="card-tip-text">${tip.text}</span>
                </div>
            </div>
        `;
    },
    
    /**
     * Renderiza advertencia
     */
    renderWarning(warning) {
        const text = typeof warning === 'string' ? warning : warning.text;
        return `
            <div class="card-warning">
                <i class="ph ph-warning"></i>
                <span class="card-tip-text">${text}</span>
            </div>
        `;
    },
    
    /**
     * Renderiza cards relacionadas
     */
    renderRelated(related) {
        if (!related || !related.length) return '';
        
        const cardsHTML = related.slice(0, 4).map(item => `
            <div class="related-card" onclick="${item.url ? `window.location.href='${item.url}'` : ''}">
                <div class="related-card-title">${item.title}</div>
                <div class="related-card-meta">
                    <i class="ph ph-${item.icon || 'article'}"></i>
                    ${item.meta || 'Ver más'}
                </div>
            </div>
        `).join('');
        
        return `<div class="related-cards-grid">${cardsHTML}</div>`;
    },
    
    /**
     * Renderiza footer con acciones
     */
    renderFooter(card) {
        const id = card.id || Math.random().toString(36).substr(2, 9);
        
        return `
            <div class="card-footer">
                <div class="card-actions">
                    <button class="card-action" onclick="AIKnowledgeCards.like('${id}')" id="like-${id}">
                        <i class="ph ph-heart"></i>
                        <span>${card.likes || ''}</span>
                    </button>
                    <button class="card-action" onclick="AIKnowledgeCards.save('${id}')" id="save-${id}">
                        <i class="ph ph-bookmark-simple"></i>
                    </button>
                    <button class="card-action" onclick="AIKnowledgeCards.share('${id}', '${encodeURIComponent(card.title)}')">
                        <i class="ph ph-share-network"></i>
                    </button>
                </div>
                <span class="card-timestamp">${card.timestamp || 'Ahora'}</span>
            </div>
        `;
    },
    
    /**
     * Renderiza texto simple con formato
     */
    renderText(text) {
        return `<div class="ai-chat-message bot">${this.formatText(text)}</div>`;
    },
    
    /**
     * Formatea texto con markdown básico
     */
    formatText(text) {
        return text
            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
            .replace(/\*(.*?)\*/g, '<em>$1</em>')
            .replace(/\n/g, '<br>');
    },
    
    // ============================================
    // ACCIONES DE USUARIO
    // ============================================
    
    like(id) {
        const btn = document.getElementById(`like-${id}`);
        if (btn) {
            btn.classList.toggle('active');
            const icon = btn.querySelector('i');
            if (icon) {
                icon.className = btn.classList.contains('active') 
                    ? 'ph ph-heart-fill' 
                    : 'ph ph-heart';
            }
        }
    },
    
    save(id) {
        const btn = document.getElementById(`save-${id}`);
        if (btn) {
            btn.classList.toggle('active');
            const icon = btn.querySelector('i');
            if (icon) {
                icon.className = btn.classList.contains('active') 
                    ? 'ph ph-bookmark-simple-fill' 
                    : 'ph ph-bookmark-simple';
            }
            
            if (typeof Toast !== 'undefined') {
                Toast.show(btn.classList.contains('active') ? 'Guardado' : 'Eliminado de guardados', 'success');
            }
        }
    },
    
    share(id, title) {
        const text = decodeURIComponent(title);
        
        if (navigator.share) {
            navigator.share({
                title: text,
                text: `Información del Colegio: ${text}`,
                url: window.location.href
            });
        } else {
            navigator.clipboard.writeText(`${text}\n${window.location.href}`);
            if (typeof Toast !== 'undefined') {
                Toast.show('Enlace copiado', 'success');
            }
        }
    }
};

// Exponer globalmente
window.AIKnowledgeCards = AIKnowledgeCards;
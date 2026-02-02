function copiarMiSitio() {
    const input = document.getElementById('mi-sitio-url');
    
    // Verificar que hay URL válida
    if (!input || input.value === 'Perfil no disponible') {
        if (typeof Toast !== 'undefined') Toast.show('Perfil no disponible', 'error');
        return;
    }
    
    const btn = document.querySelector('.btn-copy');
    const icon = document.getElementById('copy-icon');
    
    navigator.clipboard.writeText(input.value).then(() => {
        // Feedback visual
        if (icon) icon.className = 'ph ph-check';
        if (btn) btn.classList.add('copied');
        
        if (typeof SoundFX !== 'undefined') SoundFX.play('success');
        if (typeof Toast !== 'undefined') Toast.show('¡Link copiado!', 'success');
        
        setTimeout(() => {
            if (icon) icon.className = 'ph ph-copy';
            if (btn) btn.classList.remove('copied');
        }, 2000);
    }).catch(() => {
        // Fallback
        input.select();
        document.execCommand('copy');
        if (typeof Toast !== 'undefined') Toast.show('Link copiado', 'success');
    });
}

// Compartir sitio
async function compartirMiSitio() {
    const input = document.getElementById('mi-sitio-url');
    
    if (!input || input.value === 'Perfil no disponible') {
        if (typeof Toast !== 'undefined') Toast.show('Perfil no disponible', 'error');
        return;
    }
    
    const url = input.value;
    const nombre = document.querySelector('.preview-name')?.textContent || 'Mi Perfil';
    
    if (navigator.share) {
        try {
            await navigator.share({
                title: nombre + ' - Perfil Verificado',
                text: 'Verifica mi habilidad profesional:',
                url: url
            });
            if (typeof SoundFX !== 'undefined') SoundFX.play('success');
        } catch (err) {
            if (err.name !== 'AbortError') {
                console.log('Compartir cancelado');
            }
        }
    } else {
        // Fallback: abrir WhatsApp
        const mensaje = encodeURIComponent('Verifica mi habilidad profesional: ' + url);
        window.open('https://wa.me/?text=' + mensaje, '_blank');
    }
}
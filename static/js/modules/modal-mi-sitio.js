/**
 * modal-mi-sitio.js
 * Módulo lazy: Perfil público / Mi Sitio Web del colegiado
 * (Migrado de mi_sitio_web.js al patrón lazy)
 */
(function() {
    'use strict';

    const MODAL_ID = 'modal-mi-sitio';

    function copiarMiSitio() {
        const input = document.getElementById('mi-sitio-url');
        if (!input || input.value === 'Perfil no disponible') {
            Toast.show('Perfil no disponible', 'error');
            return;
        }
        const btn = document.querySelector('.btn-copy');
        const icon = document.getElementById('copy-icon');

        navigator.clipboard.writeText(input.value).then(() => {
            if (icon) icon.className = 'ph ph-check';
            if (btn) btn.classList.add('copied');
            SoundFX.play('success');
            Toast.show('¡Link copiado!', 'success');
            setTimeout(() => {
                if (icon) icon.className = 'ph ph-copy';
                if (btn) btn.classList.remove('copied');
            }, 2000);
        }).catch(() => {
            input.select();
            document.execCommand('copy');
            Toast.show('Link copiado', 'success');
        });
    }

    async function compartirMiSitio() {
        const input = document.getElementById('mi-sitio-url');
        if (!input || input.value === 'Perfil no disponible') {
            Toast.show('Perfil no disponible', 'error');
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
                SoundFX.play('success');
            } catch (err) {
                if (err.name !== 'AbortError') console.log('Compartir cancelado');
            }
        } else {
            const mensaje = encodeURIComponent('Verifica mi habilidad profesional: ' + url);
            window.open('https://wa.me/?text=' + mensaje, '_blank');
        }
    }

    // Auto-registro
    const modal = document.getElementById(MODAL_ID);
    if (modal) {
        modal.addEventListener('modal:opened', () => { /* no necesita init especial */ });
    }

    // API pública
    window.copiarMiSitio = copiarMiSitio;
    window.compartirMiSitio = compartirMiSitio;

})();
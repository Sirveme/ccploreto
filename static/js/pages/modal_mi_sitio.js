/**
 * Modal Mi Sitio Web — Copiar URL, Compartir
 */

function copiarMiSitio() {
    const input = document.getElementById('mi-sitio-url');
    if (!input) return;

    navigator.clipboard.writeText(input.value).then(() => {
        const icon = document.getElementById('copy-icon');
        if (icon) {
            icon.className = 'ph ph-check';
            setTimeout(() => { icon.className = 'ph ph-copy'; }, 2000);
        }
        if (typeof Toast !== 'undefined') Toast.show('URL copiada al portapapeles', 'success');
    }).catch(() => {
        // Fallback
        input.select();
        document.execCommand('copy');
        if (typeof Toast !== 'undefined') Toast.show('URL copiada', 'success');
    });
}

function compartirMiSitio() {
    const url = document.getElementById('mi-sitio-url')?.value;
    if (!url) return;

    if (navigator.share) {
        navigator.share({
            title: 'Mi perfil profesional',
            text: 'Consulta mi perfil de colegiado verificado',
            url: url
        }).catch(() => {});
    } else {
        copiarMiSitio();
    }
}

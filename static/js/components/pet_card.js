/* static/js/components/pet_card.js */

const PetCard = {

    // Nueva función que lee los data-attributes (Limpia el HTML)
    compartirDesdeBoton: function(btn) {
        const d = btn.dataset;
        // Convertir string "true"/"false" a booleano
        const isLost = d.lost === 'true'; 
        this.compartir(d.name, d.species, isLost, d.location);
    },
    
    // Función para compartir usando API nativa del celular
    compartir: function(nombre, especie, estado, ubicacion) {
        if (navigator.share) {
            const texto = estado 
                ? `🚨 ¡AYUDA! Se perdió ${nombre} (${especie}). Visto por última vez en: ${ubicacion}.` 
                : `Conoce a ${nombre}, nuestro vecino peludo del edificio.`;

            navigator.share({
                title: `Mascota: ${nombre}`,
                text: texto,
                url: window.location.href
            })
            .then(() => console.log('Compartido con éxito'))
            .catch((error) => console.log('Error compartiendo', error));
        } else {
            // Fallback para PC antigua: Copiar al portapapeles
            const texto = `Mira a ${nombre} en nuestra App Vecinal: ${window.location.href}`;
            navigator.clipboard.writeText(texto);
            alert("Enlace copiado al portapapeles (Tu navegador no soporta compartir nativo)");
        }
    },

    // Función para cambiar estado (Llama al backend)
    toggleEstado: async function(petId, btnElement) {
        if (!confirm("¿Deseas cambiar el estado de búsqueda de esta mascota?")) return;

        // Feedback visual inmediato (Loading)
        const originalText = btnElement.innerText;
        btnElement.innerText = "Procesando...";
        btnElement.disabled = true;

        try {
            const response = await fetch(`/pets/${petId}/lost`, { method: 'POST' });
            
            if (response.ok) {
                // Opción A: Recargar la página para ver cambios (Más fácil)
                window.location.reload();
                
                // Opción B (Avanzada): Usar HTMX en el HTML para reemplazar solo la tarjeta
                // (Si usas HTMX en el botón, no necesitas esta función JS completa)
            } else {
                alert("Error al actualizar estado. Intenta nuevamente.");
                btnElement.innerText = originalText;
                btnElement.disabled = false;
            }
        } catch (error) {
            console.error(error);
            alert("Error de conexión");
            btnElement.innerText = originalText;
            btnElement.disabled = false;
        }
    },

    verDetalle: function(id) {
        // Futuro: Abrir modal con fotos grandes
        console.log("Ver detalle mascota", id);
    }

};

// Exportar globalmente si es necesario (aunque PetCard ya es global)
window.PetCard = PetCard;
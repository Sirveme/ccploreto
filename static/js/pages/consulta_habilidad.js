/**
 * Consulta de Habilidad - JavaScript
 * Maneja la búsqueda y presentación de resultados
 */

document.addEventListener('DOMContentLoaded', function() {
    const inputQuery = document.getElementById('query');
    const btnBuscar = document.getElementById('btn-buscar');
    const resultadoContainer = document.getElementById('resultado');
    
    // Buscar al hacer clic
    btnBuscar.addEventListener('click', realizarConsulta);
    
    // Buscar al presionar Enter
    inputQuery.addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            realizarConsulta();
        }
    });
    
    // Limpiar resultado al escribir
    inputQuery.addEventListener('input', function() {
        if (this.value.length === 0) {
            resultadoContainer.style.display = 'none';
        }
    });
    
    async function realizarConsulta() {
        const query = inputQuery.value.trim();
        
        if (query.length < 3) {
            mostrarError('Ingrese al menos 3 caracteres');
            return;
        }
        
        // Mostrar loading
        setLoading(true);
        
        try {
            const response = await fetch(`/consulta/habilidad/verificar?q=${encodeURIComponent(query)}`);
            const data = await response.json();
            
            if (!response.ok) {
                mostrarError(data.detail || 'Error en la consulta');
                return;
            }
            
            mostrarResultado(data);
            
        } catch (error) {
            console.error('Error:', error);
            mostrarError('Error de conexión. Intente nuevamente.');
        } finally {
            setLoading(false);
        }
    }
    
    function mostrarResultado(data) {
        resultadoContainer.style.display = 'block';
        
        if (!data.encontrado) {
            resultadoContainer.className = 'resultado-container resultado-no-encontrado';
            resultadoContainer.innerHTML = `
                <div class="resultado-icon">🔍</div>
                <p class="resultado-estado" style="color: #4b5563;">No encontrado</p>
                <p style="text-align: center; color: #6b7280;">
                    ${data.mensaje}
                </p>
            `;
            return;
        }
        
        const esHabil = data.datos.condicion === 'habil';
        const claseEstado = esHabil ? 'resultado-habil' : 'resultado-inhabil';
        const icono = esHabil ? '✅' : '❌';
        
        resultadoContainer.className = `resultado-container ${claseEstado}`;
        resultadoContainer.innerHTML = `
            <div class="resultado-icon">${icono}</div>
            <p class="resultado-estado">${data.datos.condicion_texto}</p>
            <div class="resultado-datos">
                <p>
                    <strong>Matrícula:</strong>
                    <span>${data.datos.codigo_matricula}</span>
                </p>
                <p>
                    <strong>Nombre:</strong>
                    <span>${data.datos.apellidos_nombres}</span>
                </p>
                ${data.datos.fecha_actualizacion ? `
                <p>
                    <strong>Actualizado:</strong>
                    <span>${data.datos.fecha_actualizacion}</span>
                </p>
                ` : ''}
            </div>
        `;
    }
    
    function mostrarError(mensaje) {
        resultadoContainer.style.display = 'block';
        resultadoContainer.className = 'resultado-container resultado-no-encontrado';
        resultadoContainer.innerHTML = `
            <div class="resultado-icon">⚠️</div>
            <p style="text-align: center; color: #4b5563;">${mensaje}</p>
        `;
    }
    
    function setLoading(isLoading) {
        const btnText = btnBuscar.querySelector('.btn-text');
        const btnLoading = btnBuscar.querySelector('.btn-loading');
        
        if (isLoading) {
            btnText.style.display = 'none';
            btnLoading.style.display = 'block';
            btnBuscar.disabled = true;
            inputQuery.disabled = true;
        } else {
            btnText.style.display = 'block';
            btnLoading.style.display = 'none';
            btnBuscar.disabled = false;
            inputQuery.disabled = false;
        }
    }
});
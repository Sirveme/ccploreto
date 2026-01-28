window.Toast = {
    container: null,

    init: function() {
        if (!document.getElementById('toast-container')) {
            this.container = document.createElement('div');
            this.container.id = 'toast-container';
            document.body.appendChild(this.container);
        } else {
            this.container = document.getElementById('toast-container');
        }
    },

    show: function(message, type = 'info', duration = 4000) {
        this.init(); // Asegurar que existe

        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        
        let icon = '';
        if (type === 'success') icon = '<i class="ph ph-check-circle text-green-600 text-xl mr-3"></i>';
        if (type === 'error') icon = '<i class="ph ph-x-circle text-red-600 text-xl mr-3"></i>';
        if (type === 'info') icon = '<i class="ph ph-info text-blue-600 text-xl mr-3"></i>';
        if (type === 'warning') icon = '<i class="ph ph-warning text-yellow-600 text-xl mr-3"></i>';

        toast.innerHTML = `
            <div class="flex items-center">
                ${icon}
                <span class="font-medium">${message}</span>
            </div>
            <button onclick="this.parentElement.parentElement.remove()" class="ml-4 text-slate-400 hover:text-slate-600">
                <i class="ph ph-x"></i>
            </button>
        `;

        this.container.appendChild(toast);

        // Auto eliminar
        setTimeout(() => {
            toast.classList.add('hiding');
            toast.addEventListener('animationend', () => toast.remove());
        }, duration);
        
        // Sonido sutil opcional
        if(type === 'success' || type === 'error') {
            const audio = new Audio('/static/sounds/ding-dong.mp3'); 
            audio.volume = 0.2;
            audio.play().catch(e=>{});
        }
    }
};
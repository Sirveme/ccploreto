// login.js
document.addEventListener('DOMContentLoaded', () => {
    
    const toggleBtn = document.getElementById('toggle-password-btn');
    const passwordInput = document.getElementById('password-input');
    const iconEye = document.getElementById('icon-eye');
    const iconEyeSlash = document.getElementById('icon-eye-slash');

    if (toggleBtn && passwordInput) {
        toggleBtn.addEventListener('click', (e) => {
            e.preventDefault(); // Evitar submit accidental
            
            const type = passwordInput.getAttribute('type') === 'password' ? 'text' : 'password';
            passwordInput.setAttribute('type', type);
            
            // Alternar íconos
            iconEye.classList.toggle('hidden');
            iconEyeSlash.classList.toggle('hidden');
        });
    }
});
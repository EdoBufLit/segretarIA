document.addEventListener('DOMContentLoaded', () => {
    const intro = document.getElementById('premium-intro');
    const glow = document.querySelector('.intro-glow');
    const wordmark = document.querySelector('.intro-wordmark');

    if (!intro) return;

    // Check if intro has already been shown in this session
    if (sessionStorage.getItem('introShown')) {
        intro.style.display = 'none';
        return;
    }

    // Ensure it is visible for animation
    intro.style.display = 'flex';

    // Trigger animation
    requestAnimationFrame(() => {
        intro.style.opacity = '1';

        setTimeout(() => {
            if (glow) glow.classList.add('visible');
            if (wordmark) wordmark.classList.add('animate');
        }, 300);

        setTimeout(() => {
            // Fade out and scale down
            intro.style.opacity = '0';
            intro.style.transform = 'scale(0.9)';

            // Remove from DOM/Layout after transition
            setTimeout(() => {
                intro.style.display = 'none';
                sessionStorage.setItem('introShown', 'true');
            }, 700);
        }, 2000);
    });
});

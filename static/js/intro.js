document.addEventListener('DOMContentLoaded', () => {
    // 1. INTRO LOGIC
    const intro = document.getElementById('premium-intro');
    const wordmark = document.querySelector('.intro-wordmark');
    const glow = document.querySelector('.intro-glow');
    const hasPlayed = sessionStorage.getItem('intro_shown');
    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    // Helper to dismiss
    const dismissIntro = () => {
        if (!intro) return;
        intro.style.opacity = '0';
        intro.style.pointerEvents = 'none';
        document.body.style.overflow = ''; // Restore scroll
        setTimeout(() => {
            intro.style.display = 'none';
        }, 800); // Wait for transition
    };

    if (intro) {
        if (hasPlayed || prefersReducedMotion) {
            // Skip immediately
            intro.style.display = 'none';
        } else {
            // Play Intro
            document.body.style.overflow = 'hidden'; // Lock scroll

            // Start Animation Sequence
            requestAnimationFrame(() => {
                intro.style.opacity = '1';
                setTimeout(() => {
                    if(wordmark) wordmark.classList.add('animate');
                    if(glow) glow.classList.add('visible');
                }, 100);

                // End Sequence
                setTimeout(() => {
                    dismissIntro();
                    sessionStorage.setItem('intro_shown', 'true');
                }, 1300); // 1.3s duration
            });

            // ESC Listener
            document.addEventListener('keydown', (e) => {
                if (e.key === 'Escape') {
                    dismissIntro();
                    sessionStorage.setItem('intro_shown', 'true');
                }
            });
        }
    }

    // 2. SCROLL ANIMATIONS (Existing)
    const elements = document.querySelectorAll('.fade-in-up');

    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('visible');
                observer.unobserve(entry.target);
            }
        });
    }, {
        threshold: 0.1,
        rootMargin: "0px 0px -50px 0px"
    });

    elements.forEach(el => observer.observe(el));

    // 3. PARALLAX (Throttled)
    const blobs = document.querySelectorAll('.hero-blob');
    if (blobs.length > 0 && !prefersReducedMotion) {
        let ticking = false;

        document.addEventListener('mousemove', (e) => {
            if (!ticking) {
                window.requestAnimationFrame(() => {
                    const x = e.clientX / window.innerWidth;
                    const y = e.clientY / window.innerHeight;

                    blobs.forEach((blob, index) => {
                        const speed = (index + 1) * 20;
                        const xOffset = (x - 0.5) * speed;
                        const yOffset = (y - 0.5) * speed;

                        blob.style.transform = `translate3d(${xOffset}px, ${yOffset}px, 0)`;
                    });
                    ticking = false;
                });
                ticking = true;
            }
        });
    }
});

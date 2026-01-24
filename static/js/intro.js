const introOverlay = document.getElementById("intro-overlay");
const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

const startIntro = () => {
    if (!introOverlay) return;
    document.body.classList.add("intro-active");
    document.body.style.overflow = "hidden";
    setTimeout(() => {
        introOverlay.classList.add("intro-hidden");
        document.body.classList.remove("intro-active");
        document.body.style.overflow = "";
        sessionStorage.setItem("introPlayed", "true");
    }, 1200);
};

if (introOverlay) {
    if (prefersReducedMotion.matches) {
        introOverlay.classList.add("intro-hidden");
    } else if (!sessionStorage.getItem("introPlayed")) {
        startIntro();
    } else {
        introOverlay.classList.add("intro-hidden");
    }
}

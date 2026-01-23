const wizard = document.getElementById("booking-wizard");
const wizardCard = wizard?.querySelector(".booking-wizard__card");
const openButtons = document.querySelectorAll("[data-booking-open]");
const closeButtons = document.querySelectorAll("[data-booking-close]");
const stepContainer = document.getElementById("booking-wizard-step");
const progressText = document.getElementById("booking-wizard-progress");
const progressBar = document.getElementById("booking-wizard-progress-bar");
const errorMessage = document.getElementById("booking-wizard-error");
const prevButton = document.getElementById("booking-wizard-prev");
const nextButton = document.getElementById("booking-wizard-next");
const form = document.getElementById("booking-wizard-form");
const successState = document.getElementById("booking-wizard-success");

const steps = [
    {
        id: "full_name",
        label: "Nome e Cognome",
        type: "text",
        required: true,
        placeholder: "Mario Rossi",
    },
    {
        id: "email",
        label: "Email",
        type: "email",
        required: true,
        placeholder: "studio@esempio.it",
    },
    {
        id: "phone",
        label: "Telefono",
        type: "tel",
        required: true,
        placeholder: "+39 333 000 0000",
    },
    {
        id: "company",
        label: "Nome attività / azienda",
        type: "text",
        required: false,
        placeholder: "Studio Legale Rossi",
    },
    {
        id: "sector",
        label: "Settore",
        type: "select",
        required: true,
        options: [
            "Studio professionale",
            "Sanità",
            "Agenzia",
            "E-commerce",
            "Artigiano",
            "Servizi B2B",
            "Altro",
        ],
    },
    {
        id: "volume",
        label: "Volume chiamate stimato",
        type: "select",
        required: true,
        options: ["0–20/mese", "20–100", "100–300", "300+"],
    },
    {
        id: "needs",
        label: "Cosa ti serve?",
        type: "textarea",
        required: false,
        placeholder: "Descrivi brevemente la tua esigenza.",
    },
    {
        id: "privacy",
        label: "Consenso privacy",
        type: "checkbox",
        required: true,
        text: "Ho letto e accetto la Privacy Policy.",
    },
];

const state = {
    currentStep: 0,
    values: {},
    lastActive: null,
};

const emailPattern = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

const updateProgress = () => {
    const stepIndex = state.currentStep + 1;
    progressText.textContent = `${stepIndex}/${steps.length}`;
    progressBar.style.width = `${(stepIndex / steps.length) * 100}%`;
};

const renderStep = () => {
    const step = steps[state.currentStep];
    errorMessage.textContent = "";
    stepContainer.innerHTML = "";

    const label = document.createElement("label");
    label.className = "booking-wizard__label";
    label.setAttribute("for", `booking-${step.id}`);
    label.textContent = step.label;
    stepContainer.appendChild(label);

    let inputElement;

    if (step.type === "select") {
        inputElement = document.createElement("select");
        inputElement.className = "booking-wizard__select";
        inputElement.id = `booking-${step.id}`;
        inputElement.name = step.id;
        const placeholderOption = document.createElement("option");
        placeholderOption.value = "";
        placeholderOption.textContent = "Seleziona";
        placeholderOption.disabled = true;
        placeholderOption.selected = !state.values[step.id];
        inputElement.appendChild(placeholderOption);
        step.options.forEach((option) => {
            const opt = document.createElement("option");
            opt.value = option;
            opt.textContent = option;
            if (state.values[step.id] === option) {
                opt.selected = true;
            }
            inputElement.appendChild(opt);
        });
    } else if (step.type === "textarea") {
        inputElement = document.createElement("textarea");
        inputElement.className = "booking-wizard__textarea";
        inputElement.id = `booking-${step.id}`;
        inputElement.name = step.id;
        inputElement.placeholder = step.placeholder;
        inputElement.value = state.values[step.id] || "";
    } else if (step.type === "checkbox") {
        const wrapper = document.createElement("div");
        wrapper.className = "booking-wizard__checkbox";
        inputElement = document.createElement("input");
        inputElement.type = "checkbox";
        inputElement.id = `booking-${step.id}`;
        inputElement.name = step.id;
        inputElement.checked = Boolean(state.values[step.id]);

        const checkboxLabel = document.createElement("label");
        checkboxLabel.setAttribute("for", inputElement.id);
        checkboxLabel.innerHTML = `${step.text} <a href=\"#\" aria-label=\"Apri privacy policy\">Privacy</a>`;

        wrapper.appendChild(inputElement);
        wrapper.appendChild(checkboxLabel);
        stepContainer.appendChild(wrapper);
        inputElement.focus();
        return;
    } else {
        inputElement = document.createElement("input");
        inputElement.type = step.type;
        inputElement.className = "booking-wizard__input";
        inputElement.id = `booking-${step.id}`;
        inputElement.name = step.id;
        inputElement.placeholder = step.placeholder;
        inputElement.value = state.values[step.id] || "";
    }

    stepContainer.appendChild(inputElement);
    inputElement.focus();
};

const validateStep = () => {
    const step = steps[state.currentStep];
    let value;

    if (step.type === "checkbox") {
        const checkbox = document.getElementById(`booking-${step.id}`);
        value = checkbox?.checked;
    } else {
        const field = document.getElementById(`booking-${step.id}`);
        value = field?.value.trim();
    }

    if (step.required && !value) {
        errorMessage.textContent = "Compila il campo per continuare.";
        return false;
    }

    if (step.type === "email" && value && !emailPattern.test(value)) {
        errorMessage.textContent = "Inserisci un indirizzo email valido.";
        return false;
    }

    state.values[step.id] = value;
    return true;
};

const showSuccess = () => {
    form.hidden = true;
    successState.hidden = false;
};

const resetWizard = () => {
    state.currentStep = 0;
    state.values = {};
    form.hidden = false;
    successState.hidden = true;
    nextButton.disabled = false;
    nextButton.textContent = "Avanti";
    updateProgress();
    renderStep();
};

const openWizard = () => {
    if (!wizard) return;
    state.lastActive = document.activeElement;
    wizard.classList.add("is-open");
    wizard.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
    resetWizard();
    trapFocus();
};

const closeWizard = () => {
    wizard.classList.remove("is-open");
    wizard.setAttribute("aria-hidden", "true");
    document.body.style.overflow = "";
    releaseFocus();
    state.lastActive?.focus?.();
};

const nextStep = async () => {
    if (!validateStep()) {
        return;
    }
    if (state.currentStep === steps.length - 1) {
        await submitWizard();
        return;
    }
    state.currentStep += 1;
    updateProgress();
    renderStep();
    prevButton.disabled = state.currentStep === 0;
};

const prevStep = () => {
    if (state.currentStep === 0) return;
    state.currentStep -= 1;
    updateProgress();
    renderStep();
    prevButton.disabled = state.currentStep === 0;
};

const submitWizard = async () => {
    nextButton.disabled = true;
    nextButton.textContent = "Invio...";
    errorMessage.textContent = "";
    const payload = {
        full_name: state.values.full_name,
        email: state.values.email,
        phone: state.values.phone,
        company: state.values.company || "",
        sector: state.values.sector,
        volume: state.values.volume,
        needs: state.values.needs || "",
        privacy: state.values.privacy,
    };

    try {
        const response = await fetch("/lead", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify(payload),
        });

        if (!response.ok) {
            throw new Error("Errore durante l'invio.");
        }
        showSuccess();
    } catch (error) {
        errorMessage.textContent = "Si è verificato un errore. Riprova.";
    } finally {
        nextButton.disabled = false;
        nextButton.textContent = "Avanti";
    }
};

const handleKeydown = (event) => {
    if (!wizard.classList.contains("is-open")) return;
    if (event.key === "Escape") {
        event.preventDefault();
        closeWizard();
        return;
    }
    if (event.key === "ArrowRight") {
        event.preventDefault();
        nextStep();
        return;
    }
    if (event.key === "ArrowLeft") {
        event.preventDefault();
        prevStep();
        return;
    }
    if (event.key === "Enter") {
        const target = event.target;
        if (target?.tagName === "TEXTAREA") return;
        if (target?.type === "checkbox") return;
        event.preventDefault();
        nextStep();
    }
};

let focusTrapHandler = null;

const trapFocus = () => {
    if (!wizardCard) return;
    focusTrapHandler = (event) => {
        if (event.key !== "Tab") return;
        const focusable = wizardCard.querySelectorAll(
            "button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])"
        );
        const first = focusable[0];
        const last = focusable[focusable.length - 1];

        if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
        }
    };
    wizardCard.addEventListener("keydown", focusTrapHandler);
    document.addEventListener("keydown", handleKeydown);
};

const releaseFocus = () => {
    if (focusTrapHandler && wizardCard) {
        wizardCard.removeEventListener("keydown", focusTrapHandler);
    }
    document.removeEventListener("keydown", handleKeydown);
};

openButtons.forEach((button) => {
    button.addEventListener("click", () => {
        openWizard();
    });
});

closeButtons.forEach((button) => {
    button.addEventListener("click", () => {
        closeWizard();
    });
});

prevButton?.addEventListener("click", prevStep);
nextButton?.addEventListener("click", nextStep);

wizard?.addEventListener("click", (event) => {
    if (event.target === wizard) {
        closeWizard();
    }
});

updateProgress();
renderStep();

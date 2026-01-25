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
const titleElement = document.getElementById("booking-wizard-title");

const steps = [
    {
        title: "Dati di Contatto",
        fields: [
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
        ]
    },
    {
        title: "La tua Attività",
        fields: [
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
        ]
    },
    {
        title: "Esigenze Specifiche",
        fields: [
            {
                id: "needs",
                label: "Cosa ti serve?",
                type: "textarea",
                required: false,
                placeholder: "Descrivi brevemente la tua esigenza.",
            },
        ]
    },
    {
        title: "Privacy",
        fields: [
            {
                id: "privacy",
                label: "Consenso privacy",
                type: "checkbox",
                required: true,
                text: "Ho letto e accetto la Privacy Policy.",
            },
        ]
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

    // Update Title based on step
    if (titleElement) {
        titleElement.textContent = steps[state.currentStep].title;
    }
};

const createField = (field) => {
    const wrapper = document.createElement("div");
    wrapper.className = "booking-wizard__field";

    // Label logic
    if (field.type !== "checkbox") {
        const label = document.createElement("label");
        label.className = "booking-wizard__label";
        label.setAttribute("for", `booking-${field.id}`);
        label.textContent = field.label;
        if (field.required) {
            const span = document.createElement("span");
            span.textContent = " *";
            span.style.color = "#dc2626";
            label.appendChild(span);
        }
        wrapper.appendChild(label);
    }

    let inputElement;

    if (field.type === "select") {
        inputElement = document.createElement("select");
        inputElement.className = "booking-wizard__select";
        inputElement.id = `booking-${field.id}`;
        inputElement.name = field.id;

        const placeholderOption = document.createElement("option");
        placeholderOption.value = "";
        placeholderOption.textContent = "Seleziona...";
        placeholderOption.disabled = true;
        placeholderOption.selected = !state.values[field.id];
        inputElement.appendChild(placeholderOption);

        field.options.forEach((option) => {
            const opt = document.createElement("option");
            opt.value = option;
            opt.textContent = option;
            if (state.values[field.id] === option) {
                opt.selected = true;
            }
            inputElement.appendChild(opt);
        });
    } else if (field.type === "textarea") {
        inputElement = document.createElement("textarea");
        inputElement.className = "booking-wizard__textarea";
        inputElement.id = `booking-${field.id}`;
        inputElement.name = field.id;
        inputElement.placeholder = field.placeholder;
        inputElement.value = state.values[field.id] || "";
    } else if (field.type === "checkbox") {
        // Special wrapper for checkbox
        wrapper.className = "booking-wizard__checkbox";

        inputElement = document.createElement("input");
        inputElement.type = "checkbox";
        inputElement.id = `booking-${field.id}`;
        inputElement.name = field.id;
        inputElement.checked = Boolean(state.values[field.id]);

        const checkboxLabel = document.createElement("label");
        checkboxLabel.setAttribute("for", inputElement.id);
        checkboxLabel.innerHTML = `${field.text} <a href=\"/privacy\" target=\"_blank\" aria-label=\"Apri privacy policy\">Privacy</a>`;

        wrapper.appendChild(inputElement);
        wrapper.appendChild(checkboxLabel);
        // We return wrapper directly as it is different structure
        return wrapper;
    } else {
        inputElement = document.createElement("input");
        inputElement.type = field.type;
        inputElement.className = "booking-wizard__input";
        inputElement.id = `booking-${field.id}`;
        inputElement.name = field.id;
        inputElement.placeholder = field.placeholder;
        inputElement.value = state.values[field.id] || "";
    }

    wrapper.appendChild(inputElement);
    return wrapper;
};

const renderStep = () => {
    const step = steps[state.currentStep];
    errorMessage.textContent = "";
    stepContainer.innerHTML = "";

    // Render all fields for this step
    step.fields.forEach(field => {
        const fieldEl = createField(field);
        stepContainer.appendChild(fieldEl);
    });

    // Auto-focus first input
    const firstInput = stepContainer.querySelector("input, select, textarea");
    if (firstInput) {
        // Small timeout to allow transition to start smoothly
        setTimeout(() => firstInput.focus(), 50);
    }
};

const validateStep = () => {
    const step = steps[state.currentStep];
    let isValid = true;
    let firstErrorField = null;

    for (const field of step.fields) {
        let value;
        const el = document.getElementById(`booking-${field.id}`);

        if (field.type === "checkbox") {
            value = el?.checked;
        } else {
            value = el?.value.trim();
        }

        // Store value
        state.values[field.id] = value;

        // Validation checks
        if (field.required && !value) {
            if (!firstErrorField) firstErrorField = el;
            isValid = false;
            // Visual feedback could be added here (red border)
            el.style.borderColor = "#dc2626";
        } else {
            if (el) el.style.borderColor = "";
        }

        if (field.type === "email" && value && !emailPattern.test(value)) {
            if (!firstErrorField) firstErrorField = el;
            isValid = false;
            errorMessage.textContent = "Email non valida.";
            el.style.borderColor = "#dc2626";
        }
    }

    if (!isValid) {
        if (!errorMessage.textContent) errorMessage.textContent = "Compila tutti i campi obbligatori.";
        firstErrorField?.focus();
        return false;
    }

    return true;
};

const showSuccess = () => {
    form.hidden = true;
    successState.hidden = false;
    // Update header to hide steps or change title
    if (titleElement) titleElement.textContent = "Richiesta Inviata";
    progressText.parentElement.style.opacity = "0";
    progressBar.parentElement.style.opacity = "0";
};

const resetWizard = () => {
    state.currentStep = 0;
    state.values = {};
    form.hidden = false;
    successState.hidden = true;
    nextButton.disabled = false;
    nextButton.textContent = "Avanti";

    // Restore header visibility
    progressText.parentElement.style.opacity = "1";
    progressBar.parentElement.style.opacity = "1";

    updateProgress();
    renderStep();
};

const openWizard = () => {
    if (!wizard) return;
    state.lastActive = document.activeElement;
    wizard.classList.add("is-open");
    wizard.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";

    // Reset if it was closed in success state or midway?
    // Usually better to reset for fresh start unless we want to persist data.
    // Let's reset for now to ensure clean state.
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

    // Submit if last step
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
        ...state.values,
        // Ensure optional fields are strings
        company: state.values.company || "",
        needs: state.values.needs || ""
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
        nextButton.disabled = false;
        nextButton.textContent = "Conferma";
    }
};

const handleKeydown = (event) => {
    if (!wizard.classList.contains("is-open")) return;
    if (event.key === "Escape") {
        event.preventDefault();
        closeWizard();
        return;
    }
    if (event.key === "Enter") {
        const target = event.target;
        // Don't submit on Enter in Textarea
        if (target?.tagName === "TEXTAREA") return;
        // Don't submit on Enter on buttons (handled by click)
        if (target?.tagName === "BUTTON") return;
        // Don't submit on Enter on Checkbox if it toggles
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
        if (focusable.length === 0) return;

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
    button.addEventListener("click", (e) => {
        e.preventDefault(); // Prevent default link behavior if it's an anchor
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

// Init
updateProgress();
renderStep();
prevButton.disabled = true;

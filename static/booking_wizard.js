const wizard = document.getElementById("booking-wizard");
const wizardCard = wizard?.querySelector("[role='dialog']");
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

// Utility classes for input fields
const baseInputClasses = "w-full px-4 py-3 rounded-xl border border-neutral-200 bg-white text-neutral-900 placeholder-neutral-400 focus:outline-none focus:ring-2 focus:ring-neutral-900/10 focus:border-neutral-900 transition-all";
const errorInputClasses = "border-red-500 focus:ring-red-200 focus:border-red-500";

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

    // Checkbox has different wrapper style
    if (field.type === "checkbox") {
        wrapper.className = "flex items-start gap-3 p-4 rounded-xl border border-neutral-200 bg-neutral-50";

        const inputElement = document.createElement("input");
        inputElement.type = "checkbox";
        inputElement.id = `booking-${field.id}`;
        inputElement.name = field.id;
        inputElement.checked = Boolean(state.values[field.id]);
        inputElement.className = "mt-1 w-5 h-5 rounded border-neutral-300 text-neutral-900 focus:ring-neutral-900 cursor-pointer";

        const checkboxLabel = document.createElement("label");
        checkboxLabel.setAttribute("for", inputElement.id);
        checkboxLabel.className = "text-sm text-neutral-600 leading-relaxed cursor-pointer select-none";
        checkboxLabel.innerHTML = `${field.text} <a href="/privacy" target="_blank" class="text-neutral-900 font-semibold hover:underline">Privacy</a>`;

        wrapper.appendChild(inputElement);
        wrapper.appendChild(checkboxLabel);
        return wrapper;
    }

    // Standard fields
    wrapper.className = "flex flex-col gap-2";

    const label = document.createElement("label");
    label.className = "block text-sm font-semibold text-neutral-700";
    label.setAttribute("for", `booking-${field.id}`);
    label.textContent = field.label;
    if (field.required) {
        const span = document.createElement("span");
        span.textContent = "*";
        span.className = "text-red-500 ml-1";
        label.appendChild(span);
    }
    wrapper.appendChild(label);

    let inputElement;

    if (field.type === "select") {
        inputElement = document.createElement("select");
        inputElement.className = baseInputClasses + " appearance-none";
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
        inputElement.className = baseInputClasses + " min-h-[120px] resize-y";
        inputElement.id = `booking-${field.id}`;
        inputElement.name = field.id;
        inputElement.placeholder = field.placeholder;
        inputElement.value = state.values[field.id] || "";
    } else {
        inputElement = document.createElement("input");
        inputElement.type = field.type;
        inputElement.className = baseInputClasses;
        inputElement.id = `booking-${field.id}`;
        inputElement.name = field.id;
        inputElement.placeholder = field.placeholder;
        inputElement.value = state.values[field.id] || "";
    }

    wrapper.appendChild(inputElement);
    return wrapper;
};

const initSteps = () => {
    if (!stepContainer) return;
    stepContainer.innerHTML = ""; // Clear initial state

    steps.forEach((step, index) => {
        const wrapper = document.createElement("div");
        // Hidden by default, with flex layout and gap for spacing (replacing space-y-6 on parent)
        wrapper.className = "step-wrapper hidden flex flex-col gap-6 w-full will-change-[transform,opacity]";

        step.fields.forEach(field => {
            const fieldEl = createField(field);
            wrapper.appendChild(fieldEl);
        });

        stepContainer.appendChild(wrapper);
    });
};

const renderStep = () => {
    errorMessage.textContent = "";

    const stepWrappers = stepContainer.querySelectorAll('.step-wrapper');
    stepWrappers.forEach((el, index) => {
        if (index === state.currentStep) {
            el.classList.remove('hidden');
            el.classList.add('motion-safe:animate-fade-in-up');

            // Auto-focus first input
            const firstInput = el.querySelector("input, select, textarea");
            if (firstInput) {
                setTimeout(() => firstInput.focus(), 50);
            }
        } else {
            el.classList.add('hidden');
            el.classList.remove('motion-safe:animate-fade-in-up');
        }
    });
};

const setFieldError = (el, hasError) => {
    if (!el) return;
    if (hasError) {
        el.classList.add("border-red-500", "focus:ring-red-200", "focus:border-red-500");
        el.classList.remove("border-neutral-200", "focus:ring-neutral-900/10", "focus:border-neutral-900");
    } else {
        el.classList.remove("border-red-500", "focus:ring-red-200", "focus:border-red-500");
        el.classList.add("border-neutral-200", "focus:ring-neutral-900/10", "focus:border-neutral-900");
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

        state.values[field.id] = value;

        // Reset style
        if (field.type !== "checkbox") {
            setFieldError(el, false);
        } else {
            if (el.parentElement) el.parentElement.classList.remove("border-red-500", "bg-red-50");
        }

        // Validation
        let fieldError = false;
        if (field.required && !value) {
            fieldError = true;
        } else if (field.type === "email" && value && !emailPattern.test(value)) {
            fieldError = true;
            if (!errorMessage.textContent) errorMessage.textContent = "Email non valida.";
        }

        if (fieldError) {
            isValid = false;
            if (!firstErrorField) firstErrorField = el;

            if (field.type !== "checkbox") {
                setFieldError(el, true);
            } else {
                 if (el.parentElement) el.parentElement.classList.add("border-red-500", "bg-red-50");
            }
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
    form.classList.add("hidden");
    successState.classList.remove("hidden");

    if (progressText) progressText.parentElement.style.opacity = "0";
    if (progressBar) progressBar.parentElement.style.opacity = "0";

    if (titleElement) titleElement.textContent = "Richiesta Inviata";
};

const resetWizard = () => {
    state.currentStep = 0;
    state.values = {};

    form.classList.remove("hidden");
    successState.classList.add("hidden");

    nextButton.disabled = false;
    nextButton.textContent = "Avanti";

    if (progressText) progressText.parentElement.style.opacity = "1";
    if (progressBar) progressBar.parentElement.style.opacity = "1";

    // Reset inputs in DOM to ensure clean state
    const inputs = stepContainer.querySelectorAll("input, select, textarea");
    inputs.forEach(input => {
        if (input.type === "checkbox") {
            input.checked = false;
            if (input.parentElement) input.parentElement.classList.remove("border-red-500", "bg-red-50");
        } else {
            input.value = "";
            setFieldError(input, false);
        }
    });

    updateProgress();
    renderStep();
};

const openWizard = () => {
    if (!wizard) return;
    state.lastActive = document.activeElement;

    wizard.classList.remove("hidden");
    wizard.classList.add("flex");
    wizard.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";

    resetWizard();
    trapFocus();
};

const closeWizard = () => {
    if (!wizard) return;

    wizard.classList.remove("flex");
    wizard.classList.add("hidden");
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
        ...state.values,
        company: state.values.company || "",
        needs: state.values.needs || ""
    };

    try {
        const response = await fetch("/lead", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });

        if (!response.ok) throw new Error("Errore durante l'invio.");
        showSuccess();
    } catch (error) {
        errorMessage.textContent = "Si è verificato un errore. Riprova.";
        nextButton.disabled = false;
        nextButton.textContent = "Conferma";
    }
};

const handleKeydown = (event) => {
    if (wizard.classList.contains("hidden")) return;
    if (event.key === "Escape") {
        event.preventDefault();
        closeWizard();
        return;
    }
    if (event.key === "Enter") {
        const target = event.target;
        if (target?.tagName === "TEXTAREA") return;
        if (target?.tagName === "BUTTON") return;
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
        e.preventDefault();
        openWizard();
    });
});

closeButtons.forEach((button) => {
    button.addEventListener("click", () => {
        closeWizard();
    });
});

if (prevButton) prevButton.addEventListener("click", prevStep);
if (nextButton) nextButton.addEventListener("click", nextStep);

wizard?.addEventListener("click", (event) => {
    if (event.target === wizard || event.target.hasAttribute('data-booking-close')) {
        closeWizard();
    }
});

// Initialize Steps on Load
initSteps();

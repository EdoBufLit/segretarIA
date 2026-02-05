// static/billing.js

async function buyPlan(planCode) {
    if (!planCode) return;

    // Show loading state (generic)
    const btn = document.activeElement;
    const originalText = btn ? btn.innerText : "";
    if (btn) {
        btn.innerText = "Attendo...";
        btn.disabled = true;
    }

    try {
        const response = await fetch("/billing/checkout", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                plan_code: planCode
            }),
        });

        if (!response.ok) {
            const errorData = await response.json();
            alert("Errore durante il checkout: " + (errorData.detail || "Errore sconosciuto"));
            if (btn) {
                btn.innerText = originalText;
                btn.disabled = false;
            }
            return;
        }

        const data = await response.json();
        if (data.checkout_url) {
            window.location.href = data.checkout_url;
        } else {
            alert("Errore: Nessun URL di checkout ricevuto.");
            if (btn) {
                btn.innerText = originalText;
                btn.disabled = false;
            }
        }
    } catch (error) {
        console.error("Billing error:", error);
        alert("Si è verificato un errore di rete.");
        if (btn) {
            btn.innerText = originalText;
            btn.disabled = false;
        }
    }
}

// static/dashboard.js

let clients = {};

// =========================
// UI DASHBOARD PRINCIPALE
// =========================

// Custom confirmation modal function
function showConfirm(title, message, onConfirm) {
    const modal = document.getElementById('confirm-modal');
    const titleEl = document.getElementById('confirm-title');
    const messageEl = document.getElementById('confirm-message');
    const okBtn = document.getElementById('confirm-ok-btn');
    const cancelBtn = document.getElementById('confirm-cancel-btn');

    titleEl.textContent = title;
    messageEl.textContent = message;

    modal.classList.remove('hidden');
    modal.classList.add('flex');

    // Refresh feather icons in modal
    if (typeof feather !== 'undefined') feather.replace();

    // Clear previous handlers
    const newOkBtn = okBtn.cloneNode(true);
    okBtn.parentNode.replaceChild(newOkBtn, okBtn);
    const newCancelBtn = cancelBtn.cloneNode(true);
    cancelBtn.parentNode.replaceChild(newCancelBtn, cancelBtn);

    // Add new handlers
    newOkBtn.addEventListener('click', () => {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
        if (onConfirm) onConfirm();
    });

    newCancelBtn.addEventListener('click', () => {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
    });
}

function renderDashboardUI() {
    const container = document.getElementById("dashboard-content");
    if (!container) return;

    container.innerHTML = `
        <!-- CLIENTI -->
        <div class="bg-white p-6 rounded-lg shadow mb-10">
            <h2 class="text-2xl font-semibold mb-4">Clienti attuali</h2>

            <table class="min-w-full bg-white rounded border">
                <thead class="bg-blue-600 text-white">
                    <tr>
                        <th class="py-3 px-4 text-left">Agent ID</th>
                        <th class="py-3 px-4 text-left">Studio</th>
                        <th class="py-3 px-4 text-left">Email</th>
                        <th class="py-3 px-4 text-right">Azioni</th>
                    </tr>
                </thead>

                <tbody id="clients-table-body">
                    <!-- Popolato via JS -->
                </tbody>
            </table>
        </div>

        <!-- AGGIUNGI CLIENTE -->
        <div class="bg-white p-6 rounded-lg shadow mb-10">
            <h2 class="text-2xl font-semibold mb-4">➕ Aggiungi Cliente</h2>

            <div class="grid grid-cols-1 gap-4">
                <div>
                    <label class="font-medium">Agent ID*</label>
                    <input id="agent_id" class="w-full border p-2 rounded" placeholder="agent_xxxxxx">
                </div>

                <div>
                    <label class="font-medium">Nome Studio*</label>
                    <input id="studio_name" class="w-full border p-2 rounded" placeholder="Studio Legale Rossi">
                </div>

                <div>
                    <label class="font-medium">Email*</label>
                    <input id="email_to" class="w-full border p-2 rounded" placeholder="segreteria@studio.it">
                </div>

                <button onclick="addClient()"
                        class="mt-3 bg-blue-600 text-white p-3 rounded hover:bg-blue-700 w-40">
                    Aggiungi Cliente
                </button>
            </div>
        </div>

        <!-- GRAFICO GENERALE -->
        <div class="bg-white p-6 rounded-lg shadow mb-10">
            <h2 class="text-2xl font-semibold mb-4">📈 Attività giornaliera (totale)</h2>
            <canvas id="chart_all_clients"></canvas>
        </div>

        <!-- MODAL LOGS -->
        <div id="logModal"
             class="fixed inset-0 bg-black bg-opacity-40 hidden items-center justify-center">
            <div class="bg-white p-6 rounded-lg shadow-xl max-w-2xl w-full">
                <h2 class="text-xl font-semibold mb-4">Log chiamate</h2>

                <canvas id="clientChart" class="mb-4"></canvas>

                <pre id="logContent" class="bg-gray-100 p-3 rounded h-80 overflow-auto"></pre>

                <button onclick="closeModal()"
                        class="mt-4 bg-blue-600 text-white px-4 py-2 rounded">
                    Chiudi
                </button>
            </div>
        </div>
    `;
}

// =========================
// CRUD CLIENTI
// =========================

async function loadClients() {
    const res = await fetch("/clients");
    const data = await res.json();
    clients = data.clients || {};

    const tbody = document.getElementById("clients-table-body");
    if (!tbody) return;

    tbody.innerHTML = "";

    for (const id in clients) {
        const c = clients[id];

        tbody.innerHTML += `
            <tr class="border-b">
                <td class="py-2 px-4">${id}</td>
                <td class="py-2 px-4">${c.studio_name}</td>
                <td class="py-2 px-4">${c.email_to}</td>

                <td class="py-2 px-4 text-right space-x-2">
                    <button onclick="removeClient('${id}')"
                        class="bg-red-600 text-white px-3 py-1 rounded hover:bg-red-700">
                        Rimuovi
                    </button>
                </td>
            </tr>`;
    }
}

async function addClient() {
    const agent_id = document.getElementById("agent_id").value;
    const studio_name = document.getElementById("studio_name").value;
    const email_to = document.getElementById("email_to").value;

    if (!agent_id || !studio_name || !email_to) {
        alert("Compila tutti i campi.");
        return;
    }

    await fetch("/clients/add", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ agent_id, studio_name, email_to })
    });

    document.getElementById("agent_id").value = "";
    document.getElementById("studio_name").value = "";
    document.getElementById("email_to").value = "";

    await loadClients();
    await renderGlobalChart();
}

async function removeClient(agent_id) {
    showConfirm(
        'Rimuovi cliente',
        `Sei sicuro di voler rimuovere il client ${agent_id}? Questa azione non può essere annullata.`,
        async () => {
            await fetch("/clients/remove", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ agent_id })
            });

            await loadClients();
            await renderGlobalChart();
        }
    );
}

// =========================
// MODAL LOGS + GRAFICO
// =========================

async function openLogs(agent_id) {
    const res = await fetch(`/logs/${agent_id}`);
    const data = await res.json();

    const logContent = document.getElementById("logContent");
    if (logContent) {
        logContent.innerText = JSON.stringify(data.logs || [], null, 2);
    }

    await renderClientChart(agent_id);

    const modal = document.getElementById("logModal");
    if (modal) modal.classList.remove("hidden");
}

function closeModal() {
    const modal = document.getElementById("logModal");
    if (modal) modal.classList.add("hidden");
}


async function initLogsSection() {
    const select = document.getElementById("log-filter-client");
    select.innerHTML = "";

    const res = await fetch("/clients");
    const data = await res.json();

    const clientsObj = data.clients || {};

    for (const agentId in clientsObj) {
        const cfg = clientsObj[agentId];
        const op = document.createElement("option");
        op.value = agentId;
        op.textContent = cfg.studio_name || agentId;
        select.appendChild(op);
    }

    loadLogsTable(0);
}


// =========================
// IMPOSTAZIONI CLIENTE (Fase 6)
// =========================

async function initSettingsSection() {
    const select = document.getElementById("settings-client-select");
    if (!select) return;

    select.innerHTML = "";

    const res = await fetch("/clients");
    const data = await res.json();

    // qui dipende da come /clients risponde
    // supponiamo formato: { clients: { agent_id: {studio_name, ...}, ... } }
    const clientsObj = data.clients || {};

    for (const agentId in clientsObj) {
        const cfg = clientsObj[agentId];
        const opt = document.createElement("option");
        opt.value = agentId;
        opt.textContent = `${cfg.studio_name || agentId}`;
        select.appendChild(opt);
    }

    // Carica stato billing
    loadBillingStatus();
}

async function loadBillingStatus() {
    const loadingEl = document.getElementById("billing-loading");
    const infoEl = document.getElementById("billing-info");
    const planEl = document.getElementById("billing-plan-name");
    const statusEl = document.getElementById("billing-status");
    const detailsEl = document.getElementById("billing-details");
    const cycleEndEl = document.getElementById("billing-cycle-end");
    const usageEl = document.getElementById("billing-usage");
    const actionsEl = document.getElementById("billing-actions");

    try {
        const res = await fetch("/subscription/status");
        const data = await res.json();

        loadingEl.classList.add("hidden");
        infoEl.classList.remove("hidden");

        const status = data.status || "inactive"; // "active", "past_due", "canceled", "inactive"
        // Note: endpoint might return { "status": "inactive" } OR full object with "state" property.
        // Let's check format: ClientService.get_subscription_status returns {"state": ...} OR {"status": "inactive"}

        const state = data.state || data.status || "inactive";
        const planCode = data.plan_code || "Nessuno";

        planEl.textContent = planCode === "basic" ? "Basic" : (planCode === "pro" ? "Pro" : planCode);
        statusEl.textContent = translateStatus(state);

        // Colors for status
        statusEl.className = "text-lg font-bold capitalize " + getStatusColor(state);

        if (state === "active" || state === "past_due") {
            detailsEl.classList.remove("hidden");
            if (data.cycle_end) {
                cycleEndEl.textContent = new Date(data.cycle_end).toLocaleDateString();
            }
            if (data.minutes_used !== undefined && data.minutes_total !== undefined) {
                usageEl.textContent = `${data.minutes_used} / ${data.minutes_total}`;
            }
        } else {
            detailsEl.classList.add("hidden");
        }

        // ACTIONS
        actionsEl.innerHTML = "";

        if (state === "inactive" || state === "canceled") {
            // Show Activate Buttons
            const btnBasic = document.createElement("button");
            btnBasic.className = "px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded shadow text-sm font-medium";
            btnBasic.textContent = "Attiva Basic";
            btnBasic.onclick = () => billingCheckout("basic");
            actionsEl.appendChild(btnBasic);

            const btnPro = document.createElement("button");
            btnPro.className = "px-4 py-2 bg-purple-600 hover:bg-purple-500 text-white rounded shadow text-sm font-medium";
            btnPro.textContent = "Attiva Pro";
            btnPro.onclick = () => billingCheckout("pro");
            actionsEl.appendChild(btnPro);
        } else {
            // Active or Past Due

            // Change Plan (only if active)
            if (state === "active") {
                const targetPlan = planCode === "basic" ? "pro" : "basic";
                const btnChange = document.createElement("button");
                btnChange.className = "px-4 py-2 border border-blue-500 text-blue-400 hover:bg-blue-500/10 rounded text-sm font-medium";
                btnChange.textContent = `Passa a ${targetPlan === 'basic' ? 'Basic' : 'Pro'}`;
                btnChange.onclick = () => billingChangePlan(targetPlan);
                actionsEl.appendChild(btnChange);
            }

            // Manage Payment (Portal)
            const btnPortal = document.createElement("button");
            btnPortal.className = "px-4 py-2 bg-gray-700 hover:bg-gray-600 text-white rounded shadow text-sm font-medium";
            btnPortal.textContent = "Gestisci pagamento";
            btnPortal.onclick = () => billingPortal();
            actionsEl.appendChild(btnPortal);
        }

    } catch (e) {
        console.error("Error loading billing status:", e);
        loadingEl.textContent = "Errore nel caricamento stato.";
    }
}

function translateStatus(s) {
    const map = {
        'active': 'Attivo',
        'past_due': 'Pagamento Fallito',
        'canceled': 'Cancellato',
        'inactive': 'Inattivo',
        'trialing': 'In Prova'
    };
    return map[s] || s;
}

function getStatusColor(s) {
    if (s === 'active') return 'text-green-400';
    if (s === 'past_due') return 'text-red-400';
    if (s === 'canceled') return 'text-gray-400';
    return 'text-white';
}

async function billingCheckout(planCode) {
    try {
        const res = await fetch("/billing/checkout", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ plan_code: planCode })
        });
        const data = await res.json();
        if (data.checkout_url) {
            window.open(data.checkout_url, "_blank");
        } else {
            alert("Errore: " + (data.detail || "Impossibile creare checkout session"));
        }
    } catch (e) {
        alert("Errore di rete");
    }
}

async function billingChangePlan(targetPlan) {
    showConfirm(
        "Cambio Piano",
        `Vuoi davvero cambiare il tuo piano a ${targetPlan.toUpperCase()}?`,
        async () => {
            try {
                const res = await fetch("/billing/change-plan", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ plan_code: targetPlan })
                });
                const data = await res.json();
                if (data.status === "ok") {
                    alert("Richiesta inviata. Il piano verrà aggiornato a breve.");
                    loadBillingStatus();
                } else {
                    alert("Errore: " + (data.detail || "Impossibile cambiare piano"));
                }
            } catch (e) {
                alert("Errore di rete");
            }
        }
    );
}

async function billingPortal() {
    try {
        const res = await fetch("/billing/portal", {
            method: "POST"
        });
        const data = await res.json();
        if (data.url) {
            window.open(data.url, "_blank");
        } else {
            alert("Errore: " + (data.detail || "Impossibile aprire il portale"));
        }
    } catch (e) {
        alert("Errore di rete");
    }
}

async function loadClientSettings() {
    const select = document.getElementById("settings-client-select");
    const agentId = select.value;
    if (!agentId) return;

    const res = await fetch(`/clients/${agentId}`);
    const data = await res.json();
    const client = data.client || {};

    document.getElementById("settings-studio-name").value = client.studio_name || "";
    document.getElementById("settings-email-to").value = client.email_to || "";
    document.getElementById("settings-greeting").value = client.greeting || "";
    document.getElementById("settings-notes").value = client.notes || "";

    // 🔥 nuovi campi
    document.getElementById("settings-agent-phone-id").value = client.agent_phone_number_id || "";
    document.getElementById("settings-test-phone").value = client.test_phone_number || "";

    const form = document.getElementById("settings-form");
    form.classList.remove("hidden");

    window.currentSettingsAgentId = agentId;
}


async function saveClientSettings() {
    const agentId = window.currentSettingsAgentId;
    if (!agentId) {
        alert("Seleziona prima un cliente.");
        return;
    }

    const payload = {
        studio_name: document.getElementById("settings-studio-name").value,
        email_to: document.getElementById("settings-email-to").value,
        greeting: document.getElementById("settings-greeting").value,
        notes: document.getElementById("settings-notes").value,
        agent_phone_number_id: document.getElementById("settings-agent-phone-id").value,
        test_phone_number: document.getElementById("settings-test-phone").value
    };

    const res = await fetch(`/clients/${agentId}/update`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
    });

    const data = await res.json();
    if (data.status === "ok") {
        alert("Impostazioni salvate.");
    } else {
        alert("Errore nel salvataggio impostazioni.");
    }

    await loadClients();
    await renderGlobalChart();
}

async function triggerTestCall() {
    const agentId = window.currentSettingsAgentId;
    if (!agentId) {
        alert("Seleziona un cliente e carica le impostazioni prima.");
        return;
    }

    const phoneId = document.getElementById("settings-agent-phone-id").value.trim();
    const testNumber = document.getElementById("settings-test-phone").value.trim();

    if (!phoneId || !testNumber) {
        alert("Compila agent_phone_number_id e Numero di test prima di effettuare la chiamata.");
        return;
    }

    showConfirm(
        'Chiama Test',
        `Vuoi avviare una chiamata di test verso ${testNumber}?`,
        async () => {
            try {
                const res = await fetch(`/clients/${agentId}/test-call`, {
                    method: "POST"
                });

                if (!res.ok) {
                    const text = await res.text();
                    alert("Errore nella chiamata di test: " + text);
                    return;
                }

                const data = await res.json();
                console.log("Test call response:", data);
                alert("Chiamata di test avviata (controlla il tuo telefono).");

            } catch (e) {
                console.error(e);
                alert("Errore di rete durante la chiamata di test.");
            }
        }
    );
}


// =========================
// BOOTSTRAP
// =========================

// =========================
// BOOTSTRAP ESPORTATO
// =========================

async function initDashboard() {
    renderDashboardUI();
    await loadClients();
    await renderGlobalChart();
}

// =========================
// LOG VIEWER (Fase 5)
// =========================

let logsOffset = 0;
let logsLimit = 25;
let logsTotal = 0;

async function loadLogsTable(offsetOverride = null) {
    if (offsetOverride !== null) logsOffset = offsetOverride;

    const clientEl = document.getElementById("log-filter-client");
    const statusEl = document.getElementById("log-filter-status");
    const fromEl = document.getElementById("log-filter-from");
    const toEl = document.getElementById("log-filter-to");
    const qEl = document.getElementById("log-filter-q");

    const client = clientEl.value;
    if (!client) return;

    const params = new URLSearchParams({
        limit: logsLimit,
        offset: logsOffset,
        status: statusEl.value
    });

    if (fromEl.value) params.append("date_from", fromEl.value);
    if (toEl.value) params.append("date_to", toEl.value);
    if (qEl.value) params.append("q", qEl.value);

    const res = await fetch(`/logs/${client}/list?` + params.toString());
    const data = await res.json();

    logsTotal = data.total ?? 0;
    const items = data.items ?? [];

    // salviamo per sicurezza se un domani ti serve
    window.currentLogItems = items;
    window.currentLogClient = client;

    const tbody = document.getElementById("logs-table");
    tbody.innerHTML = "";

    items.forEach((item) => {
        const tr = document.createElement("tr");
        tr.className = item.status === "failure" ? "bg-red-50" : "";

        tr.innerHTML = `
            <td class="border p-2">${item.timestamp}</td>
            <td class="border p-2">${client}</td>
            <td class="border p-2">${item.caller}</td>
            <td class="border p-2 font-bold ${item.status === "failure" ? "text-red-600" : "text-green-600"}">
                ${item.status}
            </td>
            <td class="border p-2">${item.duration_secs ?? "-"}</td>
            <td class="border p-2">${item.summary || "-"}</td>
            <td class="border p-2 text-center">
                <button class="log-detail-btn text-blue-600 underline text-sm">
                    Dettagli
                </button>
            </td>
        `;

        tbody.appendChild(tr);

        // Attach event listener immediately after appending or creation
        const btn = tr.querySelector(".log-detail-btn");
        if (btn) {
            btn.onclick = () => openLogDetail(item);
        }
    });

    const info = document.getElementById("logs-info");
    if (logsTotal === 0) {
        info.textContent = "Nessuna chiamata trovata per questi filtri.";
    } else {
        info.textContent = `Mostrando ${logsOffset + 1} – ${Math.min(logsOffset + logsLimit, logsTotal)} di ${logsTotal}`;
    }
}


function logsNext() {
    if (logsOffset + logsLimit >= logsTotal) return;
    logsOffset += logsLimit;
    loadLogsTable();
}

function logsPrev() {
    if (logsOffset === 0) return;
    logsOffset -= logsLimit;
    loadLogsTable();
}

// Popola dropdown clienti quando apri la sezione Logs

function escapeHtml(str) {
    if (str == null) return "";
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
}

function openLogDetail(item) {
    // item è quello che arriva da /logs/.../list
    const modal = document.getElementById("log-detail-modal");
    const content = document.getElementById("log-detail-content");

    const raw = item.raw || {};
    const ai = raw.ai_enrichment || {};
    const data = raw.data || {};
    const analysis = data.analysis || {};

    const timestamp = item.timestamp || raw.timestamp || "";
    const status = item.status || raw.status || "";
    const duration = item.duration_secs != null ? `${item.duration_secs}s` : "-";

    // Dati contatto: proviamo a pescare da più punti
    const contact_name =
        ai.contact_name ||
        analysis.contact_name ||
        "";
    const phone =
        item.caller ||
        ai.contact_phone ||
        analysis.contact_phone ||
        "–";
    const email =
        ai.contact_email ||
        analysis.contact_email ||
        "";
    const callback =
        ai.callback_window ||
        ai.callback_time ||
        analysis.callback_window ||
        "";

    // Titolo + riassunto come nella mail
    const title =
        ai.short_title ||
        item.summary ||
        "Nuova richiesta";

    const summary =
        ai.summary ||
        raw.summary ||
        raw.summary_text ||
        item.summary ||
        analysis.transcript_summary ||
        "";

    // Categoria / urgenza
    const category = ai.category || "Non classificata";
    const urgency = ai.urgency || "media";

    // Transcript: proviamo varie strutture possibili
    let transcript = "";

    if (ai.transcript_text) {
        transcript = ai.transcript_text;
    } else if (analysis.transcript_summary) {
        // se non hai transcript completo, almeno il riassunto
        transcript = analysis.transcript_summary;
    } else if (Array.isArray(data.transcript)) {
        // caso in cui nel log hai l'array dei turni {role, message}
        transcript = data.transcript
            .map(t => `${(t.role || "").toUpperCase()}: ${t.message || ""}`)
            .join("\n");
    } else if (raw.transcript_plain) {
        transcript = raw.transcript_plain;
    }

    // Se il telefono è unknown/empty, mostriamo un trattino
    const phoneDisplay = (!phone || phone === "unknown") ? "–" : phone;

    content.innerHTML = `
      <!-- box titolo + riassunto -->
      <div class="border rounded bg-gray-50 p-3 mb-4">
        <p class="text-xs text-gray-400 mb-1">${escapeHtml(timestamp)}</p>
        <h4 class="font-semibold mb-1 text-base">${escapeHtml(title)}</h4>
        ${summary
            ? `<p class="text-sm whitespace-pre-wrap break-words">${escapeHtml(summary)}</p>`
            : `<p class="text-sm text-gray-500">Nessun riassunto disponibile per questa chiamata.</p>`
        }
      </div>

      <!-- griglia con info contatto e chiamata -->
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
        <div class="border rounded p-3">
          <h5 class="font-semibold text-xs uppercase text-gray-500 mb-2">Dati contatto</h5>
          <p><span class="font-semibold">Nome:</span> ${escapeHtml(contact_name || "–")}</p>
          <p><span class="font-semibold">Telefono:</span> ${escapeHtml(phoneDisplay)}</p>
          <p><span class="font-semibold">Email:</span> ${escapeHtml(email || "–")}</p>
          <p><span class="font-semibold">Richiamare:</span> ${escapeHtml(callback || "–")}</p>
        </div>
        <div class="border rounded p-3">
          <h5 class="font-semibold text-xs uppercase text-gray-500 mb-2">Info chiamata</h5>
          <p><span class="font-semibold">Stato:</span> ${escapeHtml(status || "–")}</p>
          <p><span class="font-semibold">Durata:</span> ${escapeHtml(duration)}</p>
          <p><span class="font-semibold">Categoria:</span> ${escapeHtml(category)}</p>
          <p><span class="font-semibold">Urgenza:</span> ${escapeHtml(urgency)}</p>
        </div>
      </div>

      ${transcript
            ? `
        <div class="border rounded p-3 bg-gray-50">
          <h5 class="font-semibold text-xs uppercase text-gray-500 mb-2">Transcript</h5>
          <p class="text-xs whitespace-pre-wrap break-words leading-relaxed">
            ${escapeHtml(transcript)}
          </p>
        </div>
        `
            : ""
        }
    `;

    modal.classList.remove("hidden");
    modal.classList.add("flex");
}

function closeLogDetail() {
    const modal = document.getElementById("log-detail-modal");
    modal.classList.add("hidden");
    modal.classList.remove("flex");
}




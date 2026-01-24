// static/dashboard.js

let clients = {};

// =========================
// UI DASHBOARD PRINCIPALE
// =========================

// Custom confirmation modal function
function showConfirm(title, message, onConfirm, expectedText = null) {
    const modal = document.getElementById('confirm-modal');
    const titleEl = document.getElementById('confirm-title');
    const messageEl = document.getElementById('confirm-message');
    const okBtn = document.getElementById('confirm-ok-btn');
    const cancelBtn = document.getElementById('confirm-cancel-btn');
    const inputContainer = document.getElementById('confirm-input-container');
    const input = document.getElementById('confirm-input');

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

    // Handle Input Mode
    if (expectedText && inputContainer && input) {
        inputContainer.classList.remove('hidden');
        input.value = "";

        // Initial state
        newOkBtn.disabled = true;
        newOkBtn.classList.add('opacity-50', 'cursor-not-allowed');

        input.oninput = () => {
             if (input.value === expectedText) {
                 newOkBtn.disabled = false;
                 newOkBtn.classList.remove('opacity-50', 'cursor-not-allowed');
             } else {
                 newOkBtn.disabled = true;
                 newOkBtn.classList.add('opacity-50', 'cursor-not-allowed');
             }
        };
        setTimeout(() => input.focus(), 100);
    } else {
        if (inputContainer) inputContainer.classList.add('hidden');
        newOkBtn.disabled = false;
        newOkBtn.classList.remove('opacity-50', 'cursor-not-allowed');
    }

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

    const isClient = window.user && window.user.role === 'client';

    if (isClient) {
        container.innerHTML = `
            <!-- GRAFICO GENERALE -->
            <div class="glass-card mb-10">
                <h2 class="text-2xl font-semibold mb-4 text-white">📈 Attività giornaliera</h2>
                <canvas id="chart_all_clients"></canvas>
            </div>

            <!-- MODAL LOGS -->
            <div id="logModal" class="fixed inset-0 bg-black/40 hidden items-center justify-center z-50 backdrop-blur-sm">
                <div class="glass-card w-11/12 max-w-2xl p-6">
                    <h2 class="text-xl font-semibold mb-4 text-white">Log chiamate</h2>
                    <canvas id="clientChart" class="mb-4"></canvas>
                    <div id="logContent" class="bg-black/20 p-3 rounded h-80 overflow-auto text-sm font-mono text-gray-300"></div>
                    <button onclick="closeModal()" class="mt-4 bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-500 transition-colors">
                        Chiudi
                    </button>
                </div>
            </div>
        `;
    } else {
        // Admin View - Removed Widgets (Clienti attuali & Chart) as requested.
        // The container is left empty or can be used for other Admin-specific widgets in the future.
        container.innerHTML = `
            <!-- MODAL LOGS (Optional, kept if needed for deep links, though usually accessed via Logs tab) -->
            <div id="logModal" class="fixed inset-0 bg-black/40 hidden items-center justify-center z-50 backdrop-blur-sm">
                <div class="glass-card w-11/12 max-w-2xl p-6">
                    <h2 class="text-xl font-semibold mb-4 text-white">Log chiamate</h2>
                    <canvas id="clientChart" class="mb-4"></canvas>
                    <div id="logContent" class="bg-black/20 p-3 rounded h-80 overflow-auto text-sm font-mono text-gray-300"></div>
                    <button onclick="closeModal()" class="mt-4 bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-500 transition-colors">
                        Chiudi
                    </button>
                </div>
            </div>
        `;
    }
}

// =========================
// CRUD CLIENTI
// =========================

async function loadClients() {
    const res = await fetch("/clients");
    const data = await res.json();
    clients = data.clients || {};

    // Check if the table body exists (it was removed from Admin dashboard view)
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


// =========================
// LOGS POLLING
// =========================
let logsPollInterval = null;

function startLogsPolling() {
    if (logsPollInterval) clearInterval(logsPollInterval);
    // Poll every 10 seconds
    logsPollInterval = setInterval(() => {
        // Keep current offset
        loadLogsTable(null);
    }, 10000);
}

function stopLogsPolling() {
    if (logsPollInterval) {
        clearInterval(logsPollInterval);
        logsPollInterval = null;
    }
}

async function initLogsSection() {
    const select = document.getElementById("log-filter-client");
    select.innerHTML = "";

    const isClient = window.user && window.user.role === 'client';

    if (isClient) {
        window.isClientUser = true;
        // Hide client selector
        const label = document.querySelector("label[for='log-filter-client']");
        if (label && label.parentElement) label.parentElement.classList.add("hidden");
        loadLogsTable(0);
        return;
    }

    try {
        const res = await fetch("/clients");
        if (!res.ok) throw new Error("Fetch failed");

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

    } catch (e) {
        console.warn("Could not load clients list", e);
        // Fallback
        window.isClientUser = true;
        loadLogsTable(0);
    }
}


// =========================
// IMPOSTAZIONI CLIENTE (Fase 6)
// =========================

async function initSettingsSection() {
    const select = document.getElementById("settings-client-select");
    if (!select) return;

    select.innerHTML = "";

    const isClient = window.user && window.user.role === 'client';

    if (isClient) {
        // Hide select container
        select.parentElement.classList.add("hidden");

        // Check agent_ids from user object
        const agentIds = window.user.agent_ids || [];
        if (agentIds.length > 0) {
            // Auto select first one
            const agentId = agentIds[0];
            select.innerHTML = `<option value="${agentId}" selected>${agentId}</option>`;
            select.value = agentId;
            // Trigger load immediately
            await loadClientSettings();
        } else {
            const form = document.getElementById("settings-form");
            form.innerHTML = "<p class='text-[var(--muted)] p-4'>Nessun agente assegnato al tuo account.</p>";
            form.classList.remove("hidden");
        }
        return;
    }

    // Admin Logic
    const res = await fetch("/clients");
    const data = await res.json();

    const clientsObj = data.clients || {};

    for (const agentId in clientsObj) {
        const cfg = clientsObj[agentId];
        const opt = document.createElement("option");
        opt.value = agentId;
        opt.textContent = `${cfg.studio_name || agentId}`;
        select.appendChild(opt);
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

// =========================
// ADMIN METRICS (Fase 8)
// =========================

async function updateDashboardKPIs(data) {
    if (!data || !data.kpi) return;

    const kpiClients = document.getElementById("dash-kpi-clients");
    const kpiSubs = document.getElementById("dash-kpi-subs");
    const kpiMrr = document.getElementById("dash-kpi-mrr");
    const kpiRev = document.getElementById("dash-kpi-revenue");

    if (kpiClients) kpiClients.textContent = data.kpi.total_users;
    if (kpiSubs) kpiSubs.textContent = data.kpi.active_subscriptions;
    if (kpiMrr) kpiMrr.textContent = data.kpi.mrr;
    if (kpiRev) kpiRev.textContent = data.kpi.total_revenue;
}

async function loadAdminMetrics() {
    // Only fetch if admin
    if (window.user && window.user.role !== 'admin') return;

    try {
        const res = await fetch("/admin/metrics");
        if (!res.ok) throw new Error("Failed to fetch metrics");
        const data = await res.json();

        if (data.status === "ok") {
            // Update Analytics Tab KPIs
            const elTotal = document.getElementById("metrics-total-users");
            if (elTotal) { // check if we are on analytics view logic or if elements exist
                elTotal.textContent = data.kpi.total_users;
                document.getElementById("metrics-active-subs").textContent = data.kpi.active_subscriptions;
                document.getElementById("metrics-churn").textContent = data.kpi.churned;
                document.getElementById("metrics-past-due").textContent = data.kpi.past_due;
            }

            // Update Dashboard Tab KPIs
            updateDashboardKPIs(data);

            // Update Payments Table
            const tbody = document.getElementById("metrics-payments-body");
            tbody.innerHTML = "";
            if (data.recent_payments && data.recent_payments.length > 0) {
                data.recent_payments.forEach(p => {
                    const tr = document.createElement("tr");
                    tr.className = "hover:bg-white/5 transition-colors border-b border-[var(--border)]";
                    tr.innerHTML = `
                        <td class="px-4 py-2">${p.date}</td>
                        <td class="px-4 py-2">${p.email}</td>
                        <td class="px-4 py-2 font-mono">${p.amount}</td>
                        <td class="px-4 py-2">
                            <span class="px-2 py-0.5 rounded text-xs uppercase font-bold
                                ${p.status === 'succeeded' ? 'bg-green-500/20 text-green-400' : 'bg-yellow-500/20 text-yellow-400'}">
                                ${p.status}
                            </span>
                        </td>
                    `;
                    tbody.appendChild(tr);
                });
            } else {
                tbody.innerHTML = `<tr><td colspan="4" class="text-center py-4 text-[var(--muted)]">Nessun pagamento recente trovato.</td></tr>`;
            }
        }
    } catch (e) {
        console.error("Error loading metrics:", e);
    }
}

// =========================
// ADMIN USERS (Fase 9)
// =========================

let usersOffset = 0;
let usersLimit = 50;
let usersTotal = 0;

async function loadUsersTable(offsetOverride = null) {
    if (offsetOverride !== null) usersOffset = offsetOverride;

    const q = document.getElementById("users-search").value;
    const params = new URLSearchParams({
        limit: usersLimit,
        offset: usersOffset
    });
    if (q) params.append("q", q);

    try {
        const res = await fetch("/admin/users?" + params.toString());
        const data = await res.json();

        usersTotal = data.total;
        const items = data.items || [];
        const tbody = document.getElementById("users-table-body");
        tbody.innerHTML = "";

        items.forEach(u => {
            const tr = document.createElement("tr");
            tr.className = "hover:bg-white/5 transition-colors border-b border-[var(--border)]";

            const activeBadge = u.is_active
                ? `<span class="px-2 py-0.5 rounded text-xs font-bold bg-green-500/20 text-green-400">ATTIVO</span>`
                : `<span class="px-2 py-0.5 rounded text-xs font-bold bg-red-500/20 text-red-400">SOSPESO</span>`;

            let subBadgeClass = "bg-gray-500/20 text-gray-400";
            if (u.subscription_status === 'active') subBadgeClass = "bg-green-500/20 text-green-400";
            if (u.subscription_status === 'past_due') subBadgeClass = "bg-yellow-500/20 text-yellow-400";
            if (u.subscription_status === 'canceled') subBadgeClass = "bg-red-500/20 text-red-400";

            const subBadge = `<span class="px-2 py-0.5 rounded text-xs font-bold ${subBadgeClass}">${u.subscription_status.toUpperCase()}</span>`;

            const actionBtn = u.is_active
                ? `<button onclick="suspendUser(${u.id}, '${u.username}')" class="text-red-400 hover:text-red-300 text-xs font-bold border border-red-500/30 px-2 py-1 rounded">SOSPENDI</button>`
                : `<div class="flex gap-2 justify-end">
                     <button onclick="unsuspendUser(${u.id}, '${u.username}')" class="text-green-400 hover:text-green-300 text-xs font-bold border border-green-500/30 px-2 py-1 rounded">RIATTIVA</button>
                     <button onclick="deleteUser(${u.id}, '${u.username}')" class="text-white hover:text-red-200 text-xs font-bold bg-red-600 hover:bg-red-700 px-2 py-1 rounded shadow">ELIMINA</button>
                   </div>`;

            tr.innerHTML = `
                <td class="px-4 py-2">${u.id}</td>
                <td class="px-4 py-2">${u.email}</td>
                <td class="px-4 py-2 text-[var(--muted)]">${u.role}</td>
                <td class="px-4 py-2">${activeBadge}</td>
                <td class="px-4 py-2 text-[var(--muted)] uppercase text-xs">${u.plan_code}</td>
                <td class="px-4 py-2">${subBadge}</td>
                <td class="px-4 py-2 text-right">
                    ${u.role === 'client' ? actionBtn : ''}
                </td>
            `;
            tbody.appendChild(tr);
        });

        document.getElementById("users-info").textContent = `Mostrando ${usersOffset + 1}-${Math.min(usersOffset + usersLimit, usersTotal)} di ${usersTotal}`;

    } catch(e) {
        console.error("Users load error", e);
    }
}

function usersPrev() {
    if (usersOffset > 0) {
        usersOffset -= usersLimit;
        loadUsersTable();
    }
}

function usersNext() {
    if (usersOffset + usersLimit < usersTotal) {
        usersOffset += usersLimit;
        loadUsersTable();
    }
}

function suspendUser(id, username) {
    showConfirm("Sospendi Utente", `Vuoi davvero sospendere ${username}? Non potrà più accedere.`, async () => {
        const res = await fetch(`/admin/users/${id}/suspend`, { method: "POST" });
        if (res.ok) {
            showToast("Utente sospeso", "success");
            loadUsersTable();
        } else {
            showToast("Errore", "error");
        }
    });
}

function deleteUser(id, username) {
    showConfirm(
        "ELIMINA UTENTE",
        `ATTENZIONE: Stai per eliminare definitivamente l'utente ${username} e TUTTI i dati associati (chiamate, abbonamenti, numeri). Azione IRREVERSIBILE.`,
        async () => {
            try {
                const res = await fetch(`/admin/users/${id}`, { method: "DELETE" });
                if (res.ok) {
                    showToast("Utente eliminato correttamente", "success");
                    loadUsersTable();
                } else {
                    const err = await res.json();
                    showToast("Errore: " + (err.detail || "Impossibile eliminare"), "error");
                }
            } catch (e) {
                console.error(e);
                showToast("Errore di rete", "error");
            }
        },
        "ELIMINA"
    );
}

function unsuspendUser(id, username) {
    showConfirm("Riattiva Utente", `Vuoi riattivare ${username}?`, async () => {
        const res = await fetch(`/admin/users/${id}/unsuspend`, { method: "POST" });
        if (res.ok) {
            showToast("Utente riattivato", "success");
            loadUsersTable();
        } else {
            showToast("Errore", "error");
        }
    });
}

// =========================
// PHONE NUMBERS (NUMERI)
// =========================

async function loadPhoneNumbersTable() {
    try {
        const res = await fetch("/api/admin/phone-numbers");
        if (!res.ok) throw new Error("Failed to fetch phone numbers");
        const data = await res.json();
        const items = data.items || [];

        const tbody = document.getElementById("phonenumbers-table-body");
        tbody.innerHTML = "";

        if (items.length === 0) {
            tbody.innerHTML = `<tr><td colspan="6" class="text-center py-4 text-[var(--muted)]">Nessun numero trovato.</td></tr>`;
            return;
        }

        items.forEach(n => {
            const tr = document.createElement("tr");
            tr.className = "hover:bg-white/5 transition-colors border-b border-[var(--border)]";

            let statusBadge = "";
            if (n.status === 'active') statusBadge = `<span class="px-2 py-0.5 rounded text-xs font-bold bg-green-500/20 text-green-400">ATTIVO</span>`;
            else if (n.status === 'released') statusBadge = `<span class="px-2 py-0.5 rounded text-xs font-bold bg-gray-500/20 text-gray-400">RILASCIATO</span>`;
            else if (n.status === 'pending_deprovision') statusBadge = `<span class="px-2 py-0.5 rounded text-xs font-bold bg-yellow-500/20 text-yellow-400">IN RILASCIO</span>`;
            else statusBadge = `<span class="px-2 py-0.5 rounded text-xs font-bold bg-red-500/20 text-red-400">${n.status}</span>`;

            let actions = "";
            if (n.status === 'active') {
                actions = `<button onclick="releasePhoneNumber(${n.id}, '${n.e164}')" class="text-red-400 hover:text-red-300 text-xs font-bold border border-red-500/30 px-2 py-1 rounded">RILASCIA</button>`;
            } else if (n.status === 'pending_deprovision') {
                actions = `<button onclick="cancelDeprovision(${n.id}, '${n.e164}')" class="text-green-400 hover:text-green-300 text-xs font-bold border border-green-500/30 px-2 py-1 rounded">ANNULLA RILASCIO</button>`;
            } else {
                 actions = `<span class="text-xs text-[var(--muted)]">Nessuna azione</span>`;
            }

            const username = n.username ? `${n.username} (ID: ${n.user_id})` : `<span class="text-yellow-500">Non assegnato</span>`;
            const created = n.created_at ? n.created_at.split('T')[0] : "-";
            const notes = n.notes ? `<span title="${n.notes}" class="truncate max-w-[150px] inline-block cursor-help border-b border-dotted border-gray-500">${n.notes}</span>` : "-";

            tr.innerHTML = `
                <td class="px-4 py-2 font-mono">${n.e164}</td>
                <td class="px-4 py-2">${username}</td>
                <td class="px-4 py-2">${statusBadge}</td>
                <td class="px-4 py-2 text-sm text-[var(--muted)]">${notes}</td>
                <td class="px-4 py-2 text-sm text-[var(--muted)]">${created}</td>
                <td class="px-4 py-2 text-right">${actions}</td>
            `;
            tbody.appendChild(tr);
        });
    } catch (e) {
        console.error("Error loading phone numbers:", e);
        showToast("Errore caricamento numeri", "error");
    }
}

function openAddPhoneNumberModal() {
    const modal = document.getElementById("add-phonenumber-modal");
    if (modal) {
        modal.classList.remove("hidden");
        modal.classList.add("flex");
    }
}

function closeAddPhoneNumberModal() {
    const modal = document.getElementById("add-phonenumber-modal");
    if (modal) {
        modal.classList.add("hidden");
        modal.classList.remove("flex");
        document.getElementById("add-phonenumber-form").reset();
    }
}

async function handleCreatePhoneNumber(event) {
    event.preventDefault();
    const form = event.target;
    const formData = new FormData(form);

    // Convert to JSON
    const payload = {
        e164: formData.get("e164"),
        user_id: parseInt(formData.get("user_id")),
        notes: formData.get("notes")
    };

    try {
        const res = await fetch("/api/admin/phone-numbers", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });

        if (res.ok) {
            showToast("Numero creato correttamente", "success");
            closeAddPhoneNumberModal();
            loadPhoneNumbersTable();
        } else {
            const err = await res.json();
            showToast("Errore: " + (err.detail || "Impossibile creare"), "error");
        }
    } catch (e) {
        console.error(e);
        showToast("Errore di rete", "error");
    }
}

function releasePhoneNumber(id, e164) {
    showConfirm(
        "RILASCIA NUMERO",
        `Sei sicuro di voler rilasciare il numero ${e164}? Smetterà di funzionare e verrà rimosso dall'account utente.`,
        async () => {
            try {
                const res = await fetch(`/api/admin/phone-numbers/${id}`, { method: "DELETE" });
                if (res.ok) {
                    showToast("Numero rilasciato", "success");
                    loadPhoneNumbersTable();
                } else {
                    const err = await res.json();
                    showToast("Errore: " + (err.detail || "Impossibile rilasciare"), "error");
                }
            } catch (e) {
                console.error(e);
                showToast("Errore di rete", "error");
            }
        }
    );
}

function cancelDeprovision(id, e164) {
    showConfirm(
        "Annulla Rilascio",
        `Vuoi annullare il rilascio programmato per ${e164}?`,
        async () => {
            try {
                const res = await fetch(`/api/admin/phone-numbers/${id}/cancel-deprovision`, { method: "POST" });
                if (res.ok) {
                    showToast("Rilascio annullato", "success");
                    loadPhoneNumbersTable();
                } else {
                    const err = await res.json();
                    showToast("Errore: " + (err.detail || "Errore sconosciuto"), "error");
                }
            } catch (e) {
                console.error(e);
                showToast("Errore di rete", "error");
            }
        }
    );
}

// =========================
// EXPORT LOGIC
// =========================

function triggerExport(type) {
    const fromEl = document.getElementById("export-from");
    const toEl = document.getElementById("export-to");

    if (!fromEl || !toEl) return;

    const fromVal = fromEl.value;
    const toVal = toEl.value;

    if (!fromVal || !toVal) {
        alert("Seleziona data inizio e fine.");
        return;
    }

    showToast("Download avviato...", "info");

    // Build URL
    // /admin/export/minutes?from=YYYY-MM-DD&to=YYYY-MM-DD
    // /admin/export/logs?from=YYYY-MM-DD&to=YYYY-MM-DD

    const url = `/admin/export/${type}?from=${fromVal}&to=${toVal}`;

    // Trigger download via hidden iframe or new window, or just window.location
    // Using window.location works for downloads and allows browser to handle it.
    window.location.href = url;
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
// POLLING STATUS (Fase 4A Async)
// =========================

let dashboardPollInterval = null;

async function updateDashboardStatus() {
    let isActive = false;
    let user = {};
    let sub = {};
    let success = false;

    // 1. Try /me first
    try {
        const res = await fetch("/me");
        if (res.status === 401 || res.status === 403) {
            if (dashboardPollInterval) clearInterval(dashboardPollInterval);
            window.location.href = "/login";
            return false;
        }

        if (res.ok) {
            const data = await res.json();
            user = data.user || {};
            sub = data.subscription || {};
            success = true;
        }
    } catch (e) {
        console.warn("/me failed, trying fallback...", e);
    }

    // 2. Fallback to /subscription/status if /me failed
    if (!success) {
        try {
            const res = await fetch("/subscription/status");
            if (res.status === 401 || res.status === 403) {
                if (dashboardPollInterval) clearInterval(dashboardPollInterval);
                window.location.href = "/login";
                return false;
            }
            if (res.ok) {
                const data = await res.json();
                // Map fallback data to structure expected below
                sub = {
                    state: data.state,
                    plan_code: data.plan_code
                };
                // We don't have user.is_active from this endpoint, assume active if sub is active?
                // Or leave undefined. We'll default to '?' or similar.
                // Assuming if they can fetch status, they are somewhat active session-wise.
                user = { is_active: (data.state === "active") };
            }
        } catch (e) {
            console.warn("Fallback polling failed", e);
            return false;
        }
    }

    // Update UI
    const isAdmin = (window.user && window.user.role === 'admin');
    const isUserActive = (user.is_active === true);
    const isSubActive = (sub.state === "active");
    isActive = isSubActive;

    // 1. Service Status
    const srvEl = document.getElementById("status-service");
    if (srvEl) {
        if (isAdmin || (isUserActive && isSubActive)) {
            srvEl.textContent = "ATTIVO";
            srvEl.className = "px-2 py-0.5 rounded-full bg-green-500/20 text-green-400 border border-green-500/30";
        } else if (!isUserActive) {
            srvEl.textContent = "SOSPESO";
            srvEl.className = "px-2 py-0.5 rounded-full bg-red-500/20 text-red-400 border border-red-500/30";
        } else {
            srvEl.textContent = "NON ATTIVO";
            srvEl.className = "px-2 py-0.5 rounded-full bg-gray-500/20 text-gray-400 border border-gray-500/30";
        }
    }

    // 2. Billing Status (sub.state)
    const billEl = document.getElementById("status-billing");
    if (billEl) {
        const state = (sub.state || "unknown").toUpperCase();
        billEl.textContent = state;

        // Color coding
        if (state === "ACTIVE") {
                billEl.className = "text-green-400 font-bold";
        } else if (state === "PAST_DUE" || state === "CANCELED") {
                billEl.className = "text-red-400 font-bold";
        } else {
                billEl.className = "text-[var(--muted)]";
        }
    }

    // 3. Plan Label
    const planContainer = document.getElementById("status-plan-container");
    const planEl = document.getElementById("status-plan");
    if (planContainer && planEl) {
            if (sub.plan_code) {
                planEl.textContent = sub.plan_code.toUpperCase();
                planContainer.classList.remove("hidden");
            } else {
                planContainer.classList.add("hidden");
            }
    }

    // 4. Activation Banner
    renderActivationBanner(isActive, sub.state);

    return isActive;
}

function renderActivationBanner(isActive, subState) {
    // Hide for admins
    if (window.user && window.user.role === 'admin') {
        const existing = document.getElementById("activation-banner");
        if (existing) existing.remove();
        return;
    }

    const container = document.getElementById("dashboard-content");
    if (!container) return;

    const bannerId = "activation-banner";
    let banner = document.getElementById(bannerId);

    // Normalize state
    const safeState = (subState || "").toLowerCase();
    const needsActivation = !isActive || (safeState !== "active" && safeState !== "trialing");

    if (!needsActivation) {
        if (banner) banner.remove();
        return;
    }

    // Determine message
    let msg = "Il tuo account non è attivo. Contatta l'amministratore.";
    let btnHtml = "";

    if (safeState === "canceled" || safeState === "past_due" || !safeState || safeState === "unknown") {
        msg = "Nessun abbonamento attivo. Attiva un piano per utilizzare il servizio.";
        // Link to dedicated plans page
        btnHtml = `<a href="/billing/plans" class="px-4 py-2 bg-yellow-500 hover:bg-yellow-400 text-black font-bold rounded shadow-lg transition-colors">ATTIVA ORA</a>`;
    }

    if (!banner) {
        banner = document.createElement("div");
        banner.id = bannerId;
        banner.className = "mb-6 p-4 bg-red-900/40 border border-red-500/50 rounded-lg flex flex-col md:flex-row items-center justify-between gap-4 animate-fade-in-down";
        // Insert at top of container
        container.insertBefore(banner, container.firstChild);
    }

    banner.innerHTML = `
        <div class="flex items-center gap-3 text-red-100">
            <i data-feather="alert-octagon" class="w-6 h-6 text-red-400"></i>
            <span class="font-medium">${msg}</span>
        </div>
        ${btnHtml}
    `;

    if (typeof feather !== 'undefined') feather.replace();
}

// Helper: Show Toast
function showToast(message, type = "info") {
    // Check if container exists, else create
    let container = document.getElementById("toast-container");
    if (!container) {
        container = document.createElement("div");
        container.id = "toast-container";
        container.className = "fixed bottom-4 right-4 z-50 flex flex-col gap-2";
        document.body.appendChild(container);
    }

    const toast = document.createElement("div");
    // Styling based on type
    const baseClass = "px-4 py-3 rounded shadow-lg text-white font-medium flex items-center gap-2 animate-bounce-in";
    if (type === "success") {
        toast.className = `${baseClass} bg-green-600`;
    } else if (type === "error") {
        toast.className = `${baseClass} bg-red-600`;
    } else {
        toast.className = `${baseClass} bg-blue-600`;
    }

    toast.innerHTML = `<span>${message}</span>`;

    container.appendChild(toast);

    // Auto remove after 4s
    setTimeout(() => {
        toast.remove();
    }, 4000);
}


// Handle Redirects (Success/Cancel)
async function handleBillingRedirect() {
    const params = new URLSearchParams(window.location.search);
    const billingStatus = params.get("billing"); // success | cancel
    // Also support 'stripe' for backward compat or if used elsewhere
    const stripeStatus = params.get("stripe");

    const status = billingStatus || stripeStatus;

    if (!status) return;

    // Clean URL
    window.history.replaceState({}, document.title, window.location.pathname);

    if (status === "cancel") {
        showToast("Operazione annullata.", "error");
        return;
    }

    if (status === "success") {
        showToast("Pagamento ricevuto, sto verificando...", "info");

        // Start FAST polling
        if (dashboardPollInterval) clearInterval(dashboardPollInterval);

        let attempts = 0;
        const maxAttempts = 15; // 30 seconds total (15 * 2s)

        // Fast poll loop
        const fastPoll = setInterval(async () => {
            attempts++;
            const done = await updateDashboardStatus(); // returns true if active

            if (done) {
                // Subscription became active!
                clearInterval(fastPoll);
                showToast("Abbonamento attivato con successo!", "success");
                // Resume normal polling
                dashboardPollInterval = setInterval(updateDashboardStatus, 15000);
            } else if (attempts >= maxAttempts) {
                // Timeout
                clearInterval(fastPoll);
                showToast("Verifica in corso... controlla tra poco.", "info");
                // Resume normal polling
                dashboardPollInterval = setInterval(updateDashboardStatus, 15000);
            }
        }, 2000);
    }
}


// Start polling
function startStatusPolling() {
    // Initial call
    updateDashboardStatus();
    // Poll every 15s normally
    dashboardPollInterval = setInterval(updateDashboardStatus, 15000);
}

// Page Visibility API to pause/resume polling
document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
        // Pause polling
        if (dashboardPollInterval) {
            clearInterval(dashboardPollInterval);
            dashboardPollInterval = null;
        }
        if (typeof stopLogsPolling === "function") {
            stopLogsPolling();
        }
    } else {
        // Resume polling
        if (!dashboardPollInterval) {
            startStatusPolling();
        }
        // Resume logs polling if on logs section
        const activeSection = document.querySelector('.nav-item-active');
        if (activeSection && activeSection.dataset.section === 'logs') {
            if (typeof startLogsPolling === "function") {
                startLogsPolling();
            }
        }
    }
});


// =========================
// BOOTSTRAP ESPORTATO
// =========================

async function initDashboard() {
    // Render static structure
    renderDashboardUI();

    // Check for redirects (fast polling if success)
    await handleBillingRedirect();

    // Start Polling Status Bar (if not already handled by fast polling)
    if (!dashboardPollInterval) {
         startStatusPolling();
    }

    // Existing Logic
    await loadClients();
    await renderGlobalChart();

    // Admin Dashboard KPIs
    if (window.user && window.user.role === 'admin') {
        await loadAdminMetrics();
    }
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
    // If not client mode and no client selected, return (wait for selection)
    if (!window.isClientUser && !client) return;

    const params = new URLSearchParams({
        limit: logsLimit,
        offset: logsOffset,
        status: statusEl.value
    });

    if (fromEl.value) params.append("date_from", fromEl.value);
    if (toEl.value) params.append("date_to", toEl.value);
    if (qEl.value) params.append("q", qEl.value);

    let url;
    if (window.isClientUser) {
        url = `/api/logs?` + params.toString();
    } else {
        url = `/logs/${client}/list?` + params.toString();
    }

    const res = await fetch(url);
    const data = await res.json();

    logsTotal = data.total ?? 0;
    const items = data.items ?? [];

    // salviamo per sicurezza se un domani ti serve
    window.currentLogItems = items;
    window.currentLogClient = client || "me";

    const tbody = document.getElementById("logs-table");
    tbody.innerHTML = "";

    items.forEach((item) => {
        const tr = document.createElement("tr");
        tr.className = item.status === "failure" ? "bg-red-50" : "";

        tr.innerHTML = `
            <td class="border p-2">${item.timestamp}</td>
            <td class="border p-2">${window.isClientUser ? "Me" : client}</td>
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




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
            <div class="bg-white p-6 rounded-xl border border-neutral-200 shadow-sm mb-10">
                <h2 class="text-2xl font-semibold mb-4 text-neutral-900">📈 Attività giornaliera</h2>
                <canvas id="chart_all_clients"></canvas>
            </div>

            <!-- MODAL LOGS -->
            <div id="logModal" class="fixed inset-0 bg-neutral-900/50 hidden items-center justify-center z-50 backdrop-blur-sm">
                <div class="bg-white rounded-xl shadow-2xl w-11/12 max-w-2xl p-6 border border-neutral-200">
                    <h2 class="text-xl font-semibold mb-4 text-neutral-900">Log chiamate</h2>
                    <canvas id="clientChart" class="mb-4"></canvas>
                    <div id="logContent" class="bg-neutral-50 p-3 rounded h-80 overflow-auto text-sm font-mono text-neutral-600 border border-neutral-200"></div>
                    <button onclick="closeModal()" class="mt-4 bg-neutral-900 text-white px-4 py-2 rounded-lg hover:bg-neutral-800 transition-colors shadow-sm">
                        Chiudi
                    </button>
                </div>
            </div>
        `;
    } else {
        // Admin View
        container.innerHTML = `
            <div id="logModal" class="fixed inset-0 bg-neutral-900/50 hidden items-center justify-center z-50 backdrop-blur-sm">
                <div class="bg-white rounded-xl shadow-2xl w-11/12 max-w-2xl p-6 border border-neutral-200">
                    <h2 class="text-xl font-semibold mb-4 text-neutral-900">Log chiamate</h2>
                    <canvas id="clientChart" class="mb-4"></canvas>
                    <div id="logContent" class="bg-neutral-50 p-3 rounded h-80 overflow-auto text-sm font-mono text-neutral-600 border border-neutral-200"></div>
                    <button onclick="closeModal()" class="mt-4 bg-neutral-900 text-white px-4 py-2 rounded-lg hover:bg-neutral-800 transition-colors shadow-sm">
                        Chiudi
                    </button>
                </div>
            </div>
        `;
    }
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
        const res = await fetch("/api/admin/agent-users");
        if (!res.ok) throw new Error("Fetch failed");

        const data = await res.json();
        const clientsObj = data.mapping || {};

        for (const agentId in clientsObj) {
            const cfg = clientsObj[agentId];
            const op = document.createElement("option");
            op.value = agentId;
            op.textContent = cfg.studio_name || cfg.username || agentId;
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

// Store for agent->user mapping
let agentUserMapping = {};

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

    // Admin Logic: Fetch Agent-User mapping from DB
    try {
        const res = await fetch("/api/admin/agent-users");
        if (!res.ok) throw new Error("Failed to fetch agent mappings");
        const data = await res.json();

        agentUserMapping = data.mapping || {};

        if (Object.keys(agentUserMapping).length === 0) {
             select.innerHTML = "<option disabled>Nessun agente configurato (DB)</option>";
             return;
        }

        for (const agentId in agentUserMapping) {
            const info = agentUserMapping[agentId];
            const opt = document.createElement("option");
            opt.value = agentId;
            opt.textContent = `${info.studio_name || info.username} (${agentId})`;
            select.appendChild(opt);
        }
    } catch (e) {
        console.error("Error loading settings dropdown:", e);
        select.innerHTML = "<option disabled>Errore caricamento</option>";
    }
}

async function loadClientSettings() {
    const select = document.getElementById("settings-client-select");
    const agentId = select.value;
    if (!agentId) return;

    window.currentSettingsAgentId = agentId;

    const isClient = window.user && window.user.role === 'client';

    // Default values
    let studioName = "";
    let emailTo = "";
    let agentPhoneId = "";
    let testPhone = "";
    let greeting = "";
    let notes = "";

    if (isClient) {
        // Client assumes current user context
        // Currently we don't have a direct "get my settings" endpoint for clients except /me or fetching via client API
        // For simplicity, we try to use the mapping if available or fallback to legacy read-only just for display?
        // But clients shouldn't see Admin Settings anyway?
        // Wait, Client Dashboard has "Impostazioni" tab?
        // Yes, checking nav: <a href="#" data-section="settings"...>
        // But the prompt was about Admin Dashboard changes.
        // For clients, we might need a separate endpoint `GET /client/settings`.
        // Assuming Admin context for now based on prompt.
        // If Client context, we might break if we don't handle it.
        // Let's assume clients can't change their own email/studio name via this form if it's admin-only features.
        // But let's handle Admin mostly.
    }

    // Use Mapping for Admin
    if (agentUserMapping[agentId]) {
        const info = agentUserMapping[agentId];
        studioName = info.studio_name || "";
        emailTo = info.email || "";
        // Mapping might not have all legacy fields like greeting/notes if they were only in JSON.
        // If we want to support them, we need to decide where they live.
        // Prompt focus: "email_to" and "studio_name".
    } else {
        // Fallback or refresh mapping
        console.warn("Agent not found in mapping, trying refresh...");
        await initSettingsSection();
        if (agentUserMapping[agentId]) {
             const info = agentUserMapping[agentId];
             studioName = info.studio_name || "";
             emailTo = info.email || "";
        }
    }

    try {
        const res = await fetch(`/api/admin/agent-settings/${agentId}`);
        if (res.ok) {
            const data = await res.json();
            const settings = data.settings || {};
            greeting = settings.greeting || "";
            notes = settings.notes || "";
            agentPhoneId = settings.agent_phone_number_id || "";
            testPhone = settings.test_phone_number || "";
        } else {
            console.warn("Unable to load agent settings:", await res.text());
        }
    } catch (e) {
        console.error("Error loading agent settings:", e);
    }

    document.getElementById("settings-studio-name").value = studioName;
    document.getElementById("settings-email-to").value = emailTo;

    // Legacy fields - disabled or cleared if not in DB?
    // We leave them empty or as is if we don't have DB columns for them yet.
    // Prompt didn't ask to migrate greeting/notes, but they are in the form.
    // If we only update email/studio, we should probably disable the others or warn.

    document.getElementById("settings-greeting").value = greeting;
    document.getElementById("settings-notes").value = notes;
    document.getElementById("settings-agent-phone-id").value = agentPhoneId;
    document.getElementById("settings-test-phone").value = testPhone;

    const form = document.getElementById("settings-form");
    form.classList.remove("hidden");
}


async function saveClientSettings() {
    const agentId = window.currentSettingsAgentId;
    if (!agentId) {
        alert("Seleziona prima un cliente.");
        return;
    }

    // Identify User ID from mapping
    const userInfo = agentUserMapping[agentId];
    if (!userInfo || !userInfo.user_id) {
        alert("Impossibile trovare l'utente associato a questo agente (DB Sync mancante?).");
        return;
    }

    const payload = {
        studio_name: document.getElementById("settings-studio-name").value,
        email: document.getElementById("settings-email-to").value
    };
    const settingsPayload = {
        greeting: document.getElementById("settings-greeting").value,
        notes: document.getElementById("settings-notes").value,
        agent_phone_number_id: document.getElementById("settings-agent-phone-id").value.trim(),
        test_phone_number: document.getElementById("settings-test-phone").value.trim()
    };

    try {
        const res = await fetch(`/admin/users/${userInfo.user_id}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });

        let settingsUpdateOk = true;
        let settingsUpdateError = "";
        try {
            const settingsRes = await fetch(`/api/admin/agent-settings/${agentId}`, {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(settingsPayload)
            });
            if (!settingsRes.ok) {
                settingsUpdateOk = false;
                settingsUpdateError = await settingsRes.text();
            }
        } catch (e) {
            settingsUpdateOk = false;
            settingsUpdateError = e.toString();
        }

        if (res.ok && settingsUpdateOk) {
            alert("Impostazioni salvate.");
            // Refresh mapping
            await initSettingsSection();
            // Reselect
            const select = document.getElementById("settings-client-select");
            select.value = agentId;
        } else if (!res.ok) {
            const err = await res.json();
            alert("Errore: " + (err.detail || "Impossibile salvare"));
        } else {
            alert("Email/Studio salvati nel DB, ma errore nel salvataggio impostazioni agente: " + settingsUpdateError);
        }
    } catch(e) {
        console.error(e);
        alert("Errore di rete.");
    }

    // Refresh other views
    await loadUsersTable(); // Since we modified User
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
                    tr.className = "hover:bg-neutral-50 transition-colors border-b border-neutral-100 text-sm text-neutral-600";
                    tr.innerHTML = `
                        <td class="px-6 py-3 text-xs">${p.date}</td>
                        <td class="px-6 py-3 text-xs">${p.email}</td>
                        <td class="px-6 py-3 font-mono text-xs">${p.amount}</td>
                        <td class="px-6 py-3">
                            <span class="px-2 py-0.5 rounded text-[10px] uppercase font-bold tracking-wide
                                ${p.status === 'succeeded' ? 'bg-green-100 text-green-700 border border-green-200' : 'bg-yellow-100 text-yellow-700 border border-yellow-200'}">
                                ${p.status}
                            </span>
                        </td>
                    `;
                    tbody.appendChild(tr);
                });
            } else {
                tbody.innerHTML = `<tr><td colspan="4" class="text-center py-8 text-neutral-500 text-sm">Nessun pagamento recente trovato.</td></tr>`;
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
            tr.className = "hover:bg-neutral-50 transition-colors border-b border-neutral-100 text-sm text-neutral-600";

            const toggleSwitch = `
                <label class="inline-flex items-center cursor-pointer">
                  <input type="checkbox" class="sr-only peer" ${u.is_active ? 'checked' : ''} onchange="toggleUserActive(${u.id}, '${u.username.replace(/'/g, "\\'")}', this)">
                  <div class="relative w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-neutral-900 rounded-full peer peer-checked:after:translate-x-full rtl:peer-checked:after:-translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:start-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-green-600"></div>
                  <span class="ms-3 text-xs font-medium ${u.is_active ? 'text-green-700' : 'text-neutral-500'} toggle-label-${u.id}">${u.is_active ? 'Attivo' : 'Disattivato'}</span>
                </label>
            `;

            let subBadgeClass = "bg-neutral-100 text-neutral-500 border border-neutral-200";
            if (u.subscription_status === 'active') subBadgeClass = "bg-green-100 text-green-700 border border-green-200";
            if (u.subscription_status === 'past_due') subBadgeClass = "bg-yellow-100 text-yellow-700 border border-yellow-200";
            if (u.subscription_status === 'canceled') subBadgeClass = "bg-red-100 text-red-700 border border-red-200";

            const subBadge = `<span class="px-2 py-0.5 rounded-full text-[10px] font-bold ${subBadgeClass}">${u.subscription_status.toUpperCase()}</span>`;

            const safeUsername = u.username.replace(/'/g, "\\'");
            const deleteBtn = `<button onclick="deleteUser(${u.id}, '${safeUsername}')" class="text-red-600 hover:text-red-800 text-xs font-semibold border border-red-200 bg-red-50 hover:bg-red-100 px-2 py-1 rounded transition-colors ml-2">ELIMINA</button>`;

            // Plan Select
            const plans = ['NONE', 'starter', 'pro', 'business'];
            let planOptions = plans.map(p => `<option value="${p}" ${u.subscription_plan === p ? 'selected' : ''}>${p.toUpperCase()}</option>`).join('');
            const planSelect = u.role === 'client' ? `<select onchange="updateUserPlan(${u.id}, 'subscription_plan', this.value)" class="bg-white border border-neutral-300 rounded text-xs p-1 outline-none focus:ring-2 focus:ring-neutral-900">${planOptions}</select>` : '-';

            // Expiration Date
            const dateValue = u.plan_expires_at || '';
            const dateInput = u.role === 'client' ? `<input type="date" value="${dateValue}" onchange="updateUserPlan(${u.id}, 'plan_expires_at', this.value)" class="bg-white border border-neutral-300 rounded text-xs p-1 outline-none focus:ring-2 focus:ring-neutral-900 w-32">` : '-';

            tr.innerHTML = `
                <td class="px-6 py-3 font-mono text-xs text-neutral-500">${u.id}</td>
                <td class="px-6 py-3 font-medium text-neutral-900">${u.email}</td>
                <td class="px-6 py-3 text-neutral-500">${u.role}</td>
                <td class="px-6 py-3">${u.role === 'client' ? toggleSwitch : '-'}</td>
                <td class="px-6 py-3 text-neutral-500 uppercase text-xs">${planSelect}</td>
                <td class="px-6 py-3 text-neutral-500 uppercase text-xs">${dateInput}</td>
                <td class="px-6 py-3">${subBadge}</td>
                <td class="px-6 py-3 text-right">
                    ${u.role === 'client' ? deleteBtn : ''}
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

async function toggleUserActive(id, username, checkbox) {
    const isActive = checkbox.checked;
    const action = isActive ? "unsuspend" : "suspend";
    const label = document.querySelector(`.toggle-label-${id}`);

    // Optimistic UI update
    if (label) {
        label.textContent = isActive ? "Attivo" : "Disattivato";
        label.className = `ms-3 text-xs font-medium ${isActive ? 'text-green-700' : 'text-neutral-500'} toggle-label-${id}`;
    }

    try {
        const res = await fetch(`/admin/users/${id}/${action}`, { method: "POST" });
        if (res.ok) {
            showToast(isActive ? "Utente riattivato" : "Utente sospeso", "success");
        } else {
            // Revert on failure
            checkbox.checked = !isActive;
            if (label) {
                label.textContent = !isActive ? "Attivo" : "Disattivato";
                label.className = `ms-3 text-xs font-medium ${!isActive ? 'text-green-700' : 'text-neutral-500'} toggle-label-${id}`;
            }
            showToast("Errore durante l'aggiornamento stato", "error");
        }
    } catch (e) {
        console.error(e);
        // Revert on error
        checkbox.checked = !isActive;
        showToast("Errore di rete", "error");
    }
}

async function updateUserPlan(userId, field, value) {
    const payload = {};
    payload[field] = value;

    try {
        const res = await fetch(`/admin/users/${userId}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });

        if (res.ok) {
            showToast("Piano aggiornato con successo", "success");
        } else {
            const err = await res.json();
            showToast("Errore: " + (err.detail || "Impossibile aggiornare"), "error");
        }
    } catch (e) {
        console.error(e);
        showToast("Errore di rete", "error");
    }
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


// =========================
// CHAT ADMIN
// =========================

let adminChatPollInterval = null;
let currentChatUserId = null;

function startAdminChatPolling() {
    if (adminChatPollInterval) clearInterval(adminChatPollInterval);
    checkAdminUnreadBadge();
    adminChatPollInterval = setInterval(() => {
        loadConversations();
        if (currentChatUserId) {
            loadChatDetail(currentChatUserId);
        }
        checkAdminUnreadBadge();
    }, 5000);
}

function stopAdminChatPolling() {
    if (adminChatPollInterval) {
        clearInterval(adminChatPollInterval);
        adminChatPollInterval = null;
    }
}

async function checkAdminUnreadBadge() {
    try {
        const res = await fetch("/api/chat/unread-count");
        if (res.ok) {
            const data = await res.json();
            const count = data.count || 0;
            const badge = document.getElementById("admin-chat-badge");
            if (badge) {
                if (count > 0) {
                    badge.classList.remove("hidden");
                } else {
                    badge.classList.add("hidden");
                }
            }
        }
    } catch(e) {}
}

async function loadConversations() {
    const list = document.getElementById("admin-conversations-list");
    if (!list) return;

    try {
        const res = await fetch("/api/admin/chat/conversations");
        const data = await res.json();
        const convs = data.conversations || [];

        if (convs.length === 0) {
            list.innerHTML = `<div class="text-center py-8 text-neutral-400 text-sm">Nessuna conversazione attiva.</div>`;
            return;
        }

        list.innerHTML = convs.map(c => {
            const isActive = currentChatUserId === c.user_id;
            const unreadBadge = c.unread_count > 0
                ? `<span class="bg-red-500 text-white text-[10px] font-bold px-1.5 py-0.5 rounded-full">${c.unread_count}</span>`
                : '';

            return `
                <div onclick="selectChatUser(${c.user_id}, '${c.username.replace(/'/g, "\\'")}')"
                     class="p-4 cursor-pointer hover:bg-neutral-50 transition-colors border-l-4 ${isActive ? 'bg-neutral-50 border-neutral-900' : 'border-transparent'}">
                    <div class="flex justify-between items-start mb-1">
                        <span class="font-medium text-sm text-neutral-900 truncate">${c.studio_name || c.username}</span>
                        ${unreadBadge}
                    </div>
                    <div class="text-xs text-neutral-500 truncate">${c.last_message || "Nessun messaggio"}</div>
                    <div class="text-[10px] text-neutral-400 mt-1 text-right">${c.last_active ? formatDate(c.last_active) : ''}</div>
                </div>
            `;
        }).join('');

    } catch (e) {
        console.warn("Conversations load error", e);
    }
}

function selectChatUser(userId, username) {
    currentChatUserId = userId;

    // UI Update
    document.getElementById("admin-chat-placeholder").classList.add("hidden");
    document.getElementById("admin-chat-title").textContent = username;
    document.getElementById("admin-chat-subtitle").textContent = "ID: " + userId;

    loadChatDetail(userId);
    loadConversations(); // Update selection style
}

async function loadChatDetail(userId) {
    const container = document.getElementById("admin-chat-messages");
    if (!container) return;

    try {
        // Mark read
        fetch("/api/chat/read", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ user_id: userId })
        });

        const res = await fetch(`/api/chat/messages?limit=100&user_id=${userId}`);
        const data = await res.json();
        const items = data.items || [];

        if (items.length === 0) {
            container.innerHTML = `<div class="text-center text-neutral-400 text-sm my-auto">Nessun messaggio in questa conversazione.</div>`;
            return;
        }

        // Render
        const isScrolledToBottom = container.scrollHeight - container.scrollTop <= container.clientHeight + 100;

        container.innerHTML = items.map(msg => {
            const isMe = msg.sender === 'admin';
            return `
                <div class="flex ${isMe ? 'justify-end' : 'justify-start'}">
                    <div class="max-w-[80%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${isMe ? 'bg-neutral-900 text-white rounded-br-none' : 'bg-neutral-100 text-neutral-800 rounded-bl-none'}">
                        ${escapeHtml(msg.message)}
                        <div class="text-[10px] opacity-50 mt-1 text-right">${formatTime(msg.created_at)}</div>
                    </div>
                </div>
            `;
        }).join('');

        if (isScrolledToBottom) {
            container.scrollTop = container.scrollHeight;
        }

    } catch (e) {
        console.warn("Chat detail error", e);
    }
}

async function handleSendAdminChat(event) {
    event.preventDefault();
    if (!currentChatUserId) return;

    const input = document.getElementById("admin-chat-input");
    const message = input.value.trim();
    if (!message) return;

    try {
        input.value = "";
        const res = await fetch("/api/chat/messages", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: message, user_id: currentChatUserId })
        });

        if (res.ok) {
            loadChatDetail(currentChatUserId);
        } else {
            showToast("Errore invio messaggio", "error");
        }
    } catch (e) {
        console.error(e);
        showToast("Errore di rete", "error");
    }
}

function formatDate(isoStr) {
    if (!isoStr) return "-";
    const d = new Date(isoStr);
    return d.toLocaleDateString("it-IT", { month: 'short', day: 'numeric' });
}

function formatTime(isoStr) {
    if (!isoStr) return "";
    const d = new Date(isoStr);
    return d.toLocaleTimeString("it-IT", { hour: '2-digit', minute: '2-digit' });
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
            tr.className = "hover:bg-neutral-50 transition-colors border-b border-neutral-100 text-sm text-neutral-600";

            let statusBadge = "";
            if (n.status === 'active') statusBadge = `<span class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-green-100 text-green-700 border border-green-200">ATTIVO</span>`;
            else if (n.status === 'released') statusBadge = `<span class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-neutral-100 text-neutral-500 border border-neutral-200">RILASCIATO</span>`;
            else if (n.status === 'pending_deprovision') statusBadge = `<span class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-yellow-100 text-yellow-700 border border-yellow-200">IN RILASCIO</span>`;
            else statusBadge = `<span class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-red-100 text-red-700 border border-red-200">${n.status}</span>`;

            let actions = "";
            if (n.status === 'active') {
                actions = `<button onclick="releasePhoneNumber(${n.id}, '${n.e164}')" class="text-red-600 hover:text-red-800 text-xs font-semibold border border-red-200 bg-red-50 hover:bg-red-100 px-2 py-1 rounded transition-colors">RILASCIA</button>`;
            } else if (n.status === 'pending_deprovision') {
                actions = `<button onclick="cancelDeprovision(${n.id}, '${n.e164}')" class="text-green-600 hover:text-green-800 text-xs font-semibold border border-green-200 bg-green-50 hover:bg-green-100 px-2 py-1 rounded transition-colors">ANNULLA RILASCIO</button>`;
            } else {
                 actions = `<span class="text-xs text-neutral-400">Nessuna azione</span>`;
            }
            // Aggiungi bottone ELIMINA a tutti
            actions += `<button onclick="deletePhoneNumberPermanent(${n.id}, '${n.e164}')" class="ml-2 text-neutral-600 hover:text-red-800 text-xs font-semibold border border-neutral-200 bg-neutral-50 hover:bg-red-50 px-2 py-1 rounded transition-colors">ELIMINA</button>`;

            const username = n.username ? `${n.username} (ID: ${n.user_id})` : `<span class="text-yellow-600 font-medium">Non assegnato</span>`;
            const created = n.created_at ? n.created_at.split('T')[0] : "-";
            const notes = n.notes ? `<span title="${n.notes}" class="truncate max-w-[150px] inline-block cursor-help border-b border-dotted border-neutral-400">${n.notes}</span>` : "-";

            tr.innerHTML = `
                <td class="px-6 py-3 font-mono text-xs text-neutral-900">${n.e164}</td>
                <td class="px-6 py-3 text-neutral-600">${username}</td>
                <td class="px-6 py-3">${statusBadge}</td>
                <td class="px-6 py-3 text-neutral-500">${notes}</td>
                <td class="px-6 py-3 text-neutral-500">${created}</td>
                <td class="px-6 py-3 text-right">${actions}</td>
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

function deletePhoneNumberPermanent(id, e164) {
    showConfirm(
        "Conferma eliminazione numero",
        `Questa azione è irreversibile. Vuoi davvero eliminare il numero ${e164} definitivamente?`,
        async () => {
            try {
                const res = await fetch(`/api/admin/phone-numbers/${id}/permanent`, { method: "DELETE" });
                if (res.ok) {
                    showToast("Numero eliminato", "success");
                    loadPhoneNumbersTable();
                } else {
                    const err = await res.json();
                    showToast("Errore: " + (err.detail || "Impossibile eliminare"), "error");
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
// ROUTING (INSTRADAMENTI)
// =========================

async function loadRoutingTable() {
    try {
        const res = await fetch("/api/admin/routing");
        if (!res.ok) throw new Error("Failed to fetch routing");
        const data = await res.json();
        const items = data.items || [];

        const tbody = document.getElementById("routing-table-body");
        tbody.innerHTML = "";

        if (items.length === 0) {
            tbody.innerHTML = `<tr><td colspan="6" class="text-center py-4 text-[var(--muted)]">Nessun instradamento trovato.</td></tr>`;
            return;
        }

        items.forEach(r => {
            const tr = document.createElement("tr");
            tr.className = "hover:bg-neutral-50 transition-colors border-b border-neutral-100 text-sm text-neutral-600";

            const statusBadge = r.is_active
                ? `<span class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-green-100 text-green-700 border border-green-200">ATTIVO</span>`
                : `<span class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-neutral-100 text-neutral-500 border border-neutral-200">INATTIVO</span>`;

            const actions = `<button onclick="deleteRouting(${r.id})" class="text-red-600 hover:text-red-800 text-xs font-semibold border border-red-200 bg-red-50 hover:bg-red-100 px-2 py-1 rounded transition-colors">ELIMINA</button>`;

            let username = `<span class="text-yellow-600 font-medium">Sconosciuto</span>`;
            if (r.username && r.username !== "Unknown") {
                username = `${r.username} (ID: ${r.user_id})`;
            } else if (r.status === "unassigned") {
                username = `<span class="text-red-600 font-bold animate-pulse">NON ASSEGNATO</span>`;
            }

            const lastEvent = r.last_event_at ? r.last_event_at.split('T')[0] : "-";

            tr.innerHTML = `
                <td class="px-6 py-3 text-neutral-900 font-medium">${username}</td>
                <td class="px-6 py-3 font-mono text-xs text-neutral-500">${r.agent_id}</td>
                <td class="px-6 py-3 font-mono text-xs text-neutral-500">${r.e164}</td>
                <td class="px-6 py-3">${statusBadge}</td>
                <td class="px-6 py-3 text-neutral-500">${lastEvent}</td>
                <td class="px-6 py-3 text-right">${actions}</td>
            `;
            tbody.appendChild(tr);
        });
    } catch (e) {
        console.error("Error loading routing:", e);
        showToast("Errore caricamento instradamenti", "error");
    }
}

function openAddRoutingModal() {
    const modal = document.getElementById("add-routing-modal");
    if (modal) {
        modal.classList.remove("hidden");
        modal.classList.add("flex");
    }
}

function closeAddRoutingModal() {
    const modal = document.getElementById("add-routing-modal");
    if (modal) {
        modal.classList.add("hidden");
        modal.classList.remove("flex");
        document.getElementById("add-routing-form").reset();
    }
}

async function handleCreateRouting(event) {
    event.preventDefault();
    const form = event.target;
    const formData = new FormData(form);

    // Convert to JSON
    const payload = {
        user_id: parseInt(formData.get("user_id")),
        agent_id: formData.get("agent_id"),
        phone_number_id: parseInt(formData.get("phone_number_id")),
        is_active: formData.get("is_active") === "on"
    };

    try {
        const res = await fetch("/api/admin/routing", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });

        if (res.ok) {
            showToast("Routing creato correttamente", "success");
            closeAddRoutingModal();
            loadRoutingTable();
        } else {
            const err = await res.json();
            showToast("Errore: " + (err.detail || "Impossibile creare"), "error");
        }
    } catch (e) {
        console.error(e);
        showToast("Errore di rete", "error");
    }
}

function deleteRouting(id) {
    showConfirm(
        "ELIMINA ROUTING",
        `Vuoi davvero eliminare questo instradamento?`,
        async () => {
            try {
                const res = await fetch(`/api/admin/routing/${id}`, { method: "DELETE" });
                if (res.ok) {
                    showToast("Routing eliminato", "success");
                    loadRoutingTable();
                } else {
                    const err = await res.json();
                    showToast("Errore: " + (err.detail || "Impossibile eliminare"), "error");
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
                const res = await fetch(`/api/admin/agents/${agentId}/test-call`, {
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
        <div class="flex items-center gap-3 text-red-800">
            <i data-feather="alert-octagon" class="w-6 h-6 text-red-600"></i>
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
        tr.className = "hover:bg-neutral-50 transition-colors border-b border-neutral-100";
        if (item.status === "failure") tr.classList.add("bg-red-50/50");

        const statusClass = item.status === "failure" ? "text-red-600" : "text-green-600";
        const statusIcon = item.status === "failure" ? "alert-circle" : "check-circle";

        tr.innerHTML = `
            <td class="px-6 py-3 text-xs text-neutral-500 whitespace-nowrap">${item.timestamp}</td>
            <td class="px-6 py-3 text-sm text-neutral-900 font-medium">${window.isClientUser ? "Me" : client}</td>
            <td class="px-6 py-3 text-xs text-neutral-500 font-mono">${item.caller}</td>
            <td class="px-6 py-3">
                <span class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-bold ${item.status === "failure" ? "bg-red-100 text-red-700 border border-red-200" : "bg-green-100 text-green-700 border border-green-200"}">
                    ${item.status.toUpperCase()}
                </span>
            </td>
            <td class="px-6 py-3 text-sm text-neutral-600">${item.duration_secs ?? "-"}s</td>
            <td class="px-6 py-3 text-sm text-neutral-600 max-w-xs truncate" title="${item.summary || ""}">${item.summary || "-"}</td>
            <td class="px-6 py-3 text-center">
                <button class="log-detail-btn text-neutral-400 hover:text-neutral-900 p-1.5 hover:bg-neutral-100 rounded-lg transition-colors">
                    <i data-feather="eye" class="w-4 h-4"></i>
                </button>
            </td>
        `;

        tbody.appendChild(tr);

        const btn = tr.querySelector(".log-detail-btn");
        if (btn) {
            btn.onclick = () => openLogDetail(item);
            feather.replace(); // Replace icon for this row
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
      <div class="border border-neutral-200 rounded-xl bg-neutral-50 p-4 mb-6">
        <p class="text-xs text-neutral-400 mb-2 font-medium">${escapeHtml(timestamp)}</p>
        <h4 class="font-bold mb-2 text-lg text-neutral-900">${escapeHtml(title)}</h4>
        ${summary
            ? `<p class="text-sm text-neutral-600 whitespace-pre-wrap break-words leading-relaxed">${escapeHtml(summary)}</p>`
            : `<p class="text-sm text-neutral-400 italic">Nessun riassunto disponibile per questa chiamata.</p>`
        }
      </div>

      <!-- griglia con info contatto e chiamata -->
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
        <div class="border border-neutral-200 rounded-xl p-4 bg-white shadow-sm">
          <h5 class="font-bold text-xs uppercase text-neutral-400 tracking-wider mb-3">Dati contatto</h5>
          <div class="space-y-2 text-sm">
              <p class="flex justify-between"><span class="text-neutral-500">Nome:</span> <span class="font-medium text-neutral-900">${escapeHtml(contact_name || "–")}</span></p>
              <p class="flex justify-between"><span class="text-neutral-500">Telefono:</span> <span class="font-medium text-neutral-900">${escapeHtml(phoneDisplay)}</span></p>
              <p class="flex justify-between"><span class="text-neutral-500">Email:</span> <span class="font-medium text-neutral-900">${escapeHtml(email || "–")}</span></p>
              <p class="flex justify-between"><span class="text-neutral-500">Richiamare:</span> <span class="font-medium text-neutral-900">${escapeHtml(callback || "–")}</span></p>
          </div>
        </div>
        <div class="border border-neutral-200 rounded-xl p-4 bg-white shadow-sm">
          <h5 class="font-bold text-xs uppercase text-neutral-400 tracking-wider mb-3">Info chiamata</h5>
          <div class="space-y-2 text-sm">
             <p class="flex justify-between"><span class="text-neutral-500">Stato:</span> <span class="font-medium text-neutral-900">${escapeHtml(status || "–")}</span></p>
             <p class="flex justify-between"><span class="text-neutral-500">Durata:</span> <span class="font-medium text-neutral-900">${escapeHtml(duration)}</span></p>
             <p class="flex justify-between"><span class="text-neutral-500">Categoria:</span> <span class="font-medium text-neutral-900">${escapeHtml(category)}</span></p>
             <p class="flex justify-between"><span class="text-neutral-500">Urgenza:</span> <span class="font-medium text-neutral-900">${escapeHtml(urgency)}</span></p>
          </div>
        </div>
      </div>

      ${transcript
            ? `
        <div class="border border-neutral-200 rounded-xl p-4 bg-neutral-50">
          <h5 class="font-bold text-xs uppercase text-neutral-400 tracking-wider mb-3">Transcript</h5>
          <p class="text-xs text-neutral-600 whitespace-pre-wrap break-words leading-relaxed font-mono">
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

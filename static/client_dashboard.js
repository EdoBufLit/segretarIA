// static/client_dashboard.js

// =========================
// INIT & NAVIGATION
// =========================

document.addEventListener("DOMContentLoaded", () => {
    initDashboard();
});

function openSection(name) {
    // Update Title
    const titles = {
        'dashboard': 'Panoramica',
        'logs': 'Storico Chiamate',
        'analytics': 'Analisi',
        'numbers': 'Numeri Assegnati',
        'settings': 'Impostazioni'
    };
    const el = document.getElementById('page-title');
    if (el) el.textContent = titles[name] || 'Dashboard';

    // Toggle Sections
    document.querySelectorAll(".section").forEach(s => s.classList.add("hidden"));
    const section = document.getElementById(`section-${name}`);
    if (section) section.classList.remove("hidden");

    // Update Sidebar Nav
    document.querySelectorAll(".sidebar .nav-item").forEach(a => {
        a.classList.remove("nav-item-active");
    });
    const activeLink = document.querySelector(`.sidebar a[data-section="${name}"]`);
    if (activeLink) {
        activeLink.classList.add("nav-item-active");
    }

    // Lazy Load
    if (name === "dashboard") {
         loadAnalyticsData(); // For KPI cards and main chart
    }
    if (name === "analytics") {
        renderHeatmap();
    }
    if (name === "logs") {
        loadLogsTable(0);
    }
    if (name === "numbers") {
        loadClientNumbers();
    }
    if (name === "chat") {
        loadChatMessages();
        startChatPolling();
    } else {
        stopChatPolling();
    }
}

async function initDashboard() {
    openSection('dashboard');
    startStatusPolling();
    startActiveCallPolling();
}

// =========================
// ACTIVE CALL LOGIC
// =========================

let activeCallTimeout = null;
let consecutiveEmptyPolls = 0;
let isPollingStopped = false;

function startActiveCallPolling() {
    // Reset
    consecutiveEmptyPolls = 0;
    isPollingStopped = false;
    if (activeCallTimeout) clearTimeout(activeCallTimeout);

    // Visibility listener
    document.removeEventListener("visibilitychange", handleVisibilityChange);
    document.addEventListener("visibilitychange", handleVisibilityChange);

    checkActiveCall();
}

function handleVisibilityChange() {
    if (!document.hidden && !isPollingStopped) {
         if (activeCallTimeout) clearTimeout(activeCallTimeout);
         checkActiveCall();
    }
}

async function manualRefresh() {
    const btn = document.getElementById("force-refresh-call");
    if(btn) btn.classList.add("animate-spin");

    // Reset backoff logic
    isPollingStopped = false;
    consecutiveEmptyPolls = 0;
    if (activeCallTimeout) clearTimeout(activeCallTimeout);

    try {
        await checkActiveCall();
    } finally {
        if(btn) btn.classList.remove("animate-spin");
    }
}

async function checkActiveCall() {
    if (document.hidden) return; // Resume on visibility change

    let nextDelay = 3000;

    try {
        const res = await fetch("/api/client/active-call");
        if (!res.ok) {
             consecutiveEmptyPolls++;
        } else {
            const data = await res.json();
            const call = data.active_call;

            renderActiveCallBanner(call);

            if (call) {
                consecutiveEmptyPolls = 0;
                // If ended, stop polling
                if (['ended', 'completed', 'failed'].includes(call.status)) {
                    isPollingStopped = true;
                    return;
                }
            } else {
                consecutiveEmptyPolls++;
            }
        }
    } catch(e) {
        consecutiveEmptyPolls++;
    }

    // Backoff
    if (consecutiveEmptyPolls >= 3) nextDelay = 10000;
    if (consecutiveEmptyPolls >= 6) nextDelay = 30000;

    if (!isPollingStopped) {
        activeCallTimeout = setTimeout(checkActiveCall, nextDelay);
    }
}

function renderActiveCallBanner(call) {
    const banner = document.getElementById("active-call-banner");
    const info = document.getElementById("active-call-info");
    const actions = document.getElementById("active-call-actions");

    if (!call || !['ai_active', 'human_requested'].includes(call.status)) {
        if (banner) banner.classList.add("hidden");
        return;
    }

    if (banner) banner.classList.remove("hidden");
    if (info) info.innerHTML = `Da: <span class="font-mono font-medium text-neutral-900">${call.caller_number || 'Sconosciuto'}</span>`;

    if (!actions) return;

    // Render Button Logic
    if (call.status === 'human_requested') {
        actions.innerHTML = `
            <div class="flex items-center gap-2 text-green-600 bg-green-50 px-4 py-2 rounded-lg border border-green-100">
                <div class="w-2 h-2 bg-green-500 rounded-full animate-pulse"></div>
                <span class="text-sm font-medium">Trasferimento in corso...</span>
            </div>
        `;
    } else if (call.status === 'ai_active') {
        if (call.office_phone_e164) {
            actions.innerHTML = `
                <button onclick="bargeInCall('${call.call_sid}')" id="btn-barge-${call.call_sid}" class="w-full sm:w-auto flex items-center justify-center gap-2 bg-neutral-900 hover:bg-neutral-800 text-white px-5 py-2.5 rounded-lg shadow-sm transition-all active:scale-95 group" title="Interrompe l'IA e collega la chiamata allo studio">
                    <i data-feather="phone-forwarded" class="w-4 h-4 group-hover:translate-x-0.5 transition-transform"></i>
                    <div class="text-left">
                        <div class="text-sm font-semibold">Rispondi ora</div>
                        <div class="text-[10px] opacity-80 leading-none">Trasferisci allo studio</div>
                    </div>
                </button>
            `;
            feather.replace();
        } else {
            actions.innerHTML = `
                <span class="text-xs text-neutral-400 bg-neutral-50 px-3 py-2 rounded border border-neutral-100">
                    Per trasferire serve un numero studio.
                </span>
            `;
        }
    }
}

async function bargeInCall(callSid) {
    const btn = document.getElementById(`btn-barge-${callSid}`);
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<span class="loader w-4 h-4 border-2 border-white/20 border-t-white rounded-full animate-spin"></span><span class="text-sm ml-2">Trasferimento...</span>`;
    }

    try {
        const res = await fetch(`/calls/${callSid}/barge-in`, { method: "POST" });
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || "Errore");
        }

        // Optimistic UI update
        const actions = document.getElementById("active-call-actions");
        if(actions) {
            actions.innerHTML = `
                <div class="flex items-center gap-2 text-green-600 bg-green-50 px-4 py-2 rounded-lg border border-green-100">
                    <i data-feather="check" class="w-4 h-4"></i>
                    <span class="text-sm font-medium">Richiesta inviata</span>
                </div>
            `;
            feather.replace();
        }

        // Force immediate check
        setTimeout(checkActiveCall, 1000);

    } catch (e) {
        alert("Impossibile trasferire: " + e.message);
        checkActiveCall(); // Re-render state
    }
}

// =========================
// DATA FETCHING & UI
// =========================

let globalChart = null;

async function loadAnalyticsData() {
    try {
        const res = await fetch("/api/analytics");
        if (!res.ok) throw new Error("Analytics fetch failed");
        const data = await res.json();

        // Update KPI Cards
        updateKpis(data);

        // Render Main Chart (Calls per day)
        renderMainChart(data);

    } catch (e) {
        console.warn("Could not load analytics data", e);
    }
}

function updateKpis(data) {
    const today = data.calls_today || 0;
    const week = data.calls_last_7_days || 0;
    const errors = data.errors || 0;

    const elToday = document.getElementById("kpi-today");
    const elWeek = document.getElementById("kpi-week");
    const elErrors = document.getElementById("kpi-errors");

    if (elToday) elToday.textContent = today;
    if (elWeek) elWeek.textContent = week;
    if (elErrors) elErrors.textContent = errors;
}

function renderMainChart(data) {
    const canvas = document.getElementById("chart_all_clients");
    if (!canvas) return;

    const days = Object.keys(data.by_day || {}).sort();
    const counts = days.map(d => data.by_day[d]);

    if (globalChart) {
        globalChart.destroy();
    }

    const ctx = canvas.getContext("2d");
    const gradient = ctx.createLinearGradient(0, 0, 0, canvas.height);
    gradient.addColorStop(0, "rgba(31, 111, 92, 0.25)");
    gradient.addColorStop(1, "rgba(31, 111, 92, 0.02)");

    globalChart = new Chart(canvas, {
        type: "line",
        data: {
            labels: days,
            datasets: [{
                label: "Chiamate",
                data: counts,
                borderColor: "#1f6f5c",
                backgroundColor: gradient,
                tension: 0.35,
                fill: true,
                pointRadius: 2,
                pointHoverRadius: 4,
                pointBackgroundColor: "#1f6f5c"
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: { precision: 0, color: '#6e6a64', font: { family: 'IBM Plex Sans', size: 11 } },
                    grid: { color: '#ece6df', drawBorder: false }
                },
                x: {
                    ticks: { color: '#6e6a64', font: { family: 'IBM Plex Sans', size: 11 } },
                    grid: { display: false }
                }
            },
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: '#1b1a18',
                    titleFont: { family: 'IBM Plex Sans', size: 13 },
                    bodyFont: { family: 'IBM Plex Sans', size: 12 },
                    padding: 10,
                    cornerRadius: 8,
                    displayColors: false
                }
            }
        }
    });
}

async function renderHeatmap() {
    const container = document.getElementById("heatmap-container");
    if (!container) return;

    try {
        const res = await fetch("/api/analytics");
        if (!res.ok) throw new Error("Heatmap fetch failed");
        const data = await res.json();

        // 1. Lists
        const catList = document.getElementById("analytics-category-list");
        const urgList = document.getElementById("analytics-urgency-list");

        if (catList && data.by_category) {
            catList.innerHTML = "";
            const sortedCats = Object.entries(data.by_category).sort((a,b) => b[1] - a[1]);
            sortedCats.forEach(([cat, count]) => {
                const li = document.createElement("li");
                li.className = "flex justify-between items-center py-1";
                li.innerHTML = `<span class="capitalize">${cat}</span><span class="font-medium bg-neutral-100 px-2 py-0.5 rounded text-neutral-600 text-xs">${count}</span>`;
                catList.appendChild(li);
            });
        }
        if (urgList && data.by_urgency) {
            urgList.innerHTML = "";
            const sortedUrg = Object.entries(data.by_urgency).sort((a,b) => b[1] - a[1]);
            sortedUrg.forEach(([urg, count]) => {
                const li = document.createElement("li");
                li.className = "flex justify-between items-center py-1";
                li.innerHTML = `<span class="capitalize">${urg}</span><span class="font-medium bg-neutral-100 px-2 py-0.5 rounded text-neutral-600 text-xs">${count}</span>`;
                urgList.appendChild(li);
            });
        }

        // 2. Heatmap Grid
        const heatmap = data.heatmap; // 24 rows, 7 cols
        const days = ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"];

        let html = `
            <div class="min-w-[600px] border border-neutral-100 rounded-lg overflow-hidden bg-white">
                <div class="flex bg-neutral-50 border-b border-neutral-100">
                    <div class="w-16 p-2"></div>
                    ${days.map(d => `<div class="flex-1 p-2 text-center text-xs font-semibold text-neutral-500">${d}</div>`).join('')}
                </div>
        `;

        for (let hour = 0; hour < 24; hour++) {
            const hourLabel = `${hour.toString().padStart(2, '0')}:00`;
            html += `<div class="flex border-b border-neutral-50 last:border-b-0">
                        <div class="w-16 p-2 text-xs text-neutral-400 font-mono text-right border-r border-neutral-50 bg-neutral-50/50">${hourLabel}</div>`;

            for (let day = 0; day < 7; day++) {
                const val = heatmap[hour][day];
                let bgClass = "bg-white";
                let textClass = "text-transparent";

                if (val > 0) {
                    textClass = "text-white font-bold";
                    if (val < 2) bgClass = "bg-neutral-200";
                    else if (val < 5) bgClass = "bg-neutral-400";
                    else if (val < 10) bgClass = "bg-neutral-600";
                    else bgClass = "bg-neutral-800";
                }

                html += `
                    <div class="flex-1 p-1 h-8 flex items-center justify-center border-r border-neutral-50 last:border-r-0 ${bgClass} transition-colors hover:opacity-90" title="${days[day]} ${hourLabel}: ${val} chiamate">
                        <span class="text-[10px] ${textClass}">${val > 0 ? val : ''}</span>
                    </div>
                `;
            }
            html += `</div>`;
        }
        html += `</div>`;

        container.innerHTML = html;

    } catch (e) {
        console.warn("Could not render heatmap", e);
        container.innerHTML = "<p class='text-red-500 text-sm'>Errore caricamento dati.</p>";
    }
}

// =========================
// NUMBERS SECTION
// =========================

async function loadClientNumbers() {
    const tbody = document.getElementById("numbers-table-body");
    if (!tbody) return;

    try {
        const res = await fetch("/api/client/phone-numbers");
        if (!res.ok) throw new Error("Fetch failed");
        const data = await res.json();

        tbody.innerHTML = "";

        if (!data.items || data.items.length === 0) {
            tbody.innerHTML = `<tr><td colspan="5" class="text-center py-8 text-neutral-500 text-sm">Nessun numero attivo è associato al tuo account al momento.</td></tr>`;
            return;
        }

        data.items.forEach(item => {
            const tr = document.createElement("tr");
            tr.className = "hover:bg-neutral-50 transition-colors";

            const statusBadge = item.status === 'active'
                ? `<span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-green-100 text-green-800">Attivo</span>`
                : `<span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-neutral-100 text-neutral-800">${item.status}</span>`;

            tr.innerHTML = `
                <td class="px-6 py-4 whitespace-nowrap">
                    <div class="text-sm font-medium text-neutral-900 font-mono">${item.phone_number}</div>
                </td>
                <td class="px-6 py-4 whitespace-nowrap">
                    <div class="text-sm text-neutral-900">${escapeHtml(item.display_name)}</div>
                    <div class="text-xs text-neutral-500 font-mono">${escapeHtml(item.agent_id)}</div>
                </td>
                <td class="px-6 py-4">
                    <div class="text-sm text-neutral-500 max-w-xs truncate" title="${escapeHtml(item.notes)}">${escapeHtml(item.notes || "-")}</div>
                </td>
                <td class="px-6 py-4 whitespace-nowrap">
                    ${statusBadge}
                </td>
                <td class="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                    <button onclick="copyToClipboard('${item.phone_number}')" class="text-neutral-400 hover:text-neutral-900 transition-colors p-1" title="Copia numero">
                        <i data-feather="copy" class="w-4 h-4"></i>
                    </button>
                </td>
            `;
            tbody.appendChild(tr);
        });
        feather.replace();

    } catch (e) {
        console.error("Error loading numbers", e);
        tbody.innerHTML = `<tr><td colspan="5" class="text-center py-8 text-red-500 text-sm">Errore caricamento dati.</td></tr>`;
    }
}

function copyToClipboard(text) {
    if (!text || text === "N/D") return;
    navigator.clipboard.writeText(text).then(() => {
        // Optional: show toast
        const btn = document.activeElement;
        if(btn) {
            const original = btn.innerHTML;
            btn.innerHTML = `<i data-feather="check" class="w-4 h-4 text-green-600"></i>`;
            feather.replace();
            setTimeout(() => {
                btn.innerHTML = original;
                feather.replace();
            }, 2000);
        }
    });
}

// =========================
// LOGS
// =========================

let logsOffset = 0;
let logsLimit = 15;
let logsTotal = 0;

async function loadLogsTable(offsetOverride = null) {
    if (offsetOverride !== null) logsOffset = offsetOverride;

    const params = new URLSearchParams({
        limit: logsLimit,
        offset: logsOffset
    });

    try {
        const res = await fetch("/api/logs?" + params.toString());
        const data = await res.json();

        logsTotal = data.total ?? 0;
        const items = data.items ?? [];
        const tbody = document.getElementById("logs-table");
        tbody.innerHTML = "";

        if (items.length === 0) {
            tbody.innerHTML = `<tr><td colspan="6" class="text-center py-8 text-neutral-500 text-sm">Nessuna chiamata trovata.</td></tr>`;
        } else {
            items.forEach((item) => {
                const tr = document.createElement("tr");
                tr.className = "hover:bg-neutral-50 transition-colors group";
                if (item.status === "failure") tr.classList.add("bg-red-50");

                const duration = item.duration_secs ? `${item.duration_secs}s` : "-";

                let statusBadge = `<span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-green-100 text-green-800">Successo</span>`;
                if (item.status === "failure") {
                    statusBadge = `<span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-red-100 text-red-800">Fallita</span>`;
                }

                tr.innerHTML = `
                    <td>
                        <div class="text-sm font-medium text-neutral-900">${formatDate(item.timestamp)}</div>
                        <div class="text-xs text-neutral-500">${formatTime(item.timestamp)}</div>
                    </td>
                    <td class="text-sm text-neutral-600 font-mono">${item.caller}</td>
                    <td>${statusBadge}</td>
                    <td class="text-sm text-neutral-600">${duration}</td>
                    <td>
                        <div class="text-sm text-neutral-900 max-w-xs truncate" title="${escapeHtml(item.summary)}">${escapeHtml(item.summary || "-")}</div>
                    </td>
                    <td class="text-right">
                        <button class="log-detail-btn text-neutral-400 hover:text-blue-600 p-1 rounded-md hover:bg-blue-50 transition-colors">
                            <i data-feather="eye" class="w-4 h-4"></i>
                        </button>
                    </td>
                `;
                tbody.appendChild(tr);

                // Bind click
                tr.querySelector(".log-detail-btn").addEventListener("click", () => openLogDetail(item));
            });
            feather.replace();
        }

        const info = document.getElementById("logs-info");
        info.textContent = `Mostrando ${logsOffset + 1} – ${Math.min(logsOffset + logsLimit, logsTotal)} di ${logsTotal}`;

        document.getElementById("logs-prev").disabled = logsOffset === 0;
        document.getElementById("logs-next").disabled = logsOffset + logsLimit >= logsTotal;

    } catch (e) {
        console.error("Logs load error", e);
    }
}

function logsNext() {
    if (logsOffset + logsLimit < logsTotal) {
        logsOffset += logsLimit;
        loadLogsTable();
    }
}
function logsPrev() {
    if (logsOffset > 0) {
        logsOffset -= logsLimit;
        loadLogsTable();
    }
}

// =========================
// UTILS
// =========================

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

function escapeHtml(str) {
    if (str == null) return "";
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
}

// Modal Detail Logic
function openLogDetail(item) {
    const modal = document.getElementById("log-detail-modal");
    const content = document.getElementById("log-detail-content");

    const raw = item.raw || {};
    const ai = raw.ai_enrichment || {};
    const data = raw.data || {};
    const analysis = data.analysis || {};

    const summary = item.summary || ai.summary || "";
    const transcript = ai.transcript_text || analysis.transcript_summary || "";

    content.innerHTML = `
        <div>
            <h4 class="text-xs font-semibold text-neutral-500 uppercase tracking-wider mb-2">Riassunto</h4>
            <div class="bg-neutral-50 p-4 rounded-lg border border-neutral-100 text-neutral-700 text-sm leading-relaxed">
                ${escapeHtml(summary)}
            </div>
        </div>

        <div class="grid grid-cols-2 gap-4">
            <div class="bg-neutral-50 p-3 rounded-lg border border-neutral-100">
                <span class="text-xs text-neutral-400 block mb-1">Data & Ora</span>
                <div class="text-sm font-medium text-neutral-900">${formatDate(item.timestamp)} ${formatTime(item.timestamp)}</div>
            </div>
             <div class="bg-neutral-50 p-3 rounded-lg border border-neutral-100">
                <span class="text-xs text-neutral-400 block mb-1">Durata</span>
                <div class="text-sm font-medium text-neutral-900">${item.duration_secs || 0}s</div>
            </div>
             <div class="bg-neutral-50 p-3 rounded-lg border border-neutral-100">
                <span class="text-xs text-neutral-400 block mb-1">Categoria</span>
                <div class="text-sm font-medium text-neutral-900">${escapeHtml(ai.category || "-")}</div>
            </div>
             <div class="bg-neutral-50 p-3 rounded-lg border border-neutral-100">
                <span class="text-xs text-neutral-400 block mb-1">Urgenza</span>
                <div class="text-sm font-medium text-neutral-900">${escapeHtml(ai.urgency || "-")}</div>
            </div>
        </div>

        ${transcript ? `
            <div>
                <h4 class="text-xs font-semibold text-neutral-500 uppercase tracking-wider mb-2">Trascrizione</h4>
                <div class="bg-white border border-neutral-200 p-4 rounded-lg text-xs text-neutral-600 whitespace-pre-wrap max-h-60 overflow-y-auto font-mono">
                    ${escapeHtml(transcript)}
                </div>
            </div>
        ` : ''}
    `;

    modal.classList.remove("hidden");
    modal.classList.add("flex");

    // Animate in
    const card = modal.querySelector("div[role='dialog']");
    card.classList.remove("scale-95", "opacity-0");
    card.classList.add("scale-100", "opacity-100");
}

function closeLogDetail() {
    const modal = document.getElementById("log-detail-modal");
    const card = modal.querySelector("div[role='dialog']");

    card.classList.remove("scale-100", "opacity-100");
    card.classList.add("scale-95", "opacity-0");

    setTimeout(() => {
        modal.classList.add("hidden");
        modal.classList.remove("flex");
    }, 150);
}

// =========================
// STATUS POLLING
// =========================
let statusInterval = null;

async function startStatusPolling() {
    updateStatus();
    statusInterval = setInterval(updateStatus, 15000);
}

async function updateStatus() {
    try {
        const res = await fetch("/subscription/status");
        if (res.status === 401 || res.status === 403) {
            window.location.reload();
            return;
        }

        // Also check unread messages count for badge
        const badgeRes = await fetch("/api/chat/unread-count");
        if (badgeRes.ok) {
            const data = await badgeRes.json();
            const count = data.count || 0;
            const badge = document.getElementById("nav-chat-badge");
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

// =========================
// CHAT LOGIC
// =========================

let chatPollInterval = null;

function startChatPolling() {
    if (chatPollInterval) clearInterval(chatPollInterval);
    chatPollInterval = setInterval(loadChatMessages, 5000); // 5s polling
}

function stopChatPolling() {
    if (chatPollInterval) {
        clearInterval(chatPollInterval);
        chatPollInterval = null;
    }
}

async function loadChatMessages() {
    const container = document.getElementById("chat-messages-container");
    if (!container) return;

    try {
        const res = await fetch("/api/chat/messages?limit=100");
        if (!res.ok) throw new Error("Chat fetch failed");
        const data = await res.json();

        const items = data.items || [];

        if (items.length === 0) {
            container.innerHTML = `<div class="text-center text-neutral-400 text-sm my-auto">Nessun messaggio. Scrivi qui sotto per contattare il supporto.</div>`;
            return;
        }

        // Render messages
        // Simple logic: if new items > old items, scroll to bottom
        const isScrolledToBottom = container.scrollHeight - container.scrollTop <= container.clientHeight + 100;

        container.innerHTML = items.map(msg => {
            const isMe = msg.sender === 'client';
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

        // Mark as read if we are here
        // Optimistic, fire and forget
        fetch("/api/chat/read", { method: "POST", body: JSON.stringify({}), headers: { "Content-Type": "application/json" } });

    } catch (e) {
        console.warn("Chat load error", e);
    }
}

async function handleSendChat(event) {
    event.preventDefault();
    const input = document.getElementById("chat-input");
    const message = input.value.trim();
    if (!message) return;

    try {
        // Optimistic UI append? Or just wait poll. Wait poll is safer for sync.
        // But clear input immediately.
        input.value = "";

        const res = await fetch("/api/chat/messages", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: message })
        });

        if (res.ok) {
            loadChatMessages(); // Refresh immediately
        } else {
            alert("Errore nell'invio del messaggio.");
        }
    } catch (e) {
        console.error("Send error", e);
        alert("Errore di rete.");
    }
}

// Mobile Menu
const btn = document.getElementById('mobile-menu-btn');
const sidebar = document.querySelector('.sidebar');

if (btn && sidebar) {
    btn.addEventListener('click', () => {
        sidebar.classList.toggle('hidden');
        sidebar.classList.toggle('absolute');
        sidebar.classList.toggle('z-50');
        sidebar.classList.toggle('h-full');
        sidebar.classList.toggle('shadow-2xl');
    });
}

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
        'analytics': 'Statistiche',
        'settings': 'Impostazioni'
    };
    const el = document.getElementById('page-title');
    if (el) el.textContent = titles[name] || 'Dashboard';

    // Toggle Sections
    document.querySelectorAll(".section").forEach(s => s.classList.add("hidden"));
    const section = document.getElementById(`section-${name}`);
    if (section) section.classList.remove("hidden");

    // Update Nav
    document.querySelectorAll("nav .nav-item").forEach(a => {
        a.classList.remove("nav-item-active");
        a.classList.add("text-[var(--muted)]");
    });
    const activeLink = document.querySelector(`nav a[data-section="${name}"]`);
    if (activeLink) {
        activeLink.classList.add("nav-item-active");
        activeLink.classList.remove("text-[var(--muted)]");
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
}

async function initDashboard() {
    openSection('dashboard');
    startStatusPolling();
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

    globalChart = new Chart(canvas, {
        type: "bar",
        data: {
            labels: days,
            datasets: [{
                label: "Chiamate totali",
                data: counts,
                backgroundColor: "rgba(37, 99, 235, 0.6)"
            }]
        },
        options: {
            responsive: true,
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: { precision: 0, color: '#9ca3af' },
                    grid: { color: 'rgba(255, 255, 255, 0.1)' }
                },
                x: {
                    ticks: { color: '#9ca3af' },
                    grid: { display: false }
                }
            },
            plugins: {
                legend: { labels: { color: '#fff' } }
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
            Object.entries(data.by_category).forEach(([cat, count]) => {
                const li = document.createElement("li");
                li.textContent = `${cat}: ${count}`;
                catList.appendChild(li);
            });
        }
        if (urgList && data.by_urgency) {
            urgList.innerHTML = "";
            Object.entries(data.by_urgency).forEach(([urg, count]) => {
                const li = document.createElement("li");
                li.textContent = `${urg}: ${count}`;
                urgList.appendChild(li);
            });
        }

        // 2. Heatmap Grid
        const heatmap = data.heatmap; // 24 rows, 7 cols
        const days = ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"];

        let html = `
            <div class="heatmap-grid w-full overflow-x-auto">
             <div class="min-w-[600px]">
                <div class="flex">
                    <div class="w-16 p-2"></div>
                    ${days.map(d => `<div class="flex-1 p-2 text-center text-xs font-bold text-gray-300">${d}</div>`).join('')}
                </div>
        `;

        for (let hour = 0; hour < 24; hour++) {
            const hourLabel = `${hour.toString().padStart(2, '0')}:00`;
            html += `<div class="flex border-t border-white/5">
                        <div class="w-16 p-2 text-xs text-gray-400 font-mono text-right border-r border-white/10">${hourLabel}</div>`;

            for (let day = 0; day < 7; day++) {
                const val = heatmap[hour][day];
                let bgClass = "bg-transparent";
                let textClass = "text-transparent";

                if (val > 0) {
                    textClass = "text-white/80 font-bold";
                    if (val < 2) bgClass = "bg-blue-900/40";
                    else if (val < 5) bgClass = "bg-blue-700/60";
                    else if (val < 10) bgClass = "bg-blue-600/80";
                    else bgClass = "bg-blue-500";
                }

                html += `
                    <div class="flex-1 p-1 h-8 flex items-center justify-center border-r border-white/5 ${bgClass}" title="${days[day]} ${hourLabel}: ${val} chiamate">
                        <span class="text-xs ${textClass}">${val}</span>
                    </div>
                `;
            }
            html += `</div>`;
        }
        html += `</div></div>`;

        container.innerHTML = html;

    } catch (e) {
        console.warn("Could not render heatmap", e);
        container.innerHTML = "<p class='text-red-400'>Errore caricamento dati.</p>";
    }
}

// =========================
// LOGS
// =========================

let logsOffset = 0;
let logsLimit = 25;
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
            tbody.innerHTML = `<tr><td colspan="6" class="text-center py-4 text-[var(--muted)]">Nessuna chiamata trovata.</td></tr>`;
        } else {
            items.forEach((item) => {
                const tr = document.createElement("tr");
                if (item.status === "failure") tr.className = "bg-red-900/10";

                const duration = item.duration_secs ? `${item.duration_secs}s` : "-";
                const statusColor = item.status === "failure" ? "text-red-400" : "text-green-400";

                tr.innerHTML = `
                    <td class="px-4 py-2 text-sm">${formatDate(item.timestamp)}</td>
                    <td class="px-4 py-2 text-sm font-mono">${item.caller}</td>
                    <td class="px-4 py-2 text-sm font-bold ${statusColor}">${item.status}</td>
                    <td class="px-4 py-2 text-sm">${duration}</td>
                    <td class="px-4 py-2 text-sm max-w-xs truncate" title="${escapeHtml(item.summary)}">${escapeHtml(item.summary || "-")}</td>
                    <td class="px-4 py-2 text-center">
                        <button class="log-detail-btn text-blue-400 hover:text-blue-300 underline text-xs">Dettagli</button>
                    </td>
                `;
                tbody.appendChild(tr);

                // Bind click
                tr.querySelector(".log-detail-btn").addEventListener("click", () => openLogDetail(item));
            });
        }

        const info = document.getElementById("logs-info");
        info.textContent = `Mostrando ${logsOffset + 1} – ${Math.min(logsOffset + logsLimit, logsTotal)} di ${logsTotal}`;

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
    return d.toLocaleString("it-IT", { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function escapeHtml(str) {
    if (str == null) return "";
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
}

// Modal Detail Logic (reused roughly)
function openLogDetail(item) {
    const modal = document.getElementById("log-detail-modal");
    const content = document.getElementById("log-detail-content");

    // Construct detail HTML similar to admin dashboard but safer
    const raw = item.raw || {};
    const ai = raw.ai_enrichment || {};
    const data = raw.data || {};
    const analysis = data.analysis || {};

    const summary = item.summary || ai.summary || "";
    const transcript = ai.transcript_text || analysis.transcript_summary || "";

    content.innerHTML = `
        <div class="mb-4">
            <h4 class="text-white font-bold mb-1">Riassunto</h4>
            <p class="text-gray-300 bg-black/20 p-3 rounded">${escapeHtml(summary)}</p>
        </div>
        <div class="grid grid-cols-2 gap-4 mb-4">
            <div>
                <span class="text-gray-500 text-xs uppercase">Data</span>
                <div class="text-white">${formatDate(item.timestamp)}</div>
            </div>
             <div>
                <span class="text-gray-500 text-xs uppercase">Durata</span>
                <div class="text-white">${item.duration_secs || 0}s</div>
            </div>
             <div>
                <span class="text-gray-500 text-xs uppercase">Categoria</span>
                <div class="text-white">${escapeHtml(ai.category || "-")}</div>
            </div>
             <div>
                <span class="text-gray-500 text-xs uppercase">Urgenza</span>
                <div class="text-white">${escapeHtml(ai.urgency || "-")}</div>
            </div>
        </div>

        ${transcript ? `
            <div>
                <h4 class="text-white font-bold mb-1">Trascrizione</h4>
                <div class="text-gray-300 text-xs whitespace-pre-wrap bg-black/20 p-3 rounded max-h-60 overflow-y-auto">${escapeHtml(transcript)}</div>
            </div>
        ` : ''}
    `;

    modal.classList.remove("hidden");
    modal.classList.add("flex");
}

function closeLogDetail() {
    const modal = document.getElementById("log-detail-modal");
    modal.classList.add("hidden");
    modal.classList.remove("flex");
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
        // We can just rely on page reload if status changes significantly, or implement specific check
        // For now, let's check /subscription/status
        const res = await fetch("/subscription/status");
        if (res.status === 401 || res.status === 403) {
            window.location.reload();
            return;
        }
        // Update UI if needed (e.g. billing status badge)
        // ... (Already handled by Jinja on load, but live update is nice)
    } catch(e) {}
}

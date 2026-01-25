// static/charts.js

let globalChart = null;
let clientChartObj = null;

// Aggiorna KPI cards usando i dati di /analytics/global
function updateKpis(data) {
    const total = data.total_calls || 0;
    const today = data.calls_today || 0;
    const week = data.calls_last_7_days || 0;
    const clients = data.clients_count || 0;
    const errors = data.errors || 0;

    const elTotal = document.getElementById("kpi-total-calls");
    const elToday = document.getElementById("kpi-today");
    const elWeek = document.getElementById("kpi-week");
    const elClients = document.getElementById("kpi-clients");
    const elErrors = document.getElementById("kpi-errors");

    if (elTotal) elTotal.textContent = total;
    if (elToday) elToday.textContent = today;
    if (elWeek) elWeek.textContent = week;
    if (elClients) elClients.textContent = clients;
    if (elErrors) elErrors.textContent = errors;
}

// GRAFICO GLOBALE: chiamate per giorno
async function renderGlobalChart() {
    const canvas = document.getElementById("chart_all_clients");
    if (!canvas) return;

    // Determine endpoint based on role
    let url = "/analytics/global";
    if (window.user && window.user.role === "client") {
        url = "/api/analytics";
    }

    try {
        const res = await fetch(url);
        if (!res.ok) throw new Error("Analytics fetch failed");

        const data = await res.json();

        // aggiorna KPI
        updateKpis(data);

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
                    backgroundColor: "#171717", // Neutral 900
                    hoverBackgroundColor: "#404040", // Neutral 700
                    borderRadius: 4
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: { precision: 0, font: { family: 'Inter' } },
                        grid: { color: '#f5f5f5', drawBorder: false }
                    },
                    x: {
                        ticks: { font: { family: 'Inter' } },
                        grid: { display: false }
                    }
                },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: '#171717',
                        titleFont: { family: 'Inter' },
                        bodyFont: { family: 'Inter' },
                        cornerRadius: 8,
                        padding: 10
                    }
                }
            }
        });
    } catch (e) {
        console.warn("Could not render global chart", e);
    }
}

// GRAFICO PER CLIENTE (timeline chiamate)
async function renderClientChart(agent_id) {
    const canvas = document.getElementById("clientChart");
    if (!canvas) return;

    try {
        const res = await fetch(`/analytics/${agent_id}`);
        if (!res.ok) return;
        const data = await res.json();

        const points = data.points || [];

        if (clientChartObj) {
            clientChartObj.destroy();
        }

        clientChartObj = new Chart(canvas, {
            type: "line",
            data: {
                labels: points.map(p => new Date(p).toLocaleDateString()),
                datasets: [{
                    label: "Chiamate",
                    data: points.map(() => 1), // Dummy Y axis
                    borderColor: "#171717",
                    backgroundColor: "rgba(23, 23, 23, 0.1)",
                    tension: 0.3,
                    pointRadius: 4,
                    pointBackgroundColor: "#171717"
                }]
            },
            options: {
                responsive: true,
                scales: {
                    y: {
                        display: false,
                        beginAtZero: true
                    },
                    x: {
                        grid: { display: false },
                        ticks: { font: { family: 'Inter' } }
                    }
                },
                plugins: {
                    legend: { display: false }
                }
            }
        });
    } catch(e) {
        console.warn("Error rendering client chart", e);
    }
}

// HEATMAP ORARIA (24 x 7)
async function renderHeatmap() {
    const container = document.getElementById("heatmap-container");
    if (!container) return;

    let url = "/analytics/global";
    if (window.user && window.user.role === "client") {
        url = "/api/analytics";
    }

    try {
        const res = await fetch(url);
        if (!res.ok) throw new Error("Heatmap fetch failed");
        const data = await res.json();

        // 1. Aggiorna liste categorie/urgenza
        const catList = document.getElementById("analytics-category-list");
        const urgList = document.getElementById("analytics-urgency-list");

        if (catList && data.by_category) {
            catList.innerHTML = "";
            Object.entries(data.by_category).forEach(([cat, count]) => {
                const li = document.createElement("li");
                li.className = "flex justify-between text-sm py-1 border-b border-neutral-100 last:border-0";
                li.innerHTML = `<span class="capitalize text-neutral-600">${cat}</span> <span class="font-bold text-neutral-900">${count}</span>`;
                catList.appendChild(li);
            });
        }

        if (urgList && data.by_urgency) {
            urgList.innerHTML = "";
            Object.entries(data.by_urgency).forEach(([urg, count]) => {
                const li = document.createElement("li");
                li.className = "flex justify-between text-sm py-1 border-b border-neutral-100 last:border-0";
                li.innerHTML = `<span class="capitalize text-neutral-600">${urg}</span> <span class="font-bold text-neutral-900">${count}</span>`;
                urgList.appendChild(li);
            });
        }

        // 2. Heatmap Construction (Grid Layout)
        const heatmap = data.heatmap; // 24 rows (hours), 7 cols (days)
        const days = ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"];

        // Simple Grid implementation
        let html = `
            <div class="overflow-x-auto">
                <div class="min-w-[600px] border border-neutral-200 rounded-lg overflow-hidden bg-white">
                    <div class="grid grid-cols-[50px_repeat(7,1fr)] bg-neutral-50 border-b border-neutral-200">
                        <div class="p-2"></div>
                        ${days.map(d => `<div class="p-2 text-center text-xs font-semibold text-neutral-500">${d}</div>`).join('')}
                    </div>
        `;

        for (let hour = 0; hour < 24; hour++) {
            const hourLabel = `${hour.toString().padStart(2, '0')}:00`;
            html += `<div class="grid grid-cols-[50px_repeat(7,1fr)] border-b border-neutral-100 last:border-0">
                        <div class="p-2 text-xs text-neutral-400 text-right font-mono bg-neutral-50/50">${hourLabel}</div>`;

            for (let day = 0; day < 7; day++) {
                const val = heatmap[hour][day];
                let bgClass = "bg-white";
                let textClass = "text-transparent";
                let tooltip = `${days[day]} ${hourLabel} - ${val} chiamate`;

                if (val > 0) {
                    textClass = "text-white font-bold";
                    // Using neutral scale for light theme
                    if (val < 2) bgClass = "bg-neutral-300";
                    else if (val < 5) bgClass = "bg-neutral-500";
                    else if (val < 10) bgClass = "bg-neutral-700";
                    else bgClass = "bg-neutral-900";
                }

                html += `
                    <div class="relative group h-8 flex items-center justify-center border-r border-neutral-50 last:border-r-0 ${bgClass} transition-colors" title="${tooltip}">
                        <span class="text-[10px] ${textClass}">${val > 0 ? val : ''}</span>
                    </div>
                `;
            }
            html += `</div>`;
        }

        html += `</div></div>`;
        container.innerHTML = html;

    } catch (e) {
        console.warn("Could not render heatmap", e);
        container.innerHTML = "<p class='text-red-500 text-sm p-4'>Errore caricamento grafico.</p>";
    }
}

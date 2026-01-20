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

    const res = await fetch("/analytics/global");
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
                backgroundColor: "rgba(37, 99, 235, 0.6)"
            }]
        },
        options: {
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: { precision: 0 }
                }
            }
        }
    });
}

// GRAFICO PER CLIENTE (timeline chiamate)
async function renderClientChart(agent_id) {
    const canvas = document.getElementById("clientChart");
    if (!canvas) return;

    const res = await fetch(`/analytics/${agent_id}`);
    const data = await res.json();

    const points = data.points || [];

    if (clientChartObj) {
        clientChartObj.destroy();
    }

    clientChartObj = new Chart(canvas, {
        type: "line",
        data: {
            labels: points,
            datasets: [{
                label: "Chiamate",
                data: points.map(() => 1),
                borderColor: "rgb(37, 99, 235)",
                tension: 0.3
            }]
        },
        options: {
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: { precision: 0 }
                }
            }
        }
    });
}

// HEATMAP ORARIA (24 x 7)
async function renderHeatmap() {
    const container = document.getElementById("heatmap-container");
    if (!container) return;

    const res = await fetch("/analytics/global");
    const data = await res.json();

    // 1. Aggiorna liste categorie/urgenza
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

    // 2. Heatmap Construction (Grid Layout)
    const heatmap = data.heatmap; // 24 rows (hours), 7 cols (days)
    const days = ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"];

    // Main grid container
    // Colums: First for Time label, then 7 for days
    let html = `
        <div class="heatmap-grid w-full min-h-[600px] overflow-y-auto" style="width: 100%;">
            <div class="heatmap-header-row contents">
                <div class="heatmap-corner p-2 text-xs font-bold text-gray-400"></div>
    `;

    days.forEach(d => {
        html += `<div class="heatmap-col-header p-2 text-center text-xs font-bold text-gray-300 border-b border-white/10 sticky top-0 bg-gray-900 z-10">${d}</div>`;
    });

    html += `</div>`; // end header-row contents wrapper logic (in grid we just place items)

    // Actually, for simple grid, we don't need wrapping divs for rows if using subgrid or just flattening.
    // Let's flatten: 
    // Container: display: grid; grid-template-columns: 50px repeat(7, 1fr);

    // Rows
    for (let hour = 0; hour < 24; hour++) {
        // Time label
        const hourLabel = `${hour.toString().padStart(2, '0')}:00`;
        html += `<div class="heatmap-row-label p-2 text-xs text-gray-400 border-r border-white/10 text-right font-mono">${hourLabel}</div>`;

        for (let day = 0; day < 7; day++) {
            const val = heatmap[hour][day];

            // Color scale (dark theme friendly)
            let bgClass = "bg-white/5";
            let textClass = "text-transparent"; // hide number if 0? or just faint
            let tooltip = `${days[day]} ${hour}:00 - ${val} chiamate`;

            if (val > 0) {
                textClass = "text-white/80 font-bold";
                if (val < 2) bgClass = "bg-blue-900/40";
                else if (val < 5) bgClass = "bg-blue-700/60";
                else if (val < 10) bgClass = "bg-blue-600/80";
                else bgClass = "bg-blue-500";
            } else {
                textClass = "text-white/10"; // faint 0
            }

            html += `
                <div class="heatmap-cell relative group p-1 flex items-center justify-center border-b border-r border-white/5 hover:border-white/20 transition-all cursor-default ${bgClass}" title="${tooltip}">
                    <span class="text-xs ${textClass}">${val > 0 ? val : '-'}</span>
                </div>
            `;
        }
    }

    html += `</div>`; // end grid

    container.innerHTML = html;

    // Force full width on the grid after render
    const grid = container.querySelector('.heatmap-grid');
    if (grid) {
        // Get the computed width of the container and set it on the grid
        const containerWidth = container.offsetWidth || container.clientWidth;
        if (containerWidth > 0) {
            grid.style.width = containerWidth + 'px';
        }
    }
}

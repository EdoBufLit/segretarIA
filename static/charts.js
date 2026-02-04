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

        const ctx = canvas.getContext("2d");
        const gradient = ctx.createLinearGradient(0, 0, 0, canvas.height);
        gradient.addColorStop(0, "rgba(31, 111, 92, 0.25)");
        gradient.addColorStop(1, "rgba(31, 111, 92, 0.03)");

        globalChart = new Chart(canvas, {
            type: "line",
            data: {
                labels: days,
                datasets: [{
                    label: "Chiamate totali",
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
                        ticks: { precision: 0, color: "#6e6a64", font: { family: "IBM Plex Sans", size: 11 } },
                        grid: { color: "#ece6df", drawBorder: false }
                    },
                    x: {
                        ticks: { color: "#6e6a64", font: { family: "IBM Plex Sans", size: 11 } },
                        grid: { display: false }
                    }
                },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: "#1b1a18",
                        titleFont: { family: "IBM Plex Sans", size: 13 },
                        bodyFont: { family: "IBM Plex Sans", size: 12 },
                        padding: 10,
                        cornerRadius: 8,
                        displayColors: false
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
                borderColor: "#1f6f5c",
                tension: 0.35,
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
                    ticks: { precision: 0, color: "#6e6a64", font: { family: "IBM Plex Sans", size: 11 } },
                    grid: { color: "#ece6df", drawBorder: false }
                },
                x: {
                    ticks: { color: "#6e6a64", font: { family: "IBM Plex Sans", size: 11 } },
                    grid: { display: false }
                }
            },
            plugins: {
                legend: { display: false }
            }
        }
    });
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
        let html = `
            <div class="heatmap-grid w-full min-h-[600px] overflow-y-auto" style="width: 100%;">
                <div class="heatmap-header-row contents">
                    <div class="heatmap-corner p-2 text-xs font-bold text-neutral-400"></div>
        `;

        days.forEach(d => {
            html += `<div class="heatmap-col-header p-2 text-center text-xs font-bold text-neutral-400 border-b border-neutral-200 sticky top-0 bg-white z-10">${d}</div>`;
        });

        html += `</div>`;

        // Rows
        for (let hour = 0; hour < 24; hour++) {
            // Time label
            const hourLabel = `${hour.toString().padStart(2, '0')}:00`;
            html += `<div class="heatmap-row-label p-2 text-xs text-neutral-400 border-r border-neutral-100 text-right font-mono bg-neutral-50/60">${hourLabel}</div>`;

            for (let day = 0; day < 7; day++) {
                const val = heatmap[hour][day];

                // Color scale
                let bgClass = "bg-white";
                let textClass = "text-neutral-300";
                let tooltip = `${days[day]} ${hour}:00 - ${val} chiamate`;

                if (val > 0) {
                    textClass = "text-emerald-900 font-semibold";
                    if (val < 2) bgClass = "bg-emerald-50";
                    else if (val < 5) bgClass = "bg-emerald-100";
                    else if (val < 10) bgClass = "bg-emerald-200";
                    else bgClass = "bg-emerald-300";
                } else {
                    textClass = "text-neutral-300";
                }

                html += `
                    <div class="heatmap-cell relative group p-1 flex items-center justify-center border-b border-r border-neutral-100 hover:border-neutral-200 transition-all cursor-default ${bgClass}" title="${tooltip}">
                        <span class="text-xs ${textClass}">${val > 0 ? val : '-'}</span>
                    </div>
                `;
            }
        }

        html += `</div>`;

        container.innerHTML = html;

        // Force full width
        const grid = container.querySelector('.heatmap-grid');
        if (grid) {
            const containerWidth = container.offsetWidth || container.clientWidth;
            if (containerWidth > 0) {
                grid.style.width = containerWidth + 'px';
            }
        }

    } catch (e) {
        console.warn("Could not render heatmap", e);
    }
}

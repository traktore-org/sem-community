/**
 * SEM Chart Card — Chart.js-powered, period-reactive, glassmorphism-styled
 *
 * Listens for 'sem-period-change' events from sem-period-selector-card.
 * Fetches data via HA WebSocket (recorder/statistics_during_period or history/period).
 * Renders with Chart.js (loaded from CDN on first use).
 *
 * Config:
 *   type: custom:sem-chart-card
 *   preset: costs | savings | energy | power | battery | ev
 *   title: "Optional title override"
 *   entity_prefix: sensor.sem_       # default
 *   stacked: false                    # override stacking
 *   y_label: "CHF"                    # override Y-axis label
 *   series:                           # override preset series
 *     - entity: sensor.sem_daily_costs
 *       name: Import
 *       color: "#EF5350"
 *       type: bar | line | area
 *       y_axis: 0 | 1                 # for dual-axis
 */

/* ── Chart.js loader (singleton) ── */
let _chartJsReady = null;
function _loadChartJs() {
    if (_chartJsReady) return _chartJsReady;
    _chartJsReady = new Promise((resolve, reject) => {
        // Check if already loaded globally (by another instance or apexcharts-card)
        if (window.Chart) { resolve(window.Chart); return; }
        const script = document.createElement('script');
        script.src = 'https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js';
        script.onload = () => {
            // Also load the date adapter
            const adapter = document.createElement('script');
            adapter.src = 'https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3.0.0/dist/chartjs-adapter-date-fns.bundle.min.js';
            adapter.onload = () => resolve(window.Chart);
            adapter.onerror = () => resolve(window.Chart); // adapter optional
            document.head.appendChild(adapter);
        };
        script.onerror = () => reject(new Error('Failed to load Chart.js'));
        document.head.appendChild(script);
    });
    return _chartJsReady;
}

/* ── Canonical color palette (from sem-shared.js) ── */
const C = (typeof SEM_COLORS !== 'undefined') ? SEM_COLORS : {
    solar: '#ff9800',
    gridImport: '#488fc2',
    gridExport: '#8353d1',
    batteryIn: '#f06292',
    batteryOut: '#4db6ac',
    home: '#5BC8D8',
    ev: '#8DC892',
};

/* ── Preset definitions ── */
const PRESETS = {
    costs: {
        title: 'Energy Costs',
        y_label: '_currency_',  // Replaced at render time with HA currency (#119)
        stacked: false,
        daily: [
            { suffix: 'daily_costs', name: 'Import', color: C.gridImport, type: 'bar' },
            { suffix: 'daily_export_revenue', name: 'Export', color: C.gridExport, type: 'bar' },
            { suffix: 'daily_net_cost', name: 'Net', color: C.solar, type: 'line' },
        ],
        monthly: [
            { suffix: 'monthly_costs', name: 'Import', color: C.gridImport, type: 'bar' },
            { suffix: 'monthly_export_revenue', name: 'Export', color: C.gridExport, type: 'bar' },
            { suffix: 'monthly_net_cost', name: 'Net', color: C.solar, type: 'line' },
        ],
    },
    savings: {
        title: 'Energy Savings',
        y_label: '_currency_',
        stacked: true,
        daily: [
            { suffix: 'daily_savings', name: 'Solar Savings', color: C.solar, type: 'area' },
            { suffix: 'daily_battery_savings', name: 'Battery Savings', color: C.batteryOut, type: 'area' },
        ],
        monthly: [
            { suffix: 'monthly_savings', name: 'Solar Savings', color: C.solar, type: 'area' },
            { suffix: 'monthly_battery_savings', name: 'Battery Savings', color: C.batteryOut, type: 'area' },
        ],
    },
    energy: {
        title: 'Energy Balance',
        y_label: 'kWh',
        stacked: false,
        daily: [
            { suffix: 'daily_solar_energy', name: 'Solar', color: C.solar, type: 'bar' },
            { suffix: 'daily_home_energy', name: 'Home', color: C.home, type: 'bar' },
            { suffix: 'daily_grid_import_energy', name: 'Grid Import', color: C.gridImport, type: 'bar' },
            { suffix: 'daily_grid_export_energy', name: 'Grid Export', color: C.gridExport, type: 'bar' },
        ],
        monthly: [
            { suffix: 'monthly_solar_energy', name: 'Solar', color: C.solar, type: 'bar' },
            { suffix: 'monthly_home_energy', name: 'Home', color: C.home, type: 'bar' },
            { suffix: 'monthly_grid_import_energy', name: 'Grid Import', color: C.gridImport, type: 'bar' },
            { suffix: 'monthly_grid_export_energy', name: 'Grid Export', color: C.gridExport, type: 'bar' },
        ],
    },
    power: {
        title: 'Power Flow',
        y_label: 'W',
        stacked: false,
        hourly: [
            { suffix: 'solar_power', name: 'Solar', color: C.solar, type: 'line' },
            { suffix: 'home_consumption_power', name: 'Home', color: C.home, type: 'line' },
            { suffix: 'grid_import_power', name: 'Grid Import', color: C.gridImport, type: 'line' },
            { suffix: 'grid_export_power', name: 'Grid Export', color: C.gridExport, type: 'line' },
            { suffix: 'battery_power', name: 'Battery', color: C.batteryOut, type: 'line' },
        ],
    },
    battery: {
        title: 'Battery',
        y_label: 'W',
        y2_label: '%',
        stacked: false,
        hourly: [
            { suffix: 'battery_charge_power', name: 'Charge', color: C.batteryIn, type: 'area' },
            { suffix: 'battery_discharge_power', name: 'Discharge', color: C.batteryOut, type: 'area' },
            { suffix: 'battery_soc', name: 'SOC', color: C.home, type: 'line', y_axis: 1 },
        ],
    },
    ev: {
        title: 'EV Charging',
        y_label: 'W',
        stacked: false,
        hourly: [
            { suffix: 'ev_power', name: 'EV Power', color: C.ev, type: 'area' },
        ],
        daily: [
            { suffix: 'daily_ev_energy', name: 'EV Energy', color: C.ev, type: 'bar' },
        ],
        monthly: [
            { suffix: 'monthly_ev_energy', name: 'EV Energy', color: C.ev, type: 'bar' },
        ],
    },
};

class SEMChartCard extends HTMLElement {
    constructor() {
        super();
        this.attachShadow({ mode: 'open' });
        this._chart = null;
        this._period = null;
        this._fetchTimer = null;
        this._boundPeriodHandler = (e) => this._onPeriodChange(e.detail);
    }

    setConfig(config) {
        if (!config.preset && !config.series) {
            throw new Error('sem-chart-card requires either preset or series config');
        }
        this.config = config;
        this._prefix = config.entity_prefix || 'sensor.sem_';
        this._preset = config.preset ? PRESETS[config.preset] : null;
    }

    connectedCallback() {
        document.addEventListener('sem-period-change', this._boundPeriodHandler);
    }

    disconnectedCallback() {
        document.removeEventListener('sem-period-change', this._boundPeriodHandler);
        if (this._chart) { this._chart.destroy(); this._chart = null; }
    }

    set hass(hass) {
        this._hass = hass;
        if (!this.shadowRoot.querySelector('.sem-chart-wrap')) {
            this._renderSkeleton();
        }
        // If no period received yet, use a sensible default
        if (!this._period) {
            this._setDefaultPeriod();
        }
    }

    _setDefaultPeriod() {
        const now = new Date();
        const dow = now.getDay() || 7;
        const mon = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        mon.setDate(mon.getDate() - (dow - 1));
        this._onPeriodChange({ start: mon, end: now, granularity: 'day', label: 'This Week', key: 'week' });
    }

    _onPeriodChange(detail) {
        this._period = detail;
        // Update subtitle
        const sub = this.shadowRoot.querySelector('.chart-subtitle');
        if (sub) sub.textContent = detail.label || '';
        // Debounce fetch
        clearTimeout(this._fetchTimer);
        this._fetchTimer = setTimeout(() => this._fetchAndRender(), 150);
    }

    /* ── Resolve which series to use based on granularity ── */
    _resolveSeries() {
        if (this.config.series) {
            return this.config.series.map(s => ({
                entity: s.entity,
                name: s.name || s.entity,
                color: s.color || '#42A5F5',
                type: s.type || 'bar',
                y_axis: s.y_axis || 0,
            }));
        }
        const p = this._preset;
        if (!p) return [];
        const g = this._period?.granularity || 'day';
        let defs;
        if (g === 'hour' && p.hourly) {
            defs = p.hourly;
        } else if (g === 'month' && p.monthly) {
            defs = p.monthly;
        } else {
            defs = p.daily || p.hourly || [];
        }
        return defs.map(d => ({
            entity: `${this._prefix}${d.suffix}`,
            name: d.name,
            color: d.color,
            type: d.type,
            y_axis: d.y_axis || 0,
        }));
    }

    /* ── Data fetching ── */
    async _fetchAndRender() {
        if (!this._hass || !this._period) return;
        const series = this._resolveSeries();
        if (!series.length) return;

        const { start, end, granularity } = this._period;
        const startISO = start.toISOString();
        const endISO = end.toISOString();

        let datasets;
        try {
            datasets = await this._fetchStatistics(series, startISO, endISO, granularity);
        } catch (err) {
            console.warn('sem-chart-card: fetch error', err);
            this._showEmpty('Data unavailable');
            return;
        }

        if (!datasets || datasets.every(ds => !ds.data.length)) {
            this._showEmpty('No data for this period');
            return;
        }

        this._hideEmpty();
        await this._renderChart(datasets, series);
    }

    async _fetchStatistics(series, startISO, endISO, granularity) {
        const statIds = series.map(s => s.entity);
        const period = granularity === 'month' ? 'month' : granularity === 'hour' ? 'hour' : 'day';

        let stats;
        try {
            stats = await this._hass.callWS({
                type: 'recorder/statistics_during_period',
                start_time: startISO,
                end_time: endISO,
                statistic_ids: statIds,
                period,
                types: ['state', 'mean', 'max'],
            });
        } catch {
            // Fallback for older HA versions
            stats = await this._hass.callWS({
                type: 'history/statistics_during_period',
                start_time: startISO,
                end_time: endISO,
                statistic_ids: statIds,
                period,
            });
        }

        return series.map(s => {
            const points = stats[s.entity] || [];
            return {
                data: points.map(p => ({
                    x: new Date(p.start),
                    y: p.max ?? p.state ?? p.mean ?? 0,
                })),
            };
        });
    }

    /* ── Chart.js rendering ── */
    async _renderChart(datasets, series) {
        const Chart = await _loadChartJs();
        const canvas = this.shadowRoot.querySelector('canvas');
        if (!canvas) return;

        const preset = this._preset || {};
        const stacked = this.config.stacked ?? preset.stacked ?? false;
        let yLabel = this.config.y_label || preset.y_label || '';
        if (yLabel === '_currency_') yLabel = window.semGetCurrency?.(this._hass) || 'EUR';
        const y2Label = preset.y2_label || '';
        const hasY2 = series.some(s => s.y_axis === 1);
        const granularity = this._period?.granularity || 'day';

        const chartDatasets = series.map((s, i) => {
            const isArea = s.type === 'area';
            const isBar = s.type === 'bar';
            return {
                label: s.name,
                data: datasets[i].data,
                backgroundColor: isBar
                    ? s.color + 'CC'
                    : isArea
                        ? s.color + '40'
                        : 'transparent',
                borderColor: s.color,
                borderWidth: isBar ? 0 : 2,
                fill: isArea ? 'origin' : false,
                type: isBar ? 'bar' : 'line',
                tension: 0.3,
                pointRadius: 0,
                pointHitRadius: 8,
                yAxisID: s.y_axis === 1 ? 'y1' : 'y',
                order: isBar ? 2 : 1, // lines on top
            };
        });

        const timeUnit = granularity === 'hour' ? 'hour'
            : granularity === 'month' ? 'month' : 'day';

        const config = {
            type: 'bar', // mixed chart uses bar as base
            data: { datasets: chartDatasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: { duration: 400, easing: 'easeOutQuart' },
                interaction: { mode: 'index', intersect: false },
                plugins: {
                    legend: {
                        display: true,
                        position: 'bottom',
                        labels: {
                            color: '#9e9e9e',
                            font: { size: 11, weight: '500', family: "'Segoe UI','Roboto',sans-serif" },
                            boxWidth: 12,
                            boxHeight: 12,
                            borderRadius: 3,
                            useBorderRadius: true,
                            padding: 12,
                        },
                    },
                    tooltip: {
                        backgroundColor: 'rgba(20, 20, 30, 0.95)',
                        titleColor: '#e0e0e0',
                        titleFont: { family: "'Segoe UI','Roboto',sans-serif", weight: '600' },
                        bodyColor: '#b0b0b0',
                        bodyFont: { family: "'Segoe UI','Roboto',sans-serif" },
                        borderColor: 'rgba(255,255,255,0.06)',
                        borderWidth: 1,
                        cornerRadius: 12,
                        padding: 12,
                        bodySpacing: 5,
                        callbacks: {
                            label: (ctx) => {
                                const val = ctx.parsed.y;
                                const decimals = Math.abs(val) < 10 ? 2 : 1;
                                return ` ${ctx.dataset.label}: ${val.toFixed(decimals)} ${yLabel}`;
                            },
                        },
                    },
                },
                scales: {
                    x: {
                        type: 'time',
                        min: this._period.start.toISOString(),
                        max: this._period.end.toISOString(),
                        time: {
                            unit: timeUnit,
                            tooltipFormat: granularity === 'hour' ? 'HH:mm' : granularity === 'month' ? 'MMM yyyy' : 'dd MMM',
                            displayFormats: {
                                hour: 'HH:mm',
                                day: 'dd MMM',
                                month: 'MMM',
                            },
                        },
                        grid: { color: 'rgba(255,255,255,0.03)', drawBorder: false },
                        ticks: { color: '#757575', font: { size: 10, family: "'Segoe UI','Roboto',sans-serif" }, maxRotation: 0 },
                        stacked,
                    },
                    y: {
                        position: 'left',
                        grid: { color: 'rgba(255,255,255,0.04)', drawBorder: false },
                        ticks: {
                            color: '#757575', font: { size: 10, family: "'Segoe UI','Roboto',sans-serif" },
                            callback: (v) => {
                                const abs = Math.abs(v);
                                if (abs >= 1000) return (v / 1000).toFixed(1) + 'k';
                                return v % 1 === 0 ? v : v.toFixed(1);
                            },
                        },
                        title: { display: !!yLabel, text: yLabel, color: '#757575', font: { size: 11 } },
                        stacked,
                        beginAtZero: true,
                    },
                },
            },
        };

        // Second Y-axis for dual-axis presets (e.g. battery SOC)
        if (hasY2) {
            config.options.scales.y1 = {
                position: 'right',
                grid: { drawOnChartArea: false },
                ticks: { color: '#42A5F5', font: { size: 10 }, callback: (v) => v + '%' },
                title: { display: !!y2Label, text: y2Label, color: '#42A5F5', font: { size: 11 } },
                min: 0,
                max: 100,
            };
        }

        // Always recreate chart to ensure axis bounds update correctly
        if (this._chart) {
            this._chart.destroy();
            this._chart = null;
        }
        this._chart = new Chart(canvas.getContext('2d'), config);
    }

    /* ── Empty state ── */
    _showEmpty(msg) {
        const el = this.shadowRoot.querySelector('.empty-msg');
        if (el) { el.textContent = msg; el.style.display = 'block'; }
        const c = this.shadowRoot.querySelector('canvas');
        if (c) c.style.display = 'none';
    }

    _hideEmpty() {
        const el = this.shadowRoot.querySelector('.empty-msg');
        if (el) el.style.display = 'none';
        const c = this.shadowRoot.querySelector('canvas');
        if (c) c.style.display = 'block';
    }

    /* ── Skeleton HTML ── */
    _renderSkeleton() {
        const preset = this._preset || {};
        const title = this.config.title || preset.title || 'SEM Chart';

        this.shadowRoot.innerHTML = `
            <style>
                :host { display: block; }
                .sem-chart-wrap {
                    padding: 16px;
                    min-height: 280px;
                    position: relative;
                    background:
                        radial-gradient(ellipse 70% 60% at 50% 40%, rgba(200,220,240,0.05) 0%, transparent 100%),
                        radial-gradient(circle at 2px 2px, rgba(128,128,128,0.05) 0.7px, transparent 0.7px);
                    background-size: 100% 100%, 50px 50px;
                }
                .chart-header {
                    margin-bottom: 12px;
                }
                .chart-title {
                    font-size: 15px;
                    font-weight: 600;
                    color: #e0e0e0;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    letter-spacing: 0.3px;
                    font-variant-numeric: tabular-nums;
                }
                .chart-subtitle {
                    font-size: 12px;
                    color: #757575;
                    margin-top: 2px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    font-variant-numeric: tabular-nums;
                }
                .chart-container {
                    position: relative;
                    height: 250px;
                    filter: drop-shadow(0 0 1px rgba(200,220,240,0.10));
                }
                canvas {
                    width: 100% !important;
                    height: 100% !important;
                }
                .empty-msg {
                    display: none;
                    position: absolute;
                    inset: 0;
                    display: none;
                    align-items: center;
                    justify-content: center;
                    color: #616161;
                    font-size: 13px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                }
                .empty-msg[style*="block"] {
                    display: flex;
                }
            </style>
            <ha-card>
                <div class="sem-chart-wrap">
                    <div class="chart-header">
                        <div class="chart-title">${title}</div>
                        <div class="chart-subtitle"></div>
                    </div>
                    <div class="chart-container">
                        <canvas></canvas>
                        <div class="empty-msg">Loading…</div>
                    </div>
                </div>
            </ha-card>
        `;
    }

    getCardSize() { return 5; }

    static getStubConfig() {
        return { preset: 'costs' };
    }
}

customElements.define('sem-chart-card', SEMChartCard);

window.customCards = window.customCards || [];
window.customCards.push({
    type: 'sem-chart-card',
    name: 'SEM Chart',
    description: 'Period-reactive chart with glassmorphism styling and built-in presets',
});

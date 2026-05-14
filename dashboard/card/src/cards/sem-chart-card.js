/**
 * SEM Chart Card — LitElement migration
 *
 * Chart.js-powered, period-reactive, glassmorphism-styled chart card.
 * Listens for 'sem-period-change' events from sem-period-selector-card.
 * Fetches data via HA WebSocket (recorder/statistics_during_period).
 *
 * Key migration notes:
 * - render() provides the canvas + empty-state skeleton
 * - firstUpdated() initialises the chart instance
 * - updated() refreshes data on each render cycle
 * - Chart.js loaded from CDN via module-level singleton _loadChartJs()
 * - Chart instance destroyed in disconnectedCallback()
 */

import { SEMLitBase, html, css, nothing } from '../base/sem-lit-base.js';
import { semTheme, semGetCurrency, semDefineCard, SEM_COLORS } from '../base/sem-shared.js';

/* ── Chart.js CDN singleton loader ── */
let _chartJsReady = null;
function _loadChartJs() {
    if (_chartJsReady) return _chartJsReady;
    _chartJsReady = new Promise((resolve, reject) => {
        if (window.Chart) { resolve(window.Chart); return; }
        const script = document.createElement('script');
        script.src = 'https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js';
        script.onload = () => {
            const adapter = document.createElement('script');
            adapter.src = 'https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3.0.0/dist/chartjs-adapter-date-fns.bundle.min.js';
            adapter.onload  = () => resolve(window.Chart);
            adapter.onerror = () => resolve(window.Chart); // adapter optional
            document.head.appendChild(adapter);
        };
        script.onerror = () => reject(new Error('Failed to load Chart.js'));
        document.head.appendChild(script);
    });
    return _chartJsReady;
}

/* ── Canonical color palette (falls back if SEM_COLORS is somehow unavailable) ── */
const C = SEM_COLORS || {
    solar: '#ff9800', gridImport: '#488fc2', gridExport: '#8353d1',
    batteryIn: '#f06292', batteryOut: '#4db6ac', home: '#5BC8D8', ev: '#8DC892',
};

/* ── Preset definitions ── */
const PRESETS = {
    costs: {
        title: 'energy_costs', y_label: '_currency_', stacked: false,
        daily:   [
            { suffix: 'daily_costs',           name: 'Import',  color: C.gridImport, type: 'bar'  },
            { suffix: 'daily_export_revenue',   name: 'export',  color: C.gridExport, type: 'bar'  },
            { suffix: 'daily_net_cost',         name: 'net',     color: C.solar,      type: 'line' },
        ],
        monthly: [
            { suffix: 'monthly_costs',          name: 'Import',  color: C.gridImport, type: 'bar'  },
            { suffix: 'monthly_export_revenue', name: 'export',  color: C.gridExport, type: 'bar'  },
            { suffix: 'monthly_net_cost',       name: 'net',     color: C.solar,      type: 'line' },
        ],
    },
    savings: {
        title: 'energy_savings', y_label: '_currency_', stacked: true,
        daily:   [
            { suffix: 'daily_savings',         name: 'solar_savings',   color: C.solar,      type: 'area' },
            { suffix: 'daily_battery_savings', name: 'battery_savings', color: C.batteryOut, type: 'area' },
        ],
        monthly: [
            { suffix: 'monthly_savings',         name: 'solar_savings',   color: C.solar,      type: 'area' },
            { suffix: 'monthly_battery_savings', name: 'battery_savings', color: C.batteryOut, type: 'area' },
        ],
    },
    energy: {
        title: 'energy_balance', y_label: 'kWh', stacked: false,
        daily:   [
            { suffix: 'daily_solar_energy',        name: 'solar',       color: C.solar,      type: 'bar' },
            { suffix: 'daily_home_energy',         name: 'home',        color: C.home,       type: 'bar' },
            { suffix: 'daily_grid_import_energy',  name: 'grid_import', color: C.gridImport, type: 'bar' },
            { suffix: 'daily_grid_export_energy',  name: 'grid_export', color: C.gridExport, type: 'bar' },
        ],
        monthly: [
            { suffix: 'monthly_solar_energy',       name: 'solar',       color: C.solar,      type: 'bar' },
            { suffix: 'monthly_home_energy',        name: 'home',        color: C.home,       type: 'bar' },
            { suffix: 'monthly_grid_import_energy', name: 'grid_import', color: C.gridImport, type: 'bar' },
            { suffix: 'monthly_grid_export_energy', name: 'grid_export', color: C.gridExport, type: 'bar' },
        ],
    },
    power: {
        title: 'power_flow', y_label: 'W', stacked: false,
        hourly: [
            { suffix: 'solar_power',             name: 'solar',       color: C.solar,      type: 'line' },
            { suffix: 'home_consumption_power',  name: 'home',        color: C.home,       type: 'line' },
            { suffix: 'grid_import_power',       name: 'grid_import', color: C.gridImport, type: 'line' },
            { suffix: 'grid_export_power',       name: 'grid_export', color: C.gridExport, type: 'line' },
            { suffix: 'battery_power',           name: 'battery',     color: C.batteryOut, type: 'line' },
        ],
    },
    battery: {
        title: 'battery', y_label: 'W', y2_label: '%', stacked: false,
        hourly: [
            { suffix: 'battery_charge_power',    name: 'Charge',    color: C.batteryIn,  type: 'area' },
            { suffix: 'battery_discharge_power', name: 'Discharge', color: C.batteryOut, type: 'area' },
            { suffix: 'battery_soc',             name: 'soc',       color: C.home,       type: 'line', y_axis: 1 },
        ],
    },
    ev: {
        title: 'ev_charging', y_label: 'W', stacked: false,
        hourly:  [{ suffix: 'ev_power',         name: 'ev_power',  color: C.ev, type: 'area' }],
        daily:   [{ suffix: 'daily_ev_energy',   name: 'ev_energy', color: C.ev, type: 'bar'  }],
        monthly: [{ suffix: 'monthly_ev_energy', name: 'ev_energy', color: C.ev, type: 'bar'  }],
    },
};

class SEMChartCard extends SEMLitBase {
    constructor() {
        super();
        this._chart = null;
        this._period = null;
        this._fetchTimer = null;
        this._theme = null;
        this._boundPeriodHandler = (e) => this._onPeriodChange(e.detail);
        this._prefix = 'sensor.sem_';
        this._preset = null;
    }

    setConfig(config) {
        if (!config.preset && !config.series) {
            throw new Error('sem-chart-card requires either preset or series config');
        }
        this._config  = config;
        this._prefix  = config.entity_prefix || 'sensor.sem_';
        this._preset  = config.preset ? PRESETS[config.preset] : null;
        this.requestUpdate();
    }

    // ── hass: only trigger update on locale change; period events handle data refresh ──
    set hass(hass) {
        const oldLang = this._hass?.language;
        this._hass = hass;
        const lang = hass?.language;
        if (lang !== this._lang) {
            this._lang = lang;
            this.requestUpdate();
            return;
        }
        if (!this._period) this._setDefaultPeriod();
    }

    get hass() { return this._hass; }

    connectedCallback() {
        super.connectedCallback();
        document.addEventListener('sem-period-change', this._boundPeriodHandler);
    }

    disconnectedCallback() {
        super.disconnectedCallback();
        document.removeEventListener('sem-period-change', this._boundPeriodHandler);
        if (this._chart) { this._chart.destroy(); this._chart = null; }
        clearTimeout(this._fetchTimer);
    }

    firstUpdated() {
        if (!this._period) this._setDefaultPeriod();
    }

    // ── Static CSS ──
    static get styles() {
        return css`
            :host { display: block; }
            .sem-chart-wrap {
                padding: 16px;
                min-height: 280px;
                position: relative;
            }
            .chart-header { margin-bottom: 12px; }
            .chart-title {
                font-size: 15px; font-weight: 600;
                color: var(--primary-text-color, #e0e0e0);
                font-family: 'Segoe UI','Roboto',sans-serif;
                letter-spacing: 0.3px;
                font-variant-numeric: tabular-nums;
            }
            .chart-subtitle {
                font-size: 12px;
                color: var(--secondary-text-color, #757575);
                margin-top: 2px;
                font-family: 'Segoe UI','Roboto',sans-serif;
                font-variant-numeric: tabular-nums;
            }
            .chart-container {
                position: relative;
                height: 250px;
                filter: drop-shadow(0 0 1px rgba(200,220,240,0.10));
            }
            canvas { width: 100% !important; height: 100% !important; }
            .empty-msg {
                position: absolute;
                inset: 0;
                display: none;
                align-items: center;
                justify-content: center;
                color: var(--secondary-text-color, #616161);
                font-size: 13px;
                font-family: 'Segoe UI','Roboto',sans-serif;
            }
            .empty-msg.visible { display: flex; }
        `;
    }

    // ── Render: static skeleton; chart canvas is populated imperatively ──
    render() {
        const preset = this._preset || {};
        const title = this._config?.title || this._t(preset.title || 'SEM Chart');

        return html`
            <ha-card>
                <div class="sem-chart-wrap">
                    <div class="chart-header">
                        <div class="chart-title">${title}</div>
                        <div class="chart-subtitle"></div>
                    </div>
                    <div class="chart-container">
                        <canvas></canvas>
                        <div class="empty-msg">Loading\u2026</div>
                    </div>
                </div>
            </ha-card>
        `;
    }

    // ── Period handling ──
    _setDefaultPeriod() {
        const now = new Date();
        const dow = now.getDay() || 7;
        const mon = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        mon.setDate(mon.getDate() - (dow - 1));
        this._onPeriodChange({ start: mon, end: now, granularity: 'day', label: 'This Week', key: 'week' });
    }

    _onPeriodChange(detail) {
        this._period = detail;
        const sub = this.renderRoot?.querySelector('.chart-subtitle');
        if (sub) sub.textContent = detail.label || '';
        clearTimeout(this._fetchTimer);
        this._fetchTimer = setTimeout(() => this._fetchAndRender(), 150);
    }

    // ── Series resolution ──
    _resolveSeries() {
        if (this._config?.series) {
            return this._config.series.map(s => ({
                entity: s.entity, name: s.name || s.entity,
                color: s.color || '#42A5F5', type: s.type || 'bar', y_axis: s.y_axis || 0,
            }));
        }
        const p = this._preset;
        if (!p) return [];
        const g = this._period?.granularity || 'day';
        const defs = (g === 'hour' && p.hourly)
            ? p.hourly
            : (g === 'month' && p.monthly) ? p.monthly : (p.daily || p.hourly || []);
        return defs.map(d => ({
            entity: `${this._prefix}${d.suffix}`,
            name:   this._t(d.name),
            color:  d.color, type: d.type, y_axis: d.y_axis || 0,
        }));
    }

    // ── Data fetch + render ──
    async _fetchAndRender() {
        if (!this._hass || !this._period) return;
        const series = this._resolveSeries();
        if (!series.length) return;

        const { start, end, granularity } = this._period;

        let datasets;
        try {
            datasets = await this._fetchStatistics(series, start.toISOString(), end.toISOString(), granularity);
        } catch (err) {
            console.debug('sem-chart-card: fetch error', err);
            this._showEmpty(this._t('data_unavailable'));
            return;
        }

        if (!datasets || datasets.every(ds => !ds.data.length)) {
            this._showEmpty(this._t('no_data_for_period'));
            return;
        }

        this._hideEmpty();
        await this._renderChart(datasets, series);
    }

    async _fetchStatistics(series, startISO, endISO, granularity) {
        const statIds = series.map(s => s.entity);
        const period  = granularity === 'month' ? 'month' : granularity === 'hour' ? 'hour' : 'day';
        let stats;
        try {
            stats = await this._hass.callWS({
                type: 'recorder/statistics_during_period',
                start_time: startISO, end_time: endISO,
                statistic_ids: statIds, period, types: ['state', 'mean', 'max'],
            });
        } catch {
            stats = await this._hass.callWS({
                type: 'history/statistics_during_period',
                start_time: startISO, end_time: endISO,
                statistic_ids: statIds, period,
            });
        }
        return series.map(s => ({
            data: (stats[s.entity] || []).map(p => ({
                x: new Date(p.start),
                y: p.max ?? p.state ?? p.mean ?? 0,
            })),
        }));
    }

    async _renderChart(datasets, series) {
        const Chart = await _loadChartJs();
        const canvas = this.renderRoot.querySelector('canvas');
        if (!canvas) return;

        const T       = this._theme();
        const preset  = this._preset || {};
        const stacked = this._config?.stacked ?? preset.stacked ?? false;
        let yLabel    = this._config?.y_label || preset.y_label || '';
        if (yLabel === '_currency_') yLabel = semGetCurrency(this._hass);
        const y2Label = preset.y2_label || '';
        const hasY2   = series.some(s => s.y_axis === 1);
        const gran    = this._period?.granularity || 'day';

        const chartDatasets = series.map((s, i) => {
            const isArea = s.type === 'area';
            const isBar  = s.type === 'bar';
            return {
                label: s.name, data: datasets[i].data,
                backgroundColor: isBar ? s.color + 'CC' : isArea ? s.color + '40' : 'transparent',
                borderColor: s.color, borderWidth: isBar ? 0 : 2,
                fill: isArea ? 'origin' : false,
                type: isBar ? 'bar' : 'line',
                tension: 0.3, pointRadius: 0, pointHitRadius: 8,
                yAxisID: s.y_axis === 1 ? 'y1' : 'y',
                order: isBar ? 2 : 1,
            };
        });

        const timeUnit = gran === 'hour' ? 'hour' : gran === 'month' ? 'month' : 'day';

        const config = {
            type: 'bar',
            data: { datasets: chartDatasets },
            options: {
                responsive: true, maintainAspectRatio: false,
                animation: { duration: 400, easing: 'easeOutQuart' },
                interaction: { mode: 'index', intersect: false },
                plugins: {
                    legend: {
                        display: true, position: 'bottom',
                        labels: {
                            color: T.textSec || '#9e9e9e',
                            font: { size: 11, weight: '500', family: "'Segoe UI','Roboto',sans-serif" },
                            boxWidth: 12, boxHeight: 12, borderRadius: 3, useBorderRadius: true, padding: 12,
                        },
                    },
                    tooltip: {
                        backgroundColor: T.tooltipBg || 'rgba(20,20,30,0.95)',
                        titleColor: T.tooltipText || '#e0e0e0',
                        titleFont: { family: "'Segoe UI','Roboto',sans-serif", weight: '600' },
                        bodyColor: T.textSec || '#b0b0b0',
                        bodyFont: { family: "'Segoe UI','Roboto',sans-serif" },
                        borderColor: T.tooltipBorder || 'rgba(255,255,255,0.06)',
                        borderWidth: 1, cornerRadius: 12, padding: 12, bodySpacing: 5,
                        callbacks: {
                            label: (ctx) => {
                                const val = ctx.parsed.y;
                                const dec = Math.abs(val) < 10 ? 2 : 1;
                                return ` ${ctx.dataset.label}: ${val.toFixed(dec)} ${yLabel}`;
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
                            tooltipFormat: gran === 'hour' ? 'HH:mm' : gran === 'month' ? 'MMM yyyy' : 'dd MMM',
                            displayFormats: { hour: 'HH:mm', day: 'dd MMM', month: 'MMM' },
                        },
                        grid: { color: T.surface || 'rgba(255,255,255,0.03)', drawBorder: false },
                        ticks: { color: T.textSec || '#757575', font: { size: 10, family: "'Segoe UI','Roboto',sans-serif" }, maxRotation: 0 },
                        stacked,
                    },
                    y: {
                        position: 'left',
                        grid: { color: T.surface || 'rgba(255,255,255,0.04)', drawBorder: false },
                        ticks: {
                            color: T.textSec || '#757575',
                            font: { size: 10, family: "'Segoe UI','Roboto',sans-serif" },
                            callback: (v) => {
                                const abs = Math.abs(v);
                                if (abs >= 1000) return (v / 1000).toFixed(1) + 'k';
                                return v % 1 === 0 ? v : v.toFixed(1);
                            },
                        },
                        title: { display: !!yLabel, text: yLabel, color: T.textSec || '#757575', font: { size: 11 } },
                        stacked, beginAtZero: true,
                    },
                },
            },
        };

        if (hasY2) {
            config.options.scales.y1 = {
                position: 'right', grid: { drawOnChartArea: false },
                ticks: { color: '#42A5F5', font: { size: 10 }, callback: (v) => v + '%' },
                title: { display: !!y2Label, text: y2Label, color: '#42A5F5', font: { size: 11 } },
                min: 0, max: 100,
            };
        }

        if (this._chart) { this._chart.destroy(); this._chart = null; }
        this._chart = new Chart(canvas.getContext('2d'), config);
    }

    _showEmpty(msg) {
        const el = this.renderRoot.querySelector('.empty-msg');
        if (el) { el.textContent = msg; el.classList.add('visible'); }
        const c = this.renderRoot.querySelector('canvas');
        if (c) c.style.display = 'none';
    }

    _hideEmpty() {
        const el = this.renderRoot.querySelector('.empty-msg');
        if (el) el.classList.remove('visible');
        const c = this.renderRoot.querySelector('canvas');
        if (c) c.style.display = 'block';
    }

    getCardSize() { return 5; }

    static getStubConfig() {
        return { preset: 'costs' };
    }
}

semDefineCard('sem-chart-card', SEMChartCard, {
    type: 'sem-chart-card',
    name: 'SEM Chart',
    description: 'Period-reactive chart with glassmorphism styling and built-in presets',
});

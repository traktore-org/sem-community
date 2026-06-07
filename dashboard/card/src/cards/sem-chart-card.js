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
            { suffix: 'solar_power',             name: 'solar',       color: C.solar,      type: 'area' },
            { suffix: 'home_consumption_power',  name: 'home',        color: C.home,       type: 'area' },
            { suffix: 'grid_power',              name: 'grid',        color: C.gridImport, type: 'area' },
        ],
    },
    battery: {
        title: 'battery', y_label: 'W', y2_label: '%', stacked: false,
        hourly: [
            { suffix: 'battery_power',  name: 'power', color: C.batteryOut, type: 'area' },
            { suffix: 'battery_soc',    name: 'soc',   color: '#ff9800',    type: 'line', y_axis: 1 },
        ],
    },
    ev: {
        // ``defaultPeriod: 'today'`` (since-midnight) instead of '24h'
        // (rolling) so the chart matches ``daily_ev_energy``. Rolling
        // 24h includes yesterday-evening charges as a "phantom second
        // charge" in the morning view.
        title: 'ev_charging', y_label: 'W', stacked: true, defaultPeriod: 'today',
        hourly:  [
            { suffix: 'flow_solar_to_ev_power',   name: 'solar',   color: C.solar,      type: 'area' },
            { suffix: 'flow_battery_to_ev_power',  name: 'battery', color: C.batteryOut, type: 'area' },
            { suffix: 'flow_grid_to_ev_power',     name: 'grid',    color: C.gridImport, type: 'area' },
        ],
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
        this._cachedChartTheme = null;
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
        const title = this._config?.title ? this._t(this._config.title) : this._t(preset.title || 'SEM Chart');
        const subtitle = this._period?.labelKey ? this._t(this._period.labelKey) : '';

        return html`
            <ha-card>
                <div class="sem-chart-wrap">
                    <div class="chart-header">
                        <div class="chart-title">${title}</div>
                        <div class="chart-subtitle">${subtitle}</div>
                    </div>
                    <div class="chart-container">
                        <canvas></canvas>
                        <div class="empty-msg">${this._t('loading')}</div>
                    </div>
                </div>
            </ha-card>
        `;
    }

    // ── Period handling ──

    /**
     * Compute "start of day" in HA's configured timezone, not the
     * browser's. Returns a Date pointing at the SAME absolute moment
     * (so it's safe to serialise to ISO and send to the history API);
     * just the wall-clock interpretation matches HA's local time.
     *
     * #136 fix: pre-#136 ``new Date(now.getFullYear(), getMonth(), getDate())``
     * built the date in browser-local time. When HA's server timezone
     * differs (HA Companion app on a phone roaming across timezones,
     * or a desktop on a different DST schedule than the server) the
     * resulting "Today" window shifted by 1+ hours.
     */
    _startOfDayInHaTz(now) {
        const haTz = this._hass?.config?.time_zone;
        if (!haTz) {
            // Fallback to browser-local (pre-#136 behaviour) when hass
            // hasn't loaded a timezone yet.
            return new Date(now.getFullYear(), now.getMonth(), now.getDate());
        }
        try {
            // Format ``now`` in HA's timezone to get year/month/day in
            // that zone. Then ask for that wall-clock midnight as a UTC
            // offset string to construct an absolute Date.
            const fmt = new Intl.DateTimeFormat('en-US', {
                timeZone: haTz, year: 'numeric', month: '2-digit', day: '2-digit',
            });
            const parts = Object.fromEntries(
                fmt.formatToParts(now).map(p => [p.type, p.value])
            );
            // Compose an ISO-ish string in HA's tz, then reparse via the
            // tz-aware DateTimeFormat by iterating offsets until we hit
            // midnight-in-HA-tz. Simpler: use a fixed-offset trick via
            // a probe Date round-trip.
            //
            // We construct a Date by serialising "YYYY-MM-DDT00:00:00"
            // in HA's tz to UTC via a small offset-search. The reliable
            // primitive is: take a Date, format it in haTz, compute the
            // delta between what UTC says and what haTz says, and apply.
            const localMidnightAssumingHaTzMatchesBrowser = new Date(
                Number(parts.year),
                Number(parts.month) - 1,
                Number(parts.day),
                0, 0, 0, 0,
            );
            // Now correct for the offset between browser TZ and HA TZ.
            // What time IS this Date in HA's tz? If it differs from
            // 00:00, shift by that difference.
            const haTime = new Intl.DateTimeFormat('en-US', {
                timeZone: haTz, hour: '2-digit', minute: '2-digit',
                hour12: false,
            }).formatToParts(localMidnightAssumingHaTzMatchesBrowser);
            const haH = Number(haTime.find(p => p.type === 'hour').value);
            const haM = Number(haTime.find(p => p.type === 'minute').value);
            // If HA sees this moment as 22:30, we're 1.5h before HA midnight
            // → add 1.5h. If HA sees 02:00, we're 2h after → subtract 2h.
            const haMinutesPastMidnight = (haH * 60 + haM) % (24 * 60);
            const offsetMin = haMinutesPastMidnight === 0
                ? 0
                : haMinutesPastMidnight <= 12 * 60
                    ? -haMinutesPastMidnight       // ahead of midnight → roll back
                    : (24 * 60 - haMinutesPastMidnight); // before midnight → roll forward
            return new Date(localMidnightAssumingHaTzMatchesBrowser.getTime() + offsetMin * 60 * 1000);
        } catch (e) {
            // Defensive — never break the chart on a malformed TZ; fall
            // back to browser-local midnight (pre-#136 behaviour).
            return new Date(now.getFullYear(), now.getMonth(), now.getDate());
        }
    }

    _setDefaultPeriod() {
        const now = new Date();
        const p = this._preset;
        // Presets with defaultPeriod 'today' (since-midnight) or '24h'
        // (rolling) or hourly-only presets default to an hourly view.
        const wantToday = p && p.defaultPeriod === 'today';
        const isHourly = p && (wantToday || p.defaultPeriod === '24h' || (p.hourly && !p.daily));
        if (isHourly) {
            const start = wantToday
                ? this._startOfDayInHaTz(now)
                : new Date(now.getTime() - 24 * 60 * 60 * 1000);
            const labelKey = wantToday ? 'period_today' : 'last_24h';
            const key = wantToday ? 'today' : '24h';
            this._onPeriodChange({ start, end: now, granularity: 'hour', labelKey, key });
        } else {
            const dow = now.getDay() || 7;
            const mon = this._startOfDayInHaTz(now);
            mon.setDate(mon.getDate() - (dow - 1));
            this._onPeriodChange({ start: mon, end: now, granularity: 'day', labelKey: 'period_this_week', key: 'week' });
        }
    }

    _onPeriodChange(detail) {
        // Derive labelKey from key when not provided (period selector dispatches {key} only)
        const KEY_TO_LABEL = {
            today: 'period_today', yesterday: 'period_yesterday',
            week: 'period_this_week', month: 'period_this_month',
            year: 'period_this_year', '24h': 'last_24h',
        };
        this._period = { ...detail, labelKey: detail.labelKey || KEY_TO_LABEL[detail.key] };
        this.requestUpdate();
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
        // ``per_charger: true`` on the dashboard card config replaces
        // the default solar/battery/grid breakdown of the EV chart
        // with one series per discovered charger (multi-charger
        // installs). Each charger gets a distinct color from the
        // palette so the user can see which charger ran when.
        if (
            this._config?.per_charger
            && this._config?.preset === 'ev'
            && g === 'hour'
        ) {
            return this._discoverPerChargerSeries();
        }
        const defs = (g === 'hour' && p.hourly)
            ? p.hourly
            : (g === 'month' && p.monthly) ? p.monthly : (p.daily || p.hourly || []);
        return defs.map(d => ({
            entity: `${this._prefix}${d.suffix}`,
            name:   this._t(d.name),
            color:  d.color, type: d.type, y_axis: d.y_axis || 0,
        }));
    }

    _discoverPerChargerSeries() {
        const states = this._hass?.states || {};
        const palette = [
            '#8DC892', '#64B5F6', '#FFB74D', '#BA68C8',
            '#4DB6AC', '#F06292', '#A1887F', '#7986CB',
        ];
        const re = /^sensor\.sem_charger_(.+)_power$/;
        const found = [];
        for (const eid of Object.keys(states)) {
            const m = eid.match(re);
            if (!m) continue;
            const id = m[1];
            const friendly = states[eid]?.attributes?.friendly_name
                ?.replace(/^SEM\s+/i, '').replace(/\s+Power$/i, '')
                || id.replace(/_/g, ' ');
            found.push({ id, eid, friendly });
        }
        found.sort((a, b) => a.id.localeCompare(b.id));
        return found.map((c, i) => ({
            entity: c.eid,
            name:   c.friendly,
            color:  palette[i % palette.length],
            type:   'area',
            y_axis: 0,
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
        const ctx2d   = canvas.getContext('2d');

        const chartDatasets = series.map((s, i) => {
            const isArea = s.type === 'area';
            const isBar  = s.type === 'bar';
            return {
                label: s.name, data: datasets[i].data,
                backgroundColor: isBar ? s.color + 'CC' : isArea ? s.color + '30' : 'transparent',
                borderColor: s.color, borderWidth: isBar ? 0 : 2,
                fill: isArea ? (stacked && i > 0 ? '-1' : 'origin') : false,
                type: isBar ? 'bar' : 'line',
                tension: 0.4, pointRadius: 0, pointHitRadius: 10,
                pointHoverRadius: 4, pointHoverBorderWidth: 2,
                pointHoverBackgroundColor: s.color,
                pointHoverBorderColor: '#fff',
                yAxisID: s.y_axis === 1 ? 'y1' : 'y',
                order: isBar ? 2 : 1,
                borderRadius: isBar ? 4 : 0,
                barPercentage: 0.7,
            };
        });

        const timeUnit = gran === 'hour' ? 'hour' : gran === 'month' ? 'month' : 'day';

        // Plugin: vertical crosshair line on hover
        const crosshairPlugin = {
            id: 'crosshair',
            afterDraw(chart) {
                if (chart.tooltip?._active?.length) {
                    const x = chart.tooltip._active[0].element.x;
                    const yAxis = chart.scales.y;
                    const ctx = chart.ctx;
                    ctx.save();
                    ctx.beginPath();
                    ctx.moveTo(x, yAxis.top);
                    ctx.lineTo(x, yAxis.bottom);
                    ctx.lineWidth = 1;
                    ctx.strokeStyle = 'rgba(255,255,255,0.15)';
                    ctx.stroke();
                    ctx.restore();
                }
            },
        };

        // Plugin: gradient fills for area series (runs after layout)
        const gradientPlugin = {
            id: 'gradientFill',
            beforeDatasetsDraw(chart) {
                const ctx = chart.ctx;
                chart.data.datasets.forEach((ds, idx) => {
                    if (series[idx]?.type !== 'area') return;
                    const meta = chart.getDatasetMeta(idx);
                    if (meta.hidden) return;
                    const yScale = chart.scales[ds.yAxisID || 'y'];
                    if (!yScale) return;
                    const grad = ctx.createLinearGradient(0, yScale.top, 0, yScale.bottom);
                    grad.addColorStop(0, ds.borderColor + '60');
                    grad.addColorStop(0.6, ds.borderColor + '18');
                    grad.addColorStop(1, ds.borderColor + '02');
                    ds.backgroundColor = grad;
                });
            },
        };

        const config = {
            type: 'bar',
            data: { datasets: chartDatasets },
            plugins: [crosshairPlugin, gradientPlugin],
            options: {
                responsive: true, maintainAspectRatio: false,
                animation: { duration: 300, easing: 'easeOutQuart' },
                interaction: { mode: 'index', intersect: false },
                plugins: {
                    legend: {
                        display: true, position: 'bottom',
                        labels: {
                            color: T.textSec || '#9e9e9e',
                            font: { size: 11, weight: '500', family: "'Segoe UI','Roboto',sans-serif" },
                            boxWidth: 12, boxHeight: 12, borderRadius: 3, useBorderRadius: true, padding: 14,
                            generateLabels: (chart) => {
                                const orig = Chart.defaults.plugins.legend.labels.generateLabels(chart);
                                return orig.map((label, i) => {
                                    const ds = chart.data.datasets[i];
                                    if (!ds) return label;
                                    const last = ds.data[ds.data.length - 1];
                                    const val = last?.y ?? 0;
                                    const unit = ds.yAxisID === 'y1' ? '%' : (yLabel || '');
                                    const abs = Math.abs(val);
                                    const fmt = abs >= 1000 ? (val / 1000).toFixed(1) + 'k' : abs < 10 ? val.toFixed(1) : val.toFixed(0);
                                    label.text = `${label.text}: ${fmt} ${unit}`;
                                    return label;
                                });
                            },
                        },
                    },
                    tooltip: {
                        backgroundColor: T.tooltipBg || 'rgba(15,18,25,0.94)',
                        titleColor: T.tooltipText || '#e0e0e0',
                        titleFont: { family: "'Segoe UI','Roboto',sans-serif", weight: '600', size: 12 },
                        bodyColor: T.textSec || '#b0b0b0',
                        bodyFont: { family: "'Segoe UI','Roboto',sans-serif", size: 11 },
                        borderColor: T.tooltipBorder || 'rgba(255,255,255,0.08)',
                        borderWidth: 1, cornerRadius: 10, padding: { top: 10, bottom: 10, left: 14, right: 14 },
                        bodySpacing: 6, displayColors: true, boxPadding: 4,
                        callbacks: {
                            label: (item) => {
                                const val = item.parsed.y;
                                const unit = item.dataset.yAxisID === 'y1' ? '%' : yLabel;
                                const abs = Math.abs(val);
                                const fmt = abs >= 1000 ? (val / 1000).toFixed(1) + 'k' : abs < 10 ? val.toFixed(2) : val.toFixed(1);
                                return ` ${item.dataset.label}: ${fmt} ${unit}`;
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
                        grid: { color: 'rgba(255,255,255,0.02)', drawBorder: false, drawTicks: false },
                        ticks: {
                            color: T.textSec || '#757575',
                            font: { size: 10, family: "'Segoe UI','Roboto',sans-serif" },
                            maxRotation: 0, padding: 6,
                            callback: (val, idx, ticks) => {
                                const tick = ticks[idx];
                                if (!tick) return val;
                                const d = new Date(tick.value);
                                if (isNaN(d)) return val;
                                const lang = this._hass?.language || 'en';
                                if (timeUnit === 'hour') return d.toLocaleTimeString(lang, { hour: '2-digit', minute: '2-digit' });
                                if (timeUnit === 'month') return d.toLocaleDateString(lang, { month: 'short' });
                                return d.toLocaleDateString(lang, { day: 'numeric', month: 'short' });
                            },
                        },
                        stacked,
                    },
                    y: {
                        position: 'left',
                        grid: { color: 'rgba(255,255,255,0.04)', drawBorder: false, drawTicks: false },
                        ticks: {
                            color: T.textSec || '#757575',
                            font: { size: 10, family: "'Segoe UI','Roboto',sans-serif" },
                            padding: 8,
                            callback: (v) => {
                                const abs = Math.abs(v);
                                if (abs >= 1000) return (v / 1000).toFixed(1) + 'k';
                                if (abs < 0.01 && abs > 0) return '';
                                return v % 1 === 0 ? v : v.toFixed(1);
                            },
                        },
                        title: { display: !!yLabel, text: yLabel, color: T.textSec || '#757575', font: { size: 11, family: "'Segoe UI','Roboto',sans-serif" } },
                        stacked,
                        beginAtZero: yLabel !== 'W',
                    },
                },
            },
        };

        if (hasY2) {
            config.options.scales.y1 = {
                position: 'right',
                grid: { drawOnChartArea: false, drawTicks: false },
                ticks: {
                    color: '#ff9800', font: { size: 10 }, padding: 8,
                    callback: (v) => v + '%',
                },
                title: { display: !!y2Label, text: y2Label, color: '#ff9800', font: { size: 11 } },
                min: 0, max: 100,
            };
        }

        if (this._chart) { this._chart.destroy(); this._chart = null; }
        this._chart = new Chart(ctx2d, config);
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

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

import { SEMLitBase, html, css, nothing, semGlassCss } from '../base/sem-lit-base.js';
import { semTheme, semGetCurrency, semDefineCard, SEM_COLORS } from '../base/sem-shared.js';
import { startOfDayInHaTz } from '../util/time-zone.js';
import { formatLegendLabels } from '../util/legend-format.js';

/* ── Chart.js singleton loader — LOCAL first, CDN fallback (#617) ──
   The library ships vendored under dashboard/card/vendor/ and is served
   from SEM's static path, so charts work offline / on isolated installs.
   The CDN remains only as a fallback for installs whose static path
   registration failed. */
const _CHARTJS_SOURCES = [
    '/local/custom_components/solar_energy_management/dashboard/card/vendor/chart.umd.min.js',
    'https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js',
];
const _ADAPTER_SOURCES = [
    '/local/custom_components/solar_energy_management/dashboard/card/vendor/chartjs-adapter-date-fns.bundle.min.js',
    'https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3.0.0/dist/chartjs-adapter-date-fns.bundle.min.js',
];

function _loadScriptChain(sources, resolve, reject) {
    if (!sources.length) { reject(new Error('all sources failed')); return; }
    const script = document.createElement('script');
    script.src = sources[0];
    script.onload = () => resolve();
    script.onerror = () => _loadScriptChain(sources.slice(1), resolve, reject);
    document.head.appendChild(script);
}

let _chartJsReady = null;
function _loadChartJs() {
    if (_chartJsReady) return _chartJsReady;
    _chartJsReady = new Promise((resolve, reject) => {
        // adapter is optional — resolve with Chart either way
        const loadAdapter = () => _loadScriptChain(_ADAPTER_SOURCES,
            () => resolve(window.Chart),
            () => resolve(window.Chart));
        if (window.Chart) {
            // (#646) another card's bundle may have defined window.Chart
            // WITHOUT the date adapter — the old early-exit skipped the
            // adapter entirely, so time-scale presets (energy "Last 7 Days")
            // threw "a complete date adapter is provided". The adapter
            // registers against the existing Chart; double-load is harmless.
            const hasDateAdapter = (() => {
                // the unextended stub's formats() just throws
                try { new window.Chart._adapters._date({}).formats(); return true; }
                catch { return false; }
            })();
            if (hasDateAdapter) { resolve(window.Chart); return; }
            loadAdapter();
            return;
        }
        _loadScriptChain(_CHARTJS_SOURCES, loadAdapter,
            () => reject(new Error('Failed to load Chart.js')));
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
            // (#585) cash-flow sign convention: Import (spending) drawn NEGATIVE
            // / below the axis, Export (earnings) positive, Net signed so a
            // net earning reads positive (up) — see _fetchStatistics negate.
            { suffix: 'daily_costs',           name: 'Import',  color: C.gridImport, type: 'bar',  negate: true },
            { suffix: 'daily_export_revenue',   name: 'export',  color: C.gridExport, type: 'bar'  },
            { suffix: 'daily_net_cost',         name: 'net',     color: C.solar,      type: 'line', negate: true },
        ],
        monthly: [
            { suffix: 'monthly_costs',          name: 'Import',  color: C.gridImport, type: 'bar',  negate: true },
            { suffix: 'monthly_export_revenue', name: 'export',  color: C.gridExport, type: 'bar'  },
            { suffix: 'monthly_net_cost',       name: 'net',     color: C.solar,      type: 'line', negate: true },
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
        // #523: rolling last-7-days, not "this week" (Mon→now). On Mondays
        // "this week" collapses to a single day-bucket, which renders as
        // one stray bar and contradicts the "Last 7 days" card title.
        title: 'energy_balance', y_label: 'kWh', stacked: false, defaultPeriod: '7d',
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
    // #575: forecast vs actual solar power. The apexcharts original plotted
    // ``forecast_power_now_w`` (recorder history = the forecast curve) against
    // ``solar_power``; the LitElement migration lost it by pointing the card at
    // ``preset: power`` (a plain solar/home/grid chart with no forecast series).
    forecast: {
        title: 'forecast_vs_actual', y_label: 'W', stacked: false,
        hourly: [
            { suffix: 'forecast_power_now_w', name: 'forecast', color: C.solar,      type: 'area' },
            { suffix: 'solar_power',          name: 'actual',   color: C.batteryOut, type: 'line' },
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
        // Anchor the EV power axis at 0 with a 2 kW floor: a plugged-in idle car
        // draws ~130 W of standby/handshake, which auto-scaling would otherwise
        // blow up to fill the whole chart and read like a real charge. With a
        // 2 kW suggestedMax that standby renders flat near zero, while a real
        // charge (≥ a few kW) still extends the axis normally.
        y_min: 0, y_suggested_max: 2000,
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
        this._emptyMsg = '';
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
        // #541: a relative window ('today'/'24h'/'7d'/'week') is computed once
        // and would otherwise freeze on the day it first rendered — a long-open
        // app then shows yesterday's data this morning. Re-roll it on a timer
        // and on app resume / tab focus so the window tracks "now".
        this._rollInterval = setInterval(() => this._rollRelativePeriod(), 5 * 60 * 1000);
        this._boundVisibility = () => { if (!document.hidden) this._rollRelativePeriod(); };
        document.addEventListener('visibilitychange', this._boundVisibility);
    }

    disconnectedCallback() {
        super.disconnectedCallback();
        document.removeEventListener('sem-period-change', this._boundPeriodHandler);
        if (this._boundVisibility) document.removeEventListener('visibilitychange', this._boundVisibility);
        clearInterval(this._rollInterval);
        if (this._chart) { this._chart.destroy(); this._chart = null; }
        clearTimeout(this._fetchTimer);
    }

    /** #541: recompute the card's default relative window from "now" and
     *  re-fetch, so a long-open app rolls the day boundary instead of showing
     *  a stale day. Only acts when the card is still showing its OWN default
     *  window — a user-changed/custom range is left untouched. */
    _rollRelativePeriod() {
        if (!this._period || !this._hass) return;
        const dp = this._config?.default_period || this._preset?.defaultPeriod;
        const defaultKey = dp === '24h' ? '24h' : dp === '7d' ? '7d'
            : dp === 'today' ? 'today' : 'week';
        if (this._period.key !== defaultKey) return;
        this._setDefaultPeriod();   // recomputes start/end from now + re-fetches
    }

    firstUpdated() {
        if (!this._period) this._setDefaultPeriod();
    }

    // ── Static CSS ──
    static get styles() {
        // #617 — glass chrome baked in (was card-mod *glass_card)
        return [semGlassCss, css`
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
        `];
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
                        <canvas style="display:${this._emptyMsg ? 'none' : 'block'}"></canvas>
                        <div class="empty-msg ${this._emptyMsg ? 'visible' : ''}">${this._emptyMsg}</div>
                    </div>
                </div>
            </ha-card>
        `;
    }

    // ── Period handling ──

    /**
     * Compute "start of day" in HA's configured timezone, not the
     * browser's. Thin wrapper around the extracted ``startOfDayInHaTz``
     * util so the logic is testable in isolation (see
     * ``test/time-zone.test.js``).
     */
    _startOfDayInHaTz(now) {
        return startOfDayInHaTz(now, this._hass?.config?.time_zone);
    }

    _setDefaultPeriod() {
        const now = new Date();
        const p = this._preset;
        // A per-card ``default_period`` config wins over the preset's own.
        const defaultPeriod = this._config?.default_period || (p && p.defaultPeriod);
        // Presets with defaultPeriod 'today' (since-midnight) or '24h'
        // (rolling) or hourly-only presets default to an hourly view.
        const wantToday = defaultPeriod === 'today';
        const isHourly = p && (wantToday || defaultPeriod === '24h' || (p.hourly && !p.daily));
        if (isHourly) {
            const start = wantToday
                ? this._startOfDayInHaTz(now)
                : new Date(now.getTime() - 24 * 60 * 60 * 1000);
            const labelKey = wantToday ? 'period_today' : 'last_24h';
            const key = wantToday ? 'today' : '24h';
            this._onPeriodChange({ start, end: now, granularity: 'hour', labelKey, key });
        } else if (defaultPeriod === '7d') {
            // Rolling last-7-days (#523): always 7 day-buckets, no Monday
            // single-bar collapse, matching the "Last 7 days" title.
            const start = this._startOfDayInHaTz(now);
            start.setDate(start.getDate() - 6);
            this._onPeriodChange({ start, end: now, granularity: 'day', labelKey: 'last_7_days', key: '7d' });
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
            year: 'period_this_year', '24h': 'last_24h', '7d': 'last_7_days',
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
        // (#792) The legend sums accumulating series and samples instantaneous
        // ones, so it needs to know which this is. That is decided HERE and
        // nowhere else: the granularity alone can't answer it, because a preset
        // with no `daily` block (power, battery, forecast) falls back to its
        // HOURLY defs on a day range — watts in day buckets, which must not be
        // added up. Only defs that came from `daily`/`monthly` are totals.
        const cumulative = defs === p.daily || defs === p.monthly;
        return defs.map(d => ({
            entity: `${this._prefix}${d.suffix}`,
            name:   this._t(d.name),
            color:  d.color, type: d.type, y_axis: d.y_axis || 0,
            negate: d.negate || false,
            cumulative,
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
        // Canvas visibility is lit-bound to _emptyMsg now — wait for the
        // update to land so Chart.js sizes against a visible canvas.
        await this.updateComplete;
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
        // On a STACKED power chart (e.g. EV charging power = solar+battery+grid
        // → EV) the series are COMPONENTS that must sum to a total. Plotting the
        // per-bucket MAX and stacking triple-counts: each component's max occurs
        // at a different instant (when solar peaks, grid is 0), so the stacked
        // maxes far exceed the real instantaneous total — a KEBA charging at
        // 4.4 kW showed an 11 kW "grid" peak that never happened. Use the MEAN
        // for stacked power charts so the parts sum correctly (mean of the sum =
        // sum of the means) and the area integrates to real energy. Non-stacked
        // charts keep MAX so peaks stay visible.
        const stacked = this._config?.stacked ?? this._preset?.stacked ?? false;
        const stackedPower = stacked && period === 'hour';
        return series.map(s => ({
            data: (stats[s.entity] || []).map(p => {
                let y = stackedPower
                    ? (p.mean ?? p.state ?? 0)
                    : (p.max ?? p.state ?? p.mean ?? 0);
                // (#585) cash-flow sign: negated series (Import / Net cost) are
                // drawn below the axis, so spending points down and a net
                // earning reads positive. Legend totals read the same y, so
                // they stay consistent with the bars/line.
                if (s.negate) y = -y;
                return { x: new Date(p.start), y };
            }),
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
                // (#792) rides along so the legend's sum-vs-sample choice stays
                // paired with its OWN series through Chart.js' order sorting.
                cumulative: !!s.cumulative,
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
                            generateLabels: (chart) => formatLegendLabels(
                                Chart.defaults.plugins.legend.labels.generateLabels(chart),
                                chart.data.datasets,
                                yLabel,
                            ),
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
                            // Tooltip time in HA's home timezone (DST-aware), not the
                            // viewer's browser tz — matches the axis labels.
                            title: (items) => {
                                if (!items || !items.length) return '';
                                const d = new Date(items[0].parsed.x);
                                if (isNaN(d)) return '';
                                const lang = this._hass?.language || 'en';
                                const tz = this._hass?.config?.time_zone || undefined;
                                try {
                                    if (gran === 'hour') return d.toLocaleTimeString(lang, { hour: '2-digit', minute: '2-digit', timeZone: tz });
                                    if (gran === 'month') return d.toLocaleDateString(lang, { month: 'short', year: 'numeric', timeZone: tz });
                                    return d.toLocaleDateString(lang, { day: 'numeric', month: 'short', timeZone: tz });
                                } catch (e) {
                                    // Bad tz string → fall back to browser-local rather than blank the chart.
                                    return gran === 'hour' ? d.toLocaleTimeString(lang) : d.toLocaleDateString(lang);
                                }
                            },
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
                                // Render in HA's configured home timezone, not the
                                // viewer's browser tz — and via the IANA zone name so
                                // it is DST-aware (a browser stuck on CET would otherwise
                                // show summer times 1 h early).
                                const tz = this._hass?.config?.time_zone || undefined;
                                try {
                                    if (timeUnit === 'hour') return d.toLocaleTimeString(lang, { hour: '2-digit', minute: '2-digit', timeZone: tz });
                                    if (timeUnit === 'month') return d.toLocaleDateString(lang, { month: 'short', timeZone: tz });
                                    return d.toLocaleDateString(lang, { day: 'numeric', month: 'short', timeZone: tz });
                                } catch (e) {
                                    // Bad tz string → fall back to browser-local rather than blank the axis.
                                    return timeUnit === 'hour' ? d.toLocaleTimeString(lang, { hour: '2-digit', minute: '2-digit' }) : d.toLocaleDateString(lang, { day: 'numeric', month: 'short' });
                                }
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
                        beginAtZero: yLabel !== 'W' || this._preset?.y_min === 0,
                        // Per-preset axis floor (e.g. EV: don't zoom into standby noise).
                        ...(this._preset?.y_min != null ? { min: this._preset.y_min } : {}),
                        ...(this._preset?.y_suggested_max != null ? { suggestedMax: this._preset.y_suggested_max } : {}),
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

    // Empty-state is fully lit-rendered via _emptyMsg. The previous version
    // imperatively overwrote .textContent on a node that ALSO had a lit text
    // binding — destroying lit's text part so the next requestUpdate() threw
    // "Cannot set properties of null" and froze the card (the #457 bug
    // class; this was its second instance, after the system diagram card).
    _showEmpty(msg) {
        this._emptyMsg = msg;
        this.requestUpdate();
    }

    _hideEmpty() {
        if (!this._emptyMsg) return;
        this._emptyMsg = '';
        this.requestUpdate();
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
    documentationURL:
        'https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-chart-card',
});

/**
 * SEM Next · Insights (#1321)
 *
 * One period for every chart: Today · Yesterday · Week · Month · Year. Seven
 * sub-tabs: Energy (house by source, where it went, solar, shares), Power
 * (24 h curves), Battery (power and charge), Car (per charger, sessions,
 * progress), Money (bought vs saved, payback, car economics, tariff),
 * Forecast (actual vs expected sun, accuracy) and Replay (the simulation
 * card). Charts are hand-drawn SVG fed by the recorder over the websocket
 * (util/next-history.js). A missing entity leaves its series or row out; a
 * chart with no data shows one hint line.
 *
 * Config:
 *   type: custom:sem-next-insights-card
 */

import { SEMNextBase, html, svg, nothing, nextCss, NEXT_COLORS as C } from '../base/sem-next-base.js';
import { semDefineCard, semDiscoverPVStrings } from '../base/sem-shared.js';
import { bucketsFor, fetchSeries, fetchPeriodFor, bucketValues, stackModel, lineModel, sunCurve } from '../util/next-history.js';
import { monthTotals, rowsForMonth, sessionRowView, shiftMonth, sessionMonth } from '../util/sessions.js';
import { downloadBase64 } from '../util/download.js';
import { providerName, trustConsequence } from '../util/forecast-evidence.js';
import './sem-simulation-card.js';

const PERIODS = {
    day: {
        solar: 'daily_solar_energy', grid_in: 'daily_grid_import_energy', grid_out: 'daily_grid_export_energy',
        battery: 'daily_battery_discharge_energy', batt_in: 'daily_battery_charge_energy', car: 'daily_ev_energy', house: 'daily_home_energy',
        cost: 'daily_costs', saved: 'daily_savings', batt_saved: 'daily_battery_savings', export_rev: 'daily_export_revenue',
        co2: 'daily_co2_avoided', forecast: 'forecast_today_kwh',
    },
    month: {
        solar: 'monthly_solar_yield_energy', grid_in: 'monthly_grid_import_energy', grid_out: 'monthly_grid_export_energy',
        battery: 'monthly_battery_discharge_energy', batt_in: 'monthly_battery_charge_energy', car: 'monthly_ev_consumption_energy', house: 'monthly_home_consumption_energy',
        cost: 'monthly_costs', saved: 'monthly_savings', batt_saved: 'monthly_battery_savings', export_rev: 'monthly_export_revenue',
    },
    year: {
        solar: 'yearly_solar_yield_energy', grid_in: 'yearly_grid_import_energy', grid_out: 'yearly_grid_export_energy',
        battery: 'yearly_battery_discharge_energy', batt_in: 'yearly_battery_charge_energy', car: 'yearly_ev_energy', house: 'yearly_home_consumption_energy',
        cost: 'yearly_costs', saved: 'yearly_savings', batt_saved: 'yearly_battery_savings', export_rev: 'yearly_export_revenue',
        co2: 'yearly_co2_avoided', lifetime: 'lifetime_total_savings',
    },
};
const PERIOD_KEYS = [['day', 'next_period_day'], ['yesterday', 'next_period_yesterday'], ['week', 'next_period_week'],
                     ['month', 'next_period_month'], ['year', 'next_period_year']];
const TABS = [['energy', 'next_tab_energy'], ['power', 'next_tab_power'], ['battery', 'next_tab_battery'], ['car', 'next_tab_car'],
              ['money', 'next_tab_money'], ['forecast', 'next_tab_forecast'], ['replay', 'next_replay']];
const S = 'sensor.sem_';
const HOME_FLOWS = [['solar', C.solar, 'next_from_sun'], ['battery', C.battery_out, 'next_from_battery'], ['grid', C.grid, 'next_from_grid']];
const SINKS = [['home', 'mdi:home', 'next_src_house', ['solar', 'battery', 'grid']], ['ev', 'mdi:car-electric', 'next_src_car', ['solar', 'battery', 'grid']],
               ['battery', 'mdi:battery-charging', 'next_battery_in', ['solar', 'grid']], ['grid', 'mdi:transmission-tower-export', 'next_export', ['solar', 'battery']]];
const SRC_COLOR = { solar: C.solar, battery: C.battery_out, grid: C.grid };
const CHARGER_COLORS = [C.ev, C.battery_out, C.grid, C.export, C.battery_in, C.home];
const XLSX_MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';
const SOLAR_IDS = ['monthly_solar_yield_energy', 'yearly_solar_yield_energy', 'pv_daily_specific_yield', 'pv_estimated_annual_degradation',
                   'pv_health', 'best_surplus_window', 'self_consumption_rate', 'autarky_rate', 'lifetime_co2_avoided', 'lifetime_trees_equivalent',
                   'yearly_trees_equivalent', 'roi_payback_years', 'roi_percentage', 'monthly_consecutive_peak', 'power_charge_cost',
                   'tariff_provider', 'tariff_price_level', 'tariff_current_import_rate', 'tariff_current_export_rate',
                   'lifetime_ev_energy', 'lifetime_ev_cost', 'lifetime_ev_solar_share', 'lifetime_ev_battery_share', 'lifetime_ev_grid_share',
                   'lifetime_ev_sessions', 'forecast_tomorrow_kwh', 'forecast_source', 'forecast_trust_d1', 'forecast_trust_d2',
                   'pv_performance_vs_forecast', 'battery_dynamic_floor_pct', 'battery_soc'];
const flowId = (src, sink) => `${S}flow_${src}_to_${sink}_energy`;
const ymd = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

class SEMNextInsightsCard extends SEMNextBase {
    static get properties() {
        return { _period: { state: true }, _tab: { state: true }, _hist: { state: true }, _hover: { state: true },
                 _w: { state: true }, _sess: { state: true }, _sessCid: { state: true }, _showSankey: { state: true } };
    }
    static get styles() { return nextCss; }

    constructor() {
        super();
        this._period = 'day';
        this._tab = 'energy';
        this._hist = null;
        this._histKey = '';
        this._hover = -1;
        this._w = 0;
        this._sess = {};
        this._sessCid = '';
        this._ro = null;
        this._refresh = null;
        this._needKey = '';
    }

    connectedCallback() {
        super.connectedCallback();
        const h = (typeof window !== 'undefined' && window.location ? window.location.hash : '').slice(1);
        if (TABS.some(([k]) => k === h)) this._tab = h;
        if (typeof ResizeObserver !== 'undefined') {
            this._ro = new ResizeObserver((entries) => {
                const w = Math.round(entries[0]?.contentRect?.width || 0);
                if (w && w !== this._w) this._w = w;
            });
            this._ro.observe(this);
        }
        this._refresh = setInterval(() => { this._histKey = ''; this._load(); }, 5 * 60e3);
    }

    disconnectedCallback() {
        if (this._ro) { this._ro.disconnect(); this._ro = null; }
        clearInterval(this._refresh);
        this._refresh = null;
        super.disconnectedCallback();
    }

    _watchIds() {
        const ids = [];
        for (const p of Object.values(PERIODS)) for (const k of Object.values(p)) ids.push(S + k);
        for (const k of SOLAR_IDS) ids.push(S + k);
        for (const [, , , srcs] of SINKS) for (const s of srcs) ids.push(flowId(s, 'home'));
        for (const cid of this._chargers) ids.push(`${S}charger_${cid}_daily_energy`);
        ids.push('switch.sem_simulation_tab', 'number.sem_system_investment_cost', 'number.sem_demand_charge_rate', S + 'average_purchase_price');
        return [...super._watchIds(), ...ids];
    }

    set hass(hass) {
        super.hass = hass;
        if (!hass) return;
        // Ask for history only when the period, the tab, the day or the set of
        // entities changed; the setter runs on every state change.
        const need = this._needs();
        const key = [this._period, this._tab, ymd(new Date()), need.total.join(','), need.mean.join(',')].join('|');
        if (key !== this._needKey) { this._needKey = key; this._load(); }
    }
    get hass() { return this._hass; }

    willUpdate(changed) {
        super.willUpdate?.(changed);
        const simOn = !this._has('switch.sem_simulation_tab') || this._str('switch.sem_simulation_tab') === 'on';
        if (!simOn && this._tab === 'replay') this._tab = 'energy';
        if (this._tab === 'car' && this._chargers.length) {
            if (!this._sessCid || !this._chargers.includes(this._sessCid)) this._sessCid = this._chargers[0];
            for (const cid of this._chargers) if (!this._sess[cid]) this._loadSessions(cid);
        }
    }

    // ── data ──
    _chartW() { return Math.max(280, (this._w || 640) - 48); }
    _hourly() { return this._period === 'day' || this._period === 'yesterday'; }
    _live() { return this._period === 'day' || this._period === 'month' || this._period === 'year'; }

    /** Which statistics this tab and period need: { total: [ids], mean: [ids] }, existing entities only. */
    _needs() {
        const T = new Set(), M = new Set();
        if (!this._live()) {
            for (const k of ['house', 'solar', 'cost', 'saved', 'batt_saved', 'export_rev', 'car', 'batt_in', 'battery', 'co2']) T.add(S + PERIODS.day[k]);
            T.add(flowId('solar', 'home'));
        }
        if (this._tab === 'energy') {
            for (const [, , , srcs] of SINKS) for (const s of srcs) T.add(flowId(s, 'home'));
            if (this._period !== 'day') for (const [sink, , , srcs] of SINKS) for (const s of srcs) T.add(flowId(s, sink));
        } else if (this._tab === 'power') {
            for (const k of ['solar_power', 'home_consumption_power', 'grid_power', 'battery_power']) M.add(S + k);
        } else if (this._tab === 'battery') {
            M.add(S + 'battery_power'); M.add(S + 'battery_soc');
            T.add(S + PERIODS.day.batt_in); T.add(S + PERIODS.day.battery);
        } else if (this._tab === 'car') {
            for (const cid of this._chargers) T.add(`${S}charger_${cid}_daily_energy`);
        } else if (this._tab === 'money') {
            for (const k of ['cost', 'saved', 'batt_saved', 'export_rev']) T.add(S + PERIODS.day[k]);
        } else if (this._tab === 'forecast') {
            if (this._hourly()) { M.add(S + 'solar_power'); M.add(S + 'forecast_power_now_w'); }
            else { T.add(S + 'daily_solar_energy'); M.add(S + 'forecast_today_kwh'); }
        }
        return { total: [...T].filter((id) => this._has(id)), mean: [...M].filter((id) => this._has(id)) };
    }

    async _load() {
        if (!this._hass || this._tab === 'replay') return;
        const b = bucketsFor(this._period, new Date(), { tz: this._hass.config?.time_zone, lang: this._hass.language });
        const need = this._needs();
        const key = [this._period, b.start.getTime(), need.total.join(','), need.mean.join(',')].join('|');
        if (key === this._histKey) return;
        this._histKey = key;
        const series = {};
        try {
            for (const kind of ['total', 'mean']) {
                const ids = need[kind];
                if (!ids.length) continue;
                const data = await fetchSeries(this._hass, ids, b.start.toISOString(), b.end.toISOString(), fetchPeriodFor(b, kind));
                for (const id of ids) series[id] = bucketValues(data[id], b, kind);
            }
        } catch (_e) { /* the chart shows its hint line */ }
        if (key !== this._histKey) return;
        this._hist = { key, buckets: b, series };
    }

    _series(id) { return this._hist?.series?.[id] || null; }
    _sum(id) { const s = this._series(id); return s ? s.reduce((a, v) => a + (v || 0), 0) : null; }
    _buckets() { return this._hist?.buckets || bucketsFor(this._period, new Date(), { tz: this._hass?.config?.time_zone, lang: this._hass?.language }); }

    /** A period total: the live sensor today, this month and this year; the summed statistics otherwise. */
    _pt(name) {
        if (this._live()) {
            const key = PERIODS[this._period === 'day' ? 'day' : this._period][name];
            return key ? this._num(S + key) : null;
        }
        const key = PERIODS.day[name];
        return key ? this._sum(S + key) : null;
    }
    _periodLabel() { return this._t((PERIOD_KEYS.find(([k]) => k === this._period) || PERIOD_KEYS[0])[1]); }

    _lead() {
        const house = this._pt('house'), cost = this._pt('cost');
        const sunSaved = this._pt('saved'), battSaved = this._pt('batt_saved');
        const saved = sunSaved === null && battSaved === null ? null : (sunSaved || 0) + (battSaved || 0);
        // One basis with the Shares ring: SEM's own-supply rate, which does not
        // count battery energy that came from the grid. It is a daily figure.
        const own = this._period === 'day' ? this._num(S + 'autarky_rate') : null;
        const cur = this._currency();
        const period = this._periodLabel();
        if (own !== null && cost !== null) {
            return this._tf('next_ins_lead_own', { period, pct: Math.round(Math.max(0, Math.min(100, own))), cost: this._fmt(cost, 2), saved: this._fmt(saved ?? 0, 2), cur });
        }
        if (cost !== null) return this._tf('next_ins_lead_money', { period, cost: this._fmt(cost, 2), saved: this._fmt(saved ?? 0, 2), cur });
        const solar = this._pt('solar');
        if (house !== null && solar !== null) return this._tf('next_ins_lead_energy', { period, house: this._fmt(house, 1), solar: this._fmt(solar, 1) });
        return this._t('next_ins_lead_none');
    }

    // ── chart drawing (models from util/next-history.js) ──
    _onHover(e, n, bars) {
        const r = e.currentTarget.getBoundingClientRect();
        if (!r.width || n < 1) return;
        const f = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
        this._hover = bars ? Math.min(n - 1, Math.floor(f * n)) : Math.round(f * (n - 1));
    }
    _onKey(e, n) {
        if (e.key === 'ArrowLeft') { e.preventDefault(); this._hover = Math.max(0, (this._hover < 0 ? n : this._hover) - 1); }
        if (e.key === 'ArrowRight') { e.preventDefault(); this._hover = Math.min(n - 1, this._hover + 1); }
        if (e.key === 'Escape') this._hover = -1;
    }
    _hint(key) { return html`<p class="help">${this._t(key || 'next_no_history')}</p>`; }

    _stack(model, label) {
        if (model.empty) return this._hint();
        const n = model.slots.length;
        const hov = model.slots[this._hover];
        return html`<svg class="chart" viewBox="0 0 ${model.w} ${model.h}" role="img" aria-label="${label}" tabindex="0"
                @pointermove=${(e) => this._onHover(e, n, true)} @click=${(e) => this._onHover(e, n, true)} @pointerleave=${() => { this._hover = -1; }}
                @keydown=${(e) => this._onKey(e, n)}>
            ${svg`${model.grid.map((g) => svg`<line x1="6" x2="${model.w - 6}" y1="${g.y}" y2="${g.y}" stroke="var(--n-grid)"></line>
                <text x="${model.w - 6}" y="${g.y - 3}" font-size="10" fill="var(--n-fg3)" text-anchor="end">${g.text}</text>`)}
            ${hov ? svg`<rect x="${hov.x}" y="0" width="${hov.w}" height="${model.h - 16}" fill="var(--n-fg3)" opacity=".12" rx="3"></rect>` : nothing}
            ${model.bars.map((b) => svg`<rect x="${b.x}" y="${b.y}" width="${b.w}" height="${b.h}" rx="${b.rx}" fill="${b.color}" opacity="${b.opacity}"></rect>`)}
            ${model.labels.map((l) => svg`<text x="${l.x}" y="${l.y}" font-size="11" fill="${l.strong ? 'var(--n-fg)' : 'var(--n-fg3)'}" text-anchor="middle" font-weight="${l.strong ? '500' : '400'}">${l.text}</text>`)}
            ${model.totals.map((t) => svg`<text x="${t.x}" y="${t.y}" font-size="10" fill="var(--n-fg2)" text-anchor="middle">${t.text}</text>`)}`}
        </svg>`;
    }

    _line(model, label) {
        if (model.empty) return this._hint();
        const n = model.xs.length;
        return html`<svg class="chart" viewBox="0 0 ${model.w} ${model.h}" role="img" aria-label="${label}" tabindex="0"
                @pointermove=${(e) => this._onHover(e, n, false)} @click=${(e) => this._onHover(e, n, false)} @pointerleave=${() => { this._hover = -1; }}
                @keydown=${(e) => this._onKey(e, n)}>
            ${svg`${model.grid.map((g) => svg`<line x1="6" x2="${model.w - 6}" y1="${g.y}" y2="${g.y}" stroke="var(--n-grid)"></line>
                <text x="${model.w - 6}" y="${g.y - 3}" font-size="10" fill="var(--n-fg3)" text-anchor="end">${g.text}</text>`)}
            ${model.paths.map((p) => svg`${p.area ? svg`<path d="${p.area}" fill="${p.color}" opacity=".15"></path>` : nothing}
                <path d="${p.d}" fill="none" stroke="${p.color}" stroke-width="2" stroke-linejoin="round" stroke-dasharray="${p.dash ? '4 3' : nothing}"></path>`)}
            ${model.hover ? svg`<line x1="${model.hover.x}" x2="${model.hover.x}" y1="${model.top}" y2="${model.y0}" stroke="var(--n-accent)" stroke-width="1.5"></line>` : nothing}
            ${model.ticks.map((t) => svg`<text x="${t.x}" y="${t.y}" font-size="10" fill="var(--n-fg3)" text-anchor="${t.anchor}">${t.text}</text>`)}`}
        </svg>`;
    }

    _legend(items) {
        return items.map(([color, label, value]) => html`<span>${color ? html`<i style="background:${color}"></i>` : nothing}${label}${value !== undefined ? html` <b>${value}</b>` : nothing}</span>`);
    }
    _hoverLabel(b) {
        const i = this._hover;
        if (i < 0 || i >= b.n) return '';
        if (b.period === 'hour') return `${String(i).padStart(2, '0')}:00`;
        return b.labels[i] || String(new Date(b.starts[i]).getDate());
    }

    // ── Energy ──
    _energyTab() {
        const b = this._buckets();
        const w = this._chartW();
        const layers = HOME_FLOWS.filter(([src]) => this._series(flowId(src, 'home')));
        const model = stackModel(layers.map(([src]) => this._series(flowId(src, 'home'))), layers.map(([, c]) => c), b.labels, w, 150, b.highlightIndex, { unit: 'kWh' });
        const total = model.sums.reduce((a, v) => a + v, 0);
        const i = this._hover;
        const sum = i >= 0 && i < b.n
            ? html`<div class="sumrow"><span><b>${this._hoverLabel(b)}</b></span>${this._legend(layers.map(([src, c, k]) => [c, this._t(k), this._kwh(this._series(flowId(src, 'home'))[i] || 0)]))}</div>`
            : html`<div class="sumrow"><span><b>${this._kwh(total)}</b> ${this._t('next_used')}</span>
                ${this._legend(layers.map(([src, c, k]) => [c, this._t(k), this._kwh(this._sum(flowId(src, 'home')))]))}</div>`;
        const main = this._sec(`${this._t('next_house_by_source')} · ${this._periodLabel()}`,
            html`${layers.length ? this._stack(model, this._t('next_house_by_source')) : this._hint()}${model.empty ? nothing : sum}`, { cls: 'span2' });
        return html`${main}${this._flowsCard()}${this._solarCard()}${this._sharesCard()}`;
    }

    _flowValue(src, sink) {
        const id = flowId(src, sink);
        if (!this._has(id)) return null;
        return this._period === 'day' ? this._num(id) : this._sum(id);
    }
    _flowsCard() {
        const rows = SINKS.map(([sink, icon, key, srcs]) => {
            const parts = srcs.map((s) => [s, this._flowValue(s, sink)]).filter(([, v]) => v !== null);
            const total = parts.reduce((a, [, v]) => a + Math.max(0, v), 0);
            return parts.length ? { sink, icon, key, parts, total } : null;
        }).filter(Boolean);
        const body = rows.length ? html`<div class="rows flows">${rows.map((r) => html`<div class="row">
                <div class="fh"><span>${this._icon(r.icon)} ${this._t(r.key)}</span><b class="num">${this._kwh(r.total)}</b></div>
                <div class="fb">${r.total > 0 ? r.parts.map(([s, v]) => html`<i style="flex:${Math.max(0, v) / r.total};background:${SRC_COLOR[s]}"></i>`) : nothing}</div></div>`)}</div>
            <div class="sumrow">${this._legend(HOME_FLOWS.map(([, c, k]) => [c, this._t(k)]))}<span class="dim">${this._t('next_sankey_note')}</span></div>
            ${this._sankey()}` : this._hint('next_no_flows');
        return this._sec(`${this._t('next_where_went')} · ${this._periodLabel()}`, body);
    }
    /**
     * The HACS sankey, only when its element is on the page and the period is
     * today (its sensors are daily) — and only on request: mounted by default
     * it redraws itself at zero width while HA takes the view down, which
     * logs a hundred SVG errors on every tab change.
     */
    _sankey() {
        if (this._period !== 'day' || typeof customElements === 'undefined' || !customElements.get('sankey-chart')) return nothing;
        if (!this._showSankey) return html`<div style="margin-top:8px">${this._link(this._t('next_show_sankey'), () => { this._showSankey = true; })}</div>`;
        return html`<div style="margin-top:10px"><sankey-chart></sankey-chart></div>`;
    }
    _sankeyConfig() {
        const sec1 = [['daily_solar_energy', C.solar, this._t('next_src_solar'), ['home', 'ev', 'battery', 'grid'].map((k) => flowId('solar', k))],
                      ['daily_grid_import_energy', C.grid, this._t('next_src_grid'), ['home', 'ev', 'battery'].map((k) => flowId('grid', k))],
                      ['daily_battery_discharge_energy', C.battery_out, this._t('next_src_battery'), ['home', 'ev', 'grid'].map((k) => flowId('battery', k))]];
        const sink = { home: 'daily_home_energy', ev: 'daily_ev_energy', battery: 'daily_battery_charge_energy', grid: 'daily_grid_export_energy' };
        const sec2 = [];
        for (const [src, c] of [['solar', C.solar], ['grid', C.grid], ['battery', C.battery_out]]) {
            for (const [k, s] of Object.entries(sink)) {
                if (src === k || !this._has(flowId(src, k))) continue;
                sec2.push({ entity_id: flowId(src, k), color: c, children: [S + sink[k]] });
            }
        }
        const sec3 = Object.entries(sink).filter(([, s]) => this._has(S + s)).map(([, s]) => ({ entity_id: S + s }));
        return { type: 'custom:sankey-chart', show_names: true, show_icons: true, show_states: true, wide: true, height: 220, unit_prefix: 'k', round: 2,
            sections: [{ entities: sec1.filter(([s]) => this._has(S + s)).map(([s, color, name, children]) => ({ entity_id: S + s, color, name, children: children.filter((id) => this._has(id)) })) },
                       { entities: sec2 }, { entities: sec3 }] };
    }

    _solarCard() {
        const today = this._num(S + 'daily_solar_energy'), month = this._num(S + 'monthly_solar_yield_energy'), year = this._num(S + 'yearly_solar_yield_energy');
        const spec = this._num(S + 'pv_daily_specific_yield'), fc = this._num(S + 'forecast_today_kwh');
        const deg = this._num(S + 'pv_estimated_annual_degradation');
        const tiles = [];
        if (today !== null) {
            const sub = [spec !== null && spec > 0 ? `${this._fmt(spec, 2)} kWh/kWp` : '', fc ? this._tf('next_pct_forecast', { pct: Math.round(today / fc * 100) }) : ''].filter(Boolean).join(' · ');
            tiles.push({ label: this._t('next_today'), value: this._fmt(today, 1), unit: 'kWh', sub, color: C.solar });
        }
        if (month !== null || year !== null) {
            tiles.push({ label: this._t('next_month_year'), value: month === null ? '—' : (month >= 100 ? Math.round(month) : this._fmt(month, 1)),
                unit: year === null ? 'kWh' : `· ${Math.round(year)} kWh`,
                sub: deg !== null && deg !== 0 ? html`${this._icon(deg > 0 ? 'mdi:trending-down' : 'mdi:trending-up', 's')} ${this._tf('next_per_year', { pct: this._fmt(Math.abs(deg), 1) })}` : '' });
        }
        const rows = [];
        const strings = semDiscoverPVStrings(this._hass, S);
        if (strings.length >= 2) {
            rows.push(this._row('mdi:view-module', this._tf('next_strings', { n: strings.length }), strings.map((s) => `${s.name} ${s.energyKwh === null ? '—' : this._fmt(s.energyKwh, 1)}`).join(' · '), 'kWh',
                { onClick: () => this._moreInfo(strings[0].entityId) }));
        }
        const health = this._str(S + 'pv_health');
        if (health) {
            const a = this._attrs(S + 'pv_health');
            const cls = health === 'green' ? 'ok' : health === 'red' ? 'bad' : 'warn';
            const sub = [Number.isFinite(Number(a.ratio_7d)) && a.ratio_7d !== null ? this._tf('next_ratio_7d', { ratio: Number(a.ratio_7d).toFixed(2) }) : '',
                         Number.isFinite(Number(a.downtime_min_today)) && a.downtime_min_today !== null ? this._tf('next_dark_minutes', { min: Math.round(a.downtime_min_today) }) : '',
                         a.snow ? this._t('next_snow') : ''].filter(Boolean).join(' · ');
            rows.push(this._row('mdi:solar-panel', this._t('next_pv_health'), this._pill(this._t('next_health_' + health) || health, cls), sub, { onClick: () => this._moreInfo(S + 'pv_health') }));
        }
        const win = this._str(S + 'best_surplus_window');
        if (win) rows.push(this._row('mdi:weather-sunset', this._t('next_best_window'), win, '', { onClick: () => this._moreInfo(S + 'best_surplus_window') }));
        if (!tiles.length && !rows.length) return nothing;
        return this._sec(this._t('next_src_solar'), html`${tiles.length ? this._tiles(tiles) : nothing}${rows.length ? html`<div class="rows" style="margin-top:6px">${rows}</div>` : nothing}`);
    }

    _sharesCard() {
        const self = this._num(S + 'self_consumption_rate'), aut = this._num(S + 'autarky_rate');
        const co2d = this._num(S + 'daily_co2_avoided'), co2y = this._num(S + 'yearly_co2_avoided'), co2l = this._num(S + 'lifetime_co2_avoided');
        const trees = this._num(S + 'lifetime_trees_equivalent') ?? this._num(S + 'yearly_trees_equivalent');
        const unit = this._kgUnit('daily_co2_avoided');
        const ring = (pct, color, key, subKey) => html`<div class="tile ring">${this._ring(pct, color, 52, this._t(key))}<div><span class="lbl">${this._t(key)}</span><div class="xs dim">${this._t(subKey)}</div></div></div>`;
        const tiles = [self !== null ? ring(self, C.solar, 'next_self_use', 'next_self_use_sub') : null, aut !== null ? ring(aut, C.home, 'next_own_supply', 'next_own_supply_sub') : null].filter(Boolean);
        const rows = [];
        if (co2d !== null || co2y !== null || co2l !== null) {
            const sub = [co2y !== null ? `${Math.round(co2y)} ${unit} ${this._t('next_this_year')}` : '', co2l !== null ? `${this._fmtT(co2l, unit)} ${this._t('next_lifetime')}` : '',
                         trees !== null ? this._tf('next_trees', { n: Math.round(trees) }) : ''].filter(Boolean).join(' · ');
            rows.push(this._row('mdi:leaf', this._t('next_co2_avoided'), co2d === null ? '—' : `${this._fmt(co2d, 1)} ${unit} ${this._t('next_today').toLowerCase()}`, sub, { onClick: () => this._moreInfo(S + 'daily_co2_avoided') }));
        }
        if (!tiles.length && !rows.length) return nothing;
        const title = this._period === 'day' ? this._t('next_shares') : `${this._t('next_shares')} · ${this._t('next_today')}`;
        return this._sec(title, html`${tiles.length ? html`<div class="tiles">${tiles}</div>` : nothing}${rows.length ? html`<div class="rows" style="margin-top:6px">${rows}</div>` : nothing}`);
    }
    _fmtT(kg, unit) { return unit === 'kg' && kg >= 1000 ? `${(kg / 1000).toFixed(1)} t` : `${Math.round(kg)} ${unit}`; }

    // ── Power ──
    _powerTab() {
        const b = this._buckets(), w = this._chartW();
        const pos = (arr, sign) => arr && arr.map((v) => (v === null ? null : Math.max(0, sign * v) / 1000));
        const defs = [['solar_power', C.solar, 'next_src_solar', 1, true], ['home_consumption_power', C.home, 'next_src_house', 1, false],
                      ['grid_power', C.grid, 'next_grid_in', -1, false], ['battery_power', C.battery_out, 'next_battery_out', -1, false]];
        const series = defs.map(([k, color, key, sign, area]) => ({ key, color, area, v: pos(this._series(S + k), sign) })).filter((s) => s.v);
        const model = lineModel(series, w, 150, { labels: b.labels, unit: 'kW', hover: this._hover });
        const i = this._hover;
        const legend = i >= 0 && i < b.n
            ? [[null, this._hoverLabel(b)], ...series.map((s) => [s.color, this._t(s.key), this._fmt(s.v[i], 1) + ' kW'])]
            : [...series.map((s) => [s.color, this._t(s.key)]), [null, this._t('next_hover_hint')]];
        return this._sec(`${this._t('next_power')} · ${this._periodLabel()}`,
            html`${series.length ? this._line(model, this._t('next_power')) : this._hint()}${model.empty ? nothing : html`<div class="sumrow">${this._legend(legend)}</div>`}`, { cls: 'span2' });
    }

    // ── Battery ──
    _batteryTab() {
        if (!this._has(S + 'battery_soc') && !this._has(S + 'battery_power')) return this._sec(this._t('next_tab_battery'), this._hint('next_no_battery'), { cls: 'span2' });
        const b = this._buckets(), w = this._chartW();
        const p = this._series(S + 'battery_power');
        const soc = this._series(S + 'battery_soc');
        const kw = (sign) => p && p.map((v) => (v === null ? null : Math.max(0, sign * v) / 1000));
        const pm = lineModel(p ? [{ v: kw(1), color: C.battery_in, area: true }, { v: kw(-1), color: C.battery_out, area: true }] : [], w, 120, { labels: b.labels, unit: 'kW', hover: this._hover });
        const sm = lineModel(soc ? [{ v: soc, color: C.battery_in }] : [], w, 110, { labels: b.labels, unit: '%', max: 100, hover: this._hover });
        const inK = this._pt('batt_in'), outK = this._pt('battery');
        const floor = this._num('number.sem_battery_buffer_soc'), tonight = this._num(S + 'battery_dynamic_floor_pct');
        const i = this._hover;
        const hov = i >= 0 && i < b.n;
        const pSum = hov && p ? [[null, this._hoverLabel(b)], [C.battery_in, this._t('next_in'), this._fmt(kw(1)[i], 1) + ' kW'], [C.battery_out, this._t('next_out'), this._fmt(kw(-1)[i], 1) + ' kW']]
            : [[C.battery_in, this._t('next_in'), this._kwh(inK)], [C.battery_out, this._t('next_out'), this._kwh(outK)]];
        const sSum = hov && soc ? [[null, this._hoverLabel(b)], [C.battery_in, this._t('next_charge'), this._pct(soc[i])]]
            : [[null, this._t('next_charge')], floor !== null ? [null, this._t('next_floor'), this._pct(floor)] : null, tonight !== null ? [null, this._t('next_tonight'), this._pct(tonight)] : null].filter(Boolean);
        return this._sec(`${this._t('next_tab_battery')} · ${this._periodLabel()}`, html`
            ${p ? this._line(pm, this._t('next_power')) : this._hint()}${pm.empty ? nothing : html`<div class="sumrow">${this._legend(pSum)}</div>`}
            ${soc ? html`${this._line(sm, this._t('next_charge'))}${sm.empty ? nothing : html`<div class="sumrow">${this._legend(sSum)}</div>`}` : nothing}`, { cls: 'span2' });
    }

    // ── Car ──
    _carTab() {
        if (!this._chargers.length) return this._sec(this._t('next_tab_car'), this._hint('next_no_charger'), { cls: 'span2' });
        const b = this._buckets(), w = this._chartW();
        const layers = this._chargers.map((cid, i) => ({ cid, color: CHARGER_COLORS[i % CHARGER_COLORS.length], v: this._series(`${S}charger_${cid}_daily_energy`) })).filter((l) => l.v);
        const model = stackModel(layers.map((l) => l.v), layers.map((l) => l.color), b.labels, w, 150, b.highlightIndex, { unit: 'kWh' });
        const rows = this._sessionsIn(b);
        const tot = monthTotals(rows);
        const kwh = this._pt('car') ?? model.sums.reduce((a, v) => a + v, 0);
        const perKwh = tot.cost !== null && tot.kwh > 0 ? tot.cost / tot.kwh : null;
        const per100 = this._num(`number.sem_charger_${this._chargers[0]}_ev_kwh_per_100km`);
        const i = this._hover;
        const sum = i >= 0 && i < b.n
            ? [[null, this._hoverLabel(b)], ...layers.map((l) => [l.color, this._chargerName(l.cid), this._kwh(l.v[i] || 0)])]
            : [[null, this._kwh(kwh), this._periodLabel().toLowerCase()], tot.count ? [null, this._t('next_src_sun'), this._pct(tot.solarPct)] : null,
               tot.cost !== null ? [null, this._t('next_cost'), this._money(tot.cost)] : null,
               perKwh !== null ? [null, `${this._fmt(perKwh, 2)} ${this._currency()}/kWh`, per100 ? `· ${this._fmt(perKwh * per100, 2)} ${this._currency()}/100 km` : ''] : null,
               layers.length > 1 ? [null, ''] : null, ...(layers.length > 1 ? layers.map((l) => [l.color, this._chargerName(l.cid)]) : [])].filter(Boolean);
        const main = this._sec(`${this._t('next_src_car')} · ${this._periodLabel()}`,
            html`${layers.length ? this._stack(model, this._t('next_src_car')) : this._hint()}${model.empty ? nothing : html`<div class="sumrow">${this._legend(sum)}</div>`}`, { cls: 'span2' });
        return html`${main}${this._sessionsCard()}${this._progressCard()}`;
    }

    _sessionsIn(b) {
        const from = ymd(b.start), to = ymd(new Date(b.spanEnd.getTime() - 1));
        const out = [];
        for (const cid of this._chargers) for (const r of this._sess[cid]?.rows || []) {
            const d = String(r.timestamp || '').slice(0, 10);
            if (d >= from && d <= to) out.push(r);
        }
        return out;
    }
    async _loadSessions(cid) {
        if (!this._hass?.callWS) return;
        const now = new Date();
        this._sess = { ...this._sess, [cid]: { rows: [], loading: true, month: this._sess[cid]?.month || `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}` } };
        let rows = [];
        try {
            const res = await this._hass.callWS({ type: 'solar_energy_management/session_history', charger_id: cid });
            rows = Array.isArray(res?.rows) ? res.rows : [];
        } catch (_e) { rows = []; }
        this._sess = { ...this._sess, [cid]: { ...this._sess[cid], rows, loading: false } };
    }
    async _downloadXlsx(cid) {
        if (!this._hass?.callWS) return;
        try {
            const res = await this._hass.callWS({ type: 'solar_energy_management/session_history/xlsx', charger_id: cid });
            if (res?.base64) downloadBase64(res.filename || 'sem-sessions.xlsx', res.base64, XLSX_MIME);
            this._sess = { ...this._sess, [cid]: { ...this._sess[cid], error: false } };
        } catch (_e) {
            this._sess = { ...this._sess, [cid]: { ...this._sess[cid], error: true } };
        }
    }
    _sessionsCard() {
        const cid = this._sessCid;
        const st = this._sess[cid] || { rows: [], loading: true };
        const now = new Date();
        const month = st.month || `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
        const rows = rowsForMonth(st.rows, month);
        const tot = monthTotals(rows);
        const months = new Set((st.rows || []).map(sessionMonth).filter(Boolean));
        const label = (() => { try { return new Date(`${month}-15T12:00:00`).toLocaleDateString(this._hass?.language || 'en', { month: 'long', year: 'numeric' }); } catch (_e) { return month; } })();
        const setMonth = (d) => { this._sess = { ...this._sess, [cid]: { ...st, month: shiftMonth(month, d) } }; };
        const extra = this._chargers.length > 1 ? this._seg(this._chargers.map((c) => ({ key: c, label: this._chargerName(c) })), cid, (k) => { this._sessCid = k; }, { small: true }) : nothing;
        const body = st.loading ? this._hint('next_loading')
            : html`${rows.length ? html`<div class="rows">${rows.slice(0, 12).map((r) => { const v = sessionRowView(r, this._hass?.language);
                    return this._row('mdi:ev-station', `${v.day} ${v.span}`, `${v.kwh} kWh`, [v.solar ? `${v.solar} ${this._t('next_src_sun')}` : '', v.cost ? `${v.cost} ${r.currency || this._currency()}` : '', v.min ? `${v.min} min` : ''].filter(Boolean).join(' · ')); })}</div>
                <div class="sumrow"><span><b>${tot.count}</b> ${this._t('next_sessions')}</span><span><b>${this._kwh(tot.kwh)}</b></span><span>${this._t('next_src_sun')} <b>${this._pct(tot.solarPct)}</b></span>${tot.cost !== null ? html`<span>${this._t('next_cost')} <b>${this._money(tot.cost)}</b></span>` : nothing}</div>`
                : this._hint('next_no_sessions')}
            <div class="btns" style="margin-top:8px">
                ${this._btn(this._t('next_prev_month'), () => setMonth(-1), { small: true, icon: 'mdi:chevron-left', disabled: !months.has(shiftMonth(month, -1)) })}
                ${this._btn(this._t('next_next_month'), () => setMonth(1), { small: true, icon: 'mdi:chevron-right', disabled: !months.has(shiftMonth(month, 1)) })}
                ${this._btn(this._t('next_download_xlsx'), () => this._downloadXlsx(cid), { small: true, icon: 'mdi:download', disabled: !(st.rows || []).length })}
                ${st.error ? html`<span class="pill bad">${this._t('next_download_failed')}</span>` : nothing}</div>`;
        return this._sec(`${this._t('next_sessions')} · ${label}`, body, { extra });
    }
    _progressCard() {
        const today = this._num(S + 'daily_ev_energy');
        const target = this._chargers.map((c) => this._num(`number.sem_charger_${c}_daily_ev_target`)).filter((v) => v !== null).reduce((a, v) => a + v, 0) || null;
        const life = ['lifetime_ev_energy', 'lifetime_ev_cost', 'lifetime_ev_solar_share', 'lifetime_ev_sessions'].map((k) => this._num(S + k));
        if (today === null && life.every((v) => v === null)) return nothing;
        const lifeText = [life[0] !== null ? this._kwh(life[0]) : '', life[1] !== null ? this._money(life[1]) : '', life[2] !== null ? `${this._pct(life[2])} ${this._t('next_src_sun')}` : '',
                          life[3] !== null ? `${Math.round(life[3])} ${this._t('next_sessions')}` : ''].filter(Boolean).join(' · ');
        return this._sec(this._t('next_progress'), html`
            ${today !== null && target ? this._track(today / target * 100, C.ev) : nothing}
            <div class="sumrow">${today !== null ? html`<span>${this._t('next_today').toLowerCase()} <b>${this._fmt(today, 1)}</b>${target ? ` ${this._tf('next_of_target', { kwh: this._fmt(target, 1) })}` : ' kWh'}</span>` : nothing}
                ${lifeText ? html`<span>${this._t('next_lifetime')} <b>${lifeText}</b></span>` : nothing}</div>`);
    }

    // ── Money ──
    _moneyTab() {
        const b = this._buckets(), w = this._chartW(), cur = this._currency();
        const defs = [['cost', C.grid, 'next_bought'], ['saved', C.good, 'next_saved'], ['batt_saved', C.battery_out, 'next_batt_saved']];
        const layers = defs.map(([k, color, key]) => ({ key, color, v: this._series(S + PERIODS.day[k]) })).filter((l) => l.v);
        const model = stackModel(layers.map((l) => l.v), layers.map((l) => l.color), b.labels, w, 150, b.highlightIndex, { unit: cur });
        const bought = this._pt('cost'), saved = this._pt('saved'), bs = this._pt('batt_saved'), earned = this._pt('export_rev');
        const i = this._hover;
        const sum = i >= 0 && i < b.n ? [[null, this._hoverLabel(b)], ...layers.map((l) => [l.color, this._t(l.key), this._money(l.v[i] || 0)])]
            : [bought !== null ? [C.grid, this._t('next_bought'), this._money(bought)] : null,
               saved !== null ? [C.good, this._t('next_saved'), this._money(saved + (bs || 0))] : null,
               earned !== null ? [C.export, this._t('next_earned'), this._money(earned)] : null,
               bought !== null && earned !== null ? [null, this._t('next_net'), this._money(bought - earned)] : null].filter(Boolean);
        const main = this._sec(`${this._t('next_cost_savings')} · ${this._periodLabel()}`,
            html`${layers.length ? this._stack(model, this._t('next_cost_savings')) : this._hint()}${model.empty ? nothing : html`<div class="sumrow">${this._legend(sum)}</div>`}`, { cls: 'span2' });
        return html`${main}${this._moneyCard()}`;
    }
    _moneyCard() {
        const cur = this._currency();
        const ys = this._num(S + 'yearly_savings'), yb = this._num(S + 'yearly_battery_savings');
        const pay = this._num(S + 'roi_payback_years'), roi = this._num(S + 'roi_percentage'), inv = this._num('number.sem_system_investment_cost');
        const tiles = [];
        if (ys !== null) tiles.push({ label: this._t('next_saved_year'), value: Math.round(ys + (yb || 0)), unit: cur, valueColor: C.good,
            sub: `${this._t('next_src_sun')} ${Math.round(ys)}${yb !== null ? ` · ${this._t('next_src_battery').toLowerCase()} ${Math.round(yb)}` : ''}` });
        if (pay !== null || inv !== null) tiles.push({ label: this._t('next_payback'), value: pay !== null && pay > 0 ? this._fmt(pay, 1) : '—', unit: this._t('next_years'),
            sub: html`${roi !== null ? `${this._t('next_roi')} ${this._fmt(roi, 1)} % · ` : ''}${this._t('next_invested')} ${this._has('number.sem_system_investment_cost')
                ? this._val(inv === null ? '—' : Math.round(inv), () => this._moreInfo('number.sem_system_investment_cost')) : '—'}` });
        const rows = [];
        const evE = this._num(S + 'lifetime_ev_energy'), evC = this._num(S + 'lifetime_ev_cost');
        if (evE !== null && evE > 0 && evC !== null) {
            const per100 = this._num(`number.sem_charger_${this._chargers[0] || ''}_ev_kwh_per_100km`);
            const shares = [['lifetime_ev_solar_share', 'next_src_sun'], ['lifetime_ev_battery_share', 'next_src_battery'], ['lifetime_ev_grid_share', 'next_src_grid']]
                .map(([k, key]) => { const v = this._num(S + k); return v === null ? '' : `${this._t(key).toLowerCase()} ${this._pct(v)}`; }).filter(Boolean);
            rows.push(this._row('mdi:ev-station', this._t('next_src_car'), `${this._fmt(evC / evE, 2)} ${cur}/kWh`,
                [per100 ? `${this._fmt(evC / evE * per100, 2)} ${cur}/100 km` : '', ...shares].filter(Boolean).join(' · '), { onClick: () => this._moreInfo(S + 'lifetime_ev_cost') }));
        }
        const peak = this._num(S + 'monthly_consecutive_peak');
        if (peak !== null) {
            const charge = this._num(S + 'power_charge_cost');
            rows.push(this._row('mdi:speedometer', this._t('next_demand_charge'), `${this._fmt(peak, 1)} kW ${this._t('next_peak').toLowerCase()}`,
                html`${charge !== null ? `${this._money(charge)} ${this._t('next_this_month').toLowerCase()}` : ''}${this._has('number.sem_demand_charge_rate')
                    ? html` · ${this._t('next_rate')} ${this._val(`${this._fmt(this._num('number.sem_demand_charge_rate'), 2)} ${cur}/kW`, () => this._moreInfo('number.sem_demand_charge_rate'))}` : ''}`));
        }
        const prov = this._str(S + 'tariff_provider'), level = this._str(S + 'tariff_price_level');
        const imp = this._num(S + 'tariff_current_import_rate'), exp = this._num(S + 'tariff_current_export_rate');
        if (imp !== null || prov) {
            const kind = !level || level === 'flat' ? this._t('next_level_flat') : this._t('next_dynamic');
            rows.push(this._row('mdi:tag-multiple', this._t('next_tariff'), [kind, prov].filter(Boolean).join(' · '),
                [imp !== null ? `${this._t('next_import')} ${this._fmt(imp, 2)}` : '', exp !== null ? `${this._t('next_export').toLowerCase()} ${this._fmt(exp, 2)}` : ''].filter(Boolean).join(' · '),
                { onClick: () => this._moreInfo(S + 'tariff_current_import_rate') }));
        }
        // (#1321) what SEM paid per kWh against the market's average, dynamic tariffs only
        const avgId = S + 'average_purchase_price';
        if (level && level !== 'flat' && this._has(avgId)) {
            const avg = this._num(avgId), market = Number(this._attrs(avgId).market_average);
            if (avg !== null) {
                rows.push(this._row('mdi:scale-balance', this._t('next_avg_purchase'), `${this._fmt(avg, 3)} ${cur}/kWh`,
                    Number.isFinite(market) ? this._tf('next_avg_vs_market', { price: `${this._fmt(market, 3)} ${cur}/kWh` }) : '',
                    { onClick: () => this._moreInfo(avgId) }));
            }
        }
        const life = this._num(S + 'lifetime_total_savings');
        if (life !== null) {
            const co2 = this._num(S + 'lifetime_co2_avoided'), trees = this._num(S + 'lifetime_trees_equivalent');
            rows.push(this._row('mdi:forest', this._t('next_lifetime'), `${Math.round(life)} ${cur} ${this._t('next_saved').toLowerCase()}`,
                [co2 !== null ? `${this._fmtT(co2, this._kgUnit('lifetime_co2_avoided'))} CO₂` : '', trees !== null ? this._tf('next_trees', { n: Math.round(trees) }) : ''].filter(Boolean).join(' · '), { more: true }));
        }
        if (!tiles.length && !rows.length) return nothing;
        return this._sec(this._t('next_money'), html`${tiles.length ? this._tiles(tiles) : nothing}${rows.length ? html`<div class="rows" style="margin-top:6px">${rows}</div>` : nothing}`);
    }

    // ── Forecast ──
    _forecastTab() {
        const b = this._buckets(), w = this._chartW();
        const hourly = this._hourly();
        let actual = this._series(S + (hourly ? 'solar_power' : 'daily_solar_energy'));
        let expected = this._series(S + (hourly ? 'forecast_power_now_w' : 'forecast_today_kwh'));
        const fc = this._num(S + 'forecast_today_kwh');
        if (hourly) {
            actual = actual && actual.map((v) => (v === null ? null : v / 1000));
            if (expected) expected = expected.map((v) => (v === null ? null : v / 1000));
            else if (this._period === 'day' && fc) expected = sunCurve(fc, this._str(S + 'night_end_time'), this._str(S + 'night_start_time'));
        }
        const series = [actual ? { v: actual, color: C.solar, area: true } : null, expected ? { v: expected, color: C.solar, dash: true } : null].filter(Boolean);
        const model = lineModel(series, w, 150, { labels: b.labels, unit: hourly ? 'kW' : 'kWh', hover: this._hover });
        const today = this._num(S + 'daily_solar_energy'), tom = this._num(S + 'forecast_tomorrow_kwh');
        const src = providerName(this._str(S + 'forecast_source'));
        const t1 = this._num(S + 'forecast_trust_d1'), t2 = this._num(S + 'forecast_trust_d2');
        const i = this._hover;
        const unit = hourly ? ' kW' : ' kWh';
        const sum = i >= 0 && i < b.n ? [[null, this._hoverLabel(b)], actual ? [C.solar, this._t('next_actual'), this._fmt(actual[i], 1) + unit] : null, expected ? [null, this._t('next_expected'), this._fmt(expected[i], 1) + unit] : null].filter(Boolean)
            : [[null, this._t('next_solid_dotted')], today !== null && fc ? [null, this._t('next_today').toLowerCase(), `${this._fmt(today, 1)} ${this._t('next_of')} ${this._fmt(fc, 1)} kWh · ${Math.round(today / fc * 100)} %`] : null,
               tom !== null ? [null, this._t('next_tomorrow').toLowerCase(), this._kwh(tom)] : null,
               src || t1 !== null ? [null, [src || '', t1 !== null ? `${this._t('next_trusted')} ${this._pct(t1 * 100)}${t2 !== null ? ` / ${this._pct(t2 * 100)}` : ''}` : ''].filter(Boolean).join(' · ')] : null].filter(Boolean);
        const main = this._sec(`${this._t('next_src_solar')} · ${this._t('next_forecast_actual')}`,
            html`${series.length ? this._line(model, this._t('next_forecast_actual')) : this._hint()}${model.empty ? nothing : html`<div class="sumrow">${this._legend(sum)}</div>`}`, { cls: 'span2' });
        return html`${main}${this._accuracyCard()}`;
    }
    _accuracyCard() {
        const rows = [];
        const vs = this._num(S + 'pv_performance_vs_forecast');
        if (vs !== null) rows.push(this._row('mdi:calendar-today', this._t('next_today_so_far'), `${vs > 0 ? '+' : ''}${this._fmt(vs, 0)} %`, this._t('next_vs_forecast'), { onClick: () => this._moreInfo(S + 'pv_performance_vs_forecast') }));
        const ratio = this._attrs(S + 'pv_health').ratio_7d;
        if (Number.isFinite(Number(ratio)) && ratio !== null) {
            const d = (Number(ratio) - 1) * 100;
            rows.push(this._row('mdi:calendar-range', this._t('next_last_7_days'), `${d > 0 ? '+' : ''}${this._fmt(d, 0)} %`, this._t('next_vs_forecast'), { onClick: () => this._moreInfo(S + 'pv_health') }));
        }
        const spend = this._attrs(S + 'battery_spendable_kwh');
        const src = this._str(S + 'forecast_source');
        for (const n of [1, 2]) {
            const id = `${S}forecast_trust_d${n}`;
            if (!this._has(id)) continue;
            const trust = this._num(id);
            const effect = trustConsequence({ available: spend[`forecast_d${n}_available`], trust, days: spend[`forecast_days_d${n}`], minDays: spend.forecast_min_days, t: (k) => this._t(k) });
            rows.push(this._row('mdi:weather-partly-cloudy', `${this._t(n === 1 ? 'next_tomorrow' : 'next_two_days')}${src ? ` · ${providerName(src) || src}` : ''}`,
                trust === null ? this._t('next_learning') : `${this._t('next_trusted')} ${this._pct(trust * 100)}`, effect, { onClick: () => this._moreInfo(id) }));
        }
        if (!rows.length) return nothing;
        return this._sec(this._t('next_accuracy'), html`<div class="rows">${rows}</div>`);
    }

    // ── Replay ──
    _replayTab() {
        return this._sec(this._t('next_replay'), html`<p class="help" style="margin:0 0 8px">${this._t('next_replay_hint')}</p>
            <sem-simulation-card .hass=${this._hass}></sem-simulation-card>`, { cls: 'span2' });
    }

    updated() {
        super.updated();
        const sim = this.renderRoot?.querySelector('sem-simulation-card');
        if (sim && !sim._semNextConfigured) {
            sim._semNextConfigured = true;
            try { sim.setConfig({}); } catch (_e) { /* the card may already be configured */ }
            sim.hass = this._hass;
        }
        const sk = this.renderRoot?.querySelector('sankey-chart');
        if (sk) {
            if (!sk._semNextConfigured) {
                sk._semNextConfigured = true;
                try { sk.setConfig(this._sankeyConfig()); } catch (_e) { /* the HACS card refused the config; the bars stay */ }
            }
            sk.hass = this._hass;
        }
    }

    _pick(period) { this._period = period; this._hover = -1; this._load(); }
    _pickTab(tab) {
        this._tab = tab; this._hover = -1;
        try { window.history.replaceState(null, '', '#' + tab); } catch (_e) { /* no history */ }
        this._load();
    }

    render() {
        if (!this._hass) return nothing;
        const simOn = !this._has('switch.sem_simulation_tab') || this._str('switch.sem_simulation_tab') === 'on';
        const tabs = TABS.filter(([k]) => k !== 'replay' || simOn).map(([key, label]) => ({ key, label: this._t(label) }));
        const body = { energy: () => this._energyTab(), power: () => this._powerTab(), battery: () => this._batteryTab(), car: () => this._carTab(),
                       money: () => this._moneyTab(), forecast: () => this._forecastTab(), replay: () => this._replayTab() }[this._tab] || (() => this._energyTab());
        const lead = this._tab === 'replay' ? { main: this._t('next_replay'), sub: this._t('next_replay_hint') } : { main: this._lead(), sub: this._t('next_ins_sub') };
        return this._frame(lead, html`
            <div class="period">
                ${this._seg(PERIOD_KEYS.map(([key, label]) => ({ key, label: this._t(label) })), this._period, (k) => this._pick(k), { small: true, disabled: this._tab === 'replay' })}
                ${this._seg(tabs, this._tab, (k) => this._pickTab(k), { small: true })}
            </div>
            <div class="grid">${body()}</div>`);
    }
}

semDefineCard('sem-next-insights-card', SEMNextInsightsCard, {
    type: 'sem-next-insights-card',
    name: 'SEM · Insights',
    description: 'One period for every chart: energy by source, power, battery, car, money, forecast, and a replay tab',
    documentationURL:
        'https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-next-insights-card',
    preview: true,
});

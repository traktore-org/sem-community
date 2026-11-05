/**
 * SEM Next · Insights (#1321)
 *
 * One period selector for everything: where the energy came from, what
 * it cost and saved, and a replay tab that holds the simulation card.
 *
 * Config:
 *   type: custom:sem-next-insights-card
 */

import { SEMNextBase, html, nothing, nextCss, NEXT_COLORS as C } from '../base/sem-next-base.js';
import { semDefineCard } from '../base/sem-shared.js';
import './sem-simulation-card.js';

const PERIODS = {
    day: {
        solar: 'daily_solar_energy', grid_in: 'daily_grid_import_energy', grid_out: 'daily_grid_export_energy',
        battery: 'daily_battery_discharge_energy', car: 'daily_ev_energy', house: 'daily_home_energy',
        cost: 'daily_costs', saved: 'daily_savings', batt_saved: 'daily_battery_savings', export_rev: 'daily_export_revenue',
        co2: 'daily_co2_avoided', forecast: 'forecast_today_kwh',
    },
    month: {
        solar: 'monthly_solar_yield_energy', grid_in: 'monthly_grid_import_energy', grid_out: 'monthly_grid_export_energy',
        battery: 'monthly_battery_discharge_energy', car: 'monthly_ev_consumption_energy', house: 'monthly_home_consumption_energy',
        cost: 'monthly_costs', saved: 'monthly_savings', batt_saved: 'monthly_battery_savings', export_rev: 'monthly_export_revenue',
    },
    year: {
        solar: 'yearly_solar_yield_energy', grid_in: 'yearly_grid_import_energy', grid_out: 'yearly_grid_export_energy',
        battery: 'yearly_battery_discharge_energy', car: 'yearly_ev_energy', house: 'yearly_home_consumption_energy',
        cost: 'yearly_costs', saved: 'yearly_savings', batt_saved: 'yearly_battery_savings', export_rev: 'yearly_export_revenue',
        co2: 'yearly_co2_avoided', lifetime: 'lifetime_total_savings',
    },
};
const BARS = [['solar', 'next_src_solar', C.solar], ['grid_in', 'next_grid_in', C.grid], ['battery', 'next_src_battery', C.battery_out],
              ['car', 'next_src_car', C.ev], ['grid_out', 'next_export', C.export]];

class SEMNextInsightsCard extends SEMNextBase {
    static get properties() { return { _period: { state: true }, _tab: { state: true } }; }
    static get styles() { return nextCss; }

    constructor() {
        super();
        this._period = 'day';
        this._tab = 'energy';
    }

    _watchIds() {
        const ids = [];
        for (const p of Object.values(PERIODS)) for (const k of Object.values(p)) ids.push(`sensor.sem_${k}`);
        return [...super._watchIds(), ...ids];
    }

    _v(name) {
        const key = PERIODS[this._period][name];
        return key ? this._num(`sensor.sem_${key}`) : null;
    }

    _lead() {
        const house = this._v('house'), solar = this._v('solar'), cost = this._v('cost'), saved = this._v('saved');
        const cur = this._currency();
        if (this._tab === 'money' && cost !== null) {
            return this._tf('next_ins_lead_money', { period: this._t('next_period_' + this._period), cost: this._fmt(cost, 2), saved: this._fmt(saved ?? 0, 2), cur });
        }
        if (house !== null && solar !== null) {
            const fc = this._v('forecast');
            const sub = (this._period === 'day' && fc) ? ' ' + this._tf('next_pct_forecast', { pct: Math.round(solar / fc * 100) }) : '';
            return this._tf('next_ins_lead_energy', { period: this._t('next_period_' + this._period), house: this._fmt(house, 1), solar: this._fmt(solar, 1) }) + sub;
        }
        return this._t('next_ins_lead_none');
    }

    _energy() {
        const rows = BARS.map(([k, label, color]) => ({ v: this._v(k), label: this._t(label), color })).filter((r) => r.v !== null);
        if (!rows.length) return nothing;
        const max = Math.max(1, ...rows.map((r) => r.v));
        return html`<div class="sec wide"><h3>${this._t('next_where_from')}</h3><div class="list" style="gap:6px">
            ${rows.map((r) => html`<div style="display:grid;grid-template-columns:90px 1fr 72px;align-items:center;gap:8px;font-size:0.85rem">
                <span class="src"><i style="background:${r.color}"></i>${r.label}</span>
                <div class="bar" style="height:12px;border-radius:6px"><i style="width:${Math.max(2, r.v / max * 100)}%;background:${r.color}"></i></div>
                <em class="num" style="font-style:normal;text-align:right;font-weight:600">${r.v >= 100 ? Math.round(r.v) : this._fmt(r.v, 1)} kWh</em></div>`)}
        </div></div>`;
    }

    _money() {
        const cur = this._currency();
        const rows = [['cost', 'next_cost'], ['saved', 'next_saved'], ['batt_saved', 'next_batt_saved'], ['export_rev', 'next_export_revenue'], ['lifetime', 'next_lifetime_saved']]
            .map(([k, label]) => ({ v: this._v(k), label: this._t(label), money: true }))
            .concat([{ v: this._v('co2'), label: this._t('next_co2_avoided'), money: false }])
            .filter((r) => r.v !== null);
        if (!rows.length) return nothing;
        return html`<div class="sec"><h3>${this._t('next_money')}</h3><dl class="kv">
            ${rows.map((r) => html`<dt>${r.label}</dt><dd class="num">${this._fmt(r.v, r.money ? 2 : 1)} ${r.money ? cur : this._kgUnit('daily_co2_avoided')}</dd>`)}
        </dl></div>`;
    }

    _replay() {
        return html`<div class="sec wide"><h3>${this._t('next_replay')}</h3>
            <div class="hint">${this._t('next_replay_hint')}</div>
            <sem-simulation-card .hass=${this._hass}></sem-simulation-card>
        </div>`;
    }

    updated() {
        super.updated();
        const sim = this.renderRoot?.querySelector('sem-simulation-card');
        if (sim && !sim._semNextConfigured) {
            sim._semNextConfigured = true;
            try { sim.setConfig({}); } catch (e) { /* the card may already be configured */ }
            sim.hass = this._hass;
        }
    }

    render() {
        if (!this._hass) return nothing;
        const seg = (items, cur, set) => html`<div class="sub">${items.map(([k, label]) => html`<button aria-pressed="${cur === k}" @click=${() => set(k)}>${this._t(label)}</button>`)}</div>`;
        return html`<ha-card><div class="wrap">
            ${this._renderHead()}
            <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap">
                ${seg([['day', 'next_period_day'], ['month', 'next_period_month'], ['year', 'next_period_year']], this._period, (k) => { this._period = k; })}
                ${seg([['energy', 'next_tab_energy'], ['money', 'next_tab_money'], ['replay', 'next_replay']], this._tab, (k) => { this._tab = k; })}
            </div>
            ${this._tab === 'replay' ? nothing : this._renderLead(this._lead(), '')}
            <div class="grid2">
                ${this._tab === 'energy' ? this._energy() : nothing}
                ${this._tab !== 'replay' ? this._money() : nothing}
                ${this._tab === 'replay' ? this._replay() : nothing}
            </div>
        </div></ha-card>`;
    }
}

semDefineCard('sem-next-insights-card', SEMNextInsightsCard, {
    type: 'sem-next-insights-card',
    name: 'SEM Next · Insights',
    description: 'One period selector: where the energy came from, what it cost and saved, and a replay tab',
    documentationURL:
        'https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-next-insights-card',
    preview: true,
});

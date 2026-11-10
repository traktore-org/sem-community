/**
 * (#1321) The Now screen says what is true: tonight's floor only while SEM
 * spends the battery, savings from sun AND battery, the peak on one basis,
 * no kW twice, no passed surplus window, the reserve by its name.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { register } from 'node:module';

const FAKE_LIT = `
export class LitElement {
    constructor() { this.style = {}; this.classList = { toggle() {} }; this.renderRoot = { querySelector: () => null, querySelectorAll: () => [], getElementById: () => null, appendChild() {} }; }
    connectedCallback() {}
    disconnectedCallback() {}
    requestUpdate() { this.__updates = (this.__updates || 0) + 1; }
    updated() {}
    getRootNode() { return {}; }
    get updateComplete() { return Promise.resolve(true); }
}
export const html = (strings, ...values) => ({ tpl: true, strings: [...strings], values });
export const css = () => '', svg = html;
export const nothing = Symbol('nothing');
export const repeat = (items, key, fn) => Array.from(items).map((it, i) => fn(it, i));
`;
const LOADER = `
const FAKE = ${JSON.stringify('data:text/javascript,' + encodeURIComponent(FAKE_LIT))};
export async function resolve(specifier, context, next) {
    if (specifier === 'lit' || specifier.startsWith('lit/')) return { url: FAKE, shortCircuit: true };
    return next(specifier, context);
}`;
register('data:text/javascript,' + encodeURIComponent(LOADER));
globalThis.window ??= globalThis;
globalThis.document = { addEventListener() {}, removeEventListener() {}, documentElement: {}, head: { appendChild() {} }, createElement: () => ({}) };
globalThis.addEventListener = () => {};
globalThis.removeEventListener = () => {};
globalThis.requestAnimationFrame = () => 0;
const registry = new Map();
globalThis.customElements = { get: (t) => registry.get(t), define: (t, c) => registry.set(t, c) };
globalThis.getComputedStyle = () => ({ getPropertyValue: () => '' });
globalThis.localStorage = { getItem: () => null, setItem() {} };
globalThis.navigator ??= {};
globalThis.semLocalize = (key) => key;
await import('../src/cards/sem-next-now-card.js');

function text(part) {
    if (part == null || typeof part === 'symbol' || part === false) return '';
    if (Array.isArray(part)) return part.map(text).join('');
    if (part && part.strings && part.values) {
        let out = '';
        part.strings.forEach((s, i) => { out += s; if (i < part.values.length) out += text(part.values[i]); });
        return out;
    }
    if (typeof part === 'function') return '';
    return String(part);
}
const S = (state, attributes = {}) => ({ state: String(state), attributes, last_updated: '2026-11-08T18:40:00+00:00' });

function states(phase = 'holding') {
    return {
        'switch.sem_observer_mode': S('off'),
        'sensor.sem_solar_power': S(0, { unit_of_measurement: 'W' }),
        'sensor.sem_grid_power': S(-1500, { unit_of_measurement: 'W' }),
        'sensor.sem_battery_power': S(-900, { unit_of_measurement: 'W' }),
        'sensor.sem_home_consumption_power': S(2400, { unit_of_measurement: 'W' }),
        'sensor.sem_battery_soc': S(54),
        'sensor.sem_battery_spendable_kwh': S(0, { phase }),
        'sensor.sem_battery_dynamic_floor_pct': S(91.6),
        'number.sem_battery_priority_soc': S(30),
        'switch.sem_battery_may_assist_ev': S('on'),
        'sensor.sem_consecutive_peak_15min': S(1.5, { unit_of_measurement: 'kW' }),
        'sensor.sem_target_peak_limit': S(6.0, { unit_of_measurement: 'kW' }),
        'sensor.sem_current_vs_peak_percentage': S(0),
        'sensor.sem_peak_margin': S(6.0),
        'sensor.sem_daily_costs': S(5.96), 'sensor.sem_daily_savings': S(1.59), 'sensor.sem_daily_battery_savings': S(2.88),
        'sensor.sem_monthly_costs': S(59.27), 'sensor.sem_monthly_savings': S(14.29), 'sensor.sem_monthly_battery_savings': S(8.43),
        'sensor.sem_best_surplus_window': S('13:00–15:00'),
        'sensor.sem_forecast_remaining_today_kwh': S(0),
        'sensor.sem_charging_state': S('idle', {}),
    };
}

function makeCard(st) {
    const el = new (customElements.get('sem-next-now-card'))();
    el.setConfig({ type: 'custom:sem-next-now-card' });
    el.hass = { states: st, language: 'en', config: { currency: 'CHF', time_zone: 'Europe/Zurich' }, callService: async () => {}, callWS: async () => ({}) };
    return el;
}

test('a holding battery names no floor and says it keeps its charge for the house', () => {
    const el = makeCard(states('holding'));
    const lead = el._lead();
    assert.doesNotMatch(lead.sub, /next_why_batt_floor_short/);
    assert.match(lead.sub, /next_batt_holds_house/);
    const why = text(el._why());
    assert.match(why, /next_batt_holds_house/);
    assert.doesNotMatch(why, /next_why_batt_floor\b|next_why_batt_assist/);
});

test('a spending battery names tonight\'s floor', () => {
    const el = makeCard(states('spending'));
    assert.match(el._lead().sub, /next_why_batt_floor_short/);
    assert.match(text(el._why()), /next_why_batt_floor/);
});

test('saved adds the battery to the sun, today and this month', () => {
    const out = text(makeCard(states())._moneySec());
    assert.match(out, /4\.47/);
    assert.doesNotMatch(out, />1\.59</);
});

test('the grid row puts kW in the value only, not twice', () => {
    const out = text(makeCard(states())._why());
    assert.match(out, /next_grid_import/);
    assert.doesNotMatch(out, /next_why_import/);
});

test('the peak row: % and margin from the 15-minute value', () => {
    const el = makeCard(states());
    let pct = null;
    const orig = el._tf.bind(el);
    el._tf = (k, p) => { if (k === 'next_pct_margin') pct = p; return orig(k, p); };
    el._signals();
    assert.equal(pct.pct, 25);
    assert.equal(pct.kw, '4.5');
});

test('a surplus window with no sun left today is not shown', () => {
    const out = text(makeCard(states())._signals());
    assert.doesNotMatch(out, /next_best_surplus/);
    const st = states();
    st['sensor.sem_forecast_remaining_today_kwh'] = S(3.2);
    assert.match(text(makeCard(st)._signals()), /next_best_surplus/);
});

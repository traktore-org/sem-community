/**
 * (#1321) The Plan screen says only what is true: no planner log text, an
 * honest battery floor, no buttons for a full car, no cheap/expensive legend
 * on a flat tariff, an unknown cost left unknown, the sun forecast named.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
// ── the card renders with a charger, a battery and two loads (no DOM, fake lit) ──
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
globalThis.window = globalThis;
globalThis.document = { addEventListener() {}, removeEventListener() {}, documentElement: {}, head: { appendChild() {} }, createElement: () => ({}) };
globalThis.addEventListener = () => {};
globalThis.removeEventListener = () => {};
globalThis.requestAnimationFrame = () => 0;
const registry = new Map();
globalThis.customElements = { get: (t) => registry.get(t), define: (t, c) => registry.set(t, c) };
globalThis.getComputedStyle = () => ({ getPropertyValue: () => '' });
globalThis.localStorage = { getItem: () => null, setItem() {} };
globalThis.navigator ??= {};
globalThis.semLocalize = (key) => '«' + key + '»';
const { knownNum } = await import('../src/cards/sem-next-plan-card.js');

function text(part) {
    if (part == null || typeof part === 'symbol' || part === false) return '';
    if (Array.isArray(part)) return part.map(text).join('');
    if (part && part.tpl) {
        let out = '';
        part.strings.forEach((s, i) => { out += s; if (i < part.values.length) out += text(part.values[i]); });
        return out;
    }
    if (typeof part === 'function') return '';
    return String(part);
}
const S = (state, attributes = {}) => ({ state: String(state), attributes, last_updated: '2026-11-08T19:40:00+01:00' });

function makeCard(extra = {}) {
    const el = new (customElements.get('sem-next-plan-card'))();
    el.setConfig({ type: 'custom:sem-next-plan-card' });
    el.hass = {
        states: {
            'switch.sem_observer_mode': S('off'),
            'sensor.sem_battery_soc': S(54),
            'sensor.sem_battery_dynamic_floor_pct': S(91.6),
            'select.sem_battery_mode': S('self_consumption', { options: ['auto', 'self_consumption', 'force_charge', 'force_discharge', 'off'] }),
            'select.sem_charger_keba_charge_mode': S('solar_plus_battery'),
            'sensor.sem_daily_solar_energy': S(13.9),
            'sun.sun': S('below_horizon'),
            ...extra,
        },
        language: 'en', config: { currency: 'CHF', time_zone: 'Europe/Zurich' },
        callService: async () => {}, callWS: async () => ({}),
    };
    return el;
}

test('unknown cost stays unknown: null is not 0', () => {
    assert.ok(Number.isNaN(knownNum(null)));
    assert.ok(Number.isNaN(knownNum(undefined)));
    assert.ok(Number.isNaN(knownNum('')));
    assert.equal(knownNum(0), 0);
    assert.equal(knownNum('1.5'), 1.5);
});

test('battery row: no raw planner text, honest floor, no Back to plan for a standing mode', () => {
    const el = makeCard();
    const plan = { why: 'ev_targets={x}, battery_deficit=0.00 kWh', why_codes: ['battery_no_deficit'], slots: [], batt_runs: [] };
    const out = text(el._batteryRow(plan, [], []));
    assert.match(out, /energy_plan_whyc_battery_no_deficit/);
    assert.match(out, /next_batt_below_floor/);
    assert.doesNotMatch(out, /next_batt_holds/);
    assert.doesNotMatch(out, /next_back_to_plan/);
    assert.match(out, /title=ev_targets/);   // raw text only as the tooltip
    assert.doesNotMatch(out.replace(/title=[^>]*/, ''), /battery_deficit=/);
});

test('battery row: a forced mode is an override and gets Back to plan', () => {
    const el = makeCard({ 'select.sem_battery_mode': S('force_charge', { options: ['auto', 'force_charge'] }) });
    const out = text(el._batteryRow({ slots: [], batt_runs: [] }, [], []));
    assert.match(out, /next_back_to_plan/);
});

test('a full car shows its status only, no Skip or Start now', () => {
    const el = makeCard();
    const out = text(el._chargerRow('keba', {}, [], [], [{ id: 'ev:keba', why: 'car_full' }]));
    assert.match(out, /energy_plan_why_car_full/);
    for (const k of ['next_skip', 'next_start_now', 'next_charge_now']) assert.doesNotMatch(out, new RegExp(k), k);
    const other = text(el._chargerRow('keba', {}, [], [], []));
    assert.match(other, /next_start_now/);
});

test('legend lists Cheap and Expensive only when the strip has them', () => {
    const el = makeCard();
    const flat = text(el._legend({ bands: { cheap: [], expensive: [] } }));
    assert.doesNotMatch(flat, /next_cheap|next_expensive/);
    const tou = text(el._legend({ bands: { cheap: [{ x0: 0, x1: 0.2 }], expensive: [] } }));
    assert.match(tou, /next_cheap/);
    assert.doesNotMatch(tou, /next_expensive/);
});

test('sun label: what the sun made after sunset, the forecast otherwise', () => {
    const el = makeCard();
    const real = Date.prototype.getHours;
    Date.prototype.getHours = () => 20;
    try {
        assert.match(el._sunLabel({ day: 'today', sun: { kwh: 27 } }), /next_sun_made_kwh/);
        assert.match(el._sunLabel({ day: 'tomorrow', sun: { kwh: 12 } }), /next_sun_forecast_kwh/);
    } finally { Date.prototype.getHours = real; }
    const day = makeCard({ 'sun.sun': S('above_horizon') });
    assert.match(day._sunLabel({ day: 'today', sun: { kwh: 27 } }), /next_sun_forecast_kwh/);
});

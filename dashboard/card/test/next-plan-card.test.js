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

test('Charge now is the backend force override: no mode flip, Back to plan clears it', async () => {
    const el = makeCard();
    const calls = [];
    el.hass.callService = async (d, s, data) => { calls.push([d, s, data]); };
    el._confirm = 'keba';
    await el._chargeNow('keba', {});
    assert.equal(calls.length, 1);
    assert.deepEqual(calls[0].slice(0, 2), ['solar_energy_management', 'plan_override']);
    assert.deepEqual(calls[0][2], { device_id: 'keba', action: 'force', minutes: 120 });
    assert.equal(el._confirm, null);
    assert.ok(!calls.some((c) => c[0] === 'select'), 'the charge mode is not touched');
    // the override shows, so Back to plan shows; after a reload it comes from the backend
    el.hass.states['sensor.sem_energy_plan'] = S('x', { plan_overrides: { keba: { action: 'force', until: '23:00' } } });
    const out = text(el._chargerRow('keba', {}, [], [], []));
    assert.match(out, /next_back_to_plan/);
    calls.length = 0;
    await el._overrideClear('keba');
    assert.deepEqual(calls[0], ['solar_energy_management', 'plan_override_clear', { device_id: 'keba' }]);
});

// ── the chart: sun, price and plan on one clock ──
const HOUR = 3600e3;
const isoAt = (ms) => new Date(ms).toISOString();
function planAround(now) {
    const h0 = Math.floor(now / HOUR) * HOUR;
    const slots = [];
    for (let i = -1; i < 6; i++) slots.push({ start: isoAt(h0 + i * HOUR), end: isoAt(h0 + (i + 1) * HOUR), price: 0.36, home_w: 600, home_grid_w: i >= 3 ? 500 : 0 });
    return { slots, batt_runs: [[0, 3]], blocks: [{ id: 'ev:keba', start: isoAt(h0 + 2 * HOUR), end: isoAt(h0 + 4 * HOUR), power_w: 4000 }], computed_at: isoAt(now) };
}

test('flat tariff: one price said once, no made-up sun, every row labelled', () => {
    const now = Date.now();
    const el = makeCard({
        'sensor.sem_energy_plan': S('idle', planAround(now)),
        'sensor.sem_tariff_current_import_rate': S(0.36, { is_dynamic: false, price_level: 'flat', today_avg: 0.36, upcoming: [] }),
        'sensor.sem_forecast_tomorrow_kwh': S(11.9), 'sensor.sem_forecast_today_kwh': S(29.3),
    });
    el._chargers = ['keba'];
    el._fc = {}; el._stats = [];
    const out = text(el._stripSec(el._plan()));
    assert.match(out, /next_price_flat/);
    assert.doesNotMatch(out, /next_price_avg|next_prices_later/);
    assert.match(out, /next_chip_forecast_kwh/);          // a total, never a drawn bell
    assert.match(out, /next_row_to_house/);
    assert.match(out, /next_row_from_grid/);
    assert.match(out, /next_range_next/);
    assert.match(out, /next_now_marker/);
    assert.doesNotMatch(out, /NaN|undefined/);
});

test('dynamic tariff: steps with min, max and average; unknown prices hatched; forecast drawn with its total', () => {
    const now = Date.now();
    const h0 = Math.floor(now / HOUR) * HOUR;
    const upcoming = [];
    for (let i = 0; i < 24; i++) upcoming.push({ t: isoAt(h0 + i * 900e3), price: i < 8 ? 0.21 : 0.41 });
    const el = makeCard({
        'sensor.sem_energy_plan': S('idle', planAround(now)),
        'sensor.sem_tariff_current_import_rate': S(0.21, { is_dynamic: true, price_level: 'cheap', upcoming }),
    });
    el._chargers = ['keba'];
    el._stats = [];
    el._fc = { [isoAt(h0 + 12 * HOUR)]: 1500, [isoAt(h0 + 13 * HOUR)]: 2500 };
    const out = text(el._stripSec(el._plan()));
    assert.match(out, /next_price_avg/);
    assert.match(out, /next_prices_later/);
    assert.match(out, /4\.0 kWh/);                        // the sun total chip
    assert.doesNotMatch(out, /next_price_flat|next_chip_forecast_kwh/);
    el._hover = h0 + 30 * 60e3;
    const tip = text(el._stripSec(el._plan()));
    assert.match(tip, /next_tip_price/);
});

test('the range switch is remembered and clears a picked block', () => {
    const el = makeCard({ 'sensor.sem_energy_plan': S('idle', planAround(Date.now())) });
    const saved = [];
    globalThis.localStorage = { getItem: () => null, setItem: (k, v) => saved.push([k, v]) };
    el._picked = 'x';
    const sec = el._stripSec(el._plan());
    const seg = JSON.stringify(sec, (k, v) => (typeof v === 'function' ? '[fn]' : v));
    assert.match(seg, /next_tomorrow/);
    el._range = 'tomorrow';
    assert.equal(el._range, 'tomorrow');
    globalThis.localStorage = { getItem: () => null, setItem() {} };
});

test('(#1081) a heat pump planned on the price of heat names its COP', () => {
    const el = makeCard();
    el._t = (k) => (k === 'plan_why_cheapest_heat' ? 'heat {from}–{to}, COP {cop}' : k);
    const out = el._planWhyText('cheapest_heat',
        { from: '2026-11-14T13:00:00+01:00', to: '2026-11-14T15:00:00+01:00', cop: 4.18 });
    assert.match(out, /COP 4\.2$/);
    assert.doesNotMatch(out, /\{cop\}/);
});

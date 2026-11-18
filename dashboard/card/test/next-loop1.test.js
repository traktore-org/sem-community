/**
 * (#1321) Review loop 1: one source per fact, watch-only at write time, no
 * engine text on screen. Real-shaped states: two chargers, a clock past the
 * deadline, a plan that has a heater under both ids, watch-only on.
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
const { deadlineLabel, planWhenKey } = await import('../src/util/next-time.js');
const { chargerSaysEach } = await import('../src/util/charger-questions.js');
const { planLead, planGridKwh } = await import('../src/util/next-lead.js');
const { whyLines } = await import('../src/util/plan-why.js');
const { batterySays } = await import('../src/util/battery-questions.js');
const { plainReason, recordReason } = await import('../src/util/why-rows.js');

const S = (state, attributes = {}) => ({ state: String(state), attributes, last_updated: '2026-11-18T06:16:00+00:00' });
const TZ = 'Europe/Zurich';

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
const words = { why_reason_charger_no_car: 'No car is plugged in.', why_reason_surplus: 'It runs on spare sun.', charge_mode_min_plus_solar: 'Min + Solar' };
const t = (k) => words[k] || k;

// ── A: one reading per charger ──
function twoChargers(extra = {}) {
    return {
        'sensor.sem_charging_strategy': S('idle', { reason: 'min_plus_solar but EV disconnected', reason_code: 'charger_no_car', reason_params: {} }),
        'binary_sensor.sem_charger_keba_connected': S('off'),
        'binary_sensor.sem_charger_sim_connected': S('on'),
        'sensor.sem_charging_state': S('idle', { per_charger_last_decision: {
            keba: { reason_code: 'charger_no_car', params: {} }, sim: { reason_code: 'surplus', params: {} } } }),
        ...extra,
    };
}
test('A: "No car is plugged in" never sits beside a charger that has a car', () => {
    const rows = chargerSaysEach(twoChargers(), ['keba', 'sim'], t, plainReason);
    assert.equal(rows.length, 1);
    assert.equal(rows[0].cid, 'sim');
    assert.equal(rows[0].text, 'It runs on spare sun.');
    assert.ok(!rows.some((r) => /No car/.test(r.text)));
});
test('A: with no car on any charger the fleet line stays', () => {
    const st = twoChargers({ 'binary_sensor.sem_charger_sim_connected': S('off') });
    const rows = chargerSaysEach(st, ['keba', 'sim'], t, plainReason);
    assert.deepEqual(rows.map((r) => [r.cid, r.text]), [[null, 'No car is plugged in.']]);
});

test('A: a deadline that has passed says tomorrow', () => {
    assert.equal(deadlineLabel('07:00', new Date('2026-11-18T06:16:00Z'), TZ, 'tomorrow'), 'tomorrow 07:00');   // 07:16 local
    assert.equal(deadlineLabel('07:00', new Date('2026-11-18T05:00:00Z'), TZ, 'tomorrow'), '07:00');            // 06:00 local
    assert.equal(deadlineLabel('', new Date(), TZ, 'tomorrow'), '');
});

function nowCard(st) {
    const el = new (customElements.get('sem-next-now-card'))();
    el.setConfig({ type: 'custom:sem-next-now-card' });
    el.hass = { states: st, language: 'en', config: { currency: 'CHF', time_zone: TZ }, callService: async (...a) => { el.__calls.push(a); }, callWS: async () => ({}) };
    el.__calls = [];
    return el;
}

test('A: the heat pump on the Now screen is on when it draws power, as on Devices', () => {
    const st = {
        'switch.sem_observer_mode': S('off'),
        'sensor.sem_controllable_devices_count': S(1, { devices: { heat_pump: { name: 'Heat pump', device_type: 'heat_pump', is_on: false, power_entity: 'sensor.hp_power' } } }),
        'sensor.hp_power': S(2000, { unit_of_measurement: 'W' }),
        'sensor.sem_battery_soc': S(50),
    };
    const out = text(nowCard(st)._devicesRow());
    assert.match(out, /Heat pump/);
    assert.match(out, /next_st_on/);
    assert.doesNotMatch(out, /next_st_off/);
});

test('A: the plan line and the Expected tile read one grid figure', () => {
    const plan = { computed_at: '2026-11-18T06:16:00Z', house_grid: { kwh: 0.2 }, blocks: [
        { id: 'comfort:hot_water', start: '2026-11-18T06:16:00Z', end: '2026-11-18T06:29:00Z', power_w: 2800 }] };
    const lead = planLead(plan, { when: 'this morning' });
    assert.equal(lead.main.key, 'next_plan_loads');
    assert.equal(lead.main.params.kwh, String(Math.round(planGridKwh(plan) * 10) / 10));
    assert.equal(lead.main.params.when, 'this morning');
    assert.ok(Math.abs(planGridKwh(plan) - 0.8) < 0.05);
});

test('A: the battery keeps nothing for the morning while it is under the floor', () => {
    assert.equal(batterySays({ powerW: 0, floorPct: 100, socPct: 20 }).next, null);
    assert.equal(batterySays({ powerW: 0, floorPct: 60, socPct: 80 }).next.key, 'bq_next_keeps');
});

// ── B ──
test('B: a heater planned as Keep at run is not also listed as not scheduled', () => {
    const now = Date.parse('2026-11-18T06:16:00Z');
    const plan = { demands: [{ id: 'comfort:hot_water', label: 'Sim Boiler', planned_kwh: 0.6, why: { code: 'short_window', params: { from: '2026-11-18T06:16:00Z', to: '2026-11-18T06:29:00Z' } } }],
        blocks: [{ id: 'comfort:hot_water', start: '2026-11-18T06:16:00Z', end: '2026-11-18T06:29:00Z', power_w: 2800 }],
        not_scheduled: [{ id: 'load:hot_water', why: 'no_runtime_need', label: 'Sim Boiler' }, { id: 'ev:keba', why: 'disconnected', label: 'Keba' }] };
    const ids = whyLines(plan, now).map((l) => l.id);
    assert.deepEqual(ids.filter((i) => /hot_water/.test(i)), ['comfort:hot_water']);
    assert.ok(ids.includes('ev:keba'));
});

test('B: the plan names its window by the real time', () => {
    const at = (iso) => planWhenKey(Date.parse(iso), new Date(iso), TZ);
    assert.equal(at('2026-11-18T06:16:00Z'), 'next_when_morning');   // 07:16
    assert.equal(at('2026-11-18T12:00:00Z'), 'next_when_today');     // 13:00
    assert.equal(at('2026-11-18T21:30:00Z'), 'next_tonight');        // 22:30
    assert.equal(planWhenKey(Date.parse('2026-11-19T07:00:00Z'), new Date('2026-11-18T09:00:00Z'), TZ), 'next_when_tomorrow');
    assert.equal(planWhenKey(Date.parse('2026-11-19T01:00:00Z'), new Date('2026-11-18T21:30:00Z'), TZ), 'next_tonight');
});

// ── C: watch only, checked where the write leaves ──
test('C: watch only refuses device writes at write time and lets SEM settings through', async () => {
    const st = {
        'switch.sem_observer_mode': S('on'),
        'select.sem_battery_mode': S('auto', { options: ['auto', 'force_charge'] }),
        'number.sem_target_peak_limit': S(5, { min: 0, max: 30 }),
        'switch.sem_energy_plan_actuation': S('off'),
        'button.sem_charger_keba_pause_charging': S('unknown'),
    };
    const el = nowCard(st);
    el._selectOption('select.sem_battery_mode', 'force_charge');
    assert.equal(await el._callService('solar_energy_management', 'plan_override', { device_id: 'ev:keba', action: 'force' }), false);
    assert.equal(await el._callService('switch', 'turn_on', { entity_id: 'switch.heizstab' }), false);
    el._pressButton('button.sem_charger_keba_pause_charging');
    await new Promise((r) => setTimeout(r, 0));
    assert.equal(el.__calls.length, 0, 'nothing moved a device');
    el._setNumber('number.sem_target_peak_limit', 7);
    el._toggleSwitch('switch.sem_energy_plan_actuation');
    assert.equal(await el._callService('solar_energy_management', 'update_device_config', { device_id: 'hot_water', property: 'mode', value: 'off' }), true);
    await new Promise((r) => setTimeout(r, 0));
    assert.deepEqual(el.__calls.map((c) => c[1]), ['set_value', 'turn_on', 'update_device_config']);
    assert.equal(el._devOff('select.sem_battery_mode'), true);
    assert.equal(el._devOff('select.sem_charger_keba_charge_mode'), false);
    el.hass = { ...el.hass, states: { ...st, 'switch.sem_observer_mode': S('off') } };
    assert.equal(await el._callService('solar_energy_management', 'plan_override', { device_id: 'ev:keba', action: 'force' }), true);
});

// ── D: never the engine's own words ──
test('D: a would-do record shows a plain sentence or nothing, never the log text', () => {
    const rec = { device_id: 'ev:keba', kind: 'charger', action: 'limit_discharge',
        reason: 'ev plugged in + battery SoC 20% < tonight\'s floor 100.0% → discharge limit 744 W (home/1 across fleet)' };
    const st = { 'sensor.sem_charging_state': S('idle', { per_charger_last_decision: { keba: { reason_code: 'surplus', params: {} } } }) };
    assert.equal(recordReason(rec, st, t), 'It runs on spare sun.');
    assert.equal(recordReason(rec, {}, t), '');
    assert.equal(recordReason({ ...rec, reason_code: 'surplus', params: {} }, {}, t), 'It runs on spare sun.');
    const load = { device_id: 'heizband', kind: 'load', action: 'hold', reason: 'peak_only — user-managed', reason_code: null };
    assert.equal(recordReason(load, {}, t), '');
});

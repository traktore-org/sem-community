/**
 * (#1321 review 18.11) Wrong values and raw names, each pinned with the
 * real-shaped states from PROD: the Plan line and the Grid cost tile read
 * one number, one scale for the flow bars, one price formatter, the grid
 * as import/export, one name helper, no red for a missed deadline with no car.
 *
 * Run: `node --test test/next-review-1118.test.js` (from dashboard/card).
 */
import { test, mock } from 'node:test';
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

const TEXT = {
    next_plan_house: 'house {kwh}', next_plan_quiet: 'QUIET', next_plan_sub: 'sub', next_plan_sub_nocost: 'sub',
    next_import: 'import', next_export: 'Export', next_src_grid: 'Grid', next_fresh_ok: 'ok',
    next_batt_below_floor: 'below {floor}', next_grid_cost: 'Grid cost', next_tonight: 'tonight',
};
globalThis.semLocalize = (key) => TEXT[key] || key;
await import('../src/cards/sem-next-system-card.js');
await import('../src/cards/sem-next-plan-card.js');
const { planLead, houseGridKwh } = await import('../src/util/next-lead.js');
const { flowBars } = await import('../src/util/next-flows.js');
const { fmtPrice, gridReading } = await import('../src/util/next-format.js');
const { displayName, looksRaw, cleanName } = await import('../src/util/next-names.js');
const { slotText } = await import('../src/util/next-settings.js');
const { todayRows } = await import('../src/util/next-today-rows.js');
const { deviceChips } = await import('../src/util/next-now-extras.js');

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
const S = (state, attributes = {}) => ({ state: String(state), attributes, last_updated: '2026-11-18T01:40:00+00:00' });

// the PROD night of 18.11: nothing for the car or loads, the house draws 2.9 kWh from the grid
// (#1321) a fixed clock: the slots are still to come, a past hour is history, not a plan
const NOW0 = Date.parse('2026-11-18T01:40:00Z');
mock.timers.enable({ apis: ['Date'], now: NOW0 });
const T0 = NOW0 + 5 * 60e3;
const slot = (i, w) => ({ start: new Date(T0 + i * 3600e3).toISOString(), end: new Date(T0 + (i + 1) * 3600e3).toISOString(), home_grid_w: w, price: 0.36 });
const PLAN = {
    computed_at: new Date(T0).toISOString(), blocks: [], batt_runs: [[0, 0]], total_cost: 1.05,
    house_grid: { kwh: 2.9, cost: 1.05, reason: null },
    slots: [slot(0, 0), slot(1, 1450), slot(2, 1450), slot(3, 0)],
};

const LOADS = {
    load_device_pro4pm_1: { name: 'Pro4PM S6 Tableau Output 1 Energy', device_type: 'load', power_entity: 'sensor.pro4pm_s6_tableau_output_1_power' },
    load_device_garage: { name: 'garage_carport_licht Power', device_type: 'load', power_entity: 'sensor.garage_carport_licht_power' },
    load_device_kids: { name: 'Eltern,Kind,Balkon', device_type: 'load', power_entity: 'sensor.eltern_kind_balkon_power' },
    load_device_keller: { name: 'Keller', device_type: 'load', power_entity: 'sensor.keller_power' },
};
const FRIENDLY = {
    'sensor.pro4pm_s6_tableau_output_1_power': 'Pro4PM S6 Tableau Output 1 Power',
    'sensor.garage_carport_licht_power': 'garage_carport_licht Power',
    'sensor.eltern_kind_balkon_power': 'Eltern,Kind,Balkon',
    'sensor.keller_power': 'Keller',
};
function states(extra = {}) {
    const st = {
        'switch.sem_observer_mode': S('off'), 'sensor.sem_charging_state': S('idle'), 'sensor.sem_diag_version': S('2.3.0'),
        'sensor.sem_diag_ed_config': S('ok', { energy_dashboard: { solar: { power: 'sensor.inverter_input_power' }, grid: { power: 'sensor.power_meter_active_power' } } }),
        'sensor.inverter_input_power': S(0, { friendly_name: 'Inverter Input power' }),
        'sensor.power_meter_active_power': S(-762, { friendly_name: 'Power meter Active power' }),
        'sensor.sem_solar_power': S(0), 'sensor.sem_grid_power': S(-762), 'sensor.sem_battery_power': S(0),
        'sensor.sem_controllable_devices_count': S(4, { devices: LOADS }),
        'sensor.sem_battery_soc': S(21), 'sensor.sem_battery_dynamic_floor_pct': S(100),
        'sun.sun': S('below_horizon'),
        ...extra,
    };
    for (const [id, name] of Object.entries(FRIENDLY)) st[id] = S(0, { friendly_name: name });
    return st;
}
function hassOf(extra) {
    return { states: states(extra), language: 'en', config: { currency: 'CHF', time_zone: 'Europe/Zurich' },
        entities: {}, devices: {}, callService: async () => ({}), callWS: async () => ({}) };
}
function planCard(extra) {
    const el = new (customElements.get('sem-next-plan-card'))();
    el.setConfig({ type: 'custom:sem-next-plan-card' });
    el.hass = { ...hassOf({ 'sensor.sem_energy_plan': S('x', PLAN), ...extra }) };
    return el;
}
function systemCard() {
    const el = new (customElements.get('sem-next-system-card'))();
    el.setConfig({ type: 'custom:sem-next-system-card' });
    el._optionsAsked = true;
    el.hass = hassOf();
    el._options = { tariff_mode: 'static' };
    return el;
}

// ── 1 Plan line and chart read one number ──
test('1: the Plan line names the grid kWh the Grid cost tile and the chart show', () => {
    const el = planCard();
    const m = el._model();
    const lead = el._lead(PLAN, m);
    assert.doesNotMatch(lead.main, /QUIET/, 'not "nothing planned" while the house buys 2.9 kWh');
    assert.match(lead.main, /house 2\.9/);
    assert.match(text(el._expectedSec(PLAN, m)), /2\.9 kWh|2\.9/);
    assert.equal(houseGridKwh(PLAN), 2.9);
    // chart lane: the same slots sum to the same figure
    const fromSlots = houseGridKwh({ slots: PLAN.slots });
    assert.ok(Math.abs(fromSlots - 2.9) < 0.01, 'slot sum ' + fromSlots);
    const none = planLead({ ...PLAN, house_grid: { kwh: 0 }, slots: [] }, {});
    assert.equal(none.main.key, 'next_plan_quiet', 'quiet only when the house buys nothing');
});

test('1: the battery line no longer claims it needs 100 % by morning', async () => {
    const { readFileSync } = await import('node:fs');
    const all = JSON.parse(readFileSync(new URL('../../translations.json', import.meta.url), 'utf8'));
    for (const [lang, d] of Object.entries(all)) {
        assert.ok(d.next_batt_below_floor && d.next_batt_above_floor, lang);
    }
    assert.doesNotMatch(all.en.next_batt_below_floor, /morning|needs/);
});

// ── 2 one scale, one colour per source ──
test('2: flow bars share one scale and split by source', () => {
    const rows = flowBars([
        { sink: 'home', total: 1.9, parts: [['solar', 0], ['battery', 0.4], ['grid', 1.5]] },
        { sink: 'battery', total: 0.2, parts: [['solar', 0], ['grid', 0.2]] },
        { sink: 'grid', total: 0, parts: [['solar', 0], ['battery', 0]] },
    ]);
    assert.equal(rows[0].widthPct, 100);
    assert.ok(rows[1].widthPct < 15 && rows[1].widthPct >= 2, 'battery in 0.2 of 1.9 is a sliver, got ' + rows[1].widthPct);
    assert.equal(rows[2].widthPct, 0);
    assert.deepEqual(rows[0].segs.map((s) => s.src), ['battery', 'grid'], 'zero parts drop, the rest keep their colours');
    assert.ok(Math.abs(rows[0].segs[0].flex - 0.4 / 1.9) < 1e-9);
});

// ── 3 one price formatter, grid as Now says it ──
test('3: an export price reads 0.075 everywhere, 0.36 stays 0.36', () => {
    assert.equal(fmtPrice(0.075), '0.075');
    assert.equal(fmtPrice(0.07), '0.07');
    assert.equal(fmtPrice(0.36), '0.36');
    assert.equal(fmtPrice(0.3387), '0.339');
    const slot = { kind: 'number', value: 0.075, unit: 'CHF/kWh', step: 0.001 };
    assert.equal(slotText(slot, (k) => k), '0.075\u00a0CHF/kWh', 'a no-break space keeps value and unit together');
    const el = systemCard();
    assert.equal(el._price(0.075), '0.075');
});

test('3: System shows the grid as import, a size and a way, never -762', () => {
    assert.deepEqual(gridReading('-762'), { watts: 762, dir: 'import' });
    assert.deepEqual(gridReading('300'), { watts: 300, dir: 'export' });
    assert.equal(gridReading('unavailable'), null);
    const sys = systemCard();
    sys._showSources = true;
    const out = text(sys._freshSummary(sys._freshRows()));
    assert.match(out, /762 W import/);
    assert.doesNotMatch(out, /-762|−762/);
});

// ── 4 no old level without a car, red only for a real miss ──
test('4: no car, no charge level on the chip', () => {
    const chips = deviceChips({ cars: [{ name: 'EV Charger', connected: false, charging: false, soc: 86 }] });
    assert.equal(chips[0].soc, null);
    assert.equal(chips[0].state, 'unplugged');
    assert.equal(deviceChips({ cars: [{ name: 'EV Charger', connected: true, charging: false, soc: 86 }] })[0].soc, 86);
});

test('4: Min reached after the deadline is red with a car plugged in, and not listed without one (loop 9)', () => {
    const now = Date.parse('2026-11-18T02:01:00+01:00');
    const attrs = { today_plan: [
        { kind: 'ev_deadline', when: '2026-11-18T06:14:00+01:00', label: 'plan_ev_deadline' },
        { kind: 'ev_min_reached', when: '2026-11-18T21:28:00+01:00', label: 'plan_ev_min_reached', values: { kwh: '30.0' } },
    ] };
    assert.equal(todayRows(attrs, { now, carPresent: false }).find((r) => r.kind === 'ev_min_reached'), undefined);
    assert.equal(todayRows(attrs, { now, carPresent: true }).find((r) => r.kind === 'ev_min_reached').late, true);
});

// ── 6 one name helper, no id or slug on any screen ──
const RAW = /[a-z0-9]+_[a-z0-9_]+|,\S|\b(Power|Energy)\b|\b(sensor|switch)\./;
test('6: the name helper: SEM name, HA device name, cleaned friendly name', () => {
    const hass = { states: states(), entities: { 'sensor.keller_power': { device_id: 'd1' } }, devices: { d1: { name: 'Keller', name_by_user: 'Kellerraum' } } };
    assert.equal(displayName(hass, { name: 'Wärmepumpe', entity: 'sensor.keller_power' }), 'Wärmepumpe', 'a name a person chose is kept');
    assert.equal(displayName(hass, { name: 'Keller Power', entity: 'sensor.keller_power' }), 'Kellerraum', 'the HA device name wins over a raw one');
    assert.equal(displayName(hass, { name: 'Pro4PM S6 Tableau Output 1 Energy', entity: 'sensor.pro4pm_s6_tableau_output_1_power' }), 'Pro4PM S6 Tableau Output 1');
    assert.equal(displayName(hass, { name: 'garage_carport_licht Power' }), 'Garage carport licht');
    assert.equal(displayName(hass, { name: 'Eltern,Kind,Balkon' }), 'Eltern, Kind, Balkon');
    // a name a person typed is never rewritten (decimal comma, German words)
    assert.equal(displayName(hass, { name: 'Heizstab 1,5 kW' }), 'Heizstab 1,5 kW');
    assert.equal(displayName(hass, { name: 'Wärmepumpe Verbrauch' }), 'Wärmepumpe Verbrauch');
    assert.equal(cleanName('Grid Power (HA Convention)'), 'Grid');
    assert.equal(cleanName('Sg ready heating 48282'), 'Sg ready heating');
    assert.equal(cleanName('Inverter Input'), 'Inverter');
    assert.equal(cleanName('Battery 1 Charge/Discharge Power'), 'Battery 1 Charge/Discharge');
    assert.equal(displayName(hass, { entity: 'sensor.garage_carport_licht_power' }), 'Garage carport licht');
    assert.ok(looksRaw('sensor.x_y') && looksRaw('a_b') && !looksRaw('Keller'));
});

test('6: no screen prints an entity id or a snake_case slug for these loads', () => {
    const card = systemCard();
    card._showSources = true;
    const sys = text(card.render());
    assert.doesNotMatch(sys, /garage_carport_licht|pro4pm_s6|eltern_kind|Eltern,Kind/);
    assert.doesNotMatch(sys, /Inverter Input power|Power meter Active power/);
    assert.match(sys, /Pro4PM S6 Tableau Output 1\b(?! Energy)/);
    assert.match(sys, /Garage carport licht/);
    const plan = planCard({ 'sensor.sem_energy_plan': S('x', { ...PLAN, demands: [{ id: 'load:load_device_garage', planned_kwh: 0.5 }], blocks: [] }) });
    const out = text(plan._deviceSec({ ...PLAN, demands: [{ id: 'load:load_device_garage', planned_kwh: 0.5 }] }));
    assert.doesNotMatch(out, /garage_carport_licht|load_device_garage/);
});

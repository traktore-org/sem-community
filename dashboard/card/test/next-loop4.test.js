/**
 * (#1321) Review loop 4: one source and one rounding per number, one rule for on, plain words.
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
await import('../src/cards/sem-next-system-card.js');
await import('../src/cards/sem-next-plan-card.js');
await import('../src/cards/sem-next-devices-card.js');
await import('../src/cards/sem-setup-checklist-card.js');
const { deadlineLabel, planWhenKey } = await import('../src/util/next-time.js');
const { chargerSaysEach } = await import('../src/util/charger-questions.js');
const { planLead, planGridKwh } = await import('../src/util/next-lead.js');
const { whyLines } = await import('../src/util/plan-why.js');

const { roundedParts, planRunsRounded, demandFigures, shortfalls, effectivePlan } = await import('../src/util/plan-facts.js');
const { todayRows } = await import('../src/util/next-today-rows.js');
const { nowLead } = await import('../src/util/next-lead.js');
const { mergePerDay, plainReason, commandLabel } = await import('../src/util/why-rows.js');
const { runningNow, switchStateOf } = await import('../src/util/next-devices.js');
const { reviewRows } = await import('../src/util/next-review.js');
const { planNoteText } = await import('../src/util/plan-notes.js');
const { heaterSays } = await import('../src/util/heater-questions.js');

const S = (state, attributes = {}) => ({ state: String(state), attributes, last_updated: '2026-11-18T06:16:00+00:00' });
const TZ = 'Europe/Zurich';
function text(part) {
    if (part == null || typeof part === 'symbol' || part === false) return '';
    if (Array.isArray(part)) return part.map(text).join('');
    if (part && part.strings && part.values) {
        let out = '';
        part.strings.forEach((x, i) => { out += x; if (i < part.values.length) out += text(part.values[i]); });
        return out;
    }
    return typeof part === 'function' ? '' : String(part);
}
function mount(tag, states) {
    const el = new (customElements.get(tag))();
    el.setConfig({ type: 'custom:' + tag });
    el.hass = { states, language: 'en', config: { currency: 'CHF', time_zone: TZ }, callService: async () => {}, callWS: async () => ({}) };
    return el;
}

// the live plan on the test system: two runs of one car, three kWh figures that used to disagree
const NOW = Date.parse('2026-11-18T09:41:00+01:00');
const blk = (a, b, w) => ({ id: 'ev:c2', start: `2026-11-18T${a}:00+01:00`, end: `2026-11-18T${b}:00+01:00`, power_w: w });
const PLAN = {
    blocks: [blk('14:45', '15:00', 4600), blk('15:00', '15:15', 4500), blk('15:15', '15:30', 4455),
        blk('15:45', '16:00', 4750), blk('16:00', '16:15', 4720), blk('16:15', '16:30', 4701), blk('16:30', '16:45', 4601)],
    demands: [{ id: 'ev:c2', kind: 'ev', label: 'Sim Charger 2', status: 'partial', planned_kwh: 8.0, needed_kwh: 10.0 }],
};

test('1: the parts of a figure add up to its rounded total', () => {
    const parts = roundedParts([3.45, 4.55]);
    assert.equal(Math.round(parts.reduce((a, b) => a + b, 0) * 10) / 10, 8.0);
    assert.deepEqual(roundedParts([3.35, 4.65]), [3.4, 4.6]);
    assert.deepEqual(roundedParts([]), []);
});

test('1: Coming up rows add up to the planned kWh the Plan and Now screens say', () => {
    const plan = { blocks: [blk('14:45', '15:00', 13400), blk('15:00', '15:30', 9300), blk('15:45', '16:45', 4650)], demands: PLAN.demands };
    const runs = planRunsRounded(plan, (id) => id === 'ev:c2', NOW);
    const rows = todayRows({ today_plan: [] }, { now: NOW, carPresent: true, plan, cars: [{ cid: 'c2', name: 'Sim Charger 2' }] });
    const shown = rows.filter((r) => r.kind === 'ev_charge_start').map((r) => Number(r.values.kwh));
    const total = runs.reduce((a, r) => a + r.kwh, 0);
    assert.equal(Math.round(shown.reduce((a, b) => a + b, 0) * 10) / 10, Math.round(total * 10) / 10);
    assert.equal(demandFigures(plan, 'ev:c2', NOW).planned, Math.round(total * 10) / 10);
});

test('1: a plan that serves part of the need says "planned of needed", not just the need', () => {
    const car = { present: true, charging: false, remainingKwh: 10, plannedKwh: 8, planWindow: '14:45 – 16:45' };
    const r = nowLead({ car, solarW: 0, gridW: 0 });
    assert.equal(r.main.key, 'next_lead_car_planned_part');
    assert.deepEqual([r.main.params.planned, r.main.params.kwh], ['8.0', '10.0']);
    assert.equal(nowLead({ car: { ...car, plannedKwh: 10 }, solarW: 0, gridW: 0 }).main.key, 'next_lead_car_planned');
});

test('2: "not everything fits" names who is short and by how much', (tc) => {
    tc.mock.method(Date, 'now', () => NOW);   // the plan's runs are read against now: pin it
    const low = shortfalls(effectivePlan(PLAN), NOW);
    assert.equal(low.length, 1);
    assert.deepEqual([low[0].id, low[0].planned, low[0].needed], ['ev:c2', 8.1, 10]);
    const el = mount('sem-next-plan-card', {});
    el._tf = (k, p) => `${k}|${p.name}|${p.planned}|${p.needed}`;
    el._chargerName = () => 'Sim Charger 2';
    assert.equal(el._fitsNo(effectivePlan(PLAN)).split('|').slice(1).join('|'), 'Sim Charger 2|8.1|10.0');
});

test('3: the sun bubble reads the day forecast the Now screen reads, with its day named', () => {
    const el = mount('sem-next-plan-card', { 'sensor.sem_forecast_today_kwh': S(10.4), 'sensor.sem_forecast_tomorrow_kwh': S(14.5) });
    el._tf = (k, p) => `${k}|${p.kwh}|${p.day}`;
    const noon = Date.parse('2026-11-18T12:00:00+01:00');
    const today = el._sunChip({ now: NOW, sun: { totalKwh: 10.0 } }, { s: noon - 18e5, e: noon + 18e5 });
    assert.match(today, /next_chip_sun_day\|10\.4\|/);
    const tmw = el._sunChip({ now: NOW, sun: { totalKwh: 10.0 } }, { s: noon + 864e5 - 18e5, e: noon + 864e5 + 18e5 });
    assert.match(tmw, /\|14\.5\|/);
});

test('4: a plan check and the battery night learner are told apart; a past row never says unknown for the present', () => {
    const say = (k, p) => `${k}:${p.nights}/${p.needed}`;
    const rows = reviewRows({ demands: [{ demand_id: 'arbitrage:battery', kind: 'battery', code: 'learning', nights: 0, needed: 5 },
        { demand_id: 'comfort:hot_water', kind: 'comfort', code: 'learning', nights: 0, label: 'Sim Boiler' }] }, say);
    assert.deepEqual(rows.map((r) => r.kind), ['batteryplan', 'heater'], 'own icons');
    assert.match(rows[0].text, /^next_review_learning/);
    const words = { next_reason_level_unread: 'level not read yet' };
    assert.equal(plainReason({ reason_code: 'battery_car_level_unknown' }, (k) => words[k] || k, { past: true }), 'level not read yet');
});

test('5: "in use" counts measured power; a switch with a rated size is an estimate, shown apart', () => {
    const el = mount('sem-next-devices-card', { 'switch.boiler': S('on'), 'sensor.hp_w': S(800, { unit_of_measurement: 'W' }) });
    const rows = [
        { id: 'boiler', type: 'load', isOn: true, powerEntity: 'switch.boiler', rating: 3000 },
        { id: 'hp', type: 'load', isOn: true, powerEntity: 'sensor.hp_w', rating: 2000 },
        { id: 'off', type: 'load', isOn: false, powerEntity: '', rating: 1000 },
    ];
    const use = el._inUse(rows);
    assert.equal(use.measuredW, 800);
    assert.equal(use.estW, 3000);
});

test('6: Why now has no empty car row: the plan line, or no row', () => {
    const at = (h) => new Date(Date.now() + h * 36e5).toISOString();
    const plan = { blocks: [{ id: 'ev:c2', start: at(3), end: at(4), power_w: 4000 }], demands: [] };
    const make = (p) => {
        const el = mount('sem-next-now-card', { 'sensor.sem_charging_state': S('x', { per_charger_departure: {}, today_plan: [] }),
            'sensor.sem_charging_strategy': S('x', { reason_code: 'charger_no_car' }), 'binary_sensor.sem_charger_c2_connected': S('on'),
            'sensor.sem_energy_plan': S('idle', { ...p, computed_at: at(-1) }), 'sensor.sem_battery_soc': S(21) });
        el._chargers = ['c2'];
        el._t = (k) => k;
        el._tf = (k, v) => `${k}:${v.time || ''}`;
        const seen = [];
        el._row = (icon, title, value, sub) => { seen.push({ icon, title, sub }); return null; };
        el._why();
        return seen.filter((r) => r.icon === 'mdi:car-electric');
    };
    const withPlan = make(plan);
    assert.equal(withPlan.length, 1);
    assert.match(withPlan[0].sub, /^next_st_waits_for:\d\d:\d\d$/);
    assert.equal(make({ blocks: [], demands: [] }).length, 0, 'nothing to say: no row');
});

test('7: setup done with checks to make reads one line, never "complete" beside "2 things to check"', () => {
    const el = mount('sem-setup-checklist-card', {});
    el._t = (k) => k; el._fill = (k, p) => `${k}:${p.n}`;
    const out = text(el._complete({ repairs: { count: 2, first: 'x' } }));
    assert.match(out, /next_set_up · setup_check_n:2/);
    assert.doesNotMatch(out, />setup_complete</);
    assert.match(text(el._complete({ repairs: { count: 0 } })), /setup_complete/);
});

test('8: a heater in its minimum run says so, the same as the decision', () => {
    const row = { comfort: { keep_c: 50, max_c: 53, start_c: 40, reading_c: 45 }, intent: { source: 'solar', code: 'min_run_hold' }, mergedMode: 'solar_only' };
    assert.equal(heaterSays(row, { sunW: 800 }, true).key, 'hq_st_min_run');
});

test('8: the decisions list merges repeats inside a day, never across midnight', () => {
    const rec = (time, n) => ({ time, device_kind: 'battery', device_id: 'b', new: `limit_discharge ${n} W`, reason_code: 'x' });
    const rows = mergePerDay([rec('2026-11-18T00:10:00+01:00', 600), rec('2026-11-17T23:50:00+01:00', 700), rec('2026-11-17T23:40:00+01:00', 800)], TZ);
    assert.equal(rows.length, 2);
    assert.equal(rows[0].count, undefined, 'today row stands alone');
    assert.equal(rows[1].count, 2);
    assert.equal(commandLabel('limit_discharge 1500 W', (k) => (k === 'why_verb_limit_discharge' ? 'stops powering the car' : k)), 'stops powering the car');
});

test('9: one rule for on; an unavailable switch is not on', () => {
    assert.equal(runningNow({ is_on: true }, null, 'unavailable'), false);
    assert.equal(runningNow({ is_on: true }, null, 'on'), true);
    assert.equal(switchStateOf({ switch_entity: 'switch.a' }, { 'switch.a': { state: 'unavailable' } }), 'unavailable');
    assert.equal(switchStateOf({}, {}), null);
});

test('low: a "no price" note says from when', () => {
    const d = { notes: [{ code: 'unpriced_slots', params: { count: 30 } }] };
    const t = (k) => ({ plan_note_unpriced_slots: '{count} slots', plan_note_unpriced_after: 'No prices after {time}' }[k] || k);
    assert.equal(planNoteText(d, t, { until: '13:00' }), 'No prices after 13:00');
    assert.equal(planNoteText(d, t), '30 slots');
});

test('low: every dialog footer holds its buttons, inside the dialog, as its last child', () => {
    const el = mount('sem-next-system-card', {});
    let built = null;
    el._dialog = (o) => { built = o; return { el: { querySelector: () => null }, close() {} }; };
    el._confirmDo({ title: 'T', body: 'B', okLabel: 'Go', run() {} });
    for (const native of [true, false]) {
        const html = built.build(native);
        const foot = html.slice(html.indexOf('dlg-actions'));
        assert.match(foot, /id="cf-cancel"/);
        assert.match(foot, /id="cf-ok"/);
        assert.ok(html.indexOf('ed-help') < html.indexOf('dlg-actions'), 'the footer comes after the body');
    }
});

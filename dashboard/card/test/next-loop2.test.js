/**
 * (#1321) Review loop 2: a tap alone never changes what SEM does.
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
const { deadlineLabel, planWhenKey } = await import('../src/util/next-time.js');
const { chargerSaysEach } = await import('../src/util/charger-questions.js');
const { planLead, planGridKwh } = await import('../src/util/next-lead.js');
const { whyLines } = await import('../src/util/plan-why.js');

const S = (state, attributes = {}) => ({ state: String(state), attributes, last_updated: '2026-11-18T06:16:00+00:00' });
const TZ = 'Europe/Zurich';

/** every function a template carries (the click handlers), in order */
function fns(part, out = []) {
    if (typeof part === 'function') out.push(part);
    else if (Array.isArray(part)) part.forEach((x) => fns(x, out));
    else if (part && part.values) part.values.forEach((x) => fns(x, out));
    return out;
}
function mount(tag, states) {
    const el = new (customElements.get(tag))();
    el.setConfig({ type: 'custom:' + tag });
    el.__calls = [];
    el.hass = { states, language: 'en', config: { currency: 'CHF', time_zone: TZ }, callService: async (...a) => { el.__calls.push(a); }, callWS: async () => ({}) };
    // a dialog that records its buttons instead of drawing
    el.__dlg = { opened: [], on: {} };
    el._dialog = (o) => {
        el.__dlg.opened.push(o);
        const node = { querySelector: (sel) => ({ addEventListener: (_ev, fn) => { el.__dlg.on[sel] = fn; } }) };
        return { el: node, close: () => { el.__dlg.closed = (el.__dlg.closed || 0) + 1; } };
    };
    el.__calls = [];
    return el;
}
/** the writes: loading the options is a read */
const writes = (el) => el.__calls.filter((c) => c[1] !== 'get_config');
const sys = (extra = {}) => mount('sem-next-system-card', {
    'sensor.sem_diag_grid_sign': S('negated'), 'sensor.sem_diag_battery_sign': S('normal'), 'switch.sem_observer_mode': S('on'), ...extra });

test('1: a sign row shows its direction, not "Flip sign"', () => {
    const el = sys();
    const val = (action) => el._actionValue({ kind: 'action', action, labelKey: 'next_flip_sign' }, (k) => k);
    assert.equal(val('flip_grid_sign'), 'sign_negated');
    assert.equal(val('flip_battery_sign'), 'normal');
    assert.equal(el._actionValue({ kind: 'action', action: 'purge_status_history', labelKey: 'next_run' }, (k) => k), 'Next_run');
});

for (const [action, label] of [['flip_grid_sign', 'Grid sign'], ['flip_battery_sign', 'Battery sign'], ['reset_sign_detection', 'Reset'], ['purge_status_history', 'Clean up']]) {
    test(`1: ${action} row — a tap alone calls nothing, confirm calls it once, cancel never`, async () => {
        const el = sys();
        const row = el._slotRow({ slot: { kind: 'action', action, labelKey: 'next_flip_sign' }, label, more: false });
        const tap = fns(row)[0];
        tap();
        assert.equal(writes(el).length, 0, 'tap alone');
        assert.equal(el.__dlg.opened.length, 1);
        el.__dlg.on['#cf-cancel']();
        assert.equal(writes(el).length, 0, 'cancel');
        el.__dlg.on['#cf-ok']();
        await new Promise((r) => setTimeout(r, 5));
        assert.equal(writes(el).filter((c) => c[1] === action).length, 1, 'confirm');
    });
}

test('1: the flip dialog says what flipping does and names its button Flip', () => {
    const el = sys({ 'switch.sem_observer_mode': S('off') });
    el._askAction({ kind: 'action', action: 'flip_grid_sign' }, 'Grid sign');
    const o = el.__dlg.opened[0];
    assert.equal(o.title, 'Grid sign');
    const html = o.build(true);
    assert.match(html, /next_flip_grid_body/);
    assert.match(html, />next_flip_ok</);
    assert.match(html, /cf-cancel/);
});

test('1: a confirmed flip calls the service exactly once', async () => {
    const el = sys({ 'switch.sem_observer_mode': S('off') });
    el._askAction({ kind: 'action', action: 'flip_grid_sign' }, 'Grid sign');
    assert.equal(writes(el).length, 0);
    el.__dlg.on['#cf-ok']();
    await new Promise((r) => setTimeout(r, 5));
    assert.deepEqual(writes(el).map((c) => c[1]), ['flip_grid_sign']);
});

test('1: Plan screen — Sell only asks on a tap', () => {
    const el = mount('sem-next-plan-card', { 'select.sem_battery_mode': S('auto', { options: ['auto', 'force_discharge'] }), 'switch.sem_observer_mode': S('off') });
    const row = el._batteryRow({ slots: [], batt_runs: [] }, [], [], []);
    for (const f of fns(row)) f();
    assert.equal(writes(el).length, 0);
    assert.equal(el.__dlg.opened.length, 1);
    el.__dlg.on['#cf-ok']();
    assert.deepEqual(writes(el).map((c) => [c[0], c[1]]), [['select', 'select_option']]);
});

// ── 2–4: one reading of the plan, from the test system's real shape ──
const { effectivePlan } = await import('../src/util/plan-facts.js');
const { planRows, chartWindow } = await import('../src/util/next-plan-chart.js');
const { todayRows } = await import('../src/util/next-today-rows.js');
const { nowLead } = await import('../src/util/next-lead.js');
const { heaterSays } = await import('../src/util/heater-questions.js');
const { tariffKind } = await import('../src/util/price-level.js');
const { recordReason, plainReason } = await import('../src/util/why-rows.js');

const NOW = Date.parse('2026-11-18T08:10:00+01:00');
// slots and blocks dropped (a quarter-hour day); each demand names its hours
const RAW_PLAN = {
    computed_at: '2026-11-18T08:04:23+01:00', house_grid: { kwh: 15.23 }, slots: [], blocks: [], not_scheduled: [],
    demands: [
        { id: 'comfort:hot_water', label: 'Sim Boiler', planned_kwh: 3.0, why: { code: 'unpriced_hours', params: { from: '2026-11-19T06:30:00+01:00', to: '2026-11-19T07:30:00+01:00' } } },
        { id: 'comfort:old_heater', label: 'Old heater', planned_kwh: 1.0, why: { code: 'unpriced_hours', params: { from: '2026-11-18T06:30:00+01:00', to: '2026-11-18T07:30:00+01:00' } } },
        { id: 'ev:ev_charger_1', label: 'Sim Charger 2', planned_kwh: 10.05, why: { code: 'cheapest_hours', params: { from: '2026-11-18T08:04:23+01:00', to: '2026-11-18T15:15:00+01:00', price: 0.136 } } },
    ],
};

test('2: the headline, the chart and the list read the same car window', () => {
    const plan = effectivePlan(RAW_PLAN);
    const win = chartWindow(NOW, 'next', TZ);
    const lead = planLead(plan, { when: 'today', nowMs: NOW, win });
    assert.equal(lead.main.key, 'next_plan_car', 'the car is the biggest taker still to come');
    assert.equal(lead.main.params.kwh, '9.9');           // from now on, not the 10.05 that includes 06 min gone
    const rows = planRows({ win, nowMs: NOW, plan, names: { charger: () => 'Sim Charger 2' } });
    const car = rows.find((r) => r.kind === 'ev');
    assert.ok(car, 'the chart has the car row');
    assert.equal(new Date(car.blocks[0].e).toISOString(), '2026-11-18T14:15:00.000Z');
    const why = whyLines(plan, NOW);
    assert.ok(why.find((l) => l.id === 'ev:ev_charger_1'));
});

test('2: a block that has run is history: not in the headline, not in the why list', () => {
    const plan = effectivePlan({ ...RAW_PLAN, house_grid: { kwh: 0 }, demands: RAW_PLAN.demands.filter((d) => d.id === 'comfort:old_heater') });
    const lead = planLead(plan, { when: 'today', nowMs: NOW, win: chartWindow(NOW, 'next', TZ) });
    assert.equal(lead.main.key, 'next_plan_quiet', 'a past heater block plans nothing');
    assert.deepEqual(whyLines(plan, NOW).map((l) => l.id), []);
});

test('2: a car block in the future and a heater block in the past: the car is named', () => {
    const plan = effectivePlan({ ...RAW_PLAN, blocks: [
        { id: 'ev:ev_charger_1', start: '2026-11-18T09:00:00+01:00', end: '2026-11-18T11:00:00+01:00', power_w: 4000 },
        { id: 'comfort:hot_water', start: '2026-11-18T06:30:00+01:00', end: '2026-11-18T07:30:00+01:00', power_w: 3000 }] });
    const lead = planLead(plan, { when: 'today', nowMs: NOW, win: chartWindow(NOW, 'next', TZ) });
    assert.equal(lead.main.key, 'next_plan_car');
    assert.equal(lead.main.params.kwh, '8.0');
});

test('2: tomorrow hours say tomorrow; the battery end never reads as a past hour', () => {
    const el = mount('sem-next-plan-card', {});
    const real = Date.now;
    Date.now = () => NOW;
    try {
        assert.equal(el._winText(Date.parse('2026-11-19T06:30:00+01:00'), Date.parse('2026-11-19T07:30:00+01:00')), 'next_when_tomorrow 06:30 – 07:30');
        assert.equal(el._clockDay('2026-11-19T07:30:00+01:00'), 'next_when_tomorrow 07:30');
        assert.equal(el._clockDay('2026-11-18T15:15:00+01:00'), '15:15');
    } finally { Date.now = real; }
});

test('2: Now — the car row names the plan window, the strip guess for an absent car is dropped', () => {
    const attrs = { today_plan: [
        { when: '2026-11-18T08:10:00+01:00', kind: 'device_run', label: 'plan_device_run', values: { name: 'Sim Boiler' } },
        { when: '2026-11-18T17:16:00+01:00', kind: 'ev_charge_start', label: 'plan_ev_charge_start', detail: 'plan_ev_charge_estimate', values: {} }] };
    const plan = effectivePlan(RAW_PLAN);
    const rows = todayRows(attrs, { now: NOW, carPresent: true, plan, cars: [{ cid: 'ev_charger_1', name: 'Sim Charger 2' }] });
    assert.ok(!rows.some((r) => /estimate/.test(String(r.detail))), 'no estimate beside the plan');
    const car = rows.find((r) => r.label === 'next_car_charges');
    assert.equal(car.values.name, 'Sim Charger 2');
    assert.equal(new Date(car.until).getTime(), Date.parse('2026-11-18T15:15:00+01:00'));
    // the boiler row takes the plan's hour (tomorrow 06:30), not the strip's "08:10"
    const boiler = rows.find((r) => r.kind === 'device_run');
    assert.equal(boiler.when, Date.parse('2026-11-19T06:30:00+01:00'));
    assert.equal(boiler.day, 1);
    // no car plugged in: no guess at all
    const none = todayRows(attrs, { now: NOW, carPresent: false, plan: null });
    assert.ok(!none.some((r) => r.kind === 'ev_charge_start'));
});

test('2: the Now lead names the plan window when the plan has hours for the car', () => {
    const car = { present: true, charging: false, powerW: 0, remainingKwh: 10, targetTime: 'tomorrow 07:00', planWindow: '08:04 – 15:15' };
    assert.equal(nowLead({ night: false, observer: true, solarW: 0, gridW: -900, batteryW: 0, car }).main.key, 'next_lead_car_planned');
    assert.equal(nowLead({ night: false, observer: true, solarW: 0, gridW: -900, batteryW: 0, car: { ...car, planWindow: '' } }).main.key, 'next_lead_car_waits');
});

test('3: a boiler that runs with no sun says its minimum run time, not "heating on sun"', () => {
    const row = { comfort: { keep_c: 50, max_c: 53, start_c: 45, reading_c: 48, hvac: 'heat' }, intent: { on: true, source: 'solar', code: 'surplus' }, mergedMode: 'solar_only' };
    assert.equal(heaterSays(row, { sunW: 0 }, true).key, 'hq_st_min_run');
    assert.equal(heaterSays(row, { sunW: 4200 }, true).key, 'hq_st_heating_sun');
    assert.equal(heaterSays(row, {}, true).key, 'hq_st_heating_sun', 'no reading of the sun: the old text');
});

test('3: "one rate" only when the tariff really is one rate; no prices says so', () => {
    const st = (level, extra = {}, rate = '0.15') => ({ 'sensor.sem_tariff_current_import_rate': S(rate, extra), 'sensor.sem_tariff_price_level': S(level) });
    assert.equal(tariffKind(st('flat')), 'flat');
    assert.equal(tariffKind(st('no_prices')), 'none');
    assert.equal(tariffKind(st('unknown', {}, 'unknown')), 'none');
    assert.equal(tariffKind(st('cheap')), 'dynamic');
    assert.equal(tariffKind(st('unknown', { is_dynamic: false })), 'flat');
    assert.equal(tariffKind({}), 'none');
});

test('4: a live reason reads the battery level the chip reads', () => {
    const words = { why_reason_battery_car_level_unknown: 'unknown', why_reason_battery_car_level_known: 'A car is plugged in. The battery is at {soc} %.' };
    const t = (k) => words[k] || k;
    const rec = { reason_code: 'battery_car_level_unknown', params: {} };
    assert.equal(recordReason(rec, { 'sensor.sem_battery_soc': S(20) }, t), 'A car is plugged in. The battery is at 20 %.');
    assert.equal(recordReason(rec, { 'sensor.sem_battery_soc': S('unavailable') }, t), 'unknown');
    assert.equal(plainReason(rec, t), 'unknown', 'a dated record keeps what it said then');
});

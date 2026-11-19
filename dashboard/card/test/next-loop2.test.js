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

function text(part) {
    if (part == null || typeof part === 'symbol' || part === false) return '';
    if (Array.isArray(part)) return part.map(text).join('');
    if (part && part.strings && part.values) {
        let out = '';
        part.strings.forEach((x, i) => { out += x; if (i < part.values.length) out += text(part.values[i]); });
        return out;
    }
    if (typeof part === 'function') return '';
    return String(part);
}

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

const writes_ = (el) => el.__calls.filter((c) => c[1] !== 'get_config');
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
    assert.equal(lead.main.params.kwh, '10.1');          // the whole run, as every list names it (#1321 loop 3)
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
    assert.equal(plainReason(rec, (k) => ({ next_reason_level_unread: 'not read yet' }[k] || k), { past: true }), 'not read yet');
});

// ── 5: one name ──
const { displayName, cleanName } = await import('../src/util/next-names.js');
const { chargerNameOf } = await import('../src/util/charger-name.js');

test('5: a friendly name a person chose is returned as it is; raw ones are cleaned', () => {
    const hass = (friendly) => ({ states: { 'sensor.x': { state: '1', attributes: { friendly_name: friendly } } } });
    assert.equal(displayName(hass('Heizstab 1,5 kW'), { entity: 'sensor.x' }), 'Heizstab 1,5 kW');
    assert.equal(displayName(hass('Wärmepumpe Verbrauch'), { entity: 'sensor.x' }), 'Wärmepumpe Verbrauch');
    assert.equal(displayName(hass('garage_carport_licht Power'), { entity: 'sensor.x' }), 'Garage carport licht');
    assert.equal(displayName(hass('Pro4PM S6 Tableau Output 1 Energy'), { entity: 'sensor.x' }), 'Pro4PM S6 Tableau Output 1');
    assert.equal(displayName(hass('Eltern,Kind,Balkon'), { entity: 'sensor.x' }), 'Eltern, Kind, Balkon');
    assert.equal(displayName(hass(''), { name: 'sensor.keller_power' }), 'Keller');
    assert.equal(displayName(hass(''), { name: '' }), '');
    assert.equal(cleanName(''), '');
});

test('5: the same load has one name on System and on Devices', () => {
    const devices = { energy_dashboard_shellyplus1pm_441793d5470c: { name: 'Heizkörper Frauen Energy', device_type: 'load', power_entity: 'sensor.p' } };
    const sysEl = sys({ 'sensor.sem_controllable_devices_count': S(1, { devices }), 'sensor.p': S(0, { friendly_name: 'Heizkörper Frauen Energy' }) });
    const rec = { kind: 'load', device_id: 'energy_dashboard_shellyplus1pm_441793d5470c', name: 'Heizkörper Frauen Energy' };
    const onDevices = mount('sem-next-devices-card', sysEl.hass.states)._loadName('energy_dashboard_shellyplus1pm_441793d5470c', devices.energy_dashboard_shellyplus1pm_441793d5470c);
    assert.equal(sysEl._refusedName(rec, (k) => k, [rec]), onDevices);
    assert.equal(onDevices, 'Heizkörper Frauen');
});

test('5: while names load a charger is "Charger N", never a slug or a hash', () => {
    assert.equal(chargerNameOf({}, 'keba_fa87f74cd3', 'sensor.sem_', 'Charger 1'), 'Charger 1');
    // SEM's own device list names it when the power sensor has not loaded
    const states = { 'sensor.sem_controllable_devices_count': S(1, { devices: { ev_charger_1: { name: 'Sim Charger 2' } } }) };
    assert.equal(chargerNameOf(states, 'ev_charger_1', 'sensor.sem_', 'Charger 2'), 'Sim Charger 2');
    const el = mount('sem-next-plan-card', {});
    el._chargers = ['keba_fa87f74cd3', 'ev_charger_1'];
    assert.equal(el._chargerName('ev_charger_1'), 'config_detect_charger 2');
});

// ── 6: words and numbers that agree ──
const { groups, sentenceText } = await import('../src/util/next-settings.js');
const { reviewRows } = await import('../src/util/next-review.js');
const { trustPct } = await import('../src/util/forecast-evidence.js');

test('6: by price range the fixed thresholds are named nowhere: the range does not use them', () => {
    const states = { 'number.sem_cheap_price_threshold': S(0.15, { min: 0, max: 5, step: 0.01 }), 'number.sem_expensive_price_threshold': S(0.35, { min: 0, max: 5, step: 0.01 }),
        'sensor.sem_battery_soc': S(50), 'switch.sem_observer_mode': S('off') };
    const tt = (k) => ({ next_pay_by_range: 'range {basis}', next_pay_thresholds: 'cheap {cheap} expensive {expensive} ({basis})', next_pay_dynamic: 'dyn' }[k] || k);
    const ctx = (mode) => ({ options: { tariff_mode: 'dynamic', tariff_classification_mode: mode }, currency: 'CHF', chargers: [], labels: {} });
    const pay = (mode) => groups(states, tt, ctx(mode)).find((g) => g.key === 'pay');
    const range = pay('percentile'), fixed = pay('static');
    assert.doesNotMatch(sentenceText(range.sentence, tt, states), /0\.35|0\.15/);
    assert.match(sentenceText(fixed.sentence, tt, states), /0\.35/);
    assert.ok(!range.rows.some((r) => /price_threshold/.test(r.slot.id)), 'no unused row in All settings');
    assert.ok(fixed.sentence && /0\.35/.test(sentenceText(fixed.sentence, tt, states)), 'a fixed basis still names them');
});

test('6: the forecast trust is one reading of one fraction', () => {
    assert.equal(Math.round(trustPct(0.584)), 58);
    assert.equal(Math.round(trustPct(65)), 65);
    assert.equal(trustPct('unavailable'), null);
    assert.equal(trustPct(''), null);
});

test('6: a learning row says the learner\'s own count out of what it needs (loop 3)', () => {
    const rv = { demands: [{ demand_id: 'arbitrage:battery', kind: 'battery', code: 'learning', nights: 0, needed: 5 }, { demand_id: 'ev:a', kind: 'ev', code: 'learning', nights: 3 }] };
    const say = (key, p) => `${key}:${p.nights}/${p.needed}`;
    const rows = reviewRows(rv, say, undefined, { battery: 44 });
    assert.deepEqual(rows.map((r) => r.text), ['next_review_learning:0/5', 'next_review_learning:3/5'], 'no other night count joins in');
});

test('6: a held device does not say it "turns off"; a live line keeps its own reason otherwise', () => {
    const words = { why_reason_no_source: 'so it turns off', why_reason_no_source_held: 'so it stays off' };
    const t2 = (k) => words[k] || k;
    assert.equal(plainReason({ reason_code: 'no_source', params: {} }, t2, { held: true }), 'so it stays off');
    assert.equal(plainReason({ reason_code: 'no_source', params: {} }, t2), 'so it turns off');
    assert.equal(recordReason({ reason_code: 'no_source', action: 'hold' }, {}, t2), 'so it stays off');
    assert.equal(recordReason({ reason_code: 'no_source', action: 'off' }, {}, t2), 'so it turns off');
    assert.equal(plainReason({ reason_code: 'surplus_short', params: {} }, t2, { held: true }), null, 'no held text: no sentence');
});

test('6: Plan screen — the actuation row says paused while watch-only', () => {
    const el = mount('sem-next-plan-card', { 'switch.sem_energy_plan_actuation': S('on'), 'switch.sem_observer_mode': S('on'), 'sensor.sem_energy_plan': S('fits', { computed_at: '2026-11-18T08:04:23+01:00', blocks: [], demands: [] }) });
    const m = el._model();
    assert.match(text(el._expectedSec(el._plan(), m)), /next_actuation_watch/);
    const off = mount('sem-next-plan-card', { 'switch.sem_energy_plan_actuation': S('on'), 'switch.sem_observer_mode': S('off'), 'sensor.sem_energy_plan': S('fits', { computed_at: '2026-11-18T08:04:23+01:00', blocks: [], demands: [] }) });
    assert.match(text(off._expectedSec(off._plan(), off._model())), /next_actuation_sub/);
});

// ── 11: two chargers, one mode control each ──
const { chargerBody } = await import('../src/util/next-devices-charger.js');

test('11: each of the six car modes writes that charger\'s own select, on a home with two chargers', () => {
    const MODES = ['off', 'solar_only', 'min_plus_solar', 'solar_plus_battery', 'solar_plus_cheap', 'always_max'];
    const st = { 'switch.sem_observer_mode': S('off'), 'sensor.sem_charging_state': S('idle') };
    for (const cid of ['keba', 'ev_charger_1']) {
        st[`select.sem_charger_${cid}_charge_mode`] = S('min_plus_solar', { options: MODES });
        st[`sensor.sem_charger_${cid}_power`] = S(0, { charger_name: cid });
    }
    const el = mount('sem-next-devices-card', st);
    el._chargers = ['keba', 'ev_charger_1'];
    el._freezeEntity = () => {};
    let modeSeg = null;
    el._seg = (items, key, onChange) => { if (items.some((i) => i.key === 'off') && items.some((i) => i.key === 'always_max')) modeSeg = { items, onChange }; return null; };
    for (const cid of ['keba', 'ev_charger_1']) {
        modeSeg = null;
        chargerBody(el, { cid, type: 'charger' });
        assert.ok(modeSeg, `${cid}: one mode control`);
        assert.deepEqual(modeSeg.items.map((i) => i.key).sort(), [...MODES].sort());
        el.__calls = [];
        for (const m of modeSeg.items.map((i) => i.key).filter((k) => k !== 'min_plus_solar')) modeSeg.onChange(m);
        const writes = writes_(el);
        assert.equal(writes.length, 5);
        for (const w of writes) {
            assert.deepEqual([w[0], w[1]], ['select', 'select_option']);
            assert.equal(w[2].entity_id, `select.sem_charger_${cid}_charge_mode`, 'its own charger, never the other');
        }
        assert.deepEqual(writes.map((w) => w[2].option).sort(), MODES.filter((k) => k !== 'min_plus_solar').sort());
    }
});

// ── 7–9 and the small ones ──
test('7: the Now power figure is on the bar once; the lists and "Why now" print no second copy', () => {
    const st = { 'sensor.sem_grid_power': S(-900, { unit_of_measurement: 'W' }), 'sensor.sem_solar_power': S(0, { unit_of_measurement: 'W' }),
        'sensor.sem_battery_power': S(0, { unit_of_measurement: 'W' }), 'sensor.sem_home_consumption_power': S(900, { unit_of_measurement: 'W' }),
        'sensor.sem_ev_power': S(0, { unit_of_measurement: 'W' }), 'sensor.sem_battery_soc': S(20), 'switch.sem_observer_mode': S('off') };
    const el = mount('sem-next-now-card', st);
    el._io = true;
    // what a person sees: the attributes (aria, title) are not text on the screen
    const out = (text(el._powerNow()) + text(el._why())).replace(/[\w-]+="[^"]*"/g, '');
    assert.equal((out.match(/0\.9 kW/g) || []).length, 1, out.replace(/\s+/g, ' '));
});

test('7: the System setup row counts the same checks as the Now checklist', () => {
    const el = sys({ 'sensor.sem_diag_charger_control': S('number', { setup_checklist: { items: [], done: 3, total: 3, repairs: { count: 2, first: 'x' } } }) });
    assert.match(text(el._setupRow()), /x · next_n_more_checks/, 'the same two checks, named');
});

test('8: the Devices charger shows one Phases row, falling back to the set count', () => {
    const st = { 'switch.sem_observer_mode': S('off'), 'sensor.sem_charging_state': S('idle'), 'number.sem_charger_keba_ev_phases': S(3, { min: 1, max: 3, step: 1 }),
        'sensor.sem_charger_keba_power': S(0, { charger_name: 'Keba' }), 'select.sem_charger_keba_charge_mode': S('off', { options: ['off'] }) };
    const el = mount('sem-next-devices-card', st);
    el._chargers = ['keba'];
    const out = text(chargerBody(el, { cid: 'keba', type: 'charger' }));
    assert.equal((out.match(/next_phases|config_ev_phases/g) || []).length <= 1, true);
    assert.doesNotMatch(out, /phase_status_unknown/);
});

test('9: the peak switch is the first row and "Use a limit" is not in the prose', () => {
    const st = { 'sensor.sem_battery_soc': S(50), 'switch.sem_observer_mode': S('off') };
    const tt = (k) => ({ peak_q_choice_limit: 'Use a limit', peak_q_label: 'Limit grid draw to', peak_q_sub: 'SUB' }[k] || k);
    const may = groups(st, tt, { options: { peak_limit_unlimited: false, target_peak_limit: 5 }, currency: 'CHF', chargers: [], labels: {} }).find((g) => g.key === 'may');
    const order = may.rows.map((r) => (r.slot.peak ? 'switch' : r.slot.option));
    assert.ok(order.indexOf('switch') < order.indexOf('target_peak_limit'), order.join());
    assert.doesNotMatch(sentenceText(may.sentence, tt, st), /Use a limit/);
});

test('low: no trailing dot, no break inside a temperature, next departure by its own day', (tc) => {
    // pinned: the label reads new Date() as well as Date.now()
    tc.mock.timers.enable({ apis: ['Date'], now: Date.parse('2026-11-20T18:00:00+01:00') });
    const el = mount('sem-next-plan-card', { });
    el._hass.config.unit_system = { temperature: '°C' };
    assert.equal(el._temp(2), '2.0 °C');
    const now = mount('sem-next-now-card', { 'sensor.sem_charging_state': S('idle', { per_charger_departure: { keba: { next: '2026-11-23T07:00:00+01:00' } } }) });
    assert.match(now._departureLabel('keba'), /07:00$/);
    assert.doesNotMatch(now._departureLabel('keba'), /^next_when_tomorrow/);
});

test('3.3: the Why list of a plan with a gap draws, and names both runs (loop 3)', () => {
    const t = (h) => `2026-11-18T${String(h).padStart(2, '0')}:00:00+01:00`;
    const plan = { computed_at: t(8), blocks: [{ id: 'ev:a', start: t(9), end: t(10), power_w: 3000 }, { id: 'ev:a', start: t(14), end: t(15), power_w: 2000 }],
        demands: [{ id: 'ev:a', planned_kwh: 5, why: { code: 'cheapest_hours', params: { from: t(9), to: t(15), price: 0.1 } } }] };
    // Pinned clock: runs that ended are dropped, so a real clock past 09:00
    // on the fixture's day failed this test.
    const real = Date.now; Date.now = () => Date.parse(t(8));
    try {
        const el = mount('sem-next-plan-card', { 'sensor.sem_energy_plan': S('fits', plan) });
        const out = text(el._whySec(el._plan()));
        assert.match(out, /09:00 – 10:00/);
        assert.match(out, /14:00 – 15:00/);
    } finally { Date.now = real; }
});

test('3.4: a device the plan does not schedule still draws in the Why list (loop 3)', () => {
    const plan = { computed_at: '2026-11-18T08:00:00+01:00', blocks: [], demands: [], not_scheduled: [{ id: 'ev:b', why: 'no_car' }] };
    const el = mount('sem-next-plan-card', { 'sensor.sem_energy_plan': S('idle', plan) });
    assert.doesNotThrow(() => text(el._whySec(el._plan())));
});

test('3.5: Next block on Now names a clock time, the next RUN, not a number (loop 3)', (t) => {
    t.mock.timers.enable({ apis: ['Date'], now: Date.parse('2026-11-18T10:47:00Z') });   // (#1321) a fixed clock
    const future = (m) => new Date(Date.now() + m * 60e3).toISOString();
    const plan = { computed_at: future(-5), blocks: [{ id: 'load:boiler', start: future(120), end: future(180), power_w: 1500 }] };
    const el = mount('sem-next-now-card', { 'sensor.sem_energy_plan': S('fits', plan) });
    const b = el._nextBlock();
    assert.match(b.time, /^\d\d:\d\d$/);
    assert.equal(b.kwh, '1.5');
});

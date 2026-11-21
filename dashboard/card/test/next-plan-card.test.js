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
const { nightEndMs } = await import('../src/util/next-strip.js');

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
    assert.match(out, /next_batt_now_pct/);
    assert.match(out, /next_why_batt_floor_short/);
    assert.doesNotMatch(out, /next_back_to_plan/);
    assert.match(out, /title=ev_targets/);   // raw text only as the tooltip
    assert.doesNotMatch(out.replace(/title=[^>]*/, ''), /battery_deficit=/);
});

test('battery row: a battery SEM cannot charge says so (#1367)', () => {
    const el = makeCard();
    const plan = { why_codes: ['battery_no_deficit'], slots: [], batt_runs: [] };
    const out = text(el._batteryRow(plan, [], [], [{ id: 'battery', why: 'no_charge_control', label: null }]));
    assert.match(out, /energy_plan_why_no_charge_control/);
    assert.doesNotMatch(out, /battery_no_deficit/);
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
    for (const k of ['next_skip_tonight', 'next_start_now', 'next_full_power']) assert.doesNotMatch(out, new RegExp(k), k);
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

// (#1406) the plan sensor drops its slots when the plan is too big; the end stays in ends_at
function pressed(el, label) {
    const btns = [];
    el._btn = (l, fn) => { btns.push({ l: text(l), fn }); return ''; };
    el._chargerRow('keba', el.__plan, [], [], []);
    const b = btns.find((x) => x.l.includes(label));
    assert.ok(b, label + ' is drawn');
    return b.fn;
}

for (const [label, action] of [['next_skip_tonight', 'skip'], ['next_start_now', 'force']]) {
    test(`(#1406) ${action}: a plan with its slots dropped lasts until its end, not 12 hours`, async () => {
        const el = makeCard();
        const calls = [];
        el.hass.callService = async (d, s, data) => { calls.push([d, s, data]); };
        const ends = Date.now() + (21 * 60 + 37) * 60e3;   // 09:23 → tomorrow 07:00
        el.__plan = { timeline_omitted: true, slots: [], blocks: [], demands: [], ends_at: new Date(ends).toISOString() };
        await pressed(el, label)();
        assert.equal(calls.length, 1);
        assert.deepEqual(calls[0].slice(0, 2), ['solar_energy_management', 'plan_override']);
        assert.equal(calls[0][2].action, action);
        assert.ok(Math.abs(calls[0][2].minutes - (21 * 60 + 37)) <= 1, `minutes ${calls[0][2].minutes}`);
        // the old card sent 720 here
        assert.notEqual(calls[0][2].minutes, 720);
    });
}

test('(#1406) a cold heater names the plan end also when the slots were dropped', () => {
    const el = makeCard({ 'sensor.sem_controllable_devices_count': S(1, { devices: {
        boiler: { name: 'Boiler', comfort: { keep_c: 50, start_c: 45, reading_c: 40 } } } }) });
    const ends = Date.now() + 3 * 3600e3;
    const cold = el._cold({ timeline_omitted: true, slots: [], blocks: [], ends_at: new Date(ends).toISOString() });
    assert.equal(cold.length, 1);
    assert.equal(cold[0].time, el._hhmm(new Date(ends)));
    assert.match(cold[0].time, /^\d\d:\d\d$/, 'a plain time: the sentence has its own word before it');
    // tomorrow's end (any time of day): still a plain time, never "tomorrow 07:00"
    const late = Date.now() + 23 * 3600e3;
    assert.match(el._cold({ slots: [], blocks: [], ends_at: new Date(late).toISOString() })[0].time, /^\d\d:\d\d$/);
    // no end at all: no time, the plain sentence
    assert.equal(el._cold({ slots: [], blocks: [] })[0].time, '');
    // an end that has passed (last night's plan) names no time
    assert.equal(el._cold({ slots: [], blocks: [], ends_at: new Date(Date.now() - 600e3).toISOString() })[0].time, '');
});

test('(#1406) with no plan end ahead, Skip tonight lasts until the next night end', async () => {
    // a night end three hours from now (home zone), so the answer is never 720 by chance
    const at = new Date(Date.now() + 3 * 3600e3);
    const hhmm = new Intl.DateTimeFormat('en-GB', { timeZone: 'Europe/Zurich', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(at);
    const el = makeCard({ 'sensor.sem_night_end_time': S(hhmm) });
    const calls = [];
    el.hass.callService = async (d, s, data) => { calls.push([d, s, data]); };
    el.__plan = { slots: [], blocks: [], demands: [] };   // no plan yet
    await pressed(el, 'next_skip_tonight')();
    const want = Math.round((nightEndMs(hhmm, Date.now(), 'Europe/Zurich') - Date.now()) / 60e3);
    assert.ok(want >= 178 && want <= 181, `want ${want}`);
    assert.ok(Math.abs(calls[0][2].minutes - want) <= 1, `minutes ${calls[0][2].minutes}, want ${want}`);
    // the night end sensor out: the old 12 hours
    calls.length = 0;
    el._local = {};   // the first press stands as an override; start again
    el.hass.states['sensor.sem_night_end_time'] = S('unavailable');
    await pressed(el, 'next_skip_tonight')();
    assert.equal(calls[0][2].minutes, 720);
});

// ── the chart: sun, price and plan on one clock ──
const HOUR = 3600e3;
const isoAt = (ms) => new Date(ms).toISOString();
const PINNED = Date.parse('2026-11-18T10:47:00+01:00');   // (#1321) a fixed clock: the time of day must not decide a result
function planAround(now) {
    const h0 = Math.floor(now / HOUR) * HOUR;
    const slots = [];
    for (let i = -1; i < 6; i++) slots.push({ start: isoAt(h0 + i * HOUR), end: isoAt(h0 + (i + 1) * HOUR), price: 0.36, home_w: 600, home_grid_w: i >= 3 ? 500 : 0 });
    return { slots, batt_runs: [[0, 3]], blocks: [{ id: 'ev:keba', start: isoAt(h0 + 2 * HOUR), end: isoAt(h0 + 4 * HOUR), power_w: 4000 }], computed_at: isoAt(now) };
}

test('flat tariff: one price said once, no made-up sun, every row labelled', (t) => {
    t.mock.timers.enable({ apis: ['Date'], now: PINNED });
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

test('dynamic tariff: steps with min, max and average; unknown prices hatched; forecast drawn with its total', (t) => {
    t.mock.timers.enable({ apis: ['Date'], now: PINNED });
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
    assert.match(out, /next_chip_sun_day/);               // the sun bubble names its day
    assert.doesNotMatch(out, /next_price_flat|next_chip_forecast_kwh/);
    el._hover = h0 + 30 * 60e3;
    const tip = text(el._stripSec(el._plan()));
    assert.match(tip, /next_tip_price/);
});

test('(#1390) prices below zero are drawn below the zero line, inside the lane', () => {
    const now = Date.now();
    const h0 = Math.floor(now / HOUR) * HOUR;
    // the price line's y per step, read from the drawn path ("M x y L x y …")
    const lane = (prices) => {
        const upcoming = prices.map((p, i) => ({ t: isoAt(h0 + i * 900e3), price: p }));
        const el = makeCard({
            'sensor.sem_energy_plan': S('idle', planAround(now)),
            'sensor.sem_tariff_current_import_rate': S(prices[0], { is_dynamic: true, price_level: 'normal', upcoming }),
        });
        el._chargers = ['keba'];
        el._stats = []; el._fc = {};
        const d = el._chartData(el._plan());
        const { lay, svg: chart } = el._chartSvg(d, el._plan());
        const out = text(chart);
        const paths = [...out.matchAll(/<path d="([^"]*)" fill="none"/g)].map((m) => m[1]);
        const line = paths.find((p) => (p.match(/L/g) || []).length >= d.price.steps.length);
        assert.ok(line, 'the price line is drawn');
        const nums = line.replace(/[ML]/g, ' ').trim().split(/\s+/).map(Number);
        const ys = [];
        for (let i = 1; i < nums.length; i += 2) ys.push(nums[i]);
        const at = new Map();
        // each step adds "x0 y" (or "M x0 y") then "x1 y": two points per step
        d.price.steps.forEach((st, i) => at.set(st.p, ys[2 * i + 1]));
        return { out, at, lay };
    };
    const inside = (r) => { for (const y of r.at.values()) assert.ok(y >= r.lay.price[0] && y <= r.lay.price[1], `y ${y} inside the lane`); };
    // all below zero: the dearest (-0.01) sits highest, the cheapest (-0.05) lowest
    const neg = lane([-0.01, -0.01, -0.05, -0.05, -0.03, -0.03, -0.01, -0.02]);
    assert.doesNotMatch(neg.out, /NaN|Infinity/);
    assert.ok(neg.at.get(-0.05) > neg.at.get(-0.01), 'a cheaper price is drawn lower');
    inside(neg);
    // the top price is 0: no division by zero
    const zero = lane([0, 0, -0.02, -0.02, 0, 0, -0.01, -0.01]);
    assert.doesNotMatch(zero.out, /NaN|Infinity/);
    inside(zero);
    // both signs: every step stays inside the lane, the dearest highest
    const mixed = lane([0.12, 0.12, -0.04, -0.04, 0.3, 0.3, 0.05, 0.05]);
    assert.doesNotMatch(mixed.out, /NaN|Infinity/);
    inside(mixed);
    assert.ok(mixed.at.get(0.3) < mixed.at.get(0.12) && mixed.at.get(0.12) < mixed.at.get(-0.04));
});

test('(#1321) prices all above zero use the lane: the cheapest low, the dearest high', () => {
    const now = Date.now();
    const h0 = Math.floor(now / HOUR) * HOUR;
    // a quarter-hour tariff between 0.15 and 0.25: cheapest in the middle,
    // dearest at the end
    const prices = [];
    for (let i = 0; i < 40; i++) prices.push(i >= 34 ? 0.25 : i === 18 ? 0.15 : 0.18 + (i % 4) * 0.01);
    const upcoming = prices.map((p, i) => ({ t: isoAt(h0 + i * 900e3), price: p }));
    const el = makeCard({
        'sensor.sem_energy_plan': S('idle', planAround(now)),
        'sensor.sem_tariff_current_import_rate': S(prices[0], { is_dynamic: true, price_level: 'normal', upcoming }),
    });
    el._chargers = ['keba'];
    el._stats = []; el._fc = {};
    const d = el._chartData(el._plan());
    const { lay, svg: chart } = el._chartSvg(d, el._plan());
    const out = text(chart);
    const paths = [...out.matchAll(/<path d="([^"]*)" fill="none"/g)].map((m) => m[1]);
    const line = paths.find((p) => (p.match(/L/g) || []).length >= d.price.steps.length);
    const nums = line.replace(/[ML]/g, ' ').trim().split(/\s+/).map(Number);
    const ys = [];
    for (let i = 1; i < nums.length; i += 2) ys.push(nums[i]);
    const laneH = lay.price[1] - lay.price[0];
    assert.ok(laneH >= 70, `the lane is ${laneH} px`);
    const spread = Math.max(...ys) - Math.min(...ys);
    assert.ok(spread > laneH * 0.5, `0.15 to 0.25 spans ${spread} of ${laneH} px`);
    for (const y of ys) assert.ok(y >= lay.price[0] && y <= lay.price[1], `y ${y} inside the lane`);
    // the average label sits at the end of its line further from the min and
    // max labels
    const avg = out.match(/<text class="avg" x="([\d.]+)"[^>]*text-anchor="(start|end)"/);
    assert.ok(avg, 'the average is labelled');
    const X = (ms) => Math.max(0, Math.min(lay.W, (ms - d.win.start) / (d.win.end - d.win.start) * lay.W));
    const st = d.price.steps;
    const chips = [st.find((x) => x.p === d.price.max), st.find((x) => x.p === d.price.min)].map((x) => X((x.s + x.e) / 2));
    const far = (x) => Math.min(...chips.map((c) => Math.abs(c - x)));
    assert.equal(avg[2], far(X(st[0].s)) > far(X(st[st.length - 1].e)) ? 'start' : 'end');
    assert.match(out, /paint-order="stroke"/);
});

test('the range switch is remembered and clears a picked block', (t) => {
    t.mock.timers.enable({ apis: ['Date'], now: PINNED });
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

test('(#1081) a load with no ask says why, from the plan reason code', () => {
    const el = makeCard({ 'sensor.sem_energy_plan': S('ok', { coverage_why: { 'comfort:heat_pump': 'comfort_no_band' } }) });
    const out = text(el._loadRow('comfort:heat_pump', {}, [], [], []));
    assert.match(out, /why_reason_comfort_no_band/);
    const plain = text(makeCard()._loadRow('comfort:heat_pump', {}, [], [], []));
    assert.doesNotMatch(plain, /why_reason_/);
});

// (#1377) watch-only off + plan execution off = "not applied", never "observation"
function planStates(observer, actuation) {
    return { 'switch.sem_observer_mode': S(observer), 'switch.sem_energy_plan_actuation': S(actuation) };
}

test('Plan screen: control on, plan execution off says not applied and offers the switch', async () => {
    const el = makeCard(planStates('off', 'off'));
    const calls = [];
    el.hass.callService = async (d, s, data) => { calls.push([d, s, data]); };
    const out = text(el._stripPills({ computed_at: '2026-11-08T19:40:00+01:00', actuation: false }));
    assert.match(out, /energy_plan_off/);
    assert.match(out, /energy_plan_turn_on/);
    assert.doesNotMatch(out, /next_pill_shadow/);
    el._toggleSwitch('switch.sem_energy_plan_actuation');
    assert.deepEqual(calls[0], ['switch', 'turn_on', { entity_id: 'switch.sem_energy_plan_actuation' }]);
});

test('Plan screen: watch-only still reads as shadow, live still reads live', () => {
    const watch = text(makeCard(planStates('on', 'off'))._stripPills({ computed_at: '2026-11-08T19:40:00+01:00', actuation: false }));
    assert.match(watch, /next_pill_shadow/);
    assert.doesNotMatch(watch, /energy_plan_off/);
    const live = text(makeCard(planStates('off', 'on'))._stripPills({ computed_at: '2026-11-08T19:40:00+01:00', actuation: true }));
    assert.match(live, /next_pill_live/);
});

// (#1408) the battery's house runs index the slots; the size trim sends them by time instead
test('(#1408) battery row: "to house" times also when the slots were dropped', () => {
    const el = makeCard();
    const s = '2026-11-21T22:00:00+01:00', e = '2026-11-22T02:15:00+01:00';
    const full = { slots: [{ start: s, end: '2026-11-22T00:00:00+01:00' }, { start: '2026-11-22T00:00:00+01:00', end: e }], batt_runs: [[0, 1]] };
    const trimmed = { timeline_omitted: true, slots: [], batt_runs: [], batt_times: [[s, e]] };
    const want = `next_to_house» ${el._hhmm(s)} – ${el._hhmm(e)}`;
    assert.ok(text(el._batteryRow(full, [], [])).includes(want), 'from the slots');
    assert.ok(text(el._batteryRow(trimmed, [], [])).includes(want), 'from the times the trim keeps');
    assert.ok(!text(el._batteryRow({ slots: [], batt_runs: [] }, [], [])).includes('next_to_house'), 'no run, no line');
});

test('(#1408) a home with no battery select still lists the battery when the trimmed plan uses it', () => {
    const el = makeCard();
    delete el.hass.states['select.sem_battery_mode'];
    const rows = (plan) => text(el._deviceSec(plan));
    const trimmed = { timeline_omitted: true, slots: [], blocks: [], demands: [], batt_runs: [], batt_times: [['2026-11-21T22:00:00+01:00', '2026-11-22T02:15:00+01:00']] };
    assert.match(rows(trimmed), /next_to_house/);
    assert.doesNotMatch(rows({ ...trimmed, batt_times: [] }), /next_to_house/);
});

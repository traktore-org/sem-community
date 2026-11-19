// (#1321) review loop 9
import test from 'node:test';
import assert from 'node:assert/strict';
import { whyLines, gotCheapest } from '../src/util/plan-why.js';
import { demandFigures, kwhAhead, batteryFullAt, shortfalls } from '../src/util/plan-facts.js';
import { todayRows, nightStart } from '../src/util/next-today-rows.js';
import { refillKwh } from '../src/util/next-devices-battery.js';
import { upToShown, knownCapacity, capacityUnset } from '../src/util/charger-questions.js';
import { startCode, startLine } from '../src/util/why-rows.js';
import { copLearnLine } from '../src/util/heat-pump-cost.js';
import { powerBar } from '../src/util/next-power-bar.js';
import { sentenceText, groups } from '../src/util/next-settings.js';

const HOUR = 3600e3;
const NOW = Date.parse('2026-11-18T10:00:00Z');
const iso = (h) => new Date(NOW + h * HOUR).toISOString();
const every = (stepH, prices) => prices.map((price, i) => ({ t: iso(i * stepH), price }));

const evPlan = (price) => ({
    blocks: [{ id: 'ev:c2', start: iso(2), end: iso(4), power_w: 5000, reason: 'cheapest_hours' }],
    demands: [{ id: 'ev:c2', planned_kwh: 10, why: { code: 'cheapest_hours', params: { from: iso(2), to: iso(4), price } } }],
});

test('1: hourly tariff: each cell is an hour, so the cheapest hours are the real ones', () => {
    // hours 0..5: 0.30 0.10 0.20 0.20 0.30 0.30; the car takes hours 2-4 at 0.20, the cheapest 2 h average 0.15
    const up = every(1, [0.30, 0.10, 0.20, 0.20, 0.30, 0.30]);
    const runs = [{ s: NOW + 2 * HOUR, e: NOW + 4 * HOUR }];
    assert.equal(gotCheapest({}, runs, 0.20, NOW, up), false);
    assert.equal(whyLines(evPlan(0.20), NOW, 4, up)[0].code, 'cheapest_left');
    const best = [{ s: NOW + 1 * HOUR, e: NOW + 3 * HOUR }];
    assert.equal(gotCheapest({}, best, 0.15, NOW, up), true);
});

test('1: a quarter-hour tariff: 48 points are 12 h; a longer need says nothing', () => {
    const up = every(0.25, new Array(48).fill(0.2));
    const long = [{ s: NOW, e: NOW + 14 * HOUR }];
    assert.equal(gotCheapest({}, long, 0.2, NOW, up), null);
    const ok = [{ s: NOW + 1 * HOUR, e: NOW + 3 * HOUR }];
    assert.equal(gotCheapest({}, ok, 0.2, NOW, up), true);
});

test('7: a battery block named cheapest hours that did not get them says cheap hours', () => {
    const up = every(1, [0.30, 0.11, 0.163, 0.163, 0.30]);
    const plan = { blocks: [{ id: 'arbitrage:battery', start: iso(2), end: iso(4), power_w: 2000, reason: 'cheapest_hours', reason_params: { price: 0.163 } }] };
    const line = whyLines(plan, NOW, 4, up).find((x) => x.id === 'arbitrage:battery');
    assert.equal(line.reasons[0].reason, 'cheap_hours');
    const own = { blocks: [{ id: 'arbitrage:battery', start: iso(1), end: iso(3), power_w: 2000, reason: 'cheapest_hours', reason_params: { price: 0.1365 } }] };
    assert.equal(whyLines(own, NOW, 4, up).find((x) => x.id === 'arbitrage:battery').reasons[0].reason, 'cheapest_hours');
});

const carPlan = () => ({
    computed_at: iso(-3),   // made before the 0.2 kWh run: that run was delivered since, so it comes off the need
    blocks: [
        { id: 'ev:c2', start: iso(-2), end: iso(-1.95), power_w: 4000, reason: 'cheapest_hours' },
        { id: 'ev:c2', start: iso(3), end: iso(5.25), power_w: 4356, reason: 'cheapest_hours' },
    ],
    demands: [{ id: 'ev:c2', needed_kwh: 10, planned_kwh: 10, why: { code: 'cheapest_hours', params: { from: iso(-2), to: iso(5.25) } } }],
});

test('6: only runs still ahead count, everywhere, and the past run is not a gap', () => {
    const plan = carPlan();
    const ahead = kwhAhead(plan, (id) => id === 'ev:c2', NOW);
    assert.ok(Math.abs(ahead - 9.8) < 0.01);
    const f = demandFigures(plan, 'ev:c2', NOW);
    assert.equal(f.planned, 9.8);
    assert.equal(f.needed, 9.8, 'the 0.2 kWh that ran is done, not missing');
    assert.deepEqual(shortfalls(plan, NOW), []);
});

test('6: the Why window starts at the first run ahead', () => {
    const line = whyLines(carPlan(), NOW, 4)[0];
    assert.equal(line.runs[0].s, NOW + 3 * HOUR);
    assert.ok(Math.abs(line.kwh - 9.8) < 0.01);
});

const stripAttrs = {
    today_plan: [
        { kind: 'ev_min_reached', when: iso(12), label: 'plan_ev_min_reached', values: { kwh: '20.0' } },
        { kind: 'battery_full', when: iso(11), label: 'plan_battery_full' },
        { kind: 'night_open', when: iso(7), label: 'plan_night_open' },
    ],
    per_charger_plans: { keba: [{ kind: 'ev_min_reached', when: iso(12), label: 'plan_ev_min_reached', values: { kwh: '20.0' } }], sim: [] },
};

test('4: a charger without a car has no Min row; a car with one is named', () => {
    const none = todayRows(stripAttrs, { now: NOW, carPresent: false, cars: [], multi: true });
    assert.ok(!none.some((r) => r.kind === 'ev_min_reached'));
    const withCar = todayRows(stripAttrs, { now: NOW, carPresent: true, cars: [{ cid: 'keba', name: 'Keba Charger' }], multi: true });
    assert.equal(withCar.find((r) => r.kind === 'ev_min_reached').who, 'Keba Charger');
    const other = todayRows(stripAttrs, { now: NOW, carPresent: true, cars: [{ cid: 'sim', name: 'Sim Charger' }], multi: true });
    assert.ok(!other.some((r) => r.kind === 'ev_min_reached'), 'the other charger has no such row');
});

test('5: Battery full comes from the plan; no plan time, no row', () => {
    const plan = { battery_end: { pct: 100 }, blocks: [{ id: 'arbitrage:battery', start: iso(12.75), end: iso(14), power_w: 4000, reason: 'cheapest_hours' }] };
    assert.equal(batteryFullAt(plan, NOW), NOW + 14 * HOUR);
    const rows = todayRows(stripAttrs, { now: NOW, plan });
    assert.equal(rows.find((r) => r.kind === 'battery_full').when, NOW + 14 * HOUR);
    const notFull = { ...plan, battery_end: { pct: 60 } };
    assert.ok(!todayRows(stripAttrs, { now: NOW, plan: notFull }).some((r) => r.kind === 'battery_full'));
});

test('9: tonight refills the night runs only', () => {
    const plan = { blocks: [
        { id: 'arbitrage:battery', start: iso(1), end: iso(2), power_w: 1000, reason: 'solar' },
        { id: 'arbitrage:battery', start: iso(3), end: iso(4), power_w: 2300, reason: 'cheapest_hours' },
        { id: 'arbitrage:battery', start: iso(13), end: iso(14), power_w: 4300, reason: 'cheapest_hours' }] };
    const night = nightStart(stripAttrs, NOW);
    assert.equal(night, NOW + 7 * HOUR);
    assert.equal(refillKwh(plan, 0, NOW, night), 4.3);
    assert.equal(refillKwh(plan, 0, NOW, null), 6.6, 'no night start: the sun runs are the day');
});

test('3: a capacity the server calls unset reads as unknown everywhere', () => {
    const attrs = { set_by_user: false, min: 5, max: 200 };
    assert.ok(capacityUnset(attrs));
    assert.equal(knownCapacity(40, attrs), null);
    assert.deepEqual(upToShown({ max: 100, capacity: null, bound: 200, isSoc: false, unset: true }), { max: null, full: true });
    assert.deepEqual(upToShown({ max: 30, capacity: 40, bound: 200, isSoc: false, unset: false }), { max: 30, full: false });
});

test('8: a load that is off and about to start says it in one line', () => {
    const t = (k) => ({ next_would_switch_on: 'would switch on', next_switches_soon: 'switches on soon', why_short_solar: 'enough spare sun' }[k] || k);
    const row = { type: 'load', intent: { code: 'solar' } };
    assert.equal(startCode(row, { key: 'next_st_off' }), 'solar');
    assert.equal(startCode(row, { key: 'next_st_on' }), '');
    assert.equal(startLine('solar', true, t), 'would switch on: enough spare sun');
    assert.equal(startLine('solar', false, t), 'switches on soon: enough spare sun');
    assert.equal(startLine('surplus_short', true, t), '');
});

test('low: the learned curve line says when it is not used', () => {
    const t = (k) => k;
    const learn = { state: 'learned', hours: 21, tmin: 8.9, tmax: 8.9 };
    assert.equal(copLearnLine(learn, t, 'learned'), 'hp_cop_learned_from');
    assert.equal(copLearnLine(learn, t, 'flat'), 'hp_cop_learned_idle');
});

test('low: a thin house segment still carries its number on the bar marker', () => {
    const bar = powerBar({ solarW: 1900, homeW: 200, batteryW: 1700 });
    const house = bar.sinks.find((s) => s.key === 'home');
    assert.ok(!house.label && house.share >= 0.08);
});

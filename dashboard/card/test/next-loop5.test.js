/**
 * (#1321) Review loop 5: a counter dip is not use, parts add up to the total,
 * one battery sentence, one reason source, the car capped at its battery and at
 * its need, a running load is shown running.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { diffCumulative } from '../src/util/next-history.js';
import { fitParts } from '../src/util/next-split.js';
import { batteryNeedText } from '../src/util/next-battery-line.js';
import { whyLines } from '../src/util/plan-why.js';
import { upToShown } from '../src/util/charger-questions.js';
import { effectivePlan, planRuns } from '../src/util/plan-facts.js';
import { surplusInUse, runsNotStartedBySem } from '../src/util/next-devices.js';
import { planLead } from '../src/util/next-lead.js';

// the grid-to-home counter on the test system, 18.11., hourly last states (HA time): it flickered
// down by 0.5 kWh for minutes at a time and was read as a restart
const GRID_TO_HOME = [0.69, 1.4, 2.2, 3.0, 3.8, 4.7, 5.5, 6.7, 7.7, 7.3, 7.9, 8.1];

test('1: a small drop of a daily counter is a correction, not a restart: the day adds up to its last value', () => {
    const inc = diffCumulative(GRID_TO_HOME);
    const total = inc.reduce((a, v) => a + v, 0);
    assert.ok(Math.abs(total - 8.1) < 1e-9, `hours add up to the counter, got ${total}`);
    assert.ok(Math.max(...inc) < 1.3, 'no hour jumps by the whole counter');
});

test('1: a real restart at midnight still counts what the new counter holds', () => {
    assert.deepEqual(diffCumulative([17.5, 18.0, 1.1, 1.8]).map((v) => Math.round(v * 10) / 10), [17.5, 0.5, 1.1, 0.7]);
});

test('1: the climb back after a dip is not counted twice', () => {
    assert.deepEqual(diffCumulative([7.8, 7.3, 7.85]).map((v) => Math.round(v * 100) / 100), [7.8, 0, 0.05]);
});

test('1: parts fitted to the total add up in shown decimals', () => {
    const parts = fitParts([0.7, 0, 15.1], 8.7, 1);
    assert.equal(Math.round(parts.reduce((a, v) => a + v, 0) * 10), 87);
    assert.ok(parts[2] < 8.7);
    assert.deepEqual(fitParts([1, 1, 1], 1, 1).reduce((a, v) => a + v, 0), 1);
    assert.deepEqual(fitParts([], 3), []);
});

const tf = (k, p) => `${k}|${Object.values(p || {}).join('|')}`;
const t = (k) => k;

test('2: the battery sentence names the need; when it is more than the battery holds, all of it stays', () => {
    const all = batteryNeedText(tf, t, { phase: 'holding', floor: 100, need: 11.68, soc: 21, avail: 10.18 });
    assert.equal(all, 'next_batt_need_all|11.7|10.2');
    // (#1321) a need under what is above the reserve is never "more than the battery holds"
    assert.equal(batteryNeedText(tf, t, { phase: 'holding', floor: 100, need: 8, soc: 21, avail: 10.18 }), 'next_batt_need_hold|8.0');
    assert.equal(batteryNeedText(tf, t, { phase: 'holding', floor: 100, need: 11.68, soc: 21, avail: null }), 'next_batt_need_hold|11.7');
    const spare = batteryNeedText(tf, t, { phase: 'spending', floor: 60, need: 6.2, soc: 80 });
    assert.equal(spare, 'next_batt_need_above|6.2|60');
    assert.equal(batteryNeedText(tf, t, { phase: '', floor: 100, need: null, soc: 21 }), 'next_batt_holds_house');
});

test('3: the battery line gives the reasons of its blocks, the same the chart names', () => {
    const at = (m) => new Date(Date.parse('2026-11-18T10:00:00+01:00') + m * 6e4).toISOString();
    const plan = {
        blocks: [
            { id: 'arbitrage:battery', start: at(0), end: at(60), power_w: 3000, reason: 'solar' },
            { id: 'arbitrage:battery', start: at(780), end: at(795), power_w: 2000, reason: 'cheapest_hours', reason_params: { price: 0.16 } },
        ],
        demands: [{ id: 'arbitrage:battery', kind: 'battery', planned_kwh: 3.5, why: { code: 'cheapest_hours', params: { from: at(0), to: at(800), price: 0.087 } } }],
    };
    const line = whyLines(plan, Date.parse(at(-5)))[0];
    assert.deepEqual(line.reasons.map((r) => r.reason), ['solar', 'cheapest_hours'], 'most energy first');
    assert.equal(line.code, '', 'the demand why no longer speaks for the battery');
});

test('4: the car target never reads above the car battery; unknown car at the ceiling says full', () => {
    assert.equal(upToShown({ max: 100, capacity: 40, bound: 100, isSoc: false }).max, 40);
    assert.deepEqual(upToShown({ max: 100, capacity: null, bound: 100, isSoc: false }), { max: 100, full: true });
    assert.deepEqual(upToShown({ max: 60, capacity: null, bound: 100, isSoc: false }), { max: 60, full: false });
    assert.equal(upToShown({ max: 80, capacity: 40, bound: 100, isSoc: true }).max, 80);
});

test('5: a demand is shown at its need, not at the slots it was rounded up to; the parts still add up', () => {
    const base = Date.parse('2026-11-18T14:00:00+01:00');
    const iso = (m) => new Date(base + m * 6e4).toISOString();
    const plan = {
        blocks: [
            { id: 'ev:c2', start: iso(0), end: iso(60), power_w: 4140 },
            { id: 'ev:c2', start: iso(75), end: iso(165), power_w: 4140 },
        ],
        demands: [{ id: 'ev:c2', kind: 'ev', planned_kwh: 10.3, needed_kwh: 10.0 }],
    };
    const raw = planRuns(plan, (id) => id === 'ev:c2').reduce((a, r) => a + r.kwh, 0);
    assert.ok(raw > 10.2, 'the slots hold more than the need');
    const runs = planRuns(effectivePlan(plan), (id) => id === 'ev:c2');
    assert.ok(Math.abs(runs.reduce((a, r) => a + r.kwh, 0) - 10.0) < 1e-6);
    assert.equal(runs.length, 2, 'the gap stays a gap');
});

test('6: a load SEM leaves alone that runs is shown running, with its own power', () => {
    const row = { kind: 'load', action: 'hold', power_w: 0 };
    const info = { is_on: false, power_entity: 'sensor.hp' };
    assert.equal(runsNotStartedBySem(row, info, 2000, null), true);
    assert.equal(runsNotStartedBySem(row, info, 0, null), false);
    assert.equal(runsNotStartedBySem({ ...row, action: 'activate' }, info, 2000, null), false);
});

test('7: devices in use never add up to more than the house; a sensor above the house is named', () => {
    const rows = [
        { type: 'load', name: 'Heat pump', isOn: true, rating: 2000, live: 2000 },
        { type: 'load', name: 'Heater', isOn: true, rating: 600, live: 600 },
    ];
    const use = surplusInUse(rows, (r) => r.live, 600);
    assert.equal(use.measuredW, 600);
    assert.deepEqual(use.names, ['Heater']);
    assert.deepEqual(use.over, ['Heat pump']);
    assert.equal(surplusInUse(rows, (r) => r.live, null).measuredW, 2600, 'no house reading: nothing to cap by');
});

test('low: a plan without a total cost names whose cost is missing', () => {
    const lead = planLead({ blocks: [], demands: [], computed_at: '2026-11-18T10:02:00+01:00' }, { computedAt: '10:02', cost: '', costUnknownFor: 'Sim Boiler', fitsKey: 'x', sunTomorrowKwh: 16.6 });
    assert.equal(lead.sub.key, 'next_plan_sub_nocost_who');
    assert.equal(lead.sub.params.who, 'Sim Boiler');
});

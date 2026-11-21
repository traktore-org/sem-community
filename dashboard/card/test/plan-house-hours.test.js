/**
 * (#1408) The Plan headline counts the house's grid kWh from now to the end of
 * the chart. When the plan is too big, the sensor drops the slots; the old card
 * then counted the whole plan's total, past hours and the hours after midnight
 * included. The sensor now sends `house_grid_hours` and `batt_times` in their
 * place. The fixture is the one tests/test_1408_house_grid_hours.py checks
 * against the sensor.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { houseKwhIn, houseWindowed, houseHours, houseSegments, battHouseRuns, effectivePlan } from '../src/util/plan-facts.js';
import { planLead } from '../src/util/next-lead.js';
import { planRows, chartWindow, runningAt } from '../src/util/next-plan-chart.js';

const TZ = 'Europe/Zurich';
const FX = JSON.parse(readFileSync(new URL('./fixtures/house-hours-1408.json', import.meta.url), 'utf8'));
const at = (iso) => Date.parse(iso);
const close = (a, b, eps = 0.002) => assert.ok(Math.abs(a - b) < eps, `${a} vs ${b}`);

// the plan made at 22:00 as the sensor sends it: slots dropped, the hours kept
const TRIMMED = { computed_at: '2026-11-21T22:00:00+01:00', timeline_omitted: true, slots: [], blocks: [], demands: [],
    house_grid: FX.house_grid, house_grid_hours: FX.house_grid_hours, batt_runs: [], batt_times: FX.batt_times };
const FULL = { ...TRIMMED, timeline_omitted: undefined, slots: FX.slots, house_grid_hours: undefined, batt_times: undefined, batt_runs: [[0, 16]] };

test('(#1408) the report: at 03:00 the headline counts the house from 03:00, not from 22:00', () => {
    const now = at('2026-11-22T03:00:00+01:00');
    const win = chartWindow(now, 'next', TZ);
    const kwh = houseKwhIn(TRIMMED, now, win.end);
    close(kwh, 0.475 * 4);
    assert.ok(kwh < FX.house_grid.kwh - 0.3, 'the old card counted the whole plan here');
    const lead = planLead(TRIMMED, { nowMs: now, win, when: 'tonight' });
    assert.equal(lead.main.key, 'next_plan_house');
    assert.equal(lead.main.params.kwh, '1.9');
});

test('(#1408) the Today view stops at midnight: no house hour after it', () => {
    const now = at('2026-11-21T22:30:00+01:00');
    const win = chartWindow(now, 'today', TZ);
    assert.equal(houseKwhIn(TRIMMED, now, win.end), 0, 'the house draws from 02:15 only');
    assert.equal(planLead(TRIMMED, { nowMs: now, win }).main.key, 'next_plan_quiet');
});

test('(#1408) the hours give what the slots give, on whole hours and inside them', () => {
    const cuts = ['2026-11-21T22:00:00+01:00', '2026-11-22T01:00:00+01:00', '2026-11-22T02:00:00+01:00', '2026-11-22T04:00:00+01:00', '2026-11-22T07:00:00+01:00'];
    for (const a of cuts) for (const z of cuts) {
        if (at(z) <= at(a)) continue;
        close(houseKwhIn(TRIMMED, at(a), at(z)), houseKwhIn(FULL, at(a), at(z)));
    }
    // inside an hour the hour counts by time: 04:30 – 05:00 is half of 04:00's hour
    close(houseKwhIn(TRIMMED, at('2026-11-22T04:30:00+01:00'), at('2026-11-22T05:00:00+01:00')), 0.475 / 2);
    // the 02:00 hour draws from 02:15 only: at 02:10 nothing of it has passed, as with the slots
    close(houseKwhIn(TRIMMED, at('2026-11-22T02:10:00+01:00'), Infinity), houseKwhIn(FULL, at('2026-11-22T02:10:00+01:00'), Infinity));
    close(houseKwhIn(TRIMMED, at('2026-11-22T02:00:00+01:00'), at('2026-11-22T02:15:00+01:00')), 0);
    // the whole plan: its own total
    close(houseKwhIn(TRIMMED, -Infinity, Infinity), FX.house_grid.kwh, 0.01);
});

test('(#1408) the house is named against a load when its hours are known', () => {
    const now = at('2026-11-22T02:00:00+01:00');
    const plan = { ...TRIMMED, blocks: [{ id: 'load:pump', start: '2026-11-22T03:00:00+01:00', end: '2026-11-22T04:00:00+01:00', power_w: 1000 }] };
    const lead = planLead(plan, { nowMs: now, win: chartWindow(now, 'next', TZ) });
    // house from 02:00: 0.375 + 4 × 0.475 = 2.275 kWh, more than the pump's 1.0
    assert.equal(lead.main.key, 'next_plan_house');
    assert.equal(lead.main.params.kwh, '2.3');
});

test('(#1408) a sensor from before #1408 (no slots, no hours) keeps the old reading', () => {
    const old = { ...TRIMMED, house_grid_hours: undefined };
    assert.equal(houseWindowed(old), false);
    assert.equal(houseKwhIn(old, 0, 1), FX.house_grid.kwh);
    assert.equal(houseWindowed(TRIMMED), true);
    assert.equal(houseWindowed(FULL), true);
});

test('(#1408) hours the card cannot read are no hours', () => {
    for (const h of [null, {}, { start: 'x', kwh: [1] }, { start: '2026-11-21T22:00:00+01:00' }, { start: 5, kwh: [1] }]) {
        assert.equal(houseHours({ house_grid_hours: h }), null, JSON.stringify(h));
    }
    // a value that is not a number counts nothing, the rest still counts
    const plan = { slots: [], house_grid_hours: { start: '2026-11-21T22:00:00+01:00', kwh: ['x', null, 0.5, -1] } };
    close(houseKwhIn(plan, -Infinity, Infinity), 0.5);
});

test('(#1408) the slots stay first: hours beside slots change nothing', () => {
    const both = { ...FULL, house_grid_hours: { start: FX.house_grid_hours.start, kwh: FX.house_grid_hours.kwh.map(() => 99) } };
    close(houseKwhIn(both, -Infinity, Infinity), houseKwhIn(FULL, -Infinity, Infinity));
});

test('(#1408) effectivePlan keeps the hours and the battery times', () => {
    const p = effectivePlan({ ...TRIMMED, demands: [{ id: 'ev:a', planned_kwh: 2, runs: [['2026-11-22T01:00:00+01:00', '2026-11-22T02:00:00+01:00', 2000]] }] });
    assert.equal(p.house_grid_hours, TRIMMED.house_grid_hours);
    assert.equal(p.batt_times, TRIMMED.batt_times);
});

test('(#1408) the battery runs by time: from the slots, or from the times the trim keeps', () => {
    const full = battHouseRuns(FULL);
    const trimmed = battHouseRuns(TRIMMED);
    assert.deepEqual(full.map((r) => [r.s, r.e]), trimmed.map((r) => [r.s, r.e]));
    assert.deepEqual([full[0].first, full[0].last], [0, 16]);
    assert.equal(trimmed[0].first, null);
    assert.deepEqual(battHouseRuns({ slots: [], batt_times: [['x', 'y'], 'bad', null, ['2026-11-22T02:00:00+01:00', '2026-11-22T01:00:00+01:00']] }), []);
    assert.deepEqual(battHouseRuns({ slots: FX.slots, batt_runs: [[0, 99], 'bad'] }), [], 'an index past the slots names no run');
    assert.deepEqual(battHouseRuns(null), []);
    // with slots the times are not read: the slots are the plan
    assert.deepEqual(battHouseRuns({ ...FULL, batt_runs: [], batt_times: TRIMMED.batt_times }), []);
});

test('(#1408) the chart draws the house and battery lanes when the slots were dropped', () => {
    const now = at('2026-11-21T23:00:00+01:00');
    const win = chartWindow(now, 'next', TZ);
    const rows = planRows({ win, nowMs: now, plan: TRIMMED });
    const grid = rows.find((r) => r.kind === 'grid');
    assert.ok(grid, 'the house lane is drawn');
    assert.equal(grid.blocks.length, 1, 'touching hours join');
    assert.equal(grid.blocks[0].s, at('2026-11-22T02:15:00+01:00'), 'from the draw, not from the whole hour');
    assert.equal(grid.blocks[0].e, at('2026-11-22T07:00:00+01:00'));
    close(grid.blocks[0].kwh, FX.house_grid.kwh, 0.01);
    const bat = rows.find((r) => r.kind === 'battery_out');
    assert.ok(bat, 'the battery lane is drawn');
    assert.deepEqual([bat.blocks[0].s, bat.blocks[0].e], [at('2026-11-21T22:00:00+01:00'), at('2026-11-22T02:15:00+01:00')]);
    // the same lanes, on the same hours, as with the slots
    const full = planRows({ win, nowMs: now, plan: FULL });
    const fg = full.find((r) => r.kind === 'grid');
    assert.deepEqual([fg.blocks[0].s, fg.blocks[0].e], [grid.blocks[0].s, grid.blocks[0].e]);
    // 02:05: the battery covers the house; the grid does not, also without the slots
    assert.deepEqual(runningAt(rows, at('2026-11-22T02:05:00+01:00')).map((r) => r.kind), ['battery_out']);
    close(fg.blocks[0].kwh, grid.blocks[0].kwh, 0.01);
    assert.deepEqual(full.find((r) => r.kind === 'battery_out').blocks.map((b) => [b.s, b.e]), bat.blocks.map((b) => [b.s, b.e]));
});

function files(dir) {
    return readdirSync(dir).flatMap((n) => {
        const p = join(dir, n);
        return statSync(p).isDirectory() ? files(p) : (p.endsWith('.js') ? [p] : []);
    });
}

test('(#1408) only battHouseRuns reads batt_runs: the sensor can drop the slots they index', () => {
    const src = new URL('../src', import.meta.url).pathname;
    // next-timeline.js: laneModel, whose lanes no card draws (left open in docs/BUG_CLASSES.md)
    const allowed = new Set([join('util', 'plan-facts.js'), join('util', 'next-timeline.js')]);
    const found = [];
    let seen = 0;
    for (const f of files(src)) {
        const rel = relative(src, f);
        if (!/batt_runs/.test(readFileSync(f, 'utf8'))) continue;
        seen += 1;
        if (!allowed.has(rel)) found.push(rel);
    }
    assert.deepEqual(found, [], 'read the battery runs through battHouseRuns');
    assert.ok(seen >= 1, 'the scan finds plan-facts.js itself (vacuity twin)');
});

test('(#1408) segments: an hour spreads over its draw; with no run named, over the whole hour', () => {
    const start = '2026-11-21T22:00:00+01:00';
    const segs = houseSegments({ house_grid_hours: { start, kwh: [0.6, 0, 0.3], runs: [['2026-11-21T22:20:00+01:00', '2026-11-21T22:40:00+01:00'], ['2026-11-21T22:50:00+01:00', '2026-11-21T23:10:00+01:00']] } });
    // hour 22: 20 + 10 minutes drawing → 0.4 + 0.2; hour 23: 10 minutes named, 0 kWh, nothing; hour 00: no run → whole hour
    assert.deepEqual(segs.map((g) => [new Date(g.s).toISOString().slice(11, 16), new Date(g.e).toISOString().slice(11, 16), Math.round(g.kwh * 1000) / 1000]),
        [['21:20', '21:40', 0.4], ['21:50', '22:00', 0.2], ['23:00', '00:00', 0.3]]);
    assert.deepEqual(houseSegments({ house_grid_hours: { start, kwh: [0.5] } }).map((g) => g.kwh), [0.5], 'no runs key: the whole hour');
    assert.deepEqual(houseSegments({ house_grid_hours: { start, kwh: [0.5], runs: [['x', 'y'], 'bad', null] } }).map((g) => g.e - g.s), [3600e3]);
    assert.deepEqual(houseSegments({}), []);
});

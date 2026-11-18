import { test } from 'node:test';
import assert from 'node:assert/strict';
import { planRuns, nextRun, runsText, effectivePlan, kwhIn, houseKwhIn, windowText, clockWithDay, demandWindow } from '../src/util/plan-facts.js';

const TZ = 'Europe/Zurich';
// the test system's plan at 08:10: slots and blocks dropped, each demand names its hours
const PLAN = {
    computed_at: '2026-11-18T08:04:23+01:00', house_grid: { kwh: 15.23 }, slots: [], blocks: [],
    demands: [
        { id: 'comfort:hot_water', planned_kwh: 3.0, why: { code: 'unpriced_hours', params: { from: '2026-11-19T06:30:00+01:00', to: '2026-11-19T07:30:00+01:00' } } },
        { id: 'ev:ev_charger_1', planned_kwh: 10.05, why: { code: 'cheapest_hours', params: { from: '2026-11-18T08:04:23+01:00', to: '2026-11-18T15:15:00+01:00' } } },
        { id: 'ev:keba', planned_kwh: 0, why: { code: 'x', params: { from: '2026-11-18T09:00:00+01:00', to: '2026-11-18T10:00:00+01:00' } } },
        { id: 'load:none', planned_kwh: 2, why: null },
    ],
};
const NOW = Date.parse('2026-11-18T08:10:00+01:00');

test('effectivePlan: a demand with hours and kWh gets a block; others do not', () => {
    const p = effectivePlan(PLAN);
    assert.deepEqual(p.blocks.map((b) => b.id), ['comfort:hot_water', 'ev:ev_charger_1']);
    const ev = p.blocks[1];
    assert.ok(Math.abs(kwhIn(p.blocks, (id) => id === 'ev:ev_charger_1', 0, Infinity) - 10.05) < 0.01);
    assert.equal(ev.derived, true);
    assert.equal(effectivePlan(PLAN), p, 'same object each time');
});

test('effectivePlan: real blocks win; nothing is added over them', () => {
    const real = { ...PLAN, blocks: [{ id: 'ev:ev_charger_1', start: '2026-11-18T09:00:00+01:00', end: '2026-11-18T10:00:00+01:00', power_w: 4000 }] };
    const p = effectivePlan(real);
    assert.deepEqual(p.blocks.map((b) => b.id), ['ev:ev_charger_1', 'comfort:hot_water']);
    assert.equal(p.blocks[0].power_w, 4000);
});

test('kwhIn counts a run under way whole, cuts it at the window end and drops the past', () => {
    const blocks = [{ id: 'ev:a', start: '2026-11-18T06:00:00+01:00', end: '2026-11-18T10:00:00+01:00', power_w: 1000 }];
    assert.ok(Math.abs(kwhIn(blocks, () => true, NOW, Infinity) - 4) < 0.001);
    assert.ok(Math.abs(kwhIn(blocks, () => true, NOW, Date.parse('2026-11-18T09:00:00+01:00')) - 3) < 0.001);
    assert.equal(kwhIn(blocks, () => true, Date.parse('2026-11-18T11:00:00+01:00'), Infinity), 0);
});

test('houseKwhIn: slots clip to the window; without slots the plan total', () => {
    assert.equal(houseKwhIn(PLAN, 0, 1), 15.23);
    const withSlots = { slots: [{ start: '2026-11-18T08:00:00+01:00', end: '2026-11-18T09:00:00+01:00', home_grid_w: 1000 },
                                { start: '2026-11-18T20:00:00+01:00', end: '2026-11-18T21:00:00+01:00', home_grid_w: 1000 }] };
    assert.ok(Math.abs(houseKwhIn(withSlots, NOW, NOW + 3600e3 * 6) - 50 / 60) < 0.001);
});

test('a window on another day carries its day; today stays plain', () => {
    const w = { tomorrow: 'tomorrow' };
    assert.equal(windowText(Date.parse('2026-11-19T06:30:00+01:00'), Date.parse('2026-11-19T07:30:00+01:00'), NOW, TZ, w), 'tomorrow 06:30 – 07:30');
    assert.equal(windowText(Date.parse('2026-11-18T08:04:00+01:00'), Date.parse('2026-11-18T15:15:00+01:00'), NOW, TZ, w), '08:04 – 15:15');
    assert.equal(windowText(Date.parse('2026-11-18T22:00:00+01:00'), Date.parse('2026-11-19T06:00:00+01:00'), NOW, TZ, w), '22:00 – tomorrow 06:00');
    assert.equal(clockWithDay(Date.parse('2026-11-19T07:30:00+01:00'), NOW, TZ, w), 'tomorrow 07:30');
});

test('demandWindow needs a real span', () => {
    assert.equal(demandWindow({ why: { params: { from: 'x', to: 'y' } } }), null);
    assert.equal(demandWindow(null), null);
});

test('(#1321) a demand with two runs gets two blocks, never one block over the gap', () => {
    const plan = { blocks: [], demands: [{ id: 'ev:a', planned_kwh: 5, runs: [['2026-11-19T01:00:00+01:00', '2026-11-19T02:00:00+01:00', 3000], ['2026-11-19T04:00:00+01:00', '2026-11-19T05:00:00+01:00', 2000]],
        why: { code: 'cheapest_hours', params: { from: '2026-11-19T01:00:00+01:00', to: '2026-11-19T05:00:00+01:00' } } }] };
    const p = effectivePlan(plan);
    assert.deepEqual(p.blocks.map((b) => [b.start.slice(11, 16), b.end.slice(11, 16), b.power_w]), [['00:00', '01:00', 3000], ['03:00', '04:00', 2000]]);
    assert.ok(Math.abs(kwhIn(p.blocks, () => true, -Infinity, Infinity) - 5) < 0.001, 'the kWh is the demand\'s own');
});

test('(#1321) runs join only when they touch, whatever the watts; kWh is the whole run', () => {
    const t = (h, m = 0) => `2026-11-18T${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:00+01:00`;
    const plan = { blocks: [
        { id: 'ev:a', start: t(8, 33), end: t(8, 45), power_w: 4000 }, { id: 'ev:a', start: t(8, 45), end: t(9, 45), power_w: 4800 },
        { id: 'ev:a', start: t(14, 45), end: t(15, 45), power_w: 4400 }, { id: 'ev:b', start: t(9), end: t(10), power_w: 1000 }] };
    const now = Date.parse(t(8, 34));
    const runs = planRuns(plan, (id) => id === 'ev:a', now);
    assert.equal(runs.length, 2, 'the gap stays a gap');
    assert.equal(runs[0].s, Date.parse(t(8, 33)), 'a run under way keeps its own start');
    assert.equal(Math.round((runs[0].kwh + runs[1].kwh) * 10) / 10, 4 * 0.2 + 4.8 + 4.4);
    assert.equal(nextRun(runs, now).s, Date.parse(t(14, 45)), 'the next run, not the next change of watts');
    assert.equal(runsText(runs, (s, e) => `${new Date(s).getUTCHours()}-${new Date(e).getUTCHours()}`), '7-8, 13-14');
    assert.deepEqual(planRuns(plan, (id) => id === 'ev:a', Date.parse(t(16))), [], 'ended runs are history');
});

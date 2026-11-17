/**
 * (#1321) The Today list's rows from sensor.sem_charging_state today_plan.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { todayRows, dayIndex, KINDS } from '../src/util/next-today-rows.js';

const now = new Date(2026, 10, 7, 12, 40).getTime();
const at = (h, m = 0, d = 0) => new Date(2026, 10, 7 + d, h, m).toISOString();

const LABEL_PEAK = 'plan_solar_peak';
const LABEL_CHEAP = 'plan_cheap_start';
const DETAIL_CHEAP = 'plan_cheap_detail';

test('rows keep the backend order, drop the now anchor and carry their keys', () => {
    const rows = todayRows({ today_plan: [
        { when: at(12, 40), kind: 'now', label: 'plan_now', values: { time: '12:40' } },
        { when: at(13), kind: 'cheap_start', label: LABEL_CHEAP, detail: DETAIL_CHEAP,
          values: { end: '15:00', price: '0.19', currency: 'CHF' } },
        { when: at(12, 55), kind: 'solar_peak', label: LABEL_PEAK, values: { kwh: '6.8' } },
    ] }, { now });
    assert.deepEqual(rows.map((r) => r.kind), ['solar_peak', 'cheap_start']);
    assert.equal(rows[0].icon, KINDS.solar_peak.icon);
    assert.equal(rows[0].color, 'solar');
    assert.equal(rows[0].label, LABEL_PEAK);
    assert.equal(rows[0].detail, null);
    assert.equal(rows[1].detail, DETAIL_CHEAP);
    assert.deepEqual(rows[1].values, { end: '15:00', price: '0.19', currency: 'CHF' });
    assert.equal(rows[1].day, 0);
});

test('Min reached after the charge-by deadline is late', () => {
    const rows = todayRows({ today_plan: [
        { when: at(7, 0, 1), kind: 'ev_deadline', label: 'plan_ev_deadline' },
        { when: at(8, 30, 1), kind: 'ev_min_reached', label: 'plan_ev_min_reached', values: {} },
    ] }, { now });
    assert.equal(rows[0].kind, 'ev_deadline');
    assert.equal(rows[1].late, true);
    assert.equal(rows[0].late, false);
    assert.equal(rows[1].day, 1, 'tomorrow');
});

test('Min reached before the deadline is on time', () => {
    const rows = todayRows({ today_plan: [
        { when: at(4, 30, 1), kind: 'ev_min_reached', label: 'plan_ev_min_reached' },
        { when: at(7, 0, 1), kind: 'ev_deadline', label: 'plan_ev_deadline' },
    ] }, { now });
    assert.equal(rows.find((r) => r.kind === 'ev_min_reached').late, false);
});

test('an unknown kind draws as a device run; bad rows are dropped', () => {
    const rows = todayRows({ today_plan: [
        { when: at(14), kind: 'something_new', label: 'x' },
        { when: 'nope', kind: 'solar_peak', label: LABEL_PEAK },
        null, 'junk',
    ] }, { now });
    assert.equal(rows.length, 1);
    assert.equal(rows[0].icon, KINDS.device_run.icon);
    assert.equal(rows[0].until, null);
});

test('no plan, no rows', () => {
    assert.deepEqual(todayRows({}), []);
    assert.deepEqual(todayRows(null), []);
    assert.deepEqual(todayRows({ today_plan: 'x' }), []);
});

test('dayIndex counts local calendar days, capped at later', () => {
    assert.equal(dayIndex(new Date(2026, 10, 7, 23, 59).getTime(), now), 0);
    assert.equal(dayIndex(new Date(2026, 10, 8, 0, 1).getTime(), now), 1);
    assert.equal(dayIndex(new Date(2026, 10, 9, 0, 1).getTime(), now), 2);
    assert.equal(dayIndex(new Date(2026, 10, 12).getTime(), now), 2);
    assert.equal(dayIndex(new Date(2026, 10, 6).getTime(), now), 0, 'the past reads as today');
});

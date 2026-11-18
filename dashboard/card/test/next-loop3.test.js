// (#1321) review loop 3: repeats merge, one rule for "on", runs per line.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mergeRepeats } from '../src/util/why-rows.js';
import { runningNow } from '../src/util/next-devices.js';
import { whyLines } from '../src/util/plan-why.js';

const rec = (time, nw, over = {}) => ({ time, device_kind: 'battery', device_id: 'b1', new: nw, reason_code: 'battery_car_below_floor', ...over });

test('a battery limit that swings is one row with the count and the range', () => {
    const rows = mergeRepeats([rec('08:34', 'limit_discharge 1500 W'), rec('08:33', 'limit_discharge 1750 W'), rec('08:32', 'limit_discharge 2000 W'),
        rec('08:31', 'charge 8 A', { device_kind: 'charger', device_id: 'c1' })]);
    assert.equal(rows.length, 2);
    assert.deepEqual([rows[0].count, rows[0].lo, rows[0].hi, rows[0].unit, rows[0].verb], [3, 1500, 2000, 'W', 'limit_discharge']);
    assert.equal(rows[0].time, '08:34', 'at the place of the newest');
});

test('different devices, commands or reasons never merge; a lone record stays', () => {
    const rows = mergeRepeats([rec('3', 'limit_discharge 1500 W'), rec('2', 'limit_discharge 1700 W', { reason_code: 'other' }),
        rec('1', 'limit_discharge 900 W', { device_id: 'b2' }), rec('0', 'off')]);
    assert.equal(rows.length, 4);
    assert.ok(rows.every((r) => !r.count));
});

test('one rule for on: switched on, active, or drawing power', () => {
    assert.equal(runningNow({ is_on: true }), true);
    assert.equal(runningNow({ is_active: true }), false, 'only is_on counts: surplus rows publish it');
    assert.equal(runningNow({ is_on: true }, null, 'unavailable'), false, 'an unavailable switch is unknown, not on');
    assert.equal(runningNow({ is_on: true }, 500, 'unavailable'), true, 'real power still counts');
    assert.equal(runningNow({}, 500), true);
    assert.equal(runningNow({}, 3), false);
    assert.equal(runningNow(null, null), false);
});

test('a why line names each run, so a gap shows, and sums their kWh', () => {
    const t = (h) => `2026-11-19T${String(h).padStart(2, '0')}:00:00+01:00`;
    const plan = { blocks: [{ id: 'ev:a', start: t(1), end: t(2), power_w: 3000 }, { id: 'ev:a', start: t(4), end: t(5), power_w: 2000 }],
        demands: [{ id: 'ev:a', planned_kwh: 5, why: { code: 'cheapest_hours', params: { from: t(1), to: t(5) } } }] };
    const line = whyLines(plan, Date.parse(t(0)))[0];
    assert.equal(line.runs.length, 2);
    assert.equal(Math.round(line.kwh * 10) / 10, 5);
});

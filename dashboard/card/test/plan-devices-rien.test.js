/**
 * (#1321) Rien's review, the parts that need no new engine data: the "Why
 * this plan" lines, the battery at the end, the charge-plan chip, the
 * reserve above the floor, each battery's own row, and the phone fold.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { whyLines, batteryEndPct, WHY_LINES_MAX } from '../src/util/plan-why.js';
import { chargePlanSummary } from '../src/util/charger-questions.js';
import { batteryFloorPct, kwhAboveFloor, batteryUnits } from '../src/util/battery-questions.js';
import { defaultOpen, zonesModel, weekdaySummary, PHONE_MAX_PX } from '../src/util/next-devices.js';

const NOW = Date.parse('2026-11-13T21:00:00+01:00');
const blk = (id, s, e, w, reason = '', params = {}) => ({ id, start: s, end: e, power_w: w, reason, reason_params: params });

test('why lines: one per planned device, earliest first, merged windows, the house draw left out', () => {
    const plan = { blocks: [
        blk('ev:keba', '2026-11-14T02:00:00+01:00', '2026-11-14T03:00:00+01:00', 4000, 'before_deadline', { deadline: '2026-11-14T07:00:00+01:00' }),
        blk('ev:keba', '2026-11-14T00:00:00+01:00', '2026-11-14T01:00:00+01:00', 4000, 'cheapest_hours'),
        blk('comfort:hot_water', '2026-11-14T04:00:00+01:00', '2026-11-14T05:00:00+01:00', 3000, 'keep_at'),
        blk('battery_out', '2026-11-13T21:00:00+01:00', '2026-11-14T06:00:00+01:00', 500),
        blk('ev:old', '2026-11-13T18:00:00+01:00', '2026-11-13T19:00:00+01:00', 4000),   // past
    ], not_scheduled: [{ id: 'load:towel', why: 'no_runtime_need', label: 'Towel' }] };
    const lines = whyLines(plan, NOW);
    assert.deepEqual(lines.map((l) => l.id), ['ev:keba', 'comfort:hot_water', 'load:towel']);
    assert.equal(lines[0].reason, 'cheapest_hours', 'the reason of the first block of the window');
    assert.equal(Date.parse(lines[0].start), Date.parse('2026-11-14T00:00:00+01:00'));
    assert.equal(Date.parse(lines[0].end), Date.parse('2026-11-14T03:00:00+01:00'));
    assert.ok(Math.abs(lines[0].kwh - 8) < 1e-9);
    assert.equal(lines[2].why, 'no_runtime_need');
    assert.equal(lines[2].start, '');
});

test('why lines: never more than four; the engine\'s own lines win when published', () => {
    const many = { blocks: [1, 2, 3, 4, 5, 6].map((i) => blk('load:l' + i, `2026-11-14T0${i}:00:00+01:00`, `2026-11-14T0${i}:30:00+01:00`, 1000)) };
    assert.equal(whyLines(many, NOW).length, WHY_LINES_MAX);
    const own = { why_lines: [{ id: 'ev:keba', start: 'a', end: 'b', code: 'before_deadline', params: { deadline: 'x' }, kwh: 7 }], blocks: many.blocks };
    assert.deepEqual(whyLines(own, NOW), [{ id: 'ev:keba', start: 'a', end: 'b', reason: 'before_deadline', params: { deadline: 'x' }, why: '', kwh: 7, label: '' }]);
    assert.deepEqual(whyLines(null, NOW), []);
});

test('battery at the end: only a real percentage from the plan', () => {
    assert.equal(batteryEndPct({ battery_end_soc_pct: 42.4 }), 42.4);
    for (const v of [undefined, null, '', 'x', -1, 101]) assert.equal(batteryEndPct({ battery_end_soc_pct: v }), null);
    assert.equal(batteryEndPct(null), null);
});

test('charge plan chip: one weekday run reads "07:00 · 20–100 kWh · Mon–Sun"', () => {
    const day = (i) => ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][i];
    const runs = weekdaySummary({}, '07:00');
    assert.deepEqual(chargePlanSummary({ chargeBy: '07:00', min: 20, max: 100, unit: 'kWh', runs, dayName: day }),
        { time: '07:00', range: '20–100 kWh', days: 'Mon–Sun' });
    const two = weekdaySummary({ sat: '09:00', sun: '09:00' }, '07:00');
    const s = chargePlanSummary({ chargeBy: '07:00', min: 60, max: 80, unit: '%', runs: two, dayName: day });
    assert.equal(s.days, 'Mon–Fri 07:00, Sat–Sun 09:00');
    assert.equal(s.range, '60–80 %');
    assert.equal(s.time, '07:00');
    assert.deepEqual(chargePlanSummary({}), { time: '', range: '', days: '' });
});

test('reserve: the plan\'s own floor wins, then the reserve setting; kWh above it', () => {
    const st = { 'number.sem_battery_reserve_soc': { state: '20' } };
    assert.equal(batteryFloorPct(st, { battery_floor_pct: 25 }), 25);
    assert.equal(batteryFloorPct(st, {}), 20);
    assert.equal(batteryFloorPct({}, {}), null);
    assert.ok(Math.abs(kwhAboveFloor(28, 20, 15) - 1.2) < 1e-9);
    assert.equal(kwhAboveFloor(15, 20, 15), 0, 'below the floor is nothing, never negative');
    assert.equal(kwhAboveFloor(null, 20, 15), null);
    assert.equal(kwhAboveFloor(28, 20, 0), null);
    const z = zonesModel({ soc: 28, priority: 30, buffer: 70, autoStart: 90, floor: null, reserve: 20 });
    assert.deepEqual(z.marks.map((m) => m.key), ['reserve', 'priority', 'buffer', 'auto']);
});

test('each battery: its own level and power, kW read as kW, an unknown unit skipped', () => {
    const st = {
        'sensor.sem_battery_b1_soc': { state: '65' }, 'sensor.sem_battery_b1_power': { state: '-750', attributes: { unit_of_measurement: 'W' } },
        'sensor.sem_battery_b1_status': { state: 'Discharging' },
        'sensor.sem_battery_b2_soc': { state: '40' }, 'sensor.sem_battery_b2_power': { state: '0.5', attributes: { unit_of_measurement: 'kW' } },
    };
    assert.deepEqual(batteryUnits(st, ['b1', 'b2', 'b3']), [
        { bid: 'b1', soc: 65, powerW: -750, status: 'Discharging' },
        { bid: 'b2', soc: 40, powerW: 500, status: '' },
    ]);
});

test('devices on a phone start folded; on a wide screen chargers and batteries open', () => {
    for (const type of ['charger', 'battery', 'load']) assert.equal(defaultOpen(type, true), false);
    assert.equal(defaultOpen('charger', false), true);
    assert.equal(defaultOpen('battery', false), true);
    assert.equal(defaultOpen('load', false), false);
    assert.equal(PHONE_MAX_PX, 720);
});

test('the plan timeline never forces a width wider than a phone', () => {
    const base = readFileSync(new URL('../src/base/sem-next-base.js', import.meta.url), 'utf8');
    assert.doesNotMatch(base, /min-width:\s*600px/);
    assert.match(base, /\.lanes svg \{[^}]*max-width: 100%/);
});

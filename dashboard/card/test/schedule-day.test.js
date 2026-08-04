import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
    getScheduleForDay,
    getPlanWindowForDay,
    getSolarIntensityForDay,
} from '../src/util/schedule-day.js';


test('tomorrow tariff never reuses today data and is marked preliminary when absent', () => {
    const attrs = {
        schedule_today: [{ start: '01:00', end: '02:00', level: 'cheap' }],
        schedule_tomorrow: [],
        schedule_tomorrow_status: 'preliminary',
    };

    const result = getScheduleForDay(attrs, 'tomorrow', 'expensive');

    assert.equal(result.status, 'preliminary');
    assert.equal(result.blocks.length, 1);
    assert.equal(result.blocks[0].level, 'expensive');
    assert.equal(result.blocks[0].isFallback, true);
});


test('tomorrow tariff uses published blocks and final status', () => {
    const attrs = {
        schedule_today: [{ start: '01:00', end: '02:00', level: 'cheap' }],
        schedule_tomorrow: [
            { start: '17:00', end: '19:00', level: 'expensive', avg_price: 1.23 },
        ],
        schedule_tomorrow_status: 'final',
    };

    const result = getScheduleForDay(attrs, 'tomorrow', 'normal');

    assert.equal(result.status, 'final');
    assert.deepEqual(result.blocks.map(block => block.level), ['expensive']);
    assert.equal(result.blocks[0].avgPrice, 1.23);
});


test('tomorrow EV plan clips timestamps to tomorrow calendar day', () => {
    const day = new Date('2026-05-29T00:00:00');
    const rows = [
        { kind: 'ev_charge_start', when: '2026-05-28T23:00:00' },
        { kind: 'ev_min_reached', when: '2026-05-29T02:00:00', values: { kwh: '8.0' } },
        { kind: 'ev_deadline', when: '2026-05-29T07:00:00' },
    ];

    const result = getPlanWindowForDay(rows, day);

    assert.deepEqual(result.plan, [{ start: 0, end: 2 / 24, kwh: '8.0' }]);
    assert.equal(result.deadlineFrac, 7 / 24);
});


test('solar intensity uses the selected day forecast', () => {
    assert.equal(getSolarIntensityForDay('12:00', 0.2), null);
    const curve = getSolarIntensityForDay('13:00', 12.5);
    assert.equal(curve.length, 24);
    assert.equal(Math.max(...curve), 1);
    assert.ok(curve[13] > curve[7]);
});

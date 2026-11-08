/**
 * (#1321) The SEM Next screens' pure helpers: the lead line, the timeline
 * geometry and the source freshness.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { nowLead, fill, planLead, kwhOf } from '../src/util/next-lead.js';
import { laneModel, nextClock } from '../src/util/next-timeline.js';
import { freshness, ageLabel, sourceRows, newestUpdate } from '../src/util/next-freshness.js';

const t = (k) => ({
    next_lead_car_grid: 'Night. The car charges from the grid at {amps} A, {kwh} kWh to go, done by {time}.',
    next_sub_battery_rests: 'Battery at {soc} %, below the floor of {floor} %.',
    next_sub_sun_at: 'Sun at {time}.',
    next_sub_two: '{a} {b}',
}[k] || k);

test('a night grid charge names amps, kWh and the deadline', () => {
    const r = nowLead({ night: true, observer: false, solarW: 0, gridW: -4461, batteryW: 0,
        car: { present: true, charging: true, powerW: 3120, amps: 8, remainingKwh: 6.8, targetTime: '07:00' },
        battery: { soc: 20, floorPct: 91.4 }, sunAt: '07:40' });
    assert.equal(r.prefix, 'next_lead_night');
    assert.equal(fill(t(r.main.key), r.main.params, t),
        'Night. The car charges from the grid at 8 A, 6.8 kWh to go, done by 07:00.');
    assert.equal(fill(t(r.sub.key), r.sub.params, t),
        'Battery at 20 %, below the floor of 91 %. Sun at 07:40.');
});

test('observer mode changes the prefix, not the facts', () => {
    const r = nowLead({ night: true, observer: true, solarW: 0, gridW: -200, batteryW: 0, car: null, battery: null });
    assert.equal(r.prefix, 'next_lead_observing');
    assert.equal(r.main.key, 'next_lead_house_on');
    assert.equal(r.main.params.source, 'next_src_grid');
});

test('a missing car or battery leaves the line without them', () => {
    const r = nowLead({ night: false, observer: false, solarW: 3200, gridW: 900, batteryW: 0, car: null, battery: null, nightStart: '17:31' });
    assert.equal(r.main.key, 'next_lead_sun_export');
    assert.equal(r.sub.key, 'next_sub_night_at');
});

test('kwhOf integrates power over the block span', () => {
    const blocks = [{ id: 'ev:a', start: '2026-11-05T20:00:00+01:00', end: '2026-11-05T22:00:00+01:00', power_w: 4000 },
                    { id: 'load:b', start: '2026-11-05T20:00:00+01:00', end: '2026-11-05T21:00:00+01:00', power_w: 1000 }];
    assert.equal(kwhOf(blocks, (id) => id.startsWith('ev:')), 8);
    assert.equal(planLead({ computed_at: 'x', blocks }, {}).main.key, 'next_plan_car');
    assert.equal(planLead({}, {}).main.key, 'next_plan_none');
});

test('nextClock rolls a passed time to tomorrow', () => {
    const ref = new Date(2026, 10, 5, 20, 55);
    assert.equal(nextClock('07:00', ref).getDate(), 6);
    assert.equal(nextClock('23:00', ref).getDate(), 5);
    assert.equal(nextClock('nope', ref), null);
});

test('the timeline clips blocks to the axis and makes one lane per charger', () => {
    const now = new Date(2026, 10, 5, 20, 55);
    const iso = (h, m = 0) => new Date(2026, 10, 5 + Math.floor(h / 24), h % 24, m).toISOString();
    const plan = {
        computed_at: iso(20, 30), fits: true, total_cost: 2.88, takeover: iso(18, 29),
        slots: [{ start: iso(20), end: iso(21), price: 0.36 }, { start: iso(21), end: iso(22), price: 0.36 }],
        blocks: [{ id: 'ev:ev_charger', start: iso(20, 30), end: iso(25, 40), power_w: 4952 },
                 { id: 'ev:ev_charger', start: iso(60), end: iso(61), power_w: 1000 }],
        demands: [{ id: 'ev:ev_charger', status: 'fits' }],
    };
    const m = laneModel({ now, plan, chargers: [{ id: 'ev_charger', name: 'Car' }], loads: [],
        nightStart: '17:31', nightEnd: '07:11', forecastTomorrowKwh: 11.9 });
    const car = m.lanes.find(l => l.id === 'ev:ev_charger');
    assert.ok(car, 'a charger lane');
    assert.equal(car.blocks.length, 1, 'the block two days out is dropped');
    assert.equal(car.blocks[0].x0, 0, 'a running block starts at now');
    assert.ok(car.blocks[0].x1 > 0.19 && car.blocks[0].x1 < 0.2, 'ends 01:40 = 4.75 h of 24');
    assert.equal(m.price, null, 'one price is no price lane');
    assert.ok(m.sun && m.sun.x0 > 0.42 && m.sun.x1 > m.sun.x0, 'sun from 07:11 tomorrow');
    assert.equal(m.sun.kwh, 11.9);
    assert.ok(m.lanes[0].blocks.length === 1, 'grid from the takeover to the night end');
});

test('a price lane appears when prices differ', () => {
    const now = new Date(2026, 10, 5, 20, 0);
    const iso = (h) => new Date(2026, 10, 5, h).toISOString();
    const m = laneModel({ now, plan: { slots: [{ start: iso(20), end: iso(21), price: 0.2, cheap: true }, { start: iso(21), end: iso(22), price: 0.4 }] },
        chargers: [], loads: [], nightStart: '17:31', nightEnd: '07:00' });
    assert.equal(m.price.length, 2);
    assert.equal(m.price[0].cheap, true);
});

test('freshness reads last_updated and treats unavailable as off', () => {
    const now = Date.parse('2026-11-05T20:00:00Z');
    const at = (s) => new Date(now - s * 1000).toISOString();
    assert.equal(freshness({ state: '12', last_updated: at(5) }, now), 'ok');
    // an unchanged value is still alive: no age rule without a declared limit
    assert.equal(freshness({ state: '0', last_updated: at(9000) }, now), 'ok');
    const lim = { okS: 120, oldS: 1800 };
    assert.equal(freshness({ state: '12', last_updated: at(600) }, now, lim), 'old');
    assert.equal(freshness({ state: '12', last_updated: at(9000) }, now, lim), 'off');
    assert.equal(freshness({ state: 'unavailable', last_updated: at(1) }, now), 'off');
    assert.equal(freshness(undefined, now), 'missing');
    assert.equal(ageLabel(12), '12 s');
    assert.equal(ageLabel(240), '4 min');
    const rows = sourceRows({ 'sensor.sem_solar_power': { state: '0', last_updated: at(2) } }, now);
    assert.equal(rows.length, 1);
    assert.equal(rows[0].state, 'ok');
});

test('a load without a block gets no lane; chargers and the battery are never listed as loads', () => {
    const now = new Date(2026, 10, 5, 20, 55);
    const iso = (h, m = 0) => new Date(2026, 10, 5 + Math.floor(h / 24), h % 24, m).toISOString();
    const plan = {
        computed_at: iso(20, 30), fits: true, takeover: iso(18, 29), slots: [],
        blocks: [{ id: 'load:boiler', start: iso(23), end: iso(24), power_w: 2000 }],
        demands: [{ id: 'load:boiler', status: 'fits' }],
    };
    const m = laneModel({ now, plan,
        chargers: [{ id: 'ev_charger', name: 'Car' }],
        loads: [{ id: 'boiler', name: 'Boiler' }, { id: 'pump', name: 'Pump' }, { id: 'ev_charger', name: 'Car' }, { id: 'battery:primary', name: 'Home battery' }],
        nightStart: '17:31', nightEnd: '07:11' });
    const ids = m.lanes.map(l => l.id);
    assert.ok(ids.includes('ev:ev_charger'), 'the charger keeps its lane while idle');
    assert.ok(ids.includes('load:boiler'), 'a planned load has a lane');
    assert.ok(!ids.includes('load:pump'), 'an unplanned load has none');
    assert.ok(!ids.includes('load:ev_charger') && !ids.includes('load:battery:primary'), 'no duplicates');
});

test('updated time: the newest live power reading, not solar held at 0', () => {
    const st = {
        'sensor.sem_solar_power': { state: '0', last_updated: '2026-11-08T17:31:00Z' },
        'sensor.sem_grid_power': { state: '-4200', last_updated: '2026-11-08T18:09:00Z' },
        'sensor.sem_battery_power': { state: 'unavailable', last_updated: '2026-11-08T18:09:30Z' },
    };
    assert.equal(newestUpdate(st), '2026-11-08T18:09:00.000Z');
    assert.equal(newestUpdate({}), null);
});

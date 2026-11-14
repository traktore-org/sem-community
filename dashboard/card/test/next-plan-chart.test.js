/**
 * (#1321) The Plan chart's model: one clock for sun, price and plan, in the
 * home's time zone, with nothing invented.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
    zonedMidnight, chartWindow, chartTicks, sunModel, priceModel, priceAt, planRows, focusBlock, runningAt,
} from '../src/util/next-plan-chart.js';

const TZ = 'Europe/Zurich';
const NOW = Date.parse('2026-11-08T22:54:00+01:00');
const iso = (s) => new Date(Date.parse(s)).toISOString();

test('windows follow the home clock: today, next 24 h, tomorrow', () => {
    assert.equal(zonedMidnight(NOW, TZ), Date.parse('2026-11-08T00:00:00+01:00'));
    assert.deepEqual(chartWindow(NOW, 'today', TZ), { start: Date.parse('2026-11-08T00:00:00+01:00'), end: Date.parse('2026-11-09T00:00:00+01:00') });
    assert.deepEqual(chartWindow(NOW, 'tomorrow', TZ), { start: Date.parse('2026-11-09T00:00:00+01:00'), end: Date.parse('2026-11-10T00:00:00+01:00') });
    const n = chartWindow(NOW, 'next', TZ);
    assert.equal(n.start, Date.parse('2026-11-08T20:00:00+01:00'));
    assert.equal(n.end - n.start, 24 * 3600e3);
    // a DST day is 23 h long
    const dst = Date.parse('2026-03-29T12:00:00+02:00');
    const w = chartWindow(dst, 'today', TZ);
    assert.equal(w.end - w.start, 23 * 3600e3);
});

test('ticks sit on the home clock and mark midnight', () => {
    const t = chartTicks(chartWindow(NOW, 'next', TZ), TZ, 6);
    assert.deepEqual(t.map((x) => x.label), ['00', '06', '12', '18']);
    assert.ok(t[0].midnight);
});

test('sun: past hours measured, the rest from the forecast; 30-min periods; no forecast draws nothing', () => {
    const win = chartWindow(NOW, 'today', TZ);
    const actual = [
        { t: Date.parse('2026-11-08T10:00:00+01:00'), w: 1000 },
        { t: Date.parse('2026-11-08T11:00:00+01:00'), w: 2000 },
        { t: Date.parse('2026-11-08T22:00:00+01:00'), w: 0 },   // not complete at 22:54: dropped
    ];
    const forecast = { [iso('2026-11-08T11:00:00+01:00')]: 999, [iso('2026-11-09T11:00:00+01:00')]: 1500, [iso('2026-11-09T11:30:00+01:00')]: 1500 };
    const sm = sunModel({ win, nowMs: NOW, actual, forecast });
    assert.deepEqual(sm.points.map((p) => [p.actual, p.kwh]), [[true, 1], [true, 2]]);   // tomorrow is outside today, 11:00 forecast loses to the measure
    assert.equal(sm.totalKwh, 3);
    assert.equal(sm.hasForecast, false);
    const tmw = sunModel({ win: chartWindow(NOW, 'tomorrow', TZ), nowMs: NOW, actual, forecast });
    assert.deepEqual(tmw.points.map((p) => [p.actual, p.kw, p.kwh]), [[false, 3, 1.5], [false, 3, 1.5]]);
    assert.equal(tmw.totalKwh, 3);
    assert.equal(tmw.peak.kw, 3);
    const none = sunModel({ win: chartWindow(NOW, 'tomorrow', TZ), nowMs: NOW, actual: [], forecast: {} });
    assert.deepEqual(none.points, []);
    assert.equal(none.peak, null);
});

test('price: flat says one price; dynamic steps from 15-min slots; gaps stay unknown', () => {
    const win = chartWindow(NOW, 'next', TZ);
    const flat = priceModel({ win, tz: TZ, nowMs: NOW, slots: [{ start: iso('2026-11-08T23:00:00+01:00'), end: iso('2026-11-09T00:00:00+01:00'), price: 0.36 }], isDynamic: false, level: 'flat', todayAvg: 0.36 });
    assert.deepEqual([flat.flat, flat.price, flat.steps.length], [true, 0.36, 0]);
    assert.equal(priceAt(flat, NOW), 0.36);
    const upcoming = [];
    for (let i = 0; i < 8; i++) upcoming.push({ t: iso(new Date(Date.parse('2026-11-08T23:00:00+01:00') + i * 900e3).toISOString()), price: i < 4 ? 0.2 : 0.4 });
    const schedule = [{ start: '20:00', end: '23:00', avg_price: 0.3 }];
    const dyn = priceModel({ win, tz: TZ, nowMs: NOW, upcoming, schedule, isDynamic: true, level: 'cheap' });
    assert.equal(dyn.flat, false);
    assert.deepEqual(dyn.steps.map((s) => s.p), [0.3, 0.2, 0.4]);
    assert.equal(dyn.min, 0.2); assert.equal(dyn.max, 0.4);
    assert.equal(dyn.gaps.length, 1);
    assert.equal(dyn.gaps[0].s, Date.parse('2026-11-09T01:00:00+01:00'));
    assert.equal(priceAt(dyn, Date.parse('2026-11-08T23:10:00+01:00')), 0.2);
    assert.equal(priceAt(dyn, Date.parse('2026-11-09T05:00:00+01:00')), null);
});

test('plan rows: car per charger, battery in and out, house from the grid, loads; merged and dimmed', () => {
    const t = (h) => iso(`2026-11-0${h < 12 ? 9 : 8}T${String(h % 24).padStart(2, '0')}:00:00+01:00`);
    const slots = [
        { start: t(22), end: t(23), home_w: 600, home_grid_w: 0 },
        { start: t(23), end: iso('2026-11-09T00:00:00+01:00'), home_w: 600, home_grid_w: 0 },
        { start: iso('2026-11-09T00:00:00+01:00'), end: t(1), home_w: 500, home_grid_w: 500 },
    ];
    const plan = {
        slots, batt_runs: [[0, 1]],
        blocks: [
            { id: 'ev:keba', start: t(23), end: iso('2026-11-09T00:00:00+01:00'), power_w: 4000 },
            { id: 'ev:keba', start: iso('2026-11-09T00:00:00+01:00'), end: t(1), power_w: 4000 },
            { id: 'arbitrage:battery', start: t(2), end: t(3), power_w: 2000 },
            { id: 'load:boiler', start: t(4), end: t(5), power_w: 2000 },
        ],
    };
    const rows = planRows({ win: chartWindow(NOW, 'next', TZ), nowMs: NOW, plan, names: { charger: (c) => 'Car ' + c, load: (l) => 'L ' + l } });
    assert.deepEqual(rows.map((r) => [r.kind, r.label]), [['ev', 'Car keba'], ['battery_in', ''], ['battery_out', ''], ['grid', ''], ['load', 'L boiler']]);
    assert.equal(rows[0].blocks.length, 1);                 // two touching blocks merge
    assert.equal(rows[0].blocks[0].kwh, 8);
    assert.equal(rows[2].blocks[0].kwh, 1.2);               // battery to house: the house's draw over the run
    assert.equal(rows[2].blocks[0].run, true);
    assert.equal(rows[3].blocks[0].kwh, 0.5);
    assert.equal(focusBlock(rows, NOW).row.kind, 'battery_out');
    assert.equal(focusBlock(rows, NOW, 'ev:keba:' + Date.parse(t(23))).row.kind, 'ev');
    assert.deepEqual(runningAt(rows, Date.parse('2026-11-08T23:30:00+01:00')).map((r) => r.kind), ['ev', 'battery_out']);
    assert.deepEqual(planRows({ win: chartWindow(NOW, 'next', TZ), nowMs: NOW, plan: null }), []);
});

test('past hours take the price the tariff really read, before the schedule average', async () => {
    const { priceModel } = await import('../src/util/next-plan-chart.js');
    const tz = 'Europe/Zurich';
    const now = Date.parse('2026-11-08T23:56:00+01:00');
    const win = { start: Date.parse('2026-11-08T21:00:00+01:00'), end: Date.parse('2026-11-09T21:00:00+01:00') };
    const pm = priceModel({ win, tz, nowMs: now, isDynamic: true, level: 'cheap',
        past: [{ t: Date.parse('2026-11-08T21:00:00+01:00'), p: 0.31 }, { t: Date.parse('2026-11-08T22:00:00+01:00'), p: 0.27 }],
        schedule: [{ start: '15:15', end: '23:00', avg_price: 0.2925 }, { start: '23:00', end: '24:00', avg_price: 0.2202 }],
        upcoming: [{ t: '2026-11-09T00:00:00+01:00', price: 0.21 }] });
    const at = (iso) => pm.steps.find((s) => s.s <= Date.parse(iso) && Date.parse(iso) < s.e)?.p;
    assert.equal(at('2026-11-08T21:30:00+01:00'), 0.31);
    assert.equal(at('2026-11-08T22:30:00+01:00'), 0.27);
    assert.equal(at('2026-11-08T23:30:00+01:00'), 0.2202);   // no reading yet: the schedule fills
    assert.equal(at('2026-11-09T00:05:00+01:00'), 0.21);
});

test('an odd first forecast key does not shrink the step: the curve stays one run', async () => {
    const { sunModel } = await import('../src/util/next-plan-chart.js');
    const win = { start: Date.parse('2026-11-09T00:00:00+01:00'), end: Date.parse('2026-11-10T00:00:00+01:00') };
    const fc = { '2026-11-09T07:17:36+01:00': 24, '2026-11-09T07:30:00+01:00': 176, '2026-11-09T08:00:00+01:00': 299, '2026-11-09T08:30:00+01:00': 425 };
    const sm = sunModel({ win, nowMs: win.start, forecast: fc });
    for (let i = 1; i < sm.points.length; i++) assert.equal(sm.points[i].s, sm.points[i - 1].e, 'periods touch');
    assert.equal(sm.points[sm.points.length - 1].e - sm.points[sm.points.length - 1].s, 30 * 60e3);
});

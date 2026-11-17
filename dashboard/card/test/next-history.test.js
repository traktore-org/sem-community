/**
 * (#1321) The Insights screen's history helpers: the period windows, the
 * reducers from recorder rows to bucket numbers, the SVG geometry, and the
 * one fetch with its five-minute cache (websocket mocked).
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
    bucketsFor, fetchPeriodFor, nearestIndex, diffCumulative, bucketValues, sunCurve,
    smooth, stackModel, lineModel, fetchSeries, clearSeriesCache,
} from '../src/util/next-history.js';

const NOW = new Date(2026, 10, 7, 12, 40);   // Saturday 07.11.2026 12:40 local

test('today is 24 hour buckets that end now, with the running hour marked', () => {
    const b = bucketsFor('day', NOW);
    assert.equal(b.period, 'hour');
    assert.equal(b.n, 24);
    assert.equal(b.start.getHours(), 0);
    assert.equal(b.end.getTime(), NOW.getTime());
    assert.equal(b.highlightIndex, 12);
    assert.equal(b.labels.filter(Boolean).length, 4);
});

test('yesterday is the full day before, nothing highlighted', () => {
    const b = bucketsFor('yesterday', NOW);
    assert.equal(b.start.getDate(), 6);
    assert.equal(b.spanEnd.getDate(), 7);
    assert.equal(b.end.getTime(), b.spanEnd.getTime());
    assert.equal(b.highlightIndex, -1);
});

test('the week runs Monday to Sunday with today marked; the month and year likewise', () => {
    const w = bucketsFor('week', NOW, { lang: 'en' });
    assert.equal(w.period, 'day');
    assert.equal(w.n, 7);
    assert.equal(w.start.getDay(), 1);
    assert.equal(w.highlightIndex, 5);
    assert.equal(w.labels[5], 'Sat');
    const m = bucketsFor('month', NOW);
    assert.equal(m.n, 30);
    assert.equal(m.highlightIndex, 6);
    assert.equal(m.labels[0], '1');
    const y = bucketsFor('year', NOW, { lang: 'en' });
    assert.equal(y.period, 'month');
    assert.equal(y.n, 12);
    assert.equal(y.highlightIndex, 10);
    assert.equal(y.labels[10], 'Nov');
    assert.equal(fetchPeriodFor(y, 'total'), 'day');
    assert.equal(fetchPeriodFor(y, 'mean'), 'month');
    assert.equal(fetchPeriodFor(w, 'total'), 'day');
});

test('a counter that resets gives its increments, the reset hour its own value', () => {
    assert.deepEqual(diffCumulative([1, 3, 6, 0.5, 2]), [1, 2, 3, 0.5, 1.5]);
    assert.deepEqual(diffCumulative(['x', 2]), [0, 2]);
});

test('nearestIndex snaps a row to its bucket and refuses rows outside the window', () => {
    const starts = [0, 3600e3, 7200e3];
    assert.equal(nearestIndex(3600e3 + 60e3, starts), 1);
    assert.equal(nearestIndex(-3000e3, starts), -1);
    assert.equal(nearestIndex(NaN, starts), -1);
});

test('bucketValues: hour rows of a daily counter become per-hour energy; day rows add into a month', () => {
    const day = bucketsFor('yesterday', NOW);
    const t0 = day.start.getTime();
    const rows = [0, 1, 2, 3].map((h) => ({ start: t0 + h * 3600e3, state: [0, 0.5, 1.5, 4][h] }));
    const v = bucketValues(rows, day, 'total');
    assert.deepEqual(v.slice(0, 4), [0, 0.5, 1, 2.5]);
    assert.equal(v[5], null);
    const year = bucketsFor('year', NOW);
    const days = [1, 2, 3].map((d) => ({ start: new Date(2026, 10, d).toISOString(), state: 10 }));
    const months = bucketValues(days, year, 'total');
    assert.equal(months[10], 30);
    assert.equal(months[9], null);
});

test('bucketValues: means average the rows that land in a bucket', () => {
    const day = bucketsFor('yesterday', NOW);
    const t0 = day.start.getTime();
    const rows = [{ start: t0, mean: 100 }, { start: t0 + 60e3, mean: 300 }, { start: t0 + 3600e3, mean: 50 }];
    assert.deepEqual(bucketValues(rows, day, 'mean').slice(0, 3), [200, 50, null]);
});

test('sunCurve shapes the forecast between night end and night start and keeps the total', () => {
    const c = sunCurve(24, '07:00', '17:30');
    assert.equal(c.length, 24);
    assert.equal(c[3], 0);
    assert.equal(c[20], 0);
    assert.ok(c[12] > c[8]);
    assert.ok(Math.abs(c.reduce((a, b) => a + b, 0) - 24) < 1e-9);
    assert.deepEqual(sunCurve(0, '07:00', '17:30'), new Array(24).fill(0));
    assert.deepEqual(sunCurve(5, '', '17:30'), new Array(24).fill(0));
});

test('smooth returns a line for two points and Beziers for more', () => {
    assert.equal(smooth([]), '');
    assert.equal(smooth([[0, 0], [10, 5]]), 'M0.0 0.0 L10.0 5.0');
    const d = smooth([[0, 0], [10, 5], [20, 0]]);
    assert.ok(d.startsWith('M0.0 0.0 C'));
    assert.equal((d.match(/ C/g) || []).length, 2);
});

test('stackModel stacks layers, dims every bar but the highlighted one, and knows an empty chart', () => {
    const m = stackModel([[6, 2, 0], [2, 1, 0], [4, 8, 0]], ['a', 'b', 'c'], ['Mon', 'Tue', 'Wed'], 300, 150, 1, { unit: 'kWh' });
    assert.equal(m.empty, false);
    assert.equal(m.max, 15);
    assert.deepEqual(m.sums, [12, 11, 0]);
    assert.equal(m.bars.length, 6);
    assert.equal(m.bars.find((b) => b.i === 0 && b.k === 0).opacity, 0.6);
    assert.equal(m.bars.find((b) => b.i === 1 && b.k === 0).opacity, 1);
    assert.equal(m.bars.filter((b) => b.i === 0).at(-1).rx, 3);
    assert.equal(m.labels.find((l) => l.text === 'Tue').strong, true);
    assert.equal(m.totals.length, 2);
    assert.equal(m.grid[1].text, '15 kWh');
    assert.equal(stackModel([[0, 0]], ['a'], ['x', 'y'], 300, 150).empty, true);
    assert.equal(stackModel([], [], ['x'], 300, 150).empty, true);
});

test('lineModel skips null points, makes an area for an area series, and places the hover', () => {
    const m = lineModel([{ v: [0, 2, null, 4], color: 'c', area: true }, { v: [1, 1, 1, 1], color: 'd', dash: true }],
        400, 120, { labels: ['00', '', '', '18'], unit: 'kW', hover: 3 });
    assert.equal(m.empty, false);
    assert.equal(m.paths.length, 2);
    assert.ok(m.paths[0].area.endsWith('Z'));
    assert.equal(m.paths[1].area, null);
    assert.equal(m.paths[1].dash, true);
    assert.equal(m.xs.length, 4);
    assert.equal(m.ticks.length, 2);
    assert.equal(m.ticks[1].anchor, 'end');
    assert.equal(m.hover.i, 3);
    assert.equal(lineModel([{ v: [null, null] }], 400, 120).empty, true);
    assert.equal(lineModel([{ v: [10, 20] }], 400, 120, { max: 100 }).max, 100);
});

test('fetchSeries asks the recorder, falls back to history, and serves a repeat from memory', async () => {
    clearSeriesCache();
    const calls = [];
    const hass = { callWS: async (msg) => { calls.push(msg); return { 'sensor.a': [{ start: 1, state: 2 }] }; } };
    const r1 = await fetchSeries(hass, ['sensor.a', 'sensor.b'], 's', 'e', 'hour');
    assert.equal(calls.length, 1);
    assert.equal(calls[0].type, 'recorder/statistics_during_period');
    assert.deepEqual(calls[0].statistic_ids, ['sensor.a', 'sensor.b']);
    assert.deepEqual(r1['sensor.b'], []);
    assert.equal(r1['sensor.a'][0].state, 2);
    await fetchSeries(hass, ['sensor.a', 'sensor.b'], 's', 'e', 'hour');
    assert.equal(calls.length, 1);
    await fetchSeries(hass, ['sensor.a', 'sensor.b'], 's', 'e', 'hour', { now: Date.now() + 6 * 60e3 });
    assert.equal(calls.length, 2);

    clearSeriesCache();
    const old = { callWS: async (msg) => { calls.push(msg); if (msg.type.startsWith('recorder')) throw new Error('no'); return {}; } };
    await fetchSeries(old, ['sensor.a'], 's', 'e', 'day');
    assert.equal(calls.at(-1).type, 'history/statistics_during_period');
    assert.deepEqual(await fetchSeries({}, ['sensor.a'], 's', 'e', 'day'), {});
});

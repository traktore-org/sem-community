/** (#1024) The EV card's session list — pure helpers. */
import { test } from 'node:test';
import assert from 'node:assert';
import {
    sessionMonth, shiftMonth, rowsForMonth, monthTotals, sessionRowView, sessionsCsv,
} from '../src/util/sessions.js';

const R = (ts, end, kwh, solar, cost, min, extra = {}) => ({
    timestamp: ts, end, energy_kwh: kwh, solar_share_pct: solar, cost, currency: 'CHF',
    duration_min: min, charger_id: 'keba', ...extra,
});
const ROWS = [
    R('2026-09-30T17:52:00+02:00', '2026-09-30T18:20:00+02:00', 2.0, 88, 0.31, 28),
    R('2026-09-26T22:00:00+02:00', '2026-09-27T05:10:00+02:00', 24.6, 0, 5.66, 430),
    { timestamp: '2026-09-12T18:00:00+02:00', energy_kwh: 1.0, solar_share_pct: 50, duration_min: 20 },
    R('2026-08-31T12:00:00+02:00', '2026-08-31T13:00:00+02:00', 5.0, 100, 0, 60),
];

test('month of a row, from the string as written', () => {
    assert.equal(sessionMonth(ROWS[0]), '2026-09');
    assert.equal(sessionMonth({}), '');
});

test('months step across the year', () => {
    assert.equal(shiftMonth('2026-01', -1), '2025-12');
    assert.equal(shiftMonth('2026-12', 1), '2027-01');
    assert.equal(shiftMonth('2026-09', 0), '2026-09');
});

test('rows for a month keep their order', () => {
    assert.deepEqual(rowsForMonth(ROWS, '2026-09').map(r => r.energy_kwh), [2.0, 24.6, 1.0]);
    assert.deepEqual(rowsForMonth(ROWS, '2026-07'), []);
});

test('totals: energy-weighted solar, cost only where stored', () => {
    const t = monthTotals(rowsForMonth(ROWS, '2026-09'));
    assert.equal(t.count, 3);
    assert.equal(t.kwh, 27.6);
    // (2.0*0.88 + 0 + 1.0*0.5) / 27.6 = 8.2 %
    assert.equal(t.solarPct, 8);
    assert.equal(t.cost, 5.97);
    assert.equal(t.currency, 'CHF');
});

test('totals of old rows without cost say no cost, not zero', () => {
    assert.equal(monthTotals([ROWS[2]]).cost, null);
    assert.equal(monthTotals([]).solarPct, 0);
});

test('a row formats like the approved mockup', () => {
    const v = sessionRowView(ROWS[0], 'en');
    assert.deepEqual(v, {
        day: 'Wed 30.09', span: '17:52–18:20', kwh: '2.0', solar: '88%',
        solarHigh: true, cost: '0.31', co2: '', min: '28',
    });
});

test('solar is orange from 80 %; an old row has empty cost and no end', () => {
    assert.equal(sessionRowView(R('2026-09-01T10:00:00+02:00', null, 1, 79.6, 0, 1)).solarHigh, true);
    assert.equal(sessionRowView(R('2026-09-01T10:00:00+02:00', null, 1, 79.4, 0, 1)).solarHigh, false);
    const old = sessionRowView(ROWS[2]);
    assert.equal(old.cost, '');
    assert.equal(old.span, '18:00');
});

test('weekday follows the language', () => {
    assert.match(sessionRowView(ROWS[0], 'de').day, /^Mi\.? 30\.09$/);
});

test('CSV: the service columns, comma-safe, empty for missing', () => {
    const text = sessionsCsv([ROWS[2], R('2026-09-01T10:00:00+02:00', '', 1, 10, 0.1, 5, { charger_id: 'Garage, left' })]);
    const lines = text.trim().split('\n');
    assert.equal(lines[0], 'start,end,charger,energy_kwh,solar_share_pct,cost,currency,duration_min,energy_source,co2_kg');
    assert.equal(lines[1], '2026-09-12T18:00:00+02:00,,,1,50,,,20,,');
    assert.match(lines[2], /,"Garage, left",/);
});

test('(#1088) CO2 per session: shown with one decimal, summed only where known', () => {
    const a = { ...ROWS[0], co2_kg: 0.42 };
    const b = { ...ROWS[0], co2_kg: 1.0 };
    assert.equal(sessionRowView(a).co2, '0.4');
    assert.equal(monthTotals([a, b, ROWS[2]]).co2, 1.4);
    assert.equal(monthTotals([ROWS[2]]).co2, null);   // sessions from before
});

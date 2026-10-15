/** (#1083) The Simulation card's pure helpers. */
import { test } from 'node:test';
import assert from 'node:assert';
import {
    TAG_GLYPH, tagGlyphs, isSelectable, QUICK_PICKS, pickDays, activePick, toggleDay,
    chipDate, rowDate, money, formatDelta, formatPct, ESTIMATED, needsEst, visibleRows,
    tagTiles, totalLine, initialForm, isChanged, buildParams, canRun, minutesLeft,
    progressShare, fill, monthsOf, pickMonth, calibration, BATTERY_MODES, EV_MODES,
} from '../src/util/simulation-rows.js';

const D = (date, tags, extra = {}) => ({ date, tags, backfilled: false, selectable: true, ...extra });
const DAYS = [
    D('2026-09-01', ['sunny']),
    D('2026-09-02', ['grey', 'car']),
    D('2026-09-03', ['sunny', 'gap'], { selectable: false }),
    D('2026-09-20', ['mixed', 'cheap']),
    D('2026-10-10', ['sunny', 'car', 'negative']),
    D('2026-10-12', ['grey']),
];
const TODAY = new Date(2026, 9, 14);

test('every tag has its glyph', () => {
    assert.deepEqual(TAG_GLYPH, {
        sunny: '☀️', mixed: '⛅', grey: '☁️', car: '🚗', cheap: '💸', negative: '💸', gap: '⚠️',
    });
});

test('glyphs come sky first, then car, prices, gap; one 💸 for cheap and negative', () => {
    assert.equal(tagGlyphs(['car', 'sunny']), '☀️🚗');
    assert.equal(tagGlyphs(['cheap', 'negative', 'grey']), '☁️💸');
    assert.equal(tagGlyphs(['gap', 'mixed']), '⛅⚠️');
    assert.equal(tagGlyphs(['snow']), '');
    assert.equal(tagGlyphs(null), '');
});

test('a gap day is not selectable, by flag or by tag', () => {
    assert.equal(isSelectable(DAYS[0]), true);
    assert.equal(isSelectable(DAYS[2]), false);
    assert.equal(isSelectable(D('2026-09-04', ['gap'])), false);
    assert.equal(isSelectable(D('2026-09-04', ['sunny'], { selectable: false })), false);
    assert.equal(isSelectable(null), false);
});

test('the quick picks, in order', () => {
    assert.deepEqual(QUICK_PICKS, ['sunny', 'grey', 'car', 'last30', 'last90', 'last365', 'clear']);
});

test('all sunny skips the gap day', () => {
    assert.deepEqual(pickDays(DAYS, 'sunny', TODAY), ['2026-09-01', '2026-10-10']);
});

test('all grey and days with a car', () => {
    assert.deepEqual(pickDays(DAYS, 'grey', TODAY), ['2026-09-02', '2026-10-12']);
    assert.deepEqual(pickDays(DAYS, 'car', TODAY), ['2026-09-02', '2026-10-10']);
});

test('last 30 days: the 30 days before today', () => {
    assert.deepEqual(pickDays(DAYS, 'last30', TODAY), ['2026-09-20', '2026-10-10', '2026-10-12']);
    // 14.09 is 30 days back: in; 13.09 is not
    const edge = [D('2026-09-13', ['sunny']), D('2026-09-14', ['sunny']), D('2026-10-14', ['sunny'])];
    assert.deepEqual(pickDays(edge, 'last30', TODAY), ['2026-09-14']);
});

test('last 90 and last 365 days reach further back', () => {
    const old = [D('2025-10-20', ['grey']), D('2026-07-20', ['sunny']), ...DAYS];
    assert.deepEqual(pickDays(old, 'last90', TODAY).slice(0, 1), ['2026-07-20']);
    assert.deepEqual(pickDays(old, 'last365', TODAY).slice(0, 2), ['2025-10-20', '2026-07-20']);
});

test('a month: its selectable days; the months newest first', () => {
    assert.deepEqual(monthsOf(DAYS), ['2026-10', '2026-09']);
    assert.deepEqual(pickMonth(DAYS, '2026-09'), ['2026-09-01', '2026-09-02', '2026-09-20']);
    assert.deepEqual(monthsOf(null), []);
});

test('clear picks nothing', () => {
    assert.deepEqual(pickDays(DAYS, 'clear', TODAY), []);
    assert.deepEqual(pickDays(null, 'sunny', TODAY), []);
});

test('the active pick is the one the selection equals', () => {
    assert.equal(activePick(DAYS, new Set(['2026-10-10', '2026-09-01']), TODAY), 'sunny');
    assert.equal(activePick(DAYS, new Set(['2026-09-01']), TODAY), null);
    assert.equal(activePick(DAYS, new Set(), TODAY), null);
});

test('toggling flips a day and never adds a gap day', () => {
    let sel = toggleDay(new Set(), DAYS[0]);
    assert.deepEqual([...sel], ['2026-09-01']);
    sel = toggleDay(sel, DAYS[2]);
    assert.deepEqual([...sel], ['2026-09-01']);
    sel = toggleDay(sel, DAYS[0]);
    assert.deepEqual([...sel], []);
});

test('dates: chip and row', () => {
    assert.equal(chipDate('2026-10-13'), '13.10');
    assert.equal(rowDate('2026-10-13', 'en'), 'Tue 13.10');
    assert.match(rowDate('2026-10-12', 'de'), /^Mo\.? 12\.10$/);
    assert.equal(rowDate('nope', 'en'), 'nope');
});

test('money: two decimals, a real minus, a dash for none', () => {
    assert.equal(money(184.2), '184.20');
    assert.equal(money(-1.324), '−1.32');
    assert.equal(money(-0.001), '0.00');
    assert.equal(money(null), '—');
    assert.equal(money('x'), '—');
});

test('delta: cheaper is green with a minus, dearer orange with a plus', () => {
    assert.deepEqual(formatDelta(-1.32), { text: '−1.32', cls: 'cheaper' });
    assert.deepEqual(formatDelta(0.29), { text: '+0.29', cls: 'dearer' });
    assert.deepEqual(formatDelta(0), { text: '0.00', cls: 'same' });
    assert.deepEqual(formatDelta(0.004), { text: '0.00', cls: 'same' });
    assert.deepEqual(formatDelta(undefined), { text: '—', cls: 'same' });
});

test('percent of the actual cost', () => {
    assert.equal(formatPct(-12.4, 184.2), '−6.7 %');
    assert.equal(formatPct(5, 100), '+5.0 %');
    assert.equal(formatPct(1, 0), '');
});

test('est. goes on every simulated and difference number, never on the actual', () => {
    assert.deepEqual(ESTIMATED, ['simulated', 'delta']);
    assert.equal(needsEst('simulated'), true);
    assert.equal(needsEst('delta'), true);
    assert.equal(needsEst('actual'), false);
});

test('rows newest first, 8 shown, the rest behind "more"', () => {
    const days = Array.from({ length: 11 }, (_, i) => ({ date: `2026-09-${String(i + 1).padStart(2, '0')}` }));
    const v = visibleRows(days);
    assert.equal(v.rows.length, 8);
    assert.equal(v.more, 3);
    assert.equal(v.rows[0].date, '2026-09-11');
    assert.equal(visibleRows(days, true).rows.length, 11);
    assert.equal(visibleRows(days.slice(0, 8)).more, 0);
    assert.deepEqual(visibleRows(null), { rows: [], more: 0 });
});

test('tiles: three skies and the car always; cheap only when it ran', () => {
    const per = {
        sunny: { days: 31, actual: 184.2, simulated: 171.8, delta: -12.4 },
        mixed: { days: 0, actual: 0, simulated: 0, delta: 0 },
        grey: { days: 0, actual: 0, simulated: 0, delta: 0 },
        car: { days: 9, actual: 50, simulated: 43.9, delta: -6.1 },
        cheap: { days: 0, actual: 0, simulated: 0, delta: 0 },
    };
    const tiles = tagTiles(per, { days: 31 });
    assert.deepEqual(tiles.map(t => t.tag), ['sunny', 'mixed', 'grey', 'car']);
    assert.deepEqual(tiles[0].delta, { text: '−12.40', cls: 'cheaper' });
    assert.equal(tiles[0].of, null);
    assert.equal(tiles[1].delta, null);
    assert.equal(tiles[3].of, 31);
    assert.equal(tiles[3].days, 9);
    per.cheap = { days: 2, actual: 3, simulated: 2, delta: -1 };
    assert.equal(tagTiles(per, { days: 31 }).at(-1).tag, 'cheap');
    assert.equal(tagTiles(null, null).length, 4);
});

test('the total line', () => {
    const t = totalLine({ days: 31, actual: 184.2, simulated: 171.8, delta: -12.4,
        kwh_over_limit: 2.5, indicative_days: 3 });
    assert.equal(t.days, 31);
    assert.equal(t.actual, '184.20');
    assert.equal(t.simulated, '171.80');
    assert.deepEqual(t.delta, { text: '−12.40', cls: 'cheaper' });
    assert.equal(t.pct, '−6.7 %');
    assert.equal(t.kwhOverLimit, 2.5);
    assert.equal(t.indicativeDays, 3);
    assert.equal(totalLine(null).days, 0);
});

const DEF = { capacity_kwh: 15, reserve_pct: 20, peak_limit_kw: 11, import_rate: 0.3, export_rate: 0.1, currency: 'CHF' };

test('the form starts at the install, prices as recorded', () => {
    assert.deepEqual(initialForm(DEF), {
        capacity_kwh: 15, reserve_pct: 20, peak_limit_kw: 11,
        import_mode: 'recorded', import_rate: 0.3, export_mode: 'recorded', export_rate: 0.1,
        battery_mode: 'auto', ev_mode: 'recorded',
    });
    assert.equal(initialForm({ ...DEF, peak_limit_kw: null }).peak_limit_kw, '');
});

test('changed: a number that differs, a price set flat', () => {
    const f = initialForm(DEF);
    assert.equal(isChanged('capacity_kwh', f, DEF), false);
    assert.equal(isChanged('capacity_kwh', { ...f, capacity_kwh: '20' }, DEF), true);
    assert.equal(isChanged('reserve_pct', { ...f, reserve_pct: '20' }, DEF), false);
    assert.equal(isChanged('peak_limit_kw', { ...f, peak_limit_kw: '' }, DEF), true);
    assert.equal(isChanged('peak_limit_kw', { peak_limit_kw: '' }, { peak_limit_kw: null }), false);
    assert.equal(isChanged('import_rate', f, DEF), false);
    assert.equal(isChanged('export_rate', { ...f, export_mode: 'flat' }, DEF), true);
});

test('params for start: numbers, no peak as null, prices recorded or flat', () => {
    const f = { ...initialForm(DEF), capacity_kwh: '20', peak_limit_kw: '8', export_mode: 'flat', export_rate: '0.08' };
    assert.deepEqual(buildParams(f), {
        capacity_kwh: 20, reserve_pct: 20, peak_limit_kw: 8, import_rate: 'recorded', export_rate: 0.08,
        battery_mode: 'auto', ev_mode: 'recorded',
    });
    assert.equal(buildParams({ ...f, peak_limit_kw: '' }).peak_limit_kw, null);
    assert.equal(buildParams({ ...f, peak_limit_kw: '0' }).peak_limit_kw, null);
    assert.equal(buildParams({ ...f, import_mode: 'flat', import_rate: '' }).import_rate, 'recorded');
});

test('run needs days, a size, and nothing running', () => {
    const f = initialForm(DEF);
    assert.equal(canRun(new Set(['2026-09-01']), f, { running: false }), true);
    assert.equal(canRun(new Set(), f, null), false);
    assert.equal(canRun(new Set(['2026-09-01']), f, { running: true }), false);
    assert.equal(canRun(new Set(['2026-09-01']), { ...f, capacity_kwh: '' }, null), false);
    assert.equal(canRun(new Set(['2026-09-01']), { ...f, capacity_kwh: '0' }, null), false);
});

test('minutes left from the pace so far', () => {
    const start = Date.parse('2026-10-14T10:00:00Z');
    const st = { done: 12, total: 31, started_at: '2026-10-14T10:00:00Z' };
    assert.equal(minutesLeft(st, start + 12 * 5000), 2);      // 5 s a day, 19 left = 95 s
    assert.equal(minutesLeft(st, start + 12 * 1000), 1);      // never 0
    assert.equal(minutesLeft({ ...st, done: 0 }, start), null);
    assert.equal(minutesLeft({ ...st, done: 31 }, start), null);
    assert.equal(minutesLeft({ done: 1, total: 2 }, start), null);
});

test('progress share', () => {
    assert.equal(progressShare({ done: 12, total: 31 }).toFixed(2), '0.39');
    assert.equal(progressShare({ done: 0, total: 0 }), 0);
    assert.equal(progressShare(null), 0);
});

test('fill puts values in their holes', () => {
    assert.equal(fill('day {x} of {y}', { x: 3, y: 9 }), 'day 3 of 9');
    assert.equal(fill('{n} of {n}', { n: 2 }), '2 of 2');
    assert.equal(fill(null, {}), '');
});

test('the two mode selects: SEM\'s modes, changed when not the install\'s', () => {
    assert.deepEqual(BATTERY_MODES, ['auto', 'self_consumption', 'force_charge', 'force_discharge', 'off']);
    assert.equal(EV_MODES[0], 'recorded');
    const f = initialForm({ ...DEF, battery_mode: 'self_consumption' });
    assert.equal(isChanged('battery_mode', f, { battery_mode: 'self_consumption' }), false);
    assert.equal(isChanged('battery_mode', { ...f, battery_mode: 'off' }, { battery_mode: 'self_consumption' }), true);
    assert.equal(isChanged('ev_mode', { ...f, ev_mode: 'solar_only' }, DEF), true);
    assert.equal(buildParams({ ...f, ev_mode: 'solar_only' }).ev_mode, 'solar_only');
});

test('calibration: a run the own settings could not reproduce shows no what-if', () => {
    assert.deepEqual(calibration({ calibrated: false, calibration: { error_pct: 12.3 } }), { ok: false, pct: 12.3 });
    assert.deepEqual(calibration({ calibrated: true, calibration: { error_pct: 1.2 } }), { ok: true, pct: 1.2 });
    assert.deepEqual(calibration({}), { ok: true, pct: null });
    assert.deepEqual(calibration(null), { ok: true, pct: null });
});

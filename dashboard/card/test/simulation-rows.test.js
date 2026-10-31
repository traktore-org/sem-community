/** (#1083) The Simulation card's pure helpers. */
import { test } from 'node:test';
import assert from 'node:assert';
import {
    TAG_GLYPH, tagGlyphs, isSelectable, PERIOD_PICKS, periodOf, activePeriod, periodDays,
    chipDate, rowDate, money, formatDelta, formatPct, ESTIMATED, needsEst, visibleRows,
    tagTiles, totalLine, initialForm, isChanged, buildParams, canRun, minutesLeft,
    progressShare, fill, monthsOf, monthPeriod, calibration, periodGaps, BATTERY_MODES, EV_MODES,
    FILTERS, filterRows, totalFor, dayDetail, monthRows, energyRows, PRESETS, applyPreset,
    buildStart,
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

test('a gap day never counts as a day of the period, by flag or by tag', () => {
    assert.equal(isSelectable(DAYS[0]), true);
    assert.equal(isSelectable(DAYS[2]), false);
    assert.equal(isSelectable(D('2026-09-04', ['gap'])), false);
    assert.equal(isSelectable(D('2026-09-04', ['sunny'], { selectable: false })), false);
    assert.equal(isSelectable(null), false);
});

// (#1083) A run is one continuous period: the battery carries its charge from
// day to day. The sunny / grey / car picks are result filters now.
test('the quick periods, in order', () => {
    assert.deepEqual(PERIOD_PICKS, ['last30', 'last90', 'last365']);
});

test('last 30 days: the stored days of the 30 days before today, as one span', () => {
    assert.deepEqual(periodOf(DAYS, 'last30', TODAY), { from: '2026-09-20', to: '2026-10-12' });
    // 14.09 is 30 days back: in; 13.09 is not; today is not
    const edge = [D('2026-09-13', ['sunny']), D('2026-09-14', ['sunny']), D('2026-10-14', ['sunny'])];
    assert.deepEqual(periodOf(edge, 'last30', TODAY), { from: '2026-09-14', to: '2026-09-14' });
    assert.equal(periodOf([], 'last30', TODAY), null);
    assert.equal(periodOf(DAYS, 'sunny', TODAY), null);
});

test('last 90 and last 365 days reach further back', () => {
    const old = [D('2025-10-20', ['grey']), D('2026-07-20', ['sunny']), ...DAYS];
    assert.equal(periodOf(old, 'last90', TODAY).from, '2026-07-20');
    assert.equal(periodOf(old, 'last365', TODAY).from, '2025-10-20');
});

test('a month: its first to its last stored day; the months newest first', () => {
    assert.deepEqual(monthsOf(DAYS), ['2026-10', '2026-09']);
    assert.deepEqual(monthPeriod(DAYS, '2026-09'), { from: '2026-09-01', to: '2026-09-20' });
    assert.equal(monthPeriod(DAYS, '2026-01'), null);
    assert.deepEqual(monthsOf(null), []);
});

test('a period counts its stored days; a gap day inside is left out', () => {
    assert.equal(periodDays(DAYS, { from: '2026-09-01', to: '2026-09-20' }), 3);
    assert.equal(periodDays(DAYS, null), 0);
});

test('the active quick period is the one the period equals', () => {
    assert.equal(activePeriod(DAYS, { from: '2026-09-20', to: '2026-10-12' }, TODAY), 'last30');
    assert.equal(activePeriod(DAYS, { from: '2026-09-01', to: '2026-10-12' }, TODAY), 'last90');
    assert.equal(activePeriod(DAYS, { from: '2026-09-02', to: '2026-10-10' }, TODAY), null);
    assert.equal(activePeriod(DAYS, null, TODAY), null);
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

test('tiles: three skies and the car always; cheap only when it ran; the active one filters', () => {
    const per = {
        sunny: { days: 31, actual: 184.2, simulated: 171.8, delta: -12.4 },
        mixed: { days: 0, actual: 0, simulated: 0, delta: 0 },
        grey: { days: 0, actual: 0, simulated: 0, delta: 0 },
        car: { days: 9, actual: 50, simulated: 43.9, delta: -6.1 },
        cheap: { days: 0, actual: 0, simulated: 0, delta: 0 },
    };
    const tiles = tagTiles(per, { days: 31 }, 'car');
    assert.deepEqual(tiles.map(t => t.tag), ['sunny', 'mixed', 'grey', 'car']);
    assert.deepEqual(tiles[0].delta, { text: '−12.40', cls: 'cheaper' });
    assert.equal(tiles[0].of, null);
    assert.equal(tiles[1].delta, null);
    assert.equal(tiles[3].of, 31);
    assert.equal(tiles[3].days, 9);
    assert.deepEqual(tiles.map(t => t.on), [false, false, false, true]);
    per.cheap = { days: 2, actual: 3, simulated: 2, delta: -1 };
    assert.equal(tagTiles(per, { days: 31 }).at(-1).tag, 'cheap');
    assert.equal(tagTiles(null, null).length, 4);
    assert.deepEqual(FILTERS, ['sunny', 'mixed', 'grey', 'car', 'cheap']);
});

test('a filter shows the days of its type and their totals; none shows all', () => {
    const days = [{ date: 'a', tags: ['sunny'] }, { date: 'b', tags: ['grey', 'car'] }];
    assert.deepEqual(filterRows(days, 'grey').map(d => d.date), ['b']);
    assert.equal(filterRows(days, null).length, 2);
    assert.deepEqual(filterRows(null, 'grey'), []);
    const res = { total: { days: 2, delta: -1 }, per_tag: { grey: { days: 1, delta: -2 } } };
    assert.equal(totalFor(res, null).delta, -1);
    assert.equal(totalFor(res, 'grey').delta, -2);
    assert.deepEqual(totalFor(res, 'car'), { days: 0 });
});

test('the total line', () => {
    const t = totalLine({ days: 31, actual: 184.2, simulated: 171.8, delta: -12.4,
        kwh_over_limit: 2.5, indicative_days: 3, net_delta: -20.1 });
    assert.equal(t.days, 31);
    assert.equal(t.actual, '184.20');
    assert.equal(t.simulated, '171.80');
    assert.deepEqual(t.delta, { text: '−12.40', cls: 'cheaper' });
    assert.deepEqual(t.net, { text: '−20.10', cls: 'cheaper' });
    assert.equal(t.pct, '−6.7 %');
    assert.equal(t.kwhOverLimit, 2.5);
    assert.equal(t.indicativeDays, 3);
    assert.equal(totalLine(null).days, 0);
    assert.equal(totalLine({ days: 1 }).net, null);     // an older run: no net line
});

test('a tapped day shows grid and battery in and out, its end level and why', () => {
    const d = dayDetail({ actual_grid_import_kwh: 4.04, simulated_grid_import_kwh: 1,
        actual_end_kwh: 6, simulated_end_kwh: null, net_delta: -0.4, story: ['charge from grid 2.0 kWh at 0.20'] });
    assert.deepEqual(d.lines.map(l => l.key), ['sim_grid_in', 'sim_grid_out', 'sim_batt_in', 'sim_batt_out', 'sim_pack_end']);
    assert.deepEqual(d.lines[0], { key: 'sim_grid_in', actual: '4.0', simulated: '1.0' });
    assert.deepEqual(d.lines[4], { key: 'sim_pack_end', actual: '6.0', simulated: '—' });
    assert.deepEqual(d.net, { text: '−0.40', cls: 'cheaper' });
    assert.deepEqual(d.story, ['charge from grid 2.0 kWh at 0.20']);
    assert.equal(dayDetail(null).net, null);
});

test('months: the difference per month, bars to scale, and where it helps', () => {
    const m = monthRows([{ month: '2026-09', days: 30, net_delta: 2 }, { month: '2026-10', days: 31, net_delta: -4, delta: 1 }]);
    assert.deepEqual(m.rows.map(r => r.delta.text), ['+2.00', '−4.00']);
    assert.deepEqual(m.rows.map(r => r.share), [0.5, 1]);
    assert.deepEqual(m.helps, ['2026-10']);
    assert.deepEqual(monthRows(null), { rows: [], helps: [] });
});

test('energy lines: grid in and out, self-consumption, cycles', () => {
    const rows = energyRows({ actual: { grid_import_kwh: 100, grid_export_kwh: 50, self_consumption_pct: 61.25, cycles: 120 },
        simulated: { grid_import_kwh: 80.04, grid_export_kwh: 20, self_consumption_pct: 80, cycles: 40.5 } });
    assert.deepEqual(rows.map(r => r.key), ['sim_grid_in', 'sim_grid_out', 'sim_self_use', 'sim_cycles']);
    assert.deepEqual([rows[0].actual, rows[0].simulated], ['100.0', '80.0']);
    assert.equal(rows[2].actual, '61.3 %');
    assert.equal(rows[3].simulated, '40.5');
    assert.deepEqual(energyRows(null), []);
});

const DEF = { capacity_kwh: 15, reserve_pct: 20, peak_limit_kw: 11, import_rate: 0.3, export_rate: 0.1, currency: 'CHF' };

test('the form starts at the install, prices as recorded', () => {
    assert.deepEqual(initialForm(DEF), {
        capacity_kwh: 15, reserve_pct: 20, peak_limit_kw: 11,
        import_mode: 'recorded', import_rate: 0.3, export_mode: 'recorded', export_rate: 0.1,
        battery_mode: 'auto', ev_mode: 'recorded',
        max_charge_w: '', max_discharge_w: '', pv_mode: 'factor', pv_extra_kwp: '', pv_factor: 1,
        battery_to_ev: true,
    });
    const full = initialForm({ ...DEF, max_charge_w: 5000, system_size_kwp: 12, battery_to_ev: false });
    assert.equal(full.max_charge_w, 5000);
    assert.equal(full.pv_mode, 'kwp');
    assert.equal(full.battery_to_ev, false);
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

test('the levers: battery power, more solar, battery for the car', () => {
    const f = initialForm({ ...DEF, max_charge_w: 5000, max_discharge_w: 5000, system_size_kwp: 10 });
    assert.equal(isChanged('max_charge_w', f, { max_charge_w: 5000 }), false);
    assert.equal(isChanged('max_charge_w', { ...f, max_charge_w: '8000' }, { max_charge_w: 5000 }), true);
    assert.equal(isChanged('pv', f, DEF), false);
    assert.equal(isChanged('pv', { ...f, pv_extra_kwp: '4' }, DEF), true);
    assert.equal(isChanged('pv', { ...f, pv_mode: 'factor', pv_factor: '1.5' }, DEF), true);
    assert.equal(isChanged('battery_to_ev', { ...f, battery_to_ev: false }, { battery_to_ev: true }), true);
    const p = buildParams({ ...f, max_charge_w: '8000', pv_extra_kwp: '4', battery_to_ev: false });
    assert.equal(p.max_charge_w, 8000);
    assert.equal(p.max_discharge_w, 5000);
    assert.equal(p.pv_extra_kwp, 4);
    assert.equal(p.pv_factor, undefined);
    assert.equal(p.battery_to_ev, false);
    const q = buildParams({ ...f, pv_mode: 'factor', pv_factor: '1.5' });
    assert.equal(q.pv_factor, 1.5);
    assert.equal(q.battery_to_ev, undefined);         // on is how the install runs
    assert.equal(buildParams(f).pv_factor, undefined);
});

test('scenarios fill the form; the person can still edit it', () => {
    const d = { ...DEF, max_charge_w: 5000, max_discharge_w: 4000, system_size_kwp: 10 };
    const f = initialForm(d);
    assert.deepEqual(PRESETS, ['plus_battery', 'plus_pv', 'cheap_chargers', 'no_battery_ev']);
    const one = applyPreset(f, d, 'plus_battery');
    assert.deepEqual([one.capacity_kwh, one.max_charge_w, one.max_discharge_w], [30, 10000, 8000]);
    assert.equal(f.capacity_kwh, 15, 'the form itself was changed');
    const pv = applyPreset(f, d, 'plus_pv', 5);
    assert.deepEqual([pv.pv_mode, pv.pv_extra_kwp], ['kwp', 5]);
    const factor = applyPreset(initialForm(DEF), DEF, 'plus_pv', 1.4);
    assert.deepEqual([factor.pv_mode, factor.pv_factor], ['factor', 1.4]);
    assert.equal(applyPreset(f, d, 'plus_pv', null).pv_extra_kwp, '');
    assert.equal(applyPreset(f, d, 'cheap_chargers').ev_mode, 'solar_plus_cheap');
    assert.equal(applyPreset(f, d, 'no_battery_ev').battery_to_ev, false);
    assert.equal(applyPreset(f, d, 'nope').capacity_kwh, 15);
});

test('run needs a period, a size, and nothing running', () => {
    const f = initialForm(DEF);
    const p = { from: '2026-09-01', to: '2026-09-30' };
    assert.equal(canRun(p, f, { running: false }), true);
    assert.equal(canRun(null, f, null), false);
    assert.equal(canRun({ from: '2026-09-01' }, f, null), false);
    assert.equal(canRun(p, f, { running: true }), false);
    assert.equal(canRun(p, { ...f, capacity_kwh: '' }, null), false);
    assert.equal(canRun(p, { ...f, capacity_kwh: '0' }, null), false);
    const msg = buildStart(p, f);
    assert.deepEqual([msg.from, msg.to, msg.days], ['2026-09-01', '2026-09-30', undefined]);
    assert.equal(msg.params.capacity_kwh, 15);
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
    const c = calibration({ calibrated: false, calibration: { error_pct: 12.3, days: 20, left_out: 3, car_days: 9, car_error_pct: 15.1 }, repriced: true });
    assert.deepEqual(c, { ok: false, caution: false, pct: 12.3, days: 20, leftOut: 3, carDays: 9, carPct: 15.1, repriced: true });
    assert.equal(calibration({ calibrated: true, calibration: { error_pct: 1.2 } }).ok, true);
    assert.equal(calibration({ calibrated: true, calibration: { error_pct: 1.2 } }).carPct, null);
    assert.equal(calibration({}).ok, true);
    assert.equal(calibration(null).days, null);
});

test('calibration: 5 to 10 % shows the what-if with a caution', () => {
    const c = calibration({ calibrated: true, calibration: { error_pct: 5.3, max_pct: 5 } });
    assert.equal(c.ok, true);
    assert.equal(c.caution, true);
    assert.equal(calibration({ calibrated: true, calibration: { error_pct: 4.9, max_pct: 5 } }).caution, false);
    assert.equal(calibration({ calibrated: false, calibration: { error_pct: 12, max_pct: 5 } }).caution, false);
});

test('periodGaps: counts the days of a period that cannot be picked', () => {
    const days = [
        { date: '2026-10-01', tags: ['gap'] }, { date: '2026-10-02', tags: ['sunny'] },
        { date: '2026-10-03', tags: ['gap'] }, { date: '2026-09-01', tags: ['gap'] },
    ];
    assert.equal(periodGaps(days, { from: '2026-10-01', to: '2026-10-31' }), 2);
    assert.equal(periodGaps(days, null), 0);
});

// ── The "most recent days" slider (a phone needs one drag, not 90 taps) ──
import { recentMax, recentPeriod, recentAt, SIM_CAPACITY_MAX_KWH } from '../src/util/simulation-rows.js';

const RECENT = [
    { date: '2026-10-14', tags: ['sunny'] },
    { date: '2026-10-15', tags: ['gap'] },
    { date: '2026-10-16', tags: ['grey'] },
    { date: '2026-10-12', tags: ['car'] },
    { date: '2026-10-17', tags: ['mixed'] },
];

test('the slider reaches every stored day, gaps left out', () => {
    assert.equal(recentMax(RECENT), 4);
    assert.equal(recentMax([]), 0);
});

test('the slider picks the period of the newest n stored days', () => {
    assert.deepEqual(recentPeriod(RECENT, 2), { from: '2026-10-16', to: '2026-10-17' });
    // the gap day on 15.10 lies inside: the period is still one span
    assert.deepEqual(recentPeriod(RECENT, 3), { from: '2026-10-14', to: '2026-10-17' });
    assert.equal(recentPeriod(RECENT, 0), null);
    assert.deepEqual(recentPeriod(RECENT, 99), { from: '2026-10-12', to: '2026-10-17' });
    assert.deepEqual(recentPeriod(RECENT, '2'), { from: '2026-10-16', to: '2026-10-17' });
});

test('the slider shows where it stands only for a newest-n period', () => {
    assert.equal(recentAt(RECENT, null), 0);
    assert.equal(recentAt(RECENT, { from: '2026-10-16', to: '2026-10-17' }), 2);
    assert.equal(recentAt(RECENT, { from: '2026-10-12', to: '2026-10-16' }), null);
});

test('a what-if battery may be a car pack, up to 150 kWh', () => {
    assert.equal(SIM_CAPACITY_MAX_KWH, 150);
});

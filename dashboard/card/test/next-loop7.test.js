/**
 * (#1321) Review loop 7: every check is named, a default is not a size, the plan's
 * reason is true, one battery size, watch-only says what SEM would do, no fake zero.
 *
 * Run: `node --test test/next-loop7.test.js` (from dashboard/card).
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { repairNames } from '../src/util/setup-checklist.js';
import { knownCapacity, upToShown } from '../src/util/charger-questions.js';
import { whyLines, gotCheapest, reasonRuns } from '../src/util/plan-why.js';
import { batterySize } from '../src/util/battery-size.js';
import { wouldList, wouldFor, wouldLine } from '../src/util/why-rows.js';
import { sunRuns, sunModel } from '../src/util/next-plan-chart.js';
import { mount, text, S } from './card-harness.js';

const WORDS = { next_batt_cap_usable: '{kwh} kWh battery ({usable} usable)', next_batt_cap: '{kwh} kWh battery',
    next_reason_solar: 'Runs on spare solar', next_reason_cheapest_hours: 'Cheapest hours' };
globalThis.semLocalize = (k) => WORDS[k] || k;
const HOUR = 3600e3;
const NOW = Date.parse('2026-11-18T10:00:00Z');
const iso = (h) => new Date(NOW + h * HOUR).toISOString();

test('1: the checks are named from the published titles; no "1 more to check"', () => {
    const rep = { count: 2, first: 'Files from a previous SEM install were found',
        titles: ['Files from a previous SEM install were found', 'Sim Boiler has no power reading'] };
    // HA's localize has no title for these keys, and the repairs list is not read here
    const names = repairNames(rep, [], () => '', (n) => `${n} more to check`);
    assert.deepEqual(names, rep.titles);
    // an older server sends no titles: the old reading still stands
    assert.deepEqual(repairNames({ count: 2, first: 'A' }, [], () => '', (n) => `${n} more`), ['A', '1 more']);
});

test('2: a battery size the owner never set is unknown, not 40 kWh', () => {
    assert.equal(knownCapacity(40, { set_by_user: false }), null);
    assert.equal(knownCapacity(52, { set_by_user: true }), 52);
    assert.equal(knownCapacity(52, {}), 52, 'a server with no flag is trusted');
    assert.equal(knownCapacity(null, { set_by_user: true }), null);
    // unknown size, the setting's own ceiling: "up to full", not "up to 40 kWh"
    assert.equal(upToShown({ max: 100, capacity: knownCapacity(40, { set_by_user: false }), bound: 100, isSoc: false }).full, true);
});

// the PROD night: the cheapest hour (0.11) went to the battery, the car got the next ones
const SLOTS = [[0, 0.20], [1, 0.11], [2, 0.157], [3, 0.157], [4, 0.30]].map(([h, price]) => ({ start: iso(h), end: iso(h + 1), price }));
const planWith = (price) => ({
    slots: SLOTS,
    blocks: [{ id: 'ev:c2', start: iso(2), end: iso(4), power_w: 5000, reason: 'cheapest_hours' }],
    demands: [{ id: 'ev:c2', planned_kwh: 10, why: { code: 'cheapest_hours', params: { from: iso(2), to: iso(4), price } } }],
});

test('3: "cheapest hours" is said only when the demand got them; else "left"', () => {
    const runs = [{ s: NOW + 2 * HOUR, e: NOW + 4 * HOUR }];
    assert.equal(gotCheapest(planWith(0.157), runs, 0.157, NOW), false, 'the 0.11 hour went elsewhere');
    assert.equal(whyLines(planWith(0.157), NOW)[0].code, 'cheapest_left');
    const own = { ...planWith(0.135), blocks: [{ id: 'ev:c2', start: iso(1), end: iso(3), power_w: 5000 }] };
    const ownRuns = [{ s: NOW + HOUR, e: NOW + 3 * HOUR }];
    assert.equal(gotCheapest(own, ownRuns, 0.1335, NOW), true);
    assert.equal(whyLines(own, NOW)[0].code, 'cheapest_hours');
    assert.equal(gotCheapest({ slots: [] }, runs, 0.15, NOW), null, 'no slots, no claim');
});

test('3: the battery names one reason per block, with its hours', () => {
    const blocks = [
        { id: 'battery_in', start: iso(1), end: iso(2), power_w: 2000, reason: 'cheapest_hours', reason_params: { price: 0.169 } },
        { id: 'battery_in', start: iso(3), end: iso(4), power_w: 1000, reason: 'solar', reason_params: {} },
    ];
    const r = reasonRuns(blocks, 'battery_in', NOW);
    assert.equal(r.length, 2);
    assert.equal(r[0].reason, 'cheapest_hours');
    assert.equal(r[0].runs[0].s, NOW + HOUR);
    assert.equal(r[1].runs[0].s, NOW + 3 * HOUR);
    const line = whyLines({ blocks, demands: [], slots: [] }, NOW).find((l) => l.id === 'battery_in');
    assert.equal(line.reasons.length, 2);
    // the card prefixes each reason with its hours only when there are several
    const el = mount('sem-next-plan-card', { 'sensor.sem_energy_plan': S('ok', {}) });
    const one = el._blockReasons([{ reason: 'solar', params: {}, runs: [{ s: NOW, e: NOW + HOUR }] }]);
    const two = el._blockReasons(line.reasons);
    assert.equal(one, 'Runs on spare solar', 'one reason: no hours prefix');
    assert.match(two, /: Cheapest hours.*: Runs on spare solar/, 'each reason names its own hours');
});

test('4: one battery size: nameplate with the usable size beside it', () => {
    const st = { 'sensor.sem_diag_battery_capacity': S(15), 'sensor.sem_battery_measured_capacity_kwh': S(12.7) };
    assert.deepEqual(batterySize(st), { nominal: 15, usable: 12.7 });
    assert.equal(batterySize({ 'sensor.sem_diag_battery_capacity': S(15) }).usable, null);
    assert.equal(batterySize({ 'sensor.sem_diag_battery_capacity': S(15), 'sensor.sem_battery_measured_capacity_kwh': S(15) }).usable, null);
    // System › Hardware and Devices read the same helper
    const sys = mount('sem-next-system-card', st);
    assert.match(sys._batteryText(15), /15\.0/);
    assert.match(sys._batteryText(15), /12\.7/);
});

test('5: watch-only: Devices says what System says SEM would do', () => {
    const attrs = { would_decisions: {
        a: { kind: 'load', device_id: 'boiler', action: 'activate' },
        b: { kind: 'charger', device_id: 'ev:c1', action: 'idle' },
        c: { kind: 'battery', device_id: 'battery:main', action: 'limit_discharge' },
    } };
    const list = wouldList(attrs);
    assert.equal(list.length, 2, 'idle is not a decision');
    assert.equal(wouldFor({ type: 'load', id: 'boiler' }, list).action, 'activate');
    assert.equal(wouldFor({ type: 'battery', id: 'battery' }, list).action, 'limit_discharge');
    assert.equal(wouldFor({ type: 'charger', cid: 'c1' }, list), null);
    const t = (k) => ({ next_would_x: 'Would {what}', next_act_activate: 'switch on' }[k] || k);
    assert.equal(wouldLine(list[0], t), 'Would switch on');
});

test('L: the measured sun line stops at the last reading; no fake 0 at now', () => {
    const win = { start: NOW - 10 * HOUR, end: NOW + 10 * HOUR };
    const actual = [-3, -2, -1].map((h) => ({ t: NOW + h * HOUR, w: 2000 }));
    const fc = {}; for (const h of [0, 1, 2]) fc[new Date(NOW + h * HOUR).toISOString()] = 1500;
    const sun = sunModel({ win, nowMs: NOW, actual, forecast: fc });
    const X = (t) => (t - win.start) / 1e6, SY = (kw) => 100 - kw * 10;
    const runs = sunRuns(sun.points, X, SY);
    const measured = runs.filter((r) => r.actual), forecast = runs.filter((r) => !r.actual);
    assert.ok(measured.every((r) => r.xy[r.xy.length - 1][1] < 100), 'ends at its last reading, not on the base');
    assert.ok(forecast[0].xy[0][1] < 100, 'the forecast starts from the last reading');
    // a night is still a real zero: the first measured point rises from the base
    assert.equal(measured[0].xy[0][1], 100);
});

test('L: the Devices tiles stack on a narrow screen', () => {
    const el = mount('sem-next-devices-card', {});
    const out = text(el._tiles([{ label: 'a', value: 1 }], { three: true, stack: true }));
    assert.match(out, /class="tiles stack"/);
});

test('L: the All settings switch is a view choice: it writes no server state and works with storage blocked', async () => {
    const seen = [];
    globalThis.window = globalThis.window || globalThis;
    globalThis.CustomEvent = globalThis.CustomEvent || class { constructor(type, init) { this.type = type; this.detail = init?.detail; } };
    globalThis.dispatchEvent = (e) => { seen.push(e.detail); return true; };
    Object.defineProperty(globalThis, 'localStorage', { configurable: true, get() { throw new Error('blocked'); } });
    const { setAllSettings } = await import('../src/util/view-mode.js');
    setAllSettings(true);
    assert.deepEqual(seen, [{ all: true }], 'the page still hears the choice');
});

test('1: the Now checklist names every check, not only the first', async () => {
    const st = { 'sensor.sem_diag_charger_control': S('number', { setup_checklist: { watch_only: true, items: [], done: 5, total: 5, must_open: false,
        repairs: { count: 2, first: 'A', titles: ['A', 'B'] } } }) };
    const el = mount('sem-setup-checklist-card', st);
    assert.match(text(el._repairsRow({ count: 2, first: 'A', titles: ['A', 'B'] })), /A · B/);
});

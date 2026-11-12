/**
 * (#1321) A heater says what it does and why. Discussion 1059: a tank at
 * 45.8 °C under Keep at 52 showed nothing a reader could act on. Every
 * branch of the heater sentence, the reason beside "off", the two plan
 * ids, and the Plan screen's "no hour" line.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { deviceRows, statePill, heaterSays, becauseKey, nextBlock, modeHelpKey } from '../src/util/next-devices.js';
import { planLead, coldHeaters } from '../src/util/next-lead.js';
import { planRows } from '../src/util/next-plan-chart.js';

const BAND = { state: 'willing', hvac: 'heat', keep_c: 52, start_c: 51, max_c: 56, limit_c: 36, own_run: false };
const tank = (reading, over = {}, intent = null, extra = {}) => deviceRows({
    boiler: { name: 'Boiler', priority: 1, device_type: 'switch', control_mode: 'surplus', is_on: false,
        comfort: { ...BAND, reading_c: reading, ...over }, intent, ...extra },
}, [])[0];
const pill = (row, live = {}) => statePill(row, { powerW: 0, ...live });

test('the row carries the engine intent', () => {
    assert.deepEqual(tank(45, {}, { on: false, source: null, code: 'plan_wait' }).intent, { on: false, source: null, code: 'plan_wait' });
    assert.equal(tank(45).intent, null);
});

test('a running heater says what it heats to', () => {
    const on = { is_on: true };
    assert.deepEqual(pill(tank(34, { state: 'forced' }, { on: true, source: 'comfort_floor', code: 'comfort_floor' }, on)),
        { key: 'hq_st_too_cold', params: {}, cls: 'warn', why: '' });
    assert.deepEqual(pill(tank(45, {}, { on: true, source: 'cheap_grid', code: 'comfort_goal' }, on)),
        { key: 'hq_st_heating_to', params: { keep: '52 °C' }, cls: 'ok', why: '' });
    assert.deepEqual(pill(tank(53, { state: 'willing' }, { on: true, source: 'solar', code: 'solar' }, on)),
        { key: 'hq_st_heating_sun', params: { max: '56 °C' }, cls: 'ok', why: '' });
    assert.equal(pill(tank(55, { own_run: true }, { on: true, source: 'legionella', code: 'legionella' }, on)).key, 'hq_st_legionella');
    // a paid run-time run has no heater sentence: plain "on"
    assert.equal(pill(tank(45, {}, { on: true, source: 'cheap_grid', code: 'cheap_grid' }, on)).key, 'next_st_on');
});

test('an idle heater says what comes next', () => {
    // discussion 1059: 45.8 under Keep at 52, a Keep at block ahead
    assert.deepEqual(pill(tank(45.8), { plannedAt: '23:00' }),
        { key: 'hq_st_heats_at', params: { keep: '52 °C', time: '23:00' }, cls: '', why: '', next: true });
    // …and none: it says so, never plain "off"
    assert.deepEqual(pill(tank(45.8, {}, { on: false, source: null, code: 'no_source' })),
        { key: 'hq_st_below_none', params: { keep: '52 °C' }, cls: 'warn', why: '', next: true });
    assert.equal(pill(tank(45.8, {}, { on: false, source: null, code: 'peak_shed' })).why, 'hq_because_peak');
    assert.equal(pill(tank(45.8, {}, { on: false, source: null, code: 'vacation' })).why, 'hq_because_away');
    // inside the start gap: warm, and the line it heats again under
    assert.deepEqual(pill(tank(51.4)), { key: 'hq_st_warm_again', params: { start: '51 °C' }, cls: '', why: '', next: true });
    assert.deepEqual(pill(tank(52)), { key: 'hq_st_warm', params: { reading: '52 °C' }, cls: '', why: '', next: true });
    assert.equal(pill(tank(54.2)).params.reading, '54.2 °C');
    assert.equal(pill(tank(null, { state: 'disengaged' })).key, 'hq_st_no_reading');
});

test('the user unit comes from the card, the lines from the engine', () => {
    const f = (c) => Math.round(c * 9 / 5 + 32) + ' °F';
    assert.equal(pill(tank(45.8), { plannedAt: '23:00', fmtTemp: f }).params.keep, '126 °F');
});

test('a load without a heating band keeps its texts, and off names a cause', () => {
    const plain = (intent, over = {}) => deviceRows({ pump: { name: 'Pump', priority: 1, control_mode: 'surplus', is_on: false, intent, ...over } }, [])[0];
    assert.equal(heaterSays(plain(null), {}), null);
    assert.deepEqual(pill(plain({ on: false, source: null, code: 'target_met' })), { key: 'next_st_off', params: {}, cls: '', why: 'hq_because_ran_enough' });
    assert.equal(pill(plain({ on: false, source: null, code: 'no_source' })).why, 'hq_because_no_sun');
    assert.equal(pill(plain(null)).why, '');
    assert.equal(pill(plain({ on: false, code: 'plan_wait' }), { plannedAt: '13:30' }).key, 'next_st_waits_for');
    // a cooling band and Mode Off are not the heater sentence
    assert.equal(heaterSays(tank(27, { hvac: 'cool' }), {}), null);
    assert.equal(pill(tank(45, {}, null, { control_mode: 'off' })).key, 'next_st_off_mode');
    // peak-only: SEM never starts it — the row says so, not a bare 'off'
    assert.equal(pill(plain({ on: false, source: null, code: '' }, { control_mode: 'peak_only' })).key, 'next_st_off_peak_only');
    assert.equal(becauseKey({ on: true, code: 'peak_shed' }), '');
    assert.equal(becauseKey({ on: false, code: 'something_new' }), '');
});

test('the next block is the earliest of the run-time and the Keep at block', () => {
    const now = Date.parse('2026-11-11T18:00:00+01:00');
    const blocks = [
        { id: 'load:boiler', start: '2026-11-12T02:00:00+01:00', end: '2026-11-12T03:00:00+01:00' },
        { id: 'comfort:boiler', start: '2026-11-11T23:00:00+01:00', end: '2026-11-12T00:00:00+01:00' },
        { id: 'comfort:boiler', start: '2026-11-11T12:00:00+01:00', end: '2026-11-11T13:00:00+01:00' },
        { id: 'comfort:other', start: '2026-11-11T19:00:00+01:00', end: '2026-11-11T20:00:00+01:00' },
    ];
    assert.equal(nextBlock(blocks, ['load:boiler', 'comfort:boiler'], now).start, '2026-11-11T23:00:00+01:00');
    assert.equal(nextBlock(blocks, ['load:boiler'], now).start, '2026-11-12T02:00:00+01:00');
    assert.equal(nextBlock(undefined, ['load:boiler'], now), null);
});

const DEVICES = (reading, over = {}) => ({ boiler: { name: 'Boiler', control_mode: 'surplus', is_on: false,
    comfort: { ...BAND, reading_c: reading }, ...over } });
const NOW = Date.parse('2026-11-11T18:00:00+01:00');
const KEEP_BLOCK = [{ id: 'comfort:boiler', start: '2026-11-11T23:00:00+01:00', end: '2026-11-12T00:00:00+01:00', power_w: 3000 }];

test('a cold heater with no hour is found; one with an hour, a warm one and an off one are not', () => {
    assert.deepEqual(coldHeaters(DEVICES(45.8), [], NOW), [{ id: 'boiler', name: 'Boiler', keepC: 52 }]);
    assert.deepEqual(coldHeaters(DEVICES(45.8), KEEP_BLOCK, NOW), []);
    assert.deepEqual(coldHeaters(DEVICES(51.5), [], NOW), []);
    assert.deepEqual(coldHeaters(DEVICES(45.8, { is_on: true }), [], NOW), []);
    assert.deepEqual(coldHeaters(DEVICES(45.8, { control_mode: 'off' }), [], NOW), []);
    assert.deepEqual(coldHeaters(DEVICES(null), [], NOW), []);
    assert.deepEqual(coldHeaters({ pump: { name: 'Pump' } }, [], NOW), []);
});

test('the plan line never says "nothing planned" over a cold heater', () => {
    const a = { computed_at: 'x', blocks: [] };
    assert.equal(planLead(a, {}).main.key, 'next_plan_quiet');
    assert.deepEqual(planLead(a, { cold: { name: 'Boiler', keep: '52 °C', time: '07:00' } }).main,
        { key: 'hq_plan_below_no_hour', params: { name: 'Boiler', keep: '52 °C', time: '07:00' } });
    assert.equal(planLead(a, { cold: { name: 'Boiler', keep: '52 °C', time: '' } }).main.key, 'hq_plan_below_no_hour_plain');
    // a Keep at run counts as a planned load run
    assert.equal(planLead({ computed_at: 'x', blocks: KEEP_BLOCK }, {}).main.key, 'next_plan_loads');
});

test('a Keep at run is a row named after its device, not its plan id', () => {
    const win = { start: NOW, end: NOW + 24 * 3600e3 };
    const rows = planRows({ win, nowMs: NOW, plan: { blocks: KEEP_BLOCK }, names: { load: (id) => (id === 'boiler' ? 'Boiler' : id) } });
    assert.equal(rows.length, 1);
    assert.equal(rows[0].label, 'Boiler');
    assert.equal(rows[0].keepOf, 'boiler');
    assert.equal(rows[0].kind, 'load');
});

test('solar only buys nothing: a cold tank waits for sun, and says how to allow the grid', () => {
    // discussion 1059 again: Solar only, 45.8 under Keep at 52 — no hour will ever be planned
    const row = tank(45.8, { may_buy: false }, { on: false, source: null, code: 'no_source' });
    assert.deepEqual(pill(row), { key: 'hq_st_waits_sun', params: { keep: '52 °C' }, cls: '', why: '', next: true, noBuy: true });
    // with the grid allowed it is the plan that is missing
    assert.equal(pill(tank(45.8, { may_buy: true }, { on: false, code: 'no_source' })).key, 'hq_st_below_none');
    assert.equal(pill(tank(45.8, { may_buy: true }), { plannedAt: '23:00' }).key, 'hq_st_heats_at');
    // a block ahead (its run time from the battery) still says when
    assert.equal(pill(row, { plannedAt: '02:00' }).key, 'hq_st_heats_at');
    // warm and running states do not change
    assert.equal(pill(tank(52.3, { may_buy: false })).key, 'hq_st_warm');
    assert.equal(pill(tank(34, { may_buy: false, state: 'forced' }, { on: true, code: 'comfort_floor' }, { is_on: true })).key, 'hq_st_too_cold');
});

test('a running heater keeps the engine sentence; an idle one says only what comes next', () => {
    assert.equal(pill(tank(45, {}, { on: true, source: 'cheap_grid', code: 'comfort_goal' }, { is_on: true })).next, undefined);
    assert.equal(pill(tank(45.8), { plannedAt: '03:00' }).next, true);
});

test('a heater that buys nothing is not a gap in the plan', () => {
    const dev = (may) => ({ boiler: { name: 'Boiler', control_mode: 'surplus', is_on: false, comfort: { ...BAND, reading_c: 45.8, may_buy: may } } });
    assert.deepEqual(coldHeaters(dev(false), [], NOW), []);
    assert.equal(coldHeaters(dev(true), [], NOW).length, 1);
});

test('the mode sentence is true to the grid setting', () => {
    assert.equal(modeHelpKey('solar_only', {}), 'help_mode_surplus');
    assert.equal(modeHelpKey('solar_only', { top_up_policy: 'cheap_hours' }), 'help_mode_surplus_grid');
    assert.equal(modeHelpKey('solar_only', { battery_eligible_overnight: true }), 'help_mode_surplus_battery');
    assert.equal(modeHelpKey('solar_battery', { top_up_policy: 'cheap_hours' }), 'battery_overnight_hint');
    assert.equal(modeHelpKey('off', {}), 'help_mode_off');
    assert.equal(modeHelpKey('peak_only', {}), 'help_mode_peak_only');
});

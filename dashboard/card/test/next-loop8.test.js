// (#1321) review loop 8
import test from 'node:test';
import assert from 'node:assert/strict';
import { mount, text, S } from './card-harness.js';
// (#1321) lit is faked by the harness; modules load after it (CI has no node_modules)
const { whyLines, gotCheapest } = await import('../src/util/plan-why.js');
const { refillKwh } = await import('../src/util/next-devices-battery.js');
const { aboveReserve } = await import('../src/util/next-battery-line.js');
const { sunModel, sunRuns } = await import('../src/util/next-plan-chart.js');
const { nowLead, repeatsNextBlock } = await import('../src/util/next-lead.js');
const { groups, sentenceText } = await import('../src/util/next-settings.js');

const HOUR = 3600e3;
const NOW = Date.parse('2026-11-18T10:00:00Z');
const iso = (h) => new Date(NOW + h * HOUR).toISOString();
const cells = (hourPrices) => hourPrices.flatMap((price, h) => [0, 1, 2, 3].map((q) => ({ t: iso(h + q / 4), price })));

// the live plan sensor drops its slots (timeline_omitted); the tariff's upcoming list stays
const live = (price) => ({
    timeline_omitted: true,
    blocks: [{ id: 'ev:c2', start: iso(2), end: iso(4), power_w: 5000, reason: 'cheapest_hours' }],
    demands: [{ id: 'ev:c2', planned_kwh: 10, why: { code: 'cheapest_hours', params: { from: iso(2), to: iso(4), price } } }],
});
const UP = cells([0.20, 0.11, 0.157, 0.157, 0.30]);

test('1: with timeline_omitted the tariff prices still tell whether the cheapest hours were got', () => {
    const runs = [{ s: NOW + 2 * HOUR, e: NOW + 4 * HOUR }];
    assert.equal(gotCheapest(live(0.157), runs, 0.157, NOW, UP), false);
    assert.equal(whyLines(live(0.157), NOW, 4, UP)[0].code, 'cheapest_left');
    assert.equal(whyLines(live(0.157), NOW, 4, [])[0].code, 'cheapest_hours', 'no prices at all: no claim');
    const own = { ...live(0.1335), blocks: [{ id: 'ev:c2', start: iso(1), end: iso(3), power_w: 5000 }] };
    assert.equal(whyLines(own, NOW, 4, UP)[0].code, 'cheapest_hours');
});


test('5: Devices says the battery refill the Plan names, not the forecast alone', () => {
    const plan = { blocks: [
        { id: 'arbitrage:battery', start: iso(1), end: iso(2), power_w: 1000, reason: 'solar' },
        { id: 'arbitrage:battery', start: iso(13), end: iso(14), power_w: 1800, reason: 'cheapest_hours' },
        { id: 'battery_out', start: iso(3), end: iso(5), power_w: 900 }] };
    assert.equal(refillKwh(plan, 0, NOW), 1.8, 'the 0.0 forecast does not hide the planned night charging; the day\'s sun run is not tonight\'s');
    assert.equal(refillKwh({ blocks: [] }, 0.4, NOW), 0.4, 'no battery charging planned: the forecast');
    assert.equal(refillKwh({}, NaN, NOW), null);
});

test('4: "more than the battery holds" compares with what is above the reserve', () => {
    const st = (v, a) => ({ state: String(v), attributes: a || {} });
    const states = { 'sensor.sem_diag_battery_capacity': st(15), 'number.sem_battery_reserve_soc': st(20),
        'sensor.sem_battery_spendable_kwh': st(0, { measured_capacity_kwh: 12.73 }) };
    assert.ok(Math.abs(aboveReserve(states) - 10.18) < 0.01);
    assert.equal(aboveReserve({}), null);
});


test('L: the sun line runs to the last reading, not the last whole hour', () => {
    const now = Date.parse('2026-11-18T11:43:00Z');
    const win = { start: now - 3 * HOUR, end: now + 21 * HOUR };
    const actual = [8, 9, 10].map((h) => ({ t: Date.parse(`2026-11-18T${String(h).padStart(2, '0')}:00:00Z`), w: 2000 }));
    const bare = sunModel({ win, nowMs: now, actual });
    const withLive = sunModel({ win, nowMs: now, actual, liveW: 2500 });
    const end = (m) => Math.max(...m.points.filter((p) => p.actual).map((p) => p.e));
    assert.equal(end(bare), Date.parse('2026-11-18T11:00:00Z'));
    assert.equal(end(withLive), now);
    assert.equal(withLive.totalKwh, bare.totalKwh, 'the reading adds no energy');
    const runs = sunRuns(withLive.points, (t) => t / 1000, (kw) => kw).filter((r) => r.actual);
    assert.equal(runs.length, 1, 'one line, no stray dot');
    assert.equal(sunModel({ win, nowMs: now, actual, liveW: null }).points.length, bare.points.length);
});


const WORDS = {
    next_would_limit: 'discharge limited to {kw}', next_battery_charging: 'Battery charging',
    next_battery_charge_planned: 'Battery charge planned', next_reason_solar_later: 'Charges when spare sun comes',
    next_reason_solar: 'Runs on spare solar', next_surplus_now: 'Surplus now',
};
globalThis.semLocalize = (k) => WORDS[k] || k;

const would = (action, power_w) => ({ 'switch.sem_observer_mode': S('on', { would_decisions: {
    b: { kind: 'battery', device_id: 'battery:main', action, power_w, reason_code: 'battery_normal' } } }) });

test('6: a battery that would run normally shows no limit line', () => {
    const el = mount('sem-next-system-card', would('normal', 0));
    assert.doesNotMatch(text(el._refused()), /limited to/);
    const lim = mount('sem-next-system-card', would('limit_discharge', 2200));
    assert.match(text(lim._refused()), /discharge limited to/);
});

test('8: Plan names a charge "planned" while the battery is not charging, "charging" when it is', () => {
    const el = mount('sem-next-plan-card', { 'sensor.sem_battery_power': S(-2300, { unit_of_measurement: 'W' }) });
    const now = Date.now();
    const row = { kind: 'battery_in' };
    assert.equal(el._rowName(row, now - 600e3, now + 600e3), 'Battery charge planned');
    assert.equal(el._rowName(row, now + 3600e3, now + 7200e3), 'Battery charging', 'a later block is a plan anyway');
    el.hass = { ...el._hass, states: { 'sensor.sem_battery_power': S(1800, { unit_of_measurement: 'W' }) } };
    assert.equal(el._rowName(row, now - 600e3, now + 600e3), 'Battery charging');
    el.hass = { ...el._hass, states: {} };
    assert.equal(el._rowName(row, now - 600e3, now + 600e3), 'Battery charging', 'no reading: no claim');
});

test('8: the solar reason of a battery charge that is not running says when', () => {
    const now = Date.now();
    const el = mount('sem-next-plan-card', { 'sensor.sem_battery_power': S(-2300, { unit_of_measurement: 'W' }) });
    const runs = [{ s: now - 600e3, e: now + 600e3 }];
    assert.equal(el._blockReasons([{ reason: 'solar', params: {}, runs }]), 'Charges when spare sun comes');
});

test('7: the surplus tile is labelled and says plainly what the parts are', () => {
    const states = { 'sensor.sem_surplus_total_w': S(800, { unit_of_measurement: 'W' }),
        'sensor.sem_surplus_allocated_w': S(100, { unit_of_measurement: 'W' }), 'sensor.sem_surplus_unallocated_w': S(700, { unit_of_measurement: 'W' }),
        'sensor.sem_home_consumption_power': S(900, { unit_of_measurement: 'W' }) };
    const el = mount('sem-next-devices-card', states);
    const out = text(el._surplus([{ type: 'load', name: 'Heizband', isOn: true, rating: 2100, live: 100 }]));
    assert.match(out, /Surplus now/);
    assert.doesNotMatch(out, /next_in_use_by|Counted/);
});


test('L: a heading about the car charge is not repeated by a "Next:" line', () => {
    const lead = nowLead({ night: false, observer: true, solarW: 700, gridW: 0, batteryW: -200,
        car: { present: true, charging: false, remainingKwh: 10, plannedKwh: 10, planWindow: '14:15 – 16:30' }, battery: { soc: 26 } });
    assert.equal(lead.main.key, 'next_lead_car_planned');
    assert.equal(repeatsNextBlock(lead.main.key), true);
    assert.equal(repeatsNextBlock('next_lead_sun_house'), false);
});

test('9: the morning check reads as a check with its window, not as a pause', () => {
    const states = { 'switch.sem_ev_morning_window_enabled': S('off'), 'number.sem_ev_morning_window_hours': S(2, { min: 1, max: 6, step: 0.5, unit_of_measurement: 'h' }),
        'switch.sem_observer_mode': S('off') };
    const tt = (k) => ({ next_misc_morning: 'morning check {on}, window {hours}', next_misc_hints: 'Hints {hints}' }[k] || k);
    const g = groups(states, tt, { options: {}, currency: 'CHF', chargers: [], labels: {} }).find((x) => x.key === 'misc');
    const out = sentenceText(g.sentence, tt, states);
    assert.match(out, /Morning check next_off, window 2/);
    assert.doesNotMatch(out, /for 2/);
});

test('L: a charger row label is in sentence case when there are several chargers', () => {
    const tt = (k) => ({ next_more_capacity: 'capacity', next_more_use: 'use' }[k] || k);
    const chargers = [{ cid: 'a', name: 'Keba', id: 'a' }, { cid: 'b', name: 'Box 2', id: 'b' }];
    const g = groups({ 'switch.sem_observer_mode': S('off') }, tt, { options: { ev_chargers: chargers }, currency: 'CHF', chargers, labels: {} })
        .find((x) => x.key === 'chargers');
    const labels = g.more.filter((p) => typeof p === 'string');
    assert.ok(labels.some((l) => l.startsWith('Keba · Next_more_finish_by_departure')), JSON.stringify(labels));
    assert.ok(!labels.some((l) => /· next_more_/.test(l)));
});

test('L: the setup row shows an info icon while things are open, a check mark when all is done', () => {
    const open = mount('sem-next-system-card', { 'sensor.sem_diag_charger_control': S('number', { setup_checklist: { items: [], done: 3, total: 3, repairs: { count: 2, first: 'x' } } }) });
    assert.match(text(open._setupRow()), /mdi:information-outline/);
    assert.doesNotMatch(text(open._setupRow()), /mdi:check-decagram/);
});

test('L: the Now checklist header shows an info icon, not a check mark, while checks are open', () => {
    const el = mount('sem-setup-checklist-card', {});
    const open = text(el._complete({ repairs: { count: 2, first: 'x' } }));
    assert.match(open, /mdi:information-outline/);
    assert.doesNotMatch(open, /<ha-icon class=ok icon=mdi:check-circle>/);
    assert.match(text(el._complete({ repairs: { count: 0 } })), /<ha-icon class=ok icon=mdi:check-circle>/);
});

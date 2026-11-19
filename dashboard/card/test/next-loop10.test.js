// (#1321) review loop 10: a run under way, the planner's need, the battery sentence,
// not-set capacity, off devices, and the small wording fixes. Clocks are pinned.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mount, S, text } from './card-harness.js';
import { planRuns, planRunsRounded, kwhAhead, nextRun, demandFigures, shortfalls } from '../src/util/plan-facts.js';
import { statePill } from '../src/util/next-devices.js';
import { heaterSays } from '../src/util/heater-questions.js';
import { batteryNeedText, batteryFactsFrom } from '../src/util/next-battery-line.js';
import { groups, slotText } from '../src/util/next-settings.js';
import { offStartReason } from '../src/util/why-rows.js';
import { planLead } from '../src/util/next-lead.js';
import { gotCheapest } from '../src/util/plan-why.js';
import { nightStart } from '../src/util/next-today-rows.js';

const at = (h, m = 0) => Date.parse(`2026-11-18T${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:00+01:00`);
const iso = (ms) => new Date(ms).toISOString();
const PIN = at(13, 45);
// the car's run 12:45 to 14:45 at 4 kW (8 kWh), a second run 16:00 to 17:00
const BLOCKS = [
    { id: 'ev:keba', start: iso(at(12, 45)), end: iso(at(14, 45)), power_w: 4000 },
    { id: 'ev:keba', start: iso(at(16)), end: iso(at(17)), power_w: 4000 },
];
const is = (id) => (x) => x === id;

test('1: before, inside and after a run, one helper says what is running and what is ahead', () => {
    const before = planRuns({ blocks: BLOCKS }, is('ev:keba'), at(12));
    assert.equal(before[0].running, false);
    assert.equal(nextRun(before, at(12)).s, at(12, 45));
    assert.equal(kwhAhead({ blocks: BLOCKS }, is('ev:keba'), at(12)), 12);

    const inside = planRuns({ blocks: BLOCKS }, is('ev:keba'), PIN);
    assert.equal(inside[0].running, true);
    assert.equal(nextRun(inside, PIN).e, at(14, 45), 'the run under way is the next run');
    assert.equal(inside[0].kwh, 8, 'a run keeps its whole kWh');
    assert.ok(Math.abs(kwhAhead({ blocks: BLOCKS }, is('ev:keba'), PIN) - (4 + 4)) < 1e-9, 'half of 8 kWh plus the 4 kWh run');

    const after = planRuns({ blocks: BLOCKS }, is('ev:keba'), at(15));
    assert.equal(after.length, 1);
    assert.equal(nextRun(after, at(15)).s, at(16));
    assert.equal(planRunsRounded({ blocks: BLOCKS }, is('ev:keba'), PIN)[0].running, true);
});

test('2: needed_kwh is the remaining need at computed_at; only what ran since then comes off', () => {
    // planner shape at 13:30: 6 kWh still needed, the ended 12:00-13:00 run is past, 2 kWh planned ahead
    const plan = {
        computed_at: iso(at(13, 30)),
        blocks: [
            { id: 'ev:keba', start: iso(at(12)), end: iso(at(13)), power_w: 4000 },
            { id: 'ev:keba', start: iso(at(15)), end: iso(at(15, 30)), power_w: 4000 },
        ],
        demands: [{ id: 'ev:keba', status: 'partial', planned_kwh: 2, needed_kwh: 6 }],
    };
    const f = demandFigures(plan, 'ev:keba', at(14));
    assert.deepEqual(f, { planned: 2, needed: 6 }, 'the block that ended before the plan was made is not subtracted again');
    assert.deepEqual(shortfalls(plan, at(14)), [{ id: 'ev:keba', planned: 2, needed: 6 }], 'a real shortfall is not hidden');
});

test('2: a run that went on after computed_at does come off the need', () => {
    const plan = {
        computed_at: iso(at(13, 30)),
        blocks: [{ id: 'ev:keba', start: iso(at(13)), end: iso(at(15)), power_w: 4000 }],
        demands: [{ id: 'ev:keba', status: 'fits', planned_kwh: 6, needed_kwh: 6 }],
    };
    // 14:00: 0.5 h = 2 kWh delivered since 13:30; 2 kWh needed less, 6 kWh of the run still ahead
    const f = demandFigures(plan, 'ev:keba', at(14));
    assert.equal(f.needed, 4);
    assert.equal(f.planned, 4);
    assert.deepEqual(shortfalls(plan, at(14)), []);
});

test('2: without computed_at nothing is subtracted (needed_kwh already is the remaining need)', () => {
    const plan = { blocks: [BLOCKS[0]], demands: [{ id: 'ev:keba', status: 'fits', needed_kwh: 5 }] };
    assert.equal(demandFigures(plan, 'ev:keba', at(15)).needed, 5);
});

test('1: Devices pill and next-run line name the end of a run under way, watch-only says would', (t) => {
    t.mock.timers.enable({ apis: ['Date'], now: PIN });
    const plan = S('ok', { computed_at: iso(at(13, 40)), blocks: BLOCKS, demands: [{ id: 'ev:keba', needed_kwh: 12 }] });
    const el = mount('sem-next-devices-card', { 'sensor.sem_energy_plan': plan, 'switch.sem_observer_mode': S('off') });
    assert.equal(el._plannedAt('ev:keba'), '', 'no "waits for" while the run is under way');
    assert.equal(el._plannedUntil('ev:keba'), '14:45');
    const later = mount('sem-next-devices-card', { 'sensor.sem_energy_plan': S('ok', { blocks: [BLOCKS[1]] }) });
    assert.equal(later._plannedAt('ev:keba'), '16:00');
    assert.equal(later._plannedUntil('ev:keba'), '');
    const car = { type: 'charger', mergedMode: 'solar' };
    assert.equal(statePill(car, { plannedUntil: '14:45' }).key, 'next_st_charges_until');
    assert.equal(statePill(car, { plannedUntil: '14:45', observer: true }).key, 'next_st_would_charge_until');
    const load = { type: 'load', mergedMode: 'auto' };
    assert.equal(statePill(load, { plannedUntil: '14:45', observer: true }).key, 'next_st_would_run_until');
    assert.equal(statePill(load, { plannedUntil: '14:45' }).key, 'next_st_runs_until');
    assert.equal(statePill(load, { plannedAt: '16:00' }).key, 'next_st_waits_for');
});

test('1: a heater with a run under way says until, not a later start', () => {
    const row = { comfort: { keep_c: 52, max_c: 56, start_c: 50, reading_c: 45 }, mergedMode: 'auto' };
    assert.equal(heaterSays(row, { plannedAt: '16:00', plannedUntil: '14:45' }, false).key, 'hq_st_heats_until');
    assert.equal(heaterSays(row, { plannedUntil: '14:45', observer: true }, false).key, 'hq_st_would_heat_until');
});

test('1: the Now screen names the run under way and what is left of it', (t) => {
    t.mock.timers.enable({ apis: ['Date'], now: PIN });
    const states = { 'sensor.sem_energy_plan': S('ok', { computed_at: iso(at(13, 40)), blocks: BLOCKS, demands: [{ id: 'ev:keba', needed_kwh: 12 }] }),
        'switch.sem_observer_mode': S('off') };
    const el = mount('sem-next-now-card', states);
    const b = el._nextBlock((id) => id === 'ev:keba');
    assert.equal(b.running, true);
    assert.equal(b.until, '14:45');
    assert.equal(b.kwh, '4.0', 'only the rest of the run');
});

test('3: the battery sentence names what a full battery gives, or what is above the reserve now', () => {
    const tf = (k, p) => `${k}|${Object.entries(p).map(([a, b]) => `${a}=${b}`).join(',')}`;
    const t = (k) => k;
    const short = batteryNeedText(tf, t, { phase: 'holding', floor: 100, need: 11.68, soc: 32, avail: 10.18, now: 1.5 });
    assert.equal(short, 'next_batt_need_all|need=11.7,avail=10.2');
    const room = batteryNeedText(tf, t, { phase: 'holding', floor: 100, need: 8, soc: 32, avail: 10.18, now: 1.5 });
    assert.equal(room, 'next_batt_need_now|need=8.0,now=1.5');
    const full = batteryNeedText(tf, t, { phase: 'holding', floor: 100, need: 8, soc: 100, avail: 10.18, now: 10.18 });
    assert.equal(full, 'next_batt_need_hold|need=8.0');
});

test('3: the facts carry the kWh above the reserve now, from the real battery states', () => {
    const states = {
        'sensor.sem_battery_soc': S(32), 'number.sem_battery_reserve_soc': S(20),
        'sensor.sem_battery_spendable_kwh': S(0, { phase: 'holding', overnight_need_kwh: 11.7 }),
        'number.sem_battery_capacity': S(12, { unit_of_measurement: 'kWh' }),
    };
    const f = batteryFactsFrom(states);
    if (f.avail !== null) assert.ok(f.now < f.avail, 'now is less than a full battery gives');
});

test('4: a capacity the server calls unset says not set in All settings, as Devices does', () => {
    const chargers = [{ cid: 'keba', name: 'Keba', id: 'keba' }];
    const mk = (attrs) => ({
        'switch.sem_observer_mode': S('off'),
        'number.sem_charger_keba_ev_battery_capacity_kwh': S(40, { min: 5, max: 200, step: 1, unit_of_measurement: 'kWh', ...attrs }),
        'number.sem_charger_keba_ev_kwh_per_100km': S(18, { min: 5, max: 50, step: 0.5, unit_of_measurement: 'kWh/100km' }),
    });
    const tt = (k) => k;
    const slots = (states) => groups(states, tt, { options: { ev_chargers: chargers }, currency: 'CHF', chargers, labels: {} })
        .find((x) => x.key === 'chargers').more.filter((p) => p && typeof p === 'object' && p.kind === 'number');
    const unset = slots(mk({ set_by_user: false }));
    const cap = unset.find((s) => /ev_battery_capacity/.test(s.id));
    assert.equal(slotText(cap, tt), 'next_not_set');
    assert.equal(slotText(slots(mk({ set_by_user: true })).find((s) => /ev_battery_capacity/.test(s.id)), tt), '40 kWh');
    assert.equal(slotText(cap, tt, 55), '55 kWh', 'a value the owner stages shows as typed');
    // the unit the entity sends reads with a space, like every other screen
    assert.match(slotText(unset.find((s) => /per_100km/.test(s.id)), tt), /kWh\/100 km$/);
});

test('low: a power of 1 kW or more reads in kW', () => {
    const slot = { kind: 'number', value: 2000, unit: 'W', step: 50 };
    assert.equal(slotText(slot, (k) => k), '2.0 kW');
    assert.equal(slotText({ ...slot, value: 2250 }, (k) => k), '2.25 kW');
    assert.equal(slotText({ ...slot, value: 800 }, (k) => k), '800 W');
});

test('5: a load that is off never reads "so it runs": the start line, in System and Plan', (t) => {
    t.mock.timers.enable({ apis: ['Date'], now: PIN });
    const WORDS = { next_would_switch_on: 'would switch on', next_switches_soon: 'switches on soon', why_short_solar: 'enough spare sun' };
    const tr = (k) => WORDS[k] || k;
    const realLocalize = globalThis.semLocalize;
    globalThis.semLocalize = (k) => WORDS[k] || k;
    t.after(() => { globalThis.semLocalize = realLocalize; });
    const rec = { kind: 'load', device_kind: 'load', device_id: 'boiler', reason_code: 'solar' };
    assert.equal(offStartReason(rec, false, true, tr), 'would switch on: enough spare sun');
    assert.equal(offStartReason(rec, true, true, tr), '', 'a load that runs keeps its own sentence');
    assert.equal(offStartReason({ ...rec, kind: 'charger', device_kind: 'charger' }, false, true, tr), '');
    const devices = { boiler: { name: 'Boiler', is_on: false, switch_entity: 'switch.boiler' } };
    const states = { 'sensor.sem_controllable_devices_count': S(1, { devices }), 'switch.boiler': S('off'), 'switch.sem_observer_mode': S('on') };
    const plan = mount('sem-next-plan-card', states);
    assert.equal(plan._offStart(rec), 'would switch on: enough spare sun');
    const on = mount('sem-next-plan-card', { ...states, 'sensor.sem_controllable_devices_count': S(1, { devices: { boiler: { ...devices.boiler, is_on: true } } }), 'switch.boiler': S('on') });
    assert.equal(on._offStart(rec), '');
});

test('low: the plan line says cost is unknown only when a run lacks a price', () => {
    const plan = { computed_at: iso(at(13, 40)), blocks: [{ id: 'ev:keba', start: iso(at(15)), end: iso(at(16)), power_w: 4000 }], demands: [] };
    const base = { computedAt: '13:40', fitsKey: 'fits', sunTomorrowKwh: 20, nowMs: PIN };
    assert.equal(planLead(plan, { ...base, costMissing: false }).sub.key, 'next_plan_sub_plain');
    assert.equal(planLead(plan, { ...base, costMissing: true }).sub.key, 'next_plan_sub_nocost');
    assert.equal(planLead(plan, { ...base, costMissing: true, costUnknownFor: 'Keba' }).sub.key, 'next_plan_sub_nocost_who');
    assert.equal(planLead(plan, { ...base, cost: '2.10 CHF', costMissing: false }).sub.key, 'next_plan_sub');
});

test('low: the Plan card sees a missing price per run, with a total or without', () => {
    const el = mount('sem-next-plan-card', {});
    const priced = { blocks: BLOCKS, demands: [{ id: 'ev:keba', est_cost: 1.2 }] };
    const unpriced = { blocks: BLOCKS, demands: [{ id: 'ev:keba', est_cost: null }] };
    assert.equal(el._costMissing(priced), false);
    assert.equal(el._costMissing(unpriced), true);
});

test('low: a gap in the price list does not stretch one cell across it', () => {
    const t = (h, p) => ({ t: iso(at(h)), price: p });
    // hours 13,14,15 then a gap to 19,20; 15 costs 0.1 and would last 4 h without the cap
    const up = [t(13, 0.5), t(14, 0.5), t(15, 0.1), t(19, 0.5), t(20, 0.5)];
    const runs = [{ s: at(13), e: at(16) }];
    assert.equal(gotCheapest({}, runs, 0.2, at(12), up), true, 'the cell at 15 lasts two hours, not four');
});

test('low: tonight starts when the lead says, from the night start sensor', () => {
    const attrs = { today_plan: [{ kind: 'night_open', when: iso(at(18, 40)) }, { kind: 'night_end', when: iso(at(6) + 864e5) }] };
    assert.equal(nightStart(attrs, PIN), at(18, 40), 'no clock: the list');
    // half an hour from now on the viewer's own clock, whatever zone the test runs in
    const local = new Date(PIN + 30 * 60e3), clock = `${String(local.getHours()).padStart(2, '0')}:${String(local.getMinutes()).padStart(2, '0')}`;
    local.setSeconds(0, 0);
    assert.equal(nightStart(attrs, PIN, clock), local.getTime(), 'the sensor names the hour');
    assert.equal(nightStart({ today_plan: [{ kind: 'night_end', when: iso(at(20)) }] }, PIN, clock), -Infinity, 'under way stays under way');
});

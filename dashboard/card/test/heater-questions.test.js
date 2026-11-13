/**
 * (#1349) A heater's settings as four plain questions — the ONE model the
 * Load Priority card and the SEM Next Devices card share.
 *
 * Cases A, B, C are the approved mockup: a tank waiting for its planned
 * hour, the same tank with buying off, and a load without a thermometer.
 *
 * Run: `npm test` (from dashboard/card).
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {
    heaterSays, heaterSub, heaterQuestions, sunMaxWrites, buySource, buyWrites,
    coldHeaters, nextBlock, becauseKey, asSentence, BUY_LABEL,
} from '../src/util/heater-questions.js';

const here = new URL('.', import.meta.url);
const words = JSON.parse(fs.readFileSync(new URL('../../translations.json', here), 'utf8'));
const classic = fs.readFileSync(new URL('../src/cards/sem-load-priority-card.js', here), 'utf8');
const planCard = fs.readFileSync(new URL('../src/cards/sem-energy-plan-card.js', here), 'utf8');

const band = (reading, over = {}) => ({
    state: 'willing', hvac: 'heat', reading_c: reading,
    keep_c: 52, start_c: 51, max_c: 56, limit_c: 36, own_run: false, may_buy: true, ...over,
});
const GOALS = { comfort_target: '52', comfort_offset: '4', comfort_limit: '36', top_up_policy: 'cheap_hours' };
const T = { fmtTemp: (c) => c + ' °C' };

test('case A: a tank waiting for its planned hour says when, and that sun is free', () => {
    const row = { comfort: band(45.8), intent: { on: false, source: null, code: 'plan_wait' }, mergedMode: 'solar_only' };
    const says = heaterSays(row, { ...T, plannedAt: '23:00' }, false);
    assert.equal(says.key, 'hq_st_heats_at');
    assert.deepEqual(says.params, { keep: '52 °C', time: '23:00' });
    assert.deepEqual(heaterSub(says, row, T), { key: 'hq_sub_sun_free', params: {} });
    const q = heaterQuestions({ goals: GOALS, comfort: row.comfort }, { hasBattery: true });
    assert.equal(q.view, 'band');
    assert.deepEqual([q.keep, q.floor, q.sunMax, q.buy], [52, 36, 56, 'grid']);
    // (#1349) with a house battery the battery choice is offered here too:
    // it reaches Keep at at night, above the battery's reserve
    assert.deepEqual(q.buyChoices, ['off', 'grid', 'battery']);
    assert.equal(q.buySubKey, 'hq_buy_sub_band');
    assert.equal(q.buySubBatteryKey, 'hq_buy_sub_band_battery');
    const noBatt = heaterQuestions({ goals: GOALS, comfort: row.comfort });
    assert.deepEqual(noBatt.buyChoices, ['off', 'grid']);
    assert.equal(noBatt.buySubBatteryKey, null);
});

test('case B: the same tank with buying off waits for sun and says SEM buys nothing', () => {
    const row = { comfort: band(45.8, { may_buy: false }), intent: { on: false, source: null, code: 'no_source' }, mergedMode: 'solar_only' };
    const says = heaterSays(row, T, false);
    assert.equal(says.key, 'hq_st_waits_sun');
    assert.equal(says.noBuy, true);
    assert.deepEqual(heaterSub(says, row, T), { key: 'hq_sub_no_buy', params: { limit: '36 °C' } });
    const q = heaterQuestions({ goals: { ...GOALS, top_up_policy: 'solar_only' }, comfort: row.comfort });
    assert.equal(q.buy, 'off');
});

test('case C: a load without a thermometer shows its run time, and may finish from the battery', () => {
    const q = heaterQuestions({ goals: { daily_min_runtime_min: '60', top_up_policy: 'solar_only' }, comfort: null }, { hasBattery: true });
    assert.equal(q.view, 'time');
    assert.deepEqual(q.buyChoices, ['off', 'grid', 'battery']);
    assert.equal(q.buySubKey, 'hq_buy_sub_time');
    assert.equal(heaterSays({ comfort: null, intent: null, mergedMode: 'solar_only' }, T, false), null);
    // no house battery: the choice is not offered, and a stored one reads as off
    const noBatt = heaterQuestions({ goals: { battery_eligible_overnight: true }, comfort: null }, { hasBattery: false });
    assert.deepEqual(noBatt.buyChoices, ['off', 'grid']);
    assert.equal(noBatt.buy, 'off');
});

test('every other state of a heater has its own words', () => {
    const say = (reading, intent, over = {}, live = T, running = false) =>
        heaterSays({ comfort: band(reading, over), intent, mergedMode: 'solar_only' }, live, running);
    assert.equal(say(52.4, null).key, 'hq_st_warm');
    assert.equal(say(51.5, null).key, 'hq_st_warm_again');
    assert.equal(say(null, null).key, 'hq_st_no_reading');
    const none = say(45, { on: false, code: 'peak_shed' });
    assert.equal(none.key, 'hq_st_below_none');
    assert.equal(none.why, 'hq_because_peak');
    assert.equal(say(34, { on: true, code: 'comfort_floor' }, {}, T, true).key, 'hq_st_too_cold');
    assert.equal(say(45, { on: true, code: 'comfort_goal' }, {}, T, true).key, 'hq_st_heating_to');
    assert.equal(say(45, { on: true, source: 'solar', code: 'solar' }, {}, T, true).key, 'hq_st_heating_sun');
    assert.equal(say(55, { on: true, code: 'legionella' }, { own_run: true }, T, true).key, 'hq_st_legionella');
    // Mode Off is not this sentence
    assert.equal(heaterSays({ comfort: band(45), mergedMode: 'off' }, T), null);
    assert.equal(becauseKey({ on: true, code: 'peak_shed' }), '');
});

test('"heat up to" is absolute; the stored value stays the offset above Keep at', () => {
    assert.deepEqual(sunMaxWrites({ id: 'energy_dashboard_boiler', keep: 52 }, '56'),
        { writes: [{ property: 'comfort_offset', value: '4' }], option: null });
    assert.deepEqual(sunMaxWrites({ id: 'energy_dashboard_boiler', keep: 52 }, 52).writes,
        [{ property: 'comfort_offset', value: '0' }]);
    // half-degree steps
    assert.equal(sunMaxWrites({ id: 'x', keep: 52 }, 54.6).writes[0].value, '2.5');
});

test('a value below Keep at is refused, with the reason', () => {
    assert.deepEqual(sunMaxWrites({ id: 'x', keep: 52 }, 50), { error: 'hq_err_below_keep', params: { keep: '52' } });
    assert.equal(sunMaxWrites({ id: 'x', keep: 52 }, '').error, 'hq_err_below_keep');
});

test('a hot-water tank also sets the Solar target, so both stops agree', () => {
    const res = sunMaxWrites({ id: 'hot_water', keep: 52 }, 56, { min: 30, max: 80 });
    assert.deepEqual(res.option, { key: 'hot_water_solar_target', value: 56 });
    assert.deepEqual(sunMaxWrites({ id: 'hot_water', keep: 52 }, 85, { min: 30, max: 80 }),
        { error: 'hq_err_above_max', params: { max: '80' } });
    assert.equal(sunMaxWrites({ id: 'energy_dashboard_rod', keep: 52 }, 85, { max: 80 }).option, null);
});

test('the buy question writes exactly the two flags the old picker wrote', () => {
    assert.deepEqual(buyWrites('grid'), [
        { property: 'battery_eligible_overnight', value: 'false' },
        { property: 'top_up_policy', value: 'cheap_hours' }]);
    assert.deepEqual(buyWrites('battery'), [
        { property: 'battery_eligible_overnight', value: 'true' },
        { property: 'top_up_policy', value: 'solar_only' }]);
    assert.deepEqual(buyWrites('off'), [
        { property: 'battery_eligible_overnight', value: 'false' },
        { property: 'top_up_policy', value: 'solar_only' }]);
    assert.equal(buySource({ top_up_policy: 'cheap_hours' }), 'grid');
    assert.equal(buySource({ battery_eligible_overnight: true, top_up_policy: 'cheap_hours' }), 'battery');
    assert.equal(buySource(null), 'off');
});

const coolBand = (reading, over = {}) => ({
    state: 'willing', hvac: 'cool', reading_c: reading,
    keep_c: 24, start_c: 25, max_c: 22, limit_c: 27, own_run: false, may_buy: true, ...over,
});
const COOL_GOALS = { comfort_target: '24', comfort_offset: '2', comfort_limit: '27', top_up_policy: 'cheap_hours' };

test('a cooling band asks the same four questions, turned round', () => {
    const q = heaterQuestions({ goals: COOL_GOALS, comfort: { hvac: 'cool' } });
    assert.equal(q.view, 'band');
    assert.equal(q.cooling, true);
    // "cool down to" is absolute and BELOW Keep at
    assert.deepEqual([q.keep, q.floor, q.sunMax, q.buy], [24, 27, 22, 'grid']);
    assert.deepEqual(q.keys, { keepSub: 'hq_keep_sub_cool', floor: 'hq_ceiling', floorSub: 'hq_ceiling_sub',
        sunMax: 'hq_sun_min', sunMaxSub: 'hq_sun_min_sub' });
    // a heater keeps its own words
    assert.equal(heaterQuestions({ goals: GOALS, comfort: band(45) }).keys.floor, 'hq_floor');
    // "cool down to 21" stores an offset of 3; above Keep at is refused
    assert.deepEqual(sunMaxWrites({ id: 'ac', keep: 24, cooling: true }, 21).writes,
        [{ property: 'comfort_offset', value: '3' }]);
    assert.equal(sunMaxWrites({ id: 'ac', keep: 24, cooling: true }, 21).option, null);
    assert.deepEqual(sunMaxWrites({ id: 'ac', keep: 24, cooling: true }, 25),
        { error: 'hq_err_above_keep', params: { keep: '24' } });
});

test('a cooling band says the same things with its own words', () => {
    const say = (reading, intent, over = {}, live = T, running = false) =>
        heaterSays({ comfort: coolBand(reading, over), intent, mergedMode: 'solar_only' }, live, running);
    assert.equal(say(23.5, null).key, 'hq_st_cool');
    assert.equal(say(24.5, null).key, 'hq_st_cool_again');
    assert.deepEqual(say(26, { on: false, code: 'plan_wait' }, {}, { ...T, plannedAt: '13:00' }),
        { key: 'hq_st_cools_at', params: { keep: '24 °C', time: '13:00' }, cls: '', why: '', cool: true, next: true });
    assert.equal(say(26, { on: false, code: 'no_source' }).key, 'hq_st_above_none');
    const noBuy = say(26, { on: false, code: 'no_source' }, { may_buy: false });
    assert.equal(noBuy.key, 'hq_st_waits_sun_cool');
    assert.deepEqual(heaterSub(noBuy, { comfort: coolBand(26) }, T), { key: 'hq_sub_no_buy_cool', params: { limit: '27 °C' } });
    assert.equal(heaterSub(say(26, null, {}, { ...T, plannedAt: '13:00' }), {}, T).key, 'hq_sub_sun_free_cool');
    assert.equal(say(28, { on: true, code: 'comfort_floor' }, {}, T, true).key, 'hq_st_too_warm');
    assert.equal(say(26, { on: true, code: 'comfort_goal' }, {}, T, true).key, 'hq_st_cooling_to');
    assert.equal(say(26, { on: true, source: 'solar', code: 'solar' }, {}, T, true).key, 'hq_st_cooling_sun');
    assert.equal(say(null, null).key, 'hq_st_no_reading');
});

test('a unit that picks its season says which one it is in', () => {
    const g = { ...COOL_GOALS, hvac_mode: 'by_forecast' };
    assert.equal(heaterQuestions({ goals: g, comfort: { hvac: 'cool' } }).season, 'hq_season_cooling');
    assert.equal(heaterQuestions({ goals: { ...GOALS, hvac_mode: 'by_forecast' }, comfort: band(45) }).season, 'hq_season_heating');
    assert.equal(heaterQuestions({ goals: GOALS, comfort: band(45) }).season, null);
});

test('the battery choice: it heats tonight from the house battery, or waits at the reserve', () => {
    const say = (intent, over = {}, live = T, running = false) =>
        heaterSays({ comfort: band(45, { may_buy: false, may_use_battery: true, ...over }), intent, mergedMode: 'solar_only' }, live, running);
    assert.deepEqual(say({ on: false, code: 'no_source' }),
        { key: 'hq_st_heats_tonight_battery', params: { keep: '52 °C' }, cls: '', why: '', next: true, battery: true });
    assert.equal(say({ on: false, code: 'battery_reserve' }).key, 'hq_st_waits_battery');
    assert.equal(say({ on: true, source: 'tier2_battery', code: 'comfort_goal_battery' }, {}, T, true).key, 'hq_st_heating_battery');
    // a planned hour ahead still wins the sentence
    assert.equal(say({ on: false, code: 'plan_wait' }, {}, { ...T, plannedAt: '02:00' }).key, 'hq_st_heats_at');
    assert.equal(becauseKey({ on: false, code: 'battery_reserve' }), 'hq_because_battery_reserve');
    // the stored value is the old picker's
    assert.equal(heaterQuestions({ goals: { ...GOALS, top_up_policy: 'solar_only', battery_eligible_overnight: true }, comfort: band(45) }, { hasBattery: true }).buy, 'battery');
    assert.equal(heaterQuestions({ goals: { ...GOALS, top_up_policy: 'solar_only', battery_eligible_overnight: true }, comfort: band(45) }).buy, 'off');
});

test('the plan names a heater below its line that has no hour — unless buying is off', () => {
    const now = Date.parse('2026-11-12T12:00:00Z');
    const devs = {
        boiler: { name: 'Boiler', control_mode: 'surplus', comfort: band(45) },
        sunny: { name: 'Sunny', control_mode: 'surplus', comfort: band(45, { may_buy: false }) },
        warm: { name: 'Warm', control_mode: 'surplus', comfort: band(52.5) },
    };
    assert.deepEqual(coldHeaters(devs, [], now), [{ id: 'boiler', name: 'Boiler', keepC: 52 }]);
    const block = [{ id: 'comfort:boiler', start: '2026-11-12T23:00:00Z', end: '2026-11-13T00:30:00Z' }];
    assert.deepEqual(coldHeaters(devs, block, now), []);
    // a cooler above its line is named too, and marked for its words
    const ac = { ac: { name: 'AC', control_mode: 'surplus', comfort: coolBand(26) }, fine: { name: 'Fine', control_mode: 'surplus', comfort: coolBand(24.5) } };
    assert.deepEqual(coldHeaters(ac, [], now), [{ id: 'ac', name: 'AC', keepC: 24, cool: true }]);
    assert.equal(nextBlock(block, ['load:boiler', 'comfort:boiler'], now).id, 'comfort:boiler');
    assert.equal(nextBlock(block, ['load:other'], now), null);
});

test('a short status reads as a sentence', () => {
    assert.equal(asSentence('heats to 52 °C at 23:00'), 'Heats to 52 °C at 23:00.');
    assert.equal(asSentence('done.'), 'Done.');
    assert.equal(asSentence(''), '');
});

test('every text of the model exists in every language', () => {
    const src = fs.readFileSync(new URL('../src/util/heater-questions.js', here), 'utf8');
    const keys = new Set([...src.matchAll(/'(hq_[a-z_]+)'/g)].map((m) => m[1]));
    for (const k of ['hq_now', 'hq_keep', 'hq_keep_sub', 'hq_floor', 'hq_floor_sub', 'hq_sun_max', 'hq_sun_max_sub',
        'hq_plan_above_no_hour', 'hq_plan_above_no_hour_plain',
        'hq_buy', 'hq_more', 'hq_run_each_day', 'hq_run_each_day_sub', 'hq_plan_below_no_hour', 'hq_plan_below_no_hour_plain',
        ...Object.values(BUY_LABEL)]) keys.add(k);
    assert.ok(keys.size > 35);
    for (const [lang, table] of Object.entries(words)) {
        for (const key of keys) assert.ok(table[key], lang + ' lacks ' + key);
    }
});

test('the classic card asks the shared model, and the old chip words are gone for heaters', () => {
    assert.ok(classic.includes("from '../util/heater-questions.js'"));
    for (const fn of ['heaterSays(', 'heaterQuestions(', 'sunMaxWrites(', 'heaterSub(']) assert.ok(classic.includes(fn), fn);
    // one band view for heating and cooling; the words come from the model
    assert.ok(classic.includes("q.view === 'band'") && !classic.includes("q.view === 'cool'"));
    assert.ok(classic.includes('q.keys.floor') && classic.includes('q.keys.sunMax') && classic.includes('cooling: q.cooling'));
    // the run-time progress is hidden when the thermometer leads
    assert.ok(classic.includes("this._questions(device).view === 'band'"));
    assert.ok(planCard.includes('coldHeaters('));
});

test('a load\'s mode says who runs it — no "Solar only" beside the buy question', () => {
    for (const old of ["'mode_solar_only'", "'mode_solar_battery'", "'mode_tooltip'", "'help_mode_surplus'", "'battery_overnight_hint'"]) {
        assert.ok(!classic.includes(old), old + ' is still on the load card');
    }
    for (const k of ['load_mode_sem', 'load_mode_sem_battery', 'load_mode_help_sem', 'load_mode_help_sem_battery', 'load_mode_tooltip']) {
        assert.ok(classic.includes("'" + k + "'"), k);
        for (const [lang, table] of Object.entries(words)) assert.ok(table[k], lang + ' lacks ' + k);
    }
    // a car's charge modes keep their names
    assert.equal(words.en.charge_mode_solar_only !== undefined, true);
});

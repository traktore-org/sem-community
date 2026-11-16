/**
 * (#1081) The pre-heat tick "Also in the cheapest-heat hours" under the sun
 * row of a heater's questions, and the sentences that say it.
 *
 * Run: `npm test` (from dashboard/card).
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {
    heaterSays, heaterSub, heaterQuestions, preheatWrites, preheatOn,
} from '../src/util/heater-questions.js';

const here = new URL('.', import.meta.url);
const words = JSON.parse(fs.readFileSync(new URL('../../translations.json', here), 'utf8'));
const classic = fs.readFileSync(new URL('../src/cards/sem-load-priority-card.js', here), 'utf8');

const band = (reading, over = {}) => ({
    state: 'willing', hvac: 'heat', reading_c: reading,
    keep_c: 52, start_c: 51, max_c: 56, limit_c: 36, own_run: false, may_buy: true,
    preheat: true, preheat_ok: true, anchored: false, ...over,
});
const GOALS = { comfort_target: '52', comfort_offset: '4', comfort_limit: '36', top_up_policy: 'cheap_hours' };
const T = { fmtTemp: (c) => c + ' °C' };

test('the tick shows for a band load that is not on its own setpoint', () => {
    const q = heaterQuestions({ goals: GOALS, comfort: band(47) });
    assert.deepEqual(q.preheat, { offered: true, on: false, enabled: true });
    assert.equal(heaterQuestions({ goals: { ...GOALS, preheat: 'true' }, comfort: band(47) }).preheat.on, true);
    assert.equal(heaterQuestions({ goals: { ...GOALS, preheat: true }, comfort: band(47) }).preheat.on, true);
});

test('it is not offered to a unit on its own setpoint, a cooler, or a load the engine rules out', () => {
    const riding = heaterQuestions({ goals: GOALS, comfort: band(47, { anchored: true }) });
    assert.equal(riding.preheat.offered, false);
    const climate = heaterQuestions({ goals: GOALS, comfort: band(47, { preheat_ok: false }) });
    assert.equal(climate.preheat.offered, false);
    const old = heaterQuestions({ goals: GOALS, comfort: { ...band(47), preheat_ok: undefined } });
    assert.equal(old.preheat.offered, false);
    const cool = heaterQuestions({
        goals: { comfort_target: '24', comfort_offset: '2', comfort_limit: '28', top_up_policy: 'cheap_hours', hvac_mode: 'cool' },
        comfort: band(25, { hvac: 'cool', keep_c: 24, max_c: 22, limit_c: 28 }),
    });
    assert.equal(cool.preheat.offered, false);
    // a load without a band has no question at all
    assert.equal(heaterQuestions({ goals: { daily_min_runtime_min: '60' }, comfort: null }).preheat, undefined);
});

test('without buying allowed it is disabled', () => {
    const off = heaterQuestions({ goals: { ...GOALS, top_up_policy: 'solar_only', preheat: 'true' }, comfort: band(47, { may_buy: false }) });
    assert.equal(off.preheat.offered, true);
    assert.equal(off.preheat.enabled, false);
    const battery = heaterQuestions({ goals: { ...GOALS, battery_eligible_overnight: 'true' }, comfort: band(47) }, { hasBattery: true });
    assert.equal(battery.preheat.enabled, false);
});

test('the write is the stored goal as a bool string', () => {
    assert.deepEqual(preheatWrites(true), [{ property: 'preheat', value: 'true' }]);
    assert.deepEqual(preheatWrites(false), [{ property: 'preheat', value: 'false' }]);
});

test('the card draws the tick under the sun row, disabled without buy, and writes it', () => {
    const sun = classic.indexOf("q.keys.sunMax), this._t(q.keys.sunMaxSub)");
    const tick = classic.indexOf('this._renderPreheatTick(device, q)');
    assert.ok(sun > 0 && tick > sun, 'the tick comes after the sun row');
    assert.ok(classic.includes('preheatWrites(e.target.checked)'));
    assert.ok(classic.includes('?disabled=${!pre.enabled}'));
    assert.ok(classic.includes("'hq_sub_no_buy'"), 'the existing no-buy words');
    assert.ok(classic.includes("'hq_preheat_sub'"));
    // never a backtick inside the lit template of the tick
    const body = classic.slice(classic.indexOf('_renderPreheatTick(device, q) {'), classic.indexOf('_renderBuyQuestion(device, q) {'));
    const tpl = body.slice(body.indexOf('return html`'));
    assert.equal((tpl.match(/`/g) || []).length, 2);
});

test('a planned pre-heat says it, with the top and the start', () => {
    const row = { comfort: band(46), intent: { on: false, source: null, code: 'plan_wait' }, mergedMode: 'solar_only' };
    const says = heaterSays(row, { ...T, plannedAt: '23:00' }, false);
    assert.equal(says.key, 'hq_st_preheats_at');
    assert.deepEqual(says.params, { top: '56 °C', start: '23:00' });
    assert.deepEqual(heaterSub(says, row, T), { key: 'hq_sub_sun_free', params: {} });
    // tick off: the sentence is what it was
    const plain = heaterSays({ ...row, comfort: band(46, { preheat: false }) }, { ...T, plannedAt: '23:00' }, false);
    assert.equal(plain.key, 'hq_st_heats_at');
    // a unit on its own setpoint keeps the old sentence
    const riding = heaterSays({ ...row, comfort: band(46, { anchored: true }) }, { ...T, plannedAt: '23:00' }, false);
    assert.equal(riding.key, 'hq_st_heats_at');
});

test('a running pre-heat says it', () => {
    const row = { comfort: band(53), intent: { on: true, source: 'cheap_grid', code: 'comfort_goal' }, mergedMode: 'solar_only' };
    const says = heaterSays(row, T, true);
    assert.equal(says.key, 'hq_st_preheating');
    assert.deepEqual(says.params, { top: '56 °C' });
    const off = heaterSays({ ...row, comfort: band(53, { preheat: false }) }, T, true);
    assert.equal(off.key, 'hq_st_heating_to');
    assert.equal(preheatOn(band(53)), true);
    assert.equal(preheatOn(band(53, { preheat_ok: false })), false);
    assert.equal(preheatOn(null), false);
});

test('the new texts exist in every language, with their placeholders', () => {
    const need = { hq_preheat: [], hq_preheat_sub: [], hq_st_preheating: ['{top}'], hq_st_preheats_at: ['{top}', '{start}'] };
    assert.equal(Object.keys(words).length, 16);
    for (const [lang, table] of Object.entries(words)) {
        for (const [key, holes] of Object.entries(need)) {
            assert.ok(table[key], lang + ' lacks ' + key);
            for (const h of holes) assert.ok(table[key].includes(h), lang + ' ' + key + ' lacks ' + h);
        }
    }
    assert.equal(words.en.hq_preheat, 'Also in the cheapest-heat hours');
});

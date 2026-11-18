/**
 * (#1321) Review loop 6: no "needs 0.0" before data, rated size is not live power,
 * the surplus tile never contradicts itself, plain system headline, honest split,
 * a need only caps its own window.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { surplusInUse, ratedKey } from '../src/util/next-devices.js';
import { repairNames } from '../src/util/setup-checklist.js';
import { mount, text, S } from './card-harness.js';

const WORDS = { next_sys_lead_names: 'To check: {names}.' };
globalThis.semLocalize = (k) => WORDS[k] || k;

test('2: a device that is off or has no meter shows its rated size, never "~kW"', () => {
    assert.equal(ratedKey({ ratingMeasured: true }, 0), 'next_rated_x');
    assert.equal(ratedKey({ ratingMeasured: true }, null), 'next_rated_x_unmeasured');
    assert.equal(ratedKey({ ratingMeasured: false }, 0), 'next_rated_x_unmeasured');
});

test('2: the surplus tile: an estimate stays under the house draw; "left" is surplus minus measured use', () => {
    // 18.11. test system: surplus 1.9 kW, house 0.8 kW, boiler on with no meter (rated 3.0 kW)
    const rows = [{ type: 'load', name: 'Sim Boiler', isOn: true, rating: 3000, live: null }];
    const use = surplusInUse(rows, (r) => r.live, 800, 1900);
    assert.equal(use.estW, 800, 'never more than the house draws');
    assert.equal(use.leftW, null, 'a running device without a reading: left cannot be known');
    const metered = surplusInUse([{ type: 'load', name: 'Heater', isOn: true, rating: 600, live: 500 }], (r) => r.live, 800, 1900);
    assert.equal(metered.leftW, 1400, 'surplus 1.9 minus measured 0.5');
    assert.equal(surplusInUse([], () => null, 800, 1900).leftW, 1900, 'nothing runs: all of the surplus is left');
});


test('3: every thing to check is named in plain words; no "+1"', () => {
    const listed = [
        { domain: 'solar_energy_management', translation_key: 'old_install', ignored: false },
        { domain: 'solar_energy_management', translation_key: 'boiler', ignored: false },
        { domain: 'other', translation_key: 'x', ignored: false },
    ];
    const loc = (k) => ({ 'component.solar_energy_management.issues.old_install.title': 'Files from a previous SEM install were found',
        'component.solar_energy_management.issues.boiler.title': 'Sim Boiler has no power reading' }[k] || '');
    assert.deepEqual(repairNames({ count: 2, first: 'Files from a previous SEM install were found' }, listed, loc, (n) => `${n} more`),
        ['Files from a previous SEM install were found', 'Sim Boiler has no power reading']);
});

test('3: when HA gives no titles the published one stands and the rest is counted in words', () => {
    assert.deepEqual(repairNames({ count: 3, first: 'A' }, [], () => '', (n) => `${n} more to check`), ['A', '2 more to check']);
    assert.deepEqual(repairNames({ count: 1, first: 'A' }, [], () => '', () => 'x'), ['A']);
    assert.deepEqual(repairNames({ count: 0 }, [], () => '', () => 'x'), []);
});

test('3: System headline and Setup row name every thing to check (real-shaped states)', async () => {
    const el = mount('sem-next-system-card', {
        'sensor.sem_diag_grid_sign': S('negated'), 'sensor.sem_diag_battery_sign': S('normal'), 'switch.sem_observer_mode': S('on'),
        'sensor.sem_diag_charger_control': S('number', { setup_checklist: { items: [], done: 3, total: 3, repairs: { count: 2, first: 'Files from a previous SEM install were found' } } }),
    });
    const titles = { 'component.solar_energy_management.issues.a.title': 'Files from a previous SEM install were found',
        'component.solar_energy_management.issues.b.title': 'Sim Boiler has no power reading' };
    el.hass = { ...el._hass, localize: (k) => titles[k] || '', callWS: async () => ({ issues: [
        { domain: 'solar_energy_management', translation_key: 'a' }, { domain: 'solar_energy_management', translation_key: 'b' }] }) };
    el._checkNames();
    await new Promise((r) => setTimeout(r, 5));
    const out = text(el.render()) + text(el._setupRow());
    assert.ok(out.includes('Files from a previous SEM install were found, Sim Boiler has no power reading'), out.slice(0, 400));
    assert.doesNotMatch(out, /\+1/);
    assert.doesNotMatch(text(el._setupRow()), /next_grid_sign/);
});

import { splitParts } from '../src/util/next-split.js';

test('4: parts within 10 % of the total are scaled to it; further apart they stay raw with the gap named', () => {
    const near = splitParts([4.0, 4.2], 8.0, 1);
    assert.equal(near.mismatch, null);
    assert.equal(Math.round(near.parts.reduce((a, v) => a + v, 0) * 10), 80);
    const far = splitParts([1.0, 0.5, 0.2], 8.7, 1);
    assert.deepEqual(far.parts, [1, 0.5, 0.2], 'raw, not scaled up to 8.7');
    assert.ok(Math.abs(far.mismatch - 7.0) < 1e-9);
});

test('4: a total with no part data is "no split yet", never zeros', () => {
    assert.equal(splitParts([0, 0, 0], 8.7, 1).empty, true);
    assert.equal(splitParts([], 8.7, 1).empty, true);
    assert.equal(splitParts([0, 0], 0, 1).empty, false, 'nothing used, nothing to split');
});

const INSIGHTS = (_series, total) => {
    const el = mount('sem-next-insights-card', { 'switch.sem_observer_mode': S('off') });
    const n = el._buckets().n;
    el._series = () => new Array(n).fill(0.1);
    el._pt = () => total;
    el._flowValue = (src) => (series['f_' + src] ?? null);
    el._sum = () => 0;
    return el;
};
const WORDS2 = { next_split_mismatch: 'Sources disagree by {kwh} kWh', next_no_split: 'No split yet' };

test('4: Insights shows the gap, not scaled parts, when the sources disagree with the house meter', () => {
    globalThis.semLocalize = (k) => WORDS2[k] || WORDS[k] || k;
    const el = INSIGHTS({}, 8.7);
    el._flowValue = () => 0.5;
    const out = text(el._energyTab());
    assert.match(out, /Sources disagree by/);
});

test('4: Insights with a house total and no part data says no split yet, not "0 · 0 · 0"', () => {
    globalThis.semLocalize = (k) => WORDS2[k] || WORDS[k] || k;
    const el = INSIGHTS({}, 8.7);
    el._flowValue = () => null;
    const out = text(el._energyTab());
    assert.match(out, /No split yet/);
});

import { effectivePlan, planRuns } from '../src/util/plan-facts.js';

test('5: a need cuts only the blocks of its own window; a later window under the same id keeps its hours', () => {
    const at = (h) => `2026-11-18T${String(h).padStart(2, '0')}:00:00+01:00`;
    const tomorrow = (h) => `2026-11-19T${String(h).padStart(2, '0')}:00:00+01:00`;
    const plan = {
        blocks: [
            { id: 'ev:c2', start: at(14), end: at(17), power_w: 3433 },        // 10.3 kWh in the demand's window
            { id: 'ev:c2', start: tomorrow(14), end: tomorrow(17), power_w: 3433 }, // a later window, same id
        ],
        demands: [{ id: 'ev:c2', kind: 'ev', planned_kwh: 10.3, needed_kwh: 10.0,
            why: { code: 'cheapest_hours', params: { from: at(14), to: at(17) } } }],
    };
    const runs = planRuns(effectivePlan(plan), (id) => id === 'ev:c2');
    assert.equal(Math.round(runs[0].kwh * 10) / 10, 10.0, 'its own window is cut to the need');
    assert.equal(Math.round(runs[1].kwh * 10) / 10, 10.3, 'the later window is not cut');
});

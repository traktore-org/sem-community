import { test } from 'node:test';
import assert from 'node:assert/strict';

import { noAskKey } from '../src/util/plan-no-ask.js';
import { heatCostNow } from '../src/util/heat-pump-cost.js';
import fs from 'node:fs';

// #1081 — real-shaped plan attributes of sensor.sem_energy_plan.
const PLAN = {
    coverage: { 'comfort:heat_pump': 'not in plan', 'load:heat_pump': 'not in plan' },
    coverage_why: { 'comfort:heat_pump': 'comfort_no_band', 'load:heat_pump': 'load_no_min_runtime' },
};

test('the first named reason becomes a translation key', () => {
    assert.equal(noAskKey(PLAN, 'comfort:heat_pump', 'load:heat_pump'), 'why_reason_comfort_no_band');
    assert.equal(noAskKey(PLAN, 'load:heat_pump'), 'why_reason_load_no_min_runtime');
});

test('no reason, no key; junk is refused', () => {
    assert.equal(noAskKey({ coverage: {} }, 'comfort:heat_pump'), null);
    assert.equal(noAskKey(null, 'x'), null);
    assert.equal(noAskKey({ coverage_why: { a: 'X Y' } }, 'a'), null);
});

test('every code the plan can name has a sentence in every language', () => {
    const tr = JSON.parse(fs.readFileSync(new URL('../../translations.json', import.meta.url)));
    const codes = ['comfort_away', 'comfort_no_band', 'comfort_band_wrong', 'comfort_no_room_reading',
        'comfort_too_cold', 'comfort_solar_only', 'comfort_warm', 'comfort_not_far', 'load_no_min_runtime'];
    for (const lang of Object.keys(tr)) {
        for (const c of codes) assert.ok(tr[lang]['why_reason_' + c], `${lang} ${c}`);
        assert.ok(tr[lang].hp_cop_flat_hint, lang);
    }
});

test('a flat COP with an outdoor reading stays flat', () => {
    const now = heatCostNow({ state: '0.136', attributes: { cop_used: 3, cop_source: 'flat', outdoor_c: 8.8 } });
    assert.equal(now.source, 'flat');
    assert.equal(now.outdoorC, null);
});

// (#1354) A plan id is never printed: every card names it through one reader.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { planIdName, planIdParts } from '../src/util/plan-ids.js';

const names = {
    charger: (cid) => ({ keba: 'Keba Charger' }[cid]),
    load: (key) => ({ hot_water: 'Sim Boiler' }[key]),
    battery: () => 'Battery',
    label: (id) => ({ 'load:pool': 'Pool pump' }[id]),
};

test('each kind of id becomes a name, never the id', () => {
    assert.equal(planIdName('ev:keba', names), 'Keba Charger');
    assert.equal(planIdName('load:hot_water', names), 'Sim Boiler');
    assert.equal(planIdName('comfort:hot_water', names), 'Sim Boiler');
    assert.equal(planIdName('battery', names), 'Battery');
    assert.equal(planIdName('battery_out', names), 'Battery');
    assert.equal(planIdName('load:pool', names), 'Pool pump');
    // nothing knows it: the key as words, still no prefix
    assert.equal(planIdName('comfort:heat_pump', {}), 'Heat pump');
    for (const id of ['comfort:x_y', 'load:x_y', 'ev:x_y', 'weird:x_y']) assert.doesNotMatch(planIdName(id, {}), /:|_/, id);
    assert.deepEqual(planIdParts('comfort:hot_water'), { kind: 'comfort', key: 'hot_water' });
});

test('the cards name plan ids through this reader', () => {
    const src = (f) => fs.readFileSync(new URL(f, import.meta.url), 'utf8');
    assert.ok(src('../src/cards/sem-next-now-card.js').includes('planIdName('));
    assert.ok(src('../src/util/next-plan-chart.js').includes('planIdName('));
});

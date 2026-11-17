import { test } from 'node:test';
import assert from 'node:assert/strict';

import { deviceOfDemand, heatCostRows } from '../src/util/heat-cost-table.js';

// #1081 — "Heat cost per hour" under a device's plan row. Read only.
const t = (k) => `«${k}»`;
const hm = (iso) => iso.slice(11, 16);
const HC = {
    pump: [
        ['2026-11-17T01:00', 0.3, 2.5, 0.12, 0, null],
        ['2026-11-17T02:00', 0.2, 4.2, 0.048, 1, 'cheapest_heat'],
        ['2026-11-17T03:00', 0.2, null, null, 1, 'preheat'],
    ],
};

test('a demand maps to its device', () => {
    assert.equal(deviceOfDemand('load:pump'), 'pump');
    assert.equal(deviceOfDemand('comfort:pump'), 'pump');
    assert.equal(deviceOfDemand('ev:car'), null);
    assert.equal(deviceOfDemand(null), null);
});

test('rows carry time, numbers, cheap and the reason in words', () => {
    const rows = heatCostRows(HC, 'comfort:pump', hm, t);
    assert.equal(rows.length, 3);
    assert.deepEqual(rows[0], { time: '01:00', price: 0.3, cop: 2.5, heat: 0.12,
        cheap: false, chosen: false, why: '' });
    assert.equal(rows[1].chosen, true);
    assert.equal(rows[1].why, '«energy_plan_hc_cheapest_heat»');
    assert.equal(rows[2].cop, null);               // no COP: the cell shows a dash
    assert.equal(rows[2].why, '«energy_plan_hc_preheat»');
});

test('no table without the attribute, the device or usable rows', () => {
    assert.equal(heatCostRows(null, 'load:pump', hm, t), null);
    assert.equal(heatCostRows({}, 'load:pump', hm, t), null);
    assert.equal(heatCostRows(HC, 'load:other', hm, t), null);
    assert.equal(heatCostRows(HC, 'ev:car', hm, t), null);
    assert.equal(heatCostRows({ pump: [] }, 'load:pump', hm, t), null);
    assert.equal(heatCostRows({ pump: [['x']] }, 'load:pump', hm, t), null);
});

test('an unknown reason code is not chosen text', () => {
    const rows = heatCostRows({ pump: [['2026-11-17T01:00', 1, 2, 0.5, 0, 'zzz']] },
        'load:pump', hm, t);
    assert.equal(rows[0].chosen, false);
    assert.equal(rows[0].why, '');
});

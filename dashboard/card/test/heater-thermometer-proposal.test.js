/**
 * (#1353) The crawler's thermometer proposal on a heater: shown only with a
 * proposal and no thermometer; the click sends the picker's own write.
 *
 * Run: `npm test` (from dashboard/card).
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { thermometerProposal, useThermometerWrite } from '../src/util/heater-questions.js';

const here = new URL('.', import.meta.url);
const words = JSON.parse(fs.readFileSync(new URL('../../translations.json', here), 'utf8'));
const proposal = { entity_id: 'sensor.tank_temp', name: 'Tank temperature', why: 'device' };

test('a proposal and no thermometer: the line shows', () => {
    const p = thermometerProposal({ thermometerProposal: proposal, goals: { comfort_entity: '' } });
    assert.deepEqual(p, { entity: 'sensor.tank_temp', name: 'Tank temperature', why: 'device' });
});

test('no proposal: no line', () => {
    assert.equal(thermometerProposal({ thermometerProposal: null, goals: {} }), null);
    assert.equal(thermometerProposal({ goals: {} }), null);
    assert.equal(thermometerProposal(null), null);
    assert.equal(thermometerProposal({ thermometerProposal: {}, goals: {} }), null);
});

test('a thermometer is already set: no line, whatever the engine says', () => {
    assert.equal(thermometerProposal({
        thermometerProposal: proposal, goals: { comfort_entity: 'sensor.mine' } }), null);
});

test('the texts exist in every language', () => {
    const keys = ['hq_' + 'found_thermometer', 'hq_' + 'use_thermometer'];
    for (const [lang, table] of Object.entries(words)) {
        for (const k of keys) assert.ok(table[k], lang + ' lacks ' + k);
        assert.ok(table[keys[0]].includes('{name}'), lang + ' lost {name}');
    }
});

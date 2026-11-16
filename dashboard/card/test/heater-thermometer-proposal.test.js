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
const classic = fs.readFileSync(new URL('../src/cards/sem-load-priority-card.js', here), 'utf8');
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

test('the click sends exactly the write the manual picker sends', () => {
    const w = useThermometerWrite(thermometerProposal({ thermometerProposal: proposal, goals: {} }));
    assert.deepEqual(w, { property: 'comfort_entity', value: 'sensor.tank_temp' });
    // the picker: _sendDeviceUpdate(device.id, 'comfort_entity', v)
    assert.ok(classic.includes("this._sendDeviceUpdate(device.id, 'comfort_entity', v)"));
});

test('the card wires the line to the helper and the button to one write, nothing else', () => {
    const fn = classic.slice(classic.indexOf('_renderThermometerProposal(device) {'),
        classic.indexOf('_renderStopCondition(device) {'));
    assert.ok(fn.includes('thermometerProposal(device)'));
    assert.ok(fn.includes("this._useThermometer(device, p)"));
    assert.equal((fn.match(/_setGoal\(/g) || []).length, 1);   // only in the click handler
    assert.ok(!/connectedCallback|updated\(|firstUpdated/.test(fn), 'nothing writes on render');
});

test('both goal-editor views show it', () => {
    assert.equal((classic.match(/this\._renderThermometerProposal\(device\)/g) || []).length, 2);
});

test('the texts exist in every language', () => {
    const keys = ['hq_' + 'found_thermometer', 'hq_' + 'use_thermometer'];
    for (const [lang, table] of Object.entries(words)) {
        for (const k of keys) assert.ok(table[k], lang + ' lacks ' + k);
        assert.ok(table[keys[0]].includes('{name}'), lang + ' lost {name}');
    }
});

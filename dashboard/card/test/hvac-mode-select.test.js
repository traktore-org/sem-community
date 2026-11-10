/**
 * (#1323) The load editor's HVAC-mode select: heat, cool, by forecast.
 */
import { test } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import { HVAC_MODE_LABELS, hvacModeOptions } from '../src/util/load-sections.js';

const here = new URL('.', import.meta.url);
const words = JSON.parse(fs.readFileSync(new URL('../../translations.json', here), 'utf8'));
const card = fs.readFileSync(new URL('../src/cards/sem-load-priority-card.js', here), 'utf8');

test('the editor offers heat, cool and by forecast', () => {
    assert.deepEqual(hvacModeOptions('heat'), ['heat', 'cool', 'by_forecast']);
    assert.deepEqual(hvacModeOptions('by_forecast'), ['heat', 'cool', 'by_forecast']);
    assert.deepEqual(hvacModeOptions(''), ['heat', 'cool', 'by_forecast']);
});

test('a unit on another mode keeps it in the list', () => {
    assert.deepEqual(hvacModeOptions('dry'), ['heat', 'cool', 'by_forecast', 'dry']);
    assert.deepEqual(hvacModeOptions('auto'), ['heat', 'cool', 'by_forecast', 'auto']);
});

test('every mode label is translated in every language', () => {
    const keys = [...Object.values(HVAC_MODE_LABELS), 'comfort_hvac_mode', 'comfort_hvac_hint'];
    for (const [lang, table] of Object.entries(words)) {
        for (const key of keys) assert.ok(table[key], lang + ' lacks ' + key);
    }
});

test('the select saves through the goal path the other fields use', () => {
    assert.ok(card.includes('data-goal="hvac_mode"'));
    assert.ok(card.includes('hvacModeOptions(g.hvac_mode)'));
});

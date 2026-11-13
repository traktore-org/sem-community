// (#1354) A setting that does nothing in this setup is not asked.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { taxesApply, hotWaterSetUp } from '../src/util/settings-applies.js';

test('taxes are asked only for a spot price', () => {
    assert.equal(taxesApply(undefined), false);      // the default is all-in
    assert.equal(taxesApply('all_in'), false);
    assert.equal(taxesApply('spot_incl_vat'), true);
    assert.equal(taxesApply('spot'), true);
});

test('hot water counts as set up only when its settings exist', () => {
    assert.equal(hotWaterSetUp({}), false);
    assert.equal(hotWaterSetUp(undefined), false);
    assert.equal(hotWaterSetUp({ 'number.sem_legionella_target_temp': { state: '60' } }), true);
});

test('both cards take the rule from the shared util', () => {
    const cards = new URL('../src/cards/', import.meta.url);
    const cfg = fs.readFileSync(new URL('sem-config-card.js', cards), 'utf8');
    const ctl = fs.readFileSync(new URL('sem-control-card.js', cards), 'utf8');
    assert.ok(cfg.includes("from '../util/settings-applies.js'") && cfg.includes('taxesApply(basis)'));
    assert.ok(!cfg.includes('disabled: allIn'), 'the tax fields are hidden, not greyed');
    assert.ok(ctl.includes('hotWaterSetUp(this._hass?.states)'));
});

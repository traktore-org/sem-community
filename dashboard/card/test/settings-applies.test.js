// (#1354) A setting that does nothing in this setup is not asked.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { taxesApply, hotWaterSetUp, loadRunsBySem, priceAddOns } from '../src/util/settings-applies.js';

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

test('SEM runs a load only in its own two modes', () => {
    assert.equal(loadRunsBySem('solar_only'), true);
    assert.equal(loadRunsBySem('solar_battery'), true);
    for (const m of ['off', 'peak_only', '', undefined]) assert.equal(loadRunsBySem(m), false, String(m));
});

test('an all-in price takes no VAT, markup or tax; the grid fee comes with a dynamic tariff only', () => {
    assert.deepEqual(priceAddOns('all_in', 'static'), { vat: false, markup: false, tax: false, fee: false });
    assert.deepEqual(priceAddOns('all_in', 'dynamic'), { vat: false, markup: false, tax: false, fee: true });
    assert.deepEqual(priceAddOns('spot', 'dynamic'), { vat: true, markup: true, tax: true, fee: true });
    assert.deepEqual(priceAddOns('spot_incl_vat', 'calendar'), { vat: true, markup: true, tax: true, fee: false });
    // no basis set is the default, all-in
    assert.deepEqual(priceAddOns(undefined, 'static'), { vat: false, markup: false, tax: false, fee: false });
});

test('the new card takes its rules from the same module, and the old copy is gone', () => {
    const util = new URL('../src/util/', import.meta.url);
    assert.ok(!fs.existsSync(new URL('next-applies.js', util)));
    for (const f of ['next-settings.js', 'next-devices-load.js']) {
        assert.ok(fs.readFileSync(new URL(f, util), 'utf8').includes("from './settings-applies.js'"), f);
    }
});

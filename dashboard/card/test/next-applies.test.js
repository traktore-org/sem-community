// (#1354) What a setting does in this setup — the rules the cards hide rows by.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadRunsBySem, priceAddOns } from '../src/util/next-applies.js';

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

/**
 * (#914) The anti-cycle row must not invent numbers.
 */
import { test } from 'node:test';
import assert from 'node:assert';
import { MISSING, antiCyclePlaceholder, antiCycleBounds } from '../src/util/load-sections.js';

test('placeholder shows what the live device holds', () => {
    assert.equal(antiCyclePlaceholder({ min_on_effective_min: 10 }, 'min_on_effective_min'), '10');
    assert.equal(antiCyclePlaceholder({ min_off_effective_min: 5.0 }, 'min_off_effective_min'), '5');
});

test('no live device is a dash, never "5" and never "0"', () => {
    assert.equal(antiCyclePlaceholder({ min_on_effective_min: null }, 'min_on_effective_min'), MISSING);
    assert.equal(antiCyclePlaceholder({}, 'min_on_effective_min'), MISSING);
    assert.equal(antiCyclePlaceholder(undefined, 'min_on_effective_min'), MISSING);
});

test('a non-numeric effective value is absent, not NaN', () => {
    assert.equal(antiCyclePlaceholder({ min_on_effective_min: 'n/a' }, 'min_on_effective_min'), MISSING);
});

test('bounds come from the published attribute', () => {
    assert.deepEqual(antiCycleBounds({ anti_cycle_bounds: { min: 0, max: 120, step: 1 } }), { min: 0, max: 120 });
});

test('an absent attribute is null — no range the card made up', () => {
    assert.equal(antiCycleBounds({}), null);
    assert.equal(antiCycleBounds(undefined), null);
    assert.equal(antiCycleBounds({ anti_cycle_bounds: { min: 'x', max: 120 } }), null);
});

/**
 * (#1381) On a phone the four mode buttons share about 340 px, and
 * "Sun + tariff" broke onto two lines. Narrow screens drop the spaces around
 * "+" so the label stays on one line; wide screens and screen readers keep
 * the full name.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

await import('./card-harness.js');
const { segLabel } = await import('../src/base/sem-next-base.js');

test('narrow screens join "Sun + tariff" into one word', () => {
    assert.equal(segLabel('Sun + tariff', true), 'Sun+tariff');
    assert.equal(segLabel('Sonne + Tarif', true), 'Sonne+Tarif');
    assert.equal(segLabel('Sun', true), 'Sun');
});

test('wide screens keep the full name', () => {
    assert.equal(segLabel('Sun + tariff', false), 'Sun + tariff');
});

/**
 * (#1381) PROD 25.11: "At least 10 kWh · Up to 40 kWh", 16.3 kWh charged
 * today, and the bar stood almost empty. It was scaled to the setting's
 * raw ceiling (200 kWh), not the "Up to" the card shows (capped by the car's
 * 40 kWh). The bar and its words count the same energy the decision uses for
 * "remaining": the charger's energy today.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { chargerTargetBar } from '../src/util/charger-questions.js';

test('the bar scales to the Up to the card shows, not the raw 200 kWh setting', () => {
    const b = chargerTargetBar({ have: 16.3, min: 10, max: 200, capacity: 40, bound: 200, isSoc: false });
    assert.ok(b.fill > 40, `fill ${b.fill}`);
    assert.equal(Math.round(b.fill * 10) / 10, 40.8);
    assert.equal(b.flagLeft, 25);
    assert.equal(b.reached, true);
    assert.equal(b.left, 0);
});

test('below At least the words say what is left, in the decision\'s energy', () => {
    const b = chargerTargetBar({ have: 6.8, min: 10, max: 200, capacity: 40, bound: 200, isSoc: false });
    assert.equal(b.reached, false);
    assert.equal(Math.round(b.left * 10) / 10, 3.2);
});

test('an unknown car (Up to = full) scales to the larger of At least and today', () => {
    const b = chargerTargetBar({ have: 4, min: 10, max: 200, capacity: 40, bound: 200, isSoc: false, unset: true });
    assert.equal(b.flagLeft, 100);
    assert.equal(b.fill, 40);
});

test('a SOC target keeps its 0..100 scale', () => {
    const b = chargerTargetBar({ have: 44, min: 70, max: 90, capacity: 40, bound: 100, isSoc: true });
    assert.equal(b.fill, 44);
    assert.equal(b.flagLeft, 70);
    assert.equal(b.reached, false);
});

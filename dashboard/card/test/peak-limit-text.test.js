/**
 * #1055 — the Control tab read "5.0 kW" while the install had no grid limit.
 * The sensor keeps the saved number while uncapped, so a card that prints the
 * state alone shows a limit that is not in force.
 *
 * Run: `npm test` (from dashboard/card).
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { isUncapped, peakLimitText } from '../src/util/peak-slot.js';

const st = (state, unlimited) => ({ state, attributes: { peak_limit_unlimited: unlimited } });

test('uncapped shows the word, not the saved number', () => {
    assert.equal(peakLimitText(st('80.0', true), 'Illimité'), 'Illimité');
    assert.equal(peakLimitText(st('5.0', true), 'Uncapped'), 'Uncapped');
});

test('a limit shows its own number', () => {
    assert.equal(peakLimitText(st('8.5', false), 'Uncapped'), '8.5 kW');
    assert.equal(peakLimitText(st('12', undefined), 'Uncapped'), '12.0 kW');
});

test('no reading shows a dash, never a made-up 5 kW', () => {
    assert.equal(peakLimitText(undefined, 'Uncapped'), '—');
    assert.equal(peakLimitText(st('unavailable', false), 'Uncapped'), '—');
    assert.equal(peakLimitText(st('unknown', false), 'Uncapped'), '—');
});

test('the flag decides, never the number', () => {
    assert.equal(isUncapped(st('80.0', true)), true);
    assert.equal(isUncapped(st('80.0', false)), false);
    assert.equal(isUncapped(st('0', undefined)), false);
    assert.equal(isUncapped(undefined), false);
});

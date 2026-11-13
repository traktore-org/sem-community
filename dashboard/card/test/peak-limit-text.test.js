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

test('the Control card shows no percent or margin when uncapped', () => {
    const src = readFileSync(new URL('../src/cards/sem-control-card.js', import.meta.url), 'utf8');
    const body = src.slice(src.indexOf('_renderPeakSection(T) {'));
    const section = body.slice(0, body.indexOf('\n    _render', 10));
    assert.match(section, /isUncapped\(/, 'peak section must ask the flag');
    // (#1354) in the shared word of the peak question, "No limit"
    assert.match(section, /uncapped\s*\?\s*this\._t\(PEAK_TEXT\.none\)/, 'margin tile must say there is no limit');
});

test('the Control-tab header and the Home card use it', () => {
    for (const f of ['sem-tab-header.js', 'sem-home-status-card.js']) {
        const src = readFileSync(new URL(`../src/cards/${f}`, import.meta.url), 'utf8');
        assert.match(src, /peakLimitText\(/, `${f} must render the limit through peakLimitText`);
        assert.doesNotMatch(src, /_(getState|val)\('target_peak_limit'/,
            `${f} must not print the bare limit number`);
    }
});

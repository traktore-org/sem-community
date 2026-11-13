/**
 * (#1321) The Now screen's charger line: the mode code and the readable
 * part of SEM's strategy text, without its log numbers.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { splitStrategyReason } from '../src/util/next-strategy-reason.js';

test('day zone text: mode code, readable tail, no key=value numbers', () => {
    const r = splitStrategyReason('solar_plus_battery day Zone 3: budget=0W below 8A min — staying idle (this mode spends solar and the pack only)');
    assert.equal(r.mode, 'solar_plus_battery');
    assert.equal(r.head, 'day Zone 3');
    assert.equal(r.detail, 'below 8A min · staying idle (this mode spends solar and the pack only)');
});

test('night text with a plan suffix keeps both readable parts', () => {
    const r = splitStrategyReason('min_plus_solar night: waiting for the planned window — joint energy plan: outside the plan');
    assert.equal(r.mode, 'min_plus_solar');
    assert.equal(r.detail, 'waiting for the planned window · joint energy plan: outside the plan');
});

test('no dash: the words after the colon, numbers dropped', () => {
    const r = splitStrategyReason('min_plus_solar night: target reached (remaining=0.00 kWh)');
    assert.equal(r.mode, 'min_plus_solar');
    assert.equal(r.detail, 'target reached');
});

test('a plain sentence without a mode code stays whole', () => {
    const r = splitStrategyReason('idle');
    assert.equal(r.mode, '');
    assert.equal(r.head, 'idle');
    assert.equal(r.detail, '');
});

test('empty input is safe', () => {
    assert.deepEqual(splitStrategyReason(undefined), { mode: '', head: '', detail: '' });
});

// (#1354) PROD showed "min_plus_solar but EV disconnected [structural: …]" on Now.
test('the car row says the mode label and the engine reason in words, never the raw text', async () => {
    const { strategyWords } = await import('../src/util/next-strategy-reason.js');
    const { plainReason } = await import('../src/util/why-rows.js');
    const t = (k) => ({ charge_mode_min_plus_solar: 'Min + Solar', ev_charger: 'EV Charger',
        why_reason_ev_disconnected: 'No car is plugged in.' }[k] || k);
    const raw = 'min_plus_solar but EV disconnected [structural: no car]';
    const withCode = strategyWords({ state: raw, attributes: { reason: raw, reason_code: 'ev_disconnected', reason_params: {} } }, t, plainReason);
    assert.deepEqual(withCode, { title: 'Min + Solar', text: 'No car is plugged in.' });
    // no code: no second line, and never the engine's words
    const noCode = strategyWords({ state: raw, attributes: { reason: raw } }, t, plainReason);
    assert.deepEqual(noCode, { title: 'Min + Solar', text: '' });
    // an unknown mode: the generic title, not the raw head
    const odd = strategyWords({ state: 'weird_mode zone: x', attributes: {} }, t, plainReason);
    assert.equal(odd.title, 'EV Charger');
    for (const r of [withCode, noCode, odd]) assert.doesNotMatch(r.title + r.text, /structural|min_plus_solar|EV disconnected/);
});

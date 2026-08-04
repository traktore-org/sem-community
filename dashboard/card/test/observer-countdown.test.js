import { test } from 'node:test';
import assert from 'node:assert/strict';

import { formatObserverCountdown } from '../src/util/observer-countdown.js';


test('observer countdown shows a language-neutral total-hour clock', () => {
    assert.equal(formatObserverCountdown(46 * 3600 + 30 * 60), '46:30:00');
    assert.equal(formatObserverCountdown(59), '00:00:59');
});


test('observer countdown reports zero and clamps invalid values', () => {
    assert.equal(formatObserverCountdown(0), '00:00:00');
    assert.equal(formatObserverCountdown(-10), '00:00:00');
    assert.equal(formatObserverCountdown(Number.NaN), '72:00:00');
});

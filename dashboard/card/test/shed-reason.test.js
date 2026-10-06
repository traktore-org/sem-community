/**
 * (#992) Every EMERGENCY shed was labelled "peak protection" — the card
 * compared the backend's UPPER-CASE reason against a lower-case literal.
 */
import { test } from 'node:test';
import assert from 'node:assert';
import { shedReasonKey } from '../src/util/shed-reason.js';

test('the backend\'s own spelling is what the card must match', () => {
    // these three are the ONLY values load_management.py writes
    assert.equal(shedReasonKey('EMERGENCY'), 'shed_emergency');
    assert.equal(shedReasonKey('PROGRESSIVE'), 'shed_peak');
    // (#1048) a phase over its limit — its own label, never "peak protection"
    assert.equal(shedReasonKey('PHASE'), 'shed_phase');
});

test('case never decides the label again', () => {
    assert.equal(shedReasonKey('emergency'), 'shed_emergency');
    assert.equal(shedReasonKey('Emergency'), 'shed_emergency');
});

test('absence is peak protection, not an emergency', () => {
    for (const v of [undefined, null, '', 0, false]) {
        assert.equal(shedReasonKey(v), 'shed_peak');
    }
});

test('an unknown reason is never escalated to an emergency', () => {
    assert.equal(shedReasonKey('SOMETHING_NEW'), 'shed_peak');
});

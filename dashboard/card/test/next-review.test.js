/** (#755, #800, #1321) Last night's review: codes in, sentences out, a row without text is dropped. */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { reviewRows } from '../src/util/next-review.js';

const say = (key, p) => ({
    energy_plan_review_took_less: `needs ${p.suggested} of ${p.asked}`,
    energy_plan_review_batt_refilled: `drained ${p.drained}, full by ${p.full_at}`,
    energy_plan_review_sc_met: `kept ${p.actual}% of ${p.predicted}%`,
}[key] || '');

test('a demand, the battery and the sun each give one row', () => {
    const rows = reviewRows({
        demands: [{ code: 'took_less', kind: 'ev', demand_id: 'ev:keba', label: 'Car', asked_kwh: 20, suggested_kwh: 12.34 }],
        battery: { code: 'batt_refilled', drained: 3.21, full_at_ts: 1000 },
        self_consumption: { code: 'sc_met', actual_share: 0.61, predicted_share: 0.6 },
    }, say, (ms) => 'T' + ms);
    assert.deepEqual(rows.map((r) => r.kind), ['ev', 'battery', 'sun']);
    assert.equal(rows[0].text, 'needs 12.3 of 20.0');
    assert.equal(rows[1].text, 'drained 3.2, full by T1000000');
    assert.equal(rows[2].text, 'kept 61% of 60%');
});

test('a code with no sentence is dropped, never shown as a key', () => {
    assert.deepEqual(reviewRows({ demands: [{ code: 'nope', kind: 'load' }] }, say), []);
});

test('no review gives no rows', () => {
    assert.deepEqual(reviewRows(undefined, say), []);
    assert.deepEqual(reviewRows({}, say), []);
});

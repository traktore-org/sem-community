/**
 * (#1321) The one-night override span: from now to the end of the plan.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { minutesToPlanEnd } from '../src/util/next-strip.js';

test('minutesToPlanEnd: to the last slot, 1..1440, a fallback without slots', () => {
    const now = new Date('2026-11-08T22:00:00+01:00');
    const plan = { slots: [{ start: '2026-11-08T22:00:00+01:00', end: '2026-11-09T07:00:00+01:00' }] };
    assert.equal(minutesToPlanEnd(plan, now), 540);
    assert.equal(minutesToPlanEnd({ slots: [] }, now), 720);
    assert.equal(minutesToPlanEnd({}, now, 60), 60);
    assert.equal(minutesToPlanEnd({ slots: [{ end: '2026-11-08T21:00:00+01:00' }] }, now), 720);
});

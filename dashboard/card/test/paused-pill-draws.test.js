/**
 * #1407 round 2 — a Pause chip over a charge that runs.
 *
 * A Pause is Off for a while: it stops a running charge once, then SEM sends
 * nothing (#898). A charge another system starts goes on. The head chip said
 * "paused until 14:00" beside 0.9 kW; it now says what the box draws first.
 *
 * Run: `npm test` (from dashboard/card).
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { statePill } from '../src/util/next-devices.js';

const charger = { type: 'charger', mergedMode: 'off' };

test('a paused charger that draws reads charging, with its amps', () => {
    const pill = statePill(charger, { powerW: 900, amps: 3.9, paused: true, pausedUntil: '14:00' });
    assert.equal(pill.key, 'next_st_charging_a');
    assert.deepEqual(pill.params, { amps: 4 });
});

test('a paused charger that draws, no amps known: charging', () => {
    assert.equal(statePill(charger, { powerW: 900, amps: null, paused: true }).key, 'next_st_charging');
});

test('a paused charger that draws nothing still reads paused until', () => {
    const pill = statePill(charger, { powerW: 0, amps: 0, paused: true, pausedUntil: '14:00' });
    assert.equal(pill.key, 'next_st_paused');
    assert.deepEqual(pill.params, { time: '14:00' });
});

test('a standby trickle (50 W or less) is no charge', () => {
    assert.equal(statePill(charger, { powerW: 40, paused: true, pausedUntil: '14:00' }).key, 'next_st_paused');
});

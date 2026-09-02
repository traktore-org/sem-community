/**
 * A battery SOC that is not being read must not render as "0%".
 *
 * PROD, 02.09 17:59 local, mid-dropout: the Home diagram's battery cell read
 * "0 %" with an empty fill, under "— W" and "sensor unavailable". The card
 * KNEW the reading was stale (it dimmed the node and blanked the power) and
 * still printed the one number a stale hold carries — the fallback 0 — as
 * the state of charge. 0 % is a flat pack: a real, alarming measurement.
 * The home-status chip and the battery card's gauge print the same 0 % from
 * the same unavailable sensor, without even a hold.
 *
 * `socDisplay(soc, stale)` is the one place that turns a SOC reading into a
 * label and a fill fraction; every SOC render goes through it.
 *
 * Run: `npm test` (from dashboard/card).
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { MISSING, socDisplay } from '../src/util/missing-value.js';

test('a real SOC renders as before: label and fill fraction', () => {
    assert.deepEqual(socDisplay(97), { label: '97%', fraction: 0.97, known: true });
    assert.deepEqual(socDisplay(42.6), { label: '43%', fraction: 0.426, known: true });
    assert.deepEqual(socDisplay(0), { label: '0%', fraction: 0, known: true },
        'a genuine zero is a flat pack and says so');
    assert.deepEqual(socDisplay(100), { label: '100%', fraction: 1, known: true });
});

test('an expired hold is an absent reading, not a flat pack (the 17:59 screenshot)', () => {
    // _readWithHold hands back value 0 + stale:true once the 60 s hold runs out.
    const d = socDisplay(0, true);
    assert.equal(d.label, MISSING);
    assert.equal(d.fraction, 0, 'the cell stays empty — no fill is drawn for a value nobody has');
    assert.equal(d.known, false);
    assert.ok(!d.label.includes('%'), 'no percent sign on a value that is not a percentage');
});

test('a null/NaN SOC (sibling cards read the sensor with no hold) is the same absence', () => {
    for (const v of [null, undefined, NaN]) {
        assert.deepEqual(socDisplay(v), { label: MISSING, fraction: 0, known: false },
            `soc=${String(v)}`);
    }
});

test('the fill fraction is clamped to the cell, the label is not rewritten', () => {
    assert.equal(socDisplay(104).fraction, 1);
    assert.equal(socDisplay(-3).fraction, 0);
    assert.equal(socDisplay(104).label, '104%', 'an out-of-range sensor is shown, not hidden');
});

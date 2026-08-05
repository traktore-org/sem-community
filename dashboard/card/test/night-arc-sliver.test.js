/**
 * Regression tests for the #711 night-arc position (moon on the sun arc).
 *
 * ``nightArcPos(now, nextRiseTs, nextSetTs)`` maps the current night onto
 * [1..0] (sunset → sunrise). Two things are pinned here:
 *
 * 1. The dawn/dusk SLIVERS — the minutes where the card's elevation-gated
 *    isNight disagrees with HA's limb-crossing next_rising/next_setting —
 *    must land the moon on the correct arc END, not mid-arc (the live
 *    06:05 bug: moon at ~0.72 two minutes after a 06:03 sunrise).
 * 2. Detection is by PROXIMITY to the flip event, never elapsed time: the
 *    first fix's 20 h elapsed threshold broke real 20–22 h high-latitude
 *    nights (Tromsø/Murmansk — ruflo review of 41cadcf), inverting the
 *    endpoints into a negative night and freezing the moon at mid-arc.
 *
 * Run: `npm test` (from dashboard/card). No browser/jsdom needed.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { DAY_MS, nightArcPos } from '../src/util/night-arc.js';

const H = 3600000;
const T0 = Date.parse('2026-08-04T12:00:00Z'); // arbitrary anchor noon

// Build a night: sunset at T0+offset, night of ``nightH`` hours; returns
// the sun.sun-shaped inputs as HA would publish them at ``now``:
// next_setting flips to tomorrow AT the set, next_rising flips AT the rise.
function world(nightH, nowOffsetH, { dayH = 24 - nightH } = {}) {
    const sunset = T0;
    const sunrise = sunset + nightH * H;
    const now = sunset + nowOffsetH * H;
    const nextSet = now < sunset ? sunset : sunset + nightH * H + dayH * H;
    const nextRise = now < sunrise ? sunrise : sunrise + DAY_MS;
    return { now, nextRise, nextSet };
}

test('a normal 9h night counts down 1 → 0', () => {
    for (const [off, want] of [[0.5, 1 - 0.5 / 9], [4.5, 0.5], [8.5, 1 - 8.5 / 9]]) {
        const w = world(9, off);
        assert.ok(Math.abs(nightArcPos(w.now, w.nextRise, w.nextSet) - want) < 1e-9,
            `offset ${off}h`);
    }
});

test('the dawn sliver lands on the sunrise end, not mid-arc (the 06:05 bug)', () => {
    // 2 minutes AFTER the official rise: next_rising already points at
    // tomorrow, elevation still < 0 so the caller still says night.
    const w = world(9, 9 + 2 / 60);
    const pos = nightArcPos(w.now, w.nextRise, w.nextSet);
    assert.ok(pos !== null && pos < 0.05, `expected ~0 (sunrise end), got ${pos}`);
});

test('the dusk sliver lands on the sunset end', () => {
    // 5 minutes BEFORE the official set: next_setting still points at
    // tonight's imminent set, elevation already < 0.
    const w = world(9, -5 / 60);
    const pos = nightArcPos(w.now, w.nextRise, w.nextSet);
    assert.ok(pos !== null && pos > 0.95, `expected ~1 (sunset end), got ${pos}`);
});

test('high-latitude 20–22h nights map correctly all night (ruflo catch)', () => {
    for (const nightH of [20, 21, 22]) {
        for (const off of [1, nightH / 2, nightH - 0.5]) {
            const w = world(nightH, off, { dayH: 24 - nightH });
            const pos = nightArcPos(w.now, w.nextRise, w.nextSet);
            const want = 1 - off / nightH;
            assert.ok(pos !== null, `night=${nightH}h off=${off}h returned null`);
            assert.ok(Math.abs(pos - want) < 1e-9,
                `night=${nightH}h off=${off}h: got ${pos}, want ${want}`);
        }
    }
});

test('the dawn sliver still works on a 22h night', () => {
    const w = world(22, 22 + 2 / 60, { dayH: 2 });
    const pos = nightArcPos(w.now, w.nextRise, w.nextSet);
    assert.ok(pos !== null && pos < 0.05, `expected ~0, got ${pos}`);
});

test('a degenerate sub-sliver day falls back DIRECTIONALLY, never mid-arc', () => {
    // Polar onset: 30-minute day. 18 min before the actual rise the
    // imminent next set sits inside the sliver window and the derived
    // endpoints cross — the directional fallback (ruflo) lands on the
    // NEARER end: sunrise (0) here, never a frozen 0.5.
    const w = world(23.5, 23.2, { dayH: 0.5 });
    const pos = nightArcPos(w.now, w.nextRise, w.nextSet);
    assert.equal(pos, 0, `expected sunrise end (0), got ${pos}`);
});

test('missing attributes return null (caller keeps its fallback)', () => {
    assert.equal(nightArcPos(T0, 0, T0 + 9 * H), null);
    assert.equal(nightArcPos(T0, T0 + 9 * H, 0), null);
});

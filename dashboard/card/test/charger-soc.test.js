/**
 * Regression tests for #683 — vehicle SOC leaking between EVSE tiles.
 *
 * Reported setup: two Smart EVSE entries, ONE car. Only the first charger has
 * a ``vehicle_soc_entity``; its SOC showed on both tiles.
 *
 * Mechanism (two hops, both individually reasonable):
 *   1. coordinator.py promotes the first per-charger SOC it finds into the
 *      fleet-level ``vehicle_soc`` key when no global entity is configured
 *      (#245 review #3), so the global carries charger 1's car.
 *   2. the tile fell back to that global whenever its own per-charger sensor
 *      was null — so charger 2 rendered charger 1's car.
 *
 * The fallback is legacy single-charger compatibility (#383) and stays for
 * that case; it must not apply once a second charger exists.
 *
 * Run: `npm test` (from dashboard/card).
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { resolveChargerSoc } from '../src/util/charger-soc.js';

test('#683: a second charger does not inherit the fleet SOC', () => {
    // Charger 2: no vehicle_soc_entity, no taper calibration yet.
    // The global carries charger 1's car (77%) — it must not be shown here.
    const r = resolveChargerSoc(null, 77, null, 2);
    assert.equal(r.soc, null);
    assert.equal(r.isEstimate, false);
});

test('#683: the instrumented charger still shows its own real SOC', () => {
    const r = resolveChargerSoc(77, 77, 42, 2);
    assert.equal(r.soc, 77);
    assert.equal(r.isEstimate, false);
});

test('#683: two instrumented chargers keep their own readings', () => {
    assert.equal(resolveChargerSoc(80, 80, null, 2).soc, 80);
    assert.equal(resolveChargerSoc(35, 80, null, 2).soc, 35);
});

test('#683: a second charger falls back to its OWN estimate, not the fleet', () => {
    // Estimated SOC is already per-charger, so it is a legitimate fallback.
    const r = resolveChargerSoc(null, 77, 42, 2);
    assert.equal(r.soc, 42);
    assert.equal(r.isEstimate, true);
});

test('#383: a single-charger install still uses the global fallback', () => {
    const r = resolveChargerSoc(null, 64, null, 1);
    assert.equal(r.soc, 64);
    assert.equal(r.isEstimate, false);
});

test('single charger: real global beats the local estimate', () => {
    const r = resolveChargerSoc(null, 64, 42, 1);
    assert.equal(r.soc, 64);
    assert.equal(r.isEstimate, false);
});

test('nothing configured anywhere renders no SOC at all', () => {
    const r = resolveChargerSoc(null, null, null, 2);
    assert.equal(r.soc, null);
    assert.equal(r.isEstimate, false);
});

test('0% is a real reading, not a missing one', () => {
    // The old code used `?? `, which is null-safe — but `soc` was then chosen
    // with a `!= null` test. Guard the whole chain against a 0 -> falsy slip.
    assert.equal(resolveChargerSoc(0, 77, 42, 2).soc, 0);
    assert.equal(resolveChargerSoc(0, 77, 42, 2).isEstimate, false);
    assert.equal(resolveChargerSoc(null, 0, null, 1).soc, 0);
    assert.equal(resolveChargerSoc(null, null, 0, 2).soc, 0);
    assert.equal(resolveChargerSoc(null, null, 0, 2).isEstimate, true);
});

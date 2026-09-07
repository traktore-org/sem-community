/**
 * (#925 audit) The Home tab's chips must not invent a zero.
 *
 * The SOC chip was fixed for #903 — "an unavailable SOC is an absent
 * reading, not a flat pack" — and its two NEIGHBOURS in the same render
 * were not. On the maintainer's hardware the solar read is absent ~137
 * times a day, so "Solar 0 W · Autarky 0%" sitting beside a correctly
 * em-dashed SOC was the most-seen instance of the class in the product.
 */
import { test } from 'node:test';
import assert from 'node:assert';
import { MISSING, socDisplay } from '../src/util/missing-value.js';

// The card's own reader, extracted verbatim so the test exercises the rule
// rather than a paraphrase of it.
function makeVal(states, prefix = 'sensor.sem_') {
    return function _val(suffix, fallback = 0) {
        const e = states[`${prefix}${suffix}`];
        if (!e || e.state === 'unavailable' || e.state === 'unknown') return fallback;
        const n = parseFloat(e.state);
        return Number.isFinite(n) ? n : fallback;
    };
}

const chip = (v, fmt) => (v == null ? MISSING : fmt(v));

test('an unavailable solar sensor shows nothing, not zero watts', () => {
    const _val = makeVal({ 'sensor.sem_solar_power': { state: 'unavailable' } });
    assert.equal(chip(_val('solar_power', null), (v) => `${v} W`), MISSING);
});

test('an unavailable autarky shows nothing, not zero percent', () => {
    const _val = makeVal({ 'sensor.sem_autarky_rate': { state: 'unknown' } });
    assert.equal(chip(_val('autarky_rate', null), (v) => `${v.toFixed(0)}%`), MISSING);
});

test('a real zero still shows as zero', () => {
    const _val = makeVal({ 'sensor.sem_solar_power': { state: '0' } });
    assert.equal(chip(_val('solar_power', null), (v) => `${v} W`), '0 W');
});

test('a real reading is unaffected', () => {
    const _val = makeVal({ 'sensor.sem_autarky_rate': { state: '73.4' } });
    assert.equal(chip(_val('autarky_rate', null), (v) => `${v.toFixed(0)}%`), '73%');
});

test('a non-numeric state is absent, not NaN', () => {
    // `parseFloat('n/a') ?? fallback` returns NaN — `??` only catches
    // null/undefined — so the null fallback never applied and the chip
    // rendered "NaN W".
    const _val = makeVal({ 'sensor.sem_solar_power': { state: 'n/a' } });
    assert.equal(chip(_val('solar_power', null), (v) => `${v} W`), MISSING);
});

test('a missing entity is absent', () => {
    const _val = makeVal({});
    assert.equal(chip(_val('solar_power', null), (v) => `${v} W`), MISSING);
});

test('the SOC chip beside them is still right', () => {
    assert.equal(socDisplay(null).label, MISSING);
    assert.equal(socDisplay(97).label, '97%');
    assert.equal(socDisplay(0).label, '0%');   // a flat pack is a reading
});

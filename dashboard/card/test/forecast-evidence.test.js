/**
 * The forecast-evidence cells must EXPLAIN, not just state.
 *
 * Driven by two questions asked while reading the live card: whether "1D/2D"
 * were placeholders (they are horizons) and whether the "119 days settled"
 * accuracy is used for anything (it is — it is the pool the ledger's p20 is
 * drawn from, and having it removes the pessimism margin). Both are failures
 * of wording, not of maths.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
    capacityConsequence, horizonLabel, providerName, trustConsequence,
} from '../src/util/forecast-evidence.js';

// A translator stand-in: returns the key so assertions read as intent.
const t = (k) => k;

test('the provider is named, not abbreviated to a horizon code', () => {
    assert.equal(providerName('forecast_solar'), 'Forecast.Solar');
    assert.equal(providerName('solcast'), 'Solcast');
    assert.equal(providerName('open_meteo'), 'Open-Meteo');
});

test('an unknown provider degrades to something readable, never junk', () => {
    assert.equal(providerName('some_new_integration'), 'some new integration');
    for (const bad of [null, undefined, '', 'unknown', 'unavailable', 'none'])
        assert.equal(providerName(bad), null, `sourceState=${JSON.stringify(bad)}`);
});

test('the horizon label says WHO forecasts and WHEN for — not "1D"', () => {
    const l1 = horizonLabel('forecast_solar', 1, t);
    const l2 = horizonLabel('forecast_solar', 2, t);
    assert.equal(l1, 'Forecast.Solar · horizon_tomorrow');
    assert.equal(l2, 'Forecast.Solar · horizon_two_days');
    assert.ok(!/\b1D\b|\b2D\b/.test(l1 + l2), 'the cryptic codes are gone');
});

test('with no known provider the label still says the horizon', () => {
    assert.equal(horizonLabel(null, 1, t), 'forecast_accuracy · horizon_tomorrow');
});

test('a horizon the provider does not publish says so — not "no source"', () => {
    assert.equal(
        trustConsequence({ available: false, trust: null, days: 0, minDays: 7, t }),
        'horizon_not_published');
});

test('measured trust reports what it bought: no safety margin added', () => {
    assert.equal(
        trustConsequence({ available: true, trust: 0.968, days: 119, minDays: 7, t }),
        'horizon_trusted_effect');
});

test('while learning it says how far along AND that a margin applies', () => {
    const s = trustConsequence({ available: true, trust: null, days: 3, minDays: 7, t: (k) => `${k}:{days}/{needed}` });
    assert.equal(s, 'horizon_learning_effect:3/7', 'the counts are substituted');
});

test('pack size names which capacity the maths is actually using', () => {
    assert.equal(capacityConsequence({ measuredKwh: null, nameplateKwh: 15, t }),
                 'capacity_using_nameplate');
    assert.equal(capacityConsequence({ measuredKwh: 14.2, nameplateKwh: 15, t }),
                 'capacity_using_measured');
    assert.equal(capacityConsequence({ measuredKwh: 15.0, nameplateKwh: 15.0, t }),
                 'capacity_matches_nameplate');
});

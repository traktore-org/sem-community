import { test } from 'node:test';
import assert from 'node:assert/strict';
import { applyRecommendation, recommendationFrom, recommendationText } from '../src/util/forecast-recommend.js';

const attrs = { recommended_source: 'open_meteo', recommended_by_pct: 31.4, recommended_days: 20 };

test('a published recommendation becomes a sentence with provider, days and percent', () => {
    const rec = recommendationFrom(attrs, 'solcast');
    assert.deepEqual(rec, { source: 'open_meteo', pct: 31, days: 20 });
    const t = () => '{provider} closest over {days} days ({pct} % less error).';
    assert.equal(recommendationText(rec, () => 'Open-Meteo', t), 'Open-Meteo closest over 20 days (31 % less error).');
});

test('nothing shows without a recommendation, or when it is the source in use', () => {
    assert.equal(recommendationFrom({}, 'solcast'), null);
    assert.equal(recommendationFrom(null, 'solcast'), null);
    assert.equal(recommendationFrom(attrs, 'open_meteo'), null);
    assert.equal(recommendationFrom({ ...attrs, recommended_by_pct: 'x' }, 'solcast'), null);
});

test('the tap sets solar_forecast_source through the picker option path', () => {
    const calls = [];
    applyRecommendation((k, v) => calls.push([k, v]), { source: 'open_meteo' });
    assert.deepEqual(calls, [['solar_forecast_source', 'open_meteo']]);
});

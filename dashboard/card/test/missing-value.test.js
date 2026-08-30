/**
 * #dashboard-audit — an unavailable sensor must not render as 0.
 *
 * PROD, 30.08, mid-dropout: the System tab's diagnostics read
 * "Solar 0W · Grid 0W · Battery 0W · SOC 0% · EV 0W" while those sensors
 * were `unavailable`. The card's own "Unavailable Sensors: 8" row proved it
 * knew. A hard zero on a diagnostics page is a false measurement.
 *
 * Run: `npm test` (from dashboard/card).
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fmtNum, isMissing, MISSING } from '../src/util/missing-value.js';

test('a real reading formats exactly as before', () => {
    assert.equal(fmtNum({ state: '3816' }), '3816');
    assert.equal(fmtNum({ state: '3816.4' }), '3816');
    assert.equal(fmtNum({ state: '91.37' }, 1), '91.4');
    assert.equal(fmtNum({ state: '0' }), '0', 'a genuine zero stays zero');
    assert.equal(fmtNum({ state: '-250' }), '-250', 'export/discharge sign kept');
});

test('an absent measurement renders as the em-dash, never 0', () => {
    for (const s of ['unavailable', 'unknown', '', 'not-a-number']) {
        assert.equal(fmtNum({ state: s }), MISSING, `state=${JSON.stringify(s)}`);
    }
    assert.equal(fmtNum(undefined), MISSING, 'entity missing entirely');
    assert.equal(fmtNum(null), MISSING);
    assert.equal(fmtNum({}), MISSING, 'state key absent');
});

test('isMissing is the same judgement, exposed', () => {
    assert.equal(isMissing({ state: 'unavailable' }), true);
    assert.equal(isMissing({ state: '0' }), false, 'zero is a measurement');
    assert.equal(isMissing(undefined), true);
});

test('the dropout that started this: solar out, grid live', () => {
    // Exactly PROD's state at 08:0x — solar/battery/SOC out, grid reporting.
    const line = `Solar ${fmtNum({ state: 'unavailable' })}W · `
        + `Grid ${fmtNum({ state: '2631' })}W · `
        + `SOC ${fmtNum({ state: 'unavailable' })}%`;
    assert.equal(line, 'Solar —W · Grid 2631W · SOC —%');
    assert.ok(!line.includes('0W'), 'no fabricated zero anywhere in the line');
});

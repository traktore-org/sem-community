/**
 * (#1081) The COP curve helpers both dashboards share.
 */
import { test } from 'node:test';
import assert from 'node:assert';
import {
    parseCopCurve, formatCopCurve, curveRows, curveToSend, heatCostNow, heatCostLine,
} from '../src/util/heat-pump-cost.js';

const T = {
    hp_cop_now: 'COP now {cop}',
    hp_cop_now_at: 'COP now {cop} at {temp}',
    hp_heat_costs: 'heat costs {price}',
};
const t = (k) => T[k] || k;

test('the curve reads like the server reads it', () => {
    assert.deepEqual(parseCopCurve('12:4.2, -7:2.5, 2:3.2'),
        [{ c: -7, cop: 2.5 }, { c: 2, cop: 3.2 }, { c: 12, cop: 4.2 }]);
    for (const bad of ['', null, '5:3', '1:2,2:3,3:4,4:5', 'a:b,1:2', '1:2,1:3', '1:0,5:3', '1:2:3,4:5']) {
        assert.equal(parseCopCurve(bad), null, String(bad));
    }
});

test('format sorts, rounds and drops empty rows', () => {
    assert.equal(formatCopCurve([{ c: 12, cop: 4.2 }, { c: -7, cop: 2.5 }, { c: null, cop: null }]),
        '-7:2.5, 12:4.2');
    assert.equal(formatCopCurve([]), '');
    assert.equal(formatCopCurve(null), '');
});

test('the editor has three rows, the curve first', () => {
    const rows = curveRows('-7:2.5, 12:4.2');
    assert.equal(rows.length, 3);
    assert.deepEqual(rows[0], { c: -7, cop: 2.5 });
    assert.deepEqual(rows[2], { c: null, cop: null });
    assert.equal(curveRows('').length, 3);
});

test('only a whole curve is sent; all empty clears it', () => {
    assert.equal(curveToSend([{ c: -7, cop: 2.5 }, { c: 12, cop: 4.2 }]), '-7:2.5, 12:4.2');
    assert.equal(curveToSend([{ c: -7, cop: 2.5 }, { c: null, cop: null }]), null);
    assert.equal(curveToSend([{ c: null, cop: null }]), '');
    assert.equal(curveToSend([{ c: 2, cop: 3 }, { c: 2, cop: 4 }]), null);
});

test('the live line says the outdoor reading only with a curve', () => {
    const curve = heatCostNow({ state: '0.0812', attributes: {
        cop_used: 3.7, cop_source: 'curve', outdoor_c: 7, unit_of_measurement: 'CHF/kWh' } });
    assert.equal(heatCostLine(curve, t), 'COP now 3.7 at 7 °C · heat costs 0.081 CHF/kWh');
    const flat = heatCostNow({ state: 'unknown', attributes: { cop_used: 3, cop_source: 'flat' } });
    assert.equal(heatCostLine(flat, t), 'COP now 3');
});

test('no sensor or no COP is no line', () => {
    assert.equal(heatCostNow(undefined), null);
    assert.equal(heatCostNow({ state: '0.1', attributes: {} }), null);
    assert.equal(heatCostLine(null, t), '');
});

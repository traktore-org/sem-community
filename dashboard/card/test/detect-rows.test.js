/**
 * (#1054 follow-up) The Detected-hardware rows and the power pickers read
 * the same facts the crawler does.
 *
 * - a near miss that carries a complete offer is "charger found — add it",
 *   not "no role matched";
 * - a charger that already exists is never created again: no ``<id>_1``;
 * - a sensor in kW with no device class IS a power reading (go-e ``p_all``).
 */
import { test } from 'node:test';
import assert from 'node:assert';
import {
    chargerAddPlan, detectRowLabelKey, isPowerEntity,
} from '../src/util/detect-rows.js';

test('a near miss with a complete offer says so', () => {
    assert.equal(detectRowLabelKey({ suggested_charger: { id: 'goecharger_x' }, missing: [] }),
        'config_detect_offer');
});

test('a near miss without an offer still asks for a report', () => {
    assert.equal(detectRowLabelKey({ suggested_charger: {}, missing: ['control'] }),
        'config_detect_near_miss');
    assert.equal(detectRowLabelKey({}), 'config_detect_near_miss');
});

test('an existing charger is never created twice', () => {
    const plan = chargerAddPlan({ id: 'goecharger_x', name: 'go-e' },
        ['goecharger_x'], 1);
    assert.deepEqual(plan, { action: 'exists', id: 'goecharger_x' });
});

test('a new charger keeps the id the crawler gave it', () => {
    const plan = chargerAddPlan({ id: 'goecharger_x', name: 'go-e' }, ['ev_charger'], 1);
    assert.equal(plan.action, 'add');
    assert.equal(plan.charger.id, 'goecharger_x');
    assert.equal(plan.charger.ev_min_current, 6);
    assert.equal(plan.charger.ev_surplus_priority, 4);
});

test('no id means nothing to add', () => {
    assert.equal(chargerAddPlan({}, [], 0).action, 'none');
    assert.equal(chargerAddPlan(null, [], 0).action, 'none');
});

test('a kW sensor with no device class is a power reading', () => {
    assert.equal(isPowerEntity({ attributes: { unit_of_measurement: 'kW' } }), true);
    assert.equal(isPowerEntity({ attributes: { unit_of_measurement: 'W' } }), true);
    assert.equal(isPowerEntity({ attributes: { device_class: 'power', unit_of_measurement: 'W' } }), true);
});

test('a set class wins over the unit, and other units say nothing', () => {
    assert.equal(isPowerEntity({ attributes: { device_class: 'energy', unit_of_measurement: 'kWh' } }), false);
    assert.equal(isPowerEntity({ attributes: { unit_of_measurement: 'A' } }), false);
    assert.equal(isPowerEntity({ attributes: {} }), false);
    assert.equal(isPowerEntity(null), false);
});

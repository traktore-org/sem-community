// (#1321) The Now headline: no "the car waits" while the plug sensor says no
// car is plugged in. An unknown plug state keeps the old rule.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mount, S } from './card-harness.js';

function carFact(plugState, powerW = 0) {
    const states = {
        'sensor.sem_charger_keba_power': S(powerW, { unit_of_measurement: 'W' }),
        'sensor.sem_energy_plan': S('fits', { blocks: [], demands: [] }),
    };
    if (plugState !== undefined) states['binary_sensor.sem_charger_keba_connected'] = S(plugState);
    const el = mount('sem-next-now-card', states);
    Object.defineProperty(el, '_chargers', { get: () => ['keba'] });
    el._remainingKwh = () => 30;   // an open 30 kWh target, as on the owner's system
    return el._carFact();
}

test('no car plugged in: no car fact, so no "the car waits" headline', () => {
    assert.equal(carFact('off'), null);
});

test('plugged in with an open target: the car waits', () => {
    assert.equal(carFact('on')?.present, true);
});

test('unknown plug state keeps the old rule', () => {
    assert.equal(carFact(undefined)?.present, true);
    assert.equal(carFact('unavailable')?.present, true);
});

test('drawing power always counts, whatever the plug sensor says', () => {
    assert.equal(carFact('off', 4100)?.charging, true);
});

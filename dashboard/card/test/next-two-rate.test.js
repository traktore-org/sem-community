// (#1385) A schedule or two-rate tariff is not "one rate": only the level
// 'flat' says one price. A one-rate tariff (level 'flat') stays one rate.
import test from 'node:test';
import assert from 'node:assert/strict';
import { tariffKind } from '../src/util/price-level.js';
import { mount, S } from './card-harness.js';

const states = (level, dyn) => ({
    'sensor.sem_tariff_current_import_rate': S(0.32, { is_dynamic: dyn, price_level: level }),
    'sensor.sem_tariff_price_level': S(level),
});

test('a schedule tariff in its peak or off-peak hour is not one rate', () => {
    assert.notEqual(tariffKind(states('normal', false)), 'flat');
    assert.notEqual(tariffKind(states('cheap', false)), 'flat');
});

test('a one-rate tariff stays one rate', () => {
    assert.equal(tariffKind(states('flat', false)), 'flat');
});

test('the Plan block reason keeps "Cheapest hours" on a schedule tariff', () => {
    const el = mount('sem-next-plan-card', states('cheap', false));
    el._t = (k) => ({ next_reason_cheapest_hours: 'Cheapest hours', next_reason_one_rate: 'One rate' }[k] ?? k);
    el._tf = (k) => el._t(k);
    assert.equal(el._reasonText('cheapest_hours', {}), 'Cheapest hours');
});

/** (#1321) A command and a device read as words, never as codes. */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { actionWords, deviceName } from '../src/util/why-rows.js';

const t = (k) => ({ next_act_limit_discharge: 'limit discharge', why_kind_battery: 'Battery', why_kind_charger: 'Wallbox' }[k] || k);

test('a known verb is translated, an unknown one reads as plain words', () => {
    assert.equal(actionWords('limit_discharge', t), 'limit discharge');
    assert.equal(actionWords('stop_force_charge', t), 'stop force charge');
    assert.equal(actionWords('', t), '');
});

test('a service call stays as it is', () => {
    assert.equal(actionWords('keba.set_current', t), 'keba.set_current');
});

test('a name that is only an id gives way to the kind', () => {
    assert.equal(deviceName({ name: 'primary', device_id: 'battery:primary', kind: 'battery' }, t), 'Battery');
    assert.equal(deviceName({ name: 'keba_fa87f74cd3', device_id: 'ev:keba_fa87f74cd3', kind: 'charger' }, t), 'Wallbox');
    assert.equal(deviceName({ name: 'Heat pump', device_id: 'heat_pump', kind: 'load' }, t), 'Heat pump');
});

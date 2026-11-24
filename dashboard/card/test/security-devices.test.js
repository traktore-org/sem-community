/** (#1419) Security devices are never offered as a load. */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { isSecurityEntity, withoutSecurity } from '../src/util/security-devices.js';

const hass = { entities: {
    'camera.voortuin': { entity_id: 'camera.voortuin', device_id: 'cam' },
    'switch.voortuin_camera_enabled': { entity_id: 'switch.voortuin_camera_enabled', device_id: 'cam' },
    'switch.dishwasher': { entity_id: 'switch.dishwasher', device_id: 'plug' },
    'lock.door': { entity_id: 'lock.door', device_id: 'lk' },
    'switch.door_auto_lock': { entity_id: 'switch.door_auto_lock', device_id: 'lk' },
} };

test('a camera device and its switch are security entities', () => {
    assert.equal(isSecurityEntity(hass, 'camera.voortuin'), true);
    assert.equal(isSecurityEntity(hass, 'switch.voortuin_camera_enabled'), true);
    assert.equal(isSecurityEntity(hass, 'switch.door_auto_lock'), true);
});

test('a plain plug, an unknown entity and no entity are not', () => {
    assert.equal(isSecurityEntity(hass, 'switch.dishwasher'), false);
    assert.equal(isSecurityEntity(hass, 'switch.helper'), false);
    assert.equal(isSecurityEntity(hass, ''), false);
});

test('the picker filter drops security devices and keeps the caller filter', () => {
    const f = withoutSecurity(hass, (st) => st.entity_id !== 'switch.dishwasher');
    assert.equal(f({ entity_id: 'switch.voortuin_camera_enabled' }), false);
    assert.equal(f({ entity_id: 'switch.dishwasher' }), false);
    assert.equal(f({ entity_id: 'switch.other' }), true);
    assert.equal(withoutSecurity(hass)({ entity_id: 'switch.dishwasher' }), true);
});

test('an appliance with a child lock is still a load; a door lock is not', () => {
    const h = {
        entities: {
            'switch.washer': { entity_id: 'switch.washer', device_id: 'w' },
            'sensor.washer_power': { entity_id: 'sensor.washer_power', device_id: 'w' },
            'lock.washer_child_lock': { entity_id: 'lock.washer_child_lock', device_id: 'w', entity_category: 'config' },
            'switch.door_relay': { entity_id: 'switch.door_relay', device_id: 'd' },
            'lock.front': { entity_id: 'lock.front', device_id: 'd' },
        },
        states: { 'sensor.washer_power': { attributes: { device_class: 'power' } } },
    };
    assert.equal(isSecurityEntity(h, 'switch.washer'), false);
    assert.equal(isSecurityEntity(h, 'switch.door_relay'), true);
});

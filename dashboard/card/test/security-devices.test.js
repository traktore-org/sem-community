/** (#1419) Security devices are never offered as a load. */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { isSecurityEntity, securityRole, withoutSecurity } from '../src/util/security-devices.js';

const hass = { entities: {
    'camera.voortuin': { entity_id: 'camera.voortuin', device_id: 'cam' },
    'switch.voortuin_camera_enabled': { entity_id: 'switch.voortuin_camera_enabled', device_id: 'cam' },
    'switch.washer': { entity_id: 'switch.washer', device_id: 'w' },
    'lock.washer_child_lock': { entity_id: 'lock.washer_child_lock', device_id: 'w', entity_category: 'config' },
    'switch.door_relay': { entity_id: 'switch.door_relay', device_id: 'd' },
    'lock.child_room_door': { entity_id: 'lock.child_room_door', device_id: 'd' },
    'switch.dishwasher': { entity_id: 'switch.dishwasher', device_id: 'plug' },
} };

test('the role is read from HA metadata, not from names', () => {
    assert.equal(securityRole(hass, 'switch.voortuin_camera_enabled'), 'security');
    assert.equal(securityRole(hass, 'switch.washer'), '');            // config child lock
    assert.equal(securityRole(hass, 'switch.door_relay'), 'lock');    // "child" only in its id
    assert.equal(securityRole(hass, 'switch.dishwasher'), '');
});

test('automatic listing leaves locks alone; a user may still pick one', () => {
    assert.equal(isSecurityEntity(hass, 'switch.door_relay'), true);
    assert.equal(isSecurityEntity(hass, 'switch.door_relay', { chosen: true }), false);
    assert.equal(isSecurityEntity(hass, 'switch.voortuin_camera_enabled', { chosen: true }), true);
});

test('the picker drops cameras and keeps the caller filter', () => {
    const f = withoutSecurity(hass, (st) => st.entity_id !== 'switch.dishwasher');
    assert.equal(f({ entity_id: 'switch.voortuin_camera_enabled' }), false);
    assert.equal(f({ entity_id: 'switch.dishwasher' }), false);
    assert.equal(f({ entity_id: 'switch.washer' }), true);
});

import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { roleSource, showsRoleLegend } from '../src/util/role-source.js';

const cfg = {
    ev_charger_refs: [
        { id: 'goe', device_id: 'dev1',
          overrides: { ev_charging_power_sensor: 'sensor.my_meter' },
          cleared: ['ev_session_energy_sensor'],
          found: { ev_connected_sensor: 'sensor.goe_car_status',
                   ev_charging_power_sensor: 'sensor.goe_p_all',
                   ev_session_energy_sensor: 'sensor.goe_session' } },
        { id: 'keba', device_id: null, overrides: { ev_connected_sensor: 'binary_sensor.plug' },
          cleared: [], found: {} },
    ],
};

describe('roleSource (#1054)', () => {
    it('a role the crawler found is detected', () => {
        assert.deepEqual(roleSource(cfg, 'goe', 'ev_connected_sensor'),
            { kind: 'detected', detected: 'sensor.goe_car_status' });
    });
    it('a role the user set is "you", with the detected one to go back to', () => {
        assert.deepEqual(roleSource(cfg, 'goe', 'ev_charging_power_sensor'),
            { kind: 'you', detected: 'sensor.goe_p_all' });
    });
    it('a role the crawler did not find, or the user cleared, is not found', () => {
        assert.equal(roleSource(cfg, 'goe', 'ev_start_stop_entity').kind, 'none');
        assert.equal(roleSource(cfg, 'goe', 'ev_session_energy_sensor').kind, 'none');
    });
    it('a device-less charger shows no chips and no legend', () => {
        assert.equal(roleSource(cfg, 'keba', 'ev_connected_sensor').kind, null);
        assert.equal(showsRoleLegend(cfg, 'keba'), false);
        assert.equal(showsRoleLegend(cfg, 'goe'), true);
    });
    it('a setting is not a role', () => {
        assert.equal(roleSource(cfg, 'goe', 'vehicle_soc_entity').kind, null);
    });
    it('no refs yet: no chips', () => {
        assert.equal(roleSource({}, 'goe', 'ev_connected_sensor').kind, null);
    });
});

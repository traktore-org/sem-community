/** (#1419) A load nobody turned on says so on its pill. */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { deviceRows, statePill } from '../src/util/next-devices.js';

const row = (info) => deviceRows({ energy_dashboard_x: { name: 'X', priority: 1, ...info } })[0];

test('Off by default reads "Not controlled — turn on"', () => {
    const p = statePill(row({ control_mode: 'off', mode_chosen: false }), {});
    assert.equal(p.key, 'next_st_not_controlled');
});

test('Off the user chose keeps its own words', () => {
    assert.equal(statePill(row({ control_mode: 'off', mode_chosen: true }), {}).key, 'next_st_off_mode');
    assert.equal(statePill(row({ control_mode: 'off' }), {}).key, 'next_st_off_mode');
});

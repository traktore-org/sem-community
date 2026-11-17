// (#1354) A charger's settings have one name per thing in every card.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { CHARGER_TEXT, CHARGE_MODES, chargeModeKey, targetEntities } from '../src/util/charger-questions.js';

test('the target pair writes the entities the old steppers wrote', () => {
    assert.deepEqual(targetEntities('keba', 'kwh'), {
        atLeast: 'number.sem_charger_keba_daily_ev_target', upTo: 'number.sem_charger_keba_daily_ev_target_max' });
    assert.deepEqual(targetEntities('keba', 'soc'), {
        atLeast: 'number.sem_charger_keba_target_soc', upTo: 'number.sem_charger_keba_target_soc_max' });
});

test('the modes keep their stored values and order', () => {
    assert.deepEqual(CHARGE_MODES, ['solar_only', 'solar_plus_battery', 'solar_plus_cheap', 'min_plus_solar', 'always_max', 'off']);
    assert.equal(chargeModeKey('min_plus_solar'), 'charge_mode_min_plus_solar');
});

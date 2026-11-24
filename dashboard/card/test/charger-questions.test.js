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

test('(#1381) four modes, in one order; the stored strategy keys still name hints', () => {
    assert.deepEqual(CHARGE_MODES, ['sun', 'sun_tariff', 'now', 'off']);
    assert.equal(chargeModeKey('sun_tariff'), 'charge_mode_sun_tariff');
    assert.equal(chargeModeKey('min_plus_solar'), 'charge_mode_min_plus_solar');
});

test('(#1381) a Now that ends at a time: minutes to that time today, else tomorrow', async () => {
    const { minutesUntil } = await import('../src/util/charger-questions.js');
    const now = new Date(2026, 10, 24, 20, 0);
    assert.equal(minutesUntil('21:30', now), 90);
    assert.equal(minutesUntil('06:00', now), 600);
    assert.equal(minutesUntil('nonsense', now), null);
});

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

test('every charger card names the target "At least / Up to" and the departure "Charge by"', () => {
    const cards = new URL('../src/cards/', import.meta.url);
    const cfg = fs.readFileSync(new URL('sem-config-card.js', cards), 'utf8');
    const ev = fs.readFileSync(new URL('sem-ev-status-card.js', cards), 'utf8');
    assert.ok(cfg.includes('CHARGER_TEXT.atLeast') && cfg.includes('CHARGER_TEXT.upTo'));
    assert.ok(!/'config_ev_(daily_target|daily_target_max|target_soc|target_soc_max)'/.test(cfg),
        'no second name ("Daily target / Max daily", "Target SOC / Max SOC") for the pair');
    assert.ok(ev.includes('CHARGER_TEXT.atLeast') && ev.includes('CHARGER_TEXT.departure'));
    const en = JSON.parse(fs.readFileSync(new URL('../../translations.json', import.meta.url), 'utf8')).en;
    assert.equal(en[CHARGER_TEXT.atLeast], 'At least');
    assert.equal(en[CHARGER_TEXT.upTo], 'Up to');
    assert.equal(en[CHARGER_TEXT.departure], 'Charge by');
});

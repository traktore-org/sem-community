import { test } from 'node:test';
import assert from 'node:assert/strict';

import { stateLabel, VOCAB } from '../src/util/state-label.js';

// #1053 — a Dutch System tab read "Netmodus: manual", the Control tab
// "Netteken (auto): normal" and "custom · Normaal". The card mapped two of
// the six grid modes and printed the rest, and three more sensors as they
// came. `t` here marks a translated word so the test can tell it from the raw.
const t = (k) => `«${k}»`;

test('every grid mode reaches a translation key', () => {
    assert.equal(stateLabel('diag_grid_mode', 'manual', t), '«grid_manual»');
    assert.equal(stateLabel('diag_grid_mode', 'combined', t), '«grid_combined»');
    assert.equal(stateLabel('diag_grid_mode', 'split', t), '«grid_split»');
    assert.equal(stateLabel('diag_grid_mode', 'split-declared', t), '«grid_split»');
    assert.equal(stateLabel('diag_grid_mode', 'split-lowconf', t),
                 '«grid_split_unverified»');
    assert.equal(stateLabel('diag_grid_mode', 'split-declared-unverified', t),
                 '«grid_split_unverified»');
});

test('the grid sign and the heat pump mode are translated', () => {
    assert.equal(stateLabel('diag_grid_sign', 'normal', t), '«normal»');
    assert.equal(stateLabel('diag_grid_sign', 'negated', t), '«sign_negated»');
    assert.equal(stateLabel('heat_pump_mode', 'force_on', t), '«force_on»');
    assert.equal(stateLabel('heat_pump_mode', 'normal', t), '«normal»');
});

test('a battery sign sentence is translated word by word', () => {
    assert.equal(stateLabel('diag_battery_sign', 'normal (learning)', t),
                 '«normal» («learning»)');
    assert.equal(
        stateLabel('diag_battery_sign', 'b1: negated, b2: normal (learning)', t),
        'b1: «sign_negated», b2: «normal» («learning»)');
});

test('the tariff source: own words translated, brands by name', () => {
    assert.equal(stateLabel('tariff_provider', 'custom', t), '«custom»');
    assert.equal(stateLabel('tariff_provider', 'static', t), '«tariff_static»');
    assert.equal(stateLabel('tariff_provider', 'calendar', t), '«tariff_calendar»');
    assert.equal(stateLabel('tariff_provider', 'nordpool_official', t), 'Nord Pool');
    assert.equal(stateLabel('tariff_provider', 'tibber', t), 'Tibber');
    assert.equal(stateLabel('tariff_provider', 'entsoe', t), 'ENTSO-e');
});

test('charger control: a label, and nothing for no charger', () => {
    assert.equal(stateLabel('diag_charger_control', 'number', t),
                 '«charger_control_number»');
    assert.equal(stateLabel('diag_charger_control', 'none', t), '');
});

test('a word with no row stays visible as it is', () => {
    assert.equal(stateLabel('diag_grid_mode', 'split-new-kind', t), 'split-new-kind');
    assert.equal(stateLabel('tariff_provider', 'someflow', t), 'someflow');
    assert.equal(stateLabel('not_a_vocab_sensor', 'x', t), 'x');
});

test('an empty state is empty, not a label', () => {
    assert.equal(stateLabel('diag_grid_mode', '', t), '');
    assert.equal(stateLabel('diag_grid_mode', undefined, t), '');
});

test('every table row is a key the translator is asked for', () => {
    const asked = [];
    const spy = (k) => { asked.push(k); return k; };
    for (const [sensor, table] of Object.entries(VOCAB)) {
        for (const word of Object.keys(table)) {
            stateLabel(sensor, word, spy);
        }
    }
    assert.ok(asked.length > 20);
    assert.ok(asked.every(k => typeof k === 'string' && k.length > 0));
});

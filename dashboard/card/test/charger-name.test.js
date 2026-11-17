/**
 * (#1321) A charger's name never comes from its translated friendly name.
 * Rien, PR 1322: on a Dutch install "SEM Laadpaal Links Vermogen" did not
 * match the English "… Power" pattern, so SEM Next showed "ev charger 1".
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { chargerNameOf } from '../src/util/charger-name.js';

const st = (friendly, name) => ({
    'sensor.sem_charger_ev_charger_1_power': {
        state: '0', attributes: { friendly_name: friendly, ...(name ? { charger_name: name } : {}) },
    },
});

test('the configured name wins in every language', () => {
    for (const f of ['SEM Laadpaal Links Vermogen', 'SEM Wallbox Links Leistung', 'SEM Left charger Power']) {
        assert.equal(chargerNameOf(st(f, 'Laadpaal Links'), 'ev_charger_1'), 'Laadpaal Links');
    }
});

test('the translated friendly name is never parsed', () => {
    assert.equal(chargerNameOf(st('SEM Laadpaal Links Vermogen'), 'ev_charger_1'), 'ev charger 1');
    assert.equal(chargerNameOf(st('SEM Left charger Power'), 'ev_charger_1'), 'ev charger 1');
});

test('nothing known gives the id', () => {
    assert.equal(chargerNameOf({}, 'ev_charger_1'), 'ev charger 1');
    assert.equal(chargerNameOf(undefined, 'keba_abc'), 'keba abc');
    assert.equal(chargerNameOf(st('x', '   '), 'ev_charger_1'), 'ev charger 1');
});

test('a custom prefix is honoured', () => {
    const s = { 'sensor.my_charger_a_power': { attributes: { charger_name: 'A' } } };
    assert.equal(chargerNameOf(s, 'a', 'sensor.my_'), 'A');
});

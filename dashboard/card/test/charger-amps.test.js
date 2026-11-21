/**
 * #1407 — a charge SEM did not start read "0 A" on the cards.
 *
 * Another system (evcc) charged a Zaptec at 7.26 A on one phase, SEM's mode
 * Off. The cards showed SEM's own command, 0 A, beside 1.5 kW. Every card now
 * asks one rule, `chargerAmps`: the charger's own phase current first, SEM's
 * command only while SEM sends one, and unknown (no number) while power flows
 * with neither.
 *
 * Run: `npm test` (from dashboard/card).
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { chargerAmps } from '../src/util/charger-amps.js';

function fakeCard({ measured, commanded, powerW }) {
    const phases = measured === undefined ? {} : { c1: { active_phases: 1, measured_current: measured } };
    return {
        _attrs: (id) => (id === 'sensor.sem_charging_state' ? { per_charger_phases: phases } : {}),
        _num: (id) => (id === 'sensor.sem_charger_c1_commanded_current' ? commanded : null),
        _powerW: (id) => (id === 'sensor.sem_charger_c1_power' ? powerW : null),
    };
}

test('the charger\'s own phase current wins over SEM\'s 0 A (the report)', () => {
    assert.equal(chargerAmps(fakeCard({ measured: 7.3, commanded: 0, powerW: 1500 }), 'c1'), 7.3);
});

test('the charger\'s own phase current wins over SEM\'s command', () => {
    assert.equal(chargerAmps(fakeCard({ measured: 9.8, commanded: 16, powerW: 6700 }), 'c1'), 9.8);
});

test('a measured 0 A is a reading, not missing', () => {
    assert.equal(chargerAmps(fakeCard({ measured: 0, commanded: 0, powerW: 0 }), 'c1'), 0);
});

test('no phase sensors: SEM\'s command while it sends one', () => {
    assert.equal(chargerAmps(fakeCard({ measured: null, commanded: 10, powerW: 6900 }), 'c1'), 10);
});

test('no phase sensors, power flows, no command: unknown, never 0 A', () => {
    assert.equal(chargerAmps(fakeCard({ measured: null, commanded: 0, powerW: 1500 }), 'c1'), null);
    assert.equal(chargerAmps(fakeCard({ measured: undefined, commanded: 0, powerW: 1500 }), 'c1'), null);
});

test('no phase sensors, nothing drawn: SEM\'s 0 A is true', () => {
    assert.equal(chargerAmps(fakeCard({ measured: null, commanded: 0, powerW: 0 }), 'c1'), 0);
});

test('only the rule reads SEM\'s command for a card to show', () => {
    // The entity watch lists may name it; no card may read it on its own.
    const dirs = ['../src/cards/', '../src/util/'];
    const readers = [];
    for (const d of dirs) {
        const url = new URL(d, import.meta.url);
        for (const f of readdirSync(url)) {
            if (!f.endsWith('.js') || f === 'charger-amps.js') continue;
            const src = readFileSync(new URL(f, url), 'utf8');
            for (const line of src.split('\n')) {
                if (/_commanded_current/.test(line) && /_num\(|_str\(|_powerW\(|states\?*\.?\[/.test(line)) readers.push(f + ': ' + line.trim());
            }
        }
    }
    assert.deepEqual(readers, []);
});

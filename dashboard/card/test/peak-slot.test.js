/**
 * "4.3 kW charging and 4.36 kW margin" — both true, and the card explained
 * neither (Guido, 03.09). The peak block shows a 15-minute AVERAGE; the
 * instantaneous draw and the #864 slot budget were missing, so the card read
 * as a contradiction at every ramp.
 *
 * Run: `npm test` (from dashboard/card).
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
    SLOT_MIN, hhmm, importKw, slotBudgetKwh, slotStatus, slotWindow,
} from '../src/util/peak-slot.js';

const at = (h, m, s = 0) => new Date(2026, 8, 3, h, m, s);

test('the slot is the utility\'s, aligned to :00/:15/:30/:45', () => {
    const w = slotWindow(at(20, 37, 12));
    assert.equal(hhmm(w.start), '20:30');
    assert.equal(hhmm(w.end), '20:45');
    assert.equal(Math.round(w.elapsedS), 7 * 60 + 12);
    assert.equal(SLOT_MIN, 15);
});

test('a slot boundary belongs to the slot it opens', () => {
    assert.equal(hhmm(slotWindow(at(21, 0, 0)).start), '21:00');
    assert.equal(hhmm(slotWindow(at(20, 59, 59)).start), '20:45');
});

test('the budget is the target for a quarter hour', () => {
    assert.equal(slotBudgetKwh(6.0), 1.5);
    assert.equal(slotBudgetKwh(0), null, 'uncapped is not a budget of zero');
    assert.equal(slotBudgetKwh(undefined), null);
});

test('the slot row carries what the guard steers by', () => {
    const s = slotStatus({ targetKw: 6.0, usedKwh: 0.83, allowedW: 4023, now: at(20, 38) });
    assert.equal(s.label, '20:30–20:45');
    assert.equal(s.budgetKwh, 1.5);
    assert.equal(s.allowedKw, 4.023);
    assert.ok(Math.abs(s.fraction - 0.5533) < 0.001);
    assert.equal(s.overBudget, false);
});

test('an over-budget slot fills the bar, never past it', () => {
    const s = slotStatus({ targetKw: 6.0, usedKwh: 2.4, allowedW: 0, now: at(20, 44) });
    assert.equal(s.fraction, 1);
    assert.equal(s.overBudget, true);
    assert.equal(s.allowedKw, 0);
});

test('nothing honest to say → no row', () => {
    assert.equal(slotStatus({ targetKw: 0, usedKwh: 0.5, allowedW: 100 }), null);
    assert.equal(slotStatus({ targetKw: 6, usedKwh: null, allowedW: 100 }), null);
    assert.equal(slotStatus({ targetKw: 6, usedKwh: 0.4, allowedW: null }).allowedKw, null);
});

test('import is the signed grid power, one direction only', () => {
    assert.equal(importKw(-4830), 4.83, 'negative is import (SEM convention)');
    assert.equal(importKw(2500), 0, 'exporting imports nothing');
    assert.equal(importKw('unavailable'), null);
});

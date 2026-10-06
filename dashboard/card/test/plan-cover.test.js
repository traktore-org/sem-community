import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import { battIndexes, homeCover, GRID_EPS_W } from '../src/util/plan-cover.js';

// #1063 — a home with no battery saw its sunny hours in the battery colour,
// under a "battery covers home" legend. Slots below are the shapes the
// backend publishes (sensor._energy_plan_attrs: slots + batt_runs).

test('the meter carrying the house is grid', () => {
    assert.equal(homeCover({ home_grid_w: 450 }, false), 'grid');
    assert.equal(homeCover({ home_grid_w: 450 }, true), 'grid');
    assert.equal(homeCover({ home_grid_w: GRID_EPS_W + 0.1 }, false), 'grid');
});

test('the battery colour needs the plan to say it drew the battery', () => {
    assert.equal(homeCover({ home_grid_w: 0 }, true), 'batt');
    assert.equal(homeCover({ home_grid_w: 0.4 }, true), 'batt');
});

test('nothing on the meter and no battery drawn is the sun', () => {
    // A sun slot: the ledger sets the net home draw to 0.
    assert.equal(homeCover({ home_grid_w: 0 }, false), 'sun');
    assert.equal(homeCover({ home_grid_w: 0.9 }, false), 'sun');
    // The reporter's home: no battery, so no run ever covers a slot.
    const none = battIndexes([]);
    for (const [i, w] of [0, 0.5, 1.0].entries()) {
        assert.notEqual(homeCover({ home_grid_w: w }, none.has(i)), 'batt');
    }
});

test('a missing draw is not a battery', () => {
    assert.equal(homeCover({}, false), 'sun');
    assert.equal(homeCover(null, false), 'sun');
    assert.equal(homeCover({ home_grid_w: null }, false), 'sun');
});

test('a plan from before #1063 keeps the old rule until the next stamp', () => {
    // No batt_runs on the entity: battIndexes says null, batt is undefined.
    assert.equal(battIndexes(undefined), null);
    assert.equal(battIndexes(null), null);
    assert.equal(homeCover({ home_grid_w: 0 }, undefined), 'batt');
    assert.equal(homeCover({ home_grid_w: 300 }, undefined), 'grid');
});

test('battIndexes reads inclusive runs and skips junk', () => {
    assert.deepEqual([...battIndexes([[0, 0], [2, 4]])].sort(), [0, 2, 3, 4]);
    assert.deepEqual([...battIndexes([[1, 'x'], 'bad', [5, 5]])], [5]);
    assert.equal(battIndexes([]).size, 0);
});

test('the plan card colours the Home row through homeCover', () => {
    const src = readFileSync(
        new URL('../src/cards/sem-energy-plan-card.js', import.meta.url), 'utf8');
    assert.match(src, /const battAt = battIndexes\(a\.batt_runs\)/);
    assert.match(src, /\(s, i\) => homeCover\(s, battAt \? battAt\.has\(i\) : undefined\)/);
    // The old rule — "under a watt on the meter means battery" — is gone.
    assert.doesNotMatch(src, /<=\s*GRID_EPS_W/);
    assert.doesNotMatch(src, /r\.v \? 'batt' : 'grid'/);
    // No battery: no battery icon on the Home row, no hand-over time.
    assert.match(src, /hasBatt \? 'mdi:home-battery' : 'mdi:home'/);
    assert.match(src, /const takeoverCell = !hasBatt \? nothing/);
    // Legend keys only for colours that are drawn.
    assert.match(src, /drawn\.has\('batt'\)/);
    assert.match(src, /drawn\.has\('sun'\)/);
    // Tomorrow: no battery row, no "battery charging" key.
    assert.match(src, /curve\.length > 1 \? html`<span class="key"><i class="sw" style="background:#f06292">/);
});

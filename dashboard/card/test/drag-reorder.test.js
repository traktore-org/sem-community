/**
 * Regression tests for the priority-list drag/reorder (#576).
 *
 * These lock in every scenario we hit while moving off SortableJS to the
 * Lit-native pointer-drag: the number/order desync, the 2/2 & 3/3 duplicate
 * priorities, dependency ("Requires") children separating from their parent,
 * and the drop-target math. The card imports these same functions, so the
 * tested logic IS the shipped logic.
 *
 * Run: `npm test` (from dashboard/card). No browser needed.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
    moveToIndex, regroupChildren, renumber, computeDropIndex,
} from '../src/util/drag-reorder.js';

const dev = (id, extra = {}) => ({ id, name: id, priority: 0, dependsOn: [], ...extra });
const ids = (arr) => arr.map(d => d.id);
const prios = (arr) => arr.map(d => d.priority);

// THE invariant that kills the whole bug class: the badge (= priority) is
// always the position, so it's a unique, gap-free 1..N — the number and the
// visual order can never disagree.
function assertBadgesAreSequential(arr) {
    assert.deepEqual(prios(arr), arr.map((_, i) => i + 1),
        `priority must equal position+1 (badge == order): got ${prios(arr)}`);
    assert.equal(new Set(prios(arr)).size, arr.length, 'priorities must be unique');
}

// ── moveToIndex: reordering ──────────────────────────────────────────────
test('moveToIndex: move down to a middle slot', () => {
    const out = moveToIndex([dev('a'), dev('b'), dev('c'), dev('d'), dev('e')], 'b', 3);
    assert.deepEqual(ids(out), ['a', 'c', 'd', 'b', 'e']);
    assertBadgesAreSequential(out);
});

test('moveToIndex: move up to the top', () => {
    const out = moveToIndex([dev('a'), dev('b'), dev('c')], 'c', 0);
    assert.deepEqual(ids(out), ['c', 'a', 'b']);
    assertBadgesAreSequential(out);
});

test('moveToIndex: move to the bottom (index clamped)', () => {
    const out = moveToIndex([dev('a'), dev('b'), dev('c')], 'a', 99);
    assert.deepEqual(ids(out), ['b', 'c', 'a']);
    assertBadgesAreSequential(out);
});

test('moveToIndex: unknown id leaves the order unchanged', () => {
    assert.deepEqual(ids(moveToIndex([dev('a'), dev('b')], 'zzz', 0)), ['a', 'b']);
});

test('no duplicate priorities after a sequence of moves (the 2/2, 3/3 bug)', () => {
    let list = [dev('a'), dev('b'), dev('c'), dev('d'), dev('e')];
    list = moveToIndex(list, 'e', 1);
    list = moveToIndex(list, 'a', 3);
    list = moveToIndex(list, 'c', 0);
    assertBadgesAreSequential(list);
});

test('the 1,5,2,3,4 desync can never recur: EV/battery/loads mixed reorder stays 1..N', () => {
    const list = [dev('ev_charger'), dev('heizband'), dev('shelly1'),
                  dev('home_battery'), dev('shelly2')];
    let out = moveToIndex(list, 'home_battery', 1);
    out = moveToIndex(out, 'ev_charger', 4);
    assertBadgesAreSequential(out);
});

// ── dependency ("Requires") children ─────────────────────────────────────
test('regroupChildren: a child sits immediately after its parent', () => {
    const out = regroupChildren([dev('p'), dev('x'), dev('c', { dependsOn: ['p'] })]);
    assert.deepEqual(ids(out), ['p', 'c', 'x']);
});

test('moving a parent brings its child along', () => {
    const out = moveToIndex([dev('a'), dev('p'), dev('c', { dependsOn: ['p'] }), dev('b')], 'p', 3);
    const pi = ids(out).indexOf('p'), ci = ids(out).indexOf('c');
    assert.equal(ci, pi + 1, `child must stay right after parent: ${ids(out)}`);
    assertBadgesAreSequential(out);
});

test('a child never separates from its parent across many moves (the "separated" bug)', () => {
    let list = [dev('p'), dev('c', { dependsOn: ['p'] }), dev('a'), dev('b')];
    for (const [id, to] of [['a', 0], ['b', 3], ['p', 2], ['a', 1]]) {
        list = moveToIndex(list, id, to);
        const pi = ids(list).indexOf('p'), ci = ids(list).indexOf('c');
        assert.equal(ci, pi + 1, `child adjacent after ${id}->${to}: ${ids(list)}`);
    }
});

test('orphan child (parent not in the list) is kept', () => {
    const out = regroupChildren([dev('a'), dev('orphan', { dependsOn: ['ghost'] })]);
    assert.ok(ids(out).includes('orphan'));
    assert.equal(out.length, 2);
});

test('two children of one parent both sit right after it', () => {
    const out = regroupChildren([
        dev('p'), dev('a'),
        dev('c1', { dependsOn: ['p'] }), dev('c2', { dependsOn: ['p'] }),
    ]);
    const pi = ids(out).indexOf('p');
    // both children immediately follow the parent, before any non-child
    assert.deepEqual(ids(out).slice(pi, pi + 3).sort(), ['c1', 'c2', 'p']);
    assert.ok(ids(out).indexOf('a') > pi + 2, `non-child 'a' comes after the group: ${ids(out)}`);
    assert.equal(out.length, 4);
});

test('multi-parent child is grouped, not orphaned', () => {
    const out = regroupChildren([dev('a'), dev('b'), dev('c', { dependsOn: ['a', 'b'] })]);
    // c requires both a and b — it must be placed adjacent to one of them,
    // never left floating as an orphan, and never duplicated.
    assert.equal(out.length, 3);
    const ci = ids(out).indexOf('c');
    assert.ok(ci > 0, `child placed after a parent: ${ids(out)}`);
    assert.equal(ids(out).filter(x => x === 'c').length, 1, 'no duplicate');
});

// ── renumber directly ────────────────────────────────────────────────────
test('renumber assigns unique 1..N by position', () => {
    const out = renumber([dev('a', { priority: 9 }), dev('b', { priority: 9 })]);
    assert.deepEqual(prios(out), [1, 2]);
});

// ── computeDropIndex (pointer math) ──────────────────────────────────────
test('computeDropIndex: pointer above all rows → 0', () => {
    assert.equal(computeDropIndex([10, 30, 50, 70], 1, 5), 0);
});

test('computeDropIndex: pointer below all rows → last slot', () => {
    assert.equal(computeDropIndex([10, 30, 50, 70], 1, 100), 3);
});

test('computeDropIndex: excludes the dragged row from the count', () => {
    // dragging idx 0, pointer at 55 → rows at 30 & 50 are above → 2
    assert.equal(computeDropIndex([10, 30, 50, 70], 0, 55), 2);
});

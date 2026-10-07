/**
 * (#967) The EV strip paints the window open as "charging" only when a
 * start row sits AT the open. @alexmc1510's card painted 20:36–21:41 as a
 * booked charge inside his punta band: the composer's daytime fallback put a
 * start row at the open, and the old inline rule turned `night_open` into
 * `charging` unless a start carried the private-selector detail — a joint
 * or held-back start later in the night never counted.
 */
import { test } from 'node:test';
import assert from 'node:assert';
import { evStripSegments, evStripWindow } from '../src/util/ev-strip.js';

const T = (h, m = 0, dayOffset = 0) =>
    new Date(Date.UTC(2026, 8, 16 + dayOffset, h, m)).toISOString();
const ms = (iso) => new Date(iso).getTime();
const NOW = ms(T(14, 6));
const END = NOW + 12 * 3600 * 1000;           // 02:06 next day
const OPEN = T(20, 36);

const states = (segs) => segs.map(s => s.state);
const at = (segs, iso) => segs.find(s => s.s <= ms(iso) && ms(iso) < s.e)?.state;

test('a start AT the open is charging from the open (the in-night reactive row)', () => {
    const segs = evStripSegments([
        { kind: 'night_open', when: OPEN },
        { kind: 'ev_charge_start', when: OPEN, detail: 'plan_ev_charge_night' },
        { kind: 'ev_min_reached', when: T(1, 23, 1) },
    ], { now: NOW, end: END });
    assert.deepEqual(states(segs), ['idle', 'charging', 'done']);
    assert.equal(at(segs, OPEN), 'charging');
});

test('the daytime preview at the open is an ESTIMATE, never a booked charge', () => {
    const segs = evStripSegments([
        { kind: 'night_open', when: OPEN },
        { kind: 'ev_charge_start', when: OPEN, detail: 'plan_ev_charge_estimate' },
        { kind: 'ev_min_reached', when: T(21, 41) },
    ], { now: NOW, end: END });
    assert.equal(at(segs, OPEN), 'estimate');
    assert.ok(!states(segs).includes('charging'));
});

test('a joint-plan start at 00:00 means WAIT from the open — not charging', () => {
    const segs = evStripSegments([
        { kind: 'night_open', when: OPEN },
        { kind: 'ev_charge_start', when: T(0, 0, 1), detail: 'plan_ev_charge_joint' },
        { kind: 'ev_min_reached', when: T(5, 0, 1) },
    ], { now: NOW, end: END });
    assert.equal(at(segs, OPEN), 'wait', 'the old rule painted charging here');
    assert.equal(at(segs, T(21, 0)), 'wait');
    assert.equal(at(segs, T(0, 30, 1)), 'charging');
});

test('a tariff-held start behaves the same, whatever produced it', () => {
    const segs = evStripSegments([
        { kind: 'night_open', when: OPEN },
        { kind: 'ev_charge_start', when: T(1, 12, 1), detail: 'plan_ev_charge_tariff' },
    ], { now: NOW, end: END });
    assert.equal(at(segs, OPEN), 'wait');
    assert.equal(at(segs, T(1, 30, 1)), 'charging');
});

test('no start at all after the open is WAIT — the plan has not spoken', () => {
    const segs = evStripSegments([
        { kind: 'night_open', when: OPEN },
        { kind: 'ev_deadline', when: T(6, 0, 1) },
    ], { now: NOW, end: END });
    assert.equal(at(segs, OPEN), 'wait');
});

test('the fleet tariff flag can no longer turn another charger into a bar', () => {
    const rows = [
        { kind: 'night_open', when: OPEN },
        { kind: 'ev_charge_start', when: T(0, 0, 1), detail: 'plan_ev_charge_joint' },
    ];
    const a = evStripSegments(rows, { now: NOW, end: END, usingPerPlan: false, fleetTariffWait: false });
    const b = evStripSegments(rows, { now: NOW, end: END, usingPerPlan: true, fleetTariffWait: true });
    assert.deepEqual(states(a), states(b));
    assert.equal(at(a, OPEN), 'wait');
});

test('a first event beyond the horizon leaves one full idle bar, never an empty strip', () => {
    const segs = evStripSegments([
        { kind: 'night_open', when: T(21, 35, 1) },
        { kind: 'ev_charge_start', when: T(21, 35, 1), detail: 'plan_ev_charge_night' },
    ], { now: NOW, end: END });
    assert.deepEqual(segs, [{ s: NOW, e: END, state: 'idle' }]);
});

test('deadline and min-reached both end the charge as done', () => {
    for (const kind of ['ev_min_reached', 'ev_deadline']) {
        const segs = evStripSegments([
            { kind: 'ev_charge_start', when: T(22, 0), detail: 'plan_ev_charge_night' },
            { kind, when: T(1, 0, 1) },
        ], { now: NOW, end: END });
        assert.equal(at(segs, T(1, 30, 1)), 'done', kind);
    }
});

test('rows of other kinds and unparsable times are ignored, order does not matter', () => {
    const segs = evStripSegments([
        { kind: 'ev_min_reached', when: T(1, 0, 1) },
        { kind: 'cheap_start', when: T(0, 0, 1) },
        { kind: 'ev_charge_start', when: 'not a date' },
        { kind: 'ev_charge_start', when: T(22, 0), detail: 'plan_ev_charge_night' },
    ], { now: NOW, end: END });
    assert.deepEqual(states(segs), ['idle', 'charging', 'done']);
});


/**
 * (#967, second round) @alexmc1510, 17.09: *"unfortunately 'wait' status
 * start around 9pm, not 00:00."* His plan was right by then — wait through
 * punta, charge 00:00 → 05:39, target at 06:00 — but the strip is a FIXED
 * 12-hour window and he was reading it at 09:37. It ended at 21:37, so the
 * only thing on it was a wait band beginning at the window open and running
 * off the right edge: "something starts around 9pm", and nothing after.
 * A night plan needs a window that reaches the night.
 */
const H = 3600 * 1000;

test('the window still ends at 12 h when the whole plan fits inside it', () => {
    const w = evStripWindow([
        { kind: 'ev_charge_start', when: T(20, 36) },
        { kind: 'ev_min_reached', when: T(21, 41) },
    ], NOW);
    assert.equal(w.end, NOW + 12 * H);
    assert.equal(w.hours, 12);
});

test('his morning: the window reaches past the 06:00 deadline', () => {
    const morning = ms(T(9, 37));
    const w = evStripWindow([
        { kind: 'ev_charge_start', when: T(0, 0, 1), detail: 'plan_ev_charge_tariff' },
        { kind: 'ev_min_reached', when: T(5, 39, 1) },
        { kind: 'ev_deadline', when: T(6, 0, 1) },
    ], morning);
    assert.ok(w.end > ms(T(6, 0, 1)), 'the deadline must be ON the strip, not past its edge');
    assert.equal(w.end, ms(T(7, 0, 1)), 'rounded up to the next whole hour');
    const segs = evStripSegments([
        { kind: 'night_open', when: T(20, 26) },
        { kind: 'ev_charge_start', when: T(0, 0, 1), detail: 'plan_ev_charge_tariff' },
        { kind: 'ev_min_reached', when: T(5, 39, 1) },
    ], { now: morning, end: w.end });
    assert.equal(at(segs, T(21, 0)), 'wait', 'the wait he saw — now with an end');
    assert.equal(at(segs, T(2, 0, 1)), 'charging', 'and the charge he could not see');
    assert.equal(at(segs, T(6, 0, 1)), 'done');
});

test('the window never runs past the composer own 24 h horizon', () => {
    const w = evStripWindow([{ kind: 'ev_deadline', when: T(20, 0, 1) }], NOW);
    assert.equal(w.end, NOW + 24 * H);
    assert.equal(w.hours, 24);
});

test('only the EV rows stretch it — a night open alone does not', () => {
    const w = evStripWindow([{ kind: 'night_open', when: T(20, 36) },
                             { kind: 'now', when: T(14, 6) }], NOW);
    assert.equal(w.hours, 12);
});

test('an unparsable or past row cannot shrink the window', () => {
    const w = evStripWindow([
        { kind: 'ev_deadline', when: 'not a date' },
        { kind: 'ev_min_reached', when: T(6, 0) },      // 8 h in the past
    ], NOW);
    assert.equal(w.hours, 12);
    assert.equal(evStripWindow(null, NOW).hours, 12);
    assert.equal(evStripWindow([], NOW).hours, 12);
});


/**
 * (#1023) A night in two parts: the cheap hours, then the top-up right
 * before departure. Each start row carries its window's end (`until`), so the
 * hours between them are WAITING — before, the strip drew one charging bar
 * from the first start to the last end — and the top-up is its own state,
 * hatched on the card.
 */
test('a gap between two windows waits instead of charging', () => {
    const segs = evStripSegments([
        { kind: 'night_open', when: T(20, 36) },
        { kind: 'ev_charge_start', when: T(0, 0, 1), detail: 'plan_ev_charge_joint', until: T(1, 0, 1) },
        { kind: 'ev_charge_start', when: T(1, 30, 1), detail: 'plan_ev_charge_late', until: T(2, 0, 1) },
        { kind: 'ev_min_reached', when: T(2, 0, 1) },
    ], { now: NOW, end: END });
    assert.equal(at(segs, T(0, 30, 1)), 'charging');
    assert.equal(at(segs, T(1, 15, 1)), 'wait', 'the old walk painted charging here');
    assert.equal(at(segs, T(1, 45, 1)), 'late');
    assert.equal(at(segs, T(2, 1, 1)), 'done');
});

test('a top-up touching the rest is still drawn as its own state', () => {
    const segs = evStripSegments([
        { kind: 'ev_charge_start', when: T(0, 0, 1), detail: 'plan_ev_charge_joint', until: T(1, 30, 1) },
        { kind: 'ev_charge_start', when: T(1, 30, 1), detail: 'plan_ev_charge_late', until: T(2, 0, 1) },
        { kind: 'ev_min_reached', when: T(2, 0, 1) },
    ], { now: NOW, end: END });
    assert.ok(!states(segs).includes('wait'), 'touching windows leave no gap');
    assert.equal(at(segs, T(1, 29, 1)), 'charging');
    assert.equal(at(segs, T(1, 31, 1)), 'late');
});

test('a window ending at the horizon edge or beyond it is clamped, not extended', () => {
    const segs = evStripSegments([
        { kind: 'ev_charge_start', when: T(1, 0, 1), detail: 'plan_ev_charge_joint', until: T(4, 0, 1) },
    ], { now: NOW, end: END });
    assert.equal(segs.at(-1).e, END);
    assert.equal(segs.at(-1).state, 'charging');
});

test('rows without until keep the old walk', () => {
    const segs = evStripSegments([
        { kind: 'ev_charge_start', when: T(22, 0), detail: 'plan_ev_charge_joint' },
        { kind: 'ev_charge_start', when: T(0, 0, 1), detail: 'plan_ev_charge_joint' },
        { kind: 'ev_min_reached', when: T(1, 0, 1) },
    ], { now: NOW, end: END });
    assert.deepEqual(states(segs), ['idle', 'charging', 'charging', 'done']);
});

test('an until before its own start, or unparsable, is ignored', () => {
    for (const until of [T(21, 0), 'soon']) {
        const segs = evStripSegments([
            { kind: 'ev_charge_start', when: T(22, 0), detail: 'plan_ev_charge_joint', until },
            { kind: 'ev_min_reached', when: T(1, 0, 1) },
        ], { now: NOW, end: END });
        assert.equal(at(segs, T(23, 0)), 'charging', String(until));
    }
});

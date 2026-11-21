/**
 * (#1321) The one-night override span: from now to the end of the plan.
 * (#1406) The end comes from `ends_at`, which the sensor always sends; the
 * slots are dropped when the plan is too big, and a 12-hour guess took over.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { minutesToPlanEnd, planEndMs } from '../src/util/next-strip.js';

test('minutesToPlanEnd: to the last slot, 1..1440, a fallback without slots', () => {
    const now = new Date('2026-11-08T22:00:00+01:00');
    const plan = { slots: [{ start: '2026-11-08T22:00:00+01:00', end: '2026-11-09T07:00:00+01:00' }] };
    assert.equal(minutesToPlanEnd(plan, now), 540);
    assert.equal(minutesToPlanEnd({ slots: [] }, now), 720);
    assert.equal(minutesToPlanEnd({}, now, 60), 60);
    assert.equal(minutesToPlanEnd({ slots: [{ end: '2026-11-08T21:00:00+01:00' }] }, now), 720);
});

test('(#1406) the report: a skip at 09:23 on a plan with its slots dropped lasts until tomorrow 07:00', () => {
    const now = new Date('2026-11-21T09:23:00+01:00');
    const plan = { timeline_omitted: true, slots: [], ends_at: '2026-11-22T07:00:00+01:00' };
    assert.equal(minutesToPlanEnd(plan, now), 21 * 60 + 37);
    assert.notEqual(minutesToPlanEnd(plan, now), 720, 'the 12-hour guess ended the skip at 21:23');
});

test('(#1406) ends_at wins over the slots; a bad ends_at falls back to the slots', () => {
    const now = new Date('2026-11-08T22:00:00+01:00');
    const slots = [{ start: '2026-11-08T22:00:00+01:00', end: '2026-11-09T06:00:00+01:00' }];
    assert.equal(minutesToPlanEnd({ slots, ends_at: '2026-11-09T07:00:00+01:00' }, now), 540);
    for (const bad of [null, undefined, '', 'not a time', 12345])
        assert.equal(minutesToPlanEnd({ slots, ends_at: bad }, now), 480, String(bad));
});

test('(#1406) an end that has passed, or none at all, keeps the fallback', () => {
    const now = new Date('2026-11-21T09:23:00+01:00');
    assert.equal(minutesToPlanEnd({ slots: [], ends_at: '2026-11-21T07:00:00+01:00' }, now), 720);
    assert.equal(minutesToPlanEnd({ slots: [], ends_at: null }, now), 720);
    assert.equal(minutesToPlanEnd(null, now), 720);
    assert.equal(minutesToPlanEnd(undefined, now, 90), 90);
});

test('(#1406) an end more than a day ahead is held to 1440 minutes, one just ahead to 1', () => {
    const now = new Date('2026-11-21T09:00:00+01:00');
    assert.equal(minutesToPlanEnd({ ends_at: '2026-11-23T09:00:00+01:00' }, now), 1440);
    assert.equal(minutesToPlanEnd({ ends_at: '2026-11-21T09:00:10+01:00' }, now), 1);
});

test('(#1406) planEndMs: ends_at, else the last slot, else NaN', () => {
    assert.equal(planEndMs({ ends_at: '2026-11-22T07:00:00+01:00', slots: [] }), Date.parse('2026-11-22T07:00:00+01:00'));
    assert.equal(planEndMs({ slots: [{ end: '2026-11-22T06:00:00+01:00' }] }), Date.parse('2026-11-22T06:00:00+01:00'));
    assert.ok(Number.isNaN(planEndMs({ slots: [] })));
    assert.ok(Number.isNaN(planEndMs({ slots: [null] })));
    assert.ok(Number.isNaN(planEndMs(null)));
});

function files(dir) {
    return readdirSync(dir).flatMap((n) => {
        const p = join(dir, n);
        return statSync(p).isDirectory() ? files(p) : (p.endsWith('.js') ? [p] : []);
    });
}

test('(#1406) no card reads the plan end from its last slot: only planEndMs does', () => {
    const src = new URL('../src', import.meta.url).pathname;
    const found = [];
    for (const f of files(src)) {
        const rel = relative(src, f);
        if (rel === join('util', 'next-strip.js')) continue;
        const text = readFileSync(f, 'utf8');
        if (/slots\s*\[\s*[\w.]*slots\.length\s*-\s*1\s*\]|slots\.at\(\s*-1\s*\)/.test(text)) found.push(rel);
    }
    assert.deepEqual(found, [], 'read the plan end through planEndMs: the sensor can drop the slots');
    // the scan finds the shape it looks for (vacuity twin)
    assert.match('const e = plan.slots[plan.slots.length - 1].end', /slots\s*\[\s*[\w.]*slots\.length\s*-\s*1\s*\]/);
    assert.match('slots[slots.length - 1]', /slots\s*\[\s*[\w.]*slots\.length\s*-\s*1\s*\]/);
});

/**
 * (#1321) The one-night override span: from now to the end of the plan.
 * (#1406) The end comes from `ends_at`, which the sensor always sends; the
 * slots are dropped when the plan is too big, and a 12-hour guess took over.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { minutesToPlanEnd, nightEndMs, planEndMs } from '../src/util/next-strip.js';

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

const ZH = 'Europe/Zurich';

test('(#1406) nightEndMs: the next HH:MM after now in the home zone, the planner rule', () => {
    const at = (iso) => Date.parse(iso);
    assert.equal(nightEndMs('07:00', at('2026-11-21T09:23:00+01:00'), ZH), at('2026-11-22T07:00:00+01:00'));
    assert.equal(nightEndMs('07:00', at('2026-11-21T06:00:00+01:00'), ZH), at('2026-11-21T07:00:00+01:00'));
    // exactly at the time: the next one, as resolve_deadline (candidate <= now rolls a day)
    assert.equal(nightEndMs('07:00', at('2026-11-21T07:00:00+01:00'), ZH), at('2026-11-22T07:00:00+01:00'));
    assert.equal(nightEndMs('06:45:00', at('2026-11-21T23:00:00+01:00'), ZH), at('2026-11-22T06:45:00+01:00'));
    // the home's zone, not the browser's: the same instant in New York
    assert.equal(nightEndMs('07:00', at('2026-11-21T09:23:00+01:00'), 'America/New_York'), at('2026-11-21T07:00:00-05:00'));
});

test('(#1406) nightEndMs across both clock changes is the wall time', () => {
    const at = (iso) => Date.parse(iso);
    // autumn: 25.10.2026, 03:00 summer time becomes 02:00
    assert.equal(nightEndMs('07:00', at('2026-10-24T22:00:00+02:00'), ZH), at('2026-10-25T07:00:00+01:00'));
    // spring: 29.03.2026, 02:00 becomes 03:00 summer time
    assert.equal(nightEndMs('07:00', at('2026-03-28T22:00:00+01:00'), ZH), at('2026-03-29T07:00:00+02:00'));
});

test('(#1406) nightEndMs: a state that is not a time gives NaN', () => {
    const now = Date.parse('2026-11-21T09:23:00+01:00');
    for (const bad of ['', 'unavailable', 'unknown', null, undefined, '25:00', '07:61', '7', 'x7:00'])
        assert.ok(Number.isNaN(nightEndMs(bad, now, ZH)), String(bad));
    assert.ok(Number.isNaN(nightEndMs('07:00', NaN, ZH)));
});

test('(#1406) with no plan end ahead the override lasts until the next night end, not 12 hours', () => {
    const now = new Date('2026-11-21T07:20:00+01:00');
    const night = { end: '07:00', tz: ZH };
    // last night's plan, not yet replaced
    assert.equal(minutesToPlanEnd({ ends_at: '2026-11-21T07:00:00+01:00', slots: [] }, now, 720, night), 23 * 60 + 40);
    // no plan at all (just after a restart)
    assert.equal(minutesToPlanEnd(null, now, 720, night), 23 * 60 + 40);
    assert.equal(minutesToPlanEnd({}, now, 720, night), 23 * 60 + 40);
    // a plan end ahead wins over the night end
    assert.equal(minutesToPlanEnd({ ends_at: '2026-11-22T06:30:00+01:00' }, now, 720, night), 23 * 60 + 10);
    // night end not known: the old fallback
    assert.equal(minutesToPlanEnd(null, now, 720, { end: 'unavailable', tz: ZH }), 720);
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

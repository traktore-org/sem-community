/** (#1321) Clock times follow the home's time zone, not the browser's. */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { hhmmIn } from '../src/util/next-time.js';

test('a UTC instant shows the home clock', () => {
    const t = Date.parse('2026-11-08T19:01:00Z');
    assert.equal(hhmmIn(t, 'Europe/Zurich'), '20:01');
    assert.equal(hhmmIn(t, 'UTC'), '19:01');
    assert.equal(hhmmIn(new Date('2026-07-01T05:05:00Z'), 'Europe/Zurich'), '07:05');
});

test('midnight is 00, never 24; unknown zone falls back; bad date is empty', () => {
    assert.equal(hhmmIn(Date.parse('2026-11-08T23:00:00Z'), 'Europe/Zurich'), '00:00');
    assert.match(hhmmIn(Date.now(), 'Not/AZone'), /^\d{2}:\d{2}$/);
    assert.equal(hhmmIn('nonsense', 'UTC'), '');
});

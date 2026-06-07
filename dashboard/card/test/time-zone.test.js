/**
 * Regression tests for the #450 chart timezone fix.
 *
 * ``startOfDayInHaTz(now, haTz)`` must return a Date pointing at the
 * SAME absolute moment as midnight-in-haTz on the day that contains
 * ``now`` in haTz. The fallback to browser-local midnight when haTz
 * is missing or malformed is intentional — never break the chart.
 *
 * Run: `npm test` (from dashboard/card). No browser/jsdom needed.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { startOfDayInHaTz } from '../src/util/time-zone.js';


// Helper: format a Date in a given timezone and assert the wall-clock is
// midnight on the expected y/m/d. This is the load-bearing assertion —
// the Date object's UTC representation differs between TZs but the
// wall-clock in haTz should always be 00:00 on the expected day.
function assertIsMidnightInTz(date, tz, expectedYear, expectedMonth, expectedDay) {
    const fmt = new Intl.DateTimeFormat('en-US', {
        timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit',
        // hourCycle:'h23' returns "00" for midnight; ``hour12:false`` quirk
        // returns "24" in some Node/ICU versions which broke the original
        // ``Number(parts.hour) === 0`` check.
        hourCycle: 'h23',
    });
    const parts = Object.fromEntries(
        fmt.formatToParts(date).map(p => [p.type, p.value])
    );
    const hour = Number(parts.hour);
    assert.ok(hour === 0 || hour === 24,
        `expected midnight in ${tz}, got ${parts.hour}:${parts.minute} on ${parts.year}-${parts.month}-${parts.day}`);
    assert.equal(Number(parts.minute), 0);
    assert.equal(Number(parts.year), expectedYear);
    assert.equal(Number(parts.month), expectedMonth);
    assert.equal(Number(parts.day), expectedDay);
}


// ── Fallback paths ──

test('startOfDayInHaTz: missing timezone falls back to browser-local midnight', () => {
    const now = new Date(2026, 5, 7, 14, 30, 0); // 2026-06-07 14:30 browser-local
    const result = startOfDayInHaTz(now, undefined);
    // Browser local midnight on the same day
    assert.equal(result.getFullYear(), 2026);
    assert.equal(result.getMonth(), 5);  // June
    assert.equal(result.getDate(), 7);
    assert.equal(result.getHours(), 0);
    assert.equal(result.getMinutes(), 0);
});

test('startOfDayInHaTz: empty string timezone falls back to browser-local', () => {
    const now = new Date(2026, 5, 7, 14, 30, 0);
    const result = startOfDayInHaTz(now, '');
    assert.equal(result.getHours(), 0);
    assert.equal(result.getDate(), 7);
});

test('startOfDayInHaTz: malformed timezone falls back gracefully (no throw)', () => {
    const now = new Date(2026, 5, 7, 14, 30, 0);
    const result = startOfDayInHaTz(now, 'Definitely/Not/A/Timezone');
    // The Intl.DateTimeFormat constructor throws for unknown TZ; we
    // catch and fall back to browser-local midnight.
    assert.equal(result.getHours(), 0);
    assert.equal(result.getDate(), 7);
});


// ── Real timezone cases ──
// These tests pin the core invariant: the returned Date is midnight in
// the requested TZ, regardless of where the test process is running.

test('startOfDayInHaTz: returns midnight in Europe/Berlin', () => {
    // Pick a moment squarely inside a Berlin day to avoid edge cases.
    // 2026-06-07 12:00 UTC = 2026-06-07 14:00 CEST (Berlin in summer).
    const now = new Date(Date.UTC(2026, 5, 7, 12, 0, 0));
    const result = startOfDayInHaTz(now, 'Europe/Berlin');
    assertIsMidnightInTz(result, 'Europe/Berlin', 2026, 6, 7);
});

test('startOfDayInHaTz: returns midnight in UTC', () => {
    const now = new Date(Date.UTC(2026, 5, 7, 12, 0, 0));
    const result = startOfDayInHaTz(now, 'UTC');
    assertIsMidnightInTz(result, 'UTC', 2026, 6, 7);
});

test('startOfDayInHaTz: returns midnight in America/Los_Angeles', () => {
    // 2026-06-07 12:00 UTC = 2026-06-07 05:00 PDT — still on 2026-06-07 in LA.
    const now = new Date(Date.UTC(2026, 5, 7, 12, 0, 0));
    const result = startOfDayInHaTz(now, 'America/Los_Angeles');
    assertIsMidnightInTz(result, 'America/Los_Angeles', 2026, 6, 7);
});

test('startOfDayInHaTz: returns midnight in Asia/Tokyo', () => {
    // Tokyo is UTC+9. 2026-06-07 12:00 UTC = 2026-06-07 21:00 JST.
    const now = new Date(Date.UTC(2026, 5, 7, 12, 0, 0));
    const result = startOfDayInHaTz(now, 'Asia/Tokyo');
    assertIsMidnightInTz(result, 'Asia/Tokyo', 2026, 6, 7);
});


// ── Cross-midnight cases ──
// The day boundary in haTz may not match the day boundary in UTC.

test('startOfDayInHaTz: late-night UTC that is next-day in Tokyo returns Tokyo midnight', () => {
    // 2026-06-07 22:00 UTC = 2026-06-08 07:00 JST. The "today" in Tokyo
    // is 2026-06-08, so midnight is 2026-06-07 15:00 UTC.
    const now = new Date(Date.UTC(2026, 5, 7, 22, 0, 0));
    const result = startOfDayInHaTz(now, 'Asia/Tokyo');
    assertIsMidnightInTz(result, 'Asia/Tokyo', 2026, 6, 8);
});

test('startOfDayInHaTz: early-morning UTC that is previous-day in Los_Angeles returns LA midnight', () => {
    // 2026-06-08 02:00 UTC = 2026-06-07 19:00 PDT. The "today" in LA
    // is 2026-06-07, so midnight is 2026-06-07 07:00 UTC.
    const now = new Date(Date.UTC(2026, 5, 8, 2, 0, 0));
    const result = startOfDayInHaTz(now, 'America/Los_Angeles');
    assertIsMidnightInTz(result, 'America/Los_Angeles', 2026, 6, 7);
});


// ── DST boundary case — the original PROD symptom class ──

test('startOfDayInHaTz: handles a Europe/Berlin day during CEST (UTC+2) correctly', () => {
    // Summer 2026: Berlin observes CEST (UTC+2). A naive
    // ``new Date(year, month, date)`` in a UTC-running browser would
    // produce UTC midnight, which is 02:00 in Berlin (wrong day boundary).
    // startOfDayInHaTz must produce 22:00 UTC the previous day = midnight CEST.
    const now = new Date(Date.UTC(2026, 6, 15, 10, 0, 0));  // 2026-07-15 10:00 UTC
    const result = startOfDayInHaTz(now, 'Europe/Berlin');
    // Berlin sees 2026-07-15 at this moment (12:00 CEST). Midnight CEST
    // on 2026-07-15 = 2026-07-14 22:00 UTC.
    assert.equal(result.toISOString(), '2026-07-14T22:00:00.000Z');
});


// ── Regression: original PROD symptom ──

test('startOfDayInHaTz: a "today" query in CEST returns Berlin midnight, not browser UTC midnight (#450)', () => {
    // The user-reported symptom: chart x-axis shifted ~1h.
    // Scenario: browser in UTC, HA server in Europe/Berlin (CEST = UTC+2).
    // Pre-#450: ``new Date(year, month, date)`` in UTC browser would
    // return a Date at 00:00 UTC = 02:00 CEST — query starts 2h into
    // the haTz day, dropping the first 2 hours of chart data.
    // Post-#450: query starts at 22:00-previous-day UTC = 00:00 CEST.
    const now = new Date(Date.UTC(2026, 5, 7, 12, 0, 0));
    const result = startOfDayInHaTz(now, 'Europe/Berlin');
    assertIsMidnightInTz(result, 'Europe/Berlin', 2026, 6, 7);
    // And confirm the offset from a naive browser-UTC midnight:
    const naiveUtc = new Date(Date.UTC(2026, 5, 7, 0, 0, 0));
    const delta_h = (naiveUtc.getTime() - result.getTime()) / (60 * 60 * 1000);
    // Berlin in summer is UTC+2 → midnight CEST is 2h before midnight UTC.
    assert.equal(delta_h, 2, `expected 2h offset between UTC and Berlin midnight, got ${delta_h}h`);
});

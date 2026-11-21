/**
 * (#1321) The Plan screen's one-night override span. The old strip drawing
 * moved to next-plan-chart.js (sun, price and plan on one clock).
 */

import { zoneOffsetMin } from './next-plan-chart.js';

/**
 * (#1406) When the plan ends, in ms; NaN when it does not say. `ends_at` first:
 * the sensor always sends it, while it drops the slots when the plan is too
 * big (`timeline_omitted`). The last slot is for a sensor from before #1406.
 * The only place a card reads the plan's end.
 */
export function planEndMs(plan) {
    const own = typeof plan?.ends_at === 'string' ? Date.parse(plan.ends_at) : NaN;
    if (Number.isFinite(own)) return own;
    const slots = Array.isArray(plan?.slots) ? plan.slots : [];
    return slots.length ? Date.parse(slots[slots.length - 1]?.end) : NaN;
}

/**
 * (#1406) The next `hhmm` after `nowMs` in the home's zone, in ms; NaN when
 * `hhmm` is not a time. A plan made now ends at the next night end, so this
 * is the plan's end when no plan stands yet (the planner's resolve_deadline).
 */
export function nightEndMs(hhmm, nowMs, tz) {
    const m = /^(\d{1,2}):(\d{2})(?::\d{2})?$/.exec(String(hhmm ?? '').trim());
    if (!m || Number(m[1]) > 23 || Number(m[2]) > 59 || !Number.isFinite(nowMs)) return NaN;
    const off = (ms) => zoneOffsetMin(ms, tz) * 60e3;
    const day = new Date(nowMs + off(nowMs));   // the home's date, read in UTC fields
    for (const days of [0, 1, 2]) {
        // the wall time as if it were UTC, then moved by the offset in force at it
        // (twice: the first guess can sit on the other side of a clock change)
        const wall = Date.UTC(day.getUTCFullYear(), day.getUTCMonth(), day.getUTCDate() + days, Number(m[1]), Number(m[2]));
        const at = wall - off(wall - off(wall));
        if (at > nowMs) return at;
    }
    return NaN;
}

/**
 * Minutes from `now` to the end of the plan, for a one-night override; 1..1440.
 * (#1406) With no plan end ahead, the next night end (`night` = { end: 'HH:MM', tz });
 * `fallback` only when neither is known.
 */
export function minutesToPlanEnd(plan, now, fallback = 720, night = null) {
    const nowMs = now instanceof Date ? now.getTime() : Number(now);
    let last = planEndMs(plan);
    if (!(last > nowMs) && night) last = nightEndMs(night.end, nowMs, night.tz);
    if (!Number.isFinite(last) || last <= nowMs) return fallback;
    return Math.max(1, Math.min(1440, Math.round((last - nowMs) / 60e3)));
}

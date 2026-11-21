/**
 * (#1321) The Plan screen's one-night override span. The old strip drawing
 * moved to next-plan-chart.js (sun, price and plan on one clock).
 */

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

/** Minutes from `now` to the end of the plan, for a one-night override; 1..1440, `fallback` when the plan has no end ahead. */
export function minutesToPlanEnd(plan, now, fallback = 720) {
    const last = planEndMs(plan);
    const nowMs = now instanceof Date ? now.getTime() : Number(now);
    if (!Number.isFinite(last) || last <= nowMs) return fallback;
    return Math.max(1, Math.min(1440, Math.round((last - nowMs) / 60e3)));
}

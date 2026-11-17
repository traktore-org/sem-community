/**
 * (#1321) The Plan screen's one-night override span. The old strip drawing
 * moved to next-plan-chart.js (sun, price and plan on one clock).
 */

/** Minutes from `now` to the end of the plan's slots, for a one-night override; 1..1440, `fallback` without slots. */
export function minutesToPlanEnd(plan, now, fallback = 720) {
    const slots = Array.isArray(plan?.slots) ? plan.slots : [];
    const last = slots.length ? Date.parse(slots[slots.length - 1].end) : NaN;
    const nowMs = now instanceof Date ? now.getTime() : Number(now);
    if (!Number.isFinite(last) || last <= nowMs) return fallback;
    return Math.max(1, Math.min(1440, Math.round((last - nowMs) / 60e3)));
}

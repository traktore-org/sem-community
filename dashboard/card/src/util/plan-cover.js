/**
 * #1063 — who covers the house in one plan slot (the Home row's colour).
 *
 * The card used to read "no home draw on the meter" as "the battery covers
 * the house". But a sun slot has no net draw either, and a home without a
 * battery has only the sun and the grid. So a battery-less home saw its
 * sunny hours in the battery colour, under a "battery covers home" legend.
 *
 *   grid — the meter carries the house (more than GRID_EPS_W);
 *   batt — the plan drew the battery for the house (`batt` true);
 *   sun  — nothing on the meter and no battery drawn.
 *
 * The battery colour needs the plan's own word for it, never a guess from
 * the other two: a battery the plan did not use is not drawn. `batt` is
 * undefined only for a plan stamped before #1063 (no `batt_runs` on the
 * entity): that one keeps the old rule until the next stamp, so a battery
 * home does not see its night drawn as sun right after the update.
 */

// Below this the slot's home draw is not on the meter. The backend rounds
// home_grid_w to 1 decimal, so anything under a watt is noise.
export const GRID_EPS_W = 1.0;

export function homeCover(slot, batt) {
    if (((slot && slot.home_grid_w) || 0) > GRID_EPS_W) return 'grid';
    if (batt === undefined) return 'batt';
    return batt ? 'batt' : 'sun';
}

// The slot indexes inside the entity's `batt_runs` ([[first, last], ...]),
// or null when the entity has none (a plan stamped before #1063).
export function battIndexes(runs) {
    if (!Array.isArray(runs)) return null;
    const out = new Set();
    for (const r of runs) {
        if (!Array.isArray(r)) continue;
        const a = Number(r[0]);
        const b = Number(r[1]);
        if (!Number.isInteger(a) || !Number.isInteger(b)) continue;
        for (let i = a; i <= b; i++) out.add(i);
    }
    return out;
}

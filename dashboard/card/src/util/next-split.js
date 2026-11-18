/**
 * (#1321) Parts that add up. One rounding for a split of a total, used wherever
 * a screen shows a total beside its parts (house by source, planned kWh by
 * source): the parts are scaled to the total and rounded so the shown numbers
 * add up to the shown total.
 */

/**
 * fitParts(parts, total, decimals = 1) → numbers, same order.
 * Negative and missing parts count as 0. Without a positive total the parts
 * are only rounded. A total with no parts under it gives all zeros.
 */
export function fitParts(parts, total, decimals = 1) {
    const f = 10 ** decimals;
    const raw = (parts || []).map((p) => (Number.isFinite(Number(p)) && Number(p) > 0 ? Number(p) : 0));
    const sum = raw.reduce((a, v) => a + v, 0);
    const t = Number(total);
    if (!(sum > 0) || !Number.isFinite(t) || t < 0) return raw.map((v) => Math.round(v * f) / f);
    const scaled = raw.map((v) => v * t / sum * f);
    const floors = scaled.map(Math.floor);
    let left = Math.round(t * f) - floors.reduce((a, v) => a + v, 0);
    const order = scaled.map((v, i) => [v - floors[i], i]).sort((a, b) => b[0] - a[0]);
    for (const [, i] of order) { if (left <= 0) break; floors[i] += 1; left -= 1; }
    return floors.map((v) => v / f);
}

/**
 * (#1081) The "Heat cost per hour" table under a device's plan row. Read
 * only: the plan sensor publishes heat_cost = {device_id: rows}, each row
 * [start, price, cop, heat_price, cheap (0|1), chosen reason | null]. Nothing
 * decides from it.
 */

const REASONS = ['cheapest_heat', 'comfort_goal', 'preheat', 'load'];

const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null);

/** The device a plan demand belongs to: "load:x" / "comfort:x" → "x". */
export function deviceOfDemand(demandId) {
    const m = /^(?:load|comfort):(.+)$/.exec(String(demandId || ''));
    return m ? m[1] : null;
}

/** Rows for a demand, ready to draw, or null when there is no table.
 *  hm formats an ISO start; t maps a key to its text. */
export function heatCostRows(heatCost, demandId, hm, t) {
    const dev = deviceOfDemand(demandId);
    const raw = heatCost && dev ? heatCost[dev] : null;
    if (!Array.isArray(raw) || !raw.length) return null;
    const rows = [];
    for (const r of raw) {
        if (!Array.isArray(r) || r.length < 6) continue;
        const why = REASONS.includes(r[5]) ? t('energy_plan_hc_' + r[5]) : '';
        rows.push({
            time: hm(r[0]),
            price: num(r[1]),
            cop: num(r[2]),
            heat: num(r[3]),
            cheap: r[4] === 1,
            chosen: r[5] != null && REASONS.includes(r[5]),
            why,
        });
    }
    return rows.length ? rows : null;
}

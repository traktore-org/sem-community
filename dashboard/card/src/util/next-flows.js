/**
 * (#1321) Bars for "Where the energy went".
 *
 * One scale for every row: the biggest sink fills the width, the others are
 * drawn in proportion, so 0.2 kWh never looks like 1.9 kWh. Inside a bar the
 * segments split by source (sun, battery, grid) in their own colours.
 *
 * rows: [{ sink, total, parts: [[src, kWh]] }] → the same rows plus
 * `widthPct` (of the track) and `segs: [{ src, kwh, flex }]`.
 */
export function flowBars(rows) {
    const list = Array.isArray(rows) ? rows : [];
    // a flow that reads 0.0 kWh draws nothing: no sliver beside a zero (#1321)
    const shown = (v) => (v >= 0.05 ? v : 0);
    const max = list.reduce((m, r) => Math.max(m, shown(r.total)), 0);
    return list.map((r) => {
        const total = shown(r.total);
        // a tiny but real flow keeps a visible sliver
        const widthPct = max > 0 && total > 0 ? Math.max(2, Math.round(total / max * 1000) / 10) : 0;
        const segs = total > 0
            ? r.parts.map(([src, v]) => ({ src, kwh: Math.max(0, v), flex: Math.max(0, v) / total })).filter((s) => s.flex > 0)
            : [];
        return { ...r, widthPct, segs };
    });
}

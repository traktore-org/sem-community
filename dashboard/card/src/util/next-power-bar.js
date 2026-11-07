/**
 * (#1321) The Power-now bar's model: what feeds the house right now and
 * where it goes, from the five SEM power readings.
 *
 * SEM signs: grid negative = import, battery negative = discharge. A null
 * reading is a missing entity and leaves its segment out; a zero reading
 * leaves it out too (the bar shows what flows, the list shows the rest).
 *
 * powerBar({ solarW, gridW, batteryW, homeW, evW })
 *   → { sources: [{ key, w, share, label }], sinks: [...], total, inW, outW }
 *
 * share = the segment's part of its own lane; label = share ≥ LABEL_SHARE,
 * under which a segment is too thin to carry a number. total is the
 * sources' sum, or the sinks' sum when no source reads (solar at night
 * with the grid sensor out).
 */
export const LABEL_SHARE = 0.2;

export const SOURCE_KEYS = ['solar', 'battery_out', 'grid_in'];
export const SINK_KEYS = ['home', 'ev', 'battery_in', 'grid_out'];

function num(v) {
    if (v === null || v === undefined || v === '') return NaN;
    return typeof v === 'number' ? v : parseFloat(v);
}
function pos(v) { return Number.isFinite(v) && v > 0 ? v : 0; }
function neg(v) { return Number.isFinite(v) && v < 0 ? -v : 0; }

function lane(items) {
    const kept = items.filter((it) => it.w > 0);
    const sum = kept.reduce((a, it) => a + it.w, 0);
    return kept.map((it) => {
        const share = sum > 0 ? it.w / sum : 0;
        return { key: it.key, w: it.w, share, label: share >= LABEL_SHARE };
    });
}

export function powerBar(r = {}) {
    const solar = num(r.solarW), grid = num(r.gridW), batt = num(r.batteryW);
    const home = num(r.homeW), ev = num(r.evW);
    const sources = lane([
        { key: 'solar', w: pos(solar) },
        { key: 'battery_out', w: neg(batt) },
        { key: 'grid_in', w: neg(grid) },
    ]);
    const sinks = lane([
        { key: 'home', w: pos(home) },
        { key: 'ev', w: pos(ev) },
        { key: 'battery_in', w: pos(batt) },
        { key: 'grid_out', w: pos(grid) },
    ]);
    const inW = sources.reduce((a, s) => a + s.w, 0);
    const outW = sinks.reduce((a, s) => a + s.w, 0);
    return { sources, sinks, total: inW > 0 ? inW : outW, inW, outW };
}

/**
 * (#1321) The Plan screen's timeline, as geometry.
 *
 * Pure: the plan sensor's attributes and a few clock facts in, lanes with
 * blocks as fractions of the axis out. The card only draws.
 *
 * Axis: from now to now + hours. Everything is clipped to it. A block that
 * does not fit the axis at all is dropped, never squeezed.
 */

export const LANE_COLORS = {
    sun: '#ff9800', price: '#8353d1', grid: '#488fc2',
    battery_in: '#f06292', battery_out: '#4db6ac', ev: '#8DC892', load: '#5BC8D8',
};

const HOUR_MS = 3600e3;

/** 'HH:MM' on the day of `ref` (a Date), the next day when it is already past. */
export function nextClock(hhmm, ref) {
    const m = /^(\d{1,2}):(\d{2})/.exec(String(hhmm || ''));
    if (!m) return null;
    const d = new Date(ref.getTime());
    d.setHours(Number(m[1]), Number(m[2]), 0, 0);
    if (d.getTime() <= ref.getTime()) d.setDate(d.getDate() + 1);
    return d;
}

function frac(ms, start, span) {
    return Math.min(1, Math.max(0, (ms - start) / span));
}

/**
 * laneModel({ now: Date, plan: attributes, chargers: [{id, name}],
 *             loads: [{id, name}], nightStart: 'HH:MM', nightEnd: 'HH:MM',
 *             forecastTomorrowKwh, forecastTodayKwh, hours })
 */
export function laneModel(o) {
    const now = o.now instanceof Date ? o.now : new Date(o.now || Date.now());
    const hours = o.hours || 24;
    const start = now.getTime();
    const span = hours * HOUR_MS;
    const end = start + span;
    const a = o.plan && typeof o.plan === 'object' ? o.plan : {};
    const clip = (s, e) => {
        const cs = Math.max(s, start), ce = Math.min(e, end);
        return ce > cs ? [frac(cs, start, span), frac(ce, start, span)] : null;
    };

    // Hour ticks on whole hours, every 3 h.
    const ticks = [];
    const first = new Date(start); first.setMinutes(0, 0, 0);
    for (let t = first.getTime() + HOUR_MS; t <= end; t += HOUR_MS) {
        const d = new Date(t);
        if (d.getHours() % 3 === 0) ticks.push({ x: frac(t, start, span), label: String(d.getHours()).padStart(2, '0') + ':00' });
    }

    // Sun: the next daylight span from the night window (end = sunrise or
    // the morning cap, start = sunset + the user's offset).
    let sun = null;
    const sunUp = nextClock(o.nightEnd, now);
    const sunDown = nextClock(o.nightStart, now);
    if (sunUp && sunDown) {
        let up = sunUp.getTime(), down = sunDown.getTime();
        if (down < up) up = start;          // daylight now: the sun is up until nightStart
        const f = clip(up, down);
        if (f) sun = { x0: f[0], x1: f[1], kwh: down < sunUp.getTime() ? o.forecastTodayKwh : o.forecastTomorrowKwh };
    }

    // Price: only when the slots carry more than one price.
    let price = null;
    const slots = Array.isArray(a.slots) ? a.slots : [];
    const prices = slots.map(s => s.price).filter(p => Number.isFinite(Number(p)));
    if (prices.length && new Set(prices.map(p => Number(p).toFixed(4))).size > 1) {
        price = [];
        for (const s of slots) {
            const f = clip(Date.parse(s.start), Date.parse(s.end));
            if (f && Number.isFinite(Number(s.price))) price.push({ x0: f[0], x1: f[1], price: Number(s.price), cheap: !!s.cheap });
        }
    }

    const lanes = [];
    // Grid: the house on the meter from the takeover to the end of the night.
    const grid = { id: 'grid', labelKey: 'next_lane_grid', color: LANE_COLORS.grid, blocks: [] };
    const takeover = a.takeover ? Date.parse(a.takeover) : NaN;
    if (Number.isFinite(takeover) && sunUp) {
        const f = clip(takeover, sunUp.getTime());
        if (f) grid.blocks.push({ x0: f[0], x1: f[1], kind: 'grid', dashed: true, reasonKey: 'next_reason_takeover', params: {} });
    }
    lanes.push(grid);

    // Battery: planned pre-charge blocks and the plan's battery runs.
    const bat = { id: 'battery', labelKey: 'next_lane_battery', color: LANE_COLORS.battery_out, blocks: [] };
    for (const b of (Array.isArray(a.blocks) ? a.blocks : [])) {
        if (!String(b.id).startsWith('battery')) continue;
        const f = clip(Date.parse(b.start), Date.parse(b.end));
        if (f) bat.blocks.push({ x0: f[0], x1: f[1], kind: 'battery_in', color: LANE_COLORS.battery_in, dashed: true,
            powerW: Number(b.power_w) || 0, reasonKey: 'next_reason_battery_charge', params: { kw: ((Number(b.power_w) || 0) / 1000).toFixed(1) } });
    }
    for (const r of (Array.isArray(a.batt_runs) ? a.batt_runs : [])) {
        const f = clip(Date.parse(r.start), Date.parse(r.end));
        if (f) bat.blocks.push({ x0: f[0], x1: f[1], kind: 'battery_out', color: LANE_COLORS.battery_out, dashed: true,
            reasonKey: 'next_reason_battery_house', params: {} });
    }
    lanes.push(bat);

    // One lane per charger and per load, blocks by demand id.
    const demands = Array.isArray(a.demands) ? a.demands : [];
    const noteOf = (id) => demands.find(d => d.id === id) || {};
    // A charger keeps its lane even when nothing is planned (the user looks
    // for the car); a load without a block is left out, and a load list
    // that also names the chargers or the battery does not list them twice.
    const chargerIds = new Set((o.chargers || []).map((c) => String(c.id)));
    const laneFor = (prefix, list, labelKey, color, keepEmpty) => {
        for (const it of (list || [])) {
            const itId = String(it.id);
            if (prefix === 'load' && (chargerIds.has(itId) || itId.startsWith('battery'))) continue;
            const lane = { id: `${prefix}:${it.id}`, labelKey, label: it.name || it.id, color, blocks: [] };
            for (const b of (Array.isArray(a.blocks) ? a.blocks : [])) {
                if (b.id !== lane.id) continue;
                const f = clip(Date.parse(b.start), Date.parse(b.end));
                if (!f) continue;
                const d = noteOf(b.id);
                lane.blocks.push({ x0: f[0], x1: f[1], kind: prefix, color, dashed: Date.parse(b.start) > start,
                    powerW: Number(b.power_w) || 0,
                    reasonKey: prefix === 'ev' ? 'next_reason_ev_block' : 'next_reason_load_block',
                    params: { kw: ((Number(b.power_w) || 0) / 1000).toFixed(1), status: d.status || '',
                        // (#1354) the planner's note in the user's words when the card passes a reader
                        note: (typeof o.noteText === 'function' ? o.noteText(d) : d.note) || '' } });
            }
            if (keepEmpty || lane.blocks.length) lanes.push(lane);
        }
    };
    laneFor('ev', o.chargers, 'next_lane_car', LANE_COLORS.ev, true);
    laneFor('load', o.loads, 'next_lane_load', LANE_COLORS.load, false);

    const notScheduled = Array.isArray(a.not_scheduled) ? a.not_scheduled : [];
    return { start, end, hours, ticks, sun, price, lanes, notScheduled, why: a.why || '', fits: a.fits, cost: a.total_cost, computedAt: a.computed_at || '' };
}

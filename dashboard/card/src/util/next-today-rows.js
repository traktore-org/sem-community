/**
 * (#1321) The Today list on the Now screen: the classic Today's Plan rows
 * from sensor.sem_charging_state attr today_plan, as the Next card draws
 * them. Pure: the attributes in, rows out. The row logic is the classic
 * sem-today-plan-card's; the kinds are the backend's (coordinator/today_plan.py).
 *
 * A row: { kind, when (ms), iso, icon, color, label, detail, values, until,
 *          day, late }
 *   label / detail are translation keys the card fills with `values`;
 *   color is a NEXT_COLORS name; day is 0 today, 1 tomorrow, 2 later;
 *   late marks the Min-reached row when it lands after the charge-by
 *   deadline (the card paints it red) and a car is plugged in.
 * The "now" anchor row is dropped: the lead line already says now.
 */
export const KINDS = {
    solar_peak:       { icon: 'mdi:weather-sunny',           color: 'solar' },
    solar_end:        { icon: 'mdi:weather-sunset',          color: 'solar' },
    cheap_start:      { icon: 'mdi:arrow-down-bold',         color: 'ev' },
    cheap_end:        { icon: 'mdi:arrow-up-bold',           color: 'solar' },
    expensive_start:  { icon: 'mdi:trending-up',             color: 'battery_in' },
    expensive_end:    { icon: 'mdi:trending-down',           color: 'ev' },
    night_open:       { icon: 'mdi:weather-night',           color: 'export' },
    night_end:        { icon: 'mdi:weather-sunset-up',       color: 'solar' },
    ev_charge_start:  { icon: 'mdi:ev-station',              color: 'ev' },
    ev_min_reached:   { icon: 'mdi:battery-charging-80',     color: 'battery_out' },
    ev_target_reached: { icon: 'mdi:car-electric',           color: 'ev' },
    ev_deadline:      { icon: 'mdi:flag',                    color: 'battery_in' },
    ev_wait:          { icon: 'mdi:pause-circle',            color: 'export' },
    battery_full:     { icon: 'mdi:battery-charging-100',    color: 'battery_in' },
    battery_empty:    { icon: 'mdi:battery-low',             color: 'battery_out' },
    device_run:       { icon: 'mdi:power-plug',              color: 'home' },
    device_done:      { icon: 'mdi:check-circle',            color: 'ev' },
    export_closed:    { icon: 'mdi:transmission-tower-off',  color: 'battery_in' },
    export_reopens:   { icon: 'mdi:transmission-tower',      color: 'export' },
};

/** 0 for today, 1 for tomorrow, 2 for anything later (local calendar days). */
export function dayIndex(whenMs, nowMs) {
    const a = new Date(whenMs), b = new Date(nowMs);
    const da = new Date(a.getFullYear(), a.getMonth(), a.getDate()).getTime();
    const db = new Date(b.getFullYear(), b.getMonth(), b.getDate()).getTime();
    const d = Math.round((da - db) / 86400000);
    return d <= 0 ? 0 : (d === 1 ? 1 : 2);
}

/** One row per plugged-in car that the plan has hours for: the plan's own window, not the strip's guess. */
function carPlanRows(plan, cars, now) {
    const out = [];
    for (const c of cars || []) {
        const bs = (plan && Array.isArray(plan.blocks) ? plan.blocks : [])
            .filter((b) => b && b.id === 'ev:' + c.cid && Date.parse(b.end) > now);
        if (!bs.length) continue;
        const s = Math.min(...bs.map((b) => Math.max(Date.parse(b.start), now))), e = Math.max(...bs.map((b) => Date.parse(b.end)));
        const kwh = bs.reduce((a, b) => a + (Number(b.power_w) || 0) * (Math.min(Date.parse(b.end), e) - Math.max(Date.parse(b.start), now)) / 3.6e9, 0);
        out.push({ kind: 'ev_charge_start', when: s, iso: new Date(s).toISOString(), icon: KINDS.ev_charge_start.icon, color: 'ev',
            label: 'next_car_charges', detail: null, values: { name: c.name, kwh: String(Math.round(kwh * 10) / 10) },
            until: new Date(e).toISOString(), day: dayIndex(s, now), late: false, planned: true });
    }
    return out;
}

/** A device row the plan has its own hours for takes them; a window that has ended is dropped. */
function alignDevices(rows, plan, now) {
    const demands = plan && Array.isArray(plan.demands) ? plan.demands : [];
    const out = [];
    for (const r of rows) {
        const d = r.kind === 'device_run' ? demands.find((x) => x && /^(load|comfort):/.test(String(x.id)) && x.label && x.label === r.values.name) : null;
        const bs = d ? (plan.blocks || []).filter((b) => b && b.id === d.id) : [];
        if (!bs.length) { out.push(r); continue; }
        const live = bs.filter((b) => Date.parse(b.end) > now);
        if (!live.length) continue;
        const s = Math.min(...live.map((b) => Math.max(Date.parse(b.start), now)));
        out.push({ ...r, when: s, iso: new Date(s).toISOString(), until: new Date(Math.max(...live.map((b) => Date.parse(b.end)))).toISOString(), day: dayIndex(s, now) });
    }
    return out;
}

/**
 * opts: now, carPresent, plan (the effective plan), cars [{cid, name}] plugged in.
 * The strip is the primary charger's guess: with no car it names no car; a car the plan
 * has hours for is named from the plan.
 */
export function todayRows(attrs, { now = Date.now(), carPresent = true, plan = null, cars = null } = {}) {
    const strip = attrs && Array.isArray(attrs.today_plan) ? attrs.today_plan : [];
    const rows = [];
    for (const r of strip) {
        if (!r || typeof r !== 'object' || r.kind === 'now') continue;
        const when = Date.parse(r.when);
        if (!Number.isFinite(when)) continue;
        const k = KINDS[r.kind] || KINDS.device_run;
        rows.push({
            kind: String(r.kind || ''), when, iso: String(r.when), icon: k.icon, color: k.color,
            label: String(r.label || ''), detail: r.detail ? String(r.detail) : null,
            values: r.values && typeof r.values === 'object' ? r.values : {},
            until: r.until || null, day: dayIndex(when, now), late: false,
        });
    }
    let list = [...rows];
    const guess = (r) => r.kind === 'ev_charge_start' && /estimate/.test(String(r.detail || ''));
    // a guess for a car that is not there is no plan
    if (!carPresent) list = list.filter((r) => !guess(r));
    if (plan) {
        const mine = carPlanRows(plan, cars, now);
        if (mine.length) list = list.filter((r) => !guess(r));
        list = alignDevices([...list, ...mine], plan, now);
    }
    list.sort((a, b) => a.when - b.when);
    const deadline = list.find((r) => r.kind === 'ev_deadline');
    // (#1321) red is for a real miss: with no car plugged in nothing can be late
    if (deadline && carPresent) {
        for (const r of list) if (r.kind === 'ev_min_reached' && r.when > deadline.when) r.late = true;
    }
    return list;
}

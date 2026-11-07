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
 *   deadline (the card paints it red).
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

export function todayRows(attrs, { now = Date.now() } = {}) {
    const plan = attrs && Array.isArray(attrs.today_plan) ? attrs.today_plan : [];
    const rows = [];
    for (const r of plan) {
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
    rows.sort((a, b) => a.when - b.when);
    const deadline = rows.find((r) => r.kind === 'ev_deadline');
    if (deadline) {
        for (const r of rows) if (r.kind === 'ev_min_reached' && r.when > deadline.when) r.late = true;
    }
    return rows;
}

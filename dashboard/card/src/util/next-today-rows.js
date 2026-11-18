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
import { planRunsRounded, isBatteryIn, batteryFullAt } from './plan-facts.js';
import { fmtNum } from './next-number.js';
import { nextClock } from './next-timeline.js';

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

/** One row per run of a plugged-in car that the plan has hours for: the plan's own hours, a gap stays a gap. */
function carPlanRows(plan, cars, now) {
    const out = [];
    for (const c of cars || []) {
        for (const r of planRunsRounded(plan, (id) => id === 'ev:' + c.cid, now)) {
            out.push({ kind: 'ev_charge_start', when: r.s, iso: new Date(r.s).toISOString(), icon: KINDS.ev_charge_start.icon, color: 'ev',
                label: 'next_car_charges', detail: null, values: { name: c.name, kwh: fmtNum(r.kwh, 1) },
                until: new Date(r.e).toISOString(), day: dayIndex(r.s, now), late: false, planned: true });
        }
    }
    return out;
}

/** A device row the plan has its own hours for takes them, one row per run; a window that has ended is dropped. A load whose demand has no hours is not listed; a load with no demand keeps its row. */
function alignDevices(rows, plan, now) {
    const demands = plan && Array.isArray(plan.demands) ? plan.demands : [];
    const out = [];
    for (const r of rows) {
        const d = r.kind === 'device_run' ? demands.find((x) => x && /^(load|comfort):/.test(String(x.id)) && x.label && x.label === r.values.name) : null;
        const has = d ? (plan.blocks || []).some((b) => b && b.id === d.id) : false;
        // (#1321) the plan is the one source for "expected to run" for a load it has a demand for:
        // no hours for that demand, no row. A load the plan has no demand for runs on its own schedule: its row stays.
        if (!has) { if (!(r.kind === 'device_run' && d)) out.push(r); continue; }
        for (const run of planRunsRounded(plan, (id) => id === d.id, now)) {
            out.push({ ...r, when: run.s, iso: new Date(run.s).toISOString(), until: new Date(run.e).toISOString(), day: dayIndex(run.s, now) });
        }
    }
    return out;
}

// The rows that speak for one charger's car: the fleet strip is the primary charger's guess (#1321).
const CAR_KINDS = new Set(['ev_min_reached', 'ev_target_reached', 'ev_deadline', 'ev_wait']);

/** One strip entry as a row, or null when it has no valid time. `who` names the charger. */
function stripRow(r, now, who = '') {
    if (!r || typeof r !== 'object' || r.kind === 'now') return null;
    const when = Date.parse(r.when);
    if (!Number.isFinite(when)) return null;
    const k = KINDS[r.kind] || KINDS.device_run;
    return {
        kind: String(r.kind || ''), when, iso: String(r.when), icon: k.icon, color: k.color,
        label: String(r.label || ''), detail: r.detail ? String(r.detail) : null,
        values: r.values && typeof r.values === 'object' ? r.values : {},
        until: r.until || null, day: dayIndex(when, now), late: false, who,
    };
}

/**
 * The car rows: each plugged-in charger's own list (attribute per_charger_plans), named when
 * there is more than one charger. A charger without a car has none: no Min, Target, Deadline
 * or Wait row is ever shown for a car that is not there. Null when the sensor has no such lists.
 */
function carRows(attrs, cars, multi, now) {
    const per = attrs && attrs.per_charger_plans;
    if (!per || typeof per !== 'object' || !Object.keys(per).length) return null;
    const out = [];
    for (const c of cars || []) {
        const list = Array.isArray(per[c.cid]) ? per[c.cid] : [];
        for (const r of list) {
            const row = r && CAR_KINDS.has(r.kind) ? stripRow(r, now, multi ? c.name : '') : null;
            if (row) out.push(row);
        }
    }
    return out;
}

/**
 * opts: now, carPresent, plan (the effective plan), cars [{cid, name}] plugged in, multi (more
 * than one charger: the car rows name theirs). The strip is the primary charger's guess: with no
 * car it names no car; a car the plan has hours for is named from the plan. The battery-full row
 * is the plan's own time, never the strip's estimate (the sun's guess moves by minutes).
 */
export function todayRows(attrs, { now = Date.now(), carPresent = true, plan = null, cars = null, multi = false } = {}) {
    const strip = attrs && Array.isArray(attrs.today_plan) ? attrs.today_plan : [];
    const own = carRows(attrs, cars, multi, now);
    const rows = strip.map((r) => stripRow(r, now)).filter(Boolean).filter((r) => !CAR_KINDS.has(r.kind) || (own === null && carPresent));
    let list = [...rows, ...(own || [])];
    const guess = (r) => r.kind === 'ev_charge_start' && /estimate/.test(String(r.detail || ''));
    // a guess for a car that is not there is no plan
    if (!carPresent) list = list.filter((r) => !guess(r));
    if (plan) {
        const mine = carPlanRows(plan, cars, now);
        if (mine.length) list = list.filter((r) => !guess(r));
        list = alignDevices([...list, ...mine], plan, now);
        list = planFull(list, plan, now);
    }
    list.sort((a, b) => a.when - b.when);
    const deadline = list.find((r) => r.kind === 'ev_deadline');
    // (#1321) red is for a real miss: with no car plugged in nothing can be late
    if (deadline && carPresent) {
        for (const r of list) if (r.kind === 'ev_min_reached' && r.when > deadline.when) r.late = true;
    }
    return list;
}

/** The plan's battery blocks decide the battery-full row: its time, or no row when the plan has none. */
function planFull(list, plan, now) {
    if (!(Array.isArray(plan.blocks) && plan.blocks.some((b) => b && isBatteryIn(b.id)))) return list;
    const at = batteryFullAt(plan, now);
    const rest = list.filter((r) => r.kind !== 'battery_full');
    if (at === null) return rest;
    const k = KINDS.battery_full;
    return [...rest, { kind: 'battery_full', when: at, iso: new Date(at).toISOString(), icon: k.icon, color: k.color, label: 'plan_battery_full',
        detail: null, values: {}, until: null, day: dayIndex(at, now), late: false, who: '' }];
}

/**
 * When tonight's charging window opens, from the Today list: ms; -Infinity when the night
 * is under way (its end comes first); null when the list names neither. One reading of "tonight" (#1321):
 * `clock` ('HH:MM', the night start sensor) names the hour when given, the list says whether it is open.
 */
export function nightStart(attrs, nowMs = Date.now(), clock = '') {
    const found = stripNightStart(attrs, nowMs);
    if (found === null || found === -Infinity) return found;
    // (#1321) the hour the lead shows (sunset plus the offset) wins for tonight
    const at = nextClock(clock, new Date(nowMs));
    return at && at.getDate() === new Date(nowMs).getDate() ? at.getTime() : found;
}

function stripNightStart(attrs, nowMs) {
    const strip = attrs && Array.isArray(attrs.today_plan) ? attrs.today_plan : [];
    const at = (kind) => strip.filter((r) => r && r.kind === kind).map((r) => Date.parse(r.when)).filter((t) => Number.isFinite(t) && t >= nowMs - 60e3).sort((a, b) => a - b)[0];
    const open = at('night_open'), end = at('night_end');
    if (open === undefined) return end === undefined ? null : -Infinity;
    return end !== undefined && end < open ? -Infinity : open;
}

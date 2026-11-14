/**
 * (#1354) The house battery's settings as plain questions, and what it does
 * now and next — ONE model for both dashboards. Pure: no DOM, no hass.
 *
 * The stored settings do not change. Every question names the entity it
 * shows and writes, exactly the entity the old control wrote.
 *
 * The battery zones (coordinator/decide.py `soc_zone`, flow_calculator.py
 * `battery_assist_potential_w`): below the priority level the battery fills
 * first and the car waits; up to the buffer the car gets spare sun only; from
 * the buffer the battery may help the car; from auto-start it may help fully,
 * still only with enough spare sun.
 */

const finite = (v) => (v === null || v === undefined || v === '' || !Number.isFinite(Number(v)) ? null : Number(v));

/** The four bands of the zone bar, bottom up. `upTo` names the level that ends it. */
export const BATTERY_ZONES = [
    { id: 'fill', upTo: 'priority', color: '#e57373', key: 'bq_zone_fill' },
    { id: 'sun', upTo: 'buffer', color: '#ffb74d', key: 'bq_zone_sun' },
    { id: 'assist', upTo: 'autostart', color: '#81c784', key: 'bq_zone_assist' },
    { id: 'full', upTo: null, color: '#64b5f6', key: 'bq_zone_full' },
];

/** The three zone levels as questions: label, one-line meaning, entity. */
export const BATTERY_LEVELS = [
    { id: 'priority', entity: 'number.sem_battery_priority_soc', key: 'bq_priority', sub: 'bq_priority_sub' },
    { id: 'buffer', entity: 'number.sem_battery_buffer_soc', key: 'bq_buffer', sub: 'bq_buffer_sub' },
    { id: 'autostart', entity: 'number.sem_battery_auto_start_soc', key: 'bq_autostart', sub: 'bq_autostart_sub' },
];

/** The battery's other settings as questions. `kind`: number or switch. */
export const BATTERY_QUESTIONS = {
    solar_gate: { entity: 'number.sem_battery_assist_min_surplus', kind: 'number', key: 'bq_solar_gate', sub: 'bq_solar_gate_sub' },
    assist_max: { entity: 'number.sem_battery_assist_max_power', kind: 'number', key: 'bq_assist_max', sub: 'bq_assist_max_sub' },
    discharge_max: { entity: 'number.sem_battery_max_discharge_power', kind: 'number', key: 'bq_discharge_max', sub: 'bq_discharge_max_sub' },
    may_export: { entity: 'switch.sem_battery_may_export', kind: 'switch', key: 'bq_may_export', sub: 'bq_may_export_sub' },
    may_assist: { entity: 'switch.sem_battery_may_assist_ev', kind: 'switch', key: 'bq_may_assist', sub: 'bq_may_assist_sub' },
    pacing: { entity: 'switch.sem_battery_charge_pacing_enabled', kind: 'switch', key: 'bq_pacing', sub: 'bq_pacing_sub' },
    reserve: { kind: 'number', key: 'bq_reserve', sub: 'bq_reserve_sub' },
};

/** The three zone levels from the states map, in % (null when out). */
export function batteryLevels(states) {
    const out = {};
    for (const l of BATTERY_LEVELS) out[l.id] = finite(states?.[l.entity]?.state);
    return out;
}

/** The bands of the bar with their widths in %, or null while a level is out. */
export function zoneBands(levels) {
    const p = finite(levels?.priority), b = finite(levels?.buffer), a = finite(levels?.autostart);
    if (p === null || b === null || a === null) return null;
    const c = (x) => Math.max(0, Math.min(100, x));
    const edges = [0, c(p), c(b), c(a), 100];
    return BATTERY_ZONES.map((z, i) => ({ ...z, from: edges[i], width: Math.max(0, edges[i + 1] - edges[i]) }));
}

/**
 * What the battery does now and what comes next, from what the engine
 * publishes: its power (+ charge / − discharge), its scheduler state and
 * target, and tonight's floor. `{now:{key,params}, next:{key,params}|null}`.
 */
export function batterySays({ powerW, schedulerState, schedulerTarget, floorPct } = {}) {
    const w = finite(powerW);
    const kw = (x) => (Math.abs(x) / 1000).toFixed(1);
    let now;
    if (w === null) now = { key: 'bq_says_unknown', params: {} };
    else if (w > 50) now = { key: 'bq_says_charging', params: { kw: kw(w) } };
    else if (w < -50) now = { key: 'bq_says_giving', params: { kw: kw(w) } };
    else now = { key: 'bq_says_resting', params: {} };
    const st = String(schedulerState || '');
    const target = finite(schedulerTarget);
    const floor = finite(floorPct);
    let next = null;
    if ((st === 'scheduled' || st === 'waiting_for_slot') && target !== null && target > 0) {
        next = { key: 'bq_next_grid_charge', params: { target: Math.round(target) } };
    } else if (st === 'charging' && target !== null && target > 0) {
        next = { key: 'bq_next_charging_to', params: { target: Math.round(target) } };
    } else if (st === 'discharging_arbitrage') {
        next = { key: 'bq_next_selling', params: {} };
    } else if (floor !== null && floor > 0) {
        next = { key: 'bq_next_keeps', params: { floor: Math.round(floor) } };
    }
    return { now, next };
}

/** batterySays from a Home Assistant states map. */
export function batterySaysFromStates(states) {
    const s = (id) => states?.[id]?.state;
    return batterySays({
        powerW: s('sensor.sem_battery_power'),
        schedulerState: s('sensor.sem_battery_scheduler_state'),
        schedulerTarget: s('sensor.sem_battery_scheduler_target_soc'),
        floorPct: s('sensor.sem_battery_dynamic_floor_pct'),
    });
}

/**
 * (#1321) The battery's floor in %: the plan's own floor when it publishes one
 * (`battery_floor_pct`), else the reserve setting. null when neither is known.
 */
export function batteryFloorPct(states, plan) {
    const p = plan ? Number(plan.battery_floor_pct) : NaN;
    if (plan && plan.battery_floor_pct !== null && plan.battery_floor_pct !== undefined && Number.isFinite(p)) return p;
    const st = states ? states['number.sem_battery_reserve_soc'] : null;
    const r = st ? Number(st.state) : NaN;
    return Number.isFinite(r) ? r : null;
}

/** (#1321) kWh above the floor, or null without a level, a floor or a size. */
export function kwhAboveFloor(soc, floorPct, capKwh) {
    if (![soc, floorPct, capKwh].every((v) => v !== null && v !== undefined && Number.isFinite(Number(v)))) return null;
    if (Number(capKwh) <= 0) return null;
    return Math.max(0, (Number(soc) - Number(floorPct)) / 100 * Number(capKwh));
}

/** (#1321) Each battery's own level and power: [{bid, soc, powerW, status}] from sensor.sem_battery_<bid>_*. */
export function batteryUnits(states, bids) {
    const st = states || {};
    const num = (id) => { const s = st[id]; const n = s ? Number(s.state) : NaN; return Number.isFinite(n) ? n : null; };
    return (Array.isArray(bids) ? bids : []).map((bid) => {
        const p = 'sensor.sem_battery_' + bid + '_';
        const pw = st[p + 'power'];
        const unit = pw && pw.attributes ? String(pw.attributes.unit_of_measurement || '').toLowerCase() : '';
        const w = num(p + 'power');
        return { bid, soc: num(p + 'soc'), powerW: w === null ? null : (unit === 'kw' ? w * 1000 : w), status: st[p + 'status'] ? String(st[p + 'status'].state) : '' };
    }).filter((u) => u.soc !== null || u.powerW !== null);
}

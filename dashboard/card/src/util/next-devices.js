/**
 * (#1321) The Devices screen's pure model. No DOM, no Lit, no hass, so
 * node tests cover it (test/next-devices.test.js).
 *
 * One list, one order: every entry of the load manager's device map
 * (`sensor.sem_controllable_devices_count` attr `devices`) becomes a row,
 * sorted by priority; chargers and the battery the map does not carry are
 * appended so every device has a card. The rank badge is the position,
 * and `swap` renumbers through `moveToIndex`, so the badge and the order
 * can never disagree (drag-reorder.js).
 */

import { regroupChildren, renumber } from './drag-reorder.js';
import { shedReasonKey } from './shed-reason.js';

// (#1349) the heater's words and questions are ONE model, shared with the
// Load Priority card
import { heaterSays, becauseKey } from './heater-questions.js';
export { heaterSays, becauseKey, nextBlock } from './heater-questions.js';

export const CHARGER_PREFIX = 'load_device_';

/** (#1321) sessionStorage key: the charger whose charge plan the Devices screen opens. */
export const OPEN_CHARGE_PLAN_KEY = 'sem-next-open-charge-plan';

/** (#1321) The width at and below which the screens lay out for a phone. */
export const PHONE_MAX_PX = 720;

/**
 * (#1321) Whether a device card starts open: on a phone every card starts
 * folded (its pill is the one-line summary); on a wider screen chargers and
 * batteries open, loads fold. A tap is remembered either way.
 */
export function defaultOpen(type, narrow) {
    if (narrow) return false;
    return type !== 'load';
}

const ICONS = {
    ev_charger: 'mdi:ev-station', ev_charging: 'mdi:ev-station',
    battery: 'mdi:home-battery',
    heating: 'mdi:radiator', heat_pump: 'mdi:heat-pump',
    water_heater: 'mdi:water-boiler', hot_water: 'mdi:water-boiler',
    pool_pump: 'mdi:pool', appliance: 'mdi:washing-machine',
    climate: 'mdi:thermostat', light: 'mdi:lightbulb',
    printer: 'mdi:printer', computer: 'mdi:desktop-classic',
    network: 'mdi:network', fan: 'mdi:fan',
    dryer: 'mdi:tumble-dryer', dishwasher: 'mdi:dishwasher',
    freezer: 'mdi:fridge', refrigerator: 'mdi:fridge',
};

/** The charger id behind a map entry, or null for a load. */
export function chargerIdOf(deviceId) {
    const id = String(deviceId || '');
    return id.startsWith(CHARGER_PREFIX) ? id.slice(CHARGER_PREFIX.length) : null;
}

/** heat_pump · hot_water · load — the registry names these two by id. */
export function loadKind(deviceId) {
    const id = String(deviceId || '');
    if (/^heat_pump/.test(id)) return 'heat_pump';
    if (/^hot_water/.test(id)) return 'hot_water';
    return 'load';
}

/** The icon for a map entry: its own entity's icon when the caller finds one, else by type. */
export function iconFor(info, kind) {
    if (info && info.icon) return info.icon;
    const t = info && info.device_type;
    if (ICONS[t]) return ICONS[t];
    if (ICONS[kind]) return ICONS[kind];
    return 'mdi:power-plug';
}

/** off · peak_only · solar_only · solar_battery (control_mode + battery_assist_enabled). */
export function mergedMode(info) {
    const cm = (info && info.control_mode) || 'peak_only';
    if (cm !== 'surplus') return cm;
    return (info && info.goals && info.goals.battery_assist_enabled) ? 'solar_battery' : 'solar_only';
}

/** The update_device_config writes that set a merged mode. */
export function modeWrites(info, merged) {
    const controlMode = (merged === 'off' || merged === 'peak_only') ? merged : 'surplus';
    const out = [{ property: 'control_mode', value: controlMode }];
    if (controlMode === 'surplus') {
        out.push({ property: 'battery_assist_enabled', value: String(merged === 'solar_battery') });
        if (info && info.goals && info.goals.top_up_policy === 'always') {
            out.push({ property: 'top_up_policy', value: 'solar_only' });
        }
    }
    return out;
}

/** off · battery · grid — one picker over the two overnight flags. */
export function overnightSource(goals) {
    const g = goals || {};
    if (g.battery_eligible_overnight) return 'battery';
    if (g.top_up_policy === 'cheap_hours') return 'grid';
    return 'off';
}

export function overnightWrites(source) {
    return [
        { property: 'battery_eligible_overnight', value: String(source === 'battery') },
        { property: 'top_up_policy', value: source === 'grid' ? 'cheap_hours' : 'solar_only' },
    ];
}

function rowFromMap(id, info) {
    const i = info || {};
    const type = i.device_type === 'battery' ? 'battery'
        : (i.device_type === 'ev_charger' || i.device_type === 'ev_charging') ? 'charger' : 'load';
    const kind = type === 'load' ? loadKind(id) : type;
    const pr = Number(i.priority);
    return {
        id, type, kind, inMap: true,
        cid: type === 'charger' ? (chargerIdOf(id) || id) : null,
        name: i.name || id.replace(/^(load_device_|energy_dashboard_)/, '').replace(/_/g, ' '),
        priority: Number.isFinite(pr) ? pr : 999,
        icon: iconFor(i, kind),
        powerEntity: i.power_entity || '',
        rating: Number(i.power_rating) || 0,
        // (#1326) false only when SEM says the rating is its 1 kW placeholder.
        ratingMeasured: i.rating_measured !== false,
        isOn: !!i.is_on,
        isShed: !!i.is_shed,
        shedReason: i.shed_reason || null,
        shedPhase: i.shed_phase || null,
        phase: (i.goals && i.goals.phase) || i.phase || 'unknown',
        phaseMeasured: i.phase_measured === true,
        behindRelay: !!(i.goals && i.goals.behind_operator_relay),
        lockedByOperator: i.locked_by_operator === true,
        hasControlHandle: i.has_control_handle !== undefined ? i.has_control_handle !== false : i.is_controllable !== false,
        isControllable: i.user_hands_off !== undefined ? i.user_hands_off !== true : i.is_controllable !== false,
        isCritical: !!i.is_critical,
        isAvailable: !!i.is_available,
        hasManualMapping: !!i.has_manual_mapping,
        energySensor: i.energy_sensor || '',
        control: i.control || null,
        controlEntity: (i.control && i.control.entity) || i.switch_entity || '',
        controlMode: i.control_mode || 'peak_only',
        mergedMode: mergedMode(i),
        dependsOn: Array.isArray(i.depends_on) ? i.depends_on : [],
        goals: i.goals || null,
        progress: i.progress || null,
        comfort: i.comfort || null,
        // (#1321) what the load engine decided this cycle: {on, source, code}
        intent: i.intent && typeof i.intent === 'object' ? i.intent : null,
        blockedBy: i.blocked_by || null,
        soc: i.soc,
        // (#1321) the active one-off: {action: 'force'|'skip', until: 'HH:MM'} or null
        override: i.override && i.override.action ? i.override : null,
    };
}

/**
 * Rows for the screen: the map's entries by priority, then the chargers
 * and the battery the map does not know. `chargers` = charger ids from
 * the base; `hasBattery` = a battery SOC sensor exists.
 */
export function deviceRows(devices, chargers = [], { hasBattery = false, chargerName } = {}) {
    const rows = Object.entries(devices || {}).map(([id, info]) => rowFromMap(id, info));
    rows.sort((a, b) => a.priority - b.priority || a.name.localeCompare(b.name));
    const seenCid = new Set(rows.filter((r) => r.type === 'charger').map((r) => r.cid));
    for (const cid of chargers || []) {
        if (seenCid.has(cid)) continue;
        rows.push({
            id: CHARGER_PREFIX + cid, type: 'charger', kind: 'charger', inMap: false, cid,
            name: (chargerName && chargerName(cid)) || cid, priority: 999, icon: ICONS.ev_charger,
            dependsOn: [], isOn: false, isShed: false, goals: null, progress: null, comfort: null,
            hasControlHandle: true, isControllable: true, mergedMode: 'surplus', phase: 'unknown',
        });
    }
    if (hasBattery && !rows.some((r) => r.type === 'battery')) {
        rows.push({
            id: 'battery', type: 'battery', kind: 'battery', inMap: false, cid: null,
            name: '', priority: 999, icon: ICONS.battery,
            dependsOn: [], isOn: false, isShed: false, goals: null, progress: null, comfort: null,
            hasControlHandle: true, isControllable: true, mergedMode: 'surplus', phase: 'unknown',
        });
    }
    rows.forEach((r, i) => { r.priority = i + 1; });
    return rows;
}

/**
 * (#1321) The earliest block of any of `ids` that starts after `nowMs`, or
 * null. A heater has two plan ids: `load:<id>` (its run time) and
 * `comfort:<id>` (its Keep at run).
 */
/**
 * The head pill: a translation key, its params and a class (ok · warn · bad · '').
 * `live` carries what only the entities know: power, amps, pause, the
 * planned start, the battery status and boost.
 */
export function statePill(row, live = {}) {
    const p = (key, params = {}, cls = '') => ({ key, params, cls });
    if (row.lockedByOperator) return p('locked_by_grid_operator', {}, 'warn');
    if (row.isShed) return p(shedReasonKey(row.shedReason), { phase: row.shedPhase || '?' }, 'bad');
    const w = Number.isFinite(live.powerW) ? live.powerW : null;
    if (row.type === 'charger') {
        if (live.paused) return p('next_st_paused', { time: live.pausedUntil || '' }, 'warn');
        if (w !== null && w > 50) {
            return live.amps != null
                ? p('next_st_charging_a', { amps: Math.round(live.amps) }, 'ok')
                : p('next_st_charging', {}, 'ok');
        }
        if (live.plannedAt) return p('next_st_waits_for', { time: live.plannedAt });
        if (live.connected === false) return p('next_st_unplugged');
        if (row.mergedMode === 'off') return p('next_st_off');
        return p('next_st_plugged');
    }
    if (row.type === 'battery') {
        const st = String(live.status || '').toLowerCase();
        if (st === 'selling') return p('next_st_selling', {}, 'ok');
        if (live.boost) return p('next_st_lends_car', {}, 'ok');
        if ((w !== null && w > 50) || st === 'charging') return p('next_st_batt_charging', {}, 'ok');
        if ((w !== null && w < -50) || st === 'discharging') return p('next_st_to_house', {}, 'ok');
        if (live.mode === 'off') return p('next_st_hands_off');
        return p('next_st_rests');
    }
    if (row.blockedBy) return p('next_st_waiting_for', { parent: live.parentName || row.blockedBy });
    const running = row.isOn || (w !== null && w > 10);
    const heater = heaterSays(row, live, running);
    if (heater) return heater;
    if (running) return p('next_st_on', {}, 'ok');
    if (row.mergedMode === 'off') return p('next_st_off_mode');
    // (#1321) peak-only: SEM never starts it, it only pauses it at a peak
    if (row.mergedMode === 'peak_only' || row.mergedMode === 'peak') return p('next_st_off_peak_only');
    if (live.plannedAt) return p('next_st_waits_for', { time: live.plannedAt });
    return { ...p('next_st_off'), why: becauseKey(row.intent) };
}

/**
 * (#1349) The mode sentence of a load: who runs it. Whether power is bought
 * is the buy question's to say, so the grid setting no longer changes it.
 */
export function modeHelpKey(merged) {
    if (merged === 'off') return 'help_mode_off';
    if (merged === 'peak_only') return 'help_mode_peak_only';
    if (merged === 'solar_battery') return 'load_mode_help_sem_battery';
    return merged === 'solar_only' ? 'load_mode_help_sem' : '';
}

/**
 * Move a row one step past its neighbour. A child (Requires) is locked
 * under its parent, and a parent moves with its children: swapping by
 * single positions would put a parent back in front of its own child on
 * the regroup, so ▲▼ never seemed to move it.
 */
export function swap(rows, id, dir) {
    const idx = rows.findIndex((r) => r.id === id);
    if (idx === -1) return rows;
    if ((rows[idx].dependsOn || []).length) return rows;
    const groups = [];
    for (const r of rows) {
        const last = groups[groups.length - 1];
        const deps = r.dependsOn || [];
        if (deps.length && last && last.some((x) => deps.includes(x.id))) last.push(r);
        else groups.push([r]);
    }
    const gi = groups.findIndex((g) => g[0].id === id);
    const gj = gi + (dir < 0 ? -1 : 1);
    if (gi === -1 || gj < 0 || gj >= groups.length) return rows;
    [groups[gi], groups[gj]] = [groups[gj], groups[gi]];
    return renumber(regroupChildren(groups.flat()));
}

/** The update_device_priorities payload: the rows the map knows, by position. */
export function priorityPayload(rows) {
    return { priorities: (rows || []).filter((r) => r.inMap).map((r) => ({ device_id: r.id, priority: r.priority })) };
}

/** The control verdict pill's key. */
export function verdictKey(row) {
    if (!row.hasControlHandle) return 'control_verdict_none';
    if (!row.isControllable || row.mergedMode === 'off') return 'control_verdict_off';
    return 'control_verdict_may_act';
}

/** Runtime progress toward the daily minimum, 0..100, or null without a goal. */
export function goalPct(goals, progress) {
    const target = parseFloat((goals || {}).daily_min_runtime_min);
    const done = parseFloat((progress || {}).runtime_today_min);
    if (!(target > 0) || !Number.isFinite(done)) return null;
    return Math.max(0, Math.min(100, (done / target) * 100));
}

/**
 * The charger target bar: fill and band in percent of the bar.
 * SOC targets scale to 100 %; kWh targets scale to the larger of the
 * maximum target and what was charged today.
 */
export function targetModel({ have, min, max, isSoc }) {
    const h = Number.isFinite(have) ? Math.max(0, have) : null;
    const lo = Number.isFinite(min) ? Math.max(0, min) : null;
    const hi = Number.isFinite(max) && max >= (lo ?? 0) ? max : lo;
    const scale = isSoc ? 100 : Math.max(hi ?? 0, h ?? 0, 1);
    const pct = (v) => Math.max(0, Math.min(100, (v / scale) * 100));
    return {
        fill: h === null ? 0 : pct(h),
        bandLeft: lo === null ? null : pct(lo),
        bandWidth: lo === null ? 0 : Math.max(0, pct(hi ?? lo) - pct(lo)),
        flagLeft: lo === null ? null : pct(lo),
    };
}

/** The battery zone bar: the two gradient stops and every marker that exists. */
export function zonesModel({ soc, priority, buffer, autoStart, floor, reserve }) {
    const c = (v) => (Number.isFinite(v) ? Math.max(0, Math.min(100, v)) : null);
    const marks = [];
    const push = (key, v) => { const p = c(v); if (p !== null) marks.push({ key, pct: p, value: Math.round(p) }); };
    // (#1321) the reserve: where the battery stops giving
    push('reserve', reserve);
    push('priority', priority); push('buffer', buffer); push('auto', autoStart); push('tonight', floor);
    marks.sort((a, b) => a.pct - b.pct);
    const z1 = c(Math.min(priority ?? Infinity, buffer ?? Infinity));
    const z2 = c(Math.max(priority ?? -Infinity, buffer ?? -Infinity));
    return { z1: z1 ?? 0, z2: z2 ?? (z1 ?? 0), marks, cur: c(soc) };
}

const DAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];

/**
 * Weekday departures as runs of the same time: [{from, to, time}] with
 * day indices (0 = Monday). Days without a time of their own take the
 * fallback; an empty fallback leaves them out.
 */
export function weekdaySummary(byWeekday, fallback = '') {
    const own = byWeekday || {};
    const times = DAYS.map((d) => own[d] || fallback || '');
    const runs = [];
    for (let i = 0; i < 7; i++) {
        const t = times[i];
        if (!t) continue;
        const last = runs[runs.length - 1];
        if (last && last.time === t && last.to === i - 1) last.to = i;
        else runs.push({ from: i, to: i, time: t });
    }
    return runs;
}

// ── Add a device ──

/** Domains SEM can switch: a switch device calls homeassistant.turn_on/off; climate has its own class. */
export const SWITCH_DOMAINS = ['switch', 'input_boolean', 'light', 'fan', 'climate'];

/** Loads SEM measures (from HA's Energy settings) but cannot switch yet. */
export function unmanagedLoads(rows) {
    return (rows || []).filter((r) => r && r.type === 'load' && !r.hasControlHandle);
}

/** A device id from a name, unique among the ids SEM already has. */
export function newDeviceId(name, existingIds = []) {
    const base = String(name || '').toLowerCase().normalize('NFKD').replace(/[̀-ͯ]/g, '')
        .replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '') || 'device';
    const taken = new Set(existingIds);
    if (!taken.has(base)) return base;
    let n = 2;
    while (taken.has(`${base}_${n}`)) n++;
    return `${base}_${n}`;
}

/** Entity ids in these domains, sorted; an optional filter on the state object. */
export function entityOptions(states, domains, filter = null) {
    return Object.keys(states || {})
        .filter((id) => domains.includes(id.split('.')[0]) && (!filter || filter(states[id])))
        .sort();
}

/** A temperature reading: a sensor in °C or °F. */
export function isTemperature(st) {
    const u = st?.attributes?.unit_of_measurement;
    return u === '°C' || u === '°F' || st?.attributes?.device_class === 'temperature';
}

/**
 * register_surplus_device data from the form, or { error: key }. The device
 * starts with control_mode off (the backend default): the user opts it in.
 */
export function registerPayload(form, rows = []) {
    const name = String(form?.name || '').trim();
    const entity = String(form?.entity || '').trim();
    if (!name) return { error: 'next_add_need_name' };
    if (!/^[a-z_]+\.[a-z0-9_]+$/.test(entity) || !SWITCH_DOMAINS.includes(entity.split('.')[0])) return { error: 'next_add_need_switch' };
    const data = {
        device_id: newDeviceId(name, (rows || []).map((r) => r.id)),
        entity_id: entity,
        name,
        priority: Math.max(1, Math.min(10, Math.round(Number(form.priority) || Math.min(10, (rows || []).length + 1)))),
    };
    if (entity.startsWith('climate.')) data.device_type = 'climate';
    const rated = Number(form.rated);
    if (Number.isFinite(rated) && rated > 0) data.rated_power = rated;
    const power = String(form.power || '').trim();
    if (power) data.power_entity_id = power;
    return { data };
}

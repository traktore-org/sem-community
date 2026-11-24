/**
 * (#1354) A charger's settings with ONE name per thing, for both dashboards.
 * Pure: no DOM, no hass. The stored settings do not change.
 *
 * The daily target is a pair: "At least" (the floor SEM guarantees, from the
 * grid at night if needed) and "Up to" (where spare sun stops). It is one
 * pair whether it counts kWh or the car's SOC. The departure is "Charge by".
 */

import { strategyWords } from './next-strategy-reason.js';

/** The text keys every card uses for the charger's settings. */
export const CHARGER_TEXT = {
    atLeast: 'at_least',
    upTo: 'up_to',
    target: 'charge_target',
    departure: 'ev_charge_by',
    mode: 'charge_mode',
};

/** (#1381) The four charge modes, in the order every card lists them.
 * The engine still stores one of six strategies; the select maps them. */
export const CHARGE_MODES = ['sun', 'sun_tariff', 'now', 'off'];

/** (#1381) The ends a Now can have: the plan's next block, a time, full. */
export const NOW_ENDS = ['block', 'time', 'full'];

/** (#1381) Minutes from `now` to a "HH:MM" today or, if past, tomorrow. */
export function minutesUntil(hhmm, now = new Date()) {
    const m = /^(\d{1,2}):(\d{2})/.exec(String(hhmm || ''));
    if (!m) return null;
    const at = new Date(now);
    at.setHours(Number(m[1]), Number(m[2]), 0, 0);
    if (at <= now) at.setDate(at.getDate() + 1);
    return Math.max(1, Math.min(1440, Math.round((at - now) / 60000)));
}

/** The text key of a charge mode's name. */
export function chargeModeKey(mode) {
    return 'charge_mode_' + String(mode || '');
}

/** The two target entities of a charger: kWh per day, or the car's SOC. */
export function targetEntities(cid, targetType) {
    return String(targetType) === 'soc'
        ? { atLeast: `number.sem_charger_${cid}_target_soc`, upTo: `number.sem_charger_${cid}_target_soc_max` }
        : { atLeast: `number.sem_charger_${cid}_daily_ev_target`, upTo: `number.sem_charger_${cid}_daily_ev_target_max` };
}

/**
 * What the charger does now and why, in the user's words: the mode's own
 * name and the engine's published reason (`sensor.sem_charging_strategy`
 * attributes reason_code + reason_params, through `plainReason`). Never the
 * engine's raw log text. ``{title, text}``; text is '' without a code.
 */
export function chargerSays(states, t, plainReason) {
    const strat = states ? states['sensor.sem_charging_strategy'] : null;
    if (!strat || !strat.state || strat.state === 'unavailable' || strat.state === 'unknown') return null;
    return strategyWords(strat, t, plainReason);
}

/**
 * (#1321) The fleet line, split by charger when it would contradict one.
 * The engine's fleet reason says "No car is plugged in" while any charger
 * may hold a car; then each connected charger speaks with its own last
 * decision's reason. Returns [{cid|null, title, text}].
 */
export function chargerSaysEach(states, chargerIds, t, plainReason) {
    const fleet = chargerSays(states, t, plainReason);
    if (!fleet) return [];
    const ids = Array.isArray(chargerIds) ? chargerIds : [];
    const on = ids.filter((cid) => states?.[`binary_sensor.sem_charger_${cid}_connected`]?.state === 'on');
    const code = states?.['sensor.sem_charging_strategy']?.attributes?.reason_code;
    if (code !== 'charger_no_car' || !on.length) return [{ cid: null, ...fleet }];
    const per = states?.['sensor.sem_charging_state']?.attributes?.per_charger_last_decision || {};
    return on.map((cid) => {
        const rec = per[cid] || per[`charger_${cid}`] || null;
        const own = rec && rec.reason_code !== 'charger_no_car';
        const text = own ? (plainReason({ reason_code: rec.reason_code, params: rec.params }, t) || '') : '';
        return { cid, title: fleet.title, text };
    });
}

/**
 * (#1321) The charge plan in one line: "Ready by 07:00 · 20–100 kWh · Mon–Sun".
 * `runs` = weekday runs [{from, to, time}] (0 = Monday); `dayName(i)` names a day.
 * Returns {time, range, days}; each part is '' when unknown.
 */
export function chargePlanSummary({ chargeBy = '', min = null, max = null, unit = 'kWh', runs = [], dayName = (i) => String(i) } = {}) {
    const fmt = (v) => (unit === '%' ? String(Math.round(v)) : String(Math.round(v * 10) / 10));
    const hasMin = Number.isFinite(Number(min)) && min !== null, hasMax = Number.isFinite(Number(max)) && max !== null;
    const range = hasMin && hasMax ? `${fmt(Number(min))}–${fmt(Number(max))} ${unit}`
        : hasMin ? `${fmt(Number(min))} ${unit}` : '';
    const list = Array.isArray(runs) ? runs : [];
    const one = list.length === 1 ? list[0] : null;
    const time = one && one.time ? one.time : (chargeBy || '');
    const span = (r) => (r.from === r.to ? dayName(r.from) : `${dayName(r.from)}–${dayName(r.to)}`);
    const days = list.length ? list.map((r) => (one ? span(r) : `${span(r)} ${r.time}`)).join(', ') : '';
    return { time, range, days };
}

/**
 * (#1321) The car's battery size when the owner set it. The number entity
 * always holds a value; `set_by_user: false` says it is only the factory
 * default, which must read as unknown. A server that sends no flag is trusted.
 */
export function knownCapacity(value, attrs) {
    if (capacityUnset(attrs)) return null;
    return Number.isFinite(value) ? value : null;
}

/** (#1321) The server says the capacity is only the factory default: every screen reads that one flag. */
export const capacityUnset = (attrs) => !!attrs && attrs.set_by_user === false;

/**
 * (#1321) The "Up to" figure of a kWh target, never above the car's battery.
 * → { max, full }: `max` the number to show (null when the car is unknown and
 * the figure is only the setting's own ceiling), `full` true when the text
 * should say "full" instead of a number.
 */
export function upToShown({ max, capacity, bound, isSoc, unset = false }) {
    if (max === null || max === undefined) return { max: null, full: false };
    if (isSoc) return { max, full: false };
    // an unknown car: the figure is only the setting's own number, so it reads "full" (#1321)
    if (unset) return { max: null, full: true };
    if (Number.isFinite(capacity) && capacity > 0) return { max: Math.min(max, capacity), full: false };
    return { max, full: Number.isFinite(bound) && max >= bound };
}

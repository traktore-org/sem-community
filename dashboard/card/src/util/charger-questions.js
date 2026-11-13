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

/** The charge modes in the order every card lists them. */
export const CHARGE_MODES = [
    'solar_only', 'solar_plus_battery', 'solar_plus_cheap',
    'min_plus_solar', 'always_max', 'off',
];

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

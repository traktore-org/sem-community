/**
 * (#1354) A charger's settings with ONE name per thing, for both dashboards.
 * Pure: no DOM, no hass. The stored settings do not change.
 *
 * The daily target is a pair: "At least" (the floor SEM guarantees, from the
 * grid at night if needed) and "Up to" (where spare sun stops). It is one
 * pair whether it counts kWh or the car's SOC. The departure is "Charge by".
 */

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

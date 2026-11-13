/**
 * (#1354) Does a setting do anything in this setup? ONE answer for both
 * dashboards, so a card never asks for a number nothing reads. Pure: no DOM,
 * no hass object beyond the states map.
 */

/** Markup, energy tax and VAT are added only to a spot price. An all-in
 *  price (the default) already holds them, so the three fields are not asked. */
export function taxesApply(priceBasis) {
    return String(priceBasis ?? 'all_in') !== 'all_in';
}

/** Hot water is set up when its settings exist: the Legionella target is
 *  made only for an install with a boiler (install module hot_water). */
export function hotWaterSetUp(states) {
    return !!(states && states['number.sem_legionella_target_temp']);
}

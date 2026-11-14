/**
 * (#1354) Does a setting do anything in this setup? ONE answer for both
 * dashboards, so a card never asks for a number nothing reads. Pure: no DOM,
 * no hass object beyond the states map.
 */

/**
 * Which price add-ons change what a bought kWh costs (tariff/value_layer.py
 * `import_value`, tariff/tariff_provider.py `_grid_import_surcharge`):
 * an all-in price (the default) takes no VAT, markup or energy tax; the grid
 * fee is added by the dynamic tariff only.
 */
export function priceAddOns(basis, tariffMode) {
    const onSpot = !!basis && basis !== 'all_in';
    return { vat: onSpot, markup: onSpot, tax: onSpot, fee: tariffMode === 'dynamic' };
}

/** Markup, energy tax and VAT are added only to a spot price. */
export function taxesApply(priceBasis) {
    return priceAddOns(priceBasis ?? 'all_in', null).vat;
}

/** Hot water is set up when its settings exist: the Legionella target is
 *  made only for an install with a boiler (install module hot_water). */
export function hotWaterSetUp(states) {
    return !!(states && states['number.sem_legionella_target_temp']);
}

/** SEM runs a load itself in these two modes; in Off and Peak only it does not,
 *  so the rows that steer a run (stop, thermometer, comfort) do nothing there. */
export function loadRunsBySem(mergedMode) {
    return mergedMode === 'solar_only' || mergedMode === 'solar_battery';
}

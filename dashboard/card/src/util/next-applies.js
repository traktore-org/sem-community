/**
 * (#1354) What a setting does in THIS setup — each rule written once, so a
 * row that does nothing is hidden the same way everywhere.
 */

/** SEM runs the load itself in these two modes; in Off and Peak only it does not. */
export function loadRunsBySem(mergedMode) {
    return mergedMode === 'solar_only' || mergedMode === 'solar_battery';
}

/**
 * Which price add-ons change what a bought kWh costs (tariff/value_layer.py
 * `import_value`, tariff/tariff_provider.py `_grid_import_surcharge`):
 * an all-in price takes no VAT, markup or energy tax; the grid fee is added
 * by the dynamic tariff only.
 */
export function priceAddOns(basis, tariffMode) {
    const onSpot = !!basis && basis !== 'all_in';
    return { vat: onSpot, markup: onSpot, tax: onSpot, fee: tariffMode === 'dynamic' };
}

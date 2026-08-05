// #727 — one place that decides how a temperature reading is LABELLED.
//
// SEM's temperature sensors (sensor.sem_inverter_temperature /
// sensor.sem_battery_temperature) are °C-native, and Home Assistant converts
// them to the user's unit system for display. On a US install that means the
// value HA hands the card in `.state` is already in °F. A card that then
// hardcodes a "°C" suffix mislabels the value it just read — the reported bug,
// where a converted 118 °F showed as a nonsensical "118°C".
//
// The rule: label with the unit HA actually attached to the entity; only fall
// back to °C when HA attached nothing (unit-system default / unavailable).

/** The display unit HA attached to a state object, or '°C' when absent. */
export function temperatureUnit(stateObj) {
    return (stateObj && stateObj.attributes
        && stateObj.attributes.unit_of_measurement) || '°C';
}

/**
 * Format a temperature value with its HA-attached unit.
 *
 * @param {*} value    the raw state value (number or numeric string)
 * @param {string} unit the unit HA attached ('' → °C fallback)
 * @param {{decimals?: number, space?: boolean}} [opts]
 * @returns {string} e.g. "118°F", or '' when the value is not a number
 */
export function formatTemperatureLabel(value, unit, opts = {}) {
    const { decimals = 0, space = false } = opts;
    if (value === null || value === undefined || value === '' || isNaN(parseFloat(value))) {
        return '';
    }
    const u = unit || '°C';
    return `${parseFloat(value).toFixed(decimals)}${space ? ' ' : ''}${u}`;
}

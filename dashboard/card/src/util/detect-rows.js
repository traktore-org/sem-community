/**
 * (#1054 follow-up) The Detected-hardware rows and the power pickers read
 * the same facts the crawler does — pure, so node can test them.
 */

const POWER_UNITS = new Set(['w', 'kw', 'mw']);

/** A sensor the crawler reads as a POWER reading: device_class ``power``,
 *  or — when the integration set no class — a unit in W/kW (go-e's
 *  ``p_all``). A set class other than power wins over the unit. */
export function isPowerEntity(stateObj) {
    const a = (stateObj && stateObj.attributes) || {};
    if (a.device_class) return a.device_class === 'power';
    const unit = String(a.unit_of_measurement || '').trim().toLowerCase();
    return POWER_UNITS.has(unit);
}

/** (#1088) The crawler's CO2-intensity units — the same list as
 *  hardware_detection.CO2_INTENSITY_UNITS (lower case, no spaces, ₂ → 2). */
const CO2_UNITS = new Set([
    'gco2eq/kwh', 'gco2e/kwh', 'gco2/kwh', 'kgco2eq/kwh', 'kgco2e/kwh',
    'kgco2/kwh', 'gco2eq/mwh', 'kgco2eq/mwh', 'kgco2/mwh', 'tco2/mwh',
    'tco2eq/mwh',
]);

/** A sensor whose unit says "CO2 per energy" — the grid CO2 picker shows
 *  only these, by unit, whatever integration publishes them. */
export function isCo2IntensityEntity(stateObj) {
    const a = (stateObj && stateObj.attributes) || {};
    const unit = String(a.unit_of_measurement || '').toLowerCase()
        .replace(/\s+/g, '').replace(/\u2082/g, '2');
    return CO2_UNITS.has(unit);
}

/** (#1082) The outdoor temperature picker: a temperature sensor or a real
 *  weather entity (never HA's auto-made weather.forecast_* twin). */
export function isOutdoorTemperatureCandidate(stateObj) {
    const id = String((stateObj && stateObj.entity_id) || '');
    if (id.startsWith('weather.')) return !id.startsWith('weather.forecast_');
    const a = (stateObj && stateObj.attributes) || {};
    const unit = String(a.unit_of_measurement || '').trim().toLowerCase();
    return a.device_class === 'temperature' || unit === '°c' || unit === '°f';
}

/** The label of a near-miss row: a complete offer is a charger SEM found
 *  and can add, not "no role matched". */
export function detectRowLabelKey(miss) {
    const offer = miss && miss.suggested_charger;
    const missing = (miss && miss.missing) || [];
    return (offer && offer.id && missing.length === 0)
        ? 'config_detect_offer' : 'config_detect_near_miss';
}

/** What a click on "create this charger entry" does. A charger whose id
 *  already exists is there — nothing to add, never a ``<id>_1`` copy. */
export function chargerAddPlan(suggested, existingIds, count) {
    if (!suggested || !suggested.id) return { action: 'none' };
    if ((existingIds || []).includes(suggested.id)) {
        return { action: 'exists', id: suggested.id };
    }
    return {
        action: 'add',
        charger: { ...suggested, ev_min_current: 6,
                   ev_surplus_priority: (count || 0) + 3 },
    };
}

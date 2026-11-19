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

/** (#1137) A charger whose roles matched — power, plug, charging — but that
 *  has no control SEM can drive (a Tesla Wall Connector with no car
 *  integration). It is not "no role matched" and not a report: SEM found
 *  it and can only read it. */
export function isWatchOnlyCharger(miss) {
    const offer = miss && miss.suggested_charger;
    if (offer && offer.id) return false;
    const missing = (miss && miss.missing) || [];
    const roles = (miss && miss.charger_roles) || [];
    return missing.length === 1 && missing[0] === 'control' && roles.length > 0;
}

/** What a near-miss row offers: ``add`` a complete charger, ``watch`` one
 *  that has nothing SEM can drive, or ``report`` a device where no role
 *  matched. */
export function nearMissAction(miss) {
    const offer = miss && miss.suggested_charger;
    const missing = (miss && miss.missing) || [];
    if (offer && offer.id && missing.length === 0) return 'add';
    return isWatchOnlyCharger(miss) ? 'watch' : 'report';
}

/** The label of a near-miss row: a complete offer is a charger SEM found
 *  and can add, not "no role matched"; (#1137) a charger with no control
 *  says what was found. */
export function detectRowLabelKey(miss) {
    return {
        add: 'config_detect_offer',
        watch: 'config_detect_watch_only',
        report: 'config_detect_near_miss',
    }[nearMissAction(miss)];
}

/** (#1137) The help line under a watch-only row: two cars with their own
 *  charge control are a choice SEM does not make; otherwise one car
 *  integration would let SEM drive the charger through the car. */
export function watchOnlyHelpKey(miss) {
    return ((miss && miss.choose_vehicle) || []).length
        ? 'config_detect_choose_vehicle_help' : 'config_detect_watch_only_help';
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

/** (#1224) What one "Use this" click on a proposal saves. Half of a split
 *  pair saves the whole pair in one write: ``p.pair`` maps each choice of
 *  this half to the other half's choices on the same device. The other half
 *  is the one already saved when it is one of those, else the first. Saving
 *  only the clicked half read the other as 0 W. ``null`` when there is
 *  nothing to save, or no whole pair can be made from this choice. */
export function proposalWrite(p, entity, saved) {
    if (!p || !p.config_key || !entity) return null;
    // (#1362) a select proposal also writes the option that means the role
    if (!p.pair) return { [p.config_key]: entity, ...(p.write_extra || {}) };
    const partners = p.pair[entity];
    if (!partners || !Object.keys(partners).length) return null;
    const out = { [p.config_key]: entity };
    for (const [key, choices] of Object.entries(partners)) {
        if (key === p.config_key) return null;
        const left = (choices || []).filter((e) => e && e !== entity);
        const have = saved && saved[key];
        const pick = left.includes(have) ? have : left[0];
        if (!pick) return null;
        out[key] = pick;
    }
    return out;
}

/** (#1224) True when every key a click would write already holds it. */
export function writeIsSaved(write, saved) {
    return !!write && Object.entries(write).every(([k, v]) => !!saved && saved[k] === v);
}

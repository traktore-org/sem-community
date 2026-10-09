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

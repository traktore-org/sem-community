/**
 * #994 — the price level's two absences, in one place for every card.
 *
 * `sensor.sem_tariff_price_level` publishes one of the five comparative
 * words, or one of two absences:
 *
 *   flat       the comparison WAS made and the hours do not differ —
 *              a single rate, two equal rates, a weekend under HT/NT,
 *              a day with no spread. An answer, and on a flat contract
 *              the final one.
 *   no_prices  the comparison could NOT be made — nothing cached yet,
 *              too few points, a price entity that will not read. This
 *              is the one worth a user's attention.
 *
 * Five cards render that state. Four of them passed it straight to the
 * translator, which has no key for a bare `flat`, and the fifth fell
 * through a lookup to NORMAL's label and orange — telling the user SEM
 * had concluded "mid-priced" about a day it never priced.
 */

export const LEVEL_FLAT = 'flat';
export const LEVEL_NO_PRICES = 'no_prices';

/** True for the two words that are not a comparative level. */
export function isAbsence(level) {
    const l = String(level || '').toLowerCase();
    return l === LEVEL_FLAT || l === LEVEL_NO_PRICES;
}

/**
 * The translation key for any level string, absences included.
 *
 * `negative` is the odd one out and always was: its key is `price_negative`,
 * because a bare `negative` would collide. Only the price card knew that —
 * the other four passed the raw state to the translator and would have
 * printed the untranslated word. One table now, so none of them can differ.
 */
const KEYS = {
    negative: 'price_negative',
    [LEVEL_FLAT]: 'price_level_flat',
    [LEVEL_NO_PRICES]: 'price_level_no_prices',
};

export function priceLevelKey(level) {
    const l = String(level || '').toLowerCase();
    return KEYS[l] || l;
}

/** Badge colour; the absences are grey, never NORMAL's orange. */
export function priceLevelColor(level, fallback = '#888') {
    switch (String(level || '').toLowerCase()) {
        case 'negative':       return '#4db6ac';
        case 'very_cheap':
        case 'cheap':          return '#8DC892';
        case 'normal':         return '#ff9800';
        case 'expensive':      return '#f06292';
        case 'very_expensive': return '#e53935';
        case LEVEL_FLAT:
        case LEVEL_NO_PRICES:  return '#9e9e9e';
        default:               return fallback;
    }
}

/**
 * (#1321) What the tariff is, from the states: 'dynamic', 'flat' (one rate, a
 * real answer) or 'none' (no prices to compare: never "one rate"). One reader
 * for the Now, Plan and Insights screens.
 */
export function tariffKind(states) {
    const rate = states && states['sensor.sem_tariff_current_import_rate'];
    const a = (rate && rate.attributes) || {};
    const lv = states && states['sensor.sem_tariff_price_level'];
    const own = lv && !['unknown', 'unavailable', ''].includes(String(lv.state)) ? String(lv.state).toLowerCase() : '';
    const level = own || String(a.price_level || '').toLowerCase();
    if (level === LEVEL_NO_PRICES) return 'none';
    // (#1385) not `is_dynamic`: a schedule or two-rate tariff is not dynamic but
    // has cheaper hours; only the level 'flat' means one price
    if (level === LEVEL_FLAT) return 'flat';
    if (!level) return rate && !['unknown', 'unavailable', ''].includes(String(rate.state)) ? 'flat' : 'none';
    return 'dynamic';
}

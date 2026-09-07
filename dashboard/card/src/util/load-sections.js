/**
 * (#914) Pure rules for the Load Priority card's anti-cycle row — no DOM,
 * no Lit, no hass, so they can be unit-tested headlessly like peak-slot.js.
 *
 * Both exist to stop the card inventing numbers:
 *  - the placeholder used to be a hard-coded "5", true for neither the
 *    resistive default nor the heat-pump one;
 *  - the range used to be re-declared inline as 1..120, a second copy of a
 *    value that lives in consts/bounds.py and nowhere else.
 */

export const MISSING = '—';

/**
 * What the LIVE device is holding, as the placeholder text — or a dash when
 * there is no live object yet. Absent is not zero and not "5".
 * @param {object} goals  the device's `goals` payload
 * @param {string} effKey `min_on_effective_min` | `min_off_effective_min`
 */
export function antiCyclePlaceholder(goals, effKey) {
    const v = (goals || {})[effKey];
    if (v == null) return MISSING;
    const n = Number(v);
    return Number.isFinite(n) ? String(n) : MISSING;
}

/**
 * The range the backend publishes off consts/bounds.py, or null. Null means
 * the input renders with NO min/max — never a range this card made up.
 * @param {object} attrs the devices sensor's attributes
 */
export function antiCycleBounds(attrs) {
    const b = attrs && attrs.anti_cycle_bounds;
    if (!b) return null;
    const min = Number(b.min), max = Number(b.max);
    if (!Number.isFinite(min) || !Number.isFinite(max)) return null;
    return { min, max };
}

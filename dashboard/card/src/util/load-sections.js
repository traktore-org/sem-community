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
    if (!b || b.min == null || b.max == null) return null;
    const min = Number(b.min), max = Number(b.max);
    if (!Number.isFinite(min) || !Number.isFinite(max)) return null;
    return { min, max };
}

/**
 * (#1128) The anti-cycle value to send for what was typed, or null to send
 * nothing. An input's min/max limit its arrows, not typing: a typed 500
 * still fires `change`. A value past the published range is the nearest end
 * of it. Empty, not a number, or under 1 sends nothing: 0 is the "off"
 * value, and clearing the field must not send ''. No published range: the
 * value as typed.
 * @param {string} raw    the input's value
 * @param {{min:number,max:number}|null} bounds from antiCycleBounds()
 */
export function antiCycleValue(raw, bounds) {
    if (raw === '' || raw == null) return null;
    const n = Number(raw);
    if (!Number.isFinite(n) || n < 1) return null;
    const v = bounds ? Math.min(bounds.max, Math.max(bounds.min, n)) : n;
    return v < 1 ? null : v;
}

/** (#1323) The translation key of each HVAC mode the editor offers. */
export const HVAC_MODE_LABELS = {
    heat: 'comfort_hvac_heat',
    cool: 'comfort_hvac_cool',
    by_forecast: 'comfort_hvac_by_forecast',
};

/**
 * (#1323) The modes the load editor's select lists: heat, cool, by forecast,
 * and the unit's present mode when it is another one (dry, auto, ...), so
 * opening the editor never changes what the unit was given.
 */
export function hvacModeOptions(current) {
    const base = Object.keys(HVAC_MODE_LABELS);
    const cur = String(current || '');
    return cur && !base.includes(cur) ? [...base, cur] : base;
}

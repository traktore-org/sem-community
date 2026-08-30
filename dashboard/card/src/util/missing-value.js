/**
 * "A sensor that is out is not a sensor reading zero."
 *
 * Found on PROD 30.08 by walking the live dashboard mid-dropout: the System
 * tab printed `Solar 0W · SOC 0%` while both sensors were `unavailable` —
 * during one of that install's ~137 daily solar dropouts the diagnostics
 * page said the sun was off and the battery was flat. A hard zero is
 * indistinguishable from a real measurement, which is the one thing a
 * DIAGNOSTIC surface must never blur (same care as the cards' `_readWithHold`
 * and the recorder's "an estimate is never recorded as a measurement").
 *
 * `fmtNum` renders a number for display, or the em-dash when the underlying
 * state is absent/unavailable/unknown/non-numeric. Numbers still format
 * exactly as before, so a working install sees no change.
 */

export const MISSING = '—';

/** True when a hass state object carries no usable measurement. */
export function isMissing(stateObj) {
    if (!stateObj) return true;
    const s = stateObj.state;
    if (s === undefined || s === null) return true;
    if (s === 'unavailable' || s === 'unknown' || s === '') return true;
    return Number.isNaN(parseFloat(s));
}

/**
 * Display string for a numeric state: fixed-point, or MISSING.
 * @param {object|undefined} stateObj  hass.states[entity_id]
 * @param {number} digits              decimals (default 0)
 */
export function fmtNum(stateObj, digits = 0) {
    if (isMissing(stateObj)) return MISSING;
    return parseFloat(stateObj.state).toFixed(digits);
}

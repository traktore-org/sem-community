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

/**
 * A battery SOC for display — the one place a reading becomes a label and a
 * fill fraction, so no card can print a fallback as a percentage.
 *
 * PROD 02.09: the Home diagram's battery cell read "0 %" mid-dropout, under
 * "— W" and "sensor unavailable". `_readWithHold` hands back value 0 +
 * stale:true once its 60 s hold expires, and the SOC text and fill took the
 * 0 at face value. 0 % is a flat pack — a real and alarming measurement —
 * and the one thing an absent reading must never look like.
 *
 * @param {number|null|undefined} soc  percent, or nothing
 * @param {boolean} stale              true when a hold has expired
 * @returns {{label: string, fraction: number, known: boolean}}
 *   label: "97%" or MISSING; fraction: 0..1 for a fill (0 when unknown —
 *   an empty cell, never a fabricated level); known: false when absent.
 */
export function socDisplay(soc, stale = false) {
    if (stale || soc == null || Number.isNaN(soc)) {
        return { label: MISSING, fraction: 0, known: false };
    }
    return {
        label: `${soc.toFixed(0)}%`,
        fraction: Math.max(0, Math.min(1, soc / 100)),
        known: true,
    };
}

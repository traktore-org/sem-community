/**
 * (#1354) The peak limit as ONE question: "Limit grid draw to [x kW] / No
 * limit". It replaces a "No grid limit" switch beside a separate number. The
 * stored settings do not change: the answer writes `peak_limit_unlimited` and
 * `target_peak_limit`, exactly what the switch and the number wrote. Shared by
 * both dashboards. Pure: no DOM, no hass.
 */

/** The range every peak control uses (kW). The slider moves in half kW. */
export const PEAK_KW = { min: 1, max: 80, step: 0.1, slider: 0.5, fallback: 5 };

const finite = (v) => (v === null || v === undefined || v === '' || !Number.isFinite(Number(v)) ? null : Number(v));

/** A typed limit inside the range, to one decimal; null for no number. */
export function clampPeakKw(v) {
    const x = finite(v);
    if (x === null) return null;
    return Math.round(Math.min(PEAK_KW.max, Math.max(PEAK_KW.min, x)) * 10) / 10;
}

/** The answer as stored: `{limited, kw}`. kw is the saved limit, kept while
 *  there is no limit so choosing "Limit" again brings it back. */
export function peakQuestion({ unlimited, limitKw }) {
    return { limited: !unlimited, kw: clampPeakKw(limitKw) ?? PEAK_KW.fallback };
}

/** What an answer writes: the two stored fields, as the old controls wrote them. */
export function peakWrites(limited, kw) {
    if (!limited) return { peak_limit_unlimited: true };
    const k = clampPeakKw(kw);
    return k === null ? { peak_limit_unlimited: false } : { peak_limit_unlimited: false, target_peak_limit: k };
}

/** The slider's end means "no limit"; anywhere else is a limit. */
export function sliderAnswer(kw) {
    const x = finite(kw);
    if (x !== null && x >= PEAK_KW.max - 1e-6) return { limited: false, kw: PEAK_KW.max };
    return { limited: true, kw: clampPeakKw(x) ?? PEAK_KW.min };
}

/** The text keys of the question, the same in both dashboards. */
export const PEAK_TEXT = {
    label: 'peak_q_label',          // "Limit grid draw to"
    limit: 'peak_q_choice_limit',   // "A limit"
    none: 'peak_q_choice_none',     // "No limit"
    sub: 'peak_q_sub',              // what a limit does
    subNone: 'peak_q_sub_none',     // what no limit means
};

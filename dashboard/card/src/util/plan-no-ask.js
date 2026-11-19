/**
 * (#1081) Why a device has no ask in the plan, in words. The plan sensor's
 * coverage_why maps a demand id to a reason CODE; the sentence is the
 * why_reason_<code> key, so it reads in the user's language.
 */

/** The translation key for the first of these demand ids the plan has a
 *  reason for, or null. */
export function noAskKey(planAttrs, ...ids) {
    const why = (planAttrs && planAttrs.coverage_why) || {};
    for (const id of ids) {
        const code = why[id];
        if (typeof code === 'string' && /^[a-z_]+$/.test(code)) return 'why_reason_' + code;
    }
    return null;
}

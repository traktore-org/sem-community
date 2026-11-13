/**
 * (#1354) A planner note in the user's language. The engine publishes each
 * demand's note twice: ``note`` (English, for logs) and ``notes`` — a list
 * of {code, params}. Every card renders through this one helper; the
 * English ``note`` shows only when a payload predates the codes.
 */

export const PLAN_NOTE_CODES = [
    'no_night_window', 'no_block_fits', 'unpriced_slots', 'one_price_day',
    'waits_for_sun', 'no_cheap_window', 'cost_unknown',
];

/** ``t`` maps a key to its text (the key itself when missing). */
export function planNoteText(demand, t) {
    const notes = demand && Array.isArray(demand.notes) ? demand.notes : null;
    if (!notes || !notes.length) return (demand && demand.note) || null;
    const parts = [];
    for (const n of notes) {
        const key = 'plan_note_' + (n && n.code);
        let s = t(key);
        if (!s || s === key) return demand.note || null;   // unknown code
        for (const [k, v] of Object.entries((n && n.params) || {})) {
            s = s.replace(new RegExp('\\{' + k + '\\}', 'g'), String(v));
        }
        parts.push(s);
    }
    return parts.join('; ');
}

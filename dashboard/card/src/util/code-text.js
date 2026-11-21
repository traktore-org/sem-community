/**
 * (#1321) The text for a code SEM sends — a mode, a phase, a source. The
 * translate function returns the KEY when it has no text, so `t(k) || code`
 * never falls back. Here a code with no text reads as plain words
 * ("solar_only" → "Solar only"), or "Unknown" for a state; never the code.
 */
export function codeText(t, prefix, code, { unknown = false } = {}) {
    const c = String(code ?? '');
    if (!c) return '';
    const key = prefix + c;
    const v = typeof t === 'function' ? t(key) : '';
    if (v && v !== key) return v;
    if (unknown) {
        const u = typeof t === 'function' ? t('next_code_unknown') : '';
        return u && u !== 'next_code_unknown' ? u : 'Unknown';
    }
    const words = c.replace(/_/g, ' ').trim();
    return words.charAt(0).toUpperCase() + words.slice(1);
}

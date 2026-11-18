/**
 * (#1321) One number formatter for every SEM Next screen, so 3.5 reads 3,5
 * in German, 3.5 in English. HA's own "number format" setting wins when the
 * user chose one (hass.locale.number_format), else the language.
 */

const FORMAT_LOCALE = { decimal_comma: 'de', comma_decimal: 'en-US', space_comma: 'fr', none: 'en-US' };
let current = 'en';

/** The BCP 47 tag HA's user settings ask for. */
export function localeOf(hass) {
    const fmt = hass?.locale?.number_format;
    if (fmt && FORMAT_LOCALE[fmt]) return FORMAT_LOCALE[fmt];
    return hass?.locale?.language || hass?.language || 'en';
}

/** The base class calls this on every hass update; helpers without a card read it. */
export function setNumberLocale(hass) { current = localeOf(hass); }

const cache = new Map();
function formatter(locale, d) {
    const key = locale + '|' + d;
    if (!cache.has(key)) {
        try { cache.set(key, new Intl.NumberFormat(locale, { minimumFractionDigits: d, maximumFractionDigits: d })); }
        catch (_e) { cache.set(key, new Intl.NumberFormat('en', { minimumFractionDigits: d, maximumFractionDigits: d })); }
    }
    return cache.get(key);
}

/** v with exactly d decimals in the user's format; an em dash when it is not a number. */
export function fmtNum(v, d = 1, locale = current) {
    if (v === null || v === undefined || v === '' || !Number.isFinite(Number(v))) return '—';
    return formatter(locale, d).format(Number(v));
}

/** Whole numbers stay whole, others get one decimal (axis labels, hours). */
export function fmtNice(v, locale = current) {
    const n = Number(v);
    if (!Number.isFinite(n)) return '—';
    return fmtNum(n, n >= 10 || n % 1 === 0 ? 0 : 1, locale);
}

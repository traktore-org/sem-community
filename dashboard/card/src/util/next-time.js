/**
 * (#1321) 'HH:MM' in the home's time zone (hass.config.time_zone), not the
 * viewer's browser zone. A phone abroad or a server in UTC shows the house's
 * clock. Falls back to the browser zone when tz is missing or unknown.
 */
const cache = new Map();

function formatter(tz) {
    const k = tz || '';
    if (!cache.has(k)) {
        let f;
        try {
            f = new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZone: tz || undefined });
        } catch (e) {
            f = new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
        }
        cache.set(k, f);
    }
    return cache.get(k);
}

export function hhmmIn(date, tz) {
    const d = date instanceof Date ? date : new Date(date);
    if (!Number.isFinite(d.getTime())) return '';
    return formatter(tz).format(d);
}

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

/**
 * (#1321) A daily deadline 'HH:MM' that has already passed today means the
 * next one is tomorrow: "needs 10 kWh by 07:00" at 07:16 is wrong.
 */
export function deadlineLabel(hhmm, now, tz, tomorrowWord) {
    const t = String(hhmm || '');
    if (!t) return '';
    const clock = hhmmIn(now instanceof Date ? now : new Date(now), tz);
    return clock && clock >= t ? `${String(tomorrowWord).toLowerCase()} ${t}` : t;
}

/** Local hour (0-23) and day 'YYYY-MM-DD' of a date in the home's zone. */
function localParts(date, tz) {
    const d = date instanceof Date ? date : new Date(date);
    if (!Number.isFinite(d.getTime())) return null;
    let day, hour;
    try {
        day = new Intl.DateTimeFormat('en-CA', { timeZone: tz || undefined }).format(d);
        hour = Number(hhmmIn(d, tz).slice(0, 2));
    } catch (e) {
        day = d.toISOString().slice(0, 10);
        hour = d.getHours();
    }
    return { day, hour };
}

/**
 * (#1321) The word for when a plan acts: the plan's first hour against now.
 * Another day than today = tomorrow (an overnight plan read in the evening
 * is still tonight); 18:00 to 06:00 = tonight; before noon = this morning;
 * else today. A plan read at 07:16 never says "tonight".
 */
export function planWhenKey(firstMs, now, tz) {
    const at = Number.isFinite(firstMs) ? firstMs : (now instanceof Date ? now.getTime() : Number(now));
    const a = localParts(at, tz), n = localParts(now instanceof Date ? now : new Date(now), tz);
    if (!a || !n) return 'next_tonight';
    const overnight = a.hour < 6 || a.hour >= 18;
    if (a.day > n.day && !(overnight && n.hour >= 18 && a.hour < 6)) return 'next_when_tomorrow';
    if (overnight) return 'next_tonight';
    return a.hour < 12 ? 'next_when_morning' : 'next_when_today';
}

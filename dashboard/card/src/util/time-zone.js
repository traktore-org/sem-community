/**
 * Time-zone aware "start of day" helper (#450).
 *
 * Compute the absolute Date pointing at the SAME moment as
 * "today's midnight in a given timezone" — used by the dashboard
 * chart cards to query history APIs with HA-server-local midnight
 * rather than browser-local midnight.
 *
 * Pre-#450 the chart card used ``new Date(now.getFullYear(),
 * now.getMonth(), now.getDate())`` which builds the date in browser
 * tz. When the browser TZ differs from HA's server TZ (Companion
 * app roaming, desktop on a different DST schedule) the "Today"
 * window queries the wrong hour range, shifting the visible chart
 * by 1+ hours.
 *
 * Returns a Date object whose ``.getTime()`` (Unix ms) is the
 * moment HA's local midnight occurred (or will next occur,
 * if we're past midnight today in haTz). Falls back to browser-
 * local midnight when ``haTz`` is missing or malformed.
 */
export function startOfDayInHaTz(now, haTz) {
    if (!haTz) {
        return new Date(now.getFullYear(), now.getMonth(), now.getDate());
    }
    try {
        // Step 1: ask Intl what year/month/day "now" is in haTz.
        const fmt = new Intl.DateTimeFormat('en-US', {
            timeZone: haTz, year: 'numeric', month: '2-digit', day: '2-digit',
        });
        const parts = Object.fromEntries(
            fmt.formatToParts(now).map(p => [p.type, p.value])
        );
        // Step 2: build a Date assuming THAT y/m/d at 00:00 in browser tz.
        // This is a probe — the real haTz midnight may be offset from it.
        const probe = new Date(
            Number(parts.year),
            Number(parts.month) - 1,
            Number(parts.day),
            0, 0, 0, 0,
        );
        // Step 3: ask what time it IS at probe-moment in haTz. If haTz says
        // 00:00, we're done. Otherwise compute the offset and shift.
        const haTime = new Intl.DateTimeFormat('en-US', {
            timeZone: haTz, hour: '2-digit', minute: '2-digit', hour12: false,
        }).formatToParts(probe);
        const haH = Number(haTime.find(p => p.type === 'hour').value);
        const haM = Number(haTime.find(p => p.type === 'minute').value);
        const haMinutesPastMidnight = (haH * 60 + haM) % (24 * 60);
        // If haTz sees 22:30 at probe-moment, we're 1.5h BEFORE haTz midnight
        // (probe is too early) → roll FORWARD by (24 - 22.5) = 1.5h.
        // If haTz sees 02:00, we're 2h AFTER haTz midnight (probe is too late)
        // → roll BACKWARD by 2h.
        // The cut-off is at 12:00 — anything past noon means the probe
        // landed BEFORE midnight (need to advance to next midnight), anything
        // before noon means the probe landed AFTER (need to roll back).
        const offsetMin = haMinutesPastMidnight === 0
            ? 0
            : haMinutesPastMidnight <= 12 * 60
                ? -haMinutesPastMidnight                     // probe AFTER midnight → roll back
                : (24 * 60 - haMinutesPastMidnight);         // probe BEFORE midnight → roll forward
        return new Date(probe.getTime() + offsetMin * 60 * 1000);
    } catch (e) {
        return new Date(now.getFullYear(), now.getMonth(), now.getDate());
    }
}

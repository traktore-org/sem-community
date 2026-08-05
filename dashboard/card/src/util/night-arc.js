/**
 * #711 — the moon's night-arc position, as a pure function.
 *
 * Maps the current night (sunset → next sunrise) onto the sun-arc's
 * [0..1] position, counting DOWN from 1 (sunset, right end) to 0
 * (sunrise, left end) — the same anchor points the daytime sun walks
 * 0→1 through. Extracted from sem-system-diagram-card so the sliver
 * behaviour is pinned by dashboard/card/test/night-arc-sliver.test.js.
 *
 * The two boundary slivers: the card's isNight gates on sun ELEVATION
 * < 0 (sun center), while HA's next_rising / next_setting flip at the
 * official −0.833° upper-limb crossing — the two disagree for a few
 * minutes around each event.
 *   - Dusk sliver: elevation is already < 0 while next_setting still
 *     points at TONIGHT's imminent set.
 *   - Dawn sliver: elevation is still < 0 while next_rising already
 *     points at TOMORROW.
 * Both are detected by PROXIMITY TO THE FLIP EVENT, never by elapsed
 * time: an elapsed-time threshold (the first fix) broke on real 20–22 h
 * high-latitude nights (Tromsø, Murmansk — ruflo review of 41cadcf),
 * where "20 h since sunset" is a normal small hour, not a sliver.
 *
 * Returns the raw, UNCLAMPED position (the caller clamps to its arc
 * margins). In the one degenerate case with no honest night mapping —
 * polar onset, a day shorter than the sliver window, the derived night
 * inverts — the DIRECTIONAL fallback (ruflo review) lands on whichever
 * arc end's event is nearer to now (0 = sunrise, 1 = sunset) instead of
 * freezing mid-arc. null only for missing attributes.
 */

export const DAY_MS = 86400000;
// Generous margin over the real elevation-vs-limb disagreement (minutes),
// small enough that no inhabited-latitude day or night gets mistaken for
// a sliver (shortest real days/nights near the polar circle are hours).
export const SUN_SLIVER_MS = 3600000;

export function nightArcPos(now, nextRiseTs, nextSetTs) {
    if (!nextRiseTs || !nextSetTs) return null;
    // This night's SUNSET: normally next_setting minus a day (it points at
    // tomorrow's set all night); in the dusk sliver the set is imminent and
    // next_setting IS tonight's — use it directly.
    const setTs = (nextSetTs - now < SUN_SLIVER_MS)
        ? nextSetTs : nextSetTs - DAY_MS;
    // This night's SUNRISE: normally next_rising itself; in the dawn sliver
    // it has just flipped to tomorrow (nearly a full day away) — pull it
    // back to today's, which passed moments ago.
    const riseTs = (nextRiseTs - now > DAY_MS - SUN_SLIVER_MS)
        ? nextRiseTs - DAY_MS : nextRiseTs;
    const nightLength = riseTs - setTs;
    if (nightLength <= 0) {
        // Degenerate polar-onset day (shorter than the sliver window): the
        // derived endpoints cross and no honest mapping exists. Land on
        // whichever end's event is nearer to now — 18 min before an actual
        // sunrise the moon belongs at the sunrise end, not mid-arc.
        return Math.abs(now - riseTs) <= Math.abs(now - setTs) ? 0 : 1;
    }
    return 1 - (now - setTs) / nightLength;
}

/**
 * (#1321) The charger line on the Now screen. SEM's strategy text is
 * written for its log ("solar_plus_battery day Zone 3: budget=0W below
 * 8A min — staying idle …"); the card names the mode and keeps only the
 * words a person reads.
 */

const MODE_RE = /^([a-z][a-z0-9_]*)(?=[\s:]|$)\s*/;

export function splitStrategyReason(reason) {
    const text = String(reason || '').trim();
    const m = text.match(MODE_RE);
    const mode = m && m[1].includes('_') ? m[1] : '';
    const rest = mode ? text.slice(m[0].length) : text;
    const colon = rest.indexOf(':');
    const head = (colon >= 0 ? rest.slice(0, colon) : rest).trim();
    const tail = colon >= 0 ? rest.slice(colon + 1) : '';
    const detail = tail.split(/\s[—–]\s/)
        .map((part) => part
            .replace(/\b[A-Za-z_]+=[^\s)]+(?:\s+(?:kWh|kW|W|A|%|°C|min|h|s)\b)?/g, '')
            .replace(/\(\s*\)/g, '')
            .replace(/\s{2,}/g, ' ')
            .replace(/^[\s,;:—–-]+|[\s,;:—–\]-]+$/g, '')
            .trim())
        .filter(Boolean)
        .join(' · ');
    return { mode, head: head || text, detail };
}

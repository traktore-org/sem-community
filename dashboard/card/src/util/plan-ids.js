/**
 * (#1354) A plan id (`ev:<charger>`, `load:<device>`, `comfort:<device>`,
 * `battery…`) as the name a person reads. ONE reader for every card, so no
 * card ever prints the raw id ("comfort:hot_water"). Pure.
 */

/** The id split into its kind and the device or charger key. */
export function planIdParts(id) {
    const s = String(id || '');
    if (s.startsWith('ev:')) return { kind: 'ev', key: s.slice(3) };
    if (s.startsWith('comfort:')) return { kind: 'comfort', key: s.slice(8) };
    if (s.startsWith('load:')) return { kind: 'load', key: s.slice(5) };
    if (s.includes('battery')) return { kind: 'battery', key: s };
    return { kind: 'other', key: s.replace(/^[a-z_]+:/, '') };
}

/** A key that has no name anywhere, written as words ("hot_water" → "Hot water"). */
export function keyAsWords(key) {
    const w = String(key || '').replace(/[_-]+/g, ' ').trim();
    return w ? w.charAt(0).toUpperCase() + w.slice(1) : '';
}

/**
 * The name for a plan id. `names`: `charger(cid)`, `load(key)` (a device's
 * own name), `battery()` (the battery's word), `label(id)` (the plan's own
 * label for the id). The first that answers wins; the key as words last.
 */
export function planIdName(id, names = {}) {
    const { kind, key } = planIdParts(id);
    const pick = (...xs) => xs.find((x) => typeof x === 'string' && x.trim()) || '';
    if (kind === 'battery') return pick(names.battery && names.battery(), keyAsWords('battery'));
    if (kind === 'ev') return pick(names.charger && names.charger(key), names.label && names.label(id), keyAsWords(key));
    return pick(names.load && names.load(key), names.label && names.label(id), keyAsWords(key));
}

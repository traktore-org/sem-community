/**
 * (#1321) Shared number words so one value reads the same on every screen.
 */

/**
 * A tariff price: two decimals, three when the third is not zero, so an
 * export rate of 0.075 is never rounded to 0.07 on one screen and shown
 * as 0.075 on another.
 */
export function fmtPrice(v) {
    const n = Number(v);
    if (v === null || v === undefined || v === '' || !Number.isFinite(n)) return '—';
    const three = n.toFixed(3);
    return three.endsWith('0') ? n.toFixed(2) : three;
}

/**
 * The grid reading as the Now screen says it: a positive size and the way it
 * flows. SEM's own sign is import negative, export positive.
 * → { watts: number >= 0, dir: 'import' | 'export' | '' } or null when not a number.
 */
export function gridReading(state) {
    if (state === null || state === undefined || state === '') return null;
    const w = Number(state);
    if (!Number.isFinite(w)) return null;
    return { watts: Math.abs(w), dir: w < 0 ? 'import' : (w > 0 ? 'export' : '') };
}

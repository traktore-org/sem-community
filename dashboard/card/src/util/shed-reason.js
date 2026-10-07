/**
 * (#992) Which label a shed device wears.
 *
 * The backend writes the reason in UPPER CASE — `EMERGENCY` when the meter
 * has breached the emergency threshold, `PROGRESSIVE` when it is shedding
 * toward the target (`features/load_management.py`). The card compared it
 * against a lower-case `'emergency'`, so the comparison was never true and
 * every emergency shed — the one case where the label matters — read
 * "peak protection".
 *
 * A helper rather than an inline ternary so the rule can be tested: the
 * bug survived because nothing could see it but a person reading a tile
 * during an emergency.
 */
export function shedReasonKey(shedReason) {
    if (String(shedReason || '').toUpperCase() === 'EMERGENCY') return 'shed_emergency';
    // (#1048) the phase guard's own shed — a fuse, not the peak tariff
    if (String(shedReason || '').toUpperCase() === 'PHASE') return 'shed_phase';
    return 'shed_peak';
}

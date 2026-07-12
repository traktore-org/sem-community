/**
 * Pure reorder helpers for the priority list (#576). No DOM — fully
 * unit-testable with `node --test`. The card imports these so the TESTED logic
 * IS the SHIPPED logic.
 *
 * Design invariant that kills a whole class of bugs: there is ONE source of
 * order truth (the device array), and the badge shown on a row is always its
 * POSITION (index + 1). Because `renumber` sets `priority = position + 1`, the
 * number and the visual order can never disagree, and priorities are always a
 * unique, gap-free 1..N. This is what the SortableJS→Lit rewrite guarantees.
 */

/**
 * Order children (a device's `dependsOn` parent) immediately after their
 * parent, depth-first, so a "Requires" link stays visually grouped. A child
 * whose parent is missing (orphan) keeps its place at the end. Returns a new
 * array (same device objects).
 */
export function regroupChildren(devices) {
    const result = [];
    const placed = new Set();
    const childrenOf = (id) =>
        devices.filter(d => (d.dependsOn || []).includes(id) && !placed.has(d.id));
    const add = (d) => {
        if (placed.has(d.id)) return;
        result.push(d);
        placed.add(d.id);
        childrenOf(d.id).forEach(add);
    };
    devices.filter(d => !(d.dependsOn || []).length).forEach(add);
    // orphans (dependsOn a device not in the list) — keep them, at the end
    devices.forEach(d => { if (!placed.has(d.id)) result.push(d); });
    return result;
}

/**
 * priority = position + 1. The badge shows the position, so number and order
 * can never disagree and priorities are always unique 1..N. Mutates each
 * device's `priority` and returns the same array.
 */
export function renumber(devices) {
    devices.forEach((d, i) => { d.priority = i + 1; });
    return devices;
}

/**
 * Move `deviceId` to `targetIndex`, regroup its children under it, and
 * renumber. Returns a NEW top-level array (device objects are reused). Used by
 * BOTH the pointer-drag and the ▲▼ arrows so they share one contract.
 */
export function moveToIndex(devices, deviceId, targetIndex) {
    const arr = devices.slice();
    const from = arr.findIndex(d => d.id === deviceId);
    if (from === -1) return arr;
    const [dev] = arr.splice(from, 1);
    const at = Math.max(0, Math.min(targetIndex, arr.length));
    arr.splice(at, 0, dev);
    return renumber(regroupChildren(arr));
}

/**
 * Drop index during a pointer-drag: how many OTHER rows' original centres sit
 * above the pointer Y (the dragged row at `fromIndex` is excluded). This is
 * the insertion index in the reduced array — exactly what `moveToIndex` wants.
 */
export function computeDropIndex(centres, fromIndex, pointerY) {
    let idx = 0;
    for (let i = 0; i < centres.length; i++) {
        if (i === fromIndex) continue;
        if (pointerY > centres[i]) idx++;
    }
    return idx;
}

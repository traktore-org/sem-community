// (#1204) One battery's edit of a per-battery list option.
//
// Slot N of a per-battery list is battery bN's, and SEM moves the slots when
// the batteries in the Energy Dashboard change (#1195). The card's copy of
// the options holds the lists in the battery order it read
// (``battery_slot_units``). Sending the whole list from that copy put the old
// order back after a change, and a copy that failed to read emptied every
// other slot. So the card sends only the slot it changed, with the order it
// read; SEM puts the value on that battery's slot today.

// The ``set_option`` payload for one slot, and the list to show until the
// card reads its copy again.
export function batteryListEdit(options, listKey, idx, value, count) {
    const opts = options || {};
    const units = Array.isArray(opts.battery_slot_units)
        ? [...opts.battery_slot_units] : null;
    const shown = Array.isArray(opts[listKey]) ? [...opts[listKey]] : [];
    while (shown.length < count) shown.push(null);
    shown[idx] = value || null;
    return {
        payload: { [listKey]: { slot: idx, value: value || null, battery_slot_units: units } },
        shown: { [listKey]: shown },
    };
}

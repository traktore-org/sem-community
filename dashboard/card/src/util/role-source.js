// (#1054) Where a charger role comes from, for the chip beside its picker.
//
// A charger is a device reference: SEM's crawler fills each role from the
// device (detected), the user may set one by hand (set by you), or the
// crawler found nothing (not found). The refs arrive in the merged config
// as ev_charger_refs: {id, device_id, overrides, cleared, found}.

// The roles the crawler answers for — the same list as charger_refs.ROLE_KEYS
// for the entity pickers the card shows.
export const ROLE_PICKER_KEYS = new Set([
    'ev_connected_sensor', 'ev_charging_sensor', 'ev_charging_power_sensor',
    'ev_current_control_entity', 'ev_start_stop_entity', 'ev_charge_mode_entity',
    'ev_current_sensor', 'ev_session_energy_sensor', 'ev_total_energy_sensor',
    'ev_charger_service_entity_id',
]);

export function chargerRef(config, cid) {
    const refs = (config && config.ev_charger_refs) || [];
    return refs.find((r) => r && r.id === cid) || null;
}

// {kind, detected} — kind is 'detected' | 'you' | 'none', or null when no
// chip belongs here: no ref yet, a device-less charger (the crawler is not
// asked for it), or a key that is not a role.
export function roleSource(config, cid, key) {
    if (!ROLE_PICKER_KEYS.has(key)) return { kind: null, detected: null };
    const ref = chargerRef(config, cid);
    if (!ref || !ref.device_id) return { kind: null, detected: null };
    const found = (ref.found || {})[key] || null;
    const cleared = (ref.cleared || []).includes(key);
    if (Object.prototype.hasOwnProperty.call(ref.overrides || {}, key)) {
        return { kind: 'you', detected: found && found !== ref.overrides[key] ? found : null };
    }
    if (found && !cleared) return { kind: 'detected', detected: found };
    return { kind: 'none', detected: null };
}

// The one-line legend shows only on a charger read from a device.
export function showsRoleLegend(config, cid) {
    const ref = chargerRef(config, cid);
    return Boolean(ref && ref.device_id);
}

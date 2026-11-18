/**
 * (#1053/#1321) A charger's name as the user configured it.
 *
 * SEM publishes it as the `charger_name` attribute on the charger's power
 * sensor. The friendly name is translated ("SEM Laadpaal Links Vermogen"),
 * so it is never parsed; without the attribute the id stands in.
 */
export function chargerNameOf(states, cid, prefix = 'sensor.sem_') {
    const id = String(cid || '');
    const name = states?.[`${prefix}charger_${id}_power`]?.attributes?.charger_name;
    if (typeof name === 'string' && name.trim()) return name.trim();
    return id.replace(/_/g, ' ');
}

/**
 * (#1386) The set_option payload that renames one charger, or null for a
 * blank name. The id picks the charger; the server merges by id, so the
 * other chargers and every entity id stay as they are.
 */
export function chargerRenameWrite(cid, typed) {
    const name = String(typed ?? '').replace(/\s+/g, ' ').trim().slice(0, 60);
    return name ? { ev_chargers: [{ id: String(cid), name }] } : null;
}

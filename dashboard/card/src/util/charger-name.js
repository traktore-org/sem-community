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

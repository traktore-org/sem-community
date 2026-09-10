/**
 * (#944) Which status a charger's tile shows.
 *
 * The status was read off the draw alone, so while SEM stood down from a
 * stop war (#763) — the box kept restarting itself, and SEM stopped
 * stopping it so the car is not strobed into a fault — a car drawing 3 kW
 * against SEM's intent looked exactly like an ordinary charge. The backend
 * publishes the stand-down per charger on the charging-state sensor
 * (``per_charger_stop_war``); this reads it.
 *
 * Returns a translation key.
 */
export function chargerStatusKey({ isCharging, isConnected, standDown }) {
    // Strictly true: the flag is a bool, and a stale or malformed attribute
    // must not relabel an ordinary charge.
    if (isCharging && standDown && standDown.standing_down === true) {
        return 'charger_status_stood_down';
    }
    if (isCharging) return 'charging';
    return isConnected ? 'connected' : 'idle';
}

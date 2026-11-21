/**
 * (#1407) The amps a charger runs at, as every card shows them: one rule.
 *
 * The charger's own current on each phase comes first — it holds whoever
 * runs the charge, SEM or another system. Without it, SEM's command, but
 * only while SEM sends one or nothing is drawn: a charge SEM did not ask
 * for read "0 A" beside 1.5 kW. Drawing with no command and no reading is
 * unknown (null), never 0 A.
 */
export function chargerAmps(card, cid) {
    const ph = (card._attrs('sensor.sem_charging_state').per_charger_phases || {})[cid] || {};
    const measured = ph.measured_current;
    if (measured !== null && measured !== undefined && measured !== '' && Number.isFinite(Number(measured))) {
        return Number(measured);
    }
    const commanded = card._num('sensor.sem_charger_' + cid + '_commanded_current');
    if (commanded !== null && commanded > 0) return commanded;
    const powerW = card._powerW('sensor.sem_charger_' + cid + '_power');
    return powerW !== null && powerW > 50 ? null : commanded;
}

/**
 * (#1321) The one sentence about the battery and the car, for Plan, Now and
 * Decisions. The floor is tonight's need, so the sentence says the need:
 * when the need is more than the battery holds, all of it stays for the house;
 * otherwise the car may use what is above the floor.
 */

const SPEND = 'sensor.sem_battery_spendable_kwh';

const numOf = (states, id) => {
    const v = states?.[id]?.state;
    return v === undefined || v === null || v === '' || !Number.isFinite(Number(v)) ? null : Number(v);
};

/** What the states hold: { phase, floor, need, soc } with null for what is unknown. */
export function batteryFactsFrom(states) {
    const a = states?.[SPEND]?.attributes || {};
    const need = Number(a.overnight_need_kwh);
    return {
        phase: String(a.phase || ''),
        need: Number.isFinite(need) && need > 0 ? need : null,
        floor: numOf(states, 'sensor.sem_battery_dynamic_floor_pct'),
        soc: numOf(states, 'sensor.sem_battery_soc'),
    };
}

/** What the card knows: same facts as batteryFactsFrom, read the card's way. */
export function batteryFacts(card) {
    return batteryFactsFrom(card._hass?.states);
}

/** The shared sentence from the states and a plain `t`: one source for every screen. */
export function batterySentence(states, t) {
    const tf = (k, p) => String(t(k)).replace(/\{(\w+)\}/g, (m, n) => (p && p[n] !== undefined ? String(p[n]) : m));
    return batteryNeedText(tf, t, batteryFactsFrom(states));
}

/**
 * batteryNeedText(tf, t, facts) → text or ''.
 * Holding, or a floor at 100 %: all of it stays for the house. Else the car
 * may use what is above the floor. Without the need only the floor is said.
 */
export function batteryNeedText(tf, t, f) {
    const need = f.need === null ? null : (Math.round(f.need * 10) / 10).toFixed(1);
    const under = f.floor !== null && f.soc !== null && f.soc < f.floor;   // the floor is the need: under it, nothing is spare
    const all = f.phase === 'holding' || (f.floor !== null && f.floor >= 99.5) || (under && need !== null);
    if (all) return need === null ? t('next_batt_holds_house') : tf('next_batt_need_all', { need });
    if (f.floor === null) return '';
    const floor = Math.round(f.floor);
    return need === null ? tf('next_why_batt_floor_short', { floor }) : tf('next_batt_need_above', { need, floor });
}

/**
 * (#1321) The battery's size, ONE reading for every screen. The nameplate is what the
 * pack is rated for (sem_diag_battery_capacity, else the setting); the usable size is
 * what SEM measured per full charge. Shown together as "15.0 kWh (12.7 usable)".
 */
const NAMEPLATE = ['sensor.sem_diag_battery_capacity', 'number.sem_battery_capacity'];
const MEASURED = 'sensor.sem_battery_measured_capacity_kwh';
const SPENDABLE = 'sensor.sem_battery_spendable_kwh';
const pos = (v) => (Number.isFinite(v) && v > 0 ? v : null);
const val = (states, id) => {
    const s = states && states[id]?.state;
    return s === undefined || s === null || s === '' || s === 'unknown' || s === 'unavailable' ? NaN : Number(s);
};

/** → { nominal, usable } in kWh; usable is null when it is missing or the same as the nameplate. */
export function batterySize(states) {
    const nominal = NAMEPLATE.map((id) => pos(val(states, id))).find((v) => v !== null) ?? null;
    const usable = pos(val(states, MEASURED)) ?? pos(Number(states?.[SPENDABLE]?.attributes?.measured_capacity_kwh));
    return { nominal, usable: usable !== null && (nominal === null || Math.abs(usable - nominal) >= 0.05) ? usable : null };
}

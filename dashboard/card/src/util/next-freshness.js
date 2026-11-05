/**
 * (#1321) How fresh a source is, from its last_updated stamp.
 *
 * ok: updated within okS · old: within oldS · off: older, or unavailable ·
 * missing: no such entity. A reading that is old is still shown, with its
 * age; a reading that is off is shown as off, never as 0.
 */

export const SOURCE_ROWS = [
    { key: 'next_src_solar', entity: 'sensor.sem_solar_power' },
    { key: 'next_src_grid', entity: 'sensor.sem_grid_power' },
    { key: 'next_src_battery', entity: 'sensor.sem_battery_power' },
    { key: 'next_src_car', entity: 'sensor.sem_ev_power' },
    { key: 'next_src_forecast', entity: 'sensor.sem_forecast_today_kwh', okS: 2 * 3600, oldS: 8 * 3600 },
    { key: 'next_src_price', entity: 'sensor.sem_tariff_current_import_rate', okS: 2 * 3600, oldS: 26 * 3600 },
];

export function ageSeconds(stateObj, nowMs = Date.now()) {
    const t = Date.parse(stateObj?.last_updated || '');
    return Number.isFinite(t) ? Math.max(0, (nowMs - t) / 1000) : null;
}

export function freshness(stateObj, nowMs = Date.now(), { okS = 120, oldS = 1800 } = {}) {
    if (!stateObj) return 'missing';
    const s = stateObj.state;
    if (s === 'unavailable' || s === 'unknown' || s === undefined || s === null) return 'off';
    const age = ageSeconds(stateObj, nowMs);
    if (age === null) return 'off';
    if (age <= okS) return 'ok';
    if (age <= oldS) return 'old';
    return 'off';
}

/** Human age: 12 s · 4 min · 2 h. */
export function ageLabel(seconds) {
    if (seconds === null || !Number.isFinite(seconds)) return '';
    if (seconds < 90) return `${Math.round(seconds)} s`;
    if (seconds < 5400) return `${Math.round(seconds / 60)} min`;
    return `${Math.round(seconds / 3600)} h`;
}

/** Rows for the System screen; a row whose entity does not exist is left out. */
export function sourceRows(states, nowMs = Date.now()) {
    const rows = [];
    for (const r of SOURCE_ROWS) {
        const st = states?.[r.entity];
        if (!st) continue;
        const state = freshness(st, nowMs, { okS: r.okS || 120, oldS: r.oldS || 1800 });
        rows.push({ key: r.key, entity: r.entity, state, age: ageSeconds(st, nowMs), value: st.state });
    }
    return rows;
}

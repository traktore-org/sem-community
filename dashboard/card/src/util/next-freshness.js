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

/** (#1321) Which part of SEM's own Energy-dashboard read each source row follows. */
const SOURCE_PART = { next_src_solar: 'solar', next_src_grid: 'grid', next_src_battery: 'battery' };

/**
 * The real entity behind a source row — what SEM reads, as the System card's
 * debug line shows it (Rien, PR 1322). edConfig: sensor.sem_diag_ed_config's
 * `energy_dashboard` attribute. → an entity id, or '' when SEM does not say.
 */
export function sourceEntityOf(key, edConfig) {
    const part = SOURCE_PART[key];
    const id = part ? edConfig?.[part]?.power : null;
    return typeof id === 'string' ? id : '';
}

export function ageSeconds(stateObj, nowMs = Date.now()) {
    const t = Date.parse(stateObj?.last_updated || '');
    return Number.isFinite(t) ? Math.max(0, (nowMs - t) / 1000) : null;
}

export function freshness(stateObj, nowMs = Date.now(), { okS = null, oldS = null } = {}) {
    if (!stateObj) return 'missing';
    const s = stateObj.state;
    if (s === 'unavailable' || s === 'unknown' || s === undefined || s === null) return 'off';
    // last_updated moves only when the VALUE changes: a solar sensor reads 0
    // all night and is still alive. Age judges only rows that declare a
    // limit (a forecast or a price that stopped arriving).
    if (okS === null || oldS === null) return 'ok';
    const age = ageSeconds(stateObj, nowMs);
    if (age === null) return 'off';
    if (age <= okS) return 'ok';
    if (age <= oldS) return 'old';
    return 'off';
}

export const POWER_ENTITIES = ['sensor.sem_solar_power', 'sensor.sem_grid_power', 'sensor.sem_battery_power',
    'sensor.sem_home_consumption_power', 'sensor.sem_ev_power'];

/** The newest last_updated among readings that answer. One reading that holds
 *  its value (solar at 0 all night) does not make the others look old. */
export function newestUpdate(states, ids = POWER_ENTITIES) {
    let best = null;
    for (const id of ids) {
        const st = states?.[id];
        if (!st || st.state === 'unavailable' || st.state === 'unknown') continue;
        const t = Date.parse(st.last_updated || '');
        if (Number.isFinite(t) && (best === null || t > best)) best = t;
    }
    return best === null ? null : new Date(best).toISOString();
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
        const state = freshness(st, nowMs, { okS: r.okS ?? null, oldS: r.oldS ?? null });
        // An age only where a limit makes it mean something: an unchanged
        // power reading is alive, its last_updated is just its last change.
        const aged = r.okS != null;
        rows.push({ key: r.key, entity: r.entity, state, age: aged ? ageSeconds(st, nowMs) : null, value: st.state });
    }
    return rows;
}

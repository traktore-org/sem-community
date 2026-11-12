/**
 * (#1349) A heater's settings as four plain questions, and what it does now
 * and next — ONE model for the Load Priority card and the SEM Next Devices
 * card. Pure: no DOM, no hass.
 *
 * The stored settings do not change. The cards translate:
 *   keep it at            = comfort_target
 *   never colder than     = comfort_limit
 *   with spare sun, up to = comfort_target + comfort_offset   (an ABSOLUTE temperature)
 *   may SEM buy power     = top_up_policy / battery_eligible_overnight
 *
 * The band's lines (keep_c, start_c, max_c, limit_c, may_buy) and the load's
 * intent ({on, source, code}) are published by the engine and never
 * re-derived here.
 */

export const num = (v) => (v === null || v === undefined || v === '' || !Number.isFinite(Number(v)) ? null : Number(v));

/** Why a load is off, as a text key, from the engine's reason code. '' = nothing worth saying. */
const BECAUSE = {
    peak_shed: 'hq_because_peak',
    phase_guard: 'hq_because_phase',
    phase_shed: 'hq_because_phase',
    vacation: 'hq_because_away',
    plan_wait: 'hq_because_plan_wait',
    no_source: 'hq_because_no_sun',
    surplus_short: 'hq_because_no_sun',
    target_met: 'hq_because_ran_enough',
    daily_max: 'hq_because_daily_max',
    stop_condition: 'hq_because_stop',
    at_target: 'hq_because_stop',
    load_override_stop: 'hq_because_paused',
    step_down_price: 'hq_because_held_back',
    step_down_peak: 'hq_because_held_back',
    no_season: 'hq_because_no_season',
};
export function becauseKey(intent) {
    if (!intent || intent.on) return '';
    return BECAUSE[String(intent.code || '')] || '';
}

/** The next future block of any of `ids` (plan ids like load:<id>, comfort:<id>), or null. */
export function nextBlock(blocks, ids, nowMs) {
    const want = new Set((ids || []).map(String));
    return (Array.isArray(blocks) ? blocks : [])
        .filter((b) => b && want.has(String(b.id)) && Date.parse(b.start) > nowMs)
        .sort((a, b) => Date.parse(a.start) - Date.parse(b.start))[0] || null;
}

/**
 * What a heater with a Keep at band does and what comes next:
 * `{key, params, cls, why, next?, noBuy?}`, or null for a load without a
 * heating band (it keeps the plain texts).
 * `row` = {comfort, intent, mergedMode}; `live.fmtTemp` turns °C into the
 * user's unit; `live.plannedAt` is the next planned start (HH:MM).
 */
export function heaterSays(row, live = {}, running = false) {
    const c = row && row.comfort;
    if (!c || c.hvac === 'cool') return null;
    const keep = num(c.keep_c), start = num(c.start_c), max = num(c.max_c);
    if (keep === null) return null;
    const T = typeof live.fmtTemp === 'function' ? live.fmtTemp : (v) => (Math.round(v * 10) / 10) + ' °C';
    const p = (key, params = {}, cls = '', why = '') => ({ key, params, cls, why });
    const intent = row.intent || {};
    const code = String(intent.code || '');
    const reading = num(c.reading_c);
    if (running) {
        if (c.own_run || code === 'legionella') return p('hq_st_legionella', {}, 'ok');
        if (code === 'comfort_floor' || c.state === 'forced') return p('hq_st_too_cold', {}, 'warn');
        if (code === 'comfort_goal') return p('hq_st_heating_to', { keep: T(keep) }, 'ok');
        if (intent.source === 'solar' || intent.source === 'tier1_battery') {
            return p('hq_st_heating_sun', { max: T(max === null ? keep : max) }, 'ok');
        }
        return null;
    }
    if (row.mergedMode === 'off') return null;
    // idle: these say what comes NEXT
    const idle = (key, params = {}, cls = '', why = '') => ({ ...p(key, params, cls, why), next: true });
    if (reading === null) return idle('hq_st_no_reading', {}, 'warn');
    if (reading >= keep) return idle('hq_st_warm', { reading: T(reading) });
    const line = start === null ? keep : start;
    if (reading > line) return idle('hq_st_warm_again', { start: T(line) });
    if (live.plannedAt) return idle('hq_st_heats_at', { keep: T(keep), time: live.plannedAt });
    // (#1102) Solar only buys nothing: no hour will ever be planned.
    if (c.may_buy === false) return { ...idle('hq_st_waits_sun', { keep: T(keep) }), noBuy: true };
    const why = becauseKey(row.intent);
    return idle('hq_st_below_none', { keep: T(keep) }, 'warn', why === 'hq_because_no_sun' ? '' : why);
}

/**
 * The line under the top sentence: `{key, params}` or null.
 * A planned hour ahead: sun before then is free. Solar only: SEM buys nothing.
 */
export function heaterSub(says, row, live = {}) {
    if (!says) return null;
    const T = typeof live.fmtTemp === 'function' ? live.fmtTemp : (v) => (Math.round(v * 10) / 10) + ' °C';
    if (says.key === 'hq_st_heats_at') return { key: 'hq_sub_sun_free', params: {} };
    if (says.noBuy) {
        const limit = num(row && row.comfort && row.comfort.limit_c);
        return { key: 'hq_sub_no_buy', params: { limit: limit === null ? '' : T(limit) } };
    }
    return null;
}

/** Heaters below their start line, buying allowed, with no hour in the plan. */
export function coldHeaters(devices, blocks, nowMs) {
    const list = Array.isArray(blocks) ? blocks : [];
    const out = [];
    for (const [id, info] of Object.entries(devices || {})) {
        const c = info && info.comfort;
        if (!c || c.hvac === 'cool' || c.keep_c == null || c.reading_c == null) continue;
        const keep = Number(c.keep_c), start = Number(c.start_c ?? c.keep_c), reading = Number(c.reading_c);
        if (![keep, start, reading].every(Number.isFinite) || reading > start) continue;
        if (info.is_on || (info.intent && info.intent.on)) continue;
        if (info.control_mode === 'off' || info.user_hands_off === true) continue;
        // (#1102) solar only buys nothing: it is not in the plan, it waits for sun
        if (c.may_buy === false) continue;
        const has = list.some((b) => b && (String(b.id) === 'comfort:' + id || String(b.id) === 'load:' + id) && Date.parse(b.end) > nowMs);
        if (!has) out.push({ id, name: info.name || id, keepC: keep });
    }
    return out;
}

/** off · grid · battery, as stored (the two flags "Finish overnight from" writes). */
export function buySource(goals) {
    const g = goals || {};
    if (g.battery_eligible_overnight === true || g.battery_eligible_overnight === 'true') return 'battery';
    if (g.top_up_policy === 'cheap_hours') return 'grid';
    return 'off';
}

/** The two writes of the buy question — exactly what the old picker wrote. */
export function buyWrites(source) {
    return [
        { property: 'battery_eligible_overnight', value: String(source === 'battery') },
        { property: 'top_up_policy', value: source === 'grid' ? 'cheap_hours' : 'solar_only' },
    ];
}

/**
 * The four questions of one load:
 *   view 'band'  a heater whose thermometer leads: keep · floor · sunMax · buy
 *   view 'time'  a load without an engaged band: its daily run time · buy
 *   view 'cool'  a cooling band: today's layout (not mirrored yet)
 * Temperatures are in the user's unit, as typed and stored.
 * `goals` = the row's goals; `comfort` = the row's live comfort block.
 */
export function heaterQuestions({ goals, comfort }, { hasBattery = false } = {}) {
    const g = goals || {};
    const keep = num(g.comfort_target), floor = num(g.comfort_limit);
    const offset = num(g.comfort_offset) || 0;
    const engaged = keep !== null && keep > 0 && floor !== null && floor > 0;
    const cooling = (comfort && comfort.hvac === 'cool')
        || (engaged && !(comfort && comfort.hvac) && floor > keep)
        || g.hvac_mode === 'cool';
    const src = buySource(g);
    if (engaged && cooling) return { view: 'cool', keep, floor, offset, buy: src };
    if (engaged) {
        // A battery finish serves the daily run time only; with a
        // thermometer the run time asks nothing, so it would do nothing here.
        return {
            view: 'band', keep, floor, offset,
            sunMax: Math.round((keep + offset) * 10) / 10,
            buy: g.top_up_policy === 'cheap_hours' ? 'grid' : 'off',
            buyChoices: ['off', 'grid'],
            buySubKey: 'hq_buy_sub_band',
        };
    }
    return {
        view: 'time',
        buy: src === 'battery' && !hasBattery ? 'off' : src,
        buyChoices: hasBattery ? ['off', 'grid', 'battery'] : ['off', 'grid'],
        buySubKey: 'hq_buy_sub_time',
    };
}

export const BUY_LABEL = { off: 'hq_buy_no', grid: 'hq_buy_cheap', battery: 'hq_buy_battery' };

/**
 * "With spare sun, heat up to X" → the writes, or `{error, params}`.
 * X is absolute; stored is the offset above Keep at. On a hot-water row the
 * Configuration tab's Solar target also stops the sun ("SEM stops at the
 * lower of the two"), so it is set to the same value: `option`.
 * `solarTarget` = {min, max} of that option's number entity, when known.
 */
export function sunMaxWrites({ id, keep }, x, solarTarget = null) {
    const k = num(keep), v = num(x);
    if (k === null || v === null) return { error: 'hq_err_below_keep', params: { keep: k === null ? '' : String(k) } };
    if (v < k) return { error: 'hq_err_below_keep', params: { keep: String(k) } };
    const isHotWater = /^hot_water/.test(String(id || ''));
    if (isHotWater && solarTarget && num(solarTarget.max) !== null && v > Number(solarTarget.max)) {
        return { error: 'hq_err_above_max', params: { max: String(solarTarget.max) } };
    }
    const offset = Math.round((v - k) * 2) / 2;
    return {
        writes: [{ property: 'comfort_offset', value: String(offset) }],
        option: isHotWater ? { key: 'hot_water_solar_target', value: Math.round((k + offset) * 10) / 10 } : null,
    };
}

/** A sentence from a short status text: first letter up, a full stop at the end. */
export function asSentence(text) {
    const s = String(text || '').trim();
    if (!s) return '';
    const up = s.charAt(0).toUpperCase() + s.slice(1);
    return /[.!?]$/.test(up) ? up : up + '.';
}

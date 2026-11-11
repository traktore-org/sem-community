/**
 * (#1321) The one line each SEM Next screen opens with.
 *
 * Pure: facts in, translation keys with parameters out. The card turns a
 * key into words with semLocalize and fills {name} placeholders, so the
 * sentence shape lives in translations.json for every language.
 *
 * A fact that is not known is left out of the line, never invented: a
 * missing car gives a line about the house, a missing battery a line
 * without one.
 */

const IMPORT_W = 100;   // below this the grid is "quiet"
const SUN_W = 100;      // the roof gives something above this

function fmt1(v) {
    return Number.isFinite(v) ? (Math.round(v * 10) / 10).toFixed(1) : '';
}
function fmt0(v) {
    return Number.isFinite(v) ? String(Math.round(v)) : '';
}

/**
 * The Now screen's line.
 *
 * f = {
 *   night: bool, observer: bool,
 *   solarW, gridW (SEM sign: negative = import), batteryW (negative = discharge),
 *   car: { present, charging, powerW, amps, remainingKwh, targetTime } | null,
 *   battery: { soc, floorPct, bufferPct } | null  (floorPct only while SEM spends
 *            the battery: a holding floor limits the car, never the house),
 *   sunAt: 'HH:MM' | '', nightStart: 'HH:MM' | '',
 * }
 * Returns { main: {key, params}, sub: {key, params} | null }.
 */
export function nowLead(f) {
    const car = f.car || null;
    const bat = f.battery || null;
    const importing = Number.isFinite(f.gridW) && f.gridW < -IMPORT_W;
    const exporting = Number.isFinite(f.gridW) && f.gridW > IMPORT_W;
    const sun = Number.isFinite(f.solarW) && f.solarW > SUN_W;
    const batToHouse = Number.isFinite(f.batteryW) && f.batteryW < -IMPORT_W;
    const houseKey = batToHouse ? 'next_lead_house_battery' : (importing ? 'next_lead_house_grid' : 'next_bar_idle');
    const prefix = f.observer ? 'next_lead_observing' : (f.night ? 'next_lead_night' : 'next_lead_day');
    const blind = !Number.isFinite(f.solarW) && !Number.isFinite(f.gridW) && !Number.isFinite(f.batteryW);

    let main;
    if (blind && !(car && car.present)) {
        main = { key: 'next_lead_unknown', params: {} };
    } else if (car && car.present && car.charging) {
        if (f.night || !sun) {
            main = { key: 'next_lead_car_grid_kw', params: {
                kw: fmt1(car.powerW / 1000), kwh: fmt1(car.remainingKwh), time: car.targetTime || '' } };
            if (!Number.isFinite(car.remainingKwh)) main = { key: 'next_lead_car_charging', params: { kw: fmt1(car.powerW / 1000) } };
        } else {
            main = { key: 'next_lead_car_sun', params: { kw: fmt1(car.powerW / 1000) } };
        }
    } else if (car && car.present && Number.isFinite(car.remainingKwh) && car.remainingKwh > 0.1) {
        main = { key: 'next_lead_car_waits', params: { kwh: fmt1(car.remainingKwh), time: car.targetTime || '' } };
    } else if (sun && exporting) {
        main = { key: 'next_lead_sun_export', params: { kw: fmt1(f.gridW / 1000) } };
    } else if (sun && bat && Number.isFinite(f.batteryW) && f.batteryW > IMPORT_W) {
        main = { key: 'next_lead_sun_battery', params: { soc: fmt0(bat.soc) } };
    } else if (sun) {
        main = { key: 'next_lead_sun_house', params: {} };
    } else {
        main = { key: houseKey, params: {} };
    }

    let sub = null;
    if (bat && Number.isFinite(bat.soc)) {
        if (Number.isFinite(bat.floorPct) && bat.soc < bat.floorPct && !batToHouse) {
            sub = { key: 'next_sub_battery_rests', params: { soc: fmt0(bat.soc), floor: fmt0(bat.floorPct) } };
        } else if (batToHouse) {
            sub = { key: 'next_sub_battery_house', params: { soc: fmt0(bat.soc) } };
        } else {
            sub = { key: 'next_sub_battery_at', params: { soc: fmt0(bat.soc) } };
        }
    }
    if (f.night && f.sunAt) {
        sub = sub
            ? { key: 'next_sub_two', params: { a: sub, b: { key: 'next_sub_sun_at', params: { time: f.sunAt } } } }
            : { key: 'next_sub_sun_at', params: { time: f.sunAt } };
    } else if (!f.night && f.nightStart) {
        sub = sub
            ? { key: 'next_sub_two', params: { a: sub, b: { key: 'next_sub_night_at', params: { time: f.nightStart } } } }
            : { key: 'next_sub_night_at', params: { time: f.nightStart } };
    }
    return { prefix, main, sub };
}

/** Fill {name} placeholders. Nested {key, params} values are rendered with t first. */
export function fill(text, params, t) {
    let out = String(text || '');
    for (const [k, v] of Object.entries(params || {})) {
        const val = (v && typeof v === 'object' && v.key) ? fill(t(v.key), v.params, t) : String(v ?? '');
        out = out.split('{' + k + '}').join(val);
    }
    return out;
}

/**
 * (#1321) Heaters that are below the line a planned run starts under, are
 * off, and have no hour in the plan (now or ahead). From the engine's own
 * band lines (`comfort.keep_c` / `start_c`, °C) — nothing re-derived.
 * → [{ id, name, keepC }]
 */
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
        const has = list.some((b) => b && (String(b.id) === 'comfort:' + id || String(b.id) === 'load:' + id) && Date.parse(b.end) > nowMs);
        if (!has) out.push({ id, name: info.name || id, keepC: keep });
    }
    return out;
}

/** The Plan screen's line from the plan sensor's attributes. */
export function planLead(a, extra) {
    const ok = a && typeof a === 'object' && Array.isArray(a.blocks);
    if (!ok || !a.computed_at) return { main: { key: 'next_plan_none', params: {} }, sub: null };
    const evKwh = kwhOf(a.blocks, (id) => String(id).startsWith('ev:'));
    // (#1321) a heater's Keep at run is a load run too (plan id comfort:<id>)
    const loadKwh = kwhOf(a.blocks, (id) => String(id).startsWith('load:') || String(id).startsWith('comfort:'));
    // A heater below its start line with no hour planned: "nothing planned"
    // would read as "nothing is needed". Say what is missing instead.
    const cold = extra?.cold || null;
    const quiet = cold
        ? { key: cold.time ? 'next_plan_below_no_hour' : 'next_plan_below_no_hour_plain',
            params: { name: cold.name, keep: cold.keep, time: cold.time || '' } }
        : { key: 'next_plan_quiet', params: {} };
    const main = evKwh > 0.05
        ? { key: 'next_plan_car', params: { kwh: fmt1(evKwh) } }
        : (loadKwh > 0.05 ? { key: 'next_plan_loads', params: { kwh: fmt1(loadKwh) } } : quiet);
    const sub = { key: 'next_plan_sub', params: {
        time: extra?.computedAt || '', cost: extra?.cost || '',
        fits: extra?.fitsKey || '', sun: fmt1(extra?.sunTomorrowKwh) } };
    return { main, sub };
}

/** kWh of the blocks whose id passes `pick` (power × hours). */
export function kwhOf(blocks, pick) {
    let kwh = 0;
    for (const b of (Array.isArray(blocks) ? blocks : [])) {
        if (!pick(b.id)) continue;
        const s = Date.parse(b.start), e = Date.parse(b.end);
        if (!Number.isFinite(s) || !Number.isFinite(e) || e <= s) continue;
        kwh += (Number(b.power_w) || 0) * (e - s) / 3.6e9;
    }
    return kwh;
}

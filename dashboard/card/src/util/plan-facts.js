/**
 * (#1321) ONE reading of the plan for every screen: who takes energy, when,
 * and how much. The plan sensor keeps its merged blocks when it can; when it
 * has to drop them (a day on a quarter-hour market), each demand still names
 * its hours in `why.params.from/to`. effectivePlan() turns those into blocks,
 * so the headline, the chart, "Why this plan", the per-device rows and the
 * Now screen all read the same list. Pure.
 */
import { hhmmIn } from './next-time.js';

const HOUR = 3600e3;
const cache = new WeakMap();

/** The demand's own hours { s, e } from its why code, or null. */
export function demandWindow(d) {
    const p = d && d.why && d.why.params ? d.why.params : {};
    const s = Date.parse(p.from), e = Date.parse(p.to);
    return Number.isFinite(s) && Number.isFinite(e) && e > s ? { s, e } : null;
}

/** The plan with a block for every demand that names hours but has none. */
export function effectivePlan(plan) {
    if (!plan || typeof plan !== 'object') return plan;
    if (cache.has(plan)) return cache.get(plan);
    const blocks = Array.isArray(plan.blocks) ? plan.blocks : [];
    const have = new Set(blocks.map((b) => String(b && b.id)));
    const added = [];
    for (const d of (Array.isArray(plan.demands) ? plan.demands : [])) {
        if (!d || !d.id || have.has(String(d.id))) continue;
        const w = demandWindow(d), kwh = Number(d.planned_kwh);
        if (!w || !(kwh > 0)) continue;
        added.push({ id: String(d.id), start: new Date(w.s).toISOString(), end: new Date(w.e).toISOString(),
            power_w: kwh * 1000 / ((w.e - w.s) / HOUR), price: null, derived: true });
    }
    const out = added.length ? { ...plan, blocks: [...blocks, ...added] } : plan;
    cache.set(plan, out);
    return out;
}

/** kWh of the blocks `pick` accepts that fall inside [from, to), prorated by time. */
export function kwhIn(blocks, pick, from, to) {
    let kwh = 0;
    for (const b of (Array.isArray(blocks) ? blocks : [])) {
        if (!b || !pick(String(b.id))) continue;
        const s = Date.parse(b.start), e = Date.parse(b.end);
        if (!Number.isFinite(s) || !Number.isFinite(e) || e <= s) continue;
        const a = Math.max(s, from), z = Math.min(e, to);
        if (z > a) kwh += (Number(b.power_w) || 0) * (z - a) / 3.6e9;
    }
    return kwh;
}

/** The house's own grid kWh inside [from, to): the slots when the plan has them, else its total. */
export function houseKwhIn(plan, from, to) {
    const slots = plan && Array.isArray(plan.slots) ? plan.slots : [];
    if (!slots.length) {
        const v = plan && plan.house_grid ? Number(plan.house_grid.kwh) : NaN;
        return Number.isFinite(v) ? Math.max(0, v) : 0;
    }
    let kwh = 0;
    for (const sl of slots) {
        const w = Number(sl && sl.home_grid_w), s = Date.parse(sl && sl.start), e = Date.parse(sl && sl.end);
        if (!(w > 0) || !Number.isFinite(s) || !Number.isFinite(e) || e <= s) continue;
        const a = Math.max(s, from), z = Math.min(e, to);
        if (z > a) kwh += w * (z - a) / 3.6e9;
    }
    return kwh;
}

/** Calendar day of `ms` in the home's zone, 'YYYY-MM-DD'. */
function dayOf(ms, tz) {
    try { return new Intl.DateTimeFormat('en-CA', { timeZone: tz || undefined }).format(new Date(ms)); }
    catch (e) { return new Date(ms).toISOString().slice(0, 10); }
}

/** 0 today, 1 tomorrow, 2 later, -1 before today (home zone). */
export function dayOffset(ms, nowMs, tz) {
    const a = dayOf(ms, tz), n = dayOf(nowMs, tz);
    if (a === n) return 0;
    const diff = Math.round((Date.parse(a) - Date.parse(n)) / 86400e3);
    return diff < 0 ? -1 : (diff === 1 ? 1 : 2);
}

/**
 * A clock time that never reads as a past time today: "07:30" is today's;
 * the next day's is "tomorrow 07:30", a later day's carries its weekday.
 * `words` = { tomorrow }; `weekday(ms)` names a later day.
 */
export function clockWithDay(ms, nowMs, tz, words = {}, weekday = null) {
    const t = hhmmIn(new Date(ms), tz);
    const d = dayOffset(ms, nowMs, tz);
    if (d === 1) return `${words.tomorrow || 'tomorrow'} ${t}`;
    if (d >= 2 && typeof weekday === 'function') return `${weekday(ms)} ${t}`;
    return t;
}

/** "08:04 – 15:15", or "tomorrow 06:30 – 07:30"; the day shows once when both ends share it. */
export function windowText(s, e, nowMs, tz, words = {}, weekday = null) {
    const first = clockWithDay(s, nowMs, tz, words, weekday);
    const same = dayOffset(s, nowMs, tz) === dayOffset(e, nowMs, tz);
    const last = same ? hhmmIn(new Date(e), tz) : clockWithDay(e, nowMs, tz, words, weekday);
    return `${first} – ${last}`;
}

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

/** A demand's own runs [{ s, e, w }] from `demand.runs` ([[start, end, watts], ...]), or []. */
export function demandRuns(d) {
    const out = [];
    for (const r of (d && Array.isArray(d.runs) ? d.runs : [])) {
        const s = Date.parse(r && r[0]), e = Date.parse(r && r[1]);
        if (Number.isFinite(s) && Number.isFinite(e) && e > s) out.push({ s, e, w: Number(r[2]) || 0 });
    }
    return out;
}

/**
 * (#1321) A demand is never shown more than it needs. The planner books whole
 * slots, so a car that needs 10.0 kWh can hold 10.3; the car stops at its
 * target. The blocks of such a demand are scaled down together, so the parts
 * still add up to the need. Returns the same array when nothing is over.
 */
function capAtNeed(blocks, demands) {
    const need = new Map();
    for (const d of (Array.isArray(demands) ? demands : [])) {
        const n = Number(d && d.needed_kwh);
        if (d && d.id && Number.isFinite(n) && n > 0) need.set(String(d.id), n);
    }
    const sums = new Map();
    for (const b of blocks) {
        if (!b || !need.has(String(b.id))) continue;
        const kwh = (Number(b.power_w) || 0) * Math.max(0, Date.parse(b.end) - Date.parse(b.start)) / 3.6e9;
        sums.set(String(b.id), (sums.get(String(b.id)) || 0) + (Number.isFinite(kwh) ? kwh : 0));
    }
    const factor = new Map();
    for (const [id, sum] of sums) if (sum > need.get(id) * 1.001) factor.set(id, need.get(id) / sum);
    if (!factor.size) return blocks;
    return blocks.map((b) => (b && factor.has(String(b.id)) ? { ...b, power_w: (Number(b.power_w) || 0) * factor.get(String(b.id)) } : b));
}

/**
 * The plan with a block for every demand that names hours but has none. A demand's own
 * runs come first, so a gap between two runs stays a gap; the first-to-last span of
 * `why.params` is only the fallback for a plan that has no runs (older sensor).
 */
export function effectivePlan(plan) {
    if (!plan || typeof plan !== 'object') return plan;
    if (cache.has(plan)) return cache.get(plan);
    const blocks = Array.isArray(plan.blocks) ? plan.blocks : [];
    const have = new Set(blocks.map((b) => String(b && b.id)));
    const added = [];
    for (const d of (Array.isArray(plan.demands) ? plan.demands : [])) {
        if (!d || !d.id || have.has(String(d.id))) continue;
        const iso = (ms) => new Date(ms).toISOString();
        const runs = demandRuns(d);
        if (runs.length) {
            for (const r of runs) added.push({ id: String(d.id), start: iso(r.s), end: iso(r.e), power_w: r.w, price: null, derived: true });
            continue;
        }
        const w = demandWindow(d), kwh = Number(d.planned_kwh);
        if (!w || !(kwh > 0)) continue;
        added.push({ id: String(d.id), start: iso(w.s), end: iso(w.e),
            power_w: kwh * 1000 / ((w.e - w.s) / HOUR), price: null, derived: true });
    }
    const all = capAtNeed(added.length ? [...blocks, ...added] : blocks, plan.demands);
    const out = all !== blocks ? { ...plan, blocks: all } : plan;
    cache.set(plan, out);
    return out;
}

/**
 * The runs of the plan ids `pick` accepts that have not ended: [{ s, e, kwh }], by start.
 * Blocks that touch join, whatever their watts: that is one stretch of charging. The
 * kWh is the whole run, never the part from now on, so every screen shows one figure.
 */
export function planRuns(plan, pick, nowMs = -Infinity) {
    const rows = [];
    for (const b of (plan && Array.isArray(plan.blocks) ? plan.blocks : [])) {
        if (!b || !pick(String(b.id))) continue;
        const s = Date.parse(b.start), e = Date.parse(b.end);
        if (!Number.isFinite(s) || !Number.isFinite(e) || e <= s || e <= nowMs) continue;
        rows.push({ s, e, kwh: (Number(b.power_w) || 0) * (e - s) / 3.6e9 });
    }
    rows.sort((a, b) => a.s - b.s);
    const out = [];
    for (const r of rows) {
        const last = out[out.length - 1];
        if (last && r.s <= last.e) { last.e = Math.max(last.e, r.e); last.kwh += r.kwh; } else out.push({ ...r });
    }
    return out;
}

/**
 * `values` rounded to `d` decimals so the rounded parts add up to the rounded
 * total (largest remainder). One rounding for a figure and its parts (#1321).
 */
export function roundedParts(values, d = 1) {
    const f = 10 ** d;
    const v = (values || []).map((x) => (Number.isFinite(Number(x)) ? Number(x) : 0));
    const total = Math.round(v.reduce((a, b) => a + b, 0) * f);
    const base = v.map((x) => Math.floor(x * f + 1e-9));
    let rest = total - base.reduce((a, b) => a + b, 0);
    const order = v.map((x, i) => [x * f - base[i], i]).sort((a, b) => b[0] - a[0]);
    for (let k = 0; rest > 0 && k < order.length; k++, rest--) base[order[k][1]] += 1;
    return base.map((x) => x / f);
}

/** planRuns whose kWh are rounded to one decimal and sum to the rounded total. */
export function planRunsRounded(plan, pick, nowMs = -Infinity) {
    const runs = planRuns(plan, pick, nowMs);
    const parts = roundedParts(runs.map((r) => r.kwh));
    return runs.map((r, i) => ({ ...r, kwh: parts[i] }));
}

/** kWh the plan still has for a demand id and the kWh the demand needs: { planned, needed } (needed null when unknown). */
export function demandFigures(plan, id, nowMs = -Infinity) {
    const runs = planRuns(plan, (x) => x === id, nowMs);
    const d = (plan && Array.isArray(plan.demands) ? plan.demands : []).find((x) => x && x.id === id);
    const needed = d && Number.isFinite(Number(d.needed_kwh)) ? Number(d.needed_kwh) : null;
    const planned = runs.reduce((a, r) => a + r.kwh, 0);
    return { planned: Math.round(planned * 10) / 10, needed: needed === null ? null : Math.round(needed * 10) / 10 };
}

/**
 * Demands the plan cannot fully serve: [{ id, planned, needed }] (one decimal each).
 * Names WHO is short, for the plan's "not everything fits" (#1321).
 */
export function shortfalls(plan, nowMs = -Infinity) {
    const out = [];
    for (const d of (plan && Array.isArray(plan.demands) ? plan.demands : [])) {
        if (!d || !d.id) continue;
        const f = demandFigures(plan, String(d.id), nowMs);
        const planned = f.planned > 0 || (plan.blocks || []).some((b) => b && b.id === d.id) ? f.planned : Math.round((Number(d.planned_kwh) || 0) * 10) / 10;
        if (f.needed !== null && planned < f.needed - 0.05 && d.status !== 'fits') out.push({ id: String(d.id), planned, needed: f.needed });
    }
    return out;
}

/** The first run that has not started, or null. */
export function nextRun(runs, nowMs) {
    return (runs || []).find((r) => r.s > nowMs) || null;
}

/** "08:33 – 09:45, 14:45 – 15:45": every run by its own hours (`win(s, e)` words one). */
export function runsText(runs, win) {
    return (runs || []).map((r) => win(r.s, r.e)).join(', ');
}

/** kWh of the blocks `pick` accepts that end after `from` and start before `to`; cut at `to` only. */
export function kwhIn(blocks, pick, from, to) {
    let kwh = 0;
    for (const b of (Array.isArray(blocks) ? blocks : [])) {
        if (!b || !pick(String(b.id))) continue;
        const s = Date.parse(b.start), e = Date.parse(b.end);
        if (!Number.isFinite(s) || !Number.isFinite(e) || e <= s) continue;
        // a run under way counts whole: the lists name its full kWh, so the sum agrees
        const a = s, z = Math.min(e, to);
        if (e > from && z > a) kwh += (Number(b.power_w) || 0) * (z - a) / 3.6e9;
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

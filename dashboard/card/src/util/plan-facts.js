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
const MINUTE = 60e3;
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
    const need = new Map(), win = new Map();
    for (const d of (Array.isArray(demands) ? demands : [])) {
        const n = Number(d && d.needed_kwh);
        if (!d || !d.id || !Number.isFinite(n) || n <= 0) continue;
        need.set(String(d.id), n);
        // the need belongs to the demand's own window; blocks of a later window under the same id are not cut (#1321)
        const runs = demandRuns(d);
        win.set(String(d.id), demandWindow(d) || (runs.length ? { s: Math.min(...runs.map((r) => r.s)), e: Math.max(...runs.map((r) => r.e)) } : null));
    }
    const inside = (b) => {
        const w = win.get(String(b.id));
        return !w || (Date.parse(b.start) >= w.s - MINUTE && Date.parse(b.end) <= w.e + MINUTE);
    };
    const sums = new Map();
    for (const b of blocks) {
        if (!b || !need.has(String(b.id)) || !inside(b)) continue;
        const kwh = (Number(b.power_w) || 0) * Math.max(0, Date.parse(b.end) - Date.parse(b.start)) / 3.6e9;
        sums.set(String(b.id), (sums.get(String(b.id)) || 0) + (Number.isFinite(kwh) ? kwh : 0));
    }
    const factor = new Map();
    for (const [id, sum] of sums) if (sum > need.get(id) * 1.001) factor.set(id, need.get(id) / sum);
    if (!factor.size) return blocks;
    return blocks.map((b) => (b && factor.has(String(b.id)) && inside(b) ? { ...b, power_w: (Number(b.power_w) || 0) * factor.get(String(b.id)) } : b));
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
    return out.map((r) => withProgress(r, nowMs));
}

/**
 * A run relative to now (#1321): a run with s <= now < e is "running" and only the
 * part from now on is ahead: (e - now) / (e - s) of its kWh. One reading for every screen.
 */
export function withProgress(run, nowMs) {
    const running = Number.isFinite(nowMs) && run.s <= nowMs && nowMs < run.e;
    return { ...run, running, ahead: running ? run.kwh * (run.e - nowMs) / (run.e - run.s) : run.kwh };
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
    return runs.map((r, i) => withProgress({ ...r, kwh: parts[i] }, nowMs));
}

/** kWh of the runs `pick` accepts still ahead of now (the rest of a run under way): the one figure every screen shows for a device (#1321). */
export function kwhAhead(plan, pick, nowMs = -Infinity) {
    return planRuns(plan, pick, nowMs).reduce((a, r) => a + r.ahead, 0);
}

/**
 * kWh the plan still has for a demand id and the kWh the demand still needs: { planned, needed }
 * (needed null when unknown). A block that has ended counts as done: it is not planned any more
 * and not needed any more, so a 0.2 kWh run in the past never reads as a gap (#1321).
 */
export function demandFigures(plan, id, nowMs = -Infinity) {
    const d = (plan && Array.isArray(plan.demands) ? plan.demands : []).find((x) => x && x.id === id);
    const need = d && Number.isFinite(Number(d.needed_kwh)) ? Number(d.needed_kwh) : null;
    const planned = kwhAhead(plan, (x) => x === id, nowMs);
    const needed = need === null ? null : Math.max(0, need - deliveredSincePlan(plan, id, nowMs));
    return { planned: Math.round(planned * 10) / 10, needed: needed === null ? null : Math.round(needed * 10) / 10 };
}

/**
 * kWh the plan's own blocks of a demand delivered between the plan being made and now.
 * The planner's needed_kwh is the REMAINING need at computed_at (target minus delivered),
 * so only what ran since then comes off it: never a block that ended before the plan was
 * made, and nothing at all without computed_at (#1321).
 */
function deliveredSincePlan(plan, id, nowMs) {
    const from = Date.parse(plan && plan.computed_at);
    if (!Number.isFinite(from) || !Number.isFinite(nowMs)) return 0;
    let kwh = 0;
    for (const b of (plan && Array.isArray(plan.blocks) ? plan.blocks : [])) {
        const s = Date.parse(b && b.start), e = Date.parse(b && b.end);
        if (!b || String(b.id) !== id || !Number.isFinite(s) || !Number.isFinite(e) || e <= s) continue;
        const a = Math.max(s, from), z = Math.min(e, nowMs);
        if (z > a) kwh += (Number(b.power_w) || 0) * (z - a) / 3.6e9;
    }
    return kwh;
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

/** A plan id that charges the house battery (not its output). */
export const isBatteryIn = (id) => /battery/.test(String(id)) && !String(id).startsWith('battery_out');

/**
 * When the plan has the battery full: the end of its last charging run, when the plan's
 * own end state is full. Null when the plan has no such time, so no screen guesses one (#1321).
 */
export function batteryFullAt(plan, nowMs = -Infinity) {
    const pct = Number(plan && plan.battery_end && plan.battery_end.pct);
    if (!(pct >= 99)) return null;
    const runs = planRuns(plan, isBatteryIn, nowMs);
    return runs.length ? runs[runs.length - 1].e : null;
}

/**
 * The run to name next: one under way (`running`, ends at `e`) or else the first that has not
 * started; null when none. Every "waits for" and "next" line reads this (#1321).
 */
export function nextRun(runs, nowMs) {
    const list = runs || [];
    return list.find((r) => r.s <= nowMs && nowMs < r.e) || list.find((r) => r.s > nowMs) || null;
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

/**
 * (#1408) The house's grid kWh per hour, { s (ms), kwh: [...] }, that the sensor sends when
 * the size trim drops the slots; null when it sent none. Hour i runs from s + i h.
 */
export function houseHours(plan) {
    const h = plan && plan.house_grid_hours;
    const s = h && typeof h.start === 'string' ? Date.parse(h.start) : NaN;
    return Number.isFinite(s) && Array.isArray(h.kwh) ? { s, kwh: h.kwh } : null;
}

/** (#1408) True when the house kWh can be cut to a window: the plan sent its slots or its hours. */
export function houseWindowed(plan) {
    return (Array.isArray(plan?.slots) && plan.slots.length > 0) || houseHours(plan) !== null;
}

/**
 * The house's own grid kWh inside [from, to): the slots when the plan has them; when the size
 * trim dropped them, its kWh per hour (an hour cut by the window counts by time, #1408); the
 * plan total only from a sensor that sends neither (one from before #1408).
 */
export function houseKwhIn(plan, from, to) {
    const slots = plan && Array.isArray(plan.slots) ? plan.slots : [];
    if (!slots.length) {
        const hours = houseHours(plan);
        if (hours) {
            let sum = 0;
            hours.kwh.forEach((k, i) => {
                const v = Number(k), s = hours.s + i * HOUR;
                const a = Math.max(s, from), z = Math.min(s + HOUR, to);
                if (v > 0 && z > a) sum += v * (z - a) / HOUR;
            });
            return sum;
        }
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

/**
 * (#1408) Where the plan has the battery cover the house: [{ s, e, first, last }] by time.
 * From `batt_runs` (slot indexes `first`..`last`) while the plan sends its slots; from
 * `batt_times` ([start, end], no indexes) when the size trim dropped them.
 */
export function battHouseRuns(plan) {
    const slots = plan && Array.isArray(plan.slots) ? plan.slots : [];
    const out = [];
    const push = (s, e, first, last) => { if (Number.isFinite(s) && Number.isFinite(e) && e > s) out.push({ s, e, first, last }); };
    if (slots.length) {
        for (const r of (Array.isArray(plan.batt_runs) ? plan.batt_runs : [])) {
            if (!Array.isArray(r) || !slots[r[0]] || !slots[r[1]]) continue;
            push(Date.parse(slots[r[0]].start), Date.parse(slots[r[1]].end), r[0], r[1]);
        }
        return out;
    }
    for (const r of (plan && Array.isArray(plan.batt_times) ? plan.batt_times : [])) {
        if (Array.isArray(r)) push(Date.parse(r[0]), Date.parse(r[1]), null, null);
    }
    return out;
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

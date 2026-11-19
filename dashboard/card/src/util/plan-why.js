/**
 * (#1321) "Why this plan": one line per planned device — what, when, why.
 * Pure. Takes the engine's own `why` on each plan demand; a device without
 * one keeps its block's reason code; then the not-scheduled list. At most `max` lines, the earliest first.
 */

import { kwhOf } from './next-lead.js';
import { planRuns, isBatteryIn } from './plan-facts.js';

export { isBatteryIn };

export const WHY_LINES_MAX = 4;

const hasBlocksFor = (plan, id) => (Array.isArray(plan.blocks) ? plan.blocks : []).some((b) => b && b.reason && String(b.id) === String(id));

/**
 * The reasons of one id's blocks, the one with the most energy first:
 * [{reason, params}], each reason once.
 */
export function blockReasons(blocks, id) {
    const by = new Map();
    for (const b of blocks || []) {
        if (!b || !b.reason || String(b.id) !== String(id)) continue;
        const kwh = (Number(b.power_w) || 0) * Math.max(0, Date.parse(b.end) - Date.parse(b.start)) / 3.6e9;
        const cur = by.get(b.reason) || { reason: b.reason, params: b.reason_params || {}, kwh: 0 };
        cur.kwh += kwh;
        by.set(b.reason, cur);
    }
    return [...by.values()].sort((a, b) => b.kwh - a.kwh).map(({ reason, params }) => ({ reason, params }));
}

/** blockReasons, each with the runs (planRuns shape) of the blocks that carry it: one reason per block. */
export function reasonRuns(blocks, id, nowMs) {
    return blockReasons(blocks, id).map((r) => ({
        ...r,
        runs: planRuns({ blocks: (blocks || []).filter((b) => b && String(b.id) === String(id) && b.reason === r.reason) }, () => true, nowMs),
    }));
}

/**
 * (#1321) Did a demand's runs sit in the cheapest hours of the plan's window? The planner
 * names its pick "cheapest hours" even when another demand held the cheapest slots (its
 * headroom was full). The slots tell: the cheapest hours the same length are compared with
 * the average price the demand got. Null when the slots cannot answer.
 */
export function gotCheapest(plan, runs, price, nowMs, upcoming = []) {
    const p = Number(price);
    const hours = (runs || []).reduce((a, r) => a + (r.e - r.s) / 3.6e6, 0);
    if (!Number.isFinite(p) || price === null || price === '' || !(hours > 0)) return null;
    const slots = priceCells(plan, upcoming)
        .filter((x) => x.e > nowMs)
        .sort((a, b) => a.price - b.price);
    if (!slots.length) return null;
    let need = hours, cost = 0;
    for (const x of slots) {
        const take = Math.min(need, x.h);
        cost += take * x.price; need -= take;
        if (need <= 1e-9) break;
    }
    if (need > 1e-9) return null;
    return p <= cost / hours + PRICE_EPS;
}

const num = (v) => (v === null || v === undefined || v === '' ? NaN : Number(v));
/**
 * The tariff's own prices as {h, price, e}: its upcoming list (the one the Now price
 * strip reads) first, the plan's slots when that is empty. The live plan sensor drops
 * its slots (timeline_omitted), so the tariff is the source that is always there.
 * (#1321) A cell lasts until the next timestamp (the provider's own interval, hourly or
 * quarter-hourly); the last one lasts the median gap.
 */
function priceCells(plan, upcoming) {
    const pts = (Array.isArray(upcoming) ? upcoming : []).map((u) => ({ s: Date.parse(u?.t), price: num(u?.price) }))
        .filter((x) => Number.isFinite(x.s) && Number.isFinite(x.price)).sort((a, b) => a.s - b.s);
    const gaps = pts.slice(1).map((x, i) => x.s - pts[i].s).filter((g) => g > 0).sort((a, b) => a - b);
    const median = gaps.length ? gaps[Math.floor(gaps.length / 2)] : 0;
    // a gap in the list (a missing hour) must not stretch one cell across it: cap at twice the median gap
    const cap = median ? median * 2 : Infinity;
    const ups = pts.map((x, i) => ({ ...x, e: x.s + (i + 1 < pts.length ? Math.min(pts[i + 1].s - x.s, cap) : median) }))
        .map((x) => ({ ...x, h: (x.e - x.s) / 3.6e6 }));
    const slots = (Array.isArray(plan?.slots) ? plan.slots : [])
        .map((x) => ({ s: Date.parse(x.start), e: Date.parse(x.end), price: num(x.price) }))
        .map((x) => ({ ...x, h: (x.e - x.s) / 3.6e6 }));
    const usable = (x) => x.h > 0 && Number.isFinite(x.price) && Number.isFinite(x.s);
    const own = ups.filter(usable);
    return own.length ? own : slots.filter(usable);
}
const PRICE_EPS = 0.002;

/** (#1321) A battery block named "cheapest hours" that did not get them says "cheap hours". */
const leftCheap = (plan, r, nowMs, upcoming) => (r.reason === 'cheapest_hours'
    && gotCheapest(plan, r.runs, r.params?.price, nowMs, upcoming) === false ? { ...r, reason: 'cheap_hours' } : r);

/**
 * [{id, start, end, reason, params, why, kwh, label}]: `reason`/`params` is
 * the block's reason code, `why` the not-scheduled code. Times are ISO.
 */
export function whyLines(plan, nowMs = Date.now(), max = WHY_LINES_MAX, upcoming = []) {
    if (!plan) return [];
    // The engine's own word first: each plan demand carries
    // `why: {code, params: {from, to, price?}}` (one line per device).
    const own = new Map();
    for (const d of (Array.isArray(plan.demands) ? plan.demands : [])) {
        const w = d && d.why;
        if (!d || !d.id || !w || !w.code) continue;
        // (#1321) the battery's reasons come from its blocks only: the chart names those
        if (isBatteryIn(d.id) && hasBlocksFor(plan, d.id)) continue;
        const p = w.params || {};
        // a window that has ended is history, not a plan
        const endMs = Date.parse(p.to);
        if (Number.isFinite(endMs) && endMs <= nowMs) continue;
        own.set(String(d.id), {
            id: String(d.id), start: p.from || '', end: p.to || '',
            reason: '', params: p, why: '', code: String(w.code),
            kwh: Number(d.planned_kwh) || 0, label: d.label || '',
        });
    }
    const blocks = (Array.isArray(plan.blocks) ? plan.blocks : [])
        .filter((b) => b && b.id && Number.isFinite(Date.parse(b.start)) && Date.parse(b.end) > nowMs);
    const byId = new Map();
    for (const b of blocks) {
        const id = String(b.id);
        if (id.startsWith('battery_out')) continue;   // the house's own draw is not a planned step
        const s = Date.parse(b.start), e = Date.parse(b.end);
        const cur = byId.get(id);
        if (!cur) byId.set(id, { id, s, e, reason: b.reason || '', params: b.reason_params || {} });
        else {
            if (s < cur.s) { cur.s = s; if (b.reason) { cur.reason = b.reason; cur.params = b.reason_params || {}; } }
            if (e > cur.e) cur.e = e;
        }
    }
    // a device the engine gave no why keeps the block's own reason
    const fromBlocks = [...byId.values()].filter((x) => !own.has(x.id)).map((x) => ({
        id: x.id, start: new Date(x.s).toISOString(), end: new Date(x.e).toISOString(),
        reason: String(x.reason), params: x.params, why: '', code: '', label: '',
        reasons: isBatteryIn(x.id) ? reasonRuns(blocks, x.id, nowMs).map((r) => leftCheap(plan, r, nowMs, upcoming)) : null,
        kwh: kwhOf(blocks, (i) => String(i) === x.id), s: x.s,
        runs: planRuns(plan, (i) => String(i) === x.id, nowMs),
    })).map((x) => ({ ...x, kwh: x.runs.length ? x.runs.reduce((a, r) => a + r.kwh, 0) : x.kwh }));
    // (#1321) every line names its own runs: a gap between two stays a gap, and the kWh is theirs
    const withRuns = (x) => {
        const runs = planRuns(plan, (i) => i === x.id, nowMs);
        // (#1321) the cheapest hours were not all free to this demand: say "left", never "the cheapest"
        const code = x.code === 'cheapest_hours' && gotCheapest(plan, runs, x.params?.price, nowMs, upcoming) === false ? 'cheapest_left' : x.code;
        return runs.length ? { ...x, code, runs, kwh: runs.reduce((a, r) => a + r.kwh, 0) } : x;
    };
    const planned = [...own.values()].map(withRuns).map((x) => ({ ...x, s: Date.parse(x.start) }))
        .concat(fromBlocks)
        .sort((a, b) => (Number.isFinite(a.s) ? a.s : Infinity) - (Number.isFinite(b.s) ? b.s : Infinity))
        .map(({ s: _s, ...rest }) => rest);
    const known = new Set(planned.map((x) => x.id));
    // (#1321) one line per device: a heater planned under Keep at run (comfort:x)
    // is not also "not scheduled" under its run time (load:x)
    const device = (id) => String(id).replace(/^(load|comfort):/, '');
    const plannedDevices = new Set(planned.filter((x) => /^(load|comfort):/.test(x.id)).map((x) => device(x.id)));
    const left = (Array.isArray(plan.not_scheduled) ? plan.not_scheduled : [])
        .filter((n) => n && n.id && !known.has(String(n.id))
            && !(/^(load|comfort):/.test(String(n.id)) && plannedDevices.has(device(n.id))))
        .map((n) => ({ id: String(n.id), start: '', end: '', reason: '', params: {}, why: String(n.why || n.reason || ''), code: '', kwh: 0, label: n.label || '' }));
    return [...planned, ...left].slice(0, max);
}

/**
 * The battery the plan expects at its end: `{pct, kwh, at}` from the
 * engine's `battery_end`, or null. `pct` must be a real 0–100 number.
 */
export function batteryEnd(plan) {
    const b = plan && plan.battery_end;
    if (!b || typeof b !== 'object') return null;
    const v = b.pct;
    if (v === null || v === undefined || v === '') return null;
    const pct = Number(v);
    if (!Number.isFinite(pct) || pct < 0 || pct > 100) return null;
    const kwh = Number(b.kwh);
    return { pct, kwh: Number.isFinite(kwh) ? kwh : null, at: b.at || '' };
}

/**
 * (#1321) What SEM paid per bought kWh against the hours' own average price,
 * for an Insights period. The engine puts `avg_price_paid` / `avg_price_hours`
 * on sensor.sem_daily_costs / _monthly_costs / _yearly_costs, dynamic
 * tariffs only. `{paid, hours, entity}` or null (other periods, or absent).
 */
export const AVG_PRICE_SENSOR = { day: 'sensor.sem_daily_costs', month: 'sensor.sem_monthly_costs', year: 'sensor.sem_yearly_costs' };
export function avgPriceFor(states, period) {
    const entity = AVG_PRICE_SENSOR[period];
    if (!entity) return null;
    const a = states?.[entity]?.attributes || {};
    const num = (v) => (v === null || v === undefined || v === '' ? NaN : Number(v));
    const paid = num(a.avg_price_paid), hours = num(a.avg_price_hours);
    if (!Number.isFinite(paid)) return null;
    return { paid, hours: Number.isFinite(hours) ? hours : null, entity };
}

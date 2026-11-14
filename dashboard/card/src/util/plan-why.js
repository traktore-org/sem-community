/**
 * (#1321) "Why this plan": one line per planned device — what, when, why.
 * Pure. Takes the engine's own `why` on each plan demand; a device without
 * one keeps its block's reason code; then the not-scheduled list. At most `max` lines, the earliest first.
 */

import { kwhOf } from './next-lead.js';

export const WHY_LINES_MAX = 4;

/**
 * [{id, start, end, reason, params, why, kwh, label}]: `reason`/`params` is
 * the block's reason code, `why` the not-scheduled code. Times are ISO.
 */
export function whyLines(plan, nowMs = Date.now(), max = WHY_LINES_MAX) {
    if (!plan) return [];
    // The engine's own word first: each plan demand carries
    // `why: {code, params: {from, to, price?}}` (one line per device).
    const own = new Map();
    for (const d of (Array.isArray(plan.demands) ? plan.demands : [])) {
        const w = d && d.why;
        if (!d || !d.id || !w || !w.code) continue;
        const p = w.params || {};
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
        kwh: kwhOf(blocks, (i) => String(i) === x.id), s: x.s,
    }));
    const planned = [...own.values()].map((x) => ({ ...x, s: Date.parse(x.start) }))
        .concat(fromBlocks)
        .sort((a, b) => (Number.isFinite(a.s) ? a.s : Infinity) - (Number.isFinite(b.s) ? b.s : Infinity))
        .map(({ s: _s, ...rest }) => rest);
    const known = new Set(planned.map((x) => x.id));
    const left = (Array.isArray(plan.not_scheduled) ? plan.not_scheduled : [])
        .filter((n) => n && n.id && !known.has(String(n.id)))
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

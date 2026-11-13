/**
 * (#1321) "Why this plan": one line per planned device — what, when, why.
 * Pure. Takes the engine's own `why_lines` when the plan publishes them;
 * otherwise derives them from the plan's blocks (their reason codes) and
 * the not-scheduled list. At most `max` lines, the earliest first.
 */

import { kwhOf } from './next-lead.js';

export const WHY_LINES_MAX = 4;

/**
 * [{id, start, end, reason, params, why, kwh, label}]: `reason`/`params` is
 * the block's reason code, `why` the not-scheduled code. Times are ISO.
 */
export function whyLines(plan, nowMs = Date.now(), max = WHY_LINES_MAX) {
    if (!plan) return [];
    if (Array.isArray(plan.why_lines)) {
        return plan.why_lines.filter((x) => x && x.id).slice(0, max).map((x) => ({
            id: String(x.id), start: x.start || '', end: x.end || '',
            reason: String(x.code || x.reason || ''), params: x.params || x.reason_params || {},
            why: '', kwh: Number(x.kwh) || 0, label: x.label || '',
        }));
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
    const planned = [...byId.values()].sort((a, b) => a.s - b.s).map((x) => ({
        id: x.id, start: new Date(x.s).toISOString(), end: new Date(x.e).toISOString(),
        reason: String(x.reason), params: x.params, why: '', label: '',
        kwh: kwhOf(blocks, (i) => String(i) === x.id),
    }));
    const left = (Array.isArray(plan.not_scheduled) ? plan.not_scheduled : [])
        .filter((n) => n && n.id && !byId.has(String(n.id)))
        .map((n) => ({ id: String(n.id), start: '', end: '', reason: '', params: {}, why: String(n.why || n.reason || ''), kwh: 0, label: n.label || '' }));
    return [...planned, ...left].slice(0, max);
}

/** The battery level the plan expects at its end, in %, or null (engine key `battery_end_soc_pct`). */
export function batteryEndPct(plan) {
    const v = plan ? plan.battery_end_soc_pct : null;
    if (v === null || v === undefined || v === '') return null;
    const n = Number(v);
    return Number.isFinite(n) && n >= 0 && n <= 100 ? n : null;
}

/**
 * (#755, #800, #1321) What last night's record shows, as rows. Pure.
 *
 * The coordinator publishes `review` on the plan sensor as CODES (never prose):
 * one verdict per demand, one for the battery's night, one for the share of
 * the sun kept. `say(code, params)` turns a code into the user's sentence and
 * gives '' for a code it has no text for, so a row is dropped, never shown as
 * a bare key. The viewer's clock formats the "full again by" time.
 */

import { fmtNum } from './next-number.js';

const PREFIX = 'energy_plan_review_';
// (#1321) Next words for the codes whose classic text is vague: who is learning, what is kept
const NEXT_CODE = { learning: 'next_review_learning', sc_beat: 'next_review_sc_beat', sc_met: 'next_review_sc_met', sc_missed: 'next_review_sc_missed' };
const wording = (code) => NEXT_CODE[code] || PREFIX + code;
const fix = (v, d = 1) => (v == null || !Number.isFinite(Number(v)) ? '' : fmtNum(v, d));

/** → [{ kind: 'ev'|'load'|'battery'|'sun', id?, label?, text }] */
export function reviewRows(rv, say, clock = (ts) => String(ts), nights = {}) {
    if (!rv || typeof rv !== 'object') return [];
    const rows = [];
    for (const d of Array.isArray(rv.demands) ? rv.demands : []) {
        const text = say(wording(d.code), {
            // (#1321) the learner's own count, out of what it needs: one source, no other night count
            nights: d.nights, needed: d.needed || 5, asked: fix(d.asked_kwh || 0), suggested: fix(d.suggested_kwh), actual: fix(d.last_kwh || 0),
        });
        if (text) rows.push({ kind: d.kind === 'ev' ? 'ev' : d.kind === 'battery' ? 'batteryplan' : d.kind === 'comfort' ? 'heater' : 'load', id: d.demand_id, label: d.label, text });
    }
    const b = rv.battery;
    const bt = b ? say(PREFIX + b.code, {
        drained: fix(b.drained || 0), clipped: fix(b.clipped_h || 0), full_at: b.full_at_ts ? clock(b.full_at_ts * 1000) : '',
    }) : '';
    if (bt) rows.push({ kind: 'battery', text: bt });
    const s = rv.self_consumption;
    const st = s ? say(wording(s.code), {
        actual: Math.round((s.actual_share || 0) * 100), predicted: Math.round((s.predicted_share || 0) * 100),
    }) : '';
    if (st) rows.push({ kind: 'sun', text: st });
    return rows;
}

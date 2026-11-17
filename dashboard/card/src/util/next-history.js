/**
 * (#1321) History for the Insights screen.
 *
 * Pure parts (tested in test/next-history.test.js):
 *   bucketsFor(period, now, o)      the window of one period and its buckets
 *   diffCumulative(values)          per-bucket increments of a daily counter
 *   bucketValues(points, buckets, kind)  one number per bucket
 *   sunCurve(kwh, nightEnd, nightStart)  24 hourly kW that add up to kwh
 *   stackModel / lineModel / smooth SVG geometry; the card only draws
 *
 * One fetch:
 *   fetchSeries(hass, ids, startIso, endIso, period)  recorder statistics
 *   over the websocket, the same call sem-chart-card makes, cached five
 *   minutes per request. A missing id comes back as an empty list.
 *
 * SEM's daily and flow energy sensors are state class TOTAL and reset at
 * midnight: a bucket's last `state` is the counter at the end of it. Per
 * day that is the day's total; per hour the hours are differenced.
 */
import { startOfDayInHaTz } from './time-zone.js';

export const PERIOD_KEYS = ['day', 'yesterday', 'week', 'month', 'year'];
const HOUR = 3600e3;
const CACHE_MS = 5 * 60e3;

const pad = (n) => String(n).padStart(2, '0');
const sameDay = (a, b) => a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
const addDays = (d, n) => { const x = new Date(d.getTime()); x.setDate(x.getDate() + n); return x; };

function dayName(d, lang) {
    try { return d.toLocaleDateString(lang || 'en', { weekday: 'short' }); }
    catch (_e) { return d.toLocaleDateString('en', { weekday: 'short' }); }
}
function monthName(d, lang) {
    try { return d.toLocaleDateString(lang || 'en', { month: 'short' }); }
    catch (_e) { return d.toLocaleDateString('en', { month: 'short' }); }
}

/**
 * bucketsFor('day' | 'yesterday' | 'week' | 'month' | 'year', now, { tz, lang })
 * → { period: 'hour' | 'day' | 'month', start, end, spanEnd, starts, labels,
 *     highlightIndex, n }
 *
 * `end` stops at now so a fetch never asks for the future; `spanEnd` is the
 * period's real end. `starts` are bucket start times in ms. A label is ''
 * where the axis stays quiet.
 */
export function bucketsFor(period, now = new Date(), o = {}) {
    const today0 = startOfDayInHaTz(now, o.tz);
    const starts = [], labels = [];
    let start, spanEnd, bucket, hi = -1;
    if (period === 'day' || period === 'yesterday') {
        start = period === 'day' ? today0 : addDays(today0, -1);
        spanEnd = addDays(start, 1);
        bucket = 'hour';
        for (let h = 0; h < 24; h++) {
            starts.push(start.getTime() + h * HOUR);
            labels.push(h % 6 === 0 ? pad(h) : '');
        }
        if (period === 'day') hi = Math.max(0, Math.min(23, Math.floor((now.getTime() - start.getTime()) / HOUR)));
    } else if (period === 'week') {
        const dow = today0.getDay() || 7;
        start = addDays(today0, -(dow - 1));
        spanEnd = addDays(start, 7);
        bucket = 'day';
        for (let i = 0; i < 7; i++) {
            const d = addDays(start, i);
            starts.push(d.getTime());
            labels.push(dayName(d, o.lang));
            if (sameDay(d, today0)) hi = i;
        }
    } else if (period === 'month') {
        start = new Date(today0.getTime()); start.setDate(1);
        spanEnd = new Date(start.getTime()); spanEnd.setMonth(spanEnd.getMonth() + 1);
        bucket = 'day';
        const n = Math.round((spanEnd.getTime() - start.getTime()) / 864e5);
        for (let i = 0; i < n; i++) {
            const d = addDays(start, i);
            starts.push(d.getTime());
            labels.push(i === 0 || (i + 1) % 5 === 0 ? String(i + 1) : '');
            if (sameDay(d, today0)) hi = i;
        }
    } else {
        start = new Date(today0.getTime()); start.setMonth(0, 1);
        spanEnd = new Date(start.getTime()); spanEnd.setFullYear(spanEnd.getFullYear() + 1);
        bucket = 'month';
        for (let m = 0; m < 12; m++) {
            const d = new Date(start.getTime()); d.setMonth(m);
            starts.push(d.getTime());
            labels.push(monthName(d, o.lang));
            if (m === today0.getMonth()) hi = m;
        }
    }
    const end = spanEnd.getTime() > now.getTime() ? new Date(now.getTime()) : spanEnd;
    return { period: bucket, start, end, spanEnd, starts, labels, highlightIndex: hi, n: starts.length };
}

/** The statistics period to ask for: totals need day rows summed into a month. */
export function fetchPeriodFor(buckets, kind) {
    return kind === 'total' && buckets.period === 'month' ? 'day' : buckets.period;
}

/** Index of the bucket whose start is nearest to `ts`, or -1 outside the window. */
export function nearestIndex(ts, starts) {
    if (!starts.length || !Number.isFinite(ts)) return -1;
    let best = 0, dist = Math.abs(ts - starts[0]);
    for (let i = 1; i < starts.length; i++) {
        const d = Math.abs(ts - starts[i]);
        if (d < dist) { best = i; dist = d; }
    }
    const step = starts.length > 1 ? starts[1] - starts[0] : HOUR;
    return dist <= step * 0.75 ? best : -1;
}

/** Increments of a counter that resets: a drop means the counter started over. */
export function diffCumulative(values) {
    const out = [];
    let prev = null;
    for (const raw of values || []) {
        const v = Number(raw);
        if (!Number.isFinite(v)) { out.push(0); continue; }
        if (prev === null || v < prev) out.push(Math.max(0, v));
        else out.push(v - prev);
        prev = v;
    }
    return out;
}

/**
 * One number per bucket. `points` are recorder rows {start, state, mean}
 * (`start` as ms or ISO). kind 'total' reads the counter's last state per
 * row, differencing hour rows; kind 'mean' averages the means that land in
 * a bucket. A bucket nobody wrote is null, so a chart can tell "0" from
 * "not yet".
 */
export function bucketValues(points, buckets, kind = 'total') {
    const n = buckets.starts.length;
    const sums = new Array(n).fill(null), counts = new Array(n).fill(0);
    const rows = (points || [])
        .map((p) => ({ t: typeof p.start === 'number' ? p.start : Date.parse(p.start), p }))
        .filter((r) => Number.isFinite(r.t))
        .sort((a, b) => a.t - b.t);
    let vals;
    if (kind === 'total') {
        const states = rows.map((r) => r.p.state ?? r.p.max ?? r.p.mean);
        vals = buckets.period === 'hour' ? diffCumulative(states) : states.map((s) => (Number.isFinite(Number(s)) ? Math.max(0, Number(s)) : 0));
    } else {
        vals = rows.map((r) => r.p.mean ?? r.p.state ?? r.p.max);
    }
    rows.forEach((r, i) => {
        const v = Number(vals[i]);
        if (!Number.isFinite(v)) return;
        const idx = nearestIndex(r.t, buckets.starts);
        if (idx < 0) return;
        sums[idx] = (sums[idx] || 0) + v;
        counts[idx] += 1;
    });
    if (kind === 'mean') return sums.map((s, i) => (counts[i] ? s / counts[i] : null));
    return sums;
}

/** Hourly kW for a day that gives `kwh` between two 'HH:MM' clocks, a sine. */
export function sunCurve(kwh, nightEnd, nightStart) {
    const h = (s) => { const m = /^(\d{1,2}):(\d{2})/.exec(String(s || '')); return m ? Number(m[1]) + Number(m[2]) / 60 : null; };
    const up = h(nightEnd), down = h(nightStart);
    const out = new Array(24).fill(0);
    const total = Number(kwh);
    if (!Number.isFinite(total) || total <= 0 || up === null || down === null || down <= up) return out;
    let sum = 0;
    for (let i = 0; i < 24; i++) {
        const c = i + 0.5;
        if (c <= up || c >= down) continue;
        out[i] = Math.sin(Math.PI * (c - up) / (down - up));
        sum += out[i];
    }
    return sum > 0 ? out.map((v) => v * total / sum) : out;
}

/** Catmull-Rom through the points as cubic Beziers; the mockup's smooth(). */
export function smooth(pts) {
    if (!pts.length) return '';
    if (pts.length < 3) return pts.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join(' ');
    let d = 'M' + pts[0][0].toFixed(1) + ' ' + pts[0][1].toFixed(1);
    for (let i = 0; i < pts.length - 1; i++) {
        const p0 = pts[Math.max(0, i - 1)], p1 = pts[i], p2 = pts[i + 1], p3 = pts[Math.min(pts.length - 1, i + 2)];
        const c1 = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6];
        const c2 = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6];
        d += ' C' + c1[0].toFixed(1) + ' ' + c1[1].toFixed(1) + ' ' + c2[0].toFixed(1) + ' ' + c2[1].toFixed(1) + ' ' + p2[0].toFixed(1) + ' ' + p2[1].toFixed(1);
    }
    return d;
}

const num = (v) => (Number.isFinite(Number(v)) ? Number(v) : 0);
const gridText = (g) => (g >= 10 ? String(Math.round(g)) : g.toFixed(1));

/** A round axis top: 5-steps above 5, else 1-steps, never 0. */
function niceMax(v) {
    if (!(v > 0)) return 1;
    if (v > 5) return Math.ceil(v / 5) * 5;
    return Math.ceil(v);
}

/**
 * stackModel(series, colors, labels, w, h, highlightIndex, { unit })
 * series = [[v0, v1, …], …] one array per layer, each as long as labels.
 * → { w, h, empty, max, grid, bars, labels, totals, slots }
 */
export function stackModel(series, colors, labels, w = 600, h = 150, highlightIndex = -1, o = {}) {
    const n = labels.length;
    const L = 6, B = 22, T = 14;
    const totals = labels.map((_, i) => series.reduce((a, s) => a + Math.max(0, num(s[i])), 0));
    const empty = !series.length || !totals.some((t) => t > 0);
    const max = niceMax(Math.max(...totals, 0));
    const bw = (w - L * 2) / Math.max(1, n);
    const y = (v) => T + (h - T - B) * (1 - v / max);
    const unit = o.unit || '';
    const grid = [max / 2, max].map((g) => ({ y: y(g), text: gridText(g) + (unit ? ' ' + unit : '') }));
    const bars = [], labelOut = [], totalOut = [], slots = [];
    labels.forEach((lab, i) => {
        let acc = 0;
        const x = L + i * bw + bw * 0.2, ww = Math.max(2, bw * 0.6);
        const dim = highlightIndex >= 0 && i !== highlightIndex ? 0.6 : 1;
        slots.push({ x: L + i * bw, w: bw, i });
        series.forEach((sr, k) => {
            const v0 = Math.max(0, num(sr[i]));
            if (v0 <= 0) return;
            const y1 = y(acc + v0), y0 = y(acc);
            bars.push({ x, y: y1 + (k ? 1 : 0), w: ww, h: Math.max(0, y0 - y1 - (k ? 1 : 0) - 1),
                rx: k === series.length - 1 ? 3 : 1, color: colors[k] || colors[0], opacity: dim, i, k });
            acc += v0;
        });
        if (lab) labelOut.push({ x: x + ww / 2, y: h - 6, text: lab, strong: i === highlightIndex });
        if (totals[i] > 0 && (n <= 12 || i === highlightIndex)) {
            totalOut.push({ x: x + ww / 2, y: y(totals[i]) - 4, text: totals[i] >= 10 ? String(Math.round(totals[i])) : totals[i].toFixed(1) });
        }
    });
    return { w, h, empty, max, grid, bars, labels: labelOut, totals: totalOut, slots, sums: totals };
}

/**
 * lineModel(series, w, h, { labels, unit, max, hover })
 * series = [{ v: [...], color, area, dash }], every v as long as the first.
 * A null value breaks nothing: it is left out of the path.
 * → { w, h, empty, max, grid, paths, xs, ticks, y0, hover }
 */
export function lineModel(series, w = 600, h = 150, o = {}) {
    const L = 6, B = 18, T = 10;
    const n = Math.max(0, ...series.map((s) => (s.v || []).length));
    const all = series.flatMap((s) => (s.v || []).filter((v) => v !== null && Number.isFinite(Number(v))).map(Number));
    const empty = !all.length || !all.some((v) => v > 0);
    const max = o.max || niceMax(Math.max(...all, 0) * 1.05);
    const x = (i) => L + (n > 1 ? i / (n - 1) : 0.5) * (w - L * 2);
    const y = (v) => T + (h - T - B) * (1 - Math.max(0, Math.min(max, v)) / max);
    const unit = o.unit || '';
    const grid = [max / 2, max * 0.95].map((g) => ({ y: y(g), text: gridText(g) + (unit ? ' ' + unit : '') }));
    const paths = series.map((sr) => {
        const pts = (sr.v || []).map((v, i) => (v === null || !Number.isFinite(Number(v)) ? null : [x(i), y(Number(v))])).filter(Boolean);
        const d = smooth(pts);
        const area = sr.area && pts.length ? d + ' L' + pts[pts.length - 1][0].toFixed(1) + ' ' + y(0).toFixed(1) + ' L' + pts[0][0].toFixed(1) + ' ' + y(0).toFixed(1) + ' Z' : null;
        return { d, area, color: sr.color, dash: !!sr.dash };
    });
    const ticks = [];
    (o.labels || []).forEach((lab, i) => {
        if (!lab) return;
        ticks.push({ x: x(i), y: h - 4, text: lab, anchor: i === 0 ? 'start' : i === n - 1 ? 'end' : 'middle' });
    });
    const xs = Array.from({ length: n }, (_, i) => x(i));
    const hover = Number.isInteger(o.hover) && o.hover >= 0 && o.hover < n ? { x: x(o.hover), i: o.hover } : null;
    return { w, h, empty, max, grid, paths, xs, ticks, y0: y(0), top: T, hover };
}

// ── the one fetch ──
const _cache = new Map();

/** Drop what is older than five minutes; a test may call it to start clean. */
export function clearSeriesCache() { _cache.clear(); }

/**
 * fetchSeries(hass, ids, startIso, endIso, period) → { [id]: [{start, state, mean, max, sum}] }
 * period: 'hour' | 'day' | 'month'. The same request inside five minutes is
 * served from memory. recorder/statistics_during_period first, the older
 * history/… name when that fails (copied from sem-chart-card).
 */
export async function fetchSeries(hass, ids, startIso, endIso, period, o = {}) {
    const list = (ids || []).filter(Boolean);
    if (!hass?.callWS || !list.length) return {};
    const key = [period, startIso, endIso, list.join(',')].join('|');
    const now = o.now || Date.now();
    const hit = _cache.get(key);
    if (hit && now - hit.at < CACHE_MS) return hit.data;
    const units = { power: 'W', energy: 'kWh' };
    let stats;
    try {
        stats = await hass.callWS({
            type: 'recorder/statistics_during_period',
            start_time: startIso, end_time: endIso,
            statistic_ids: list, period, types: ['state', 'mean', 'max', 'sum'], units,
        });
    } catch (_e) {
        stats = await hass.callWS({
            type: 'history/statistics_during_period',
            start_time: startIso, end_time: endIso,
            statistic_ids: list, period, units,
        });
    }
    const data = {};
    for (const id of list) data[id] = Array.isArray(stats?.[id]) ? stats[id] : [];
    _cache.set(key, { at: now, data });
    return data;
}

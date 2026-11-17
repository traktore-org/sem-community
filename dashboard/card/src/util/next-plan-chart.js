/**
 * (#1321) The Plan screen's chart: sun, price and plan on one clock.
 *
 * Pure: readings in, three lanes out, every time in ms. The card only maps
 * ms to x and draws. Nothing is invented: no forecast hours give no future
 * sun curve, an unknown price stays unknown, a block outside the window is
 * dropped. Times of day follow the home's time zone.
 */

import { planIdName, planIdParts } from './plan-ids.js';

const HOUR = 3600e3;
const CELL = 15 * 60e3;

export const RANGES = ['today', 'next', 'tomorrow'];

/** Minutes the zone is ahead of UTC at `ms` (DST-aware via Intl). */
export function zoneOffsetMin(ms, tz) {
    try {
        const f = new Intl.DateTimeFormat('en-US', { timeZone: tz || undefined, hourCycle: 'h23',
            year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' });
        const p = Object.fromEntries(f.formatToParts(new Date(ms)).map((x) => [x.type, x.value]));
        const asUtc = Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour % 24, +p.minute, +p.second);
        return Math.round((asUtc - Math.floor(ms / 1000) * 1000) / 60e3);
    } catch (e) {
        return -new Date(ms).getTimezoneOffset();
    }
}

/** 00:00 of the home's day containing `ms`, plus `days`, as ms. */
export function zonedMidnight(ms, tz, days = 0) {
    const off = zoneOffsetMin(ms, tz);
    const local = new Date(ms + off * 60e3);
    let guess = Date.UTC(local.getUTCFullYear(), local.getUTCMonth(), local.getUTCDate() + days) - off * 60e3;
    // across a DST change the offset at the target differs: one correction is enough
    const off2 = zoneOffsetMin(guess, tz);
    if (off2 !== off) guess += (off - off2) * 60e3;
    return guess;
}

/** The hour of the day (0–23) at `ms` in the home's zone. */
export function zonedHour(ms, tz) {
    return Math.floor((((ms + zoneOffsetMin(ms, tz) * 60e3) % (24 * HOUR)) + 24 * HOUR) % (24 * HOUR) / HOUR);
}

/** The window for a range: today and tomorrow are 00–24, next is now−2 h → +22 h. */
export function chartWindow(nowMs, range, tz) {
    if (range === 'today') { const s = zonedMidnight(nowMs, tz); return { start: s, end: zonedMidnight(nowMs, tz, 1) }; }
    if (range === 'tomorrow') { return { start: zonedMidnight(nowMs, tz, 1), end: zonedMidnight(nowMs, tz, 2) }; }
    const s = Math.floor(nowMs / HOUR) * HOUR - 2 * HOUR;
    return { start: s, end: s + 24 * HOUR };
}

/** Ticks every `every` hours on the home clock; `day` marks a midnight inside the window. */
export function chartTicks(win, tz, every = 3) {
    const out = [];
    for (let t = Math.ceil(win.start / HOUR) * HOUR; t <= win.end; t += HOUR) {
        const h = zonedHour(t, tz);
        if (h % every !== 0) continue;
        out.push({ t, label: String(h).padStart(2, '0'), midnight: h === 0 && t > win.start && t < win.end });
    }
    return out;
}

const num = (v) => (v === null || v === undefined || v === '' ? NaN : Number(v));

/**
 * The sun lane. actual: [{ t: ms of the hour start, w: mean W }] from the
 * recorder's hourly statistics; forecast: { iso period start: Wh } from the
 * forecast command (a key holds until the next key). Past whole hours are
 * the actual; what comes after the last actual hour is the forecast.
 * → { points: [{ s, e, kw, kwh, actual }], totalKwh, peak, hasForecast }
 */
export function sunModel({ win, nowMs, actual = [], forecast = {} }) {
    const pts = [];
    let lastActualEnd = win.start;
    for (const a of actual) {
        const s = num(a.t), w = num(a.w);
        if (!Number.isFinite(s) || !Number.isFinite(w)) continue;
        const e = s + HOUR;
        if (e > nowMs || e <= win.start || s >= win.end) continue;
        pts.push({ s, e, kw: Math.max(0, w) / 1000, kwh: Math.max(0, w) / 1000, actual: true });
        lastActualEnd = Math.max(lastActualEnd, e);
    }
    const keys = Object.keys(forecast || {}).map((k) => [Date.parse(k), num(forecast[k])])
        .filter(([t, v]) => Number.isFinite(t) && Number.isFinite(v)).sort((p, q) => p[0] - q[0]);
    const gaps = keys.slice(1).map((k, i) => k[0] - keys[i][0]).filter((g) => g > 0).sort((p, q) => p - q);
    // the period length: the most common gap (an odd first key, e.g. at sunrise, is not the step;
    // a day jump between two keys is not a period either)
    const counts = new Map();
    for (const g of gaps) if (g <= HOUR) counts.set(g, (counts.get(g) || 0) + 1);
    const step = counts.size ? [...counts.entries()].sort((p, q) => q[1] - p[1] || p[0] - q[0])[0][0] : HOUR;
    let hasForecast = false;
    keys.forEach(([s, wh], i) => {
        const e = i + 1 < keys.length ? Math.min(keys[i + 1][0], s + 2 * step) : s + step;
        if (e <= s || e <= win.start || s >= win.end) return;
        if (e <= lastActualEnd) return;   // the measured hours win
        const h = (e - s) / HOUR;
        pts.push({ s, e, kw: Math.max(0, wh) / 1000 / h, kwh: Math.max(0, wh) / 1000, actual: false });
        hasForecast = true;
    });
    pts.sort((p, q) => p.s - q.s);
    const totalKwh = pts.reduce((a, p) => {
        const ov = Math.max(0, Math.min(p.e, win.end) - Math.max(p.s, win.start)) / (p.e - p.s);
        return a + p.kwh * ov;
    }, 0);
    const peak = pts.reduce((a, p) => (!a || p.kw > a.kw ? p : a), null);
    return { points: pts, totalKwh, peak: peak && peak.kw > 0 ? peak : null, hasForecast };
}

/**
 * The price lane. upcoming: [{ t, price }] 15-min slots; slots: the plan's
 * [{ start, end, price }]; schedule: [{ start 'HH:MM', end, avg_price }] for
 * today. The first source that covers a 15-minute cell wins.
 * → { flat, price, steps: [{ s, e, p }], gaps: [{ s, e }], min, max, avg }
 */
export function priceModel({ win, tz, nowMs, upcoming = [], slots = [], schedule = [], past = [], isDynamic, level, todayAvg }) {
    const sources = [];
    // what the tariff sensor really read, hour by hour (recorder means): the past only
    for (const h of past || []) {
        const s = num(h?.t), p = num(h?.p);
        if (Number.isFinite(s) && Number.isFinite(p) && s < nowMs) sources.push([s, s + HOUR, p, 0.5]);
    }
    for (const u of upcoming || []) {
        const s = Date.parse(u?.t), p = num(u?.price);
        if (Number.isFinite(s) && Number.isFinite(p)) sources.push([s, s + CELL, p, 0]);
    }
    for (const sl of slots || []) {
        const s = Date.parse(sl?.start), e = Date.parse(sl?.end), p = num(sl?.price);
        if (Number.isFinite(s) && Number.isFinite(e) && e > s && Number.isFinite(p)) sources.push([s, e, p, 1]);
    }
    const day0 = zonedMidnight(nowMs, tz);
    const clock = (hhmm) => { const m = /^(\d{1,2}):(\d{2})/.exec(String(hhmm || '')); return m ? day0 + (+m[1] * 60 + +m[2]) * 60e3 : NaN; };
    for (const sc of schedule || []) {
        const s = clock(sc?.start); let e = clock(sc?.end); const p = num(sc?.avg_price);
        if (String(sc?.end || '').startsWith('24')) e = day0 + 24 * HOUR;
        if (Number.isFinite(s) && Number.isFinite(e) && e > s && Number.isFinite(p)) sources.push([s, e, p, 2]);
    }
    sources.sort((p, q) => p[3] - q[3]);
    const cells = [];
    for (let t = win.start; t < win.end; t += CELL) {
        const mid = t + CELL / 2;
        const hit = sources.find(([s, e]) => s <= mid && mid < e);
        cells.push({ s: t, e: t + CELL, p: hit ? hit[2] : null });
    }
    const known = cells.filter((c) => c.p !== null).map((c) => c.p);
    const min = known.length ? Math.min(...known) : null;
    const max = known.length ? Math.max(...known) : null;
    const dynamic = isDynamic === true || (isDynamic !== false && level !== 'flat');
    const flat = !dynamic || level === 'flat' || (known.length > 0 && max - min < 1e-6);
    const avgNum = num(todayAvg);
    if (flat) {
        const price = known.length ? known[0] : (Number.isFinite(avgNum) ? avgNum : null);
        return { flat: true, price, steps: [], gaps: [], min: price, max: price, avg: price };
    }
    const steps = [], gaps = [];
    for (const c of cells) {
        if (c.p === null) {
            const g = gaps[gaps.length - 1];
            if (g && g.e === c.s) g.e = c.e; else gaps.push({ s: c.s, e: c.e });
            continue;
        }
        const st = steps[steps.length - 1];
        if (st && st.e === c.s && Math.abs(st.p - c.p) < 1e-9) st.e = c.e; else steps.push({ s: c.s, e: c.e, p: c.p });
    }
    const avg = known.length ? known.reduce((a, b) => a + b, 0) / known.length : null;
    return { flat: false, price: null, steps, gaps, min, max, avg };
}

/** The price at `ms`, or null. */
export function priceAt(pm, ms) {
    if (!pm) return null;
    if (pm.flat) return pm.price;
    const s = pm.steps.find((x) => x.s <= ms && ms < x.e);
    return s ? s.p : null;
}

/**
 * The plan lane: one row per kind present in the window.
 * names: { charger(cid) → name, load(id) → name }.
 * → [{ key, kind, label, blocks: [{ s, e, kwh, past, run, provisional }] }]
 */
export function planRows({ win, nowMs, plan, names = {} }) {
    const a = plan && typeof plan === 'object' ? plan : {};
    const slots = Array.isArray(a.slots) ? a.slots : [];
    const rows = new Map();
    const row = (key, kind, label) => {
        if (!rows.has(key)) rows.set(key, { key, kind, label, blocks: [] });
        return rows.get(key);
    };
    const add = (r, s, e, kwh, provisional = false) => {
        if (!Number.isFinite(s) || !Number.isFinite(e) || e <= s || e <= win.start || s >= win.end) return;
        const last = r.blocks[r.blocks.length - 1];
        if (last && last.e === s && last.provisional === provisional) { last.e = e; last.kwh += kwh; }
        else r.blocks.push({ s, e, kwh, provisional });
    };
    const blockRow = (id) => {
        // (#1354) every row is named through the one plan-id reader, never by its id
        const name = planIdName(id, names);
        const { kind, key } = planIdParts(id);
        if (kind === 'ev') return row(id, 'ev', name);
        if (kind === 'load') return row(id, 'load', name);
        // (#1321) a heater's Keep at run: its own row, named after the device
        if (kind === 'comfort') {
            const r = row(id, 'load', name);
            r.keepOf = key;
            return r;
        }
        if (kind === 'battery') return row('battery_in', 'battery_in', '');
        return row(id, 'load', name);
    };
    const fromBlocks = (list, provisional) => {
        for (const b of list || []) {
            const s = Date.parse(b?.start), e = Date.parse(b?.end);
            const w = num(b?.power_w);
            add(blockRow(String(b?.id || '')), s, e, Number.isFinite(w) ? w * (e - s) / 3.6e9 : 0, provisional);
        }
    };
    fromBlocks(a.blocks, false);
    for (const r of Array.isArray(a.batt_runs) ? a.batt_runs : []) {
        const s0 = Array.isArray(r) ? slots[r[0]] : null, s1 = Array.isArray(r) ? slots[r[1]] : null;
        if (!s0 || !s1) continue;
        let kwh = 0;
        for (let i = r[0]; i <= r[1]; i++) {
            const sl = slots[i]; const w = num(sl?.home_w);
            if (sl && Number.isFinite(w)) kwh += Math.max(0, w) * (Date.parse(sl.end) - Date.parse(sl.start)) / 3.6e9;
        }
        add(row('battery_out', 'battery_out', ''), Date.parse(s0.start), Date.parse(s1.end), kwh);
    }
    for (const sl of slots) {
        const w = num(sl?.home_grid_w);
        if (!(w > 0)) continue;
        const s = Date.parse(sl.start), e = Date.parse(sl.end);
        add(row('grid', 'grid', ''), s, e, w * (e - s) / 3.6e9);
    }
    const tmw = a.tomorrow && typeof a.tomorrow === 'object' ? a.tomorrow : null;
    if (tmw && tmw.provisional && Array.isArray(tmw.provisional.blocks)) fromBlocks(tmw.provisional.blocks, true);
    const order = { ev: 0, battery_in: 1, battery_out: 2, grid: 3, load: 4 };
    const out = [...rows.values()].filter((r) => r.blocks.length);
    for (const r of out) for (const b of r.blocks) { b.past = b.e <= nowMs; b.run = b.s <= nowMs && nowMs < b.e; }
    return out.sort((p, q) => order[p.kind] - order[q.kind] || p.key.localeCompare(q.key));
}

/** The block to name below the chart: the picked one, the running one, else the next. */
export function focusBlock(rows, nowMs, pickedKey) {
    const all = rows.flatMap((r) => r.blocks.map((b) => ({ ...b, row: r, key: r.key + ':' + b.s })));
    return all.find((b) => b.key === pickedKey) || all.find((b) => b.run)
        || all.filter((b) => b.s > nowMs).sort((p, q) => p.s - q.s)[0] || null;
}

/** What runs at `ms`: the rows with a block over it. */
export function runningAt(rows, ms) {
    return rows.filter((r) => r.blocks.some((b) => b.s <= ms && ms < b.e));
}

/**
 * (#1321) The Plan screen's price-and-plan strip, as geometry.
 *
 * Pure: the plan sensor's attributes, the chosen day and a few clock facts
 * in; hourly price bars, the cheap and expensive bands, the sun curve, the
 * block rects by lane and the marker lines out. Every x is a fraction 0..1
 * of a 24 h axis that starts at 00:00 of the chosen day, so the card only
 * multiplies by its width and draws.
 *
 * Nothing is invented: no slots give no bars, no forecast gives no sun, a
 * block outside the day is dropped, never squeezed in.
 */

const HOUR_MS = 3600e3;

/** Lane index by block id: the car on top, the battery, then the loads. */
export const LANES = { ev: 0, battery: 1, load: 2 };
export const LANE_COUNT = 3;

/** 00:00 of today or tomorrow (local), as ms bounds. */
export function dayBounds(now, day) {
    const d = new Date(now.getTime());
    d.setHours(0, 0, 0, 0);
    if (day === 'tomorrow') d.setDate(d.getDate() + 1);
    const e = new Date(d.getTime());
    e.setDate(e.getDate() + 1);
    return { start: d.getTime(), end: e.getTime() };
}

/** 'HH:MM' on the day that starts at `dayStart`, as ms; null when unreadable. */
export function clockMs(hhmm, dayStart) {
    const m = /^(\d{1,2}):(\d{2})/.exec(String(hhmm || ''));
    if (!m) return null;
    const d = new Date(dayStart);
    d.setHours(Number(m[1]), Number(m[2]), 0, 0);
    return d.getTime();
}

/** The price above which an hour counts as expensive when no threshold is set: the top quartile. */
export function topQuartile(prices) {
    const p = (prices || []).filter((v) => Number.isFinite(v)).sort((a, b) => a - b);
    if (p.length < 4 || p[p.length - 1] <= p[0]) return null;
    return p[Math.floor(p.length * 0.75) - 1];
}

function laneOf(id) {
    if (id.startsWith('ev:')) return LANES.ev;
    if (id.startsWith('battery')) return LANES.battery;
    return LANES.load;
}

function kindOf(id) {
    if (id.startsWith('ev:')) return 'ev';
    if (id.startsWith('battery')) return 'battery_in';
    return 'load';
}

/** Consecutive hour bars merged into [x0, x1] runs. */
function runsOf(bars) {
    const out = [];
    for (const b of bars) {
        const last = out[out.length - 1];
        if (last && last.h1 === b.h - 1) { last.h1 = b.h; last.x1 = b.x1; }
        else out.push({ h0: b.h, h1: b.h, x0: b.x0, x1: b.x1 });
    }
    return out.map(({ x0, x1 }) => ({ x0, x1 }));
}

/**
 * stripModel({ plan: attributes, day: 'today' | 'tomorrow', now: Date,
 *              nightStart: 'HH:MM', nightEnd: 'HH:MM', forecastKwh,
 *              expensiveThreshold, departure: 'HH:MM' })
 * → { day, start, end, bars, price, threshold, bands, sun, blocks, lines, ticks }
 */
export function stripModel(o) {
    const now = o.now instanceof Date ? o.now : new Date(o.now || Date.now());
    const day = o.day === 'tomorrow' ? 'tomorrow' : 'today';
    const { start, end } = dayBounds(now, day);
    const span = end - start;
    const hours = Math.round(span / HOUR_MS);
    const nowMs = now.getTime();
    const x = (ms) => Math.min(1, Math.max(0, (ms - start) / span));
    const a = o.plan && typeof o.plan === 'object' ? o.plan : {};
    const slots = Array.isArray(a.slots) ? a.slots : [];
    const tmw = a.tomorrow && typeof a.tomorrow === 'object' ? a.tomorrow : null;

    // ── price bars: one per hour of the day the slots cover, the mean of its slots ──
    const buckets = new Map();
    for (const s of slots) {
        const s0 = Date.parse(s.start), s1 = Date.parse(s.end);
        const p = Number(s.price);
        if (!Number.isFinite(s0) || !Number.isFinite(s1) || s1 <= s0 || !Number.isFinite(p)) continue;
        if (s1 <= start || s0 >= end) continue;
        const mid = (Math.max(s0, start) + Math.min(s1, end)) / 2;
        const h = Math.floor((mid - start) / HOUR_MS);
        if (h < 0 || h >= hours) continue;
        const b = buckets.get(h) || { h, sum: 0, n: 0, cheap: false, co2: 0, nco2: 0 };
        b.sum += p; b.n += 1;
        if (s.cheap) b.cheap = true;
        if (Number.isFinite(Number(s.co2))) { b.co2 += Number(s.co2); b.nco2 += 1; }
        buckets.set(h, b);
    }
    const bars = [...buckets.values()].sort((p, q) => p.h - q.h).map((b) => ({
        h: b.h, x0: b.h * HOUR_MS / span, x1: (b.h + 1) * HOUR_MS / span,
        price: b.sum / b.n, cheap: b.cheap, co2: b.nco2 ? b.co2 / b.nco2 : null,
        past: start + (b.h + 1) * HOUR_MS <= nowMs,
    }));
    const prices = bars.map((b) => b.price);
    const price = prices.length ? { min: Math.min(...prices), max: Math.max(...prices) } : null;

    // ── bands: cheap from the tariff's word, expensive above the threshold ──
    let threshold = Number(o.expensiveThreshold);
    if (!Number.isFinite(threshold) || threshold <= 0) threshold = topQuartile(prices);
    const cheap = runsOf(bars.filter((b) => b.cheap));
    const expensive = threshold === null ? [] : runsOf(bars.filter((b) => !b.cheap && b.price > threshold));
    if (tmw && Array.isArray(tmw.cheap_windows)) {
        for (const w of tmw.cheap_windows) {
            const w0 = Date.parse(w?.start), w1 = Date.parse(w?.end);
            if (!Number.isFinite(w0) || !Number.isFinite(w1) || w1 <= w0) continue;
            if (w1 <= start || w0 >= end) continue;
            const f0 = x(Math.max(w0, start)), f1 = x(Math.min(w1, end));
            if (!cheap.some((c) => c.x0 <= f0 && c.x1 >= f1)) cheap.push({ x0: f0, x1: f1 });
        }
    }

    // ── sun: the forecast shaped as a bell between night end and night start ──
    let sun = null;
    const kwh = Number(o.forecastKwh);
    const up = clockMs(o.nightEnd, start), down = clockMs(o.nightStart, start);
    if (Number.isFinite(kwh) && kwh > 0 && up !== null && down !== null && down > up) {
        const n = 24;
        const points = [];
        for (let i = 0; i <= n; i++) {
            const f = i / n;
            points.push([x(up + (down - up) * f), Math.sin(Math.PI * f)]);
        }
        sun = { x0: x(up), x1: x(down), points, kwh };
    }

    // ── blocks by lane ──
    const blocks = [];
    const push = (b, extra) => {
        const s = Date.parse(b?.start), e = Date.parse(b?.end);
        if (!Number.isFinite(s) || !Number.isFinite(e) || e <= s) return;
        if (e <= start || s >= end) return;
        const id = String(b.id || '');
        const powerW = Number(b.power_w) || 0;
        blocks.push({
            key: `${extra.src}:${id}:${s}`, id, lane: laneOf(id), kind: extra.kind || kindOf(id),
            x0: x(Math.max(s, start)), x1: x(Math.min(e, end)), start: s, end: e,
            powerW, kwh: powerW * (e - s) / 3.6e9,
            run: s <= nowMs && nowMs < e, done: e <= nowMs,
            label: b.label || '', coverage: b.coverage ?? null, provisional: !!extra.provisional,
        });
    };
    for (const b of (Array.isArray(a.blocks) ? a.blocks : [])) push(b, { src: 'plan' });
    for (const r of (Array.isArray(a.batt_runs) ? a.batt_runs : [])) {
        const s0 = Array.isArray(r) ? slots[r[0]] : null, s1 = Array.isArray(r) ? slots[r[1]] : null;
        if (!s0 || !s1) continue;
        push({ id: 'battery_out', start: s0.start, end: s1.end }, { src: 'batt', kind: 'battery_out' });
    }
    if (tmw && tmw.provisional && Array.isArray(tmw.provisional.blocks)) {
        for (const b of tmw.provisional.blocks) push(b, { src: 'tmw', provisional: true });
    }
    blocks.sort((p, q) => p.lane - q.lane || p.start - q.start);

    // ── marker lines ──
    const lines = { now: null, departure: null };
    if (nowMs >= start && nowMs < end) lines.now = x(nowMs);
    const dep = clockMs(o.departure, start);
    if (dep !== null && dep > nowMs && dep > start && dep < end) {
        lines.departure = { x: x(dep), label: String(o.departure).slice(0, 5) };
    }

    const ticks = [];
    for (let h = 0; h <= 24; h += 6) ticks.push({ x: h === 24 ? 1 : x(start + h * HOUR_MS), label: h === 24 ? '24' : String(h).padStart(2, '0') });

    return { day, start, end, bars, price, threshold, bands: { cheap, expensive }, sun, blocks, lines, ticks };
}

/** A Catmull-Rom-like smooth path through [x, y] points (the mockup's smooth()). */
export function smoothPath(pts) {
    if (!pts.length) return '';
    if (pts.length < 3) return pts.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join(' ');
    let d = 'M' + pts[0][0].toFixed(1) + ' ' + pts[0][1].toFixed(1);
    for (let i = 0; i < pts.length - 1; i++) {
        const p0 = pts[Math.max(0, i - 1)], p1 = pts[i], p2 = pts[i + 1], p3 = pts[Math.min(pts.length - 1, i + 2)];
        const c1 = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6];
        const c2 = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6];
        d += ` C${c1[0].toFixed(1)} ${c1[1].toFixed(1)} ${c2[0].toFixed(1)} ${c2[1].toFixed(1)} ${p2[0].toFixed(1)} ${p2[1].toFixed(1)}`;
    }
    return d;
}

/** Minutes from `now` to the end of the plan's slots, for a one-night override; 1..1440, `fallback` without slots. */
export function minutesToPlanEnd(plan, now, fallback = 720) {
    const slots = Array.isArray(plan?.slots) ? plan.slots : [];
    const last = slots.length ? Date.parse(slots[slots.length - 1].end) : NaN;
    const nowMs = now instanceof Date ? now.getTime() : Number(now);
    if (!Number.isFinite(last) || last <= nowMs) return fallback;
    return Math.max(1, Math.min(1440, Math.round((last - nowMs) / 60e3)));
}

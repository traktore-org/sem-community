/**
 * (#1321) Three small additions to the SEM-dashboard Now screen, as pure
 * models: where the house's power comes from now (shares), the next 24 hours
 * of price as levels, and one summary chip per device.
 */
import { SOURCE_KEYS } from './next-power-bar.js';

/**
 * The share of each source in what flows in now, in whole percent that add
 * up to 100 (largest remainder). Sources at 0 W are left out.
 * bar: the powerBar() result → [{ key, w, pct }]
 */
export function sourceMix(bar) {
    const parts = (bar?.sources || []).filter((s) => SOURCE_KEYS.includes(s.key) && s.w > 0);
    const total = parts.reduce((a, s) => a + s.w, 0);
    if (!(total > 0)) return [];
    const raw = parts.map((s) => ({ key: s.key, w: s.w, exact: s.w / total * 100 }));
    const out = raw.map((r) => ({ key: r.key, w: r.w, pct: Math.floor(r.exact) }));
    let left = 100 - out.reduce((a, r) => a + r.pct, 0);
    const order = raw.map((r, i) => ({ i, rest: r.exact - Math.floor(r.exact) })).sort((a, b) => b.rest - a.rest);
    for (let k = 0; left > 0 && k < order.length; k += 1, left -= 1) out[order[k].i].pct += 1;
    return out;
}

/** A price's level: the install's own thresholds when set, else thirds of the window. */
export function levelOf(p, { cheap = null, expensive = null, min = null, max = null } = {}) {
    if (p === null || p === undefined || !Number.isFinite(p)) return 'unknown';
    const c = Number.isFinite(cheap) ? cheap : (Number.isFinite(min) && Number.isFinite(max) ? min + (max - min) / 3 : null);
    const e = Number.isFinite(expensive) ? expensive : (Number.isFinite(min) && Number.isFinite(max) ? min + (max - min) * 2 / 3 : null);
    if (c === null || e === null) return 'normal';
    if (p <= c) return 'cheap';
    if (p >= e) return 'expensive';
    return 'normal';
}

/**
 * The price strip: runs of one level across the window, from priceModel().
 * → null for a flat tariff (one rate: the strip would say nothing),
 *   else { runs: [{ s, e, level }], nowLevel }
 */
export function priceStrip(pm, win, nowMs, thresholds = {}) {
    if (!pm || pm.flat || !win) return null;
    const lim = { ...thresholds, min: pm.min, max: pm.max };
    const cells = [];
    for (const st of pm.steps || []) cells.push({ s: st.s, e: st.e, level: levelOf(st.p, lim) });
    for (const g of pm.gaps || []) cells.push({ s: g.s, e: g.e, level: 'unknown' });
    cells.sort((a, b) => a.s - b.s);
    const runs = [];
    for (const c of cells) {
        const s = Math.max(c.s, win.start), e = Math.min(c.e, win.end);
        if (e <= s) continue;
        const last = runs[runs.length - 1];
        if (last && last.level === c.level && last.e === s) last.e = e; else runs.push({ s, e, level: c.level });
    }
    if (!runs.some((r) => r.level !== 'unknown')) return null;
    const at = runs.find((r) => r.s <= nowMs && nowMs < r.e);
    return { runs, nowLevel: at ? at.level : 'unknown' };
}

/**
 * One chip per device for the summary row: the house battery, each car,
 * each heat pump or hot-water tank. Pure: the caller reads the states.
 * input: { batterySoc, cars: [{ name, connected, charging, soc }], heaters: [{ name, on }] }
 * → [{ kind, label, state, soc }]
 */
export function deviceChips({ batterySoc = null, cars = [], heaters = [] } = {}) {
    const chips = [];
    if (batterySoc !== null && Number.isFinite(batterySoc)) chips.push({ kind: 'battery', label: null, state: null, soc: Math.round(batterySoc) });
    for (const c of cars) {
        const state = c.charging ? 'charging' : (c.connected === false ? 'unplugged' : (c.connected ? 'plugged' : null));
        chips.push({ kind: 'car', label: c.name, state, soc: Number.isFinite(c.soc) ? Math.round(c.soc) : null });
    }
    for (const h of heaters) chips.push({ kind: 'heater', label: h.name, state: h.on ? 'on' : 'off', soc: null });
    return chips;
}

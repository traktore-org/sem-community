/**
 * SEM Next · Plan (#1321)
 *
 * Sun, price and plan on one clock (Today / Next 24 h / Tomorrow): the sun
 * as measured and as forecast, the price as a step line, the plan as one
 * row per device. Hover or tap for the moment's numbers; tap a block for its
 * reason. Below: one row per device with the one-night overrides, the
 * expected numbers, and today's decisions from the log.
 *
 * Config:
 *   type: custom:sem-next-plan-card
 */

import { SEMNextBase, html, css, svg, nothing, nextCss, NEXT_COLORS as C } from '../base/sem-next-base.js';
import { semDefineCard } from '../base/sem-shared.js';
import { planLead, kwhOf, coldHeaters } from '../util/next-lead.js';

/** null / '' is unknown, never 0 (Number(null) is 0). */
export function knownNum(v) {
    if (v === null || v === undefined || v === '') return NaN;
    const n = Number(v);
    return Number.isFinite(n) ? n : NaN;
}
import { laneModel } from '../util/next-timeline.js';
import { minutesToPlanEnd } from '../util/next-strip.js';
import { chartWindow, chartTicks, sunModel, priceModel, priceAt, planRows, focusBlock, runningAt, RANGES } from '../util/next-plan-chart.js';
import {
    WHY_KINDS, changeLabel, deviceName, earlierKey, filterRecords, isToday, plainReason, rowTime, whyChips,
} from '../util/why-rows.js';

export const WS_DECISION_LOG = 'solar_energy_management/decision_log';
/** The decisions list reads the log again this often while the screen is open. */
export const LOG_REFRESH_MS = 60000;
const DOMAIN = 'solar_energy_management';
const IDS = ['sensor.sem_energy_plan', 'sensor.sem_forecast_tomorrow_kwh', 'sensor.sem_forecast_today_kwh',
             'sensor.sem_tariff_price_level', 'sensor.sem_controllable_devices_count', 'switch.sem_energy_plan_actuation',
             'sensor.sem_charging_state', 'number.sem_expensive_price_threshold', 'select.sem_battery_mode',
             'sensor.sem_battery_dynamic_floor_pct', 'sensor.sem_forecast_trust_d2'];
const SHOWN_ROWS = 6;
const CHARGE_NOW_MINUTES = 120;   // how long "Charge now" holds before the plan takes over
const KIND_COLOR = { ev: C.ev, battery_in: C.battery_in, battery_out: C.battery_out, grid: C.grid, load: C.home };
const KIND_ICON = { ev: 'mdi:car-electric', battery_in: 'mdi:battery-charging', battery_out: 'mdi:home-battery', grid: 'mdi:transmission-tower', load: 'mdi:power-plug' };
export const WS_SOLAR_FORECAST = 'solar_energy_management/solar_forecast';
const SUN_REFRESH_MS = 30 * 60e3, STATS_REFRESH_MS = 15 * 60e3;
const RANGE_KEY = 'sem-next-plan-range';
function readRange() {
    try { const v = window.localStorage.getItem(RANGE_KEY); return RANGES.includes(v) ? v : 'next'; } catch (e) { return 'next'; }
}
function writeRange(v) {
    try { window.localStorage.setItem(RANGE_KEY, v); } catch (e) { /* private window: nothing kept */ }
}

/** A smooth line through points (Catmull-Rom as cubic Béziers), never below the first/last y. */
function smoothPath(pts) {
    if (pts.length < 2) return '';
    let d = `M${pts[0][0]} ${pts[0][1]}`;
    for (let i = 0; i < pts.length - 1; i++) {
        const p0 = pts[i - 1] || pts[i], p1 = pts[i], p2 = pts[i + 1], p3 = pts[i + 2] || p2;
        const c1x = p1[0] + (p2[0] - p0[0]) / 6, c1y = Math.min(Math.max(p1[1] + (p2[1] - p0[1]) / 6, Math.min(p1[1], p2[1]) - 6), Math.max(p1[1], p2[1]));
        const c2x = p2[0] - (p3[0] - p1[0]) / 6, c2y = Math.min(Math.max(p2[1] - (p3[1] - p1[1]) / 6, Math.min(p1[1], p2[1]) - 6), Math.max(p1[1], p2[1]));
        d += ` C${c1x} ${c1y} ${c2x} ${c2y} ${p2[0]} ${p2[1]}`;
    }
    return d;
}

class SEMNextPlanCard extends SEMNextBase {
    static get properties() {
        return {
            _picked: { state: true }, _confirm: { state: true }, _range: { state: true }, _hover: { state: true }, _fc: { state: true }, _stats: { state: true },
            _w: { state: true }, _records: { state: true }, _chip: { state: true }, _fold: { state: true },
            _logError: { state: true },
        };
    }
    // A 24 h axis in 380 px is unreadable: the per-device lanes keep their
    // width and scroll sideways inside their own box instead of shrinking.
    static get styles() {
        return [nextCss, css`
            .tm { width: 42px; flex: 0 0 auto; }
            .reason .t { min-width: 0; }
            .pc { position: relative; margin-top: 4px; touch-action: pan-y; }
            .pc svg { display: block; overflow: visible; }
            .pc .lab { position: absolute; left: 0; display: flex; align-items: center; gap: 4px; font-size: 11px; color: var(--n-fg2);
                white-space: nowrap; overflow: hidden; text-overflow: ellipsis; transform: translateY(-50%); line-height: 1.1; }
            .pc .lab ha-icon { --mdc-icon-size: 15px; flex: 0 0 auto; }
            .pc .lab small { display: block; font-size: 9.5px; color: var(--n-fg3); }
            .pc .lab span { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
            .pc .lab ha-icon { color: var(--c); }
            .pc .tip { position: absolute; z-index: 2; pointer-events: none; background: var(--n-card); border: 1px solid var(--n-line);
                border-radius: 10px; padding: 7px 10px; font-size: 12px; line-height: 1.4; box-shadow: 0 6px 20px rgba(0, 0, 0, .25);
                min-width: 120px; max-width: 220px; }
            .pc .tip b { font-variant-numeric: tabular-nums; }
            .pc .tip i { display: inline-block; width: 8px; height: 8px; border-radius: 2px; margin-right: 5px; }
            .pc .blk { cursor: pointer; }
        `];
    }

    constructor() {
        super();
        this._picked = null;       // block key in the plan lane
        this._hover = null;        // ms under the pointer, or null
        this._fc = null;           // the hourly sun forecast { iso: Wh }; null = not read yet
        this._stats = null;        // measured sun, [{ t, w }] per hour
        this._priceStats = null;   // what the tariff read, [{ t, p }] per hour
        this._sunTimer = null;
        this._statTimer = null;
        this._confirm = null;      // charger id awaiting "Charge now" confirmation
        this._range = readRange();
        this._w = 720;
        this._hostW = 0;
        this._ro = null;
        this._m = null;
        this._records = null;      // null = not loaded yet
        this._chip = '';           // '' = all devices
        this._fold = false;
        this._logError = false;
        this._loading = false;
        this._logTimer = null;
        this._local = {};          // device id → {action, until}, until the next plan
        this._localStamp = '';
    }

    connectedCallback() {
        super.connectedCallback();
        if (typeof ResizeObserver !== 'undefined' && !this._ro) {
            this._ro = new ResizeObserver((entries) => {
                const w = Math.floor(entries[0]?.contentRect?.width || 0);
                if (w > 0 && w !== this._hostW) {
                    this._hostW = w;
                    // the app frame pads 8 px, the card 16 px, each side
                    this._w = Math.max(240, Math.min(w, 1180) - 48);
                }
            });
            this._ro.observe(this);
        }
        this._stopLog();
        this._loadLog();
        this._logTimer = setInterval(() => this._loadLog(), LOG_REFRESH_MS);
        this._loadSun();
        this._loadStats();
        this._sunTimer = setInterval(() => this._loadSun(), SUN_REFRESH_MS);
        this._statTimer = setInterval(() => this._loadStats(), STATS_REFRESH_MS);
    }

    disconnectedCallback() {
        if (this._ro) { this._ro.disconnect(); this._ro = null; }
        this._stopLog();
        clearInterval(this._sunTimer); clearInterval(this._statTimer);
        this._sunTimer = null; this._statTimer = null;
        super.disconnectedCallback();
    }

    set hass(hass) {
        super.hass = hass;
        if (hass && this._records === null) this._loadLog();
        if (hass && this._fc === null) this._loadSun();
        if (hass && this._stats === null) this._loadStats();
    }
    get hass() { return this._hass; }

    _watchIds() {
        const per = this._chargers.flatMap((cid) => [`select.sem_charger_${cid}_charge_mode`, `time.sem_charger_${cid}_target_time`]);
        return [...super._watchIds(), ...IDS, ...per];
    }

    // ── the decision log ──
    _stopLog() {
        if (this._logTimer) { clearInterval(this._logTimer); this._logTimer = null; }
    }

    async _loadLog() {
        if (this._loading || !this._hass?.callWS) return;
        this._loading = true;
        try {
            const res = await this._hass.callWS({ type: WS_DECISION_LOG });
            this._records = Array.isArray(res?.records) ? res.records : [];
            this._logError = false;
        } catch (_err) {
            if (this._records === null) this._records = [];
            this._logError = true;
        } finally {
            this._loading = false;
        }
    }

    // ── the sun: forecast by the hour, and what it made ──
    async _loadSun() {
        if (this._sunBusy || !this._hass?.callWS) return;
        this._sunBusy = true;
        try {
            const r = await this._hass.callWS({ type: WS_SOLAR_FORECAST });
            this._fc = r && typeof r.wh_hours === 'object' && r.wh_hours ? r.wh_hours : {};
        } catch (_err) {
            this._fc = {};
        } finally {
            this._sunBusy = false;
        }
    }

    async _loadStats() {
        if (this._statBusy || !this._hass?.callWS) return;
        this._statBusy = true;
        try {
            const tz = this._hass.config?.time_zone;
            const now = Date.now();
            const from = Math.min(chartWindow(now, 'today', tz).start, chartWindow(now, 'next', tz).start);
            const r = await this._hass.callWS({ type: 'recorder/statistics_during_period', start_time: new Date(from).toISOString(),
                statistic_ids: ['sensor.sem_solar_power', 'sensor.sem_tariff_current_import_rate'], period: 'hour', types: ['mean'], units: { power: 'W' } });
            const at = (x) => (typeof x.start === 'number' ? x.start : Date.parse(x.start));
            const rows = Array.isArray(r?.['sensor.sem_solar_power']) ? r['sensor.sem_solar_power'] : [];
            this._stats = rows.map((x) => ({ t: at(x), w: x.mean }));
            const prices = Array.isArray(r?.['sensor.sem_tariff_current_import_rate']) ? r['sensor.sem_tariff_current_import_rate'] : [];
            this._priceStats = prices.map((x) => ({ t: at(x), p: x.mean }));
        } catch (_err) {
            this._stats = [];
        } finally {
            this._statBusy = false;
        }
    }

    // ── models ──
    _plan() { return this._attrs('sensor.sem_energy_plan'); }

    _devices() { return this._attrs('sensor.sem_controllable_devices_count').devices || {}; }

    _loads() {
        return Object.entries(this._devices()).map(([id, info]) => ({ id, name: info?.name || id }));
    }

    _model() {
        return laneModel({
            now: new Date(), plan: this._plan(),
            chargers: this._chargers.map((cid) => ({ id: cid, name: this._chargerName(cid) })),
            loads: this._loads(),
            nightStart: this._str('sensor.sem_night_start_time'), nightEnd: this._str('sensor.sem_night_end_time'),
            forecastTomorrowKwh: this._num('sensor.sem_forecast_tomorrow_kwh'),
            forecastTodayKwh: this._num('sensor.sem_forecast_today_kwh'),
        });
    }

    /** The earliest charger Charge-by time, 'HH:MM', or ''. */
    _departure() {
        const times = this._chargers.map((cid) => (this._str(`time.sem_charger_${cid}_target_time`) || '').slice(0, 5)).filter((t) => /^\d{2}:\d{2}$/.test(t)).sort();
        return times[0] || '';
    }

    _rowLabel(r) {
        if (r.kind === 'ev' && !r.label) {
            // two unnamed cars must not read the same: number them in row order
            const evs = (this._lastRows || []).filter((x) => x.kind === 'ev');
            const i = evs.indexOf(r);
            return evs.length > 1 && i >= 0 ? `${this._t('next_src_car')} ${i + 1}` : this._t('next_src_car');
        }
        if (r.kind === 'ev' || r.kind === 'load') return (r.label || this._t('next_lane_load')) + this._toKeep(r.keepOf);
        return this._t({ battery_in: 'next_row_charge', battery_out: 'next_row_to_house', grid: 'next_row_from_grid' }[r.kind]);
    }

    /** (#1321) " · to 52 °C" for a heater's Keep at run, '' otherwise. */
    _toKeep(deviceId) {
        const keep = deviceId ? this._devices()[deviceId]?.comfort?.keep_c : null;
        return keep == null || !Number.isFinite(Number(keep)) ? '' : ' · ' + this._tf('next_plan_to_keep', { keep: this._temp(keep) });
    }

    /** (#1321) Heaters below their start line with no hour in the plan. */
    _cold(plan) {
        const slots = Array.isArray(plan.slots) ? plan.slots : [];
        const end = slots.length ? slots[slots.length - 1].end : '';
        const time = end && Number.isFinite(Date.parse(end)) ? this._hhmm(end) : '';
        return coldHeaters(this._devices(), plan.blocks, Date.now())
            .map((h) => ({ ...h, keep: this._temp(h.keepC), time }));
    }

    _rowName(r) {
        if (r.kind === 'ev' || r.kind === 'load') return this._rowLabel(r);
        return this._t({ battery_in: 'next_battery_charging', battery_out: 'next_battery_to_house', grid: 'next_house_from_grid' }[r.kind]);
    }

    /** The plan's why codes as sentences; the raw log text never shows. */
    _whyCodes(plan) {
        return (Array.isArray(plan?.why_codes) ? plan.why_codes : [])
            .map((c) => { const k = 'energy_plan_whyc_' + c; const v = this._t(k); return v && v !== k ? v : ''; })
            .filter(Boolean).join(' · ');
    }

    /** The not_scheduled entry's machine why, as a sentence. */
    _whyText(n) {
        const code = n?.why || n?.reason || '';
        const key = 'energy_plan_why_' + code;
        const said = this._t(key);
        return said && said !== key ? said : (n?.note || String(code));
    }

    /** (#1321) The planner's own why for the tapped block, in words; '' when none. */
    _blockWhy(fb, plan) {
        const blocks = Array.isArray(plan?.blocks) ? plan.blocks : [];
        const b = blocks.filter((x) => x && x.reason && Date.parse(x.start) < fb.e && Date.parse(x.end) > fb.s
            && (x.id === fb.row.key || (fb.row.kind === 'battery_in' && String(x.id || '').includes('battery'))))
            .sort((p, q) => Date.parse(p.start) - Date.parse(q.start))[0];
        if (!b) return '';
        const key = 'next_reason_' + b.reason;
        const text = this._t(key);
        if (!text || text === key) return '';
        const p = b.reason_params || {};
        const time = p.deadline ? this._hhmm(p.deadline) : '';
        if (text.includes('{time}') && !time) return '';
        const said = this._tf(key, { time });
        const price = Number(p.price);
        return p.price !== undefined && p.price !== null && Number.isFinite(price)
            ? `${said} · ${this._tf('next_tip_price', { price: this._fmt(price, 3), cur: this._currency() })}` : said;
    }

    _focusReason(fb, plan) {
        if (fb.provisional) return this._t('next_provisional_reason');
        const hours = (fb.e - fb.s) / 3.6e6;
        const kw = this._fmt(hours > 0 ? fb.kwh / hours : 0, 1);
        const kind = fb.row.kind;
        const why = kind === 'ev' || kind === 'load' || kind === 'battery_in' ? this._blockWhy(fb, plan) : '';
        if (why) return why;
        if (kind === 'battery_in') return this._whyCodes(plan) || this._tf('next_reason_battery_charge', { kw });
        if (kind === 'battery_out') return this._t('next_reason_battery_house');
        if (kind === 'grid') return this._t('next_reason_house_grid');
        const demands = Array.isArray(plan.demands) ? plan.demands : [];
        const d = demands.find((x) => x.id === fb.row.key);
        if (d?.note) return String(d.note);
        if (d?.status) return this._t('next_status_' + d.status);
        return this._tf(kind === 'ev' ? 'next_reason_ev_block' : 'next_reason_load_block', { kw, status: '', note: '' }).replace(/\s+/g, ' ').trim();
    }

    _chartData(plan) {
        const tz = this._hass?.config?.time_zone;
        const now = Date.now();
        const win = chartWindow(now, this._range, tz);
        const sun = sunModel({ win, nowMs: now, actual: this._stats || [], forecast: this._fc || {} });
        const tar = this._attrs('sensor.sem_tariff_current_import_rate');
        const price = priceModel({ win, tz, nowMs: now, upcoming: tar.upcoming, slots: plan.slots, schedule: tar.schedule_today, past: this._priceStats || [],
            isDynamic: tar.is_dynamic, level: tar.price_level || this._str('sensor.sem_tariff_price_level'), todayAvg: tar.today_avg });
        const rows = planRows({ win, nowMs: now, plan, names: {
            charger: (cid) => (this._chargers.includes(cid) ? this._chargerName(cid) : ''),
            load: (id) => this._devices()[id]?.name || id,
        } });
        this._lastRows = rows;
        return { tz, now, win, sun, price, rows };
    }

    /** The visible day's forecast total, when no hourly forecast exists. */
    _sunFallbackKwh(d) {
        const tomorrow = this._range === 'tomorrow' || (this._range === 'next' && new Date(d.now).getHours() >= 12);
        return this._num(tomorrow ? 'sensor.sem_forecast_tomorrow_kwh' : 'sensor.sem_forecast_today_kwh');
    }

    _svgChip(x, y, text, fill, fg, minX, maxX) {
        const w = text.length * 6.2 + 14;
        const cx = Math.max(minX, Math.min(maxX - w, x - w / 2));
        return svg`<rect x="${cx}" y="${y}" width="${w}" height="18" rx="9" fill="${fill}"></rect>
            <text x="${cx + w / 2}" y="${y + 12.5}" text-anchor="middle" font-size="10.5" font-weight="700" fill="${fg}">${text}</text>`;
    }

    _chartLayout(d) {
        const narrow = (this._w || 720) < 520;
        const LBL = narrow ? 26 : 112;
        const W = Math.max(160, (this._w || 720) - LBL);
        // room on top for the now label (y 4–18) and the sun total chip (y 22–40)
        const sun = [46, 94], price = [118, 168];
        const planY = 190, rowH = 26;
        const planEnd = planY + Math.max(1, d.rows.length) * rowH;
        const axisY = planEnd + 16;
        return { narrow, LBL, W, sun, price, planY, rowH, planEnd, axisY, H: axisY + 22 };
    }

    _chartSvg(d, plan) {
        const lay = this._chartLayout(d);
        const { W, sun: [sy0, sy1], price: [py0, py1], planY, rowH, planEnd, axisY, H } = lay;
        const span = d.win.end - d.win.start;
        const X = (ms) => Math.max(0, Math.min(W, (ms - d.win.start) / span * W));
        const cur = this._currency();
        const parts = [];
        const gid = 'pc' + Math.round(W);
        parts.push(svg`<defs>
            <linearGradient id="${gid}s" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="${C.solar}" stop-opacity=".55"></stop><stop offset="1" stop-color="${C.solar}" stop-opacity=".04"></stop></linearGradient>
            <linearGradient id="${gid}f" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="${C.solar}" stop-opacity=".28"></stop><stop offset="1" stop-color="${C.solar}" stop-opacity=".02"></stop></linearGradient>
            <linearGradient id="${gid}p" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="${C.grid}" stop-opacity=".35"></stop><stop offset="1" stop-color="${C.grid}" stop-opacity="0"></stop></linearGradient>
            <pattern id="${gid}h" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="6" stroke="var(--n-line)" stroke-width="3"></line></pattern>
        </defs>`);
        // sun lane
        parts.push(svg`<line x1="0" x2="${W}" y1="${sy1}" y2="${sy1}" stroke="var(--n-line)"></line>`);
        if (d.sun.points.length) {
            const max = Math.max(...d.sun.points.map((p) => p.kw), 0.1) * 1.15;
            const SY = (kw) => sy1 - (sy1 - sy0) * kw / max;
            for (const actual of [true, false]) {
                const pts = d.sun.points.filter((p) => p.actual === actual);
                if (!pts.length) continue;
                // runs of touching periods; each run a smooth curve through the midpoints
                const runs = [];
                for (const p of pts) {
                    const last = runs[runs.length - 1];
                    if (last && p.s - last[last.length - 1].e < 40 * 60e3) last.push(p); else runs.push([p]);
                }
                let line = '', area = '';
                for (const run of runs) {
                    const xy = [[X(run[0].s), SY(0)], ...run.map((p) => [X((p.s + p.e) / 2), SY(p.kw)]), [X(run[run.length - 1].e), SY(0)]];
                    const curve = smoothPath(xy);
                    line += (line ? ' ' : '') + curve;
                    area += (area ? ' ' : '') + curve + ` L${xy[xy.length - 1][0]} ${sy1} L${xy[0][0]} ${sy1} Z`;
                }
                parts.push(svg`<path d="${area}" fill="url(#${gid}${actual ? 's' : 'f'})"></path>
                    <path d="${line}" fill="none" stroke="${C.solar}" stroke-width="2" stroke-linejoin="round" stroke-dasharray="${actual ? nothing : '4 3'}"></path>`);
            }
            const pk = d.sun.peak;
            if (pk && d.sun.totalKwh > 0.05) parts.push(this._svgChip(X((pk.s + pk.e) / 2), sy0 - 24, `${this._fmt(d.sun.totalKwh, 1)} kWh`, C.solar, '#1b1204', 0, W));
        } else {
            const kwh = this._sunFallbackKwh(d);
            const text = kwh !== null ? this._tf('next_chip_forecast_kwh', { kwh: this._fmt(kwh, 1) }) : this._t('next_sun_none');
            parts.push(svg`<text x="${W / 2}" y="${(sy0 + sy1) / 2 + 4}" text-anchor="middle" font-size="11" fill="${C.fg3}">${text}</text>`);
        }
        // price lane
        parts.push(svg`<line x1="0" x2="${W}" y1="${py1}" y2="${py1}" stroke="var(--n-line)"></line>`);
        const pm = d.price;
        if (pm.flat && pm.price !== null) {
            const y = (py0 + py1) / 2 + 6;
            parts.push(svg`<rect x="0" y="${y}" width="${W}" height="${py1 - y}" fill="url(#${gid}p)"></rect>
                <line x1="0" x2="${W}" y1="${y}" y2="${y}" stroke="${C.grid}" stroke-width="2"></line>`);
            parts.push(this._svgChip(W / 2, y - 26, this._tf('next_price_flat', { price: this._fmt(pm.price, 2), cur }), 'var(--n-fg)', 'var(--n-card)', 0, W));
        } else if (pm.steps.length) {
            const PY = (v) => py1 - (py1 - py0 - 4) * v / (pm.max * 1.12);
            let line = '', area = '';
            let prev = null;
            for (const st of pm.steps) {
                const x0 = X(st.s), x1 = X(st.e), y = PY(st.p);
                if (!prev || prev.e !== st.s) { line += `${line ? ' ' : ''}M${x0} ${y}`; if (prev) area += ` L${X(prev.e)} ${py1} Z`; area += `${area ? ' ' : ''}M${x0} ${py1} L${x0} ${y}`; }
                else line += ` L${x0} ${y}`;
                line += ` L${x1} ${y}`; area += ` L${x0} ${y} L${x1} ${y}`;
                prev = st;
            }
            area += ` L${X(prev.e)} ${py1} Z`;
            parts.push(svg`<path d="${area}" fill="url(#${gid}p)"></path><path d="${line}" fill="none" stroke="${C.grid}" stroke-width="2" stroke-linejoin="round"></path>`);
            const knownW = X(pm.steps[pm.steps.length - 1].e) - X(pm.steps[0].s);
            if (pm.avg !== null && knownW > 140) {
                const ay = PY(pm.avg);
                const ax0 = X(pm.steps[0].s), ax1 = X(pm.steps[pm.steps.length - 1].e);
                parts.push(svg`<line x1="${ax0}" x2="${ax1}" y1="${ay}" y2="${ay}" stroke="${C.fg3}" stroke-dasharray="3 4"></line>
                    <text x="${ax1 - 2}" y="${ay - 4}" text-anchor="end" font-size="10" fill="${C.fg3}">${this._tf('next_price_avg', { price: this._fmt(pm.avg, 2) })}</text>`);
            }
            const lo = pm.steps.find((st) => st.p === pm.min), hi = pm.steps.find((st) => st.p === pm.max);
            if (hi && knownW > 60) parts.push(this._svgChip(X((hi.s + hi.e) / 2), PY(hi.p) - 22, this._fmt(hi.p, 2), 'var(--n-fg)', 'var(--n-card)', 0, W));
            if (lo && lo !== hi && knownW > 140) parts.push(this._svgChip(X((lo.s + lo.e) / 2), Math.min(py1 - 18, PY(lo.p) + 5), this._fmt(lo.p, 2), 'var(--n-fg)', 'var(--n-card)', 0, W));
            for (const g of pm.gaps) {
                const gx0 = X(g.s), gw = X(g.e) - gx0;
                if (gw < 2) continue;
                parts.push(svg`<rect x="${gx0}" y="${py0}" width="${gw}" height="${py1 - py0}" rx="6" fill="url(#${gid}h)"></rect>`);
                if (gw > 96 && g.e > d.now) parts.push(svg`<text x="${gx0 + gw / 2}" y="${py1 - 10}" text-anchor="middle" font-size="10.5" fill="${C.fg3}">${this._t('next_prices_later')}</text>`);
            }
        } else {
            parts.push(svg`<text x="${W / 2}" y="${(py0 + py1) / 2 + 4}" text-anchor="middle" font-size="11" fill="${C.fg3}">${this._t('next_prices_none')}</text>`);
        }
        // plan lane
        if (!d.rows.length) {
            parts.push(svg`<text x="${W / 2}" y="${planY + rowH / 2 + 4}" text-anchor="middle" font-size="11" fill="${C.fg3}">${this._t('next_plan_nothing_window')}</text>`);
        }
        d.rows.forEach((r, i) => {
            const y = planY + i * rowH;
            const color = KIND_COLOR[r.kind] || C.home;
            parts.push(svg`<line x1="0" x2="${W}" y1="${y + rowH / 2}" y2="${y + rowH / 2}" stroke="var(--n-line)"></line>`);
            for (const b of r.blocks) {
                const x0 = X(b.s), x1 = X(b.e), w = Math.max(3, x1 - x0 - 1.5);
                const key = r.key + ':' + b.s;
                const on = this._picked === key;
                const title = `${this._rowName(r)} · ${this._hhmm(new Date(b.s))} – ${this._hhmm(new Date(b.e))}${b.kwh > 0.05 ? ' · ' + this._kwh(b.kwh) : ''}`;
                const go = (e) => { e.stopPropagation(); this._picked = on ? null : key; };
                parts.push(svg`<g class="blk" tabindex="0" role="button" aria-label="${title}" @click=${go}
                        @keydown=${(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(e); } }}>
                    <rect x="${x0 + 0.75}" y="${y + 4}" width="${w}" height="${rowH - 8}" rx="${Math.min(7, w / 4)}" fill="${color}"
                        fill-opacity="${b.provisional ? 0.45 : (b.past ? 0.35 : 1)}" stroke="${on ? 'var(--n-fg)' : (b.provisional ? color : 'none')}"
                        stroke-width="${on ? 2 : 1}" stroke-dasharray="${b.provisional ? '3 2' : nothing}"><title>${title}</title></rect>
                    ${b.kwh > 0.05 && w > 48 ? svg`<text x="${x0 + 0.75 + w / 2}" y="${y + rowH / 2 + 4}" text-anchor="middle" font-size="10.5" font-weight="700" fill="#10161c" pointer-events="none">${this._fmt(b.kwh, 1)} kWh</text>` : nothing}
                </g>`);
            }
        });
        // past mask, now line, axis
        const nowIn = d.now >= d.win.start && d.now < d.win.end;
        if (nowIn) {
            const nx = X(d.now);
            parts.push(svg`<rect x="0" y="${sy0 - 4}" width="${nx}" height="${planEnd - sy0 + 4}" fill="var(--n-card)" opacity=".42" pointer-events="none"></rect>`);
            const right = nx > W - 70;
            parts.push(svg`<line x1="${nx}" x2="${nx}" y1="10" y2="${planEnd}" stroke="${C.accent}" stroke-width="2" stroke-linecap="round" pointer-events="none"></line>
                <circle cx="${nx}" cy="10" r="3.5" fill="${C.accent}"></circle>
                <text x="${right ? nx - 6 : nx + 6}" y="13.5" text-anchor="${right ? 'end' : 'start'}" font-size="10.5" font-weight="700" fill="${C.accent}">${this._t('next_now_marker')} ${this._hhmm(new Date(d.now))}</text>`);
        }
        for (const tk of chartTicks(d.win, d.tz, lay.narrow ? 6 : 3)) {
            const tx = X(tk.t);
            const anchor = tx < 10 ? 'start' : tx > W - 10 ? 'end' : 'middle';
            parts.push(svg`<line x1="${tx}" x2="${tx}" y1="${planEnd}" y2="${planEnd + 4}" stroke="var(--n-line)"></line>
                <text x="${tx}" y="${axisY}" text-anchor="${anchor}" font-size="10" fill="${C.fg3}">${tk.label}</text>
                ${tk.midnight ? svg`<text x="${tx}" y="${axisY + 13}" text-anchor="${anchor}" font-size="9.5" fill="${C.fg3}">${this._t(this._range === 'today' ? 'next_today' : 'next_tomorrow').toLowerCase()}</text>` : nothing}`);
        }
        // hover layer and crosshair
        if (this._hover !== null && this._hover >= d.win.start && this._hover < d.win.end) {
            const hx = X(this._hover);
            parts.push(svg`<line x1="${hx}" x2="${hx}" y1="${sy0 - 6}" y2="${planEnd}" stroke="var(--n-fg)" stroke-width="1" opacity=".55" pointer-events="none"></line>`);
        }
        const pick = (e) => {
            const r = e.currentTarget.getBoundingClientRect();
            const f = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
            return d.win.start + f * span;
        };
        parts.push(svg`<rect x="0" y="0" width="${W}" height="${planY - 4}" fill="transparent"
            @pointermove=${(e) => { if (e.pointerType === 'mouse') this._hover = pick(e); }}
            @pointerleave=${(e) => { if (e.pointerType === 'mouse') this._hover = null; }}
            @click=${(e) => { const t = pick(e); this._hover = this._hover !== null && Math.abs(this._hover - t) < span / 48 ? null : t; }}></rect>`);
        return { lay, svg: svg`<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="${this._t('next_price_and_plan')}">${parts}</svg>` };
    }

    _tooltip(d, lay) {
        if (this._hover === null || this._hover < d.win.start || this._hover >= d.win.end) return nothing;
        const t = this._hover;
        const p = priceAt(d.price, t);
        const sp = d.sun.points.find((x) => x.s <= t && t < x.e);
        const runs = runningAt(d.rows, t);
        const x = lay.LBL + (t - d.win.start) / (d.win.end - d.win.start) * lay.W;
        const left = Math.max(0, Math.min(lay.LBL + lay.W - 200, x + 10));
        return html`<div class="tip" style="left:${left}px;top:${lay.price[1] - 30}px">
            <div><b>${this._hhmm(new Date(t))}</b></div>
            <div>${p !== null ? this._tf('next_tip_price', { price: this._fmt(p, 3), cur: this._currency() }) : this._t('next_tip_price_unknown')}</div>
            <div>${sp && sp.kwh > 0.005 ? this._tf(sp.actual ? 'next_tip_sun_made' : 'next_tip_sun_fc', { kwh: this._fmt(sp.kwh, 2) }) : this._t('next_tip_no_sun')}</div>
            ${runs.length ? runs.map((r) => html`<div><i style="background:${KIND_COLOR[r.kind]}"></i>${this._rowName(r)}</div>`) : html`<div class="dim">${this._t('next_tip_nothing_runs')}</div>`}
        </div>`;
    }

    _labels(d, lay) {
        const lab = (y, icon, color, text, sub = '') => html`<div class="lab" style="top:${y}px;width:${lay.LBL - 6}px;--c:${color}" title="${text}">
            ${this._icon(icon)}${lay.narrow ? nothing : html`<span>${text}${sub ? html`<small>${sub}</small>` : nothing}</span>`}</div>`;
        return html`
            ${lab((lay.sun[0] + lay.sun[1]) / 2, 'mdi:white-balance-sunny', C.solar, this._t('next_lane_sun'))}
            ${lab((lay.price[0] + lay.price[1]) / 2, 'mdi:cash', C.fg3, this._t('next_lane_price'), `${this._currency()}/kWh`)}
            ${d.rows.map((r, i) => lab(lay.planY + i * lay.rowH + lay.rowH / 2, KIND_ICON[r.kind] || 'mdi:power-plug', KIND_COLOR[r.kind], this._rowLabel(r)))}`;
    }

    _stripPills(plan) {
        const t = (k) => this._t(k);
        const out = [];
        if (plan.fits === true) out.push(this._pill(t('next_fits_yes'), 'ok', { icon: 'mdi:check' }));
        else if (plan.fits === false) out.push(this._pill(t('next_fits_no'), 'warn'));
        if (plan.computed_at) out.push(this._pill(this._tf('next_made_at', { time: this._hhmm(plan.computed_at) })));
        const noSun = plan?.tomorrow?.provisional?.not_enough_sun;
        if (Array.isArray(noSun) && noSun.length) out.push(this._pill(t('next_tmrw_no_sun_car'), 'warn', { icon: 'mdi:weather-cloudy' }));
        if (this._range === 'tomorrow') {
            const tmw = plan.tomorrow;
            const prices = tmw ? ' · ' + t(tmw.prices === 'final' ? 'next_prices_final' : 'next_prices_pending') : '';
            out.push(this._pill(t('next_pill_provisional') + prices));
        } else if (plan.computed_at) {
            out.push(this._pill(plan.actuation ? t('next_pill_live') : t('next_pill_shadow'), plan.actuation ? 'ok' : ''));
        }
        return out;
    }

    _stripSec(plan) {
        const t = (k) => this._t(k);
        const d = this._chartData(plan);
        const seg0 = () => this._seg([{ key: 'today', label: t('next_today') }, { key: 'next', label: t('next_range_next') }, { key: 'tomorrow', label: t('next_tomorrow') }],
            this._range, (k) => { this._range = k; this._picked = null; this._hover = null; writeRange(k); }, { small: true });
        // nothing to draw at all: say so, no empty clock
        if (!d.sun.points.length && !d.price.steps.length && d.price.price === null && !d.rows.length && this._sunFallbackKwh(d) === null) {
            return this._sec(t('next_price_and_plan'), html`<p class="help">${t('next_plan_none')}</p>`, { cls: 'span2', extra: seg0() });
        }
        const { lay, svg: chart } = this._chartSvg(d, plan);
        const fb = focusBlock(d.rows, d.now, this._picked);
        const seg = seg0();
        const body = html`
            <div class="pc" style="padding-left:${lay.LBL}px;height:${lay.H}px">${this._labels(d, lay)}${chart}${this._tooltip(d, lay)}</div>
            ${fb ? html`<div class="reason" style="--c:${KIND_COLOR[fb.row.kind] || C.home}">${this._icon(fb.run ? 'mdi:play-circle' : 'mdi:clock-outline')}
                    <div class="t"><b>${this._rowName(fb.row)}</b> · ${this._hhmm(new Date(fb.s))} – ${this._hhmm(new Date(fb.e))}${fb.kwh > 0.05 ? ' · ' + this._kwh(fb.kwh) : ''}
                    <div class="sm muted">${this._focusReason(fb, plan)}</div></div></div>` : nothing}
            <div class="btns" style="margin-top:10px">${this._stripPills(plan)}</div>`;
        return this._sec(t('next_price_and_plan'), body, { cls: 'span2', extra: seg });
    }

    // ── per device ──
    _windowOf(blocks, id) {
        const mine = blocks.filter((b) => b.id === id && Number.isFinite(Date.parse(b.start)) && Number.isFinite(Date.parse(b.end)))
            .sort((p, q) => Date.parse(p.start) - Date.parse(q.start));
        if (!mine.length) return '';
        return `${this._hhmm(mine[0].start)} – ${this._hhmm(mine[mine.length - 1].end)}`;
    }

    _devRow(icon, color, name, rest, sub, btns, tip = '') {
        return html`<div class="row" style="--c:${color}" title=${tip || nothing}><div class="k">${this._icon(icon)}<span class="t"><b>${name}</b>${rest ? html` · ${rest}` : nothing}${sub ? html`<br><span class="sm muted">${sub}</span>` : nothing}</span></div>${btns.length ? html`<div class="btns">${btns}</div>` : nothing}</div>`;
    }

    _overrideOf(deviceId) {
        const ov = this._attrs('sensor.sem_charging_state').per_charger_plan_override || {};
        const rec = ov[deviceId] || this._local[deviceId] || null;
        return rec && rec.action ? { action: String(rec.action), until: String(rec.until || '') } : null;
    }

    _overrideText(ov) {
        const word = this._t('next_override_' + ov.action);
        return ov.until ? this._tf('next_override_until', { action: word, time: ov.until }) : word;
    }

    _chargerRow(cid, plan, blocks, demands, notSched) {
        const t = (k) => this._t(k);
        const obs = this._obs();
        const id = `ev:${cid}`;
        const sel = `select.sem_charger_${cid}_charge_mode`;
        const mode = this._str(sel);
        const win = this._windowOf(blocks, id);
        const kwh = kwhOf(blocks, (x) => x === id);
        const d = demands.find((x) => x.id === id);
        const ns = notSched.find((x) => x.id === id);
        const bits = [];
        if (d?.note) bits.push(String(d.note));
        else if (d?.status) bits.push(t('next_status_' + d.status));
        else if (ns) bits.push(this._whyText(ns));
        else if (!win) bits.push(t('next_nothing_planned'));
        if (mode) bits.push(this._tf('next_mode_now', { mode: t('charge_mode_' + mode) || mode }));
        const ov = this._overrideOf(cid);
        if (ov) bits.push(this._overrideText(ov));
        const btns = [];
        const full = (ns?.why || ns?.reason) === 'car_full';
        if (full && !ov) {
            // a full car has nothing to skip or start
        } else if (this._confirm === cid) {
            btns.push(this._btn(t('next_confirm'), () => this._chargeNow(cid, plan), { small: true, primary: true, disabled: obs }));
            btns.push(this._btn(t('next_cancel'), () => { this._confirm = null; }, { small: true }));
        } else if (ov) {
            btns.push(this._btn(t('next_back_to_plan'), () => this._overrideClear(cid), { small: true, disabled: obs }));
        } else {
            btns.push(this._btn(t('next_skip'), () => this._override(cid, 'skip', minutesToPlanEnd(plan, new Date()), plan), { small: true, disabled: obs }));
            btns.push(this._btn(t('next_start_now'), () => this._override(cid, 'force', minutesToPlanEnd(plan, new Date()), plan), { small: true, primary: true, disabled: obs }));
            if (mode) btns.push(this._btn(t('next_charge_now'), () => { this._confirm = cid; }, { small: true, ghost: true, disabled: obs || mode === 'always_max' }));
        }
        const rest = win ? `${win}${kwh > 0.05 ? ' · ' + this._kwh(kwh) : ''}` : '';
        return this._devRow('mdi:car-electric', C.ev, this._chargerName(cid), rest, bits.join(' · '), btns);
    }

    _batteryRow(plan, blocks, demands) {
        const t = (k) => this._t(k);
        const obs = this._obs();
        const floor = this._num('sensor.sem_battery_dynamic_floor_pct');
        const slots = Array.isArray(plan.slots) ? plan.slots : [];
        const runs = Array.isArray(plan.batt_runs) ? plan.batt_runs : [];
        const parts = [];
        const soc = this._num('sensor.sem_battery_soc');
        if (floor !== null && soc !== null) {
            parts.push(this._tf(soc < floor ? 'next_batt_below_floor' : 'next_batt_above_floor', { floor: Math.round(floor), soc: Math.round(soc) }));
        }
        const inWin = this._windowOf(blocks.filter((b) => String(b.id).startsWith('battery')).map((b) => ({ ...b, id: 'battery' })), 'battery');
        if (inWin) parts.push(`${t('next_battery_charging')} ${inWin}`);
        const first = runs.length && Array.isArray(runs[0]) ? slots[runs[0][0]] : null;
        const last = runs.length && Array.isArray(runs[runs.length - 1]) ? slots[runs[runs.length - 1][1]] : null;
        if (first && last) parts.push(`${t('next_to_house')} ${this._hhmm(first.start)} – ${this._hhmm(last.end)}`);
        const d = demands.find((x) => String(x.id).startsWith('battery'));
        const arb = plan.arbitrage;
        const sub = d?.note ? String(d.note) : (this._whyCodes(plan) || (arb && arb.enabled && arb.reason ? String(arb.reason) : ''));
        const mode = this._str('select.sem_battery_mode');
        const options = this._attrs('select.sem_battery_mode').options || [];
        const btns = [];
        // A one-off force is an override to undo; any other mode is the user's standing choice.
        if (mode === 'force_charge' || mode === 'force_discharge') {
            if (options.includes('auto')) btns.push(this._btn(t('next_back_to_plan'), () => this._selectOption('select.sem_battery_mode', 'auto'), { small: true, disabled: obs }));
        } else if (mode && options.includes('force_discharge')) {
            btns.push(this._btn(t('next_sell'), () => this._selectOption('select.sem_battery_mode', 'force_discharge'), { small: true, disabled: obs }));
        }
        const modeText = mode && mode !== 'auto' ? this._tf('next_mode_now', { mode: t('battery_mode_' + mode) || mode }) : '';
        return this._devRow('mdi:home-battery', C.battery_out, t('next_src_battery'), parts.join(' · '), [sub, modeText].filter(Boolean).join(' · '), btns, plan.why ? String(plan.why) : '');
    }

    _loadRow(id, plan, blocks, demands, notSched) {
        const t = (k) => this._t(k);
        const obs = this._obs();
        const keepRun = id.startsWith('comfort:');
        const key = id.replace(/^(load|comfort):/, '');
        const d = demands.find((x) => x.id === id);
        const ns = notSched.find((x) => x.id === id);
        const name = (this._devices()[key]?.name || d?.label || ns?.label || key) + (keepRun ? this._toKeep(key) : '');
        const win = this._windowOf(blocks, id);
        const kwh = win ? kwhOf(blocks, (x) => x === id) : Number(d?.planned_kwh) || 0;
        const bits = [];
        if (d?.note) bits.push(String(d.note));
        else if (d?.status) bits.push(t('next_status_' + d.status));
        else if (ns) bits.push(this._whyText(ns));
        const ov = this._overrideOf(key);
        if (ov) bits.push(this._overrideText(ov));
        const btns = [];
        // A load takes no one-off override: SEM acts on one only for a
        // charger or the battery (the service refuses any other id). A
        // stored one from before can still be cleared.
        if (ov) btns.push(this._btn(t('next_back_to_plan'), () => this._overrideClear(key), { small: true, disabled: obs }));
        const rest = win ? `${win}${kwh > 0.05 ? ' · ' + this._kwh(kwh) : ''}` : t('next_not_scheduled');
        return this._devRow('mdi:power-plug', C.home, name, rest, bits.join(' · '), btns);
    }

    _deviceSec(plan) {
        const t = (k) => this._t(k);
        const blocks = Array.isArray(plan.blocks) ? plan.blocks : [];
        const demands = Array.isArray(plan.demands) ? plan.demands : [];
        const notSched = Array.isArray(plan.not_scheduled) ? plan.not_scheduled : [];
        const rows = this._chargers.map((cid) => this._chargerRow(cid, plan, blocks, demands, notSched));
        const hasBattery = plan.has_battery !== false
            && (this._has('select.sem_battery_mode') || blocks.some((b) => String(b.id).startsWith('battery')) || (Array.isArray(plan.batt_runs) && plan.batt_runs.length > 0));
        if (hasBattery) rows.push(this._batteryRow(plan, blocks, demands));
        const loadIds = new Set();
        // (#1321) a heater's Keep at run (comfort:<id>) is listed like its run time
        const isLoad = (x) => String(x.id).startsWith('load:') || String(x.id).startsWith('comfort:');
        for (const d of demands) if (isLoad(d)) loadIds.add(String(d.id));
        for (const b of blocks) if (isLoad(b)) loadIds.add(String(b.id));
        for (const n of notSched) if (isLoad(n)) loadIds.add(String(n.id));
        // one row per heater: its Keep at run speaks for it, so a run-time
        // entry that only says "not scheduled" is dropped beside it
        const hasBlock = (id) => blocks.some((b) => String(b.id) === id);
        for (const id of [...loadIds]) {
            if (id.startsWith('load:') && !hasBlock(id) && hasBlock('comfort:' + id.slice(5))) loadIds.delete(id);
        }
        for (const id of loadIds) rows.push(this._loadRow(id, plan, blocks, demands, notSched));
        // …and a heater that is below its line with no hour says so, not nothing
        for (const h of this._cold(plan)) {
            if (loadIds.has('comfort:' + h.id) || loadIds.has('load:' + h.id)) continue;
            rows.push(this._devRow('mdi:thermometer-alert', C.home, h.name,
                t('next_not_scheduled'),
                this._tf(h.time ? 'hq_plan_below_no_hour' : 'hq_plan_below_no_hour_plain', { name: h.name, keep: h.keep, time: h.time }), []));
        }
        if (!rows.length) return nothing;
        return this._sec(t('next_per_device'), html`<div class="rows">${rows}</div>
            <p class="help">${this._obs() ? t('next_observing_hint') : t('next_override_help')}</p>`);
    }

    async _override(deviceId, action, minutes, plan) {
        const mins = Math.max(1, Math.min(1440, Math.round(Number(minutes) || 60)));
        if (!await this._callService(DOMAIN, 'plan_override', { device_id: deviceId, action, minutes: mins })) return;
        this._local = { ...this._local, [deviceId]: { action, until: this._hhmm(new Date(Date.now() + mins * 60e3)) } };
        this._localStamp = String(plan?.computed_at || '');
        this.requestUpdate();
    }

    async _overrideClear(deviceId) {
        if (!await this._callService(DOMAIN, 'plan_override_clear', { device_id: deviceId })) return false;
        const { [deviceId]: _gone, ...rest } = this._local;
        this._local = rest;
        this.requestUpdate();
        return true;
    }

    // "Charge now" is the backend's own one-off force: it runs the charger
    // at full power for a set time, then lets go by itself. Nothing is stored
    // in the browser and the charge mode select is left alone.
    async _chargeNow(cid, plan) {
        this._confirm = null;
        await this._override(cid, 'force', CHARGE_NOW_MINUTES, plan);
    }

    // ── expected ──
    _expectedSec(plan, m) {
        const t = (k) => this._t(k);
        const obs = this._obs();
        const tiles = [];
        const cost = knownNum(plan.total_cost);
        if (Array.isArray(plan.blocks) && Number.isFinite(cost)) {
            const houseKwh = Number(plan.house_grid?.kwh);
            const gridKwh = kwhOf(plan.blocks, (id) => !String(id).startsWith('battery_out')) + (Number.isFinite(houseKwh) ? houseKwh : 0);
            tiles.push({ label: t('next_grid_cost'), value: this._fmt(cost, 2), unit: this._currency(), sub: `${this._kwh(gridKwh)} · ${t('next_tonight')}` });
        }
        // (#1321) what waiting for the planned hours saves; no field, no tile
        const saved = knownNum(plan.saved);
        if (Number.isFinite(saved)) {
            tiles.push({ label: t('next_saved_by_plan'), value: this._fmt(saved, 2), unit: this._currency(), sub: t('next_vs_now'), valueColor: C.good });
        }
        const sun = this._num('sensor.sem_forecast_tomorrow_kwh');
        if (sun !== null) {
            const trust = this._num('sensor.sem_forecast_trust_d2');
            const sub = trust !== null && trust > 0 && trust <= 1.5
                ? `${t('next_forecast')} · ${this._tf('next_trusted', { pct: Math.round(trust * 100) })}` : t('next_forecast');
            tiles.push({ label: t('next_sun_tomorrow'), value: this._fmt(sun, 1), unit: 'kWh', sub });
        }
        const rows = [];
        const arb = plan.arbitrage;
        if (arb && arb.enabled) {
            const profit = Number(arb.est_profit);
            rows.push(this._row('mdi:swap-vertical', t('next_arbitrage'), arb.opportunity ? (Number.isFinite(profit) ? this._money(profit) : t('next_yes')) : t('next_off'), arb.reason || ''));
        }
        if (this._has('switch.sem_energy_plan_actuation')) {
            const on = this._str('switch.sem_energy_plan_actuation') === 'on';
            rows.push(this._row('mdi:toggle-switch-outline', t('next_plan_acts'),
                this._btn(on ? t('next_on') : t('next_off'), () => this._toggleSwitch('switch.sem_energy_plan_actuation'), { small: true, primary: on, disabled: obs }),
                t('next_actuation_sub')));
        }
        rows.push(this._row('mdi:sync', t('next_replan'),
            this._btn(t('next_now_btn'), () => this._callService(DOMAIN, 'replan', {}), { small: true, disabled: obs }),
            m.computedAt ? this._tf('next_replan_last', { time: this._hhmm(m.computedAt) }) : ''));
        return this._sec(t('next_expected'), html`${tiles.length ? this._tiles(tiles, { three: tiles.length === 3 }) : nothing}
            <div class="rows" style="margin-top:8px">${rows}</div>`);
    }

    // ── decisions today ──
    _logRow(rec, many) {
        const t = (k) => this._t(k);
        const tz = this._hass?.config?.time_zone;
        const lang = this._hass?.language || 'en';
        const kind = WHY_KINDS[rec.device_kind] || WHY_KINDS.load;
        const plain = plainReason(rec, t);
        const why = plain || rec.text || '';
        return html`<div class="row" style="--c:${kind.color}"><div class="k"><span class="dim num sm tm">${rowTime(rec.time, lang, new Date(), tz)}</span>
            <span class="t"><b>${deviceName(rec, t, many[rec.device_kind] > 1)}</b> · ${changeLabel(rec, t)}${rec.observer ? html` ${this._pill(t('why_observer'), 'warn')}` : nothing}
            ${why ? html`<br><span class="sm muted" title="${plain ? rec.text || '' : ''}">${why}</span>` : nothing}</span></div></div>`;
    }

    _decisionsSec() {
        const t = (k) => this._t(k);
        const all = this._records || [];
        const chips = whyChips(all, t);
        const chip = chips.some((c) => c.key === this._chip) ? this._chip : '';
        const many = {};
        for (const c of chips) many[c.kind] = (many[c.kind] || 0) + 1;
        const rows = filterRecords(all, chip);
        const tz = this._hass?.config?.time_zone;
        const todays = rows.filter((r) => isToday(r.time, new Date(), tz));
        const shown = (todays.length ? todays : rows).slice(0, SHOWN_ROWS);
        const earlier = rows.slice(shown.length);
        const body = html`
            ${chips.length ? this._seg([{ key: '', label: t('why_all') }, ...chips.map((c) => ({ key: c.key, label: c.name }))], chip, (k) => { this._chip = k; }, { small: true }) : nothing}
            ${this._logError ? html`<p class="help">${t('why_load_error')}</p>` : nothing}
            ${this._records !== null && !rows.length && !this._logError ? html`<p class="help">${t('why_empty')}</p>` : nothing}
            <div class="rows" style="margin-top:8px">${shown.map((r) => this._logRow(r, many))}${this._fold ? earlier.map((r) => this._logRow(r, many)) : nothing}</div>
            ${earlier.length ? this._link(this._fold ? t('next_less') : this._tf(earlierKey(earlier, new Date(), tz), { n: earlier.length }) + ' ›', () => { this._fold = !this._fold; }) : nothing}`;
        return this._sec(t('next_decisions_today'), body);
    }

    // ── lead ──
    _lead(plan, m) {
        if (this._range === 'tomorrow') {
            const sun = this._num('sensor.sem_forecast_tomorrow_kwh');
            const sunLine = sun !== null ? this._tf('next_plan_tmw_main', { sun: this._fmt(sun, 1) }) : '';
            const tmw = plan.tomorrow;
            if (!tmw) return { main: this._t('next_plan_tmw_none'), sub: sunLine };
            return { main: sunLine || this._t('next_plan_tmw_plain'), sub: this._t(tmw.prices === 'final' ? 'next_plan_tmw_sub_final' : 'next_plan_tmw_sub_prelim') };
        }
        const lead = planLead(plan, {
            computedAt: m.computedAt ? this._hhmm(m.computedAt) : '',
            cost: Number.isFinite(knownNum(m.cost)) ? this._money(knownNum(m.cost)) : '',
            fitsKey: m.fits === undefined ? '' : this._t(m.fits ? 'next_fits_yes' : 'next_fits_no'),
            sunTomorrowKwh: this._num('sensor.sem_forecast_tomorrow_kwh'),
            cold: this._cold(plan)[0] || null,
        });
        const flat = (this._str('sensor.sem_tariff_price_level') || 'flat') === 'flat';
        const main = this._tf(lead.main.key, lead.main.params);
        const sub = lead.sub ? this._tf(lead.sub.key, lead.sub.params) + (flat ? ' ' + this._t('next_one_rate_sub') : '') : '';
        return { main, sub };
    }

    render() {
        if (!this._hass) return nothing;
        const plan = this._plan();
        const stamp = String(plan.computed_at || '');
        if (stamp !== this._localStamp) { this._local = {}; this._localStamp = stamp; }
        const m = this._model();
        return this._frame(this._lead(plan, m), html`<div class="grid">
            ${this._stripSec(plan)}
            ${this._deviceSec(plan)}
            ${this._expectedSec(plan, m)}
            ${this._decisionsSec()}
        </div>`);
    }
}

semDefineCard('sem-next-plan-card', SEMNextPlanCard, {
    type: 'sem-next-plan-card',
    name: 'SEM · Plan',
    description: 'Sun, price and plan on one clock, the plan per device, the one-night overrides and today\'s decisions',
    documentationURL:
        'https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-next-plan-card',
    preview: true,
});

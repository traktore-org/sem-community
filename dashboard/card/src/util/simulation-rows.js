/**
 * (#1083) The Simulation tab's card, as pure helpers.
 *
 * Days come from `solar_energy_management/simulation/days` as ISO dates
 * ('YYYY-MM-DD', the install's own calendar). A run takes one period
 * (from … to); day types filter the result afterwards. Every simulated
 * number is modelled, not measured: the card marks each one "est."
 * (ESTIMATED).
 */

/** One glyph per tag. `negative` prices share the cheap glyph. */
export const TAG_GLYPH = {
    sunny: '☀️', mixed: '⛅', grey: '☁️', car: '🚗', cheap: '💸', negative: '💸', gap: '⚠️',
};

const GLYPH_ORDER = ['sunny', 'mixed', 'grey', 'car', 'cheap', 'negative', 'gap'];

/** The glyphs of a day's tags, sky first; one 💸 even with cheap AND negative. */
export function tagGlyphs(tags) {
    const have = new Set(tags || []);
    const out = [];
    for (const t of GLYPH_ORDER) {
        if (have.has(t) && !out.includes(TAG_GLYPH[t])) out.push(TAG_GLYPH[t]);
    }
    return out.join('');
}

/** A gap day has no full data: it never counts as a day of the period. */
export function isSelectable(day) {
    if (!day) return false;
    if (day.selectable === false) return false;
    return !(day.tags || []).includes('gap');
}

/**
 * A run is one continuous period: a battery carries its charge from one day
 * to the next, so single days cannot be replayed on their own. The quick
 * periods, in the order the card shows them; a month and the "most recent
 * days" slider pick a period too.
 */
export const PERIOD_PICKS = ['last30', 'last90', 'last365'];

const LAST_N = { last30: 30, last90: 90, last365: 365 };

/** The largest battery a what-if may try, in kWh: a car pack (up to ~150 kWh)
 * as home storage. Above the setup's 100 kWh on purpose; the backend
 * (`simulation_ws.SIM_CAPACITY`) holds the same number. */
export const SIM_CAPACITY_MAX_KWH = 150;

const stored = (days) => (days || []).filter(isSelectable).map(d => String(d.date)).sort();

/** `{from, to}` spanning the stored days of `dates` (sorted), or null. */
function spanOf(dates) {
    return dates.length ? { from: dates[0], to: dates[dates.length - 1] } : null;
}

/** How far the "most recent days" slider reaches: every stored day. */
export function recentMax(days) {
    return stored(days).length;
}

/** The period from the `n`-th newest stored day to the newest, or null. One
 * drag on a phone instead of a tap per day. */
export function recentPeriod(days, n) {
    const ok = stored(days);
    const k = Math.max(0, Math.min(ok.length, Math.round(Number(n) || 0)));
    return k ? spanOf(ok.slice(ok.length - k)) : null;
}

/** Where the slider stands: `n` when the period is exactly the newest `n`
 * stored days, else null (a quick period or a month picked it). */
export function recentAt(days, period) {
    if (!period) return 0;
    const ok = stored(days);
    const inside = ok.filter(d => d >= period.from && d <= period.to);
    if (!inside.length || inside[inside.length - 1] !== ok[ok.length - 1]) return null;
    const want = recentPeriod(days, inside.length);
    return want && want.from === period.from && want.to === period.to ? inside.length : null;
}

/** The months the stored days cover, newest first ('YYYY-MM'). */
export function monthsOf(days) {
    const out = new Set((days || []).map(d => String(d.date || '').slice(0, 7)).filter(Boolean));
    return [...out].sort().reverse();
}

/** The period of one month ('YYYY-MM'): its first to its last stored day. */
export function monthPeriod(days, month) {
    return spanOf(stored(days).filter(d => d.slice(0, 7) === month));
}

function isoMinusDays(today, n) {
    const d = new Date(Date.UTC(today.getFullYear(), today.getMonth(), today.getDate()));
    d.setUTCDate(d.getUTCDate() - n);
    return d.toISOString().slice(0, 10);
}

/** A quick period: the stored days of the last N days before today. */
export function periodOf(days, pick, today = new Date()) {
    const n = LAST_N[pick];
    if (!n) return null;
    const from = isoMinusDays(today, n);
    const to = isoMinusDays(today, 0);
    return spanOf(stored(days).filter(d => d >= from && d < to));
}

/** The quick period the period equals, or null. */
export function activePeriod(days, period, today = new Date()) {
    if (!period) return null;
    for (const pick of PERIOD_PICKS) {
        const p = periodOf(days, pick, today);
        if (p && p.from === period.from && p.to === period.to) return pick;
    }
    return null;
}

/** How many stored days the period holds (gap days are left out). */
export function periodDays(days, period) {
    if (!period) return 0;
    return stored(days).filter(d => d >= period.from && d <= period.to).length;
}

/** How many stored days inside the period are left out as gaps. */
export function periodGaps(days, period) {
    if (!period) return 0;
    return (days || []).filter(d => !isSelectable(d)
        && String(d.date) >= period.from && String(d.date) <= period.to).length;
}

/** '2026-10-13' → '13.10' */
export function chipDate(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ''));
    return m ? `${m[3]}.${m[2]}` : String(iso || '');
}

/** '2026-10-13' → 'Mon 13.10' (weekday in the user's language). */
export function rowDate(iso, lang = 'en') {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ''));
    if (!m) return String(iso || '');
    const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
    let wd = '';
    try {
        wd = new Intl.DateTimeFormat(lang, { weekday: 'short', timeZone: 'UTC' }).format(d);
    } catch (_err) {
        wd = new Intl.DateTimeFormat('en', { weekday: 'short', timeZone: 'UTC' }).format(d);
    }
    return `${wd} ${m[3]}.${m[2]}`;
}

const MINUS = '−';

/** A money amount with two decimals and a real minus sign; '—' for none. */
export function money(value) {
    const v = Number(value);
    if (value === null || value === undefined || !Number.isFinite(v)) return '—';
    const r = Math.round(v * 100) / 100;
    if (r === 0) return '0.00';
    return (r < 0 ? MINUS : '') + Math.abs(r).toFixed(2);
}

/**
 * A difference (simulated − actual) with its sign and colour class:
 * below 0 the what-if is cheaper (green), above 0 dearer (orange).
 */
export function formatDelta(value) {
    const v = Number(value);
    if (value === null || value === undefined || !Number.isFinite(v)) {
        return { text: '—', cls: 'same' };
    }
    const r = Math.round(v * 100) / 100;
    if (r === 0) return { text: '0.00', cls: 'same' };
    return r < 0
        ? { text: MINUS + Math.abs(r).toFixed(2), cls: 'cheaper' }
        : { text: '+' + r.toFixed(2), cls: 'dearer' };
}

/** delta ÷ actual as a signed percent ('−6.7 %'), or '' when actual is 0. */
export function formatPct(delta, actual) {
    const a = Number(actual);
    const d = Number(delta);
    if (!Number.isFinite(a) || !Number.isFinite(d) || a === 0) return '';
    const p = Math.round((d / Math.abs(a)) * 1000) / 10;
    if (p === 0) return '0.0 %';
    return (p < 0 ? MINUS : '+') + Math.abs(p).toFixed(1) + ' %';
}

/** The columns whose numbers are modelled. Actual cost is measured. */
export const ESTIMATED = ['simulated', 'delta'];

/** Does this column's number carry the "est." badge? */
export function needsEst(column) {
    return ESTIMATED.includes(column);
}
/** Result rows newest first; the first `limit` shown unless expanded. */
export function visibleRows(days, expanded = false, limit = 8) {
    const rows = [...(days || [])].sort((a, b) => String(b.date).localeCompare(String(a.date)));
    if (expanded || rows.length <= limit) return { rows, more: 0 };
    return { rows: rows.slice(0, limit), more: rows.length - limit };
}

/** The day types a result can be filtered by. A filter never changes what
 * was simulated: it shows the days of that type and their totals. */
export const FILTERS = ['sunny', 'mixed', 'grey', 'car', 'cheap'];

/** The result's days of one type (`null` = every day). */
export function filterRows(days, tag) {
    const all = days || [];
    return tag ? all.filter(d => (d.tags || []).includes(tag)) : all;
}

/** The day-type tiles — the filter buttons: the three skies and the car
 * always, cheap when it ran. `active` marks the one that filters. */
export function tagTiles(perTag, total, active = null) {
    const all = Number(total?.days) || 0;
    const tiles = [];
    for (const tag of FILTERS) {
        const t = perTag?.[tag] || {};
        const n = Number(t.days) || 0;
        if (tag === 'cheap' && n === 0) continue;
        const sky = tag === 'sunny' || tag === 'mixed' || tag === 'grey';
        tiles.push({
            tag,
            glyph: TAG_GLYPH[tag],
            days: n,
            of: sky ? null : all,
            delta: n ? formatDelta(t.delta) : null,
            actual: n ? Number(t.actual) || 0 : null,
            simulated: n ? Number(t.simulated) || 0 : null,
            on: active === tag,
        });
    }
    return tiles;
}

/** The totals one filter shows: a day type's, or the whole run's. */
export function totalFor(result, tag) {
    if (!tag) return result?.total || {};
    return result?.per_tag?.[tag] || { days: 0 };
}

/** The total line's numbers. `net` is the difference with the stored energy
 * counted — what the what-if saves once the pack's leftover is valued. */
export function totalLine(total) {
    const t = total || {};
    const net = t.net_delta ?? null;
    return {
        days: Number(t.days) || 0,
        actual: money(t.actual),
        simulated: money(t.simulated),
        delta: formatDelta(t.delta),
        net: net === null ? null : formatDelta(net),
        pct: formatPct(t.delta, t.actual),
        kwhOverLimit: Number(t.kwh_over_limit) || 0,
        indicativeDays: Number(t.indicative_days) || 0,
    };
}

const kwh = (v) => {
    const n = Number(v);
    return v === null || v === undefined || !Number.isFinite(n) ? '—' : n.toFixed(1);
};

/** What a tapped day row opens: grid in and out, battery in and out and the
 * pack's level at the day's end, actual → simulated, and why. */
export function dayDetail(row) {
    const r = row || {};
    const pair = (key) => ({ actual: kwh(r[`actual_${key}_kwh`]), simulated: kwh(r[`simulated_${key}_kwh`]) });
    return {
        lines: [
            { key: 'sim_grid_in', ...pair('grid_import') },
            { key: 'sim_grid_out', ...pair('grid_export') },
            { key: 'sim_batt_in', ...pair('battery_charge') },
            { key: 'sim_batt_out', ...pair('battery_discharge') },
            { key: 'sim_pack_end', actual: kwh(r.actual_end_kwh), simulated: kwh(r.simulated_end_kwh) },
        ],
        net: r.net_delta === undefined || r.net_delta === null ? null : formatDelta(r.net_delta),
        story: [...(r.story || [])],
    };
}

/** The difference per month, oldest first, and the months where the what-if
 * helps (its difference with the pack's gain counted is below 0). */
export function monthRows(months) {
    const rows = (months || []).map(m => ({
        month: String(m.month || ''),
        days: Number(m.days) || 0,
        delta: formatDelta(m.net_delta ?? m.delta),
        value: Number(m.net_delta ?? m.delta) || 0,
    }));
    const peak = Math.max(0, ...rows.map(r => Math.abs(r.value)));
    for (const r of rows) r.share = peak > 0 ? Math.abs(r.value) / peak : 0;
    const helps = rows.filter(r => Math.round(r.value * 100) < 0).map(r => r.month);
    return { rows, helps };
}

/** Energy, actual → simulated: the lines the result shows under the total. */
export function energyRows(energy) {
    const a = energy?.actual || {};
    const s = energy?.simulated || {};
    if (!energy?.actual && !energy?.simulated) return [];
    const pct = (v) => (v === null || v === undefined ? '—' : `${Number(v).toFixed(1)} %`);
    const num = (v) => (v === null || v === undefined ? '—' : Number(v).toFixed(1));
    return [
        { key: 'sim_grid_in', actual: kwh(a.grid_import_kwh), simulated: kwh(s.grid_import_kwh), unit: 'kWh' },
        { key: 'sim_grid_out', actual: kwh(a.grid_export_kwh), simulated: kwh(s.grid_export_kwh), unit: 'kWh' },
        { key: 'sim_self_use', actual: pct(a.self_consumption_pct), simulated: pct(s.self_consumption_pct), unit: '' },
        { key: 'sim_cycles', actual: num(a.cycles), simulated: num(s.cycles), unit: '' },
    ];
}

/** The form a fresh card starts with: the install as configured. */
export function initialForm(defaults) {
    const d = defaults || {};
    return {
        capacity_kwh: d.capacity_kwh ?? '',
        reserve_pct: d.reserve_pct ?? '',
        peak_limit_kw: d.peak_limit_kw ?? '',
        import_mode: 'recorded',
        import_rate: d.import_rate ?? '',
        export_mode: 'recorded',
        export_rate: d.export_rate ?? '',
        battery_mode: d.battery_mode ?? 'auto',
        ev_mode: 'recorded',
        max_charge_w: d.max_charge_w ?? '',
        max_discharge_w: d.max_discharge_w ?? '',
        // extra kWp needs the install's size; without it the form asks a factor
        pv_mode: d.system_size_kwp ? 'kwp' : 'factor',
        pv_extra_kwp: '',
        pv_factor: 1,
        battery_to_ev: d.battery_to_ev !== false,
    };
}

/** SEM's battery modes and the car's charge modes a what-if offers. */
export const BATTERY_MODES = ['auto', 'self_consumption', 'force_charge', 'force_discharge', 'off'];
export const EV_MODES = ['recorded', 'solar_only', 'solar_plus_battery', 'solar_plus_cheap',
    'min_plus_solar', 'always_max', 'off'];

const numOrNull = (v) => {
    if (v === '' || v === null || v === undefined) return null;
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
};

/** Is this form field different from what the install has? */
export function isChanged(field, form, defaults) {
    const f = form || {};
    const d = defaults || {};
    if (field === 'import_rate') return f.import_mode === 'flat';
    if (field === 'export_rate') return f.export_mode === 'flat';
    if (field === 'battery_mode') return (f.battery_mode || 'auto') !== (d.battery_mode || 'auto');
    if (field === 'ev_mode') return (f.ev_mode || 'recorded') !== 'recorded';
    if (field === 'battery_to_ev') return (f.battery_to_ev !== false) !== (d.battery_to_ev !== false);
    if (field === 'pv') {
        return f.pv_mode === 'kwp' ? (numOrNull(f.pv_extra_kwp) || 0) !== 0
            : (numOrNull(f.pv_factor) ?? 1) !== 1;
    }
    const now = numOrNull(d[field]);
    const want = numOrNull(f[field]);
    return now !== want;
}

/** The `params` the `start` command takes, from the form. */
export function buildParams(form) {
    const f = form || {};
    const out = {
        capacity_kwh: numOrNull(f.capacity_kwh),
        reserve_pct: numOrNull(f.reserve_pct),
    };
    const peak = numOrNull(f.peak_limit_kw);
    out.peak_limit_kw = peak && peak > 0 ? peak : null;
    for (const key of ['import', 'export']) {
        const rate = numOrNull(f[`${key}_rate`]);
        out[`${key}_rate`] = f[`${key}_mode`] === 'flat' && rate !== null ? rate : 'recorded';
    }
    if (f.battery_mode) out.battery_mode = f.battery_mode;
    out.ev_mode = f.ev_mode || 'recorded';
    for (const key of ['max_charge_w', 'max_discharge_w']) {
        const w = numOrNull(f[key]);
        if (w !== null) out[key] = w;
    }
    if (f.pv_mode === 'kwp') {
        const extra = numOrNull(f.pv_extra_kwp);
        if (extra) out.pv_extra_kwp = extra;
    } else {
        const factor = numOrNull(f.pv_factor);
        if (factor !== null && factor !== 1) out.pv_factor = factor;
    }
    if (f.battery_to_ev === false) out.battery_to_ev = false;
    return out;
}

/** The scenarios: one tap fills the fields; the person can still edit them. */
export const PRESETS = ['plus_battery', 'plus_pv', 'cheap_chargers', 'no_battery_ev'];

/**
 * The form with a scenario laid over it. `plus_battery` doubles the size and
 * the power (a second pack of the same kind); `plus_pv` takes `extra` kWp (or,
 * without a known PV size, a factor); `cheap_chargers` puts the car on
 * Solar + cheap; `no_battery_ev` keeps the pack away from the car.
 */
export function applyPreset(form, defaults, preset, extra = null) {
    const f = { ...(form || initialForm(defaults)) };
    const d = defaults || {};
    const twice = (v, base) => {
        const n = numOrNull(v) ?? numOrNull(base);
        return n === null ? v : Math.round(n * 2 * 10) / 10;
    };
    switch (preset) {
    case 'plus_battery':
        f.capacity_kwh = twice(f.capacity_kwh, d.capacity_kwh);
        f.max_charge_w = twice(f.max_charge_w, d.max_charge_w);
        f.max_discharge_w = twice(f.max_discharge_w, d.max_discharge_w);
        break;
    case 'plus_pv': {
        const x = numOrNull(extra);
        if (x === null) break;
        if (d.system_size_kwp) {
            f.pv_mode = 'kwp';
            f.pv_extra_kwp = x;
        } else {
            f.pv_mode = 'factor';
            f.pv_factor = x;
        }
        break;
    }
    case 'cheap_chargers':
        f.ev_mode = 'solar_plus_cheap';
        break;
    case 'no_battery_ev':
        f.battery_to_ev = false;
        break;
    default:
        break;
    }
    return f;
}

/** Can a run start? A period picked, sizes set, nothing running. */
export function canRun(period, form, status) {
    if (status?.running) return false;
    if (!period?.from || !period?.to) return false;
    const p = buildParams(form);
    return p.capacity_kwh !== null && p.capacity_kwh > 0 && p.reserve_pct !== null;
}

/** The `start` command's message: the period and the form. */
export function buildStart(period, form) {
    return { from: period.from, to: period.to, params: buildParams(form) };
}

/** Minutes left (rounded up, at least 1), or null before the first day ends. */
export function minutesLeft(status, nowMs = Date.now()) {
    const done = Number(status?.done) || 0;
    const total = Number(status?.total) || 0;
    const started = Date.parse(status?.started_at || '');
    if (!done || !total || done >= total || !Number.isFinite(started)) return null;
    const per = (nowMs - started) / done;
    if (!(per > 0)) return null;
    return Math.max(1, Math.ceil((per * (total - done)) / 60000));
}

/** Progress as a share 0…1. */
export function progressShare(status) {
    const done = Number(status?.done) || 0;
    const total = Number(status?.total) || 0;
    return total > 0 ? Math.min(1, done / total) : 0;
}

/** Fill '{n}'-style holes in a translated string. */
export function fill(text, values) {
    let out = String(text || '');
    for (const [k, v] of Object.entries(values || {})) out = out.split(`{${k}}`).join(String(v));
    return out;
}

/**
 * The calibration check: did the own settings give back the real cost?
 * `{ ok, pct }` — `ok` false means the what-if numbers must not be shown.
 * An older run without the check counts as not checked (ok true).
 */
export function calibration(result) {
    const c = result?.calibration;
    const num = (v) => (v === null || v === undefined ? null : Number(v));
    if (!c || result?.calibrated === undefined) return { ok: true, caution: false, pct: null, days: null, leftOut: 0, carDays: 0, carPct: null, repriced: false };
    const pct = num(c.error_pct);
    const max = num(c.max_pct);
    return {
        ok: !!result.calibrated,
        // shown, but past the level where the numbers stand without a note
        caution: !!result.calibrated && pct !== null && max !== null && pct > max,
        pct,
        days: num(c.days),
        leftOut: Number(c.left_out) || 0,
        carDays: Number(c.car_days) || 0,
        carPct: num(c.car_error_pct),
        repriced: !!result.repriced,
    };
}

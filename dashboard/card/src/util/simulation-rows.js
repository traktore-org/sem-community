/**
 * (#1083) The Simulation tab's card, as pure helpers.
 *
 * Days come from `solar_energy_management/simulation/days` as ISO dates
 * ('YYYY-MM-DD', the install's own calendar). Every simulated number is
 * modelled, not measured: the card marks each one "est." (ESTIMATED).
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

/** A gap day cannot be picked. */
export function isSelectable(day) {
    if (!day) return false;
    if (day.selectable === false) return false;
    return !(day.tags || []).includes('gap');
}

/** The quick picks, in the order the card shows them. */
export const QUICK_PICKS = ['sunny', 'grey', 'car', 'last30', 'clear'];

/** The glyph a quick pick shows in front of its label. */
export const PICK_GLYPH = { sunny: '☀️', grey: '☁️', car: '🚗', last30: '', clear: '' };

function isoMinusDays(today, n) {
    const d = new Date(Date.UTC(today.getFullYear(), today.getMonth(), today.getDate()));
    d.setUTCDate(d.getUTCDate() - n);
    return d.toISOString().slice(0, 10);
}

function isoOf(today) {
    return isoMinusDays(today, 0);
}

/** The dates a quick pick selects, oldest first. Gap days never. */
export function pickDays(days, pick, today = new Date()) {
    const ok = (days || []).filter(isSelectable);
    switch (pick) {
    case 'sunny':
    case 'grey':
    case 'car':
        return ok.filter(d => (d.tags || []).includes(pick)).map(d => d.date);
    case 'last30': {
        const from = isoMinusDays(today, 30);
        const to = isoOf(today);
        return ok.filter(d => d.date >= from && d.date < to).map(d => d.date);
    }
    default:
        return [];
    }
}

/** The quick pick the selection equals, or null. `clear` = nothing picked. */
export function activePick(days, selected, today = new Date()) {
    const sel = [...(selected || [])].sort();
    if (!sel.length) return null;
    for (const pick of QUICK_PICKS) {
        if (pick === 'clear') continue;
        const want = pickDays(days, pick, today).slice().sort();
        if (want.length === sel.length && want.every((d, i) => d === sel[i])) return pick;
    }
    return null;
}

/** Flip one date in the selection; a gap day stays out. Returns a new Set. */
export function toggleDay(selected, day) {
    const out = new Set(selected || []);
    if (!isSelectable(day)) return out;
    if (out.has(day.date)) out.delete(day.date); else out.add(day.date);
    return out;
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

/** The day-type tiles: the three skies and the car always, cheap when it ran. */
export function tagTiles(perTag, total) {
    const all = Number(total?.days) || 0;
    const tiles = [];
    for (const tag of ['sunny', 'mixed', 'grey', 'car', 'cheap']) {
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
        });
    }
    return tiles;
}

/** The total line's numbers. */
export function totalLine(total) {
    const t = total || {};
    return {
        days: Number(t.days) || 0,
        actual: money(t.actual),
        simulated: money(t.simulated),
        delta: formatDelta(t.delta),
        pct: formatPct(t.delta, t.actual),
        kwhOverLimit: Number(t.kwh_over_limit) || 0,
        indicativeDays: Number(t.indicative_days) || 0,
    };
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
    };
}

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
    return out;
}

/** Can a run start? Days picked, sizes set, nothing running. */
export function canRun(selected, form, status) {
    if (status?.running) return false;
    if (!selected || ![...selected].length) return false;
    const p = buildParams(form);
    return p.capacity_kwh !== null && p.capacity_kwh > 0 && p.reserve_pct !== null;
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

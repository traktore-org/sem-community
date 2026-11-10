/**
 * (#1084) The Why? card's rows — pure helpers, no DOM.
 *
 * A record is one command change from the decision log, as the websocket
 * command `solar_energy_management/decision_log` hands it: newest first,
 * { time, device_id, device_kind, name, old, new, reason_code, params,
 *   text, inputs, observer }.
 */

/** How many rows Everyday keeps open; the rest sit in the fold. */
export const WHY_EVERYDAY_ROWS = 4;

/** Device colours from the palette: wallbox green, battery teal, house load cyan, grid export violet. */
export const WHY_KINDS = {
    charger: { icon: 'mdi:ev-station', color: '#8DC892' },
    battery: { icon: 'mdi:home-battery', color: '#4db6ac' },
    load: { icon: 'mdi:power-plug', color: '#5BC8D8' },
    // (#1174) the grid export limit, in the grid-export colour
    export: { icon: 'mdi:transmission-tower-export', color: '#8353d1' },
};

/** The verbs the log writes; each has a `why_verb_<verb>` key. */
export const WHY_VERBS = [
    'charge', 'stop', 'disable', 'park_off', 'normal', 'limit_discharge',
    'force_charge', 'stop_force_charge', 'force_discharge',
    'stop_force_discharge', 'off', 'on', 'restore',
    'limit_export', 'release_export',
];

export const chipKey = (rec) => `${rec?.device_kind || ''}:${rec?.device_id || ''}`;

/** A device's shown name: its own, or the kind's word when the log only has an id. */
export function deviceName(rec, t, many = false) {
    const own = rec?.name;
    if (own && own !== rec.device_id) return own;
    const word = t(`why_kind_${rec?.device_kind}`);
    if (!word || word === `why_kind_${rec?.device_kind}`) return own || rec?.device_id || '';
    return many ? `${word} ${rec.device_id}` : word;
}

/** The chips: one per device that has rows, in the order the rows meet them. */
export function whyChips(records, t) {
    const seen = new Map();
    for (const rec of records || []) {
        const key = chipKey(rec);
        if (!seen.has(key)) seen.set(key, rec);
    }
    const perKind = {};
    for (const rec of seen.values()) perKind[rec.device_kind] = (perKind[rec.device_kind] || 0) + 1;
    return [...seen.entries()].map(([key, rec]) => ({
        key, kind: rec.device_kind, name: deviceName(rec, t, perKind[rec.device_kind] > 1),
    }));
}

export function filterRecords(records, chip) {
    const rows = records || [];
    return chip ? rows.filter((r) => chipKey(r) === chip) : rows;
}

/** Everyday's open rows and the rows in the fold. */
export function splitRows(records, n = WHY_EVERYDAY_ROWS) {
    const rows = records || [];
    return { shown: rows.slice(0, n), earlier: rows.slice(n) };
}

/** `charge 8 A` → `8 A`; `limit_discharge 1500 W` → `limit discharge 1500 W`. */
export function commandLabel(cmd, t) {
    if (!cmd) return '';
    const [verb, ...rest] = String(cmd).split(' ');
    const value = rest.join(' ');
    if (verb === 'charge' && value) return value;
    const key = `why_verb_${verb}`;
    const word = t(key);
    const said = word && word !== key ? word : verb.replace(/_/g, ' ');
    return value ? `${said} ${value}` : said;
}

/** `8 A → off`, or only the new command when there was none before. */
export function changeLabel(rec, t) {
    const now = commandLabel(rec?.new, t);
    return rec?.old ? `${commandLabel(rec.old, t)} → ${now}` : now;
}

/**
 * (#1174) The row's reason as a plain sentence: the record's code looked
 * up as `why_reason_<code>`, its `{name}` placeholders filled from
 * `rec.params`. Null when the code has no sentence or a number it names
 * is missing; the card then shows the internal text instead.
 */
export function plainReason(rec, t) {
    const code = rec?.reason_code;
    if (!code) return null;
    const key = `why_reason_${code}`;
    const sentence = t(key);
    if (!sentence || sentence === key) return null;
    const params = rec.params || {};
    let missing = false;
    const out = String(sentence).replace(/\{(\w+)\}/g, (m, name) => {
        const v = params[name];
        if (v === undefined || v === null || v === '') { missing = true; return m; }
        return String(v);
    });
    return missing ? null : out;
}

const _num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null);

export function formatWatts(w) {
    const v = _num(w);
    if (v === null) return '';
    return Math.abs(v) >= 1000 ? `${(v / 1000).toFixed(1)} kW` : `${Math.round(v)} W`;
}

/**
 * The small line of what SEM decided on: [{ icon?, text }].
 * Sun and SOC carry an icon; prices and surplus a word.
 */
export function inputChips(inputs, t, currency = '') {
    const i = inputs || {};
    const out = [];
    const price = (v) => `${v.toFixed(2)}${currency ? ` ${currency}` : ''}/kWh`;
    if (_num(i.solar_w) !== null) out.push({ icon: 'mdi:white-balance-sunny', color: '#ff9800', text: formatWatts(i.solar_w) });
    if (_num(i.soc) !== null) out.push({ icon: 'mdi:battery-medium', color: '#4db6ac', text: `${Math.round(i.soc)} %` });
    if (_num(i.import_price) !== null) out.push({ text: `${t('why_in_import')} ${price(i.import_price)}` });
    if (_num(i.export_rate) !== null) out.push({ text: `${t('why_in_export')} ${price(i.export_rate)}` });
    if (_num(i.surplus_w) !== null) out.push({ text: `${t('why_in_surplus')} ${formatWatts(i.surplus_w)}` });
    if (_num(i.budget_w) !== null) out.push({ text: `${t('why_in_budget')} ${formatWatts(i.budget_w)}` });
    if (_num(i.target_soc) !== null) out.push({ text: `${t('why_in_target')} ${Math.round(i.target_soc)} %` });
    else if (_num(i.target_kwh) !== null && i.target_kwh > 0) out.push({ text: `${t('why_in_target')} ${i.target_kwh.toFixed(1)} kWh` });
    return out;
}

const _dayKey = (d, tz) => {
    try { return d.toLocaleDateString('en-CA', { timeZone: tz || undefined }); } catch (_e) { return d.toDateString(); }
};

/** Same calendar day as `now`, in the home's time zone. */
export function isToday(iso, now = new Date(), tz) {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return false;
    return _dayKey(d, tz) === _dayKey(now, tz);
}

/** `19:23` today, `Wed 19:23` before. */
export function rowTime(iso, lang = 'en', now = new Date(), tz) {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '—';
    const opts = { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: tz || undefined };
    let time;
    try { time = d.toLocaleTimeString(lang, opts); } catch (_e) { time = d.toLocaleTimeString([], opts); }
    if (isToday(iso, now, tz)) return time;
    let day;
    try { day = d.toLocaleDateString(lang, { weekday: 'short', timeZone: tz || undefined }); } catch (_e) { day = ''; }
    return day ? `${day} ${time}` : time;
}

/** The fold's label key: "Earlier today" when every folded row is from today. */
export function earlierKey(rows, now = new Date(), tz) {
    return (rows || []).every((r) => isToday(r.time, now, tz)) ? 'why_earlier_today' : 'why_earlier';
}

/** A change key for the newest rows on the three state sensors. */
export function lastDecisionStamp(states, prefix = 'sensor.sem_') {
    const maps = [
        states?.[`${prefix}charging_state`]?.attributes?.per_charger_last_decision,
        states?.[`${prefix}battery_status`]?.attributes?.per_battery_last_decision,
        states?.[`${prefix}load_management_status`]?.attributes?.per_device_last_decision,
    ];
    let newest = '';
    let count = 0;
    for (const m of maps) {
        for (const rec of Object.values(m || {})) {
            count += 1;
            const t = String(rec?.time || '');
            if (t > newest) newest = t;
        }
    }
    return `${count}|${newest}`;
}

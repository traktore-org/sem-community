/**
 * (#1084) The Why? card's rows — pure helpers, no DOM.
 *
 * A record is one command change from the decision log, as the websocket
 * command `solar_energy_management/decision_log` hands it: newest first,
 * { time, device_id, device_kind, name, old, new, reason_code, params,
 *   text, inputs, observer }.
 */


import { batterySentence } from './next-battery-line.js';
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
    // (#1323) a heat pump held below its normal state
    'step_down',
    // (#1427) a battery asked to limit that has no way to cap it
    'no_limit',
];

export const chipKey = (rec) => `${rec?.device_kind || ''}:${rec?.device_id || ''}`;

/** A device's shown name: its own, or the kind's word when the log only has an id. */
export function deviceName(rec, t, many = false) {
    const own = rec?.name;
    // a name that is only an id (primary, keba_fa87f74cd3) is not a name
    if (own && own !== rec.device_id && !/^[a-z0-9_:.-]+$/.test(String(own))) return own;
    const kind = rec?.device_kind || rec?.kind;
    const word = t(`why_kind_${kind}`);
    if (!word || word === `why_kind_${kind}`) return own || rec?.device_id || '';
    return many ? `${word} ${rec.device_id}` : word;
}

/**
 * (#1321) A command verb in words: `next_act_<verb>`; a verb with no text
 * reads as plain words (limit_export becomes "limit export"), never snake_case.
 */
export function actionWords(action, t) {
    const code = String(action || '').trim();
    if (!code) return '';
    if (code.includes('.')) return code;  // a service call (keba.set_current) stays as it is
    const key = `next_act_${code}`;
    const said = t(key);
    if (said && said !== key) return said;
    return code.replace(/[_\s]+/g, ' ').trim().toLowerCase();
}

// a load asked to "adjust power" whose reason says it stays on: say so (#1321)
const STAYS_ON = new Set(['min_run_hold']);

/** The verb a would-do row shows: the action in words; "keep on" when the reason says it only stays on. */
export function wouldVerb(rec, t) {
    if (String(rec?.action || '') === 'adjust' && STAYS_ON.has(rec?.reason_code)) return t('next_act_keep_on');
    return actionWords(rec?.action, t);
}

/** (#1321) A battery row (the record names its kind either way). */
export const isBattery = (rec) => (rec?.kind || rec?.device_kind) === 'battery';

/**
 * (#1321) Does the battery would-row set a limit? "Run normally" sets none, so it shows no limit.
 * (#1427) Nor does `no_limit`: SEM has no way to cap that battery, so no "limited to" figure.
 */
export const setsLimit = (rec) => /^limit_/.test(String(rec?.action || ''));

/** (#1321) "Run normally": no limit, no power to name. */
export const isNormal = (rec) => String(rec?.action || '') === 'normal';

/** (#1321) The decisions SEM would make in watch-only mode, from the observer switch's attributes. */
export function wouldList(attrs) {
    return Object.values((attrs && attrs.would_decisions) || {}).filter((d) => d && d.action && d.action !== 'idle');
}

/** (#1321) The would-decision of one Devices row (charger, battery or load), or null. */
export function wouldFor(row, decisions) {
    const bare = (id) => String(id || '').replace(/^(ev|battery|load):/, '');
    return (decisions || []).find((d) => {
        const kind = d.kind || d.device_kind;
        if (kind !== row.type) return false;
        if (row.type === 'battery') return true;
        return bare(d.device_id) === bare(row.type === 'charger' ? row.cid : row.id);
    }) || null;
}

/** (#1321) "Would switch on": the same words System › What SEM would do uses. */
export function wouldLine(rec, t) {
    const verb = wouldVerb(rec, t);
    return verb ? t('next_would_x').replace('{what}', verb) : '';
}

// (#1321) reason codes whose sentence says a load runs: for a load that is still off they mean "about to"
const START_CODES = ['solar', 'surplus', 'tier1_battery', 'cheap_grid', 'deadline', 'load_override_run'];

/** The start reason of a load that is off, or '' (a load that runs, or whose reason is no start). */
export function startCode(row, pill) {
    const code = String(row?.intent?.code || '');
    return row?.type === 'load' && pill?.key === 'next_st_off' && START_CODES.includes(code) ? code : '';
}

/** "would switch on: enough spare sun" (watch only) or "switches on soon: enough spare sun". One helper for every screen. */
export function startLine(code, watchOnly, t) {
    const key = 'why_short_' + code;
    const why = START_CODES.includes(code) ? t(key) : '';
    return why && why !== key ? `${t(watchOnly ? 'next_would_switch_on' : 'next_switches_soon')}: ${why}` : '';
}

/**
 * (#1321) A load's standing reason when the device is off: the start line, never "so it runs".
 * '' when the record is no load's start reason or the device runs; the caller keeps its own text then.
 */
export function offStartReason(rec, running, watchOnly, t) {
    const kind = rec && (rec.kind || rec.device_kind);
    if (kind !== 'load' || running) return '';
    return startLine(String(rec.reason_code || ''), watchOnly, t);
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
    // (#1321) a battery limit is a plain fact: it stops powering the car; the watts are noise
    if (verb === 'limit_discharge') return t('why_verb_limit_discharge') || 'limit discharge';
    const key = `why_verb_${verb}`;
    const word = t(key);
    const said = word && word !== key ? word : verb.replace(/_/g, ' ');
    return value ? `${said} ${value}` : said;
}

const _VALUE = /^(-?\d+(?:\.\d+)?)\s*(.*)$/;

/**
 * (#1321) A device that is nudged again and again (a battery limit swinging 1500, 1750,
 * 2000 W) is one row: the same device, the same command word and the same reason join at
 * the place of the newest. A group has `count`, `lo`, `hi`, `unit`, `verb`. Records whose
 * command has no number stay as they are; so does a lone record.
 */
export function mergeRepeats(records) {
    const parse = (r) => {
        const [verb, ...rest] = String(r?.new || '').split(' ');
        const m = _VALUE.exec(rest.join(' '));
        return verb && m ? { verb, value: Number(m[1]), unit: m[2] } : null;
    };
    const groups = new Map();
    for (const r of records || []) {
        const p = parse(r);
        if (!p) continue;
        const key = [chipKey(r), p.verb, p.unit, r.reason_code || ''].join('|');
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push({ r, p });
    }
    const first = new Map();
    for (const g of groups.values()) {
        if (g.length < 2) continue;
        const vals = g.map((x) => x.p.value);
        first.set(g[0].r, { ...g[0].r, count: g.length, lo: Math.min(...vals), hi: Math.max(...vals), unit: g[0].p.unit, verb: g[0].p.verb });
        for (const x of g.slice(1)) first.set(x.r, null);
    }
    return (records || []).filter((r) => first.get(r) !== null).map((r) => first.get(r) || r);
}

/**
 * (#1321) mergeRepeats per calendar day: a swing at 23:50 and one at 00:10 are two days'
 * rows, so today's list never counts yesterday's nudges. Order is kept.
 */
export function mergePerDay(records, tz) {
    const out = [];
    let group = [], day = null;
    const flush = () => { out.push(...mergeRepeats(group)); group = []; };
    for (const r of records || []) {
        const d = _dayKey(new Date(r?.time), tz);
        if (day !== null && d !== day) flush();
        day = d;
        group.push(r);
    }
    flush();
    return out;
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
export function plainReason(rec, t, opts = {}) {
    let code = rec?.reason_code;
    if (!code) return null;
    // (#1321) a live line never says the level is unknown while the chip reads it
    if (code === 'battery_car_level_unknown' && Number.isFinite(opts.soc)) {
        return t('why_reason_battery_car_level_known').replace('{soc}', String(Math.round(opts.soc)));
    }
    // (#1321) a standing "battery is below the floor" says it the way every screen does: what tonight needs
    if (code === 'battery_car_below_floor' && opts.battery) return opts.battery;
    // a past row: the level was not read THEN; say so without claiming it is unknown now
    if (code === 'battery_car_level_unknown' && opts.past) return t('next_reason_level_unread');
    // (#1321) a device that is held ("keep as is") is not turning off: its reason says it stays off
    const heldKey = opts.held ? `why_reason_${{ phase_shed: 'phase_guard' }[code] || code}_held` : '';
    const heldText = heldKey ? t(heldKey) : '';
    const key = heldText && heldText !== heldKey ? heldKey : `why_reason_${code}`;
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

/**
 * (#1321) A would-do / held-back record's reason in plain words. The record's
 * own code first; else the code the decision log holds for that device
 * (charger, battery or load); else nothing. The engine's log text
 * ("ev plugged in + battery SoC 20% < floor …") is never shown.
 */
export function recordReason(rec, states, t) {
    const soc = Number(states?.['sensor.sem_battery_soc']?.state);
    const live = { soc: Number.isFinite(soc) && states?.['sensor.sem_battery_soc']?.state !== '' ? soc : NaN };
    live.held = rec?.action === 'hold';
    live.battery = batterySentence(states, t);
    const own = plainReason(rec, t, live);
    if (own) return own;
    const id = String(rec?.device_id || '');
    const kind = rec?.kind || rec?.device_kind;
    const attr = (sid, a) => states?.[sid]?.attributes?.[a] || {};
    let log = {};
    let key = id;
    if (kind === 'charger') { log = attr('sensor.sem_charging_state', 'per_charger_last_decision'); key = id.replace(/^ev:/, ''); }
    else if (kind === 'battery') { log = attr('sensor.sem_battery_status', 'per_battery_last_decision'); key = id.replace(/^battery:/, ''); }
    else if (kind === 'load') log = attr('sensor.sem_load_management_status', 'per_device_last_decision');
    const held = log[key];
    return held ? (plainReason({ reason_code: held.reason_code, params: held.params }, t, live) || '') : '';
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

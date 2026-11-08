/**
 * (#1321) The System screen's settings as sentences, pure.
 *
 * `groups(states, t, ctx)` builds the seven group cards: each a sentence
 * (what Everyday shows) and a `more` list (All settings). Both are flat
 * arrays of text and value slots. A slot is bound to an entity
 * (`number.*` / `select.*` / `switch.*`, written directly) or to an
 * integration option (`set_option`, several keys in one call). Field ids,
 * option keys, ranges and defaults are copied from `cards/sem-config-card.js`
 * (SECTIONS and its renderers), the structural keys from its STRUCTURAL_KEYS
 * (mirror of `__init__.py:_SET_OPTION_STRUCTURAL_KEYS`).
 *
 * A missing entity or an unloaded option leaves its slot out: the fragment
 * that needs it is dropped, the sentence is built from the fragments that
 * resolve. Nothing here invents an id or a value.
 *
 * `applyPlan(pending, states)` turns the pending map into entity writes
 * (one service call each), one options payload, and whether that payload
 * reloads the integration.
 */

// (#528) option keys that reload the entry when written — copied from
// cards/sem-config-card.js STRUCTURAL_KEYS.
export const STRUCTURAL_KEYS = new Set([
    'battery_soc_sensor', 'tariff_schedule_entity',
    'grid_power_sensor', 'solar_production_sensor', 'battery_power_sensor', 'house_power_sensor',
    'heat_pump_relay1_entity', 'heat_pump_relay2_entity',
    'heat_pump_relay1_on_value', 'heat_pump_relay1_off_value',
    'heat_pump_relay2_on_value', 'heat_pump_relay2_off_value',
    'heat_pump_climate_entity', 'heat_pump_power_sensor',
    'heat_pump_temperature_sensor', 'heat_pump_invert_sg_ready',
    'heat_pump_tariff_rate', 'heat_pump_tariff_entity', 'heat_pump_tariff_meter',
    'heat_pump_energy_sensor', 'hot_water_energy_sensor',
    'heat_pump_rated_power', 'hot_water_rated_power',
    'hot_water_entity', 'hot_water_power_sensor', 'hot_water_temperature_sensor',
    'battery_force_discharge_control_entity', 'battery_strategy_control_entity',
    'battery_discharge_control_entity', 'battery_charge_end_soc_entity',
    'battery_discharge_protection_enabled', 'battery_setpoint_bidirectional',
    'battery_setpoint_model', 'battery_power_direction_entity',
    'battery_direction_discharge_value', 'battery_direction_charge_value',
    'battery_cycles_sensor', 'ev_chargers',
]);

export const DIAGNOSE = {
    pay: 'tariff', may: 'load_management', battery: 'battery_zones', chargers: 'ev_chargers',
    heat: 'heat_pump', reads: 'all', misc: 'notifications',
};

// ── readers ──

function st(states, id) { return states ? states[id] : undefined; }
function alive(e) { return !!e && e.state !== 'unavailable' && e.state !== 'unknown' && e.state !== undefined; }
function num(x) { const n = parseFloat(x); return Number.isFinite(n) ? n : null; }

/** A number entity as a slot: its own min / max / step / unit. */
function numSlot(states, id, o = {}) {
    const e = st(states, id);
    if (!alive(e)) return null;
    const v = num(e.state);
    if (v === null) return null;
    const a = e.attributes || {};
    return { id, kind: 'number', value: v, unit: o.unit ?? (a.unit_of_measurement || ''),
             min: num(a.min), max: num(a.max), step: num(a.step) ?? 1, zeroKey: o.zeroKey || null, clock: !!o.clock };
}

function switchSlot(states, id) {
    const e = st(states, id);
    if (!alive(e)) return null;
    return { id, kind: 'switch', value: e.state === 'on' };
}

/** `labelOf(value)` gives the option's label key. */
function selectSlot(states, id, labelOf) {
    const e = st(states, id);
    if (!alive(e)) return null;
    const opts = Array.isArray(e.attributes?.options) ? e.attributes.options : [];
    return { id, kind: 'select', value: String(e.state),
             options: opts.map((v) => ({ value: v, labelKey: labelOf ? labelOf(v) : null, label: labelOf ? null : v })) };
}

function optNum(opts, key, cfg) {
    if (!opts) return null;
    const v = num(opts[key] ?? cfg.default);
    if (v === null) return null;
    return { option: key, kind: 'number', value: v, unit: cfg.unit || '', min: cfg.min ?? null,
             max: cfg.max ?? null, step: cfg.step ?? 1, zeroKey: cfg.zeroKey || null };
}

function optSwitch(opts, key, def) {
    if (!opts) return null;
    return { option: key, kind: 'switch', value: opts[key] != null ? !!opts[key] : !!def };
}

/** options = [{value, labelKey}] or [{value, label}] */
function optSelect(opts, key, options, def) {
    if (!opts) return null;
    const v = opts[key] != null && opts[key] !== '' ? String(opts[key]) : String(def ?? '');
    return { option: key, kind: 'select', value: v, options };
}

function optText(opts, key) {
    if (!opts) return null;
    return { option: key, kind: 'text', value: opts[key] == null ? '' : String(opts[key]) };
}

/** A per-charger key inside `ev_chargers`, merged by id on the backend. */
function chargerSlot(opts, cid, key, kind, extra = {}) {
    if (!opts) return null;
    const c = (opts.ev_chargers || []).find((x) => x && x.id === cid) || null;
    if (!c) return null;
    const base = { option: 'ev_chargers', charger: cid, key, kind };
    if (kind === 'switch') return { ...base, value: !!c[key] };
    if (kind === 'select') return { ...base, value: String(c[key] ?? extra.def ?? ''), options: extra.options || [] };
    return null;
}

/** Read-only text in the sentence (a name, an entity id). */
function text(v) { return v ? { kind: 'text', ro: true, value: String(v) } : null; }

function action(name, labelKey) { return { kind: 'action', action: name, labelKey }; }

// ── sentence building ──

export function pendingKey(slot) {
    if (!slot) return '';
    if (slot.id) return slot.id;
    if (slot.option === 'ev_chargers' && slot.charger) return `opt:ev_chargers:${slot.charger}:${slot.key}`;
    if (slot.option) return `opt:${slot.option}`;
    if (slot.action) return `act:${slot.action}`;
    return '';
}

/** Decimals a number shows, from its step. */
export function decimalsOf(step) {
    const s = Number(step);
    if (!Number.isFinite(s) || s <= 0 || s >= 1) return 0;
    if (s >= 0.1) return 1;
    if (s >= 0.01) return 2;
    return 3;
}

/** The words a slot shows when it is not being edited. */
export function slotText(slot, t, value = slot.value) {
    if (!slot) return '';
    if (slot.kind === 'number') {
        if (slot.zeroKey && Number(value) === 0) return t(slot.zeroKey);
        const v = Number(value);
        if (!Number.isFinite(v)) return '—';
        if (slot.clock) {
            const h = Math.floor(v), m = Math.round((v - h) * 60);
            return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
        }
        const s = v.toFixed(decimalsOf(slot.step));
        return slot.unit ? `${s} ${slot.unit}` : s;
    }
    if (slot.kind === 'switch') return value ? t('next_on') : t('next_off');
    if (slot.kind === 'select') {
        const o = (slot.options || []).find((x) => String(x.value) === String(value));
        if (!o) return String(value ?? '');
        return o.labelKey ? t(o.labelKey) : (o.label ?? String(o.value));
    }
    if (slot.kind === 'action') return t(slot.labelKey);
    return String(value ?? '');
}

/** Split `t(key)` on its {placeholders}; null when a slot is missing. */
function frag(t, key, slots) {
    for (const v of Object.values(slots || {})) if (!v) return null;
    const txt = String(t(key) || '');
    const out = [];
    const re = /\{(\w+)\}/g;
    let last = 0, m;
    while ((m = re.exec(txt))) {
        if (m.index > last) out.push(txt.slice(last, m.index));
        const s = slots[m[1]];
        if (!s) return null;
        out.push(s);
        last = re.lastIndex;
    }
    if (last < txt.length) out.push(txt.slice(last));
    return out;
}

/** Capitalise the sentence when it opens with text; a name or value may open it as is. */
function capFirst(parts) {
    const s = parts[0];
    if (typeof s !== 'string') return parts;
    const j = s.search(/\S/);
    if (j < 0) return parts;
    parts[0] = s.slice(0, j) + s.charAt(j).toUpperCase() + s.slice(j + 1);
    return parts;
}

/** Join the fragments that resolved: "a, b, c." — one sentence. */
function clause(frags, sep = ', ', end = '.') {
    const ok = frags.filter(Boolean);
    if (!ok.length) return [];
    const out = [];
    ok.forEach((f, i) => { if (i) out.push(sep); out.push(...f); });
    if (end) out.push(end);
    return capFirst(out);
}

/** Sentences one after the other, a space between. */
function join(...sentences) {
    const out = [];
    for (const s of sentences) {
        if (!s || !s.length) continue;
        if (out.length) out.push(' ');
        out.push(...s);
    }
    return out;
}

/** The All-settings list: "label value · label value". */
function more(t, items) {
    const out = [];
    let n = 0;
    for (const it of items) {
        const [labelKey, slot] = it;
        if (!slot) continue;
        if (n) out.push(' · ');
        out.push(t(labelKey) + ' ', slot);
        n += 1;
    }
    return { parts: out, count: n };
}

// ── option vocabularies (labels are keys from sem-config-card.js) ──

const TARIFF_MODES = [
    { value: 'static', labelKey: 'next_tariff_static' },
    { value: 'dynamic', labelKey: 'next_tariff_dynamic' },
    { value: 'calendar', labelKey: 'next_tariff_calendar' },
];
const CLASS_MODES = [
    { value: 'percentile', labelKey: 'next_class_percentile' },
    { value: 'static', labelKey: 'next_class_static' },
];
const FEE_MODELS = ['none', 'per_kwh', 'tiered', 'fixed_monthly'].map((v) => ({ value: v, labelKey: 'config_fee_model_' + v }));
const PRICE_BASIS = ['all_in', 'spot_incl_vat', 'spot'].map((v) => ({ value: v, labelKey: 'config_price_basis_' + v }));
const PRESETS = ['none', 'nl_2027', 'custom'].map((v) => ({ value: v, labelKey: 'config_value_preset_' + v }));
const EXT_MODES = ['none', 'yield', 'observe'].map((v) => ({ value: v, labelKey: 'config_ext_ctrl_mode_' + v }));
const TARGET_TYPES = [{ value: 'kwh', labelKey: 'next_target_kwh' }, { value: 'soc', labelKey: 'next_target_soc' }];
const FORECAST_SOURCES = [
    { value: 'auto', labelKey: 'config_forecast_source_auto' },
    { value: 'solcast', label: 'Solcast' }, { value: 'forecast_solar', label: 'Forecast.Solar' },
    { value: 'open_meteo', label: 'Open-Meteo' }, { value: 'helios', label: 'Helios' },
];
const HINT_LABEL = (v) => ({ off: 'off', weekly: 'weekly', all: 'all' }[v] || null);

// ── discovery helpers the card reuses ──

export function hasBattery(states) {
    if (!states) return false;
    if (st(states, 'sensor.sem_battery_soc') || st(states, 'sensor.sem_battery_power')) return true;
    return Object.keys(states).some((id) => /^sensor\.sem_battery_b\d+_power$/.test(id));
}

/** `number.sem_battery_reserve_soc` (one battery) or `..._b<n>_reserve_soc` (several). */
export function reserveIds(states) {
    return Object.keys(states || {}).filter((id) => /^number\.sem_battery_(b\d+_)?reserve_soc$/.test(id)).sort();
}

/** PV strings from their power sensors (a restored, removed string is not one). */
export function pvStrings(states) {
    const out = [];
    for (const id of Object.keys(states || {})) {
        const m = id.match(/^sensor\.sem_pv_string_(pv\d+)_power$/);
        if (!m) continue;
        const e = states[id];
        if (e?.attributes?.restored === true) continue;
        out.push({ slot: m[1], name: e?.attributes?.string_name || m[1].toUpperCase() });
    }
    out.sort((a, b) => a.slot.localeCompare(b.slot, undefined, { numeric: true }));
    return out;
}

/** The Setup check rows, as sem-config-card.js builds them (its _setupItems). */
export function setupItems(states, options) {
    const o = options || {};
    const chargers = Object.keys(states || {}).some((id) => /^number\.sem_charger_.+_minimum_current$/.test(id));
    const on = (id) => st(states, id)?.state === 'on';
    const tariffDone = o.tariff_mode === 'dynamic' ? !!o.dynamic_tariff_entity
        : o.tariff_mode === 'calendar' ? !!o.tariff_schedule_entity : !!o.electricity_import_rate;
    return [
        { key: 'energy', labelKey: 'config_overview_energy_dashboard', done: !!st(states, 'sensor.sem_charging_state') },
        { key: 'ev', labelKey: 'config_overview_chargers', done: chargers },
        { key: 'hp', labelKey: 'heat_pump_title', done: on('binary_sensor.sem_heat_pump_registered') },
        { key: 'hw', labelKey: 'config_section_hot_water', done: !!o.hot_water_entity },
        { key: 'tariff', labelKey: 'config_section_tariff', done: tariffDone },
        { key: 'battery', labelKey: 'config_section_battery_zones', done: hasBattery(states) },
        { key: 'loads', labelKey: 'config_section_load_management', done: !!o.load_management_enabled, optional: true },
    ];
}

/** Loads with a power entity, for the freshness tiles (chargers and the battery have their own). */
export function loadSources(states) {
    const devs = st(states, 'sensor.sem_controllable_devices_count')?.attributes?.devices;
    const out = [];
    const list = devs && typeof devs === 'object' ? Object.entries(devs) : [];
    for (const [id, d] of list) {
        if (!d || typeof d !== 'object') continue;
        if (d.device_type === 'ev_charger' || d.device_type === 'battery') continue;
        if (!d.power_entity) continue;
        out.push({ id, name: d.name || id, entity: d.power_entity });
    }
    return out;
}

/** Unavailable: SEM's own count, of every sem_ entity HA knows. */
export function unavailableCount(states) {
    const e = st(states, 'sensor.sem_diag_sensors_unavailable');
    const n = alive(e) ? num(e.state) : null;
    const m = Object.keys(states || {}).filter((id) => /^[a-z_]+\.sem_/.test(id)).length;
    return { n, m };
}

// ── the groups ──

/**
 * ctx = { options, currency, chargers: [{cid, name}], labels: {control, provider,
 *         gridSign, battSign}, notifyServices: [{value, label}] }
 */
export function groups(states, t, ctx = {}) {
    const o = ctx.options || null;
    const cur = ctx.currency || 'EUR';
    const perKwh = `${cur}/kWh`;
    const labels = ctx.labels || {};
    const out = [];

    // 1 · How I pay
    {
        const mode = optSelect(o, 'tariff_mode', TARIFF_MODES, 'static');
        const modeV = mode ? mode.value : '';
        const rate = numSlot(states, 'number.sem_electricity_import_rate')
            || optNum(o, 'electricity_import_rate', { min: 0, max: 10000, step: 0.001, unit: perKwh, default: 0.3387 });
        const offPeak = optNum(o, 'electricity_off_peak_rate', { min: 0, max: 10000, step: 0.001, unit: perKwh,
            default: o ? (o.electricity_nt_rate ?? o.electricity_import_rate ?? 0.3387) : 0.3387 });
        const exportRate = numSlot(states, 'number.sem_electricity_export_rate')
            || optNum(o, 'electricity_export_rate', { min: 0, max: 10000, step: 0.001, unit: perKwh, default: 0.075 });
        const vat = optNum(o, 'import_vat_percent', { min: 0, max: 100, step: 0.1, unit: '%', default: 0 });
        const fee = optNum(o, 'grid_import_surcharge', { min: 0, max: 10, step: 0.001, unit: perKwh, default: 0 });
        const cheap = numSlot(states, 'number.sem_cheap_price_threshold');
        const expensive = numSlot(states, 'number.sem_expensive_price_threshold');
        const basis = modeV === 'dynamic' ? optSelect(o, 'tariff_classification_mode', CLASS_MODES, 'percentile') : null;
        const provider = text(labels.provider);
        const feeModel = optSelect(o, 'feed_in_fee_model', FEE_MODELS, 'none');
        const feeV = feeModel ? feeModel.value : 'none';
        const first = modeV === 'dynamic'
            ? (frag(t, 'next_pay_dynamic', { mode, provider }) || frag(t, 'next_pay_mode', { mode }))
            : modeV === 'calendar'
                ? (frag(t, 'next_pay_calendar', { mode, rate, offpeak: offPeak }) || frag(t, 'next_pay_mode', { mode }))
                : (frag(t, 'next_pay_static', { mode, rate }) || frag(t, 'next_pay_rate', { rate }) || frag(t, 'next_pay_mode', { mode }));
        const sentence = join(
            first ? capFirst(first) : [],
            clause([frag(t, 'next_pay_taxes', { vat, fee })]),
            clause([frag(t, 'next_pay_export', { export: exportRate })]),
            clause([frag(t, 'next_pay_thresholds', { cheap, expensive, basis }) || frag(t, 'next_pay_thresholds_plain', { cheap, expensive })]),
        );
        const m = more(t, [
            ['next_more_demand_charge', numSlot(states, 'number.sem_demand_charge_rate')
                || optNum(o, 'demand_charge_rate', { min: 0, max: 100000, step: 0.01, unit: `${cur}/kW`, default: 4.32 })],
            ['next_more_off_peak', modeV === 'calendar' ? null : offPeak],
            ['next_more_fee_model', feeModel],
            ['next_more_fee_amount', feeV === 'per_kwh' || feeV === 'fixed_monthly'
                ? optNum(o, 'feed_in_fee', { min: 0, max: 100000, step: 0.0001, unit: feeV === 'fixed_monthly' ? `${cur}/${t('next_month_short')}` : perKwh, default: 0 }) : null],
            ['next_more_fee_tiers', feeV === 'tiered' ? optText(o, 'feed_in_fee_tiers') : null],
            ['next_more_price_basis', optSelect(o, 'import_price_basis', PRICE_BASIS, 'all_in')],
            ['next_more_markup', optNum(o, 'import_markup', { min: 0, max: 10000, step: 0.0001, unit: perKwh, default: 0 })],
            ['next_more_energy_tax', optNum(o, 'import_energy_tax', { min: 0, max: 10000, step: 0.0001, unit: perKwh, default: 0 })],
            ['next_more_export_floor', optNum(o, 'export_value_threshold', { min: -10000, max: 10000, step: 0.0001, unit: perKwh, default: 0 })],
            ['next_more_preset', optSelect(o, 'tariff_value_preset', PRESETS, 'none')],
        ]);
        out.push({ key: 'pay', titleKey: 'next_g_pay', diagnoseSection: DIAGNOSE.pay, sentence, more: m.parts, count: m.count });
    }

    // 2 · What SEM may do
    {
        const unlimited = optSwitch(o, 'peak_limit_unlimited', false);
        const limit = optNum(o, 'target_peak_limit', { min: 1, max: 80, step: 0.1, unit: 'kW', default: 5 });
        const warn = optNum(o, 'warning_peak_level', { min: 1, max: 80, step: 0.1, unit: 'kW', default: 4.5 });
        const shed = optNum(o, 'emergency_peak_level', { min: 1, max: 80, step: 0.1, unit: 'kW', default: 6 });
        const ac = optNum(o, 'inverter_ac_limit_w', { min: 0, max: 100000, step: 100, unit: 'W', default: 0 });
        const acSet = ac && ac.value > 0 ? ac : null;
        const relay = o && o.shed_signal_entity ? text(o.shed_signal_entity) : null;
        const sentence = join(
            unlimited && unlimited.value
                ? clause([frag(t, 'next_may_unlimited', { unlimited })])
                : clause([frag(t, 'next_may_peak', { limit })]),
            unlimited && unlimited.value ? [] : clause([frag(t, 'next_may_levels', { warn, shed })]),
            clause([frag(t, 'next_may_ac', { ac: acSet })]),
        );
        const m = more(t, [
            ['next_more_load_mgmt', optSwitch(o, 'load_management_enabled', false)],
            ['next_more_no_limit', unlimited],
            ['next_more_shed_signal', relay],
            ['next_more_operator_limit', relay ? optNum(o, 'shed_signal_limit', { min: 1, max: 80, step: 0.1, unit: 'kW', default: 4.2 }) : null],
            ['next_more_ac_limit', acSet ? null : ac],
            ['next_more_export_guard', switchSlot(states, 'switch.sem_export_guard_enabled')],
            ['next_more_engage', numSlot(states, 'number.sem_export_guard_engage_s')],
            ['next_more_release', numSlot(states, 'number.sem_export_guard_release_s')],
            ['next_more_override_external', switchSlot(states, 'switch.sem_export_guard_override_external')],
        ]);
        out.push({ key: 'may', titleKey: 'next_g_may', diagnoseSection: DIAGNOSE.may, sentence, more: m.parts, count: m.count });
    }

    // 3 · Battery rules (only with a battery)
    if (hasBattery(states)) {
        const priority = numSlot(states, 'number.sem_battery_priority_soc');
        const buffer = numSlot(states, 'number.sem_battery_buffer_soc');
        const auto = numSlot(states, 'number.sem_battery_auto_start_soc');
        const sentence = join(
            clause([frag(t, 'next_batt_zones', { priority, buffer, autostart: auto })
                || frag(t, 'next_batt_zones_two', { priority, buffer })]),
            clause([
                frag(t, 'next_batt_spend', { v: switchSlot(states, 'switch.sem_forecast_spending_enabled') }),
                frag(t, 'next_batt_pace', { v: switchSlot(states, 'switch.sem_battery_charge_pacing_enabled') }),
                frag(t, 'next_batt_sell', { v: switchSlot(states, 'switch.sem_battery_may_export') }),
                frag(t, 'next_batt_assist', { v: switchSlot(states, 'switch.sem_battery_may_assist_ev') }),
            ]),
        );
        const reserves = reserveIds(states).map((id, i) => ['next_more_reserve', numSlot(states, id)]);
        const m = more(t, [
            ['next_more_max_discharge', numSlot(states, 'number.sem_battery_max_discharge_power')],
            ['next_more_drain_floor', numSlot(states, 'number.sem_battery_morning_drain_floor_soc')],
            ['next_more_house_sink', switchSlot(states, 'switch.sem_battery_house_sink_enabled')],
            ['next_more_vpp', optSwitch(o, 'vpp_enabled', false)],
            ...reserves,
            ['next_more_assist_max', numSlot(states, 'number.sem_battery_assist_max_power')],
            ['next_more_solar_gate', numSlot(states, 'number.sem_battery_assist_min_surplus')],
            ['next_more_protection', optSwitch(o, 'battery_discharge_protection_enabled', true)],
            ['next_more_scheduler', optSwitch(o, 'battery_charge_scheduler_enabled', false)],
        ]);
        out.push({ key: 'battery', titleKey: 'next_g_battery', diagnoseSection: DIAGNOSE.battery, sentence, more: m.parts, count: m.count });
    }

    // 4 · Chargers
    {
        const chargers = ctx.chargers || [];
        const control = text(labels.control);
        const sentences = [];
        const moreItems = [];
        for (const c of chargers) {
            const cid = c.cid;
            const name = text(c.name || cid);
            const phases = numSlot(states, `number.sem_charger_${cid}_ev_phases`);
            const min = numSlot(states, `number.sem_charger_${cid}_minimum_current`, { unit: '' });
            const max = numSlot(states, `number.sem_charger_${cid}_maximum_current`);
            const entry = o ? (o.ev_chargers || []).find((x) => x && x.id === cid) : null;
            const types = entry && entry.vehicle_soc_entity ? TARGET_TYPES : TARGET_TYPES.slice(0, 1);
            const type = chargerSlot(o, cid, 'ev_target_type', 'select', { options: types, def: 'kwh' });
            sentences.push(clause([
                frag(t, 'next_ch_name_control', { name, control }) || frag(t, 'next_ch_name', { name }),
                frag(t, 'next_ch_phases', { phases }),
                frag(t, 'next_ch_amps', { min, max }),
            ]));
            sentences.push(clause([frag(t, 'next_ch_targets', { type })]));
            moreItems.push(
                ['next_more_ext_control', chargerSlot(o, cid, 'external_control_mode', 'select', { options: EXT_MODES, def: 'none' })],
                ['next_more_finish_by_departure', chargerSlot(o, cid, 'finish_by_departure', 'switch')],
                ['next_more_capacity', numSlot(states, `number.sem_charger_${cid}_ev_battery_capacity_kwh`)],
                ['next_more_use', numSlot(states, `number.sem_charger_${cid}_ev_kwh_per_100km`)],
                ['next_more_phase_switching', chargerSlot(o, cid, 'ev_phase_switching_enabled', 'switch')],
            );
        }
        moreItems.push(
            ['next_more_enable_delay', numSlot(states, 'number.sem_ev_enable_delay_seconds')],
            ['next_more_disable_delay', numSlot(states, 'number.sem_ev_disable_delay_seconds')],
        );
        const sentence = chargers.length ? join(...sentences) : [t('next_ch_none')];
        const m = more(t, moreItems);
        out.push({ key: 'chargers', titleKey: 'next_g_chargers', diagnoseSection: DIAGNOSE.chargers, sentence, more: m.parts, count: m.count });
    }

    // 5 · Heat pump and hot water (only when one is set up)
    {
        const hpOn = st(states, 'binary_sensor.sem_heat_pump_registered')?.state === 'on';
        const hpSet = hpOn || !!(o && (o.heat_pump_relay1_entity || o.heat_pump_climate_entity));
        const hwSet = !!(o && o.hot_water_entity) || st(states, 'binary_sensor.sem_hot_water_registered')?.state === 'on';
        if (hpSet || hwSet) {
            const hpRate = optNum(o, 'heat_pump_tariff_rate', { min: 0, max: 10000, step: 0.001, unit: perKwh, default: 0 });
            const hpRateSet = hpRate && hpRate.value > 0 ? hpRate : null;
            const boost = hpOn ? numSlot(states, 'number.sem_heat_pump_boost_offset')
                : optNum(o, 'heat_pump_boost_offset', { min: 0, max: 10, step: 0.5, unit: '°C', default: 2 });
            const hp = hpSet ? clause([
                frag(t, 'next_hp_rated', { rated: optNum(o, 'heat_pump_rated_power', { min: 100, max: 30000, step: 50, unit: 'W', default: 2000 }) }),
                o && o.heat_pump_climate_entity
                    ? frag(t, 'next_hp_climate', { climate: text(o.heat_pump_climate_entity) })
                    : (frag(t, 'next_hp_contacts', { relay1: text(o && o.heat_pump_relay1_entity), relay2: text(o && o.heat_pump_relay2_entity) })
                        || frag(t, 'next_hp_contact', { relay1: text(o && o.heat_pump_relay1_entity) })),
                frag(t, 'next_hp_boost', { boost }),
                frag(t, 'next_hp_tariff', { rate: hpRateSet }),
            ]) : [];
            const hw = hwSet ? clause([
                frag(t, 'next_hw_rated', { rated: optNum(o, 'hot_water_rated_power', { min: 100, max: 30000, step: 50, unit: 'W', default: 2500 }) }),
                frag(t, 'next_hw_target', { target: numSlot(states, 'number.sem_hot_water_solar_target') }),
                frag(t, 'next_hw_legionella', { temp: numSlot(states, 'number.sem_legionella_target_temp'),
                                               hours: numSlot(states, 'number.sem_legionella_interval_hours') }),
            ]) : [];
            const sentence = join(hp, hw);
            const safety = st(states, 'sensor.sem_hot_water_temperature_safety_path');
            const activation = st(states, 'sensor.sem_hot_water_activation_path');
            const m = more(t, [
                ['next_more_safety_path', alive(safety) && safety.state !== 'uninitialized' ? text(safety.state) : null],
                ['next_more_activation', alive(activation) && activation.state !== 'uninitialized' ? text(activation.state) : null],
                ['next_more_max_setpoint', hpSet ? optNum(o, 'heat_pump_max_setpoint', { min: 30, max: 80, step: 1, unit: '°C', default: 55 }) : null],
                ['next_more_invert_contacts', hpSet ? optSwitch(o, 'heat_pump_invert_sg_ready', false) : null],
                ['next_more_own_tariff', hpSet && !hpRateSet ? hpRate : null],
                ['next_more_vacation_signal', o && o.vacation_mode_entity ? text(o.vacation_mode_entity) : null],
            ]);
            out.push({ key: 'heat', titleKey: 'next_g_heat', diagnoseSection: DIAGNOSE.heat, sentence, more: m.parts, count: m.count });
        }
    }

    // 6 · What SEM reads
    {
        const ed = st(states, 'sensor.sem_diag_ed_config')?.attributes?.energy_dashboard || {};
        const solar = text((o && o.solar_production_sensor) || ed.solar?.power);
        const grid = text((o && o.grid_power_sensor) || ed.grid?.power);
        const battery = hasBattery(states) ? text((o && o.battery_power_sensor) || ed.battery?.power) : null;
        const gridSign = text(labels.gridSign);
        const flipGrid = action('flip_grid_sign', 'next_flip_sign');
        const flipBatt = action('flip_battery_sign', 'next_flip_sign');
        const house = o && o.house_power_sensor ? text(o.house_power_sensor) : text(t('next_computed'));
        const sentence = clause([
            frag(t, 'next_reads_solar', { solar }),
            frag(t, 'next_reads_grid_sign', { grid, sign: gridSign, flip: flipGrid }) || frag(t, 'next_reads_grid', { grid, flip: flipGrid }),
            frag(t, 'next_reads_battery', { battery, flip: flipBatt }),
            frag(t, 'next_reads_house', { house }),
        ]);
        const strings = pvStrings(states);
        const m = more(t, [
            ['next_more_house_meter', o ? text(o.house_power_sensor || t('config_notif_none')) : null],
            ['next_more_reset_signs', action('reset_sign_detection', 'next_run')],
            ['next_more_strings', strings.length ? text(strings.map((s) => s.name).join(' / ')) : null],
            ['next_more_system_size', numSlot(states, 'number.sem_system_size_kwp')],
            ['next_more_forecast', optSelect(o, 'solar_forecast_source', FORECAST_SOURCES, 'auto')],
        ]);
        out.push({ key: 'reads', titleKey: 'next_g_reads', diagnoseSection: DIAGNOSE.reads, sentence, more: m.parts, count: m.count });
    }

    // 7 · Notifications and more
    {
        const hints = selectSlot(states, 'select.sem_hints', HINT_LABEL);
        const services = ctx.notifyServices || [];
        const service = services.length
            ? optSelect(o, 'mobile_notification_service', [{ value: '', labelKey: 'config_notif_none' }, ...services], '')
            : (o && o.mobile_notification_service ? text(o.mobile_notification_service) : null);
        const sentence = join(
            clause([frag(t, 'next_misc_hints_to', { hints, service }) || frag(t, 'next_misc_hints', { hints })]),
            clause([frag(t, 'next_misc_interval', { interval: numSlot(states, 'number.sem_update_interval') })]),
            clause([frag(t, 'next_misc_morning', { on: switchSlot(states, 'switch.sem_ev_morning_window_enabled'),
                                                   hours: numSlot(states, 'number.sem_ev_morning_window_hours') })]),
            clause([frag(t, 'next_misc_night', { offset: numSlot(states, 'number.sem_night_start_offset_min'),
                                                 end: numSlot(states, 'number.sem_night_latest_end', { clock: true }) })
                || frag(t, 'next_misc_night_offset', { offset: numSlot(states, 'number.sem_night_start_offset_min') })]),
            clause([frag(t, 'next_misc_vacation', { v: switchSlot(states, 'switch.sem_vacation_mode') })]),
            clause([frag(t, 'next_misc_keep', { days: optNum(o, 'status_retention_days',
                { min: 0, max: 14, step: 1, unit: t('config_retention_unit_days'), default: 0, zeroKey: 'config_retention_off' }) })]),
        );
        const m = more(t, [
            ['next_more_simulation_tab', switchSlot(states, 'switch.sem_simulation_tab')],
            ['next_more_min_solar', numSlot(states, 'number.sem_minimum_solar_power')],
            ['next_more_regulation_offset', numSlot(states, 'number.sem_regulation_offset')],
            ['next_more_charger_notes', optSwitch(o, 'enable_charger_notifications', true)],
            ['next_more_mobile_notes', optSwitch(o, 'enable_mobile_notifications', false)],
            ['next_more_clean_up', action('purge_status_history', 'next_run')],
        ]);
        out.push({ key: 'misc', titleKey: 'next_g_misc', diagnoseSection: DIAGNOSE.misc, sentence, more: m.parts, count: m.count });
    }

    return out;
}

/** Every slot in a group list, sentence and more together. */
export function slotsOf(groupList) {
    const out = [];
    for (const g of groupList || []) {
        for (const p of [...(g.sentence || []), ...(g.more || [])]) {
            if (p && typeof p === 'object' && (p.id || p.option || p.action)) out.push(p);
        }
    }
    return out;
}

/**
 * pending = { [pendingKey]: { slot, value } }.
 * → { entityWrites: [{domain, service, data}], options: {...}, reload }.
 * A number written to an entity is clamped to the entity's own min / max.
 */
export function applyPlan(pending, states) {
    const entityWrites = [];
    const options = {};
    const chargers = {};
    let reload = false;
    for (const item of Object.values(pending || {})) {
        const slot = item && item.slot;
        if (!slot) continue;
        const value = item.value;
        if (slot.id) {
            if (slot.kind === 'number') {
                const a = st(states, slot.id)?.attributes || {};
                let v = Number(value);
                const mn = num(a.min), mx = num(a.max);
                if (mn !== null) v = Math.max(mn, v);
                if (mx !== null) v = Math.min(mx, v);
                entityWrites.push({ domain: 'number', service: 'set_value', data: { entity_id: slot.id, value: v } });
            } else if (slot.kind === 'select') {
                entityWrites.push({ domain: 'select', service: 'select_option', data: { entity_id: slot.id, option: String(value) } });
            } else if (slot.kind === 'switch') {
                entityWrites.push({ domain: 'switch', service: value ? 'turn_on' : 'turn_off', data: { entity_id: slot.id } });
            } else if (slot.kind === 'text') {
                entityWrites.push({ domain: 'text', service: 'set_value', data: { entity_id: slot.id, value: String(value) } });
            }
        } else if (slot.option === 'ev_chargers' && slot.charger) {
            if (!chargers[slot.charger]) chargers[slot.charger] = { id: slot.charger };
            chargers[slot.charger][slot.key] = value;
            reload = true;
        } else if (slot.option) {
            options[slot.option] = slot.kind === 'number' ? Number(value) : value;
            if (STRUCTURAL_KEYS.has(slot.option)) reload = true;
        }
    }
    if (Object.keys(chargers).length) options.ev_chargers = Object.values(chargers);
    return { entityWrites, options, reload };
}

/**
 * (#1321) The Devices screen's pure model: rows from the device map,
 * the head pill, reorder, the priority payload, the mode writes and the
 * two bars.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
    deviceRows, statePill, swap, priorityPayload, mergedMode, modeWrites,
    overnightSource, overnightWrites, verdictKey, goalPct, targetModel, zonesModel,
    weekdaySummary, chargerIdOf, loadKind,
} from '../src/util/next-devices.js';

const MAP = {
    hot_water: { name: 'Hot water', priority: 3, device_type: 'switch', control_mode: 'surplus',
        goals: { daily_min_runtime_min: 60, daily_max_runtime_min: 180, phase: 'L1' },
        progress: { runtime_today_min: 30 }, is_on: false },
    load_device_keba: { name: 'Car', priority: 1, device_type: 'ev_charger', is_on: true },
    battery: { name: 'Battery', priority: 5, device_type: 'battery', soc: 58 },
    heat_pump: { name: 'Heat pump', priority: 2, device_type: 'individual_device', control_mode: 'surplus',
        goals: { battery_assist_enabled: true }, depends_on: [] },
    pool: { name: 'Pool', priority: 4, control_mode: 'off', depends_on: ['heat_pump'], has_control_handle: false },
};

test('rows come out by priority, typed, with the rank as the position', () => {
    const rows = deviceRows(MAP, ['keba']);
    assert.deepEqual(rows.map((r) => r.id), ['load_device_keba', 'heat_pump', 'hot_water', 'pool', 'battery']);
    assert.deepEqual(rows.map((r) => r.type), ['charger', 'load', 'load', 'load', 'battery']);
    assert.deepEqual(rows.map((r) => r.kind), ['charger', 'heat_pump', 'hot_water', 'load', 'battery']);
    assert.deepEqual(rows.map((r) => r.priority), [1, 2, 3, 4, 5]);
    assert.equal(rows[0].cid, 'keba');
    assert.equal(rows[1].mergedMode, 'solar_battery');
    assert.equal(rows[2].mergedMode, 'solar_only');
    assert.ok(rows.every((r) => r.inMap));
});

test('a charger or battery the map lacks is appended, outside the payload', () => {
    const rows = deviceRows({ hot_water: MAP.hot_water }, ['keba', 'go'], { hasBattery: true, chargerName: (c) => c.toUpperCase() });
    assert.deepEqual(rows.map((r) => r.id), ['hot_water', 'load_device_keba', 'load_device_go', 'battery']);
    assert.equal(rows[1].name, 'KEBA');
    assert.deepEqual(rows.map((r) => r.inMap), [true, false, false, false]);
    assert.deepEqual(priorityPayload(rows), { priorities: [{ device_id: 'hot_water', priority: 1 }] });
});

test('an empty map gives no rows', () => {
    assert.deepEqual(deviceRows({}, []), []);
    assert.deepEqual(deviceRows(undefined, []), []);
});

test('the head pill says what the device does', () => {
    const [car, hp, hw, pool, bat] = deviceRows(MAP, ['keba']);
    assert.deepEqual(statePill(car, { powerW: 4100, amps: 6 }), { key: 'next_st_charging_a', params: { amps: 6 }, cls: 'ok' });
    assert.equal(statePill(car, { powerW: 0, plannedAt: '02:00' }).key, 'next_st_waits_for');
    assert.equal(statePill(car, { powerW: 0, paused: true }).cls, 'warn');
    assert.equal(statePill(car, { powerW: 0, connected: false }).key, 'next_st_unplugged');
    assert.equal(statePill(hp, { powerW: 900 }).key, 'next_st_on');
    assert.equal(statePill(hw, { powerW: 0, plannedAt: '13:30' }).key, 'next_st_waits_for');
    assert.equal(statePill({ ...pool, blockedBy: 'heat_pump' }, { parentName: 'Heat pump' }).params.parent, 'Heat pump');
    assert.equal(statePill(pool, {}).key, 'next_st_off_mode');
    assert.equal(statePill(bat, { powerW: -300, boost: true }).key, 'next_st_lends_car');
    assert.equal(statePill(bat, { powerW: -300 }).key, 'next_st_to_house');
    assert.equal(statePill(bat, { powerW: 0, status: 'Selling' }).key, 'next_st_selling');
    assert.equal(statePill(bat, { powerW: 0 }).key, 'next_st_rests');
    assert.deepEqual(statePill({ ...hw, isShed: true, shedReason: 'PHASE', shedPhase: 'L1' }, {}),
        { key: 'shed_phase', params: { phase: 'L1' }, cls: 'bad' });
    assert.equal(statePill({ ...hw, lockedByOperator: true }, {}).key, 'locked_by_grid_operator');
});

test('swap moves one step, keeps the ends, locks a child, renumbers', () => {
    const rows = deviceRows(MAP, ['keba']);
    // the pool requires the heat pump, so it follows it (drag-reorder's contract)
    const down = swap(rows, 'load_device_keba', 1);
    assert.deepEqual(down.map((r) => r.id), ['heat_pump', 'pool', 'load_device_keba', 'hot_water', 'battery']);
    assert.deepEqual(down.map((r) => r.priority), [1, 2, 3, 4, 5]);
    assert.equal(swap(rows, 'load_device_keba', -1), rows);
    assert.equal(swap(rows, 'battery', 1), rows);
    assert.equal(swap(rows, 'pool', -1), rows);
    assert.equal(swap(rows, 'nope', 1), rows);
    // a child follows its parent
    const up = swap(rows, 'heat_pump', -1);
    assert.deepEqual(up.map((r) => r.id), ['heat_pump', 'pool', 'load_device_keba', 'hot_water', 'battery']);
});

test('merged mode maps to the two backend properties', () => {
    assert.equal(mergedMode({ control_mode: 'off' }), 'off');
    assert.equal(mergedMode({}), 'peak_only');
    assert.deepEqual(modeWrites({}, 'peak_only'), [{ property: 'control_mode', value: 'peak_only' }]);
    assert.deepEqual(modeWrites({ goals: { top_up_policy: 'always' } }, 'solar_battery'), [
        { property: 'control_mode', value: 'surplus' },
        { property: 'battery_assist_enabled', value: 'true' },
        { property: 'top_up_policy', value: 'solar_only' },
    ]);
    assert.equal(overnightSource({ battery_eligible_overnight: true }), 'battery');
    assert.equal(overnightSource({ top_up_policy: 'cheap_hours' }), 'grid');
    assert.deepEqual(overnightWrites('grid'), [
        { property: 'battery_eligible_overnight', value: 'false' },
        { property: 'top_up_policy', value: 'cheap_hours' },
    ]);
});

test('verdict, goal progress and the names that draw', () => {
    const rows = deviceRows(MAP, ['keba']);
    assert.equal(verdictKey(rows[3]), 'control_verdict_none');
    assert.equal(verdictKey({ ...rows[2], mergedMode: 'off' }), 'control_verdict_off');
    assert.equal(verdictKey(rows[2]), 'control_verdict_may_act');
    assert.equal(goalPct(rows[2].goals, rows[2].progress), 50);
    assert.equal(goalPct({}, { runtime_today_min: 10 }), null);
});

test('the target bar scales SOC to 100 and kWh to the larger of max and today', () => {
    const s = targetModel({ have: 44, min: 70, max: 90, isSoc: true });
    assert.deepEqual(s, { fill: 44, bandLeft: 70, bandWidth: 20, flagLeft: 70 });
    const k = targetModel({ have: 12, min: 10, max: 20, isSoc: false });
    assert.deepEqual(k, { fill: 60, bandLeft: 50, bandWidth: 50, flagLeft: 50 });
    const over = targetModel({ have: 30, min: 10, max: 20, isSoc: false });
    assert.equal(over.fill, 100);
    const none = targetModel({ have: null, min: null, max: null, isSoc: true });
    assert.deepEqual(none, { fill: 0, bandLeft: null, bandWidth: 0, flagLeft: null });
});

test('the zone bar keeps only the markers that exist', () => {
    const z = zonesModel({ soc: 58, priority: 30, buffer: 70, autoStart: null, floor: 89 });
    assert.equal(z.z1, 30); assert.equal(z.z2, 70); assert.equal(z.cur, 58);
    assert.deepEqual(z.marks.map((m) => m.key), ['priority', 'buffer', 'tonight']);
    const e = zonesModel({ soc: null, priority: null, buffer: null, autoStart: null, floor: null });
    assert.deepEqual(e, { z1: 0, z2: 0, marks: [], cur: null });
});

test('weekday departures fold into runs', () => {
    const runs = weekdaySummary({ sat: '09:00' }, '07:00');
    assert.deepEqual(runs, [{ from: 0, to: 4, time: '07:00' }, { from: 5, to: 5, time: '09:00' }, { from: 6, to: 6, time: '07:00' }]);
    assert.deepEqual(weekdaySummary({}, ''), []);
    assert.deepEqual(weekdaySummary({ mon: '06:00', wed: '06:00' }, ''), [{ from: 0, to: 0, time: '06:00' }, { from: 2, to: 2, time: '06:00' }]);
});

test('ids: a charger row and the two named loads', () => {
    assert.equal(chargerIdOf('load_device_keba'), 'keba');
    assert.equal(chargerIdOf('hot_water'), null);
    assert.equal(loadKind('heat_pump'), 'heat_pump');
    assert.equal(loadKind('hot_water_2'), 'hot_water');
    assert.equal(loadKind('pool'), 'load');
});

// ── the card renders with a charger, a battery and two loads (no DOM, fake lit) ──
import { register } from 'node:module';

const FAKE_LIT = `
export class LitElement {
    constructor() { this.style = {}; this.classList = { toggle() {} }; this.renderRoot = { querySelector: () => null, querySelectorAll: () => [], getElementById: () => null, appendChild() {} }; }
    connectedCallback() {}
    disconnectedCallback() {}
    requestUpdate() { this.__updates = (this.__updates || 0) + 1; }
    updated() {}
    getRootNode() { return {}; }
    get updateComplete() { return Promise.resolve(true); }
}
export const html = (strings, ...values) => ({ tpl: true, strings: [...strings], values });
export const css = () => '', svg = html;
export const nothing = Symbol('nothing');
export const repeat = (items, key, fn) => Array.from(items).map((it, i) => fn(it, i));
`;
const LOADER = `
const FAKE = ${JSON.stringify('data:text/javascript,' + encodeURIComponent(FAKE_LIT))};
export async function resolve(specifier, context, next) {
    if (specifier === 'lit' || specifier.startsWith('lit/')) return { url: FAKE, shortCircuit: true };
    return next(specifier, context);
}`;
register('data:text/javascript,' + encodeURIComponent(LOADER));
globalThis.window = globalThis;
globalThis.document = { addEventListener() {}, removeEventListener() {}, documentElement: {}, head: { appendChild() {} }, createElement: () => ({}) };
globalThis.addEventListener = () => {};
globalThis.removeEventListener = () => {};
globalThis.requestAnimationFrame = () => 0;
const registry = new Map();
globalThis.customElements = { get: (t) => registry.get(t), define: (t, c) => registry.set(t, c) };
globalThis.getComputedStyle = () => ({ getPropertyValue: () => '' });
globalThis.localStorage = { getItem: () => null, setItem() {} };
globalThis.navigator ??= {};
globalThis.semLocalize = (key) => key;
await import('../src/cards/sem-next-devices-card.js');

function text(part) {
    if (part == null || typeof part === 'symbol' || part === false) return '';
    if (Array.isArray(part)) return part.map(text).join('');
    if (part && part.tpl) {
        let out = '';
        part.strings.forEach((s, i) => { out += s; if (i < part.values.length) out += text(part.values[i]); });
        return out;
    }
    if (typeof part === 'function') return '';
    return String(part);
}
const S = (state, attributes = {}) => ({ state: String(state), attributes, last_updated: '2026-11-07T12:40:00+01:00' });

function states() {
    const st = {
        'switch.sem_observer_mode': S('off'),
        'sensor.sem_battery_soc': S(58), 'sensor.sem_battery_power': S(-300, { unit_of_measurement: 'W' }),
        'sensor.sem_battery_status': S('Discharging'),
        'sensor.sem_battery_spendable_kwh': S(2.3, { phase: 'holding', overnight_need_kwh: 7.1, expected_refill_kwh: 6, nights_sealed: 41, dynamic_floor_pct: 89, battery_sell_state: 'none' }),
        'sensor.sem_battery_dynamic_floor_pct': S(89), 'sensor.sem_battery_measured_capacity_kwh': S(9.6),
        'sensor.sem_diag_battery_capacity': S(10), 'sensor.sem_battery_capacity_drift_pct': S(-4),
        'sensor.sem_battery_health_score': S(96), 'sensor.sem_battery_cycles_estimated': S(412), 'sensor.sem_battery_temperature': S(28, { unit_of_measurement: '°C' }),
        'sensor.sem_battery_charge_pacing': S('paced', { reason_code: 'paced', action: 'wrote', cap_w: 2000, full_at: '2026-11-07T16:00:00+01:00', enabled: true }),
        'switch.sem_battery_charge_pacing_enabled': S('on'), 'switch.sem_battery_may_export': S('off'), 'switch.sem_battery_may_assist_ev': S('on'),
        'sensor.sem_daily_battery_charge_energy': S(6.2), 'sensor.sem_daily_battery_discharge_energy': S(3.1),
        'select.sem_battery_mode': S('auto', { options: ['auto', 'self_consumption', 'force_charge', 'force_discharge', 'off'] }),
        'select.sem_battery_b1_mode': S('auto', { options: ['auto', 'off'] }), 'number.sem_battery_b1_reserve_soc': S(20),
        'number.sem_battery_buffer_soc': S(70), 'number.sem_battery_priority_soc': S(30), 'number.sem_battery_auto_start_soc': S(40),
        'number.sem_battery_assist_max_power': S(2000), 'number.sem_battery_assist_min_surplus': S(500),
        'sensor.sem_forecast_source': S('solcast'), 'sensor.sem_forecast_trust_d1': S(87), 'sensor.sem_forecast_trust_d2': S(79),
        'sensor.sem_tariff_current_export_rate': S(0.12),
        'sensor.sem_surplus_total_w': S(4900), 'sensor.sem_surplus_allocated_w': S(4400), 'sensor.sem_surplus_unallocated_w': S(500),
        'sensor.sem_surplus_active_devices': S(2), 'sensor.sem_surplus_total_devices': S(5),
        'sensor.sem_consecutive_peak_15min': S(3.5), 'sensor.sem_target_peak_limit': S(5, { peak_slot_used_kwh: 0.8, peak_slot_allowed_w: 4200 }),
        'sensor.sem_peak_margin': S(1.5), 'sensor.sem_monthly_consecutive_peak': S(6.1), 'sensor.sem_available_load_reduction': S(2.8),
        'sensor.sem_load_management_status': S('normal', { shed_signal_active: true, shed_signal_cap_kw: 4.2, shed_signal_since: '2026-11-07T14:05:00+01:00' }),
        'sensor.sem_load_management_recommendation': S('none'),
        'sensor.sem_energy_plan': S('ok', { computed_at: 'x', blocks: [{ id: 'ev:keba', start: '2099-01-01T02:00:00+01:00', end: '2099-01-01T04:30:00+01:00', power_w: 4000 }] }),
        'sensor.sem_charging_state': S('charging', {
            per_charger_departure: { keba: { default: '07:00', by_weekday: { sat: '09:00' }, next: '2026-11-08T07:00:00+01:00', one_block: false, late_min: 30, boost_allowed: true } },
            per_charger_phases: { keba: { active_phases: 3 } }, battery_boost: null, battery_boost_preview: { default_floor: 50, capacity_kwh: 10 },
        }),
        'sensor.sem_charger_keba_power': S(4100, { unit_of_measurement: 'W', friendly_name: 'SEM Car Power' }),
        'sensor.sem_charger_keba_commanded_current': S(6), 'sensor.sem_charger_keba_daily_energy': S(12), 'sensor.sem_charger_keba_session_energy': S(8.4),
        'sensor.sem_charger_keba_session_solar_share': S(92), 'sensor.sem_charger_keba_vehicle_soc': S(44), 'sensor.sem_charger_keba_estimated_soc': S(45, { vehicle_soc_last: 44, vehicle_soc_last_at: '2026-11-07T12:00:00+01:00' }),
        'sensor.sem_charger_keba_flow_solar_to_ev_energy': S(11), 'sensor.sem_charger_keba_flow_grid_to_ev_energy': S(1),
        'select.sem_charger_keba_charge_mode': S('solar_plus_cheap', { options: ['solar_only', 'solar_plus_battery', 'solar_plus_cheap', 'min_plus_solar', 'always_max', 'off'] }),
        'select.sem_charger_keba_ev_target_type': S('soc', { options: ['kwh', 'soc'] }), 'select.sem_charger_keba_phase_mode': S('auto', { options: ['auto', '1', '3'] }),
        'number.sem_charger_keba_target_soc': S(70, { min: 0, max: 100, step: 5 }), 'number.sem_charger_keba_target_soc_max': S(90, { min: 0, max: 100, step: 5 }),
        'number.sem_charger_keba_ev_battery_capacity_kwh': S(62), 'number.sem_charger_keba_minimum_current': S(6), 'number.sem_charger_keba_maximum_current': S(16),
        'number.sem_charger_keba_ev_kwh_per_100km': S(17), 'number.sem_charger_keba_ev_phases': S(3), 'time.sem_charger_keba_target_time': S('07:00:00'),
        'button.sem_charger_keba_pause_charging': S('unknown'), 'select.sem_pause_duration': S('2_hours', { options: ['1_hour', '2_hours'] }),
        'binary_sensor.sem_charger_keba_connected': S('on'),
        'sensor.sem_lifetime_ev_energy': S(3412), 'sensor.sem_lifetime_ev_cost': S(268), 'sensor.sem_lifetime_ev_solar_share': S(71), 'sensor.sem_lifetime_ev_sessions': S(186),
        'sensor.sem_heat_pump_sg_ready_state': S(2), 'sensor.sem_heat_pump_mode': S('normal'), 'binary_sensor.sem_heat_pump_solar_boost': S('off'),
        'number.sem_legionella_target_temp': S(60, { unit_of_measurement: '°C' }), 'number.sem_legionella_interval_hours': S(168),
        'sensor.boiler_temp': S(48, { unit_of_measurement: '°C' }), 'sensor.hp_power': S(900, { unit_of_measurement: 'W' }),
        'sensor.sem_controllable_devices_count': S(4, { anti_cycle_bounds: { min: 0, max: 120 }, devices: {
            load_device_keba: { name: 'Car', priority: 1, device_type: 'ev_charger', is_on: true, power_entity: 'sensor.sem_charger_keba_power' },
            heat_pump: { name: 'Heat pump', priority: 2, control_mode: 'surplus', is_on: true, power_entity: 'sensor.hp_power',
                goals: { battery_assist_enabled: true, comfort_target: 20, comfort_offset: 2, comfort_limit: 22, min_on_effective_min: 5 }, comfort: { state: 'banked', reading_c: 20.5 }, progress: { runtime_today_min: 120 } },
            hot_water: { name: 'Hot water', priority: 3, control_mode: 'surplus', is_on: false, power_rating: 2000,
                goals: { daily_min_runtime_min: 60, daily_max_runtime_min: 180, stop_entity: 'sensor.boiler_temp', stop_at: 55, phase: 'L1' }, progress: { runtime_today_min: 0 }, depends_on: ['heat_pump'], blocked_by: 'heat_pump', control: { type: 'switch', entity: 'switch.hot_water' } },
            battery: { name: 'Battery', priority: 4, device_type: 'battery', soc: 58 },
        } }),
    };
    return st;
}

function makeCard(st, extra = {}) {
    const el = new (customElements.get('sem-next-devices-card'))();
    el.setConfig({ type: 'custom:sem-next-devices-card' });
    el.hass = { states: st, language: 'en', config: { currency: 'CHF', unit_system: { temperature: '°C' } }, callService: async () => {}, callWS: async () => ({ rows: [] }), ...extra };
    return el;
}

test('the card renders every device with its body, the surplus section and the lead', () => {
    const el = makeCard(states());
    el._all = true;
    const out = text(el.render());
    assert.match(out, /next_dev_lead2/);
    assert.match(out, /next_surplus_peak/);
    assert.match(out, /operator_limit_banner/);
    for (const k of ['next_st_charging_a', 'next_st_on', 'next_st_waiting_for', 'next_st_to_house',
        'charge_mode_hint_solar_plus_cheap_surplus', 'next_departures', 'next_set_once', 'next_lifetime',
        'help_mode_surplus', 'next_legionella', 'next_sg_ready', 'battery_mode_hint_auto', 'next_bat_sent_fill',
        'planning_phase_holding', 'charge_pacing', 'next_sell_window', 'next_battery_n', 'next_evidence', 'health']) {
        assert.match(out, new RegExp(k), k);
    }
    assert.doesNotMatch(out, /undefined|NaN/);
    assert.equal(el._rowsNow().map((r) => r.id).join(','), 'load_device_keba,heat_pump,hot_water,battery');
});

test('loads start folded, chargers and the battery open; a tap and All settings open them', () => {
    const el = makeCard(states());
    const rows = el._rowsNow();
    const byId = Object.fromEntries(rows.map((r) => [r.id, r]));
    assert.equal(el._isOpen(byId.load_device_keba), true);
    assert.equal(el._isOpen(byId.battery), true);
    assert.equal(el._isOpen(byId.heat_pump), false);
    let out = text(el.render());
    assert.doesNotMatch(out, /help_mode_surplus/);
    assert.match(out, /next_open_all/);
    el._toggleOpen(byId.heat_pump);
    assert.equal(el._isOpen(byId.heat_pump), true);
    el._toggleOpen(byId.battery);
    assert.equal(el._isOpen(byId.battery), false);
    el._setAllOpen(rows, true);
    assert.ok(rows.every((r) => el._isOpen(r)));
    out = text(el.render());
    assert.match(out, /help_mode_surplus/);
    assert.match(out, /next_fold_all/);
    el._setAllOpen(rows, false);
    el._all = true;
    assert.ok(rows.every((r) => el._isOpen(r)));
});

test('observer mode disables the controls and reorder writes the order on Done', async () => {
    const st = states();
    st['switch.sem_observer_mode'] = S('on');
    const calls = [];
    const el = makeCard(st, { callService: async (d, s, data) => { calls.push([s, data]); } });
    const out = text(el.render());
    assert.match(out, /next_observing_hint/);
    st['switch.sem_observer_mode'] = S('off');
    const el2 = makeCard(st, { callService: async (d, s, data) => { calls.push([s, data]); } });
    el2._toggleReorder();
    assert.ok(el2._reorder);
    await el2._move('hot_water', -1);           // a child: locked
    assert.equal(el2._work[2].id, 'hot_water');
    await el2._move('heat_pump', 1);            // heat pump down: its child follows
    assert.deepEqual(el2._work.map((r) => r.id), ['load_device_keba', 'battery', 'heat_pump', 'hot_water']);
    el2._toggleReorder();
    assert.equal(calls[0][0], 'update_device_priorities');
    assert.deepEqual(calls[0][1].priorities.map((p) => p.device_id + ':' + p.priority), ['load_device_keba:1', 'battery:2', 'heat_pump:3', 'hot_water:4']);
    assert.equal(el2._rowsNow()[1].id, 'battery');  // held until the sensor has it
});

test('a missing entity leaves its row out', () => {
    const st = states();
    for (const id of Object.keys(st)) if (/battery_charge_pacing|may_export|forecast_|battery_health|cycles|temperature|measured_capacity|drift|legionella/.test(id)) delete st[id];
    delete st['sensor.sem_target_peak_limit'];
    const out = text(makeCard(st).render());
    for (const k of ['charge_pacing', 'next_sell_window', 'next_evidence', '>health<', 'next_legionella', 'next_sent_limit', 'next_peak']) {
        assert.doesNotMatch(out, new RegExp(k), k);
    }
    assert.match(out, /next_surplus/);
});

test('peak sensors are kW: tile, limit and month peak are not divided again', () => {
    const el = makeCard(states());
    assert.equal(el._kwSensorW('sensor.sem_target_peak_limit'), 5000);
    assert.equal(el._kwSensorW('sensor.sem_consecutive_peak_15min'), 3500);
    const st = states();
    st['sensor.sem_peak_margin'] = S(1500, { unit_of_measurement: 'W' });
    assert.equal(makeCard(st)._kwSensorW('sensor.sem_peak_margin'), 1500);
    el._all = true;
    const out = text(el.render());
    assert.match(out, /3\.5/);
    assert.equal(el._kw(el._kwSensorW('sensor.sem_monthly_consecutive_peak')), '6.1 kW');
});

test('session energy: the charger counter first, SEM counter when it reads 0', () => {
    const st = states();
    st['sensor.sem_charger_keba_session_energy_external'] = S(9.1);
    let el = makeCard(st); el._all = true;
    assert.match(text(el.render()), /9\.1 kWh/);
    st['sensor.sem_charger_keba_session_energy_external'] = S(0);
    el = makeCard(st); el._all = true;
    assert.match(text(el.render()), /8\.4 kWh/);
});

test('solar + battery with an at-least target says it may use the grid at night', () => {
    const st = states();
    st['select.sem_charger_keba_charge_mode'] = S('solar_plus_battery', { options: ['solar_only', 'solar_plus_battery', 'off'] });
    let el = makeCard(st); el._all = true;
    assert.match(text(el.render()), /next_floor_uses_grid/);
    st['number.sem_charger_keba_target_soc'] = S(0, { min: 0, max: 100, step: 5 });
    el = makeCard(st); el._all = true;
    assert.doesNotMatch(text(el.render()), /next_floor_uses_grid/);
});

test('a load SEM can not switch is shown as measured only, without modes or permissions', () => {
    const st = states();
    st['sensor.sem_controllable_devices_count'].attributes.devices.meter = {
        name: 'Meter only', priority: 5, control_mode: 'peak_only', is_on: true, has_control_handle: false, control: null,
        power_entity: 'sensor.hp_power', goals: {}, progress: {},
    };
    const el = makeCard(st); el._all = true;
    const row = el._rowsNow().find((r) => r.id === 'meter');
    assert.equal(row.hasControlHandle, false);
    const out = text(el.render());
    assert.match(out, /next_measure_only/);
    const body = out.slice(out.indexOf('Meter only'));
    const end = body.indexOf('</section>');
    const section = body.slice(0, end);
    assert.doesNotMatch(section, /next_may_switch|next_min_run_pause|requires/);
});

test('a load whose rating is the 1 kW placeholder says not measured, not ~1.0 kW (#1326)', () => {
    const st = states();
    const devs = st['sensor.sem_controllable_devices_count'].attributes.devices;
    devs.hot_water.rating_measured = false;
    devs.hot_water.power_rating = 1000;
    const el = makeCard(st);
    el._all = true;
    const row = el._rowsNow().find((r) => r.id === 'hot_water');
    assert.equal(row.ratingMeasured, false);
    const out = text(el.render());
    assert.match(out, /rating_not_measured/);
    devs.hot_water.rating_measured = true;
    assert.equal(makeCard(st)._rowsNow().find((r) => r.id === 'hot_water').ratingMeasured, true);
    delete devs.hot_water.rating_measured;
    assert.equal(makeCard(st)._rowsNow().find((r) => r.id === 'hot_water').ratingMeasured, true);
});

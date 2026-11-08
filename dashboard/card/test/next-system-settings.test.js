/**
 * (#1321) The System screen replaces the classic setup card: entity fields
 * as pickers with the classic card's filters, per-charger hardware, add and
 * remove a charger, PV names, battery wiring, scheduler tuning and VPP.
 *
 * Run: `node --test test/next-system-settings.test.js` (from dashboard/card).
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { groups, applyPlan, pendingKey, slotText, slotsOf, chargerSkeleton, isValueContact,
         ENTITY_FIELDS, CHARGER_ENTITY_FIELDS, STRUCTURAL_KEYS } from '../src/util/next-settings.js';

const K_AUTO = 'next_entity_auto';
const K_NONE = 'config_notif_none';
const K_HEAT_NONE = 'next_heat_none';
const TEXT = { [K_AUTO]: '{name} (auto)', next_reads_solar: 'solar from {solar}', next_reads_house: 'house {house}',
               next_reads_grid: 'grid from {grid} ({flip})', next_hp_contact: 'on contact {relay1}' };
const t = (k) => TEXT[k] || k;

const sw = (on) => ({ state: on ? 'on' : 'off', attributes: {} });
function states() {
    return {
        'sensor.sem_charging_state': { state: 'solar', attributes: {} },
        'sensor.sem_battery_soc': { state: '55', attributes: {} },
        'switch.sem_observer_mode': sw(false),
        'sensor.pv': { state: '0', attributes: { friendly_name: 'Inverter input power' } },
        'sensor.meter': { state: '0', attributes: { friendly_name: 'Meter' } },
        'sensor.my_grid': { state: '0', attributes: { friendly_name: 'My grid meter' } },
        'sensor.sem_pv_string_pv1_power': { state: '0', attributes: { string_name: 'East' } },
        'sensor.sem_pv_string_pv2_power': { state: '0', attributes: {} },
        'sensor.sem_diag_ed_config': { state: 'ok', attributes: { energy_dashboard: { solar: { power: 'sensor.pv' }, grid: { power: 'sensor.meter' } } } },
    };
}
const OPTS = {
    tariff_mode: 'static',
    ev_chargers: [{ id: 'keba', ev_current_control_entity: 'number.keba_current', external_control_mode: 'none' },
                  { id: 'wb2', ev_phase_switch_entity: 'select.wb2_phases', external_control_mode: 'yield' }],
    pv_string_names: { pv1: 'East' },
};
const CTX = { options: OPTS, currency: 'CHF', chargers: [{ cid: 'keba', name: 'Keba' }, { cid: 'wb2', name: 'Box 2' }], labels: {} };

const all = (opts = OPTS, st = states()) => slotsOf(groups(st, t, { ...CTX, options: opts }));
const find = (slots, pred) => slots.find(pred);

test('the four sources are pickers that show what SEM found until overridden', () => {
    const reads = groups(states(), t, CTX).find((g) => g.key === 'reads');
    const solar = find(reads.sentence, (p) => p && p.option === 'solar_production_sensor');
    assert.equal(solar.kind, 'entity');
    assert.equal(solar.value, '');
    assert.equal(solar.fallback, 'sensor.pv');
    assert.deepEqual(solar.domains, ['sensor']);
    assert.equal(solar.deviceClass, 'power');
    assert.equal(slotText(solar, t, solar.value, states()), 'Inverter input power (auto)');
    assert.equal(slotText(solar, t, 'sensor.my_grid', states()), 'My grid meter');
    const house = find(reads.sentence, (p) => p && p.option === 'house_power_sensor');
    assert.equal(slotText(house, t, '', states()), 'next_computed');
});

test('an entity with nothing set and nothing found reads None', () => {
    const co2 = find(all(), (s) => s.option === 'grid_co2_entity');
    assert.equal(slotText(co2, t, '', states()), K_NONE);
    assert.equal(co2.deviceClass, 'co2_intensity');
});

test('every entity slot carries the classic picker filters for its key', () => {
    for (const s of all({ ...OPTS, vpp_enabled: true, battery_strategy_control_entity: 'select.x', battery_setpoint_model: 'direction_select', battery_charge_platform: 'deye' })) {
        if (s.kind !== 'entity') continue;
        const f = s.charger ? CHARGER_ENTITY_FIELDS[s.key] : ENTITY_FIELDS[s.option];
        assert.ok(f, `${s.option}/${s.key} has a field spec`);
        const doms = Array.isArray(f.domain) ? f.domain : [f.domain];
        assert.deepEqual(s.domains, doms, s.option);
    }
});

test('per-charger hardware: pickers per charger, values only once their entity is set', () => {
    const slots = all();
    const cur = find(slots, (s) => s.charger === 'keba' && s.key === 'ev_current_control_entity');
    assert.equal(cur.kind, 'entity');
    assert.equal(cur.value, 'number.keba_current');
    assert.equal(pendingKey(cur), 'opt:ev_chargers:keba:ev_current_control_entity');
    // keba has no phase switch → no 1p/3p values; wb2 has one → both values
    assert.ok(!find(slots, (s) => s.charger === 'keba' && s.key === 'ev_phase_switch_value_1p'));
    assert.ok(find(slots, (s) => s.charger === 'wb2' && s.key === 'ev_phase_switch_value_1p'));
    assert.ok(find(slots, (s) => s.charger === 'wb2' && s.key === 'ev_phase_switch_value_3p'));
    // the steering indicator only when another party steers
    assert.ok(!find(slots, (s) => s.charger === 'keba' && s.key === 'external_control_indicator'));
    assert.ok(find(slots, (s) => s.charger === 'wb2' && s.key === 'external_control_indicator'));
});

test('two chargers: each hardware row is labelled with its charger', () => {
    const ch = groups(states(), t, CTX).find((g) => g.key === 'chargers');
    const labels = ch.more.filter((p) => typeof p === 'string');
    assert.ok(labels.some((l) => l.includes('Keba · config_ev_current_control')));
    assert.ok(labels.some((l) => l.includes('Box 2 · config_ev_phase_switch')));
    assert.equal(ch.count, slotsOf([ch]).filter((s) => ch.more.includes(s)).length);
});

test('Apply: a charger picker writes only that key of that charger, by id', () => {
    const slots = all();
    const cur = find(slots, (s) => s.charger === 'keba' && s.key === 'ev_current_control_entity');
    const soc = find(slots, (s) => s.charger === 'wb2' && s.key === 'vehicle_soc_entity');
    const plan = applyPlan({ [pendingKey(cur)]: { slot: cur, value: 'number.other' },
                             [pendingKey(soc)]: { slot: soc, value: 'sensor.car_soc' } }, {});
    assert.deepEqual(plan.options.ev_chargers, [{ id: 'keba', ev_current_control_entity: 'number.other' },
                                                { id: 'wb2', vehicle_soc_entity: 'sensor.car_soc' }]);
    assert.ok(plan.reload);
});

test('Apply: a source override is structural; clearing it sends an empty string', () => {
    const grid = find(all(), (s) => s.option === 'grid_power_sensor');
    assert.ok(STRUCTURAL_KEYS.has('grid_power_sensor'));
    let plan = applyPlan({ [pendingKey(grid)]: { slot: grid, value: 'sensor.my_grid' } }, {});
    assert.deepEqual(plan.options, { grid_power_sensor: 'sensor.my_grid' });
    assert.ok(plan.reload);
    plan = applyPlan({ [pendingKey(grid)]: { slot: grid, value: '' } }, {});
    assert.deepEqual(plan.options, { grid_power_sensor: '' });
    const co2 = find(all(), (s) => s.option === 'grid_co2_entity');
    plan = applyPlan({ [pendingKey(co2)]: { slot: co2, value: 'sensor.co2' } }, {});
    assert.ok(!plan.reload, 'a non-structural pick does not reload');
});

test('PV names: one slot per string, merged into the saved dict, blank clears', () => {
    const slots = all();
    const pv1 = find(slots, (s) => s.option === 'pv_string_names' && s.pv === 'pv1');
    const pv2 = find(slots, (s) => s.option === 'pv_string_names' && s.pv === 'pv2');
    assert.equal(pv1.value, 'East');
    assert.equal(slotText(pv2, t, ''), 'PV2');
    const plan = applyPlan({ [pendingKey(pv1)]: { slot: pv1, value: ' ' }, [pendingKey(pv2)]: { slot: pv2, value: 'West ' } }, {});
    assert.deepEqual(plan.options.pv_string_names, { pv2: 'West' });
    assert.ok(plan.reload);
});

test('battery wiring: strategy values only with a strategy entity, scheduler tuning only when on', () => {
    let s = all();
    assert.ok(find(s, (x) => x.option === 'battery_strategy_control_entity'));
    assert.ok(!find(s, (x) => x.option === 'battery_strategy_active_value'));
    assert.ok(!find(s, (x) => x.option === 'battery_roundtrip_efficiency'));
    assert.ok(!find(s, (x) => x.option === 'battery_external_control_indicator'));
    s = all({ ...OPTS, battery_strategy_control_entity: 'select.mode', battery_charge_scheduler_enabled: true,
              battery_external_control_mode: 'observe', battery_setpoint_model: 'direction_select' });
    for (const k of ['battery_strategy_active_value', 'battery_strategy_idle_value', 'battery_strategy_self_consume_value',
                     'battery_strategy_off_value', 'battery_roundtrip_efficiency', 'battery_cycle_cost', 'battery_max_charge_power_w',
                     'battery_max_target_soc', 'battery_min_deficit_kwh', 'battery_pessimism_weight', 'battery_precharge_trigger_hour',
                     'battery_prefer_consecutive_window', 'battery_replan_interval_min', 'battery_force_charge_negative_price',
                     'battery_external_control_indicator', 'battery_power_direction_entity', 'battery_direction_discharge_value']) {
        assert.ok(find(s, (x) => x.option === k), k);
    }
    const active = find(s, (x) => x.option === 'battery_strategy_active_value');
    assert.equal(slotText(active, t, ''), 'api');
});

test('a setpoint model outside the list keeps its value as an option', () => {
    const m = find(all({ ...OPTS, battery_setpoint_model: 'custom_x' }), (x) => x.option === 'battery_setpoint_model');
    assert.ok(m.options.some((o) => o.value === 'custom_x'));
});

test('VPP sits in What SEM may do; its entities show once it is on', () => {
    let g = groups(states(), t, CTX);
    const may = g.find((x) => x.key === 'may');
    assert.ok(slotsOf([may]).some((s) => s.option === 'vpp_enabled'));
    assert.ok(!slotsOf(g).some((s) => s.option === 'vpp_event_active_entity'));
    g = groups(states(), t, { ...CTX, options: { ...OPTS, vpp_enabled: true } });
    const vppKeys = slotsOf(g).filter((s) => String(s.option || '').startsWith('vpp_')).map((s) => s.option);
    for (const k of ['vpp_enabled', 'vpp_observer_mode', 'vpp_event_active_entity', 'vpp_direction_entity',
                     'vpp_event_end_entity', 'vpp_pre_event_entity', 'vpp_reserve_soc']) assert.ok(vppKeys.includes(k), k);
});

test('heat pump: the group is there to set one up; a set contact is not listed twice', () => {
    let heat = groups(states(), t, CTX).find((g) => g.key === 'heat');
    assert.deepEqual(heat.sentence, [K_HEAT_NONE]);
    assert.ok(slotsOf([heat]).some((s) => s.option === 'heat_pump_relay1_entity'));
    assert.ok(slotsOf([heat]).some((s) => s.option === 'hot_water_entity'));
    heat = groups(states(), t, { ...CTX, options: { ...OPTS, heat_pump_relay1_entity: 'select.sg1' } }).find((g) => g.key === 'heat');
    const relay1 = slotsOf([heat]).filter((s) => s.option === 'heat_pump_relay1_entity');
    assert.equal(relay1.length, 1);
    assert.ok(heat.sentence.includes(relay1[0]), 'the contact is in the sentence');
    // a select contact takes on/off values
    assert.ok(slotsOf([heat]).some((s) => s.option === 'heat_pump_relay1_on_value'));
    assert.ok(isValueContact('select.sg1'));
    assert.ok(!isValueContact('switch.sg1'));
});

test('pending keys stay unique with every optional row shown', () => {
    const rich = { ...OPTS, tariff_mode: 'dynamic', vpp_enabled: true, battery_strategy_control_entity: 'select.x',
                   battery_charge_scheduler_enabled: true, battery_external_control_mode: 'yield',
                   battery_setpoint_model: 'direction_select', battery_charge_platform: 'deye',
                   heat_pump_relay1_entity: 'select.a', heat_pump_relay2_entity: 'text.b', hot_water_entity: 'switch.hw',
                   shed_signal_entity: 'binary_sensor.relay' };
    const keys = all(rich).map(pendingKey);
    assert.equal(new Set(keys).size, keys.length);
});

test('add charger: the classic id rule and skeleton', () => {
    assert.deepEqual(chargerSkeleton([], [], 'New charger'),
        { id: 'ev_charger', name: 'New charger 1', ev_min_current: 6, ev_surplus_priority: 3 });
    const sk = chargerSkeleton([{ id: 'ev_charger' }], ['ev_charger_1'], 'New charger');
    assert.equal(sk.id, 'ev_charger_2');
    assert.equal(sk.name, 'New charger 2');
    assert.equal(sk.ev_surplus_priority, 4);
});

test('the System card never sends the user to the classic dashboard', () => {
    const src = readFileSync(new URL('../src/cards/sem-next-system-card.js', import.meta.url), 'utf8');
    assert.ok(!src.includes('/sem-dashboard'));
    assert.ok(src.includes('/config/integrations/integration/solar_energy_management'));
    assert.ok(src.includes("'remove_charger'"));
    assert.ok(src.includes('_setupPanel(kind)'));
});

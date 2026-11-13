/**
 * (#1321) The System screen's settings as sentences: groups built from
 * real ids only, a missing entity leaves its slot out, Apply maps to the
 * right service calls and reloads only on a structural key.
 *
 * Run: `node --test test/next-settings.test.js` (from dashboard/card).
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { groups, applyPlan, pendingKey, slotText, slotsOf, setupItems, loadSources,
         unavailableCount, reserveIds, STRUCTURAL_KEYS } from '../src/util/next-settings.js';

// Keys as variables; the stub returns the key with its placeholders so a
// fragment's shape is visible without English in the asserts.
const K_PAY_STATIC = 'next_pay_static';
const K_PAY_DYNAMIC = 'next_pay_dynamic';
const K_BATT_ZONES = 'next_batt_zones';
const K_CH_NONE = 'next_ch_none';
const TEXT = {
    [K_PAY_STATIC]: 'prices are {mode}: {rate} per kWh.',
    [K_PAY_DYNAMIC]: 'prices are {mode} from {provider}.',
    next_pay_mode: 'prices are {mode}.',
    next_pay_rate: 'prices: {rate} per kWh.',
    next_pay_plus_vat: 'plus VAT {vat}',
    next_pay_plus_fee: 'plus a grid fee of {fee}',
    next_pay_export: 'export pays {export}',
    next_pay_thresholds_plain: 'cheap means below {cheap}, expensive above {expensive}',
    [K_BATT_ZONES]: 'fill the battery first below {priority}, buffer at {buffer}, help the house above {autostart}',
    next_batt_zones_two: 'fill the battery first below {priority}, buffer at {buffer}',
    next_batt_spend: 'spend forecast sun {v}',
    next_batt_sell: 'sell {v}',
    next_ch_name_control: '{name} controls {control}',
    next_ch_amps: '{min} to {max}',
    next_ch_targets: 'targets in {type}',
    next_misc_interval: 'update every {interval}',
    next_misc_night: 'night starts {offset} after sunset and ends by {end}',
    next_misc_night_offset: 'night starts {offset} after sunset',
    next_reads_grid: 'grid from {grid} ({flip})',
    next_reads_house: 'house {house}',
    next_on: 'on', next_off: 'off',
};
const t = (k) => TEXT[k] || k;

const numE = (state, min, max, step, unit) => ({ state: String(state), attributes: { min, max, step, unit_of_measurement: unit } });
const sw = (on) => ({ state: on ? 'on' : 'off', attributes: {} });

function fullStates() {
    return {
        'sensor.sem_charging_state': { state: 'solar', attributes: {} },
        'sensor.sem_battery_soc': numE(55, 0, 100, 1, '%'),
        'number.sem_electricity_import_rate': numE(0.28, 0, 10000, 0.01, 'CHF/kWh'),
        'number.sem_electricity_export_rate': numE(0.12, 0, 10000, 0.005, 'CHF/kWh'),
        'number.sem_cheap_price_threshold': numE(0.22, 0, 2, 0.01, 'CHF/kWh'),
        'number.sem_expensive_price_threshold': numE(0.33, 0, 2, 0.01, 'CHF/kWh'),
        'number.sem_battery_priority_soc': numE(50, 0, 100, 1, '%'),
        'number.sem_battery_buffer_soc': numE(20, 0, 100, 1, '%'),
        'number.sem_battery_auto_start_soc': numE(30, 0, 100, 1, '%'),
        'switch.sem_forecast_spending_enabled': sw(true),
        'switch.sem_battery_may_export': sw(false),
        'number.sem_battery_b1_reserve_soc': numE(20, 0, 100, 1, '%'),
        'number.sem_battery_b2_reserve_soc': numE(20, 0, 100, 1, '%'),
        'number.sem_charger_keba_minimum_current': numE(6, 6, 32, 1, 'A'),
        'number.sem_charger_keba_maximum_current': numE(16, 6, 32, 1, 'A'),
        'number.sem_charger_keba_ev_phases': numE(3, 1, 3, 1, ''),
        'number.sem_update_interval': numE(30, 10, 300, 5, 's'),
        'number.sem_night_start_offset_min': numE(30, 0, 180, 5, 'min'),
        'select.sem_hints': { state: 'weekly', attributes: { options: ['off', 'weekly', 'all'] } },
        'switch.sem_vacation_mode': sw(false),
        'switch.sem_observer_mode': sw(false),
        'sensor.sem_diag_ed_config': { state: 'ok', attributes: { energy_dashboard: { solar: { power: 'sensor.pv' }, grid: { power: 'sensor.meter' } } } },
        'sensor.sem_diag_sensors_unavailable': { state: '2', attributes: {} },
        'sensor.sem_controllable_devices_count': { state: '2', attributes: { devices: {
            keba: { name: 'Keba', device_type: 'ev_charger', power_entity: 'sensor.keba_p' },
            hp: { name: 'Heat pump', device_type: 'heat_pump', power_entity: 'sensor.hp_p' },
            relay: { name: 'Pool', power_entity: '' },
        } } },
    };
}
const OPTS = { tariff_mode: 'static', import_vat_percent: 8.1, grid_import_surcharge: 0.02,
               target_peak_limit: 5, warning_peak_level: 4.5, emergency_peak_level: 6,
               ev_chargers: [{ id: 'keba', ev_target_type: 'kwh', finish_by_departure: false }],
               status_retention_days: 0 };
const CTX = { options: OPTS, currency: 'CHF', chargers: [{ cid: 'keba', name: 'Keba' }],
              labels: { control: 'via action', gridSign: 'import negative' } };

const strings = (parts) => parts.filter((p) => typeof p === 'string').join('');
const slots = (parts) => parts.filter((p) => p && typeof p === 'object');

test('seven groups in the order of the mockup, each with a sentence', () => {
    const g = groups(fullStates(), t, { ...CTX, options: { ...OPTS, hot_water_entity: 'switch.boiler' } });
    assert.deepEqual(g.map((x) => x.key), ['pay', 'may', 'battery', 'chargers', 'heat', 'reads', 'misc']);
    for (const x of g) {
        assert.ok(x.sentence.length, x.key);
        assert.ok(x.titleKey.startsWith('next_g_'));
        assert.ok(x.diagnoseSection);
        assert.ok(!strings(x.sentence).includes('{'), x.key + ' leaves no placeholder');
        assert.ok(!strings(x.sentence).includes('undefined'), x.key);
    }
});

test('a static tariff binds the rate to its number entity and keeps the text around it', () => {
    const pay = groups(fullStates(), t, CTX).find((x) => x.key === 'pay');
    const rate = slots(pay.sentence).find((s) => s.id === 'number.sem_electricity_import_rate');
    assert.ok(rate);
    assert.equal(rate.kind, 'number');
    assert.equal(rate.unit, 'CHF/kWh');
    assert.equal(rate.step, 0.01);
    const mode = slots(pay.sentence).find((s) => s.option === 'tariff_mode');
    assert.equal(mode.value, 'static');
    assert.ok(strings(pay.sentence).startsWith('Prices are '));
    // (#1354) an all-in price (the default basis) takes no VAT: not in the sentence, not in More
    assert.equal(slots(pay.sentence).find((s) => s.option === 'import_vat_percent'), undefined);
    assert.ok(!pay.more.some((m) => JSON.stringify(m).includes('import_vat_percent')));
});

test('a spot price names the VAT that applies; a dynamic tariff adds its grid fee', () => {
    const pay = groups(fullStates(), t, { ...CTX, options: { ...OPTS, import_price_basis: 'spot', tariff_mode: 'dynamic', grid_import_surcharge: 0.05 } })
        .find((x) => x.key === 'pay');
    const vat = slots(pay.sentence).find((s) => s.option === 'import_vat_percent');
    assert.equal(vat.value, 8.1);
    assert.equal(vat.unit, '%');
    const fee = slots(pay.sentence).find((s) => s.option === 'grid_import_surcharge');
    assert.equal(fee.value, 0.05);
    assert.match(strings(pay.sentence), /plus VAT/i);
    // a static tariff never adds the grid fee, so it is neither said nor offered
    const st = groups(fullStates(), t, { ...CTX, options: { ...OPTS, import_price_basis: 'spot', grid_import_surcharge: 0.05 } })
        .find((x) => x.key === 'pay');
    assert.equal(slots(st.sentence).find((s) => s.option === 'grid_import_surcharge'), undefined);
    assert.ok(!st.more.some((m) => JSON.stringify(m).includes('grid_import_surcharge')));
});

test('a dynamic tariff names the provider as plain text, not a control', () => {
    const pay = groups(fullStates(), t, { ...CTX, options: { ...OPTS, tariff_mode: 'dynamic' }, labels: { provider: 'Tibber' } })
        .find((x) => x.key === 'pay');
    const prov = slots(pay.sentence).find((s) => s.ro);
    assert.equal(prov.value, 'Tibber');
    assert.ok(!slots(pay.sentence).some((s) => s.id === 'number.sem_electricity_import_rate'));
});

test('a missing entity drops its fragment; the sentence still reads', () => {
    const states = fullStates();
    delete states['number.sem_battery_auto_start_soc'];
    const batt = groups(states, t, CTX).find((x) => x.key === 'battery');
    const ids = slots(batt.sentence).map((s) => s.id);
    assert.ok(ids.includes('number.sem_battery_priority_soc'));
    assert.ok(!ids.includes('number.sem_battery_auto_start_soc'));
    assert.ok(strings(batt.sentence).includes('buffer at'));
    assert.ok(!strings(batt.sentence).includes('help the house'));
    // the flags that exist are joined into one sentence, capitalised once
    const txt = strings(batt.sentence);
    assert.ok(txt.includes('Spend forecast sun '));
    assert.ok(txt.includes(', sell '));
});

test('no battery, no battery group; no charger, a one-line charger group', () => {
    const states = fullStates();
    delete states['sensor.sem_battery_soc'];
    delete states['number.sem_battery_b1_reserve_soc'];
    delete states['number.sem_battery_b2_reserve_soc'];
    const g = groups(states, t, { ...CTX, chargers: [] });
    assert.ok(!g.some((x) => x.key === 'battery'));
    const ch = g.find((x) => x.key === 'chargers');
    assert.deepEqual(ch.sentence, [K_CH_NONE]);
});

test('options not loaded yet: option slots are left out, entity slots stay', () => {
    const g = groups(fullStates(), t, { ...CTX, options: null });
    const pay = g.find((x) => x.key === 'pay');
    assert.ok(!slots(pay.sentence).some((s) => s.option));
    assert.ok(slots(pay.sentence).some((s) => s.id === 'number.sem_electricity_import_rate'));
    const may = g.find((x) => x.key === 'may');
    assert.equal(may.sentence.length, 0);
});

test('per-charger values: the amps pair, the target type as a nested option', () => {
    const ch = groups(fullStates(), t, CTX).find((x) => x.key === 'chargers');
    const s = slots(ch.sentence);
    assert.ok(s.some((x) => x.id === 'number.sem_charger_keba_minimum_current'));
    assert.ok(s.some((x) => x.id === 'number.sem_charger_keba_maximum_current'));
    const type = s.find((x) => x.option === 'ev_chargers');
    assert.equal(type.charger, 'keba');
    assert.equal(type.key, 'ev_target_type');
    assert.deepEqual(type.options.map((o) => o.value), ['kwh']);
    assert.equal(pendingKey(type), 'opt:ev_chargers:keba:ev_target_type');
    assert.ok(ch.more.length);
    assert.equal(ch.count, slots(ch.more).length);
});

test('the observer switch is never a settings slot', () => {
    const all = slotsOf(groups(fullStates(), t, CTX));
    assert.ok(!all.some((s) => s.id === 'switch.sem_observer_mode'));
    const keys = all.map(pendingKey);
    assert.equal(new Set(keys).size, keys.length, 'pending keys are unique');
});

test('slotText: units, decimals from the step, on/off words, a zero label', () => {
    assert.equal(slotText({ kind: 'number', value: 0.28, step: 0.01, unit: 'CHF/kWh' }, t), '0.28 CHF/kWh');
    assert.equal(slotText({ kind: 'number', value: 5, step: 0.1, unit: 'kW' }, t), '5.0 kW');
    assert.equal(slotText({ kind: 'number', value: 30, step: 5, unit: 's' }, t), '30 s');
    assert.equal(slotText({ kind: 'number', value: 0, step: 1, unit: 'days', zeroKey: 'config_retention_off' }, t), 'config_retention_off');
    assert.equal(slotText({ kind: 'switch', value: true }, t), 'on');
    assert.equal(slotText({ kind: 'number', value: 7.5, step: 0.5, unit: 'h', clock: true }, t), '07:30');
    assert.equal(slotText({ kind: 'select', value: 'weekly', options: [{ value: 'weekly', labelKey: 'weekly' }] }, t), 'weekly');
});

test('applyPlan: entities write directly, options go in one payload, reload only when structural', () => {
    const states = fullStates();
    const pending = {
        'number.sem_update_interval': { slot: { id: 'number.sem_update_interval', kind: 'number' }, value: 500 },
        'switch.sem_vacation_mode': { slot: { id: 'switch.sem_vacation_mode', kind: 'switch' }, value: true },
        'select.sem_hints': { slot: { id: 'select.sem_hints', kind: 'select' }, value: 'all' },
        'opt:target_peak_limit': { slot: { option: 'target_peak_limit', kind: 'number' }, value: '6.5' },
        'opt:tariff_mode': { slot: { option: 'tariff_mode', kind: 'select' }, value: 'dynamic' },
    };
    const plan = applyPlan(pending, states);
    assert.deepEqual(plan.entityWrites, [
        { domain: 'number', service: 'set_value', data: { entity_id: 'number.sem_update_interval', value: 300 } },
        { domain: 'switch', service: 'turn_on', data: { entity_id: 'switch.sem_vacation_mode' } },
        { domain: 'select', service: 'select_option', data: { entity_id: 'select.sem_hints', option: 'all' } },
    ]);
    assert.deepEqual(plan.options, { target_peak_limit: 6.5, tariff_mode: 'dynamic' });
    assert.equal(plan.reload, false);
});

test('applyPlan: a per-charger key becomes an ev_chargers entry with its id, and reloads', () => {
    const pending = {
        'opt:ev_chargers:keba:finish_by_departure': { slot: { option: 'ev_chargers', charger: 'keba', key: 'finish_by_departure', kind: 'switch' }, value: true },
        'opt:ev_chargers:keba:ev_target_type': { slot: { option: 'ev_chargers', charger: 'keba', key: 'ev_target_type', kind: 'select' }, value: 'soc' },
        'opt:heat_pump_rated_power': { slot: { option: 'heat_pump_rated_power', kind: 'number' }, value: 3200 },
    };
    const plan = applyPlan(pending, {});
    assert.deepEqual(plan.options.ev_chargers, [{ id: 'keba', finish_by_departure: true, ev_target_type: 'soc' }]);
    assert.equal(plan.options.heat_pump_rated_power, 3200);
    assert.equal(plan.reload, true);
    assert.ok(STRUCTURAL_KEYS.has('heat_pump_rated_power'));
    assert.deepEqual(applyPlan({}, {}), { entityWrites: [], options: {}, listEdits: [], reload: false });
});

test('setup check, load tiles, unavailable count and reserve ids read real ids only', () => {
    const states = fullStates();
    const items = setupItems(states, OPTS);
    assert.equal(items.find((i) => i.key === 'energy').done, true);
    assert.equal(items.find((i) => i.key === 'ev').done, true);
    assert.equal(items.find((i) => i.key === 'tariff').done, false);  // static mode needs a saved rate
    assert.equal(items.find((i) => i.key === 'battery').done, true);
    assert.equal(items.find((i) => i.key === 'loads').optional, true);
    assert.deepEqual(loadSources(states), [{ id: 'hp', name: 'Heat pump', entity: 'sensor.hp_p' }]);
    const u = unavailableCount(states);
    assert.equal(u.n, 2);
    assert.ok(u.m >= 20);
    assert.deepEqual(reserveIds(states), ['number.sem_battery_b1_reserve_soc', 'number.sem_battery_b2_reserve_soc']);
});

// (#523, #1204) Two batteries: one picker row per battery and list, and an
// edit sends only that battery's slot with the order it was read in.
test('per-battery entity rows send one slot with the battery order', async () => {
    const { groups, applyPlan, pendingKey, BATTERY_LISTS } = await import('../src/util/next-settings.js');
    const states = {
        'sensor.sem_battery_soc': { state: '50', attributes: {} },
        'sensor.sem_battery_power': { state: '0', attributes: {} },
        'sensor.sem_battery_b1_power': { state: '0', attributes: {} },
        'sensor.sem_battery_b2_power': { state: '0', attributes: {} },
    };
    const options = { battery_slot_units: ['u1', 'u2'], battery_discharge_control_entities: ['number.limit_1', null] };
    const g = groups(states, (k) => k, { options }).find((x) => x.key === 'battery');
    const slots = g.more.filter((p) => p && typeof p === 'object' && Number.isInteger(p.listIdx));
    assert.equal(slots.length, BATTERY_LISTS.length * 2);
    const first = slots.find((s) => s.option === 'battery_discharge_control_entities' && s.listIdx === 0);
    assert.equal(first.value, 'number.limit_1');
    const second = slots.find((s) => s.option === 'battery_discharge_control_entities' && s.listIdx === 1);
    assert.notEqual(pendingKey(first), pendingKey(second));
    const plan = applyPlan({ [pendingKey(second)]: { slot: second, value: 'number.limit_2' } }, states);
    assert.deepEqual(plan.listEdits, [{ battery_discharge_control_entities: { slot: 1, value: 'number.limit_2', battery_slot_units: ['u1', 'u2'] } }]);
    assert.deepEqual(plan.options, {});
    assert.equal(plan.reload, true);
});

test('one battery shows no per-battery rows', async () => {
    const { groups } = await import('../src/util/next-settings.js');
    const states = { 'sensor.sem_battery_soc': { state: '50', attributes: {} }, 'sensor.sem_battery_power': { state: '0', attributes: {} },
                     'sensor.sem_battery_b1_power': { state: '0', attributes: {} } };
    const g = groups(states, (k) => k, { options: { battery_slot_units: ['u1'] } }).find((x) => x.key === 'battery');
    assert.equal(g.more.filter((p) => p && typeof p === 'object' && Number.isInteger(p.listIdx)).length, 0);
});

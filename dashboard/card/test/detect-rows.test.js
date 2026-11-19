/**
 * (#1054 follow-up) The Detected-hardware rows and the power pickers read
 * the same facts the crawler does.
 *
 * - a near miss that carries a complete offer is "charger found — add it",
 *   not "no role matched";
 * - a charger that already exists is never created again: no ``<id>_1``;
 * - a sensor in kW with no device class IS a power reading (go-e ``p_all``);
 * - (#1137) a charger whose roles matched but that has no control SEM can
 *   drive says what was found — never "no role matched", never a report.
 */
import { test } from 'node:test';
import assert from 'node:assert';
import {
    chargerAddPlan, detectRowLabelKey, isCo2IntensityEntity, isPowerEntity,
    isWatchOnlyCharger, nearMissAction, proposalWrite, watchOnlyHelpKey,
} from '../src/util/detect-rows.js';
import { readFileSync } from 'node:fs';

test('a near miss with a complete offer says so', () => {
    assert.equal(detectRowLabelKey({ suggested_charger: { id: 'goecharger_x' }, missing: [] }),
        'config_detect_offer');
});

test('a near miss without an offer still asks for a report', () => {
    assert.equal(detectRowLabelKey({ suggested_charger: {}, missing: ['control'] }),
        'config_detect_near_miss');
    assert.equal(detectRowLabelKey({}), 'config_detect_near_miss');
});

test('an existing charger is never created twice', () => {
    const plan = chargerAddPlan({ id: 'goecharger_x', name: 'go-e' },
        ['goecharger_x'], 1);
    assert.deepEqual(plan, { action: 'exists', id: 'goecharger_x' });
});

test('a new charger keeps the id the crawler gave it', () => {
    const plan = chargerAddPlan({ id: 'goecharger_x', name: 'go-e' }, ['ev_charger'], 1);
    assert.equal(plan.action, 'add');
    assert.equal(plan.charger.id, 'goecharger_x');
    assert.equal(plan.charger.ev_min_current, 6);
    assert.equal(plan.charger.ev_surplus_priority, 4);
});

test('no id means nothing to add', () => {
    assert.equal(chargerAddPlan({}, [], 0).action, 'none');
    assert.equal(chargerAddPlan(null, [], 0).action, 'none');
});

test('a kW sensor with no device class is a power reading', () => {
    assert.equal(isPowerEntity({ attributes: { unit_of_measurement: 'kW' } }), true);
    assert.equal(isPowerEntity({ attributes: { unit_of_measurement: 'W' } }), true);
    assert.equal(isPowerEntity({ attributes: { device_class: 'power', unit_of_measurement: 'W' } }), true);
});

test('a set class wins over the unit, and other units say nothing', () => {
    assert.equal(isPowerEntity({ attributes: { device_class: 'energy', unit_of_measurement: 'kWh' } }), false);
    assert.equal(isPowerEntity({ attributes: { unit_of_measurement: 'A' } }), false);
    assert.equal(isPowerEntity({ attributes: {} }), false);
    assert.equal(isPowerEntity(null), false);
});

test('(#1088) the CO2 picker shows sensors by unit, whatever their integration', () => {
    const st = (unit) => ({ attributes: { unit_of_measurement: unit } });
    assert.equal(isCo2IntensityEntity(st('gCO2eq/kWh')), true);   // Electricity Maps
    assert.equal(isCo2IntensityEntity(st('g CO\u2082/kWh')), true); // spaces, subscript
    assert.equal(isCo2IntensityEntity(st('kgCO2/kWh')), true);
    assert.equal(isCo2IntensityEntity(st('kg')), false);           // SEM's own CO2 avoided
    assert.equal(isCo2IntensityEntity(st('%')), false);            // fossil fuel share
    assert.equal(isCo2IntensityEntity({}), false);
});

test('(#1082) the outdoor temperature picker shows thermometers and real weather entities', async () => {
    const { isOutdoorTemperatureCandidate: f } = await import('../src/util/detect-rows.js');
    assert.equal(f({ entity_id: 'sensor.wetterstation_temp', attributes: { device_class: 'temperature' } }), true);
    assert.equal(f({ entity_id: 'sensor.t', attributes: { unit_of_measurement: '°F' } }), true);
    assert.equal(f({ entity_id: 'weather.erlen', attributes: {} }), true);
    assert.equal(f({ entity_id: 'weather.forecast_home', attributes: {} }), false);
    assert.equal(f({ entity_id: 'sensor.power', attributes: { unit_of_measurement: 'W' } }), false);
});

// (#1137) The Wall Connector as the crawler reports it with no car
// integration (tests/integrations_rig/crawler/tesla_wall_connector.json).
const WALL_CONNECTOR = {
    platform: 'tesla_wall_connector',
    charger_roles: ['charging', 'plug', 'power', 'session_energy'],
    missing: ['control'],
    suggested_charger: {},
};

test('(#1137) a charger with roles and no control is found, not "no role matched"', () => {
    assert.equal(isWatchOnlyCharger(WALL_CONNECTOR), true);
    assert.equal(nearMissAction(WALL_CONNECTOR), 'watch');
    assert.equal(detectRowLabelKey(WALL_CONNECTOR), 'config_detect_watch_only');
    assert.equal(watchOnlyHelpKey(WALL_CONNECTOR), 'config_detect_watch_only_help');
});

test('(#1137) two cars with charge control are a choice, said as one', () => {
    const m = { ...WALL_CONNECTOR, choose_vehicle: ['car1', 'car2'] };
    assert.equal(nearMissAction(m), 'watch');
    assert.equal(watchOnlyHelpKey(m), 'config_detect_choose_vehicle_help');
});

test('(#1137) a device where no role matched still asks for a report', () => {
    // no roles at all
    assert.equal(nearMissAction({ missing: ['control'], suggested_charger: {} }), 'report');
    assert.equal(nearMissAction({ charger_roles: [], missing: ['control'] }), 'report');
    // a power reading missing too: not a charger SEM can describe
    assert.equal(nearMissAction({ charger_roles: ['plug'],
        missing: ['power reading', 'control'] }), 'report');
    assert.equal(nearMissAction({}), 'report');
    assert.equal(nearMissAction(null), 'report');
});

test('(#1137) the car-driven offer wins over watch-only', () => {
    const m = { ...WALL_CONNECTOR, missing: [],
        suggested_charger: { id: 'tesla_wall_connector_x' } };
    assert.equal(isWatchOnlyCharger(m), false);
    assert.equal(nearMissAction(m), 'add');
    assert.equal(detectRowLabelKey(m), 'config_detect_offer');
});

test('(#1137) the watch-only copy names the roles and never asks for a report', () => {
    const tr = JSON.parse(readFileSync(
        new URL('../../translations.json', import.meta.url), 'utf8'));
    for (const [lang, t] of Object.entries(tr)) {
        for (const k of ['config_detect_watch_only', 'config_detect_watch_only_help',
                         'config_detect_choose_vehicle_help']) {
            assert.ok(t[k], `${lang} lacks ${k}`);
        }
        assert.ok(t.config_detect_watch_only.includes('{roles}'), lang);
    }
    const en = tr.en.config_detect_watch_only + ' ' + tr.en.config_detect_watch_only_help;
    assert.ok(!/no role matched|please report|report this/i.test(en), en);
});

// (#1362) a select proposal writes the select and the option that means it
test('proposalWrite adds the option a select proposal carries', () => {
    const p = { config_key: 'battery_charge_select_entity',
                write_extra: { battery_charge_select_option: 'Solar and mains' } };
    assert.deepEqual(proposalWrite(p, 'select.charge_source', {}),
        { battery_charge_select_entity: 'select.charge_source',
          battery_charge_select_option: 'Solar and mains' });
});

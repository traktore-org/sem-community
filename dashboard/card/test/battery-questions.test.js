// (#1354) The house battery's settings as questions, and what it does now
// and next — one model for both dashboards.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { BATTERY_LEVELS, BATTERY_QUESTIONS, BATTERY_ZONES, batteryLevels, batterySays, zoneBands } from '../src/util/battery-questions.js';

const st = (v) => ({ state: String(v) });

test('the levels are read from the entities the old knobs wrote', () => {
    assert.deepEqual(BATTERY_LEVELS.map((l) => l.entity), [
        'number.sem_battery_priority_soc', 'number.sem_battery_buffer_soc', 'number.sem_battery_auto_start_soc']);
    const lv = batteryLevels({
        'number.sem_battery_priority_soc': st(30), 'number.sem_battery_buffer_soc': st(70),
        'number.sem_battery_auto_start_soc': st(90) });
    assert.deepEqual(lv, { priority: 30, buffer: 70, autostart: 90 });
    assert.deepEqual(batteryLevels({}), { priority: null, buffer: null, autostart: null });
});

test('the band under the priority level is where the battery fills first, not "Reserve"', () => {
    const b = zoneBands({ priority: 30, buffer: 70, autostart: 90 });
    assert.deepEqual(b.map((z) => [z.key, z.from, z.width]), [
        ['bq_zone_fill', 0, 30], ['bq_zone_sun', 30, 40], ['bq_zone_assist', 70, 20], ['bq_zone_full', 90, 10]]);
    assert.equal(zoneBands({ priority: 30, buffer: null, autostart: 90 }), null);
    assert.ok(!BATTERY_ZONES.some((z) => /reserve/.test(z.key)));
});

test('the other questions write the entities the old controls wrote', () => {
    assert.equal(BATTERY_QUESTIONS.solar_gate.entity, 'number.sem_battery_assist_min_surplus');
    assert.equal(BATTERY_QUESTIONS.assist_max.entity, 'number.sem_battery_assist_max_power');
    assert.equal(BATTERY_QUESTIONS.discharge_max.entity, 'number.sem_battery_max_discharge_power');
    assert.equal(BATTERY_QUESTIONS.may_export.entity, 'switch.sem_battery_may_export');
    assert.equal(BATTERY_QUESTIONS.may_assist.entity, 'switch.sem_battery_may_assist_ev');
    assert.equal(BATTERY_QUESTIONS.pacing.entity, 'switch.sem_battery_charge_pacing_enabled');
});

test('what it does now and next comes from what the engine publishes', () => {
    assert.deepEqual(batterySays({ powerW: 1200 }).now, { key: 'bq_says_charging', params: { kw: '1.2' } });
    assert.deepEqual(batterySays({ powerW: -750 }).now, { key: 'bq_says_giving', params: { kw: '0.8' } });
    assert.equal(batterySays({ powerW: 20 }).now.key, 'bq_says_resting');
    assert.equal(batterySays({ powerW: 'unavailable' }).now.key, 'bq_says_unknown');
    assert.deepEqual(batterySays({ powerW: 0, schedulerState: 'scheduled', schedulerTarget: 80 }).next,
        { key: 'bq_next_grid_charge', params: { target: 80 } });
    assert.equal(batterySays({ powerW: 0, schedulerState: 'charging', schedulerTarget: 80 }).next.key, 'bq_next_charging_to');
    assert.equal(batterySays({ powerW: 0, schedulerState: 'discharging_arbitrage' }).next.key, 'bq_next_selling');
    assert.deepEqual(batterySays({ powerW: 0, schedulerState: 'idle', floorPct: 90.5 }).next,
        { key: 'bq_next_keeps', params: { floor: 91 } });
    assert.equal(batterySays({ powerW: 0, schedulerState: 'idle' }).next, null);
});

test('the classic cards take the battery from the shared model', () => {
    const cards = new URL('../src/cards/', import.meta.url);
    const read = (f) => fs.readFileSync(new URL(f, cards), 'utf8');
    assert.ok(read('sem-config-card.js').includes('zoneBands(batteryLevels('));
    assert.ok(!read('sem-config-card.js').includes("'zone_legend_reserve'"));
    assert.ok(read('sem-battery-zones-card.js').includes("from '../util/battery-questions.js'"));
    assert.ok(read('sem-battery-card.js').includes('batterySaysFromStates(this._hass?.states)'));
});

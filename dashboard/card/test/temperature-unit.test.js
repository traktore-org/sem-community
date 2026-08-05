/**
 * Regression tests for #727 — inverter/battery temperature mislabelled °C.
 *
 * Reported setup: a US install (HA imperial units) with a temperature source.
 * SEM publishes sensor.sem_inverter_temperature as °C-native; HA converts it to
 * °F for display, so `.state` is already the °F number. The card then hardcoded
 * a "°C" suffix, turning a 118 °F reading into a nonsensical "118°C".
 *
 * The fix: label with the unit HA actually attached to the entity, falling back
 * to °C only when HA attached none.
 *
 * Run: `npm test` (from dashboard/card).
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { temperatureUnit, formatTemperatureLabel } from '../src/util/temperature.js';

test('#727: a °F entity is labelled °F, not °C', () => {
    const stateObj = { state: '118', attributes: { unit_of_measurement: '°F' } };
    assert.equal(temperatureUnit(stateObj), '°F');
    assert.equal(formatTemperatureLabel(stateObj.state, temperatureUnit(stateObj)), '118°F');
});

test('#727: a °C entity is labelled °C', () => {
    const stateObj = { state: '40', attributes: { unit_of_measurement: '°C' } };
    assert.equal(temperatureUnit(stateObj), '°C');
    assert.equal(formatTemperatureLabel(stateObj.state, temperatureUnit(stateObj)), '40°C');
});

test('#727: no unit attached falls back to °C', () => {
    assert.equal(temperatureUnit({ state: '25', attributes: {} }), '°C');
    assert.equal(temperatureUnit(null), '°C');
    assert.equal(temperatureUnit(undefined), '°C');
});

test('#727: the exact reported chimera is no longer producible', () => {
    // The bug: HA-converted °F value + hardcoded °C. With the unit read from the
    // entity, the same 118 value can only ever be labelled with its real unit.
    const stateObj = { state: '118.4', attributes: { unit_of_measurement: '°F' } };
    const label = formatTemperatureLabel(stateObj.state, temperatureUnit(stateObj));
    assert.equal(label, '118°F');
    assert.ok(!label.includes('°C'), 'a °F reading must never be labelled °C');
});

test('formatTemperatureLabel: blank when the value is not a number', () => {
    assert.equal(formatTemperatureLabel('', '°C'), '');
    assert.equal(formatTemperatureLabel(null, '°C'), '');
    assert.equal(formatTemperatureLabel(undefined, '°C'), '');
    assert.equal(formatTemperatureLabel('unavailable', '°C'), '');
});

test('formatTemperatureLabel: negative (cold-climate) readings still show', () => {
    assert.equal(formatTemperatureLabel('-5', '°C'), '-5°C');
});

test('formatTemperatureLabel: decimals and spacing options (battery tile)', () => {
    assert.equal(formatTemperatureLabel('24.53', '°F', { decimals: 1, space: true }), '24.5 °F');
});

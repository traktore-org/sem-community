/**
 * Regression tests for the load-device "Configure" modal (#219).
 *
 * The bug: the modal opened blank on reopen because it never carried the
 * saved mapping into the form — so users thought their mapping wasn't saved.
 * `buildLoadConfigModalHTML` MUST pre-fill the stored values; these tests pin
 * that, plus the control↔service-data mapping for all four control types.
 *
 * Run: `node --test` (from dashboard/card). No browser/jsdom needed.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
    controlToFormValues,
    formValuesToServiceData,
    buildLoadConfigModalHTML,
} from '../src/cards/load-config-modal.js';

const t = (k) => k; // identity translator — assert on raw keys

test('controlToFormValues: switch mapping round-trips entity + type', () => {
    const v = controlToFormValues({ type: 'switch', entity: 'switch.dryer' });
    assert.equal(v.type, 'switch');
    assert.equal(v.entity, 'switch.dryer');
});

test('controlToFormValues: service mapping keeps service/param/shed/restore', () => {
    const v = controlToFormValues({
        type: 'service', service: 'keba.set_current', param: 'current',
        shed_value: 6, restore_value: 16,
    });
    assert.equal(v.type, 'service');
    assert.equal(v.service, 'keba.set_current');
    assert.equal(v.param, 'current');
    assert.equal(v.shed_value, 6);
    assert.equal(v.restore_value, 16);
});

test('controlToFormValues: null/unknown defaults to switch with empty entity', () => {
    const v = controlToFormValues(null);
    assert.equal(v.type, 'switch');
    assert.equal(v.entity, '');
    assert.equal(v.param, 'current');
    assert.equal(v.restore_value, 16);
});

// ── The #219 regression: the form must be PRE-FILLED, not blank ──
test('buildLoadConfigModalHTML pre-fills the saved entity value', () => {
    const values = controlToFormValues({ type: 'switch', entity: 'switch.dryer' });
    const html = buildLoadConfigModalHTML({ deviceName: 'Dryer', values, t });
    // The entity input must carry the saved value (the exact bug that shipped).
    assert.match(html, /id="cfg-entity"[^>]*value="switch\.dryer"/);
    // ...and the matching control-type option must be selected.
    assert.match(html, /<option value="switch" selected>/);
});

test('buildLoadConfigModalHTML selects the saved control type (current)', () => {
    const values = controlToFormValues({ type: 'current', entity: 'number.keba' });
    const html = buildLoadConfigModalHTML({ deviceName: 'Charger', values, t });
    assert.match(html, /<option value="current" selected>/);
    assert.match(html, /id="cfg-entity"[^>]*value="number\.keba"/);
});

test('buildLoadConfigModalHTML shows service fields (pre-filled) for service type', () => {
    const values = controlToFormValues({
        type: 'service', service: 'keba.set_current', param: 'current',
        shed_value: 6, restore_value: 16,
    });
    const html = buildLoadConfigModalHTML({ deviceName: 'KEBA', values, t });
    assert.match(html, /<option value="service" selected>/);
    assert.match(html, /id="cfg-service"[^>]*value="keba\.set_current"/);
    assert.match(html, /id="cfg-service-group" style="display:block"/);
    assert.match(html, /id="cfg-entity-group" style="display:none"/);
});

test('buildLoadConfigModalHTML escapes the device name', () => {
    const values = controlToFormValues(null);
    const html = buildLoadConfigModalHTML({ deviceName: '<img src=x>', values, t });
    assert.doesNotMatch(html, /<img src=x>/);
    assert.match(html, /&lt;img src=x&gt;/);
});

// ── form → service-call data, per control type ──
test('formValuesToServiceData: switch/current/input_boolean send control_entity', () => {
    for (const type of ['switch', 'current', 'input_boolean']) {
        const data = formValuesToServiceData('sensor.e', { type, entity: 'switch.x' });
        assert.equal(data.control_type, type);
        assert.equal(data.control_entity, 'switch.x');
        assert.equal(data.energy_sensor, 'sensor.e');
    }
});

test('formValuesToServiceData: service sends service/param/shed/restore', () => {
    const data = formValuesToServiceData('sensor.e', {
        type: 'service', service: 'keba.set_current', param: 'current',
        shed_value: '6', restore_value: '16',
    });
    assert.equal(data.control_type, 'service');
    assert.equal(data.service, 'keba.set_current');
    assert.equal(data.shed_value, 6);
    assert.equal(data.restore_value, 16);
    assert.ok(!('control_entity' in data));
});

test('formValuesToServiceData: entity type without entity throws', () => {
    assert.throws(() => formValuesToServiceData('sensor.e', { type: 'switch', entity: '' }),
        /mapping_entity_required/);
});

test('formValuesToServiceData: service type without service throws', () => {
    assert.throws(() => formValuesToServiceData('sensor.e', { type: 'service', service: '' }),
        /mapping_service_required/);
});

// ── Remove-mapping button (#219 follow-up: clear a mapping) ──
test('buildLoadConfigModalHTML shows Remove button only for a manual mapping', () => {
    const values = controlToFormValues({ type: 'switch', entity: 'switch.x' });
    const withManual = buildLoadConfigModalHTML({ deviceName: 'D', values, t, hasManual: true });
    const noManual = buildLoadConfigModalHTML({ deviceName: 'D', values, t, hasManual: false });
    assert.match(withManual, /id="cfg-remove"/);
    assert.doesNotMatch(noManual, /id="cfg-remove"/);
});

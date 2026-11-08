/**
 * (#1321) The System card renders natively: the charger tools in place of
 * the old link, an entity value opens HA's picker, the setup and hardware
 * rows open in place, and nothing points at the classic dashboard.
 *
 * Run: `node --test test/next-system-card.test.js` (from dashboard/card).
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

await import('lit');
globalThis.window ??= globalThis;
globalThis.document = { addEventListener() {}, removeEventListener() {}, documentElement: {}, head: { appendChild() {} }, createElement: () => ({}) };
globalThis.addEventListener = () => {};
globalThis.removeEventListener = () => {};
globalThis.requestAnimationFrame = () => 0;
const registry = new Map();
globalThis.customElements = { get: (t) => registry.get(t), define: (t, c) => registry.set(t, c) };
globalThis.getComputedStyle = () => ({ getPropertyValue: () => '' });
globalThis.localStorage = { getItem: () => null, setItem() {} };
globalThis.navigator ??= {};
const TEXT = { next_reads_solar: 'solar from {solar}', next_reads_house: 'house {house}', next_entity_auto: '{name} (auto)' };
globalThis.semLocalize = (key) => TEXT[key] || key;
await import('../src/cards/sem-next-system-card.js');
const { groups, pendingKey, slotsOf } = await import('../src/util/next-settings.js');

function text(part) {
    if (part == null || typeof part === 'symbol' || part === false) return '';
    if (Array.isArray(part)) return part.map(text).join('');
    if (part && part.strings && part.values) {
        let out = '';
        part.strings.forEach((s, i) => { out += s; if (i < part.values.length) out += text(part.values[i]); });
        return out;
    }
    if (typeof part === 'function') return '';
    return String(part);
}
const S = (state, attributes = {}) => ({ state: String(state), attributes, last_updated: '2026-11-08T18:40:00+00:00' });

function makeCard(calls) {
    const el = new (customElements.get('sem-next-system-card'))();
    el.setConfig({ type: 'custom:sem-next-system-card' });
    el._optionsAsked = true;
    el.hass = {
        states: {
            'switch.sem_observer_mode': S('off'),
            'sensor.sem_charging_state': S('idle'),
            'sensor.sem_diag_version': S('2.3.0'),
            'sensor.sem_diag_ed_config': S('ok', { energy_dashboard: { solar: { power: 'sensor.pv' }, grid: { power: 'sensor.meter' } } }),
            'sensor.pv': S(0, { friendly_name: 'Inverter input' }),
        },
        language: 'en', config: { currency: 'CHF', version: '2026.11.0', time_zone: 'Europe/Zurich' }, services: {},
        callService: async (d, s, data) => { calls.push([d, s, data]); return {}; },
        callWS: async () => ({}),
    };
    el._options = { tariff_mode: 'static', ev_chargers: [{ id: 'keba', name: 'Keba' }] };
    el._entryId = 'E1';
    return el;
}

test('renders the charger tools and the HA settings link, no classic link', () => {
    const el = makeCard([]);
    const out = text(el.render());
    assert.match(out, /config_ev_add_charger/);
    assert.match(out, /config_ev_remove Keba/);
    assert.match(out, /config_open_ha_settings/);
    assert.doesNotMatch(out, /next_ch_add/);
    assert.doesNotMatch(out, /sem-dashboard/);
    assert.match(out, /Inverter input/, 'the auto-found solar source is named');
});

test('an entity value opens HA\'s picker (or a text box when HA has not loaded it)', () => {
    const el = makeCard([]);
    const g = groups(el.hass.states, (k) => TEXT[k] || k, el._ctx());
    const solar = slotsOf(g).find((s) => s.option === 'solar_production_sensor');
    el._editing = pendingKey(solar);
    let out = text(el.render());
    assert.match(out, /placeholder="sensor/, 'text fallback without ha-entity-picker');
    customElements.define('ha-entity-picker', class {});
    out = text(el.render());
    assert.match(out, /<ha-entity-picker/);
});

test('add charger sends one skeleton through set_option; remove needs a confirm', async () => {
    const calls = [];
    const el = makeCard(calls);
    await el._addCharger();
    const add = calls.find((c) => c[1] === 'set_option');
    assert.deepEqual(add[2].options.ev_chargers.map((c) => c.id), ['ev_charger']);
    assert.equal(add[2].entry_id, 'E1');
    el._confirmRemove = 'keba';
    assert.match(text(el.render()), /config_ev_remove_confirm/);
    await el._removeCharger('keba');
    assert.deepEqual(calls.find((c) => c[1] === 'remove_charger')[2], { charger_id: 'keba' });
});

test('the setup and hardware rows open their panel in place', () => {
    const el = makeCard([]);
    el._togglePanel('setup');
    assert.equal(el._panel, 'setup');
    el._togglePanel('setup');
    assert.equal(el._panel, '');
    el._togglePanel('hardware');
    const flat = (tpl) => tpl.strings.join('|') + '|' + tpl.values.filter((v) => typeof v === 'string').join('|');
    assert.match(flat(el._setupPanel('hardware')), /sem-next-setup-panel/);
    assert.ok(el._setupPanel('setup').values.includes('check'));
    assert.ok(el._setupPanel('hardware').values.includes('hardware'));
});

test('observer mode: adding and removing chargers sends nothing', async () => {
    const calls = [];
    const el = makeCard(calls);
    el.hass.states['switch.sem_observer_mode'] = S('on');
    await el._addCharger();
    await el._removeCharger('keba');
    assert.equal(calls.length, 0);
});

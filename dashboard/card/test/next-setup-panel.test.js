/**
 * (#1321) The Setup check and the Detected-hardware review in SEM Next:
 * the row model, and the writes a click sends (same as the classic card).
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';

const FAKE_LIT = `
export class LitElement {
    constructor() { this.style = {}; this.classList = { toggle() {} }; this.renderRoot = { querySelector: () => null, querySelectorAll: () => [] }; }
    connectedCallback() {}
    disconnectedCallback() {}
    requestUpdate() { this.__updates = (this.__updates || 0) + 1; }
    updated() {}
    dispatchEvent(e) { (this.__events = this.__events || []).push(e); return true; }
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
globalThis.CustomEvent = class { constructor(type, init = {}) { this.type = type; this.detail = init.detail; } };
globalThis.semLocalize = (key) => '«' + key + '»';
Object.defineProperty(globalThis, 'navigator', { value: { clipboard: { writeText: async () => {} } }, configurable: true });

const {
    checkModel, hardwareModel, proposalModel, whyNoButton, reportNearMissUrl, knownChargerIds,
} = await import('../src/cards/sem-next-setup-panel.js');

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
const S = (state, attributes = {}) => ({ state: String(state), attributes, last_updated: '2026-11-08T19:40:00+01:00' });

const REPORT = {
    chargers: [{ platform: 'keba', name: 'KEBA P30', control: 'number entity', configured: true,
        mapped: { power: { entity: 'sensor.keba_power', domain: 'sensor', device_class: 'power' } },
        unmapped: [{ entity: 'sensor.keba_rfid' }] }],
    near_misses: [
        { platform: 'easee', roster: { name: 'Easee', installs: 900 }, charger_roles: ['power'],
          entities: [{ entity: 'sensor.easee_power', domain: 'sensor', device_class: 'power' }],
          suggested_charger: { id: 'easee_1', name: 'Easee', ev_charging_power_sensor: 'sensor.easee_power' },
          proposed_roles: {
              grid_power_sensor: { action: 'set_option', config_key: 'grid_power_sensor', entity: 'sensor.p1', matched_key: 'grid',
                  alternatives: [{ entity: 'sensor.p1_b', matched_key: 'grid_b' }, { entity: 'sensor.p1_c', action: 'not_loaded' }] },
              ev_current: { action: 'per_charger', entity: 'number.easee_current', matched_key: 'current' },
          } },
        { platform: 'mystery', entities: [{ entity: 'sensor.x', domain: 'sensor' }], charger_roles: [] },
    ],
    roster_proposals: [{ domain: 'p1_monitor', roster: { name: 'P1 Monitor' },
        proposed_roles: { solar_production_sensor: { action: 'unit_mismatch', unit_seen: 'kWh', unit_wanted: 'W', entity: 'sensor.p1_solar', matched_key: 'solar' } } }],
    census: { unknown_energy_domains: ['eg4'], unknown_energy_domains_named: [{ domain: 'eg4', name: 'EG4 Web Monitor', installs: 412 }], rows_matched_nothing: ['sensor.row'] },
    disagreements: [{ kind: 'prober_only', platform: 'ocpp' }],
};

test('check model: progress counts only required items, reads what SEM reads', () => {
    const states = {
        'sensor.sem_charging_state': S('idle'),
        'number.sem_charger_keba_minimum_current': S(6),
        'sensor.sem_solar_power': S(1200),
        'sensor.sem_grid_import_power': S(0), 'sensor.sem_grid_export_power': S(500),
        'sensor.sem_battery_charge_power': S(300), 'sensor.sem_battery_discharge_power': S(0),
        'sensor.sem_home_consumption_power': S(400),
    };
    const m = checkModel(states, { tariff_mode: 'static', electricity_import_rate: 0.3 });
    assert.equal(m.total, 6);
    assert.equal(m.items.find((i) => i.key === 'loads').optional, true);
    assert.ok(m.items.find((i) => i.key === 'ev').done);
    assert.ok(m.items.find((i) => i.key === 'tariff').done);
    assert.equal(m.hasBattery, true);
    assert.equal(m.sources.find((r) => r.key === 'grid').dir, 'sending');
    assert.equal(m.pct, Math.round(m.done / 6 * 100));
});

test('proposal model: a click saves what proposalWrite says, a saved one offers no button', () => {
    const p = REPORT.near_misses[0].proposed_roles.grid_power_sensor;
    const fresh = proposalModel('grid_power_sensor', p, {});
    assert.deepEqual(fresh.write, { grid_power_sensor: 'sensor.p1' });
    assert.equal(fresh.saved, false);
    assert.deepEqual(fresh.alts[0].write, { grid_power_sensor: 'sensor.p1_b' });
    assert.deepEqual(fresh.alts[1].why, { key: 'config_proposed_not_loaded' });
    const saved = proposalModel('grid_power_sensor', p, { grid_power_sensor: 'sensor.p1' });
    assert.equal(saved.write, null);
    assert.equal(saved.saved, true);
    const perCharger = proposalModel('ev_current', REPORT.near_misses[0].proposed_roles.ev_current, {});
    assert.equal(perCharger.write, null);
    assert.deepEqual(perCharger.why, { key: 'config_proposed_per_charger' });
});

test('why no button: every refusal names its reason', () => {
    assert.deepEqual(whyNoButton({ action: 'unit_mismatch', unit_seen: 'kWh', unit_wanted: 'W' }),
        { key: 'config_proposed_unit_mismatch', vars: { seen: 'kWh', wanted: 'W' } });
    assert.deepEqual(whyNoButton({ action: 'needs_hand_wiring', reason: 'service only' }), { text: 'service only' });
    assert.equal(whyNoButton({ action: 'set_option' }), null);
});

test('hardware model: chargers, near misses with add/report, roster, census, prober', () => {
    const m = hardwareModel(REPORT, { ev_chargers: [{ id: 'keba' }] }, ['keba']);
    assert.equal(m.chargers[0].configured, true);
    assert.deepEqual(m.chargers[0].unmapped, ['sensor.keba_rfid']);
    assert.equal(m.misses[0].action, 'add');
    assert.equal(m.misses[0].plan.action, 'add');
    assert.equal(m.misses[0].plan.charger.id, 'easee_1');
    assert.equal(m.misses[0].plan.charger.ev_surplus_priority, 4);
    assert.equal(m.misses[1].action, 'report');
    assert.match(m.misses[1].reportUrl, /issues\/new\?labels=enhancement/);
    assert.deepEqual(m.unknown, [{ name: 'EG4 Web Monitor', installs: 412 }]);
    assert.deepEqual(m.roster[0].proposals[0].why.key, 'config_proposed_unit_mismatch');
    assert.deepEqual(m.proberOnly, ['ocpp']);
    assert.equal(m.empty, false);
    assert.equal(hardwareModel(null, {}, []), null);
});

test('a charger that exists is not added twice', () => {
    const m = hardwareModel(REPORT, { ev_chargers: [{ id: 'easee_1' }] }, ['easee_1']);
    assert.equal(m.misses[0].plan.action, 'exists');
});

test('known charger ids: options and runtime entities, once each', () => {
    const ids = knownChargerIds({ 'number.sem_charger_keba_minimum_current': S(6), 'number.sem_charger_ev_1_minimum_current': S(6) },
        { ev_chargers: [{ id: 'keba' }, { id: 'new_one' }] });
    assert.deepEqual(ids.sort(), ['ev_1', 'keba', 'new_one']);
});

test('report url carries the platform and the entities', () => {
    const url = reportNearMissUrl(REPORT.near_misses[1]);
    assert.match(decodeURIComponent(url), /mystery/);
    assert.match(decodeURIComponent(url), /sensor\.x/);
    assert.equal(reportNearMissUrl(REPORT.near_misses[0]), '');
});

// ── the element: what a click sends ──

function makePanel(kind, extraStates = {}, options = { ev_chargers: [{ id: 'keba' }] }) {
    const calls = [];
    const el = new (customElements.get('sem-next-setup-panel'))();
    el.kind = kind;
    el.hass = {
        states: {
            'switch.sem_observer_mode': S('off'),
            'sensor.sem_diag_charger_control': S('number entity', { detection_report: REPORT }),
            'sensor.sem_charging_state': S('idle'),
            'number.sem_charger_keba_minimum_current': S(6),
            'sensor.sem_solar_power': S(0), 'sensor.sem_home_consumption_power': S(500),
            ...extraStates,
        },
        language: 'en', config: { time_zone: 'Europe/Zurich' },
        callService: async (domain, service, data, target, notify, ret) => {
            calls.push({ domain, service, data, notify, ret });
            if (service === 'get_config') return { response: { config: options, entry_id: 'E1' } };
            if (service.startsWith('flip_')) return { response: { user_flip: true } };
            return {};
        },
        callWS: async () => ({}),
    };
    return { el, calls };
}

test('panel reads the options once with get_config', async () => {
    const { el, calls } = makePanel('check');
    await new Promise((r) => setTimeout(r, 0));
    assert.equal(calls[0].service, 'get_config');
    assert.equal(calls[0].ret, true);
    assert.equal(el._entryId, 'E1');
});

test('check render: progress, the reads, both flips, no backtick or raw key leak', async () => {
    const { el } = makePanel('check', { 'sensor.sem_battery_charge_power': S(0), 'sensor.sem_battery_discharge_power': S(900) });
    await new Promise((r) => setTimeout(r, 0));
    const out = text(el.render());
    assert.match(out, /config_setup_progress|config_setup_done/);
    assert.match(out, /config_check_grid_wrong/);
    assert.match(out, /config_check_battery_wrong/);
    assert.match(out, /config_check_giving/);
    assert.doesNotMatch(out, /undefined|NaN/);
});

test('"Use this" saves the proposal with set_option and the entry id', async () => {
    const { el, calls } = makePanel('hardware');
    await new Promise((r) => setTimeout(r, 0));
    await el._save({ grid_power_sensor: 'sensor.p1' }, 'prop_0_grid');
    const set = calls.find((c) => c.service === 'set_option');
    assert.deepEqual(set.data, { options: { grid_power_sensor: 'sensor.p1' }, entry_id: 'E1' });
    assert.equal(set.notify, false);
    assert.equal(el._status.prop_0_grid, 'ok');
});

test('"Add this charger" sends only the new skeleton; an existing one sends nothing', async () => {
    const { el, calls } = makePanel('hardware');
    await new Promise((r) => setTimeout(r, 0));
    await el._addCharger(REPORT.near_misses[0].suggested_charger);
    const set = calls.filter((c) => c.service === 'set_option');
    assert.equal(set.length, 1);
    assert.equal(set[0].data.options.ev_chargers.length, 1);
    assert.equal(set[0].data.options.ev_chargers[0].id, 'easee_1');
    await el._addCharger({ id: 'keba' });
    assert.equal(calls.filter((c) => c.service === 'set_option').length, 1);
});

test('a refused save shows the error in the panel', async () => {
    const { el } = makePanel('hardware');
    await new Promise((r) => setTimeout(r, 0));
    el.hass.callService = async () => { throw new Error('nope'); };
    await el._save({ grid_power_sensor: 'sensor.p1' }, 'f');
    assert.equal(el._err, 'nope');
    assert.match(text(el.render()), /nope/);
});

test('flip asks for the response and reports it; observer mode sends nothing', async () => {
    const { el, calls } = makePanel('check');
    await new Promise((r) => setTimeout(r, 0));
    await el._flip('grid');
    const f = calls.find((c) => c.service === 'flip_grid_sign');
    assert.equal(f.ret, true);
    assert.equal(el._msg, '«sign_flipped_copied»');
    const obs = makePanel('check', { 'switch.sem_observer_mode': S('on') });
    await new Promise((r) => setTimeout(r, 0));
    await obs.el._flip('battery');
    assert.equal(obs.calls.filter((c) => c.service.startsWith('flip_')).length, 0);
});

test('hardware render: add button, report link, proposals, census and close event', async () => {
    const { el } = makePanel('hardware');
    await new Promise((r) => setTimeout(r, 0));
    const out = text(el.render());
    for (const k of ['config_near_miss_add', 'config_near_miss_report', 'config_proposed_roles', 'config_proposed_use',
        'config_census_unknown', 'EG4 Web Monitor', 'config_detect_prober_only', 'config_detect_configured', 'next_panel_close']) {
        assert.match(out, new RegExp(k), k);
    }
    assert.doesNotMatch(out, /undefined|NaN/);
    el._close('ev');
    assert.equal(el.__events[0].type, 'sem-next-close');
    assert.deepEqual(el.__events[0].detail, { goto: 'ev' });
});

test('no detection report yet: says so', async () => {
    const { el } = makePanel('hardware', { 'sensor.sem_diag_charger_control': S('unknown', {}) });
    await new Promise((r) => setTimeout(r, 0));
    assert.match(text(el.render()), /config_detect_none/);
});

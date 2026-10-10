/**
 * #1089 — two batteries, one discharge-limit field.
 *
 * SEM limits each battery through its own slot of
 * `battery_discharge_control_entities`, but the Config tab only offered the
 * one shared entity. Two Sessys, one picked: the second kept discharging
 * into the car. Each battery now gets its own row under the shared one.
 *
 * The real card code runs here; lit is replaced by a stub (CI runs
 * `node --test` with no node_modules).
 *
 * Run: `npm test` (from dashboard/card).
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';

const FAKE_LIT = `
export class LitElement {
    constructor() { this.style = {}; this.renderRoot = { querySelector: () => null, querySelectorAll: () => [] }; }
    connectedCallback() {}
    disconnectedCallback() {}
    requestUpdate() {}
    updated() {}
    get updateComplete() { return Promise.resolve(true); }
}
const tag = () => '';
export const html = tag, css = tag, svg = tag;
export const nothing = Symbol('nothing');
export const unsafeSVG = (s) => s;
`;
const LOADER = `
const FAKE = ${JSON.stringify('data:text/javascript,' + encodeURIComponent(FAKE_LIT))};
export async function resolve(specifier, context, next) {
    if (specifier === 'lit' || specifier.startsWith('lit/')) return { url: FAKE, shortCircuit: true };
    return next(specifier, context);
}`;
register('data:text/javascript,' + encodeURIComponent(LOADER));

globalThis.window = globalThis;
globalThis.document = {
    addEventListener() {}, removeEventListener() {},
    documentElement: {}, head: { appendChild() {} }, createElement: () => ({}),
};
globalThis.addEventListener = () => {};
globalThis.removeEventListener = () => {};
const registry = new Map();
globalThis.customElements = { get: (t) => registry.get(t), define: (t, c) => registry.set(t, c) };
globalThis.getComputedStyle = () => ({ getPropertyValue: () => '' });
globalThis.localStorage = { getItem: () => null, setItem() {} };
globalThis.navigator ??= {};

await import('../src/cards/sem-config-card.js');

const LIST = 'battery_discharge_control_entities';
const T = new Proxy({}, { get: () => '' });

function card(options, { batteries = 2, advanced = true } = {}) {
    const el = new (customElements.get('sem-config-card'))();
    el.setConfig({});
    el._advanced = advanced;
    el._options = { ...options };
    el._entryId = 'entry1';
    el.calls = [];
    const states = {};
    for (let i = 1; i <= batteries; i++) states[`sensor.sem_battery_b${i}_power`] = { state: '0' };
    el._hass = {
        states, config: { currency: 'EUR' }, language: 'en',
        callService: async (domain, service, data) => { el.calls.push({ domain, service, data }); },
        callWS: async () => [],
    };
    // Record the per-battery rows the section asks for.
    el.rows = [];
    const real = el._renderBatteryListPicker.bind(el);
    el._renderBatteryListPicker = (listKey, labelKey, domains, idx, count, opts, helpKey) => {
        el.rows.push({ listKey, idx, count, domains, helpKey });
        return real(listKey, labelKey, domains, idx, count, opts, helpKey);
    };
    return el;
}

const limitRows = (el) => el.rows.filter((r) => r.listKey === LIST);

test('two batteries: one discharge-limit row each, under the shared one', () => {
    const el = card({});
    el._renderBatteryZones(T);
    assert.deepEqual(limitRows(el).map((r) => [r.idx, r.count]), [[0, 2], [1, 2]]);
    assert.deepEqual(limitRows(el)[0].domains, ['number']);
    assert.equal(limitRows(el)[0].helpKey, 'config_help_batt_discharge_entity_each');
});

test('three batteries: three rows', () => {
    const el = card({}, { batteries: 3 });
    el._renderBatteryZones(T);
    assert.equal(limitRows(el).length, 3);
});

test('one battery: the shared field only', () => {
    for (const batteries of [0, 1]) {
        const el = card({}, { batteries });
        el._renderBatteryZones(T);
        assert.equal(limitRows(el).length, 0, `${batteries} batteries`);
    }
});

test('the rows show where the shared field shows (Advanced)', () => {
    const el = card({}, { advanced: false });
    assert.equal(el._showsControl('battery_discharge_control_entity'), false);
    el._renderBatteryZones(T);
    assert.equal(limitRows(el).length, 0);
});

test("picking B2's entity writes slot 2 and keeps slot 1", async () => {
    const el = card({ [LIST]: ['number.sessy_a_maximum_power'] });
    await el._saveListField(LIST, 1, 'number.sessy_b_maximum_power', 2);
    const sets = el.calls.filter((c) => c.service === 'set_option');
    assert.equal(sets.length, 1);
    assert.deepEqual(sets[0].data.options, {
        [LIST]: ['number.sessy_a_maximum_power', 'number.sessy_b_maximum_power'],
    });
    assert.deepEqual(el._options[LIST],
        ['number.sessy_a_maximum_power', 'number.sessy_b_maximum_power']);
});

test("emptying B1 leaves B2's entity alone", async () => {
    const el = card({ [LIST]: ['number.a', 'number.b'] });
    await el._saveListField(LIST, 0, '', 2);
    assert.deepEqual(el.calls[0].data.options, { [LIST]: [null, 'number.b'] });
});

test('the battery-control rows still ask for their own lists', () => {
    const el = card({});
    el._renderTariff(T);
    const keys = new Set(el.rows.map((r) => r.listKey));
    assert.ok(keys.has('battery_force_discharge_entities'));
    assert.ok(keys.has('battery_strategy_entities'));
    assert.ok(!keys.has(LIST), 'the limit rows belong to the battery section');
});

/**
 * #1362 — grid-charge fields. The select pair showed for one battery only,
 * so a two-battery home could not set it in the Configuration tab. It now
 * shows for any count. The charge switch and target stay with one battery:
 * a stop by one pack would put them back while another still charges.
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


const T_ = new Proxy({}, { get: () => '' });

function card(options, batteries) {
    const el = new (customElements.get('sem-config-card'))();
    el.setConfig({});
    el._advanced = true;
    el._options = { ...options };
    el._entryId = 'entry1';
    const states = {};
    for (let i = 1; i <= batteries; i++) states[`sensor.sem_battery_b${i}_power`] = { state: '0' };
    el._hass = { states, config: { currency: 'EUR' }, language: 'en',
                 callService: async () => ({}), callWS: async () => [] };
    el.pickers = [];
    const real = el._renderPicker.bind(el);
    el._renderPicker = (key, ...rest) => { el.pickers.push(key); return real(key, ...rest); };
    const opt = el._renderSelectOptionPicker.bind(el);
    el._renderSelectOptionPicker = (key, ...rest) => { el.pickers.push(key); return opt(key, ...rest); };
    return el;
}

const CHARGE = ['battery_charge_select_entity', 'battery_charge_select_option'];
const EXTRA = ['battery_force_charge_switch', 'battery_target_soc_entity'];

test('two batteries: the select pair shows, the switch and target do not', () => {
    const el = card({}, 2);
    el._renderBatteryChargeFields({}, 2);
    assert.deepEqual(el.pickers, CHARGE);
});

test('one battery: the select pair, the switch and the target show', () => {
    const el = card({}, 1);
    el._renderBatteryChargeFields({}, 1);
    assert.deepEqual(el.pickers, [...CHARGE, ...EXTRA]);
});

test('the Battery control section hands both counts to the fields', () => {
    for (const [n, want] of [[2, CHARGE], [1, [...CHARGE, ...EXTRA]]]) {
        const el = card({}, n);
        el._renderTariff(T_);
        const got = el.pickers.filter((k) => [...CHARGE, ...EXTRA].includes(k));
        assert.deepEqual(got, want, `${n} batteries`);
    }
});

// (#1362) the hold select: the same shared setting for any battery count
const HOLD = ['battery_hold_select_entity', 'battery_hold_select_option'];

test('the hold select pair shows for one battery and for two', () => {
    for (const n of [1, 2]) {
        const el = card({}, n);
        el._renderBatteryHoldFields({});
        assert.deepEqual(el.pickers, HOLD, `${n} batteries`);
    }
});

test('the Battery control section renders the hold fields for both counts', () => {
    for (const n of [1, 2]) {
        const el = card({}, n);
        el._renderTariff(T_);
        assert.deepEqual(el.pickers.filter((k) => HOLD.includes(k)), HOLD, `${n} batteries`);
    }
});

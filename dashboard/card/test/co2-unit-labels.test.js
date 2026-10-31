/**
 * #1242 — three cards printed "kg" after a CO2 figure whatever unit the
 * sensor shows in. A sensor set to lb or g is served in that unit by HA,
 * so the number was right and the label wrong. Each card now reads the
 * unit from the sensor, and falls back to kg when it has none.
 *
 * Run: `npm test` (from dashboard/card).
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';
import { readFileSync } from 'node:fs';

const FAKE_LIT = `
export class LitElement {
    constructor() { this.style = {}; this.renderRoot = { querySelector: () => null, querySelectorAll: () => [] }; }
    connectedCallback() {}
    disconnectedCallback() {}
    requestUpdate() { this.__updates = (this.__updates || 0) + 1; }
    updated() {}
    getRootNode() { return {}; }
    get updateComplete() { return Promise.resolve(true); }
}
export const html = (strings, ...values) => ({ tpl: true, strings: [...strings], values });
export const css = () => '', svg = html;
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
globalThis.requestAnimationFrame = () => 0;
const registry = new Map();
globalThis.customElements = { get: (t) => registry.get(t), define: (t, c) => registry.set(t, c) };
globalThis.getComputedStyle = () => ({ getPropertyValue: () => '' });
globalThis.localStorage = { getItem: () => null, setItem() {} };
globalThis.navigator ??= {};

await import('../src/cards/sem-home-status-card.js');
await import('../src/cards/sem-costs-card.js');
await import('../src/cards/sem-tab-header.js');

function text(part) {
    if (part == null || typeof part === 'symbol' || part === false) return '';
    if (Array.isArray(part)) return part.map(text).join('');
    if (part && part.tpl) {
        let out = '';
        part.strings.forEach((s, i) => {
            out += s;
            if (i < part.values.length) out += text(part.values[i]);
        });
        return out;
    }
    return String(part);
}

const S = (state, unit) => ({ state: String(state), attributes: unit ? { unit_of_measurement: unit } : {} });

function states(unit) {
    return {
        'sensor.sem_daily_co2_avoided': S(2.27, unit),
        'sensor.sem_yearly_co2_avoided': S(412, unit),
        'sensor.sem_lifetime_co2_avoided': S(1880, unit),
    };
}

function card(tag, st, config = {}) {
    const el = new (customElements.get(tag))();
    el.setConfig({ type: `custom:${tag}`, ...config });
    el.hass = { states: st, language: 'en' };
    return el;
}

// [card, how it prints today's figure]
for (const [tag, today] of [['sem-home-status-card', '2.27'], ['sem-costs-card', '2.3']]) {
    test(`${tag} prints the unit the sensor shows in`, () => {
        const out = text(card(tag, states('lb')).render());
        assert.ok(out.includes(`${today} lb`), out);
        assert.doesNotMatch(out, /\d kg/);
    });
    test(`${tag} falls back to kg when the sensor has no unit`, () => {
        const out = text(card(tag, states(undefined)).render());
        assert.ok(out.includes(`${today} kg`), out);
    });
}

test('the tab header prints the unit on the system tab', () => {
    const el = card('sem-tab-header', states('g'), { tab: 'system' });
    const out = el._getStatValues ? el._getStatValues() : null;
    assert.ok(out, 'stat values method');
    assert.ok(out.some((v) => /1880 g$/.test(v)), JSON.stringify(out));
});

test('the tab header falls back to kg', () => {
    const el = card('sem-tab-header', states(undefined), { tab: 'system' });
    assert.ok(el._getStatValues().some((v) => /1880 kg$/.test(v)));
});

/**
 * #1264 — "Buffer", "% self" and "% solar" were written into three cards in
 * English. They now come from the translation files, in all 16 languages.
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


await import('../src/cards/sem-battery-zones-card.js');
await import('../src/cards/sem-flow-card.js');
await import('../src/cards/sem-costs-detail-card.js');

const TABLES = JSON.parse(readFileSync(new URL('../../translations.json', import.meta.url), 'utf8'));
const LANGS = Object.keys(TABLES);
const KEYS = ['buffer_word', 'self_word', 'solar_word'];

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

const S = (state) => ({ state: String(state), attributes: {} });

function card(tag, st, lang, config = {}) {
    globalThis.semLocalize = (key, l) => (TABLES[l] || {})[key] ?? key;
    const el = new (customElements.get(tag))();
    el.setConfig({ type: `custom:${tag}`, ...config });
    el.hass = { states: st, language: lang };
    return el;
}

test('every language has the three words', () => {
    assert.equal(LANGS.length, 16);
    for (const l of LANGS) for (const k of KEYS) assert.ok(TABLES[l][k], `${l} ${k}`);
});

test('the zones card asks its levels in German, not English', () => {
    // (#1354) the levels are questions now; the German card must not fall
    // back to the English words (it said "Buffer" once).
    const st = {
        'number.sem_battery_auto_start_soc': S(30),
        'number.sem_battery_buffer_soc': S(20),
        'number.sem_battery_priority_soc': S(10),
    };
    const out = text(card('sem-battery-zones-card', st, 'de').render());
    assert.match(out, /Ab hier darf die Batterie dem Auto helfen/, out);
    assert.match(out, /Batterie lädt zuerst/, out);
    assert.doesNotMatch(out, /From this the battery may help the car|Buffer/);
});

test('the EV costs line says zon in Dutch, not solar', () => {
    const st = {
        'sensor.sem_lifetime_ev_energy': S(100),
        'sensor.sem_lifetime_ev_cost': S(10),
        'sensor.sem_lifetime_ev_solar_share': S(60),
    };
    const el = card('sem-costs-detail-card', st, 'nl');
    assert.match(el._sectionSubtitle('ev_econ', 'CHF'), /60% zon$/);
});

test('the Home label under the flow says eigen in German', () => {
    const st = { 'sensor.sem_autarky_rate': S(75) };
    const el = card('sem-flow-card', st, 'de', { entity_prefix: 'sensor.sem_' });
    const shown = {};
    el.renderRoot.getElementById = () => null;
    el._setText = () => {};
    el._animateValue = (id, v, ms, fmt) => { if (typeof fmt === 'function') shown[id] = fmt(v); };
    try { el._updateFlowsImperative(); } catch (e) { shown.err = String(e.stack); }
    assert.ok(shown['val-autarky'], 'autarky label was set: ' + shown.err);
    assert.match(shown['val-autarky'], /75% eigen$/);
});

/**
 * (#1321) Every removed classic card tag is defined by the retired-card stub,
 * so a card placed by hand on another dashboard shows one short line with a
 * link to the SEM dashboard instead of a red error card.
 *
 * Run: `node --test test/retired-card.test.js` (from dashboard/card).
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';
import { readdirSync, readFileSync } from 'node:fs';

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
globalThis.getComputedStyle = () => ({ getPropertyValue: () => '' });
const registry = new Map();
globalThis.customElements = { get: (t) => registry.get(t), define: (t, c) => registry.set(t, c) };
globalThis.semLocalize = (key) => key;

const { RETIRED_TAGS } = await import('../src/cards/sem-retired-card.js');

const text = (p) => {
    if (p == null || typeof p === 'symbol' || p === false) return '';
    if (Array.isArray(p)) return p.map(text).join('');
    if (typeof p === 'object' && p.tpl) {
        let out = '';
        p.strings.forEach((s, i) => { out += s; if (i < p.values.length) out += text(p.values[i]); });
        return out;
    }
    return String(p);
};

test('every retired tag is defined, none of them a live card', () => {
    assert.ok(RETIRED_TAGS.length > 30);
    for (const tag of RETIRED_TAGS) assert.ok(customElements.get(tag), tag);
    const live = readdirSync(new URL('../src/cards/', import.meta.url)).map((f) => f.replace(/\.js$/, ''));
    for (const tag of RETIRED_TAGS) assert.ok(!live.includes(tag), `${tag} still has a card file`);
});

test('every classic tag the old template used is covered', () => {
    for (const tag of ['sem-flow-card', 'sem-config-card', 'sem-system-diagram-card', 'sem-require', 'sem-next-link-card']) {
        assert.ok(RETIRED_TAGS.includes(tag), tag);
    }
});

test('the stub says it is retired and links to the live dashboard, whatever its URL', async () => {
    const el = new (customElements.get('sem-solar-card'))();
    el.setConfig({ type: 'custom:sem-solar-card' });
    el._scheduleUpdate = () => {};
    el.hass = { states: {}, language: 'en', callWS: async () => [{ url_path: 'sem-dashboard' }, { url_path: 'other' }] };
    await new Promise((r) => setTimeout(r, 0));
    const out = text(el.render());
    assert.match(out, /retired_card/);
    assert.match(out, /href="\/sem-dashboard"|\/sem-dashboard/);
});

test('with no SEM dashboard listed there is no link, only the line', async () => {
    const el = new (customElements.get('sem-gauge-card'))();
    el.setConfig({ type: 'custom:sem-gauge-card' });
    el._scheduleUpdate = () => {};
    el.hass = { states: {}, language: 'en', callWS: async () => { throw new Error('no'); } };
    await new Promise((r) => setTimeout(r, 0));
    assert.doesNotMatch(text(el.render()), /retired_card_open/);
});

test('the bundle imports the stub, and the card files are gone', () => {
    const bundle = readFileSync(new URL('../src/sem-cards.js', import.meta.url), 'utf8');
    assert.match(bundle, /sem-retired-card\.js/);
});

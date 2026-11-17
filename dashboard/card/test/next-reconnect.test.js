/**
 * (#1058, #1321) Home Assistant takes a card off the page when you leave a
 * screen and puts the same object back. The Plan screen's timers stop on
 * leaving and start again on return, one set only.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';

const FAKE_LIT = `
export class LitElement { constructor() { this.style = {}; this.classList = { toggle() {} }; this.renderRoot = { querySelector: () => null, querySelectorAll: () => [], getElementById: () => null, appendChild() {} }; }
    connectedCallback() {} disconnectedCallback() {} requestUpdate() {} updated() {} getRootNode() { return {}; } get updateComplete() { return Promise.resolve(true); } }
export const html = (strings, ...values) => ({ tpl: true, strings: [...strings], values });
export const css = () => '', svg = html;
export const nothing = Symbol('nothing');
export const repeat = (items, key, fn) => Array.from(items).map((it, i) => fn(it, i));
`;
register('data:text/javascript,' + encodeURIComponent(`
const FAKE = ${JSON.stringify('data:text/javascript,' + encodeURIComponent(FAKE_LIT))};
export async function resolve(s, c, n) { if (s === 'lit' || s.startsWith('lit/')) return { url: FAKE, shortCircuit: true }; return n(s, c); }`));
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
globalThis.semLocalize = (key) => key;
await import('../src/cards/sem-next-plan-card.js');

test('leaving the Plan screen stops its timers, returning starts one set again', () => {
    const el = new (customElements.get('sem-next-plan-card'))();
    el.connectedCallback();
    const first = [el._logTimer, el._sunTimer, el._statTimer];
    assert.ok(first.every(Boolean), 'running after connect');
    el.disconnectedCallback();
    assert.deepEqual([el._logTimer, el._sunTimer, el._statTimer], [null, null, null]);
    el.connectedCallback();
    const again = [el._logTimer, el._sunTimer, el._statTimer];
    assert.ok(again.every(Boolean), 'running after return');
    assert.ok(again.every((t, i) => t !== first[i]), 'new timers, not the old ones');
    el.disconnectedCallback();
});

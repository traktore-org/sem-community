/** (#1321) Shared card test harness: lit faked, the cards loaded, real-shaped states. */
import { register } from 'node:module';

const FAKE_LIT = `
export class LitElement {
    constructor() { this.style = {}; this.classList = { toggle() {} }; this.renderRoot = { querySelector: () => null, querySelectorAll: () => [], getElementById: () => null, appendChild() {} }; }
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
export const repeat = (items, key, fn) => Array.from(items).map((it, i) => fn(it, i));
`;
const LOADER = `
const FAKE = ${JSON.stringify('data:text/javascript,' + encodeURIComponent(FAKE_LIT))};
export async function resolve(specifier, context, next) {
    if (specifier === 'lit' || specifier.startsWith('lit/')) return { url: FAKE, shortCircuit: true };
    return next(specifier, context);
}`;
register('data:text/javascript,' + encodeURIComponent(LOADER));
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
await import('../src/cards/sem-next-now-card.js');
await import('../src/cards/sem-next-system-card.js');
await import('../src/cards/sem-next-plan-card.js');
await import('../src/cards/sem-next-devices-card.js');
await import('../src/cards/sem-next-insights-card.js');

export const S = (state, attributes = {}) => ({ state: String(state), attributes, last_updated: '2026-11-18T06:16:00+00:00' });
export const TZ = 'Europe/Zurich';

export function text(part) {
    if (part == null || typeof part === 'symbol' || part === false) return '';
    if (Array.isArray(part)) return part.map(text).join('');
    if (part && part.strings && part.values) {
        let out = '';
        part.strings.forEach((x, i) => { out += x; if (i < part.values.length) out += text(part.values[i]); });
        return out;
    }
    if (typeof part === 'function') return '';
    return String(part);
}

/** every function a template carries (the click handlers), in order */
export function fns(part, out = []) {
    if (typeof part === 'function') out.push(part);
    else if (Array.isArray(part)) part.forEach((x) => fns(x, out));
    else if (part && part.values) part.values.forEach((x) => fns(x, out));
    return out;
}
export function mount(tag, states) {
    const el = new (customElements.get(tag))();
    el.setConfig({ type: 'custom:' + tag });
    el.__calls = [];
    el.hass = { states, language: 'en', config: { currency: 'CHF', time_zone: TZ }, callService: async (...a) => { el.__calls.push(a); }, callWS: async () => ({}) };
    // a dialog that records its buttons instead of drawing
    el.__dlg = { opened: [], on: {} };
    el._dialog = (o) => {
        el.__dlg.opened.push(o);
        const node = { querySelector: (sel) => ({ addEventListener: (_ev, fn) => { el.__dlg.on[sel] = fn; } }) };
        return { el: node, close: () => { el.__dlg.closed = (el.__dlg.closed || 0) + 1; } };
    };
    el.__calls = [];
    return el;
}
export const writes = (el) => el.__calls.filter((c) => c[1] !== 'get_config');

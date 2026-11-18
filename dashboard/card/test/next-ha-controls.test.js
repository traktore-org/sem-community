/**
 * (#1321) Every control draws Home Assistant's element when it is defined and
 * a native one when it is not, and both do the same job.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
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
const waiting = new Map();
globalThis.customElements = {
    get: (t) => registry.get(t),
    define: (t, c) => { registry.set(t, c); (waiting.get(t) || []).forEach((f) => f()); },
    whenDefined: (t) => (registry.has(t) ? Promise.resolve() : new Promise((r) => { waiting.set(t, [...(waiting.get(t) || []), r]); })),
};
globalThis.getComputedStyle = () => ({ getPropertyValue: () => '' });
globalThis.localStorage = { getItem: () => null, setItem() {} };
globalThis.navigator ??= {};
globalThis.semLocalize = (key) => key;
await import('../src/cards/sem-next-now-card.js');
const { ensureHaElements, haDefined } = await import('../src/util/ha-elements.js');

const TAGS = ['ha-switch', 'ha-control-select', 'ha-button', 'ha-selector', 'ha-textfield', 'ha-alert'];
const STUB = class {};
const defineAll = (on) => TAGS.forEach((t) => { if (on) registry.set(t, STUB); else registry.delete(t); });

function text(part) {
    if (part == null || typeof part === 'symbol' || part === false) return '';
    if (Array.isArray(part)) return part.map(text).join('');
    if (part && part.strings && part.values) {
        let out = '';
        part.strings.forEach((s, i) => { out += s; if (i < part.values.length) out += text(part.values[i]); });
        return out;
    }
    return typeof part === 'function' ? '' : String(part);
}
const handlers = (part, out = []) => {
    if (Array.isArray(part)) part.forEach((p) => handlers(p, out));
    else if (part && part.values) part.values.forEach((v) => (typeof v === 'function' ? out.push(v) : handlers(v, out)));
    return out;
};
const card = () => {
    const el = new (customElements.get('sem-next-now-card'))();
    el._hass = { states: {}, language: 'en', config: {}, callService: async () => {} };
    return el;
};
const ITEMS = [{ key: 'a', label: 'Alpha' }, { key: 2, label: 'Two' }, { key: 'c', label: 'Gamma', disabled: true }];

for (const defined of [false, true]) {
    const how = defined ? 'HA element defined' : 'HA element undefined';

    test(`switch, ${how}`, () => {
        defineAll(defined);
        const got = [];
        const out = card()._switch(true, (v) => got.push(v), { label: 'x' });
        assert.match(text(out), defined ? /<ha-switch/ : /<button[^>]*role="switch"/);
        const [fire] = handlers(out).filter((f) => f.length <= 1);
        fire({ target: { checked: false } });
        assert.equal(got.length, 1);
    });

    test(`segmented control, ${how}`, () => {
        defineAll(defined);
        const picked = [];
        const out = card()._seg(ITEMS, 'a', (k) => picked.push(k));
        assert.match(text(out), defined ? /<ha-control-select/ : /<div class="seg/);
        const fire = handlers(out).find((f) => f.length === 1);
        defined ? fire({ detail: { value: '2' } }) : null;
        if (defined) {
            fire({ detail: { value: 'a' } });   // already selected: nothing
            fire({ detail: { value: 'c' } });   // disabled: nothing
        } else {
            handlers(out).forEach((f) => f());  // each native button
            picked.length = 0;
            handlers(out)[1]();
        }
        assert.deepEqual(picked, [2], 'the key comes back as it was given (a number stays a number)');
    });

    test(`button, ${how}`, () => {
        defineAll(defined);
        let n = 0;
        const out = card()._btn('Go', () => { n++; }, { primary: true });
        assert.match(text(out), defined ? /<ha-button[^>]*appearance="filled"/ : /<button[^>]*class="btn primary/);
        handlers(out).find((f) => f.length <= 1)();
        assert.equal(n, 1);
    });

    test(`one-line field, ${how}`, () => {
        defineAll(defined);
        const seen = [];
        const out = card()._input({ type: 'number', value: 5, min: 0, onChange: (e) => seen.push(e.target.value) });
        assert.match(text(out), defined ? /<ha-textfield/ : /<input/);
        handlers(out)[0]({ target: { value: '7' } });
        assert.deepEqual(seen, ['7']);
    });

    test(`choice list, ${how}`, () => {
        defineAll(defined);
        const seen = [];
        const out = card()._select([{ value: 'x', label: 'X' }, { value: 'y', label: 'Y' }], 'x', (v) => seen.push(v));
        // (#1321) the rounded chip either way: HA's grey form field looked out of place
        assert.match(text(out), /pickchip/);
        assert.match(text(out), /<select/);
        assert.doesNotMatch(text(out), /<ha-selector/);
        const fire = handlers(out)[0];
        fire({ target: { value: 'y' } });
        assert.deepEqual(seen, ['y']);
    });
}

test('the toast goes to HA\'s snackbar when it exists, else shows in the card', () => {
    defineAll(false);
    const el = card();
    el._toast('Saved');
    assert.equal(el._toastText, 'Saved');
    registry.set('notification-manager', STUB);
    const events = [];
    el.dispatchEvent = (e) => events.push(e);
    el._toast('Again');
    registry.delete('notification-manager');
    assert.equal(events[0].type, 'hass-notification');
    assert.equal(events[0].detail.message, 'Again');
    assert.equal(el._toastText, '', 'nothing shown twice');
});

test('the header switch is HA\'s ha-switch when defined, the native one otherwise', () => {
    defineAll(false);
    assert.doesNotMatch(text(card()._renderHead()), /<ha-switch/);
    assert.match(text(card()._renderHead()), /role="switch"/);
    defineAll(true);
    assert.match(text(card()._renderHead()), /<ha-switch/);
    defineAll(false);
});

test('ensureHaElements reports what exists, waits for what arrives, gives up on the rest', async () => {
    defineAll(false);
    registry.delete('ha-late');
    registry.delete('ha-never');
    registry.set('ha-now', STUB);
    setTimeout(() => customElements.define('ha-late', STUB), 20);
    const got = await ensureHaElements(['ha-now', 'ha-late', 'ha-never'], 150);
    assert.deepEqual(got, { 'ha-now': true, 'ha-late': true, 'ha-never': false });
    assert.equal(haDefined('ha-late'), true);
});

test('ensureHaElements works where the page has no element registry', async () => {
    const saved = globalThis.customElements;
    globalThis.customElements = undefined;
    try { assert.deepEqual(await ensureHaElements(['ha-switch'], 10), { 'ha-switch': false }); }
    finally { globalThis.customElements = saved; }
});

test('a disabled segmented control is the readable native one even when HA has its own', () => {
    defineAll(true);
    const el = card();
    el._hass.states['switch.sem_observer_mode'] = { state: 'on', attributes: {} };
    const out = el._seg(ITEMS, 'a', () => {}, { disabled: true });
    assert.match(text(out), /<div class="seg[^"]* off/);
    assert.doesNotMatch(text(out), /<ha-control-select/);
    assert.match(text(out), /next_disabled_watching/, 'says why on hover while SEM only watches');
    defineAll(false);
});

test('a disabled button says why while SEM only watches, an enabled one does not', () => {
    defineAll(false);
    const el = card();
    el._hass.states['switch.sem_observer_mode'] = { state: 'on', attributes: {} };
    assert.match(text(el._btn('Go', () => {}, { disabled: true })), /title="next_disabled_watching"/);
    assert.doesNotMatch(text(el._btn('Go', () => {})), /next_disabled_watching/);
});

for (const defined of [false, true]) {
    test(`alert, ${defined ? 'HA element defined' : 'HA element undefined'}`, () => {
        defineAll(defined);
        const out = card()._alert('info', 'Title', 'Body', 'ACTION');
        assert.match(text(out), defined ? /<ha-alert alert-type="info"/ : /<div class="alert info"/);
        assert.match(text(out), /Body/);
        assert.match(text(out), /ACTION/);
        defineAll(false);
    });
}

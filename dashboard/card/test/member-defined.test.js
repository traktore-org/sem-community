/**
 * #1128 — a card read a field it never set.
 *
 * The load list read `this._prefix` to find the anti-cycle range. The card
 * names its prefix `this.entityPrefix`, so the read gave `undefined`, the
 * range was never found, and the minimum run / pause fields took any value.
 * JavaScript gives no error for this: a missing member is `undefined`. The
 * Solar card had the same fault: its per-string rows called
 * `this._fireMoreInfo?.()`, a method only two other cards define, so a click
 * did nothing.
 *
 * This test loads every card (Lit replaced by a stub, as in
 * reconnect.test.js) and fails when a card reads `this.<name>` that the
 * card, SEMLitBase or the browser element does not define.
 *
 * Run: `npm test` (from dashboard/card).
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';
import { readFileSync, readdirSync } from 'node:fs';

const FAKE_LIT = `
export class LitElement {
    constructor() { this.renderRoot = globalThis.__semFakeRoot(); this.style = {}; }
    connectedCallback() {}
    disconnectedCallback() {}
    requestUpdate() {}
    get updateComplete() { return Promise.resolve(true); }
}
const tag = () => '';
export const html = tag, css = tag, svg = tag;
export const nothing = Symbol('nothing');
export const unsafeSVG = (s) => s;
export const repeat = () => '';
`;
const LOADER = `
const FAKE = ${JSON.stringify('data:text/javascript,' + encodeURIComponent(FAKE_LIT))};
export async function resolve(specifier, context, next) {
    if (specifier === 'lit' || specifier.startsWith('lit/')) return { url: FAKE, shortCircuit: true };
    return next(specifier, context);
}`;
register('data:text/javascript,' + encodeURIComponent(LOADER));

globalThis.__semFakeRoot = () => ({
    querySelector: () => null, querySelectorAll: () => [], getElementById: () => null,
});
globalThis.window ??= globalThis;
globalThis.document ??= {
    addEventListener() {}, removeEventListener() {},
    documentElement: {}, head: { appendChild() {} }, createElement: () => ({}),
};
globalThis.addEventListener ??= () => {};
globalThis.removeEventListener ??= () => {};
const registry = new Map();
globalThis.customElements ??= { get: (t) => registry.get(t), define: (t, c) => registry.set(t, c) };
globalThis.getComputedStyle ??= () => ({ getPropertyValue: () => '' });
globalThis.localStorage ??= { getItem: () => null, setItem() {} };

// What a real element gets from HTMLElement and LitElement, which the stub
// does not have. Only names the cards use; a new one is added here.
const ELEMENT_MEMBERS = new Set([
    'shadowRoot', 'renderRoot', 'isConnected', 'dispatchEvent', 'addEventListener',
    'removeEventListener', 'querySelector', 'querySelectorAll', 'getBoundingClientRect',
    'closest', 'parentNode', 'parentElement', 'offsetWidth', 'offsetHeight',
    'clientWidth', 'clientHeight', 'style', 'classList', 'getAttribute', 'setAttribute',
    'hasUpdated', 'updateComplete', 'requestUpdate', 'constructor', 'tagName',
]);

const SRC = new URL('../src/', import.meta.url);
const read = (rel) => readFileSync(new URL(rel, SRC), 'utf8');

// Comments say `this.x` in prose; strings name members for bracket access
// (`'this._lastBattPower'`). Neither is a read. A quoted run never crosses
// `${`, so apostrophes in template text (`Don't ${this.x} won't`) do not
// hide the read between them.
const code = (src) => src
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|\s)\/\/.*$/gm, '$1')
    .replace(/'(?:[^'\\\n$]|\\.|\$(?!\{))*'/g, "''");

// Fields the source writes: `this.x = …`, `this.x += …`, `this.x++`.
// Class fields (`_options = {};`) are read off a real instance instead.
function written(src) {
    const names = new Set();
    for (const m of src.matchAll(/this\.([A-Za-z_$][\w$]*)\s*(?:[-+*/%|&?]{0,2}=(?!=)|\+\+|--)/g)) names.add(m[1]);
    return names;
}

function protoNames(cls) {
    const names = new Set();
    for (let p = cls.prototype; p && p !== Object.prototype; p = Object.getPrototypeOf(p)) {
        for (const n of Object.getOwnPropertyNames(p)) names.add(n);
    }
    return names;
}

function cardFiles() {
    const out = [];
    for (const dir of ['cards/']) {
        for (const f of readdirSync(new URL(dir, SRC))) {
            if (!f.endsWith('.js')) continue;
            const tag = read(dir + f).match(/(?:semDefineCard|customElements\.define)\(\s*'([a-z-]+)'/)?.[1];
            if (tag) out.push({ file: dir + f, tag });
        }
    }
    return out;
}

const BASE = 'base/sem-lit-base.js';
const { SEMLitBase } = await import(new URL(BASE, SRC));

test('every card defines each member it reads', async () => {
    const cards = cardFiles();
    assert.ok(cards.length >= 8, `the card list is wrong: ${cards.length} cards`);
    const baseWritten = written(code(read(BASE)));
    const problems = [];
    for (const { file, tag } of cards) {
        await import(new URL(file, SRC));
        const Card = customElements.get(tag);
        if (!Card) { problems.push(`${file}: no card found for ${tag}`); continue; }
        const src = code(read(file));
        const defined = new Set([
            ...protoNames(Card), ...written(src), ...ELEMENT_MEMBERS,
            ...Object.keys(new Card()), ...Object.keys(Card.properties || {}),
            ...(Card.prototype instanceof SEMLitBase ? baseWritten : []),
        ]);
        const reads = new Set([...src.matchAll(/this\.([A-Za-z_$][\w$]*)/g)].map((m) => m[1]));
        for (const r of reads) if (!defined.has(r)) problems.push(`${file}: reads this.${r}, never defines it`);
    }
    assert.deepEqual(problems, []);
});

test('SEMLitBase defines each member it reads', () => {
    const src = code(read(BASE));
    const defined = new Set([...protoNames(SEMLitBase), ...written(src), ...ELEMENT_MEMBERS]);
    const reads = new Set([...src.matchAll(/this\.([A-Za-z_$][\w$]*)/g)].map((m) => m[1]));
    // The base reads `_prefix` with a fallback; each card writes it.
    defined.add('_prefix');
    assert.deepEqual([...reads].filter((r) => !defined.has(r)), []);
});

test('the check sees a missing member', () => {
    const src = code(`
        class X { setConfig(c) { this.entityPrefix = c.p; }
                  a() { return this._prefix + 'x'; } }`);
    const reads = [...src.matchAll(/this\.([A-Za-z_$][\w$]*)/g)].map((m) => m[1]);
    const missing = reads.filter((r) => !written(src).has(r));
    assert.deepEqual(missing, ['_prefix']);
});

test('one name for the entity prefix in every card', async () => {
    // SEMLitBase reads `this._prefix` as text. A card that keeps its prefix
    // under another name, or makes `_prefix` a method, is not seen by it.
    const problems = [];
    for (const { file, tag } of cardFiles()) {
        const src = code(read(file));
        for (const m of src.matchAll(/this\.([A-Za-z_$][\w$]*)\s*=\s*config\.entity_prefix\b/g)) {
            if (m[1] !== '_prefix') problems.push(`${file}: keeps the prefix in this.${m[1]}`);
        }
        await import(new URL(file, SRC));
        if (typeof customElements.get(tag)?.prototype._prefix === 'function') {
            problems.push(`${file}: _prefix is a method`);
        }
    }
    assert.deepEqual(problems, []);
});

/**
 * #1200 — a card must not print 0 for a sensor that is out.
 *
 * Each card kept a small reader, `_val(suffix, fallback = 0)`, that handed
 * back 0 for an unavailable or unknown sensor, and the card printed it: the
 * EV card read "0 W" for a charger power that was out, the same as a car that
 * is not charging; the battery card "0%" health and "0.00 kWh" for the day.
 * `parseFloat(state) ?? fallback` let a state that is no number through as
 * NaN. Found while fixing the tab header (#1198, class 164).
 *
 * Every card in src/cards is drawn here with every SEM sensor out. It may
 * print only the numbers listed for it below: settings, counts and labels,
 * never a sensor's fallback. A new card, or a new figure that prints its
 * fallback, fails here.
 *
 * The real card code runs here; lit is replaced by a stub that keeps the
 * template parts (CI runs `node --test` with no node_modules).
 *
 * Run: `npm test` (from dashboard/card).
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';
import { readdirSync, readFileSync } from 'node:fs';

const FAKE_LIT = `
export class LitElement {
    constructor() { this.style = {}; this.renderRoot = { querySelector: () => null, querySelectorAll: () => [], getElementById: () => null }; }
    connectedCallback() {}
    disconnectedCallback() {}
    requestUpdate() {}
    updated() {}
    getRootNode() { return {}; }
    get updateComplete() { return Promise.resolve(true); }
}
export const html = (strings, ...values) => ({ tpl: true, strings: [...strings], values });
export const css = () => '', svg = html;
export const nothing = Symbol('nothing');
export const unsafeSVG = (s) => s;
export const repeat = (items, k, f) => (items || []).map((x, i) => (f || k)(x, i));
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
    addEventListener() {}, removeEventListener() {}, querySelector: () => null,
    documentElement: {}, head: { appendChild() {} },
    createElement: () => ({ style: {}, setAttribute() {}, appendChild() {} }),
    hidden: false, visibilityState: 'visible',
};
globalThis.addEventListener = () => {};
globalThis.removeEventListener = () => {};
const registry = new Map();
globalThis.customElements = { get: (t) => registry.get(t), define: (t, c) => registry.set(t, c) };
globalThis.getComputedStyle = () => ({ getPropertyValue: () => '' });
globalThis.localStorage = { getItem: () => null, setItem() {} };
globalThis.navigator ??= {};
globalThis.requestAnimationFrame = () => 1;
globalThis.cancelAnimationFrame = () => {};
const observer = class { observe() {} disconnect() {} unobserve() {} };
globalThis.ResizeObserver = observer;
globalThis.IntersectionObserver = observer;
globalThis.MutationObserver = observer;
globalThis.fetch = async () => ({ ok: false, json: async () => ({}) });

// Template parts → the text a person would read.
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
    if (typeof part === 'function') return '';
    return String(part);
}
const words = (s) => s
    .replace(/<style[\s\S]*?<\/style>/g, ' ')
    .replace(/<!--[\s\S]*?-->/g, ' ')
    .replace(/<[^>]*>/g, ' ')
    .replace(/&nbsp;/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
// Every number a person reads: "0", "0.00", "+56", "−3" — not the 1 in "PV1".
// (#1321) a charger named while names load is "Charger 1": its place in the list, not a reading
const numbers = (s) => [...s.replace(/config_detect_charger \d+/g, 'config_detect_charger').matchAll(/(?<![\w.])[+\-−]?\d+(?:[.,]\d+)?(?![\w])/g)].map((m) => m[0]);

const CARDS = readdirSync(new URL('../src/cards/', import.meta.url))
    .filter((f) => f.startsWith('sem-') && f.endsWith('.js'))
    .map((f) => f.replace(/\.js$/, ''));
for (const c of CARDS) await import(`../src/cards/${c}.js`);

// A card that needs a config to draw at all gets one.
const CONFIG = {
};

// Every SEM sensor reads `state`; settings (number, select, switch) are not
// there, so a card shows its own default for them. A charger and a battery
// exist. `state === undefined`: no SEM sensor exists at all.
function hassWith(state) {
    const base = {};
    if (state !== undefined) {
        for (const id of DISCOVERY) base[id] = { entity_id: id, state, attributes: {} };
    }
    const states = new Proxy(base, {
        get(t, k) {
            if (typeof k !== 'string') return undefined;
            if (k in t) return t[k];
            if (state !== undefined && k.startsWith('sensor.')) return { entity_id: k, state, attributes: {} };
            return undefined;
        },
    });
    return {
        states, language: 'en', locale: { language: 'en' },
        config: { currency: 'EUR', unit_system: { temperature: '°C' }, time_zone: 'UTC' },
        callWS: async () => ({}), callService: async () => ({}),
        connection: { subscribeMessage: async () => () => {}, subscribeEvents: async () => () => {} },
    };
}
const DISCOVERY = ['sensor.sem_charger_keba_power', 'sensor.sem_battery_b1_power',
    'sensor.sem_battery_power', 'sensor.sem_solar_power', 'sensor.sem_ev_power'];

function card(tag, hass) {
    const el = new (customElements.get(tag))();
    el.setConfig({ type: `custom:${tag}`, ...(CONFIG[tag] || {}) });
    el._scheduleUpdate = () => {};
    el.hass = hass;
    return el;
}
const draw = (tag, state) => words(text(card(tag, hassWith(state)).render()));
const dashes = (s) => s.split('—').length - 1;

// The numbers a card may print with every SEM sensor out: settings shown with
// their own default (no number entity here), counts, labels, the hours of a
// day. Never a sensor's fallback.
const ALLOWED_OUT = {
    // (#1321) the SEM Next screens: counts ride inside translated lines
    // ("{n} devices"), which the stub localizer leaves as bare keys.
    'sem-next-devices-card': ['1', '50', '2'],                 // rank badges; boost floor default
    'sem-next-insights-card': [],
    'sem-next-now-card': [],
    'sem-next-plan-card': [],
    'sem-next-setup-panel': [],
    'sem-next-system-card': [],
    'sem-setup-checklist-card': [],
    'sem-simulation-card': ['0'],                              // days stored, from its own query
};
// The dashes a card prints with every sensor reading: the settings, times and
// query results that are not here. A sensor that reads never prints the dash.
const DASHES_WITH_READINGS = {
    'sem-simulation-card': 2,
    // (#1321) the schedule shows once, as rows that need their entities: no
    // entity, no row, no dash
    'sem-next-devices-card': 0,
    // drawn before the first update writes its labels (tested below)
};
const DRAWN = CARDS.filter((t) => typeof customElements.get(t) === 'function');

test('every card is listed: a new card says what it prints', () => {
    assert.deepEqual([...DRAWN].sort(), Object.keys(ALLOWED_OUT).sort());
});

for (const tag of DRAWN) {
    test(`${tag}: a sensor that is out prints no number`, () => {
        for (const state of ['unavailable', 'unknown', 'n/a', 'nan', '']) {
            const out = draw(tag, state);
            assert.doesNotMatch(out, /NaN|undefined|null|Infinity/, `${state}: ${out}`);
            assert.deepEqual(numbers(out), ALLOWED_OUT[tag], `"${state}": ${out}`);
        }
        // No sensor at all: fewer sections, and still no fallback. The
        // charger count is then 0.
        const none = numbers(draw(tag, undefined));
        const may = [...ALLOWED_OUT[tag], ...(tag === 'sem-charger-status-card' ? ['0'] : [])];
        for (const n of none) assert.ok(may.includes(n), `missing: ${n}`);
    });

    test(`${tag}: a sensor that reads never prints the dash`, () => {
        const out = draw(tag, '1234');
        assert.doesNotMatch(out, /NaN|undefined|null|Infinity/, out);
        assert.equal(dashes(out), DASHES_WITH_READINGS[tag] ?? 0, out);
    });
}

// ── The readers ────────────────────────────────────────────────────────────

const { readNumber, fmtValue, MISSING } = await import('../src/util/missing-value.js');
const { importKw } = await import('../src/util/peak-slot.js');

test('readNumber: a number, or null when the sensor gives none', () => {
    const st = (state) => ({ state });
    assert.equal(readNumber(st('12.5')), 12.5);
    assert.equal(readNumber(st('0')), 0, 'a real 0 is a reading');
    assert.equal(readNumber(st('-300')), -300);
    for (const s of ['unavailable', 'unknown', '', 'n/a', 'nan', 'NaN', 'Infinity', 'none']) {
        assert.equal(readNumber(st(s)), null, s);
    }
    assert.equal(readNumber(undefined), null);
    assert.equal(fmtValue(null, 1), MISSING);
    assert.equal(fmtValue(NaN, 1), MISSING);
    assert.equal(fmtValue(0, 1), '0.0');
    assert.equal(importKw(''), null, 'an empty state imports nothing known');
    assert.equal(importKw('-1500'), 1.5);
});

// Every card reader: no number as a default, and no `parseFloat(x) ?? y`,
// which lets NaN through. A sum that wants 0 passes it.
test('no card reader keeps a number as its default', () => {
    const dir = new URL('../src/', import.meta.url);
    const files = [];
    for (const sub of ['cards/', 'base/']) {
        for (const f of readdirSync(new URL(sub, dir))) {
            if (f.endsWith('.js')) files.push(new URL(sub + f, dir));
        }
    }
    for (const f of files) {
        const src = readFileSync(f, 'utf8');
        const name = f.pathname.split('/src/')[1];
        assert.doesNotMatch(src, /^\s+_\w+\([\w, ]*\bfallback\s*=\s*-?\d/m,
            `${name}: a reader's default is a number again`);
        // The readers by name, whatever their parameters are called.
        for (const m of src.matchAll(/^\s+_(val|state|valNum|numVal|entityVal|getState)\(([^)]*)\)\s*\{/gm)) {
            assert.doesNotMatch(m[2], /=\s*-?\d/, `${name}: _${m[1]}(${m[2]})`);
        }
        assert.doesNotMatch(src, /parseFloat\([^()]*\)\s*\?\?/,
            `${name}: parseFloat(x) ?? y lets NaN through`);
    }
});

// ── Sums and checks keep their own 0 ───────────────────────────────────────

const st = (state, attributes = {}) => ({ state: String(state), attributes });
const OUT = st('unavailable');
const hassOf = (states) => ({ states, language: 'en', config: { currency: 'EUR' } });
function made(tag, states, config = {}) {
    const el = new (customElements.get(tag))();
    el.setConfig({ type: `custom:${tag}`, ...config });
    el._scheduleUpdate = () => {};
    el.hass = hassOf(states);
    return el;
}

// ── Found in review ────────────────────────────────────────────────────────

// ── #1265: half a pair that is set, and it is out ──────────────────────────

const { pairOut } = await import('../src/util/missing-value.js');

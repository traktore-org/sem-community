/**
 * #1292 — the chart card draws W and kWh, so it asks the recorder for W and
 * kWh. A sensor kept in kW or MWh came back in its own unit and was drawn a
 * thousand times too small or large.
 *
 * Run: `npm test` (from dashboard/card).
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';
import { readFileSync, readdirSync } from 'node:fs';

const FAKE_LIT = `
export class LitElement {
    constructor() {
        this.hasUpdated = false;
        this.isConnected = false;
        this.style = {};
        this.renderRoot = globalThis.__semFakeRoot();
        this.updates = 0;
        this.__enabled = false;
        this.__pending = true;
    }
    connectedCallback() {
        if (this.__enabled) return;
        this.__enabled = true;
        queueMicrotask(() => this.__perform());
    }
    disconnectedCallback() {}
    requestUpdate() {
        if (this.__pending) return;
        this.__pending = true;
        if (this.__enabled) queueMicrotask(() => this.__perform());
    }
    __perform() {
        if (!this.__pending) return;
        this.__pending = false;
        this.updates++;
        if (!this.hasUpdated) { this.hasUpdated = true; this.firstUpdated?.(new Map()); }
        this.updated?.(new Map());
    }
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


globalThis.__semFakeRoot = () => ({
    querySelector: () => null, querySelectorAll: () => [], getElementById: () => null,
});
globalThis.window = globalThis;
globalThis.document = {
    addEventListener() {}, removeEventListener() {},
    documentElement: {}, head: { appendChild() {} }, createElement: () => ({}),
    hidden: false, visibilityState: 'visible',
};
globalThis.addEventListener = () => {};
globalThis.removeEventListener = () => {};
const registry = new Map();
globalThis.customElements = { get: (t) => registry.get(t), define: (t, c) => registry.set(t, c) };
globalThis.getComputedStyle = () => ({ getPropertyValue: () => '' });
globalThis.ResizeObserver = class { observe() {} disconnect() {} };
globalThis.IntersectionObserver = class { observe() {} disconnect() {} };
globalThis.localStorage = { getItem: () => null, setItem() {} };
globalThis.navigator ??= {};

await import('../src/cards/sem-chart-card.js');

function card(callWS) {
    const el = new (customElements.get('sem-chart-card'))();
    el.setConfig({ preset: 'power' });
    el._hass = { language: 'en', config: { time_zone: 'UTC' }, states: {}, callWS };
    return el;
}
const SERIES = [{ entity: 'sensor.sem_solar_power' }];
const T0 = '2026-11-01T00:00:00Z', T1 = '2026-11-01T12:00:00Z';

test('the recorder is asked for W and kWh', async () => {
    const seen = [];
    const el = card(async (msg) => { seen.push(msg); return { 'sensor.sem_solar_power': [] }; });
    await el._fetchStatistics(SERIES, T0, T1, 'hour');
    assert.equal(seen.length, 1);
    assert.deepEqual(seen[0].units, { power: 'W', energy: 'kWh' });
});

test('the older statistics call is asked for the same units', async () => {
    const seen = [];
    const el = card(async (msg) => {
        seen.push(msg);
        if (msg.type === 'recorder/statistics_during_period') throw new Error('unknown command');
        return { 'sensor.sem_solar_power': [] };
    });
    await el._fetchStatistics(SERIES, T0, T1, 'day');
    assert.equal(seen[1].type, 'history/statistics_during_period');
    assert.deepEqual(seen[1].units, { power: 'W', energy: 'kWh' });
});

test('every card that reads statistics passes units', () => {
    const dir = new URL('../src/', import.meta.url);
    const files = [];
    const walk = (d) => {
        for (const e of readdirSync(d, { withFileTypes: true })) {
            const u = new URL(e.name + (e.isDirectory() ? '/' : ''), d);
            if (e.isDirectory()) walk(u); else if (e.name.endsWith('.js')) files.push(u);
        }
    };
    walk(dir);
    let callers = 0;
    for (const f of files) {
        const text = readFileSync(f, 'utf8');
        const calls = text.match(/type:\s*'(?:recorder|history)\/statistics_during_period'[^}]*}/g) || [];
        for (const c of calls) {
            callers++;
            assert.match(c, /\bunits\b/, `${f.pathname} reads statistics without units`);
        }
    }
    assert.ok(callers >= 2, 'the scan found the chart card calls');
});

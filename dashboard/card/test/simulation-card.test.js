/**
 * (#1083) The Simulation card, driven with a fake hass: it polls `status`
 * every 2 s only while a run runs, stops when you leave the tab, reads the
 * result once the run ends, and says "busy" when another run is going.
 *
 * Lit is replaced by a stub (as in reconnect.test.js), so only the card's
 * own code runs. Run: `npm test` (from dashboard/card).
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';

const FAKE_LIT = `
export class LitElement {
    constructor() { this.isConnected = false; this.hasUpdated = false; this.style = {}; }
    connectedCallback() {}
    disconnectedCallback() {}
    requestUpdate() {}
    updated() {}
}
const tag = () => '';
export const html = tag, css = tag, svg = tag;
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
globalThis.document = {
    addEventListener() {}, removeEventListener() {}, documentElement: {},
    body: { appendChild() {} }, createElement: () => ({ click() {}, remove() {} }),
};
const registry = new Map();
globalThis.customElements = { get: (t) => registry.get(t), define: (t, c) => registry.set(t, c) };
globalThis.getComputedStyle = () => ({ getPropertyValue: () => '' });

// Timers the card sets are held here and fired by hand: no real waiting.
const timers = new Map();
let nextId = 1;
globalThis.setTimeout = (fn, ms) => { const id = nextId++; timers.set(id, { fn, ms }); return id; };
globalThis.clearTimeout = (id) => { timers.delete(id); };
const pollTimers = () => [...timers.values()].filter((t) => t.ms === 2000);
async function firePolls() {
    const due = [...timers.entries()].filter(([, t]) => t.ms === 2000);
    for (const [id, t] of due) { timers.delete(id); await t.fn(); }
    await flush();
}
const flush = () => new Promise((r) => queueMicrotask(() => queueMicrotask(r)));
async function settle() { for (let i = 0; i < 10; i++) await flush(); }

await import('../src/cards/sem-simulation-card.js');
const Card = customElements.get('sem-simulation-card');

function fakeHass({ statuses, startError } = {}) {
    const calls = [];
    const seq = [...(statuses || [{ running: false, status: 'idle' }])];
    const hass = {
        language: 'en', states: {}, config: {}, calls,
        callWS: async (msg) => {
            const cmd = msg.type.split('/').pop();
            calls.push({ cmd, msg });
            switch (cmd) {
            case 'days': return { days: [{ date: '2026-10-01', tags: ['sunny'], selectable: true }], stored: 1, gaps: 0 };
            case 'defaults': return { capacity_kwh: 15, reserve_pct: 20, peak_limit_kw: null, import_rate: 0.3, export_rate: 0.1, currency: 'CHF' };
            case 'status': return seq.length > 1 ? seq.shift() : seq[0];
            case 'start':
                if (startError) { const e = new Error(startError.message); e.code = startError.code; throw e; }
                return { run_id: 'r1' };
            case 'cancel': return { cancelled: true };
            case 'result': return { run_id: 'r1', currency: 'CHF', days: [], per_tag: {}, total: { days: 1 } };
            default: return {};
            }
        },
    };
    return hass;
}
const count = (hass, cmd) => hass.calls.filter((c) => c.cmd === cmd).length;

async function mount(hass) {
    timers.clear();
    const el = new Card();
    el.setConfig({});
    el.isConnected = true;
    el.connectedCallback();
    el.hass = hass;
    await settle();
    return el;
}
function leave(el) { el.isConnected = false; el.disconnectedCallback(); }

test('nothing running: no polling, the last result is read once', async () => {
    const hass = fakeHass();
    const el = await mount(hass);
    assert.equal(count(hass, 'status'), 1);
    assert.equal(pollTimers().length, 0, 'polls while nothing runs');
    assert.equal(count(hass, 'result'), 1);
    assert.equal(el._days.stored, 1);
    assert.equal(el._form.capacity_kwh, 15);
    leave(el);
});

test('a run polls every 2 s until it ends, then reads the result', async () => {
    const run = { running: true, status: 'running', done: 1, total: 3, run_id: 'r1', started_at: new Date().toISOString() };
    const hass = fakeHass({ statuses: [run, { ...run, done: 2 }, { ...run, running: false, status: 'done', done: 3 }] });
    const el = await mount(hass);
    assert.equal(pollTimers().length, 1, 'no poll while running');
    assert.equal(count(hass, 'result'), 0, 'read a result mid-run');
    await firePolls();
    assert.equal(pollTimers().length, 1);
    await firePolls();
    assert.equal(pollTimers().length, 0, 'still polling after the run ended');
    assert.equal(count(hass, 'result'), 1);
    assert.equal(hass.calls.find((c) => c.cmd === 'result').msg.run_id, 'r1');
    leave(el);
});

test('leaving the tab stops polling; coming back starts it again', async () => {
    const run = { running: true, status: 'running', done: 1, total: 3, run_id: 'r1' };
    const hass = fakeHass({ statuses: [run] });
    const el = await mount(hass);
    assert.equal(pollTimers().length, 1);
    leave(el);
    assert.equal(pollTimers().length, 0, 'a poll outlived the card');
    el.isConnected = true;
    el.connectedCallback();
    await settle();
    assert.equal(pollTimers().length, 1, 'polling did not come back');
    leave(el);
});

test('start sends the picked days and the form; then polls', async () => {
    const run = { running: true, status: 'running', done: 0, total: 1, run_id: 'r1' };
    const hass = fakeHass({ statuses: [{ running: false, status: 'idle' }, run] });
    const el = await mount(hass);
    el._pick('sunny');
    el._setForm({ capacity_kwh: '20', export_mode: 'flat', export_rate: '0.08' });
    await el._start();
    const start = hass.calls.find((c) => c.cmd === 'start').msg;
    assert.deepEqual(start.days, ['2026-10-01']);
    assert.deepEqual(start.params, {
        capacity_kwh: 20, reserve_pct: 20, peak_limit_kw: null, import_rate: 'recorded', export_rate: 0.08,
    });
    assert.equal(pollTimers().length, 1);
    leave(el);
});

test('no days picked: start sends nothing', async () => {
    const hass = fakeHass();
    const el = await mount(hass);
    await el._start();
    assert.equal(count(hass, 'start'), 0);
    leave(el);
});

test('busy: a short line, and the other run is followed', async () => {
    const run = { running: true, status: 'running', done: 1, total: 5, run_id: 'other' };
    const hass = fakeHass({ statuses: [{ running: false, status: 'idle' }, run], startError: { code: 'busy', message: 'busy' } });
    const el = await mount(hass);
    el._pick('sunny');
    await el._start();
    await settle();
    assert.deepEqual(el._error, { kind: 'busy' });
    assert.equal(el._status.run_id, 'other');
    assert.equal(pollTimers().length, 1);
    leave(el);
});

test('a failed run shows its error text', async () => {
    const hass = fakeHass({ statuses: [{ running: false, status: 'failed', error: 'recorder gone' }] });
    const el = await mount(hass);
    assert.deepEqual(el._error, { kind: 'failed', text: 'recorder gone' });
    leave(el);
});

test('stop cancels and reads the result of what ran', async () => {
    const run = { running: true, status: 'running', done: 1, total: 3, run_id: 'r1' };
    const hass = fakeHass({ statuses: [run, { ...run, running: false, status: 'cancelled' }] });
    const el = await mount(hass);
    await el._cancel();
    await settle();
    assert.equal(count(hass, 'cancel'), 1);
    assert.equal(count(hass, 'result'), 1);
    assert.equal(pollTimers().length, 0);
    leave(el);
});

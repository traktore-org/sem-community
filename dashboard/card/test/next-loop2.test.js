/**
 * (#1321) Review loop 2: a tap alone never changes what SEM does.
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
globalThis.customElements = { get: (t) => registry.get(t), define: (t, c) => registry.set(t, c) };
globalThis.getComputedStyle = () => ({ getPropertyValue: () => '' });
globalThis.localStorage = { getItem: () => null, setItem() {} };
globalThis.navigator ??= {};
globalThis.semLocalize = (key) => key;
await import('../src/cards/sem-next-now-card.js');
await import('../src/cards/sem-next-system-card.js');
await import('../src/cards/sem-next-plan-card.js');
await import('../src/cards/sem-next-devices-card.js');
const { deadlineLabel, planWhenKey } = await import('../src/util/next-time.js');
const { chargerSaysEach } = await import('../src/util/charger-questions.js');
const { planLead, planGridKwh } = await import('../src/util/next-lead.js');
const { whyLines } = await import('../src/util/plan-why.js');

const S = (state, attributes = {}) => ({ state: String(state), attributes, last_updated: '2026-11-18T06:16:00+00:00' });
const TZ = 'Europe/Zurich';

/** every function a template carries (the click handlers), in order */
function fns(part, out = []) {
    if (typeof part === 'function') out.push(part);
    else if (Array.isArray(part)) part.forEach((x) => fns(x, out));
    else if (part && part.values) part.values.forEach((x) => fns(x, out));
    return out;
}
function mount(tag, states) {
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
/** the writes: loading the options is a read */
const writes = (el) => el.__calls.filter((c) => c[1] !== 'get_config');
const sys = (extra = {}) => mount('sem-next-system-card', {
    'sensor.sem_diag_grid_sign': S('negated'), 'sensor.sem_diag_battery_sign': S('normal'), 'switch.sem_observer_mode': S('on'), ...extra });

test('1: a sign row shows its direction, not "Flip sign"', () => {
    const el = sys();
    const val = (action) => el._actionValue({ kind: 'action', action, labelKey: 'next_flip_sign' }, (k) => k);
    assert.equal(val('flip_grid_sign'), 'sign_negated');
    assert.equal(val('flip_battery_sign'), 'normal');
    assert.equal(el._actionValue({ kind: 'action', action: 'purge_status_history', labelKey: 'next_run' }, (k) => k), 'Next_run');
});

for (const [action, label] of [['flip_grid_sign', 'Grid sign'], ['flip_battery_sign', 'Battery sign'], ['reset_sign_detection', 'Reset'], ['purge_status_history', 'Clean up']]) {
    test(`1: ${action} row — a tap alone calls nothing, confirm calls it once, cancel never`, async () => {
        const el = sys();
        const row = el._slotRow({ slot: { kind: 'action', action, labelKey: 'next_flip_sign' }, label, more: false });
        const tap = fns(row)[0];
        tap();
        assert.equal(writes(el).length, 0, 'tap alone');
        assert.equal(el.__dlg.opened.length, 1);
        el.__dlg.on['#cf-cancel']();
        assert.equal(writes(el).length, 0, 'cancel');
        el.__dlg.on['#cf-ok']();
        await new Promise((r) => setTimeout(r, 5));
        assert.equal(writes(el).filter((c) => c[1] === action).length, 1, 'confirm');
    });
}

test('1: the flip dialog says what flipping does and names its button Flip', () => {
    const el = sys({ 'switch.sem_observer_mode': S('off') });
    el._askAction({ kind: 'action', action: 'flip_grid_sign' }, 'Grid sign');
    const o = el.__dlg.opened[0];
    assert.equal(o.title, 'Grid sign');
    const html = o.build(true);
    assert.match(html, /next_flip_grid_body/);
    assert.match(html, />next_flip_ok</);
    assert.match(html, /cf-cancel/);
});

test('1: a confirmed flip calls the service exactly once', async () => {
    const el = sys({ 'switch.sem_observer_mode': S('off') });
    el._askAction({ kind: 'action', action: 'flip_grid_sign' }, 'Grid sign');
    assert.equal(writes(el).length, 0);
    el.__dlg.on['#cf-ok']();
    await new Promise((r) => setTimeout(r, 5));
    assert.deepEqual(writes(el).map((c) => c[1]), ['flip_grid_sign']);
});

test('1: Plan screen — Sell only asks on a tap', () => {
    const el = mount('sem-next-plan-card', { 'select.sem_battery_mode': S('auto', { options: ['auto', 'force_discharge'] }), 'switch.sem_observer_mode': S('off') });
    const row = el._batteryRow({ slots: [], batt_runs: [] }, [], [], []);
    for (const f of fns(row)) f();
    assert.equal(writes(el).length, 0);
    assert.equal(el.__dlg.opened.length, 1);
    el.__dlg.on['#cf-ok']();
    assert.deepEqual(writes(el).map((c) => [c[0], c[1]]), [['select', 'select_option']]);
});

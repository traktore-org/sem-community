/**
 * (#1081) The Devices screen's heat pump COP row: the COP now, the curve as
 * text, and only a whole curve (or an empty box) is sent.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';

const FAKE_LIT = `
export class LitElement { constructor() { this.style = {}; } }
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
globalThis.window = globalThis;
globalThis.document = { addEventListener() {}, removeEventListener() {}, documentElement: {}, head: { appendChild() {} }, createElement: () => ({}) };
const registry = new Map();
globalThis.customElements = { get: (t) => registry.get(t), define: (t, c) => registry.set(t, c) };
globalThis.navigator ??= {};
const { copCurveRow } = await import('../src/util/next-devices-load.js');

function fakeCard(states = {}) {
    const card = {
        _hass: { states },
        _t: (k) => k,
        _tf: (k, p) => k + ' ' + JSON.stringify(p),
        _fmt: (v, d = 1) => Number(v).toFixed(d),
        rows: [],
        editors: {},
        _inline(key, text, editor) { this.editors[key] = editor; return text; },
        _textEdit(key, o) { return o; },
        _row(icon, label, val, sub, o) { return { icon, label, val, sub, o }; },
    };
    return card;
}

test('a curve shows as text, under More, with the COP now', () => {
    const card = fakeCard({ 'sensor.sem_heat_pump_cost_of_heat': { state: '0.08',
        attributes: { cop_used: 3.7, cop_source: 'curve', outdoor_c: 7 } } });
    const r = copCurveRow(card, { id: 'heat_pump' }, { cop_curve: '12:4.2, -7:2.5' }, () => {});
    assert.equal(r.val, '-7:2.5, 12:4.2');
    assert.equal(r.o.more, true);
    assert.match(r.sub, /hp_cop_now_at .*"cop":"3.7".*"temp":"7 °C"/);
});

test('no curve reads as one fixed COP', () => {
    const r = copCurveRow(fakeCard(), { id: 'heat_pump' }, { cop_curve: '' }, () => {});
    assert.equal(r.val, 'next_cop_fixed');
});

test('only a whole curve or an empty box is sent', () => {
    const sent = [];
    const card = fakeCard();
    copCurveRow(card, { id: 'heat_pump' }, { cop_curve: '' }, (p, v) => sent.push([p, v]));
    const ed = card.editors['cop:heat_pump']();
    ed.onCommit('5:3');            // one point: not a curve
    ed.onCommit('2:3, 2:4');       // the same °C twice
    ed.onCommit(' 12:4.2,-7:2.5 ');
    ed.onCommit('');
    assert.deepEqual(sent, [['cop_curve', '-7:2.5, 12:4.2'], ['cop_curve', '']]);
});

/**
 * (#1353, #1081, #1321) The Devices screen offers a tank's thermometer
 * proposal and the pre-heat tick, through the classic card's helpers.
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
const { loadBody, preheatRow } = await import('../src/util/next-devices-load.js');
const { deviceRows } = await import('../src/util/next-devices.js');
const rowFromMap = (id, info) => deviceRows({ [id]: info })[0];

function fakeCard(obs = false) {
    // any helper the test does not care about renders nothing
    return new Proxy({
        sent: [], _hass: { states: {}, config: { unit_system: { temperature: '°C' } } },
        _t: (k) => k, _tf: (k, p) => k + ' ' + JSON.stringify(p),
        _obs: () => obs, _rowsNow: () => [], _has: () => false, _attrs: () => ({}),
        _dev(id, property, value) { this.sent.push({ id, property, value }); },
        _row(icon, label, val, sub, o) { return { icon, label, val, sub, o }; },
        _btn(label, onClick, o) { return { btn: label, onClick, o }; },
        _val: (text, onTap, o) => ({ text, onTap, o }), _seg: () => null,
        _switch: (on, onChange, o) => ({ sw: true, on, onChange, o }),
        _inline: () => null, _entEdit: () => null, _textEdit: () => null, _selEdit: () => null,
        _sentence: () => '', _powerW: () => null, _money: (v) => String(v), _kw: String,
        _live: () => ({}), _pillText: (p) => p.key, _callService() {}, _showConfigureModal() {}, _showError() {},
    }, { get: (t, k) => (k in t ? t[k] : (typeof k === 'string' && k[0] === '_' ? () => null : undefined)) });
}
const flat = (x, out = []) => {
    if (Array.isArray(x)) x.forEach((y) => flat(y, out));
    else if (x && typeof x === 'object') { out.push(x); if (x.tpl) flat(x.values, out); else if (x.val) flat(x.val, out); }
    return out;
};
const rowsOf = (card, info) => {
    const row = rowFromMap('hot_water', { name: 'Boiler', kind: 'hot_water', control_mode: 'solar_only',
        has_control_handle: true, goals: {}, ...info });
    let rows = [];
    const orig = card._row.bind(card);
    card._row = (...a) => { const r = orig(...a); rows.push(r); return r; };
    loadBody(card, row);
    return rows;
};
const PROP = { entity_id: 'sensor.tank_temp', name: 'Tank temp.', why: 'tank' };

test('the proposal row shows with a proposal and no thermometer, and sends comfort_entity', () => {
    const card = fakeCard();
    const r = rowsOf(card, { thermometer_proposal: PROP }).find((x) => /hq_found_thermometer/.test(x.label));
    assert.ok(r, 'row shown');
    assert.match(r.label, /"name":"Tank temp"/);
    r.val.onClick();
    assert.deepEqual(card.sent, [{ id: 'hot_water', property: 'comfort_entity', value: 'sensor.tank_temp' }]);
});

test('no proposal row without a proposal or with a thermometer set', () => {
    assert.equal(rowsOf(fakeCard(), {}).some((x) => /hq_found_thermometer/.test(x.label)), false);
    assert.equal(rowsOf(fakeCard(), { thermometer_proposal: PROP, goals: { comfort_entity: 'sensor.mine' } })
        .some((x) => /hq_found_thermometer/.test(x.label)), false);
});

test('the proposal button stays usable in watch only (it is a SEM setting)', () => {
    const r = rowsOf(fakeCard(true), { thermometer_proposal: PROP }).find((x) => /hq_found_thermometer/.test(x.label));
    assert.equal(!!r.val.o.disabled, false);
});

const BAND = { goals: { comfort_target: 55, comfort_limit: 40, comfort_entity: 'sensor.t', overnight_source: 'grid' },
    comfort: { keep_c: 55, limit_c: 40, preheat_ok: true, reading_c: 50 } };
const tickRow = (card, info) => rowsOf(card, info).find((x) => x.label === 'hq_preheat');

test('the tick shows only with preheat_ok', () => {
    assert.ok(tickRow(fakeCard(), BAND));
    assert.equal(tickRow(fakeCard(), { ...BAND, comfort: { ...BAND.comfort, preheat_ok: false } }), undefined);
});

test('the pre-heat checkbox sends preheat true and false', () => {
    const sent = [];
    const send = (p, v) => sent.push([p, v]);
    const box = preheatRow(fakeCard(), { on: false, enabled: true }, false, send).val;
    box.onChange(true);
    box.onChange(false);
    assert.deepEqual(sent, [['preheat', 'true'], ['preheat', 'false']]);
});

test('without grid buying the tick stays checked when stored on, disabled, with the no-buy words', () => {
    const r = preheatRow(fakeCard(), { on: true, enabled: false }, false, () => {}, '40 °C');
    assert.equal(r.val.on, true);          // checked
    assert.equal(r.val.o.disabled, true);  // disabled
    assert.match(r.sub, /hq_sub_no_buy .*40 °C/);
});

test('in observer mode the tick is disabled even with buying allowed', () => {
    const r = preheatRow(fakeCard(), { on: false, enabled: true }, true, () => {});
    assert.equal(r.val.o.disabled, true);
});

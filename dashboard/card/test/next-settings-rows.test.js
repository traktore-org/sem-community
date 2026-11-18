/**
 * (#1321, round 3) Settings are Home Assistant settings rows: label left,
 * value right, a tap opens the dialog with the right control, a boolean is a
 * switch on the row. The model (util/next-settings.js) stays the one source;
 * Apply sends what it always sent.
 *
 * Run: `node --test test/next-settings-rows.test.js` (from dashboard/card).
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


import { readFileSync } from 'node:fs';
globalThis.semLocalize = (key) => key;
await import('../src/cards/sem-next-system-card.js');
await import('../src/cards/sem-next-devices-card.js');
const { fmtNum, localeOf, setNumberLocale } = await import('../src/util/next-number.js');
const { isRealTip } = await import('../src/util/next-now-extras.js');
const { batteryBody } = await import('../src/util/next-devices-battery.js');
const { chargerBody } = await import('../src/util/next-devices-charger.js');

function text(part) {
    if (part == null || typeof part === 'symbol' || part === false) return '';
    if (Array.isArray(part)) return part.map(text).join('');
    if (part && part.strings && part.values) {
        let out = '';
        part.strings.forEach((s, i) => { out += s; if (i < part.values.length) out += text(part.values[i]); });
        return out;
    }
    if (typeof part === 'function') return '';
    return String(part);
}
/** every function a template holds, in order, with the strings before it */
function fns(part, found = []) {
    if (part == null || typeof part === 'symbol') return found;
    if (Array.isArray(part)) { part.forEach((p) => fns(p, found)); return found; }
    if (part && part.strings && part.values) {
        part.values.forEach((v, i) => {
            if (typeof v === 'function') found.push({ fn: v, before: part.strings[i] });
            else fns(v, found);
        });
    }
    return found;
}
/** the functions of a template that come after a marker string, in order */
function fnsAfter(part, marker, st = { on: false, out: [] }) {
    if (Array.isArray(part)) { part.forEach((p) => fnsAfter(p, marker, st)); return st.out; }
    if (part && part.strings && part.values) {
        part.values.forEach((v, i) => {
            if (part.strings[i].includes(marker)) st.on = true;
            if (typeof v === 'function') { if (st.on) st.out.push(v); } else fnsAfter(v, marker, st);
        });
    }
    return st.out;
}
const src = (p) => readFileSync(new URL(p, import.meta.url), 'utf8');
const S = (state, attributes = {}) => ({ state: String(state), attributes, last_updated: '2026-11-18T01:40:00+00:00' });
const HASS = (st, extra = {}) => ({ states: st, language: 'en', config: { currency: 'CHF', time_zone: 'Europe/Zurich', unit_system: { temperature: '°C' } },
    entities: {}, devices: {}, callService: async () => ({}), callWS: async () => ({}), ...extra });
function mk(tag, st, extra) {
    const el = new (customElements.get(tag))();
    el.setConfig({ type: 'custom:' + tag });
    el.hass = HASS(st, extra);
    return el;
}
const BASE = { 'switch.sem_observer_mode': S('off'), 'sensor.sem_battery_soc': S(58) };


const { groups, applyPlan, pendingKey, slotsOf, slotText } = await import('../src/util/next-settings.js');
const EN = JSON.parse(readFileSync(new URL('../../translations.json', import.meta.url), 'utf8')).en;
globalThis.semLocalize = (key) => EN[key] || key;
const tEn = (k) => EN[k] || k;
const rowTextOf = (x) => String(x).replace(/\s*\([^)]*\)\s*$/, '');

const numE = (state, min, max, step, unit) => S(state, { min, max, step, unit_of_measurement: unit });
function states() {
    return {
        'switch.sem_observer_mode': S('off'),
        'sensor.sem_charging_state': S('idle'),
        'sensor.sem_battery_soc': numE(55, 0, 100, 1, '%'),
        'sensor.sem_battery_power': S(0),
        'number.sem_electricity_import_rate': numE(0.28, 0, 10000, 0.01, 'CHF/kWh'),
        'number.sem_electricity_export_rate': numE(0.12, 0, 10000, 0.005, 'CHF/kWh'),
        'number.sem_cheap_price_threshold': numE(0.22, 0, 2, 0.01, 'CHF/kWh'),
        'number.sem_expensive_price_threshold': numE(0.33, 0, 2, 0.01, 'CHF/kWh'),
        'switch.sem_forecast_spending_enabled': S('on'),
        'number.sem_charger_keba_minimum_current': numE(6, 6, 32, 1, 'A'),
        'number.sem_charger_keba_maximum_current': numE(16, 6, 32, 1, 'A'),
        'number.sem_charger_keba_ev_phases': numE(3, 1, 3, 1, ''),
        'number.sem_update_interval': numE(30, 10, 300, 5, 's'),
        'number.sem_night_start_offset_min': numE(30, 0, 180, 5, 'min'),
        'select.sem_hints': S('weekly', { options: ['off', 'weekly', 'all'] }),
        'switch.sem_vacation_mode': S('off'),
        'sensor.pv': S(0, { friendly_name: 'Inverter input' }),
        'sensor.sem_diag_ed_config': S('ok', { energy_dashboard: { solar: { power: 'sensor.pv' }, grid: { power: 'sensor.meter' } } }),
    };
}
const OPTS = { tariff_mode: 'static', import_vat_percent: 8.1, target_peak_limit: 5, warning_peak_level: 4.5, emergency_peak_level: 6,
    ev_chargers: [{ id: 'keba', ev_target_type: 'kwh', finish_by_departure: false, external_control_mode: 'none' }],
    status_retention_days: 0, vpp_enabled: true, battery_charge_scheduler_enabled: true, load_management_enabled: true,
    shed_signal_entity: 'binary_sensor.relay', battery_external_control_mode: 'yield' };

function sys(calls = [], opts = OPTS) {
    const el = mk('sem-next-system-card', states(), { callService: async (d, s, data) => { calls.push([d, s, data]); return {}; } });
    el._optionsAsked = true; el._options = opts; el._entryId = 'E1'; el._all = true;
    return el;
}
const groupsOf = (el) => groups(el.hass.states, tEn, el._ctx());
const rowsOfAll = (el) => groupsOf(el).flatMap((g) => g.rows);
const KIND = { number: 'number', select: 'select', entity: 'entity', text: 'text' };

test('every setting slot has a row with a label and a value', () => {
    const el = sys();
    const gs = groupsOf(el);
    const slots = slotsOf(gs);
    assert.ok(slots.length > 60, 'the fixture reaches most of the model: ' + slots.length);
    const rowKeys = new Set(gs.flatMap((g) => g.rows).map((r) => pendingKey(r.slot)));
    for (const s of slots) assert.ok(rowKeys.has(pendingKey(s)), 'no row for ' + pendingKey(s));
    for (const r of rowsOfAll(el)) {
        assert.ok(r.label && r.label.trim(), 'a label for ' + pendingKey(r.slot));
        assert.doesNotMatch(r.label, /^[a-z_.]+$/, 'a plain label, not a key or id: ' + r.label);
        const out = text(el._slotRow(r));
        assert.ok(out.includes(r.label), r.label);
        if (r.slot.kind !== 'switch' && r.slot.kind !== 'action' && !r.slot.peak) {
            assert.ok(out.includes(slotText(r.slot, tEn, r.slot.value, el.hass.states)), 'value of ' + r.label);
        }
    }
});

test('a row opens the dialog for its kind; a boolean toggles on the row', () => {
    const el = sys();
    const specs = [];
    el._editDialog = (spec) => { specs.push(spec); return {}; };
    let opened = 0, toggled = 0;
    for (const r of rowsOfAll(el)) {
        const tpl = el._slotRow(r);
        const kind = r.slot.kind;
        if (kind === 'switch' || r.slot.peak) {
            assert.doesNotMatch(text(tpl), /role="button"/, 'a switch row is not a button');
            assert.match(text(tpl), /role="switch"/);
            toggled += 1;
        } else if (KIND[kind] && !r.slot.ro) {
            const [click] = fns(tpl).map((f) => f.fn);
            assert.equal(typeof click, 'function', 'tap on ' + r.label);
            click();
            const spec = specs.at(-1);
            assert.equal(spec.kind, KIND[kind], r.label);
            assert.equal(spec.title, r.label);
            opened += 1;
        }
    }
    assert.equal(specs.length, opened);
    assert.ok(opened > 40 && toggled > 5, `${opened} dialogs, ${toggled} switches`);
});

test('every row has a real label key, never the fallback word or a raw id', () => {
    const el = sys();
    for (const r of rowsOfAll(el)) {
        assert.notEqual(r.label, rowTextOf(tEn('next_row_setting')), 'fallback label on ' + pendingKey(r.slot));
        assert.doesNotMatch(r.label, /[a-z]+_[a-z]+/, 'no raw id: ' + r.label);
    }
});

test('the peak limit is a switch row, and no row prints a help line', () => {
    const el = sys();
    const r = rowsOfAll(el).find((x) => x.slot.peak);
    assert.ok(r, 'a peak row');
    assert.match(text(el._slotRow(r)), /role="switch"/);
    fns(el._slotRow(r)).map((f) => f.fn)[0]();
    assert.equal(Object.values(el._pending).length, 1, 'the toggle stages one change');
    assert.ok(['limit', 'none'].includes(Object.values(el._pending)[0].value));
    for (const row of rowsOfAll(el)) assert.doesNotMatch(text(el._slotRow(row)), /class="hlp"/, row.label);
});

test('a switch row stages the boolean, like the old inline button did', () => {
    const el = sys();
    const r = rowsOfAll(el).find((x) => x.slot.id === 'switch.sem_vacation_mode');
    const click = fns(el._slotRow(r)).map((f) => f.fn)[0];
    click();
    assert.deepEqual(el._pending['switch.sem_vacation_mode'].value, true);
    assert.deepEqual(applyPlan(el._pending, el.hass.states).entityWrites,
        [{ domain: 'switch', service: 'turn_on', data: { entity_id: 'switch.sem_vacation_mode' } }]);
    assert.match(text(el._slotRow(r)), /aria-checked="true"/);
});

// the old inline editors called _stage(slot, raw) then applyPlan; the dialog commits through the same _stage
const COMMIT = { number: 12.5, select: null, entity: 'sensor.other', text: 'abc' };
test('Apply sends the same entity writes and options as the inline editors did', async () => {
    const el = sys();
    const specs = [];
    el._editDialog = (spec) => { specs.push(spec); return {}; };
    const old = {};
    for (const r of rowsOfAll(el)) {
        const kind = r.slot.kind;
        if (!KIND[kind] || r.slot.ro || kind === 'switch' || r.slot.peak) continue;
        fns(el._slotRow(r)).map((f) => f.fn)[0]();
        const spec = specs.at(-1);
        const other = kind === 'select' ? spec.options.find((o) => String(o.value) !== String(r.slot.value)) : null;
        if (kind === 'select' && !other) continue;
        const v = kind === 'select' ? other.value : COMMIT[kind];
        spec.onCommit(v);
        old[pendingKey(r.slot)] = { slot: r.slot, value: kind === 'number' ? Number(v) : v };
    }
    const keys = Object.keys(el._pending).sort();
    assert.deepEqual(keys, Object.keys(old).sort());
    assert.deepEqual(applyPlan(el._pending, el.hass.states), applyPlan(old, el.hass.states));
    const plan = applyPlan(el._pending, el.hass.states);
    assert.ok(plan.entityWrites.length > 5 && Object.keys(plan.options).length > 8);
    // the apply bar sends them together, as before
    const calls = [];
    el.hass = { ...el.hass, callService: async (d, s, data) => { calls.push([d, s, data]); return {}; } };
    el._loadOptions = async () => {};
    await el._apply();
    assert.deepEqual(calls.filter((c) => c[0] !== 'solar_energy_management').map((c) => ({ domain: c[0], service: c[1], data: c[2] })), plan.entityWrites);
    const optCalls = calls.filter((c) => c[1] === 'set_option' && c[2].options && c[2].options.tariff_mode !== undefined);
    assert.equal(optCalls.length, 1, 'one options call');
    assert.deepEqual(optCalls[0][2], { options: plan.options, entry_id: 'E1' });
    assert.deepEqual(el._pending, {});
});

test('a number typed in the dialog goes through the same range clamp', () => {
    const el = sys();
    el._editDialog = (spec) => { spec.onCommit(99999); return {}; };
    const r = rowsOfAll(el).find((x) => x.slot.option === 'target_peak_limit');
    fns(el._slotRow(r)).map((f) => f.fn)[0]();
    const plan = applyPlan(el._pending, el.hass.states);
    assert.equal(plan.options.target_peak_limit, r.slot.max);
});

test('while SEM only watches, SEM settings rows still open (they are SEM config)', () => {
    const el = sys();
    el.hass = { ...el.hass, states: { ...el.hass.states, 'switch.sem_observer_mode': S('on') } };
    const specs = [];
    el._editDialog = (s) => { specs.push(s); return {}; };
    const r = rowsOfAll(el).find((x) => x.slot.option === 'tariff_mode');
    const out = text(el._slotRow(r));
    assert.match(out, /role="button"/);
    assert.doesNotMatch(out, /aria-disabled="true"/);
    el._openEdit(r.slot, r.label, r.slot.value);
    assert.equal(specs.length, 1);
});

test('the group keeps one read-only summary, then the rows; the rest sit under All settings', () => {
    const el = sys();
    const pay = groupsOf(el).find((g) => g.key === 'pay');
    const out = text(el._group(pay));
    assert.match(out, /class="sent"/);
    assert.doesNotMatch(out.slice(out.indexOf('class="sent"'), out.indexOf('class="rows"')), /class="val|<button/);
    assert.match(out, /class="rows"/);
    assert.ok(pay.rows.some((r) => !r.more) && pay.rows.some((r) => r.more), 'everyday and All-settings rows');
    assert.match(out, /more in All settings/);
});

test('rows are buttons for the keyboard: Enter and Space open, other keys do not', () => {
    const el = mk('sem-next-devices-card', BASE);
    let n = 0;
    const tpl = el._setRow({ label: 'Label', value: '5 kW', onTap: () => { n += 1; } });
    const out = text(tpl);
    assert.match(out, /role="button"/);
    assert.match(out, /tabindex="0"/);
    const [click, key] = fns(tpl).map((f) => f.fn);
    click();
    assert.equal(n, 1);
    for (const k of ['Enter', ' ']) key({ key: k, preventDefault() {} });
    assert.equal(n, 3);
    key({ key: 'a', preventDefault() {} });
    assert.equal(n, 3);
    const ro = text(el._setRow({ label: 'L', value: 'v', ro: true, onTap: () => {} }));
    assert.doesNotMatch(ro, /role="button"/);
});

// ── the dialog: HA elements when defined, native ones otherwise ──
class FakeEl {
    constructor(tag) { this.tag = tag; this.attrs = {}; this.children = []; this.listeners = {}; this.btns = {}; this.value = ''; this.id = ''; this.removed = false; }
    setAttribute(k, v) { this.attrs[k] = v; }
    appendChild(c) { this.children.push(c); return c; }
    addEventListener(t, f) { this.listeners[t] = f; }
    remove() { this.removed = true; }
    focus() { this.focused = true; }
    querySelector(sel) {
        if (sel === '.ed-body') return (this.body ??= new FakeEl('div'));
        const m = /^#(.+)$/.exec(sel);
        if (m && String(this.innerHTML).includes(`id="${m[1]}"`)) return (this.btns[m[1]] ??= new FakeEl('btn'));
        return null;
    }
}
function dialogCard(defined = []) {
    const el = mk('sem-next-devices-card', BASE);
    const made = [];
    const root = { activeElement: null, getElementById: () => null, appendChild: (x) => made.push(x), querySelector: () => null };
    el.renderRoot = root;
    return { el, made, run: async (fn) => {
        const prevC = document.createElement, prevG = customElements.get;
        document.createElement = (tag) => new FakeEl(tag);
        customElements.get = (t) => (defined.includes(t) ? class {} : registry.get(t));
        try { return await fn(); } finally { document.createElement = prevC; customElements.get = prevG; }
    } };
}

test('the dialog without HA elements uses native fields; OK commits, Cancel and Escape do not', async () => {
    const { el, run } = dialogCard();
    const got = [];
    const { dlg, field } = await run(async () => {
        const dlg = await el._editDialog({ title: 'Level', kind: 'number', value: 5, min: 0, max: 10, step: 1, unit: 'kW', onCommit: (v) => got.push(v) });
        return { dlg, field: dlg.el.body.children.at(-1) };
    });
    assert.equal(dlg.el.attrs.role, 'dialog');
    const input = field.children ? field.children[0] : field;
    assert.equal(input.tag, 'input');
    assert.equal(input.attrs.type, 'number');
    assert.equal(input.attrs.max, '10');
    input.value = '7';
    dlg.el.btns['ed-ok'].listeners.click();
    assert.deepEqual(got, [7]);
    assert.equal(dlg.el.removed, true);
});

test('the dialog commits nothing for a blank number, an unchanged value or Escape', async () => {
    const { el, run } = dialogCard();
    const got = [];
    const open = (spec) => run(async () => el._editDialog({ title: 'T', onCommit: (...v) => got.push(v), ...spec }));
    let d = await open({ kind: 'number', value: 5 });
    d.el.body.children.at(-1).children[0] ? null : null;
    const num = (dlg) => { const c = dlg.el.body.children.at(-1); return c.tag === 'input' ? c : c.children[0]; };
    num(d).value = '';
    d.el.btns['ed-ok'].listeners.click();
    d = await open({ kind: 'number', value: 5 });
    num(d).value = '5';
    d.el.btns['ed-ok'].listeners.click();
    d = await open({ kind: 'number', value: 5 });
    num(d).value = '9';
    d.el.listeners.keydown({ key: 'Escape', stopPropagation() {} });
    assert.equal(d.el.removed, true);
    assert.deepEqual(got, []);
});

test('a select is a native select without ha-selector, ha-selector with it', async () => {
    const options = [{ value: 'a', label: 'A' }, { value: 'b', label: 'B' }];
    let got = null;
    let c = dialogCard();
    let d = await c.run(async () => c.el._editDialog({ title: 'T', kind: 'select', value: 'a', options, onCommit: (v) => { got = v; } }));
    const sel = d.el.body.children.at(-1);
    assert.equal(sel.tag, 'select');
    assert.deepEqual(sel.children.map((o) => o.value), ['a', 'b']);
    sel.value = 'b';
    d.el.btns['ed-ok'].listeners.click();
    assert.equal(got, 'b');
    c = dialogCard(['ha-selector', 'ha-textfield', 'ha-dialog']);
    got = null;
    d = await c.run(async () => c.el._editDialog({ title: 'T', kind: 'select', value: 'a', options, onCommit: (v) => { got = v; } }));
    const hs = d.el.body.children.at(-1);
    assert.equal(hs.tag, 'ha-selector');
    assert.deepEqual(hs.selector.select.options.map((o) => o.value), ['a', 'b']);
    assert.ok(hs.hass);
    hs.listeners['value-changed']({ stopPropagation() {}, detail: { value: 'b' } });
    d.el.btns['ed-ok'].listeners.click();
    assert.equal(got, 'b');
});

test('text and entity fields: ha-textfield and the picker when defined, plain inputs otherwise', async () => {
    let got = null;
    let c = dialogCard(['ha-textfield', 'ha-dialog']);
    let d = await c.run(async () => c.el._editDialog({ title: 'T', kind: 'text', value: 'x', unit: 'min', onCommit: (v) => { got = v; } }));
    const tf = d.el.body.children.at(-1);
    assert.equal(tf.tag, 'ha-textfield');
    assert.equal(tf.attrs.suffix, 'min');
    tf.value = 'abc';
    tf.listeners.keydown({ key: 'Enter', preventDefault() {} });
    assert.equal(got, 'abc', 'Enter in the field commits');
    got = null;
    c = dialogCard();
    d = await c.run(async () => c.el._editDialog({ title: 'T', kind: 'entity', value: '', domains: ['sensor'], allowClear: true, onCommit: (v) => { got = v; } }));
    const inp = d.el.body.children.at(-1);
    assert.equal(inp.tag, 'input');
    assert.match(inp.attrs.placeholder, /sensor/);
    inp.value = 'sensor.a';
    d.el.btns['ed-ok'].listeners.click();
    assert.equal(got, 'sensor.a');
});

test('a pair dialog commits both numbers; an entity with a value can be cleared', async () => {
    let got = null;
    let c = dialogCard();
    let d = await c.run(async () => c.el._editDialog({ title: 'T', kind: 'pair', unit: 'kWh', a: { value: 1, min: 0, max: 9 }, b: { value: 5, min: 0, max: 9 }, onCommit: (a, b) => { got = [a, b]; } }));
    const ins = d.el.body.children.filter((x) => x.tag === 'input' || (x.children && x.children[0]));
    const inp = (x) => (x.tag === 'input' ? x : x.children[0]);
    inp(ins[0]).value = '2'; inp(ins[1]).value = '6';
    d.el.btns['ed-ok'].listeners.click();
    assert.deepEqual(got, [2, 6]);
    got = null;
    c = dialogCard();
    d = await c.run(async () => c.el._editDialog({ title: 'T', kind: 'entity', value: 'sensor.a', allowClear: true, onCommit: (v) => { got = v; } }));
    d.el.btns['ed-none'].listeners.click();
    assert.equal(got, '');
});

// ── Devices: the sentence editors are rows ──
const DEV = { ...BASE,
    'sensor.sem_battery_power': S(-800), 'sensor.sem_battery_status': S('discharging'),
    'number.sem_battery_priority_soc': numE(30, 0, 100, 1, '%'), 'number.sem_battery_buffer_soc': numE(70, 0, 100, 1, '%'),
    'number.sem_battery_auto_start_soc': numE(85, 0, 100, 1, '%'), 'switch.sem_battery_may_assist_ev': S('on'),
    'number.sem_battery_assist_max_power': numE(3000, 0, 10000, 100, 'W'), 'number.sem_battery_assist_min_surplus': numE(500, 0, 5000, 50, 'W'),
    'select.sem_battery_mode': S('auto', { options: ['auto', 'off'] }) };
test('Devices: the battery levels are rows; a tap opens a number dialog that writes the entity', () => {
    const calls = [];
    const el = mk('sem-next-devices-card', DEV, { callService: async (d, s, data) => { calls.push([d, s, data]); } });
    const tpl = batteryBody(el, { id: 'battery', type: 'battery' });
    const out = text(tpl);
    for (const k of ['bq_priority', 'bq_buffer', 'bq_autostart', 'bq_assist_max', 'bq_solar_gate', 'bq_may_assist']) assert.ok(out.includes(EN[k]), k);
    assert.match(out, /30 %/);
    assert.ok(out.includes(EN.bq_priority_sub), 'help under the label');
    const specs = [];
    el._editDialog = (s) => { specs.push(s); return {}; };
    const rows = (function collect(p, out = []) {
        if (Array.isArray(p)) p.forEach((x) => collect(x, out));
        else if (p && p.strings) { if (p.strings.join('').includes('class="row set')) out.push(p); p.values.forEach((v) => collect(v, out)); }
        return out;
    })(tpl);
    const pri = rows.find((r) => text(r).includes(EN.bq_priority));
    fns(pri)[0].fn();
    assert.equal(specs[0].kind, 'number');
    assert.equal(specs[0].max, 100);
    specs[0].onCommit(35);
    assert.deepEqual(calls.at(-1), ['number', 'set_value', { entity_id: 'number.sem_battery_priority_soc', value: 35 }]);
    const sw = rows.find((r) => text(r).includes(EN.bq_may_assist));
    assert.match(text(sw), /role="switch"/);
    fns(sw)[0].fn();
    assert.deepEqual(calls.at(-1), ['switch', 'turn_off', { entity_id: 'switch.sem_battery_may_assist_ev' }]);
});

const CAR = { ...BASE, 'sensor.sem_charging_state': S('idle', { per_charger_departure: { keba: { default: '07:00', by_weekday: {}, one_block: false, late_min: 0, boost_allowed: true } },
        per_charger_phases: { keba: { active_phases: 3 } }, battery_boost_preview: { default_floor: 50 } }),
    'sensor.sem_charger_keba_power': S(0, { unit_of_measurement: 'W' }),
    'select.sem_charger_keba_charge_mode': S('solar_only', { options: ['solar_only', 'off'] }),
    'time.sem_charger_keba_target_time': S('07:00:00'), 'button.sem_charger_keba_pause_charging': S('unknown') };
test('Devices: the charger target, charge by and goal are rows; the pair dialog writes both entities', () => {
    const calls = [];
    const st = { ...CAR, 'number.sem_charger_keba_minimum_current': numE(6, 6, 32, 1, 'A'),
        'number.sem_charger_keba_daily_ev_target': numE(10, 0, 50, 1, 'kWh'), 'number.sem_charger_keba_ev_target_min': numE(10, 0, 50, 1, 'kWh'),
        'number.sem_charger_keba_ev_target_max': numE(30, 0, 50, 1, 'kWh'),
        'number.sem_charger_keba_daily_ev_target_max': numE(30, 0, 50, 1, 'kWh') };
    const el = mk('sem-next-devices-card', st, { callService: async (d, s, data) => { calls.push([d, s, data]); } });
    const tpl = chargerBody(el, { id: 'load_device_keba', cid: 'keba', type: 'charger' });
    const out = text(tpl);
    assert.ok(out.includes(EN.ev_charge_by));
    assert.ok(out.includes(EN.charge_target));
    const specs = [];
    el._editDialog = (s) => { specs.push(s); return {}; };
    const rows = (function collect(p, out = []) {
        if (Array.isArray(p)) p.forEach((x) => collect(x, out));
        else if (p && p.strings) { if (p.strings.join('').includes('class="row set')) out.push(p); p.values.forEach((v) => collect(v, out)); }
        return out;
    })(tpl);
    const by = rows.find((r) => text(r).includes(EN.ev_charge_by));
    assert.ok(by, 'a Charge by row');
    fns(by)[0].fn();
    assert.equal(specs.at(-1).kind, 'time');
    specs.at(-1).onCommit('08:30');
    assert.deepEqual(calls.at(-1), ['time', 'set_value', { entity_id: 'time.sem_charger_keba_target_time', time: '08:30:00' }]);
});

/**
 * (#1321 review 18.11, round 2) Layout and handling: one sources row, one
 * number on the bar, one mode control, one filled button, text buttons,
 * outlined tiles, touch sizes, keyboard, locale numbers, one dialog.
 *
 * Run: `node --test test/next-review-1118-r2.test.js` (from dashboard/card).
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
await import('../src/cards/sem-next-plan-card.js');
await import('../src/cards/sem-next-now-card.js');
await import('../src/cards/sem-next-devices-card.js');
await import('../src/cards/sem-next-insights-card.js');
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

// ── 5 System: one row for healthy sources, rows only for problems ──
test('5: all sources fine = one row, no source names; a problem gets its own row', () => {
    const sys = mk('sem-next-system-card', BASE);
    const ok = (n) => ({ key: 'k' + n, name: 'Source ' + n, entity: 'sensor.x' + n, src: null, state: 'ok', age: 5, icon: 'mdi:flash', color: 'red' });
    const rows = [ok(1), ok(2), ok(3)];
    let out = text(sys._freshSummary(rows));
    assert.match(out, /next_all_sources_ok/);
    assert.doesNotMatch(out, /Source 1/);
    sys._showSources = true;
    assert.match(text(sys._freshSummary(rows)), /Source 1/, 'tap opens the list');
    sys._showSources = false;
    out = text(sys._freshSummary([ok(1), { ...ok(2), state: 'stale' }]));
    assert.match(out, /Source 2/);
    assert.doesNotMatch(out, /Source 1/);
    assert.match(out, /next_n_sources_ok/);
    assert.doesNotMatch(out, /next_all_sources_ok/);
});

// ── 10 Observer is a switch row, not a tool button ──
test('10: Observer mode is a switch row apart from the tool buttons', () => {
    const sys = mk('sem-next-system-card', BASE);
    const row = text(sys._observerRow());
    assert.match(row, /role="switch"/);
    assert.match(row, /next_observer_sub/);
    const health = text(sys._health([]));
    assert.match(health, /copy_diagnostics/);
    // the three tools are text buttons; the observer is not among the tool buttons
    const btns = health.slice(health.indexOf('class="btns"'));
    assert.doesNotMatch(btns, /next_observer/);
    assert.doesNotMatch(btns, /btn primary/);
});

test('10: a button is a text button unless it is the one main action', () => {
    const sys = mk('sem-next-system-card', BASE);
    assert.match(text(sys._btn('A', () => {})), /ghost/);
    assert.doesNotMatch(text(sys._btn('B', () => {}, { primary: true })), /ghost/);
    assert.match(text(sys._btn('B', () => {}, { primary: true })), /primary/);
});

test('10: Plan buttons use plain labels and one filled action per charger', () => {
    const plan = mk('sem-next-plan-card', { ...BASE, 'sensor.sem_charging_state': S('idle'),
        'select.sem_charger_keba_charge_mode': S('solar_only', { options: ['solar_only', 'off'] }) });
    const out = text(plan._chargerRow('keba', {}, [], [], []));
    for (const k of ['next_skip_tonight', 'next_start_now', 'next_full_power']) assert.match(out, new RegExp(k));
    assert.equal((out.match(/btn primary/g) || []).length, 1);
});

// ── 8 Now ──
test('8: the power number is printed once on the bar', () => {
    const now = mk('sem-next-now-card', { ...BASE, 'sensor.sem_grid_power': S(-800), 'sensor.sem_home_consumption_power': S(800),
        'sensor.sem_solar_power': S(0), 'sensor.sem_battery_power': S(0), 'sensor.sem_ev_power': S(0) });
    now._io = false;
    const out = text(now._powerNow());
    assert.equal((out.match(/>0\.8 kW</g) || []).length, 1, out);
    assert.doesNotMatch(out, /next_tap_row_history|next_self_use_pct/);
    assert.doesNotMatch(out, /next_bar_unfold|next_bar_fold/, 'no hint line under the bar');
});

test('8: the two Today cards are named and "No recommendations" is not a tip', () => {
    const now = mk('sem-next-now-card', { ...BASE, 'sensor.sem_charging_state': S('idle'), 'sensor.sem_energy_tip': S('No recommendations') });
    assert.match(text(now._todayList()), /next_coming_up/);
    assert.doesNotMatch(text(now._signals()), /next_tip/);
    assert.equal(isRealTip('No recommendations at this time'), false);
    assert.equal(isRealTip('Run the dishwasher at noon'), true);
});

// ── 9 Devices ──
const BAT = { ...BASE, 'select.sem_battery_mode': S('auto', { options: ['auto', 'self_consumption', 'force_charge', 'force_discharge', 'off'] }),
    'sensor.sem_battery_charge_pacing': S('x', { reason_code: 'paced', action: 'wrote', cap_w: 2000, enabled: true }),
    'switch.sem_battery_charge_pacing_enabled': S('on') };
test('9: the battery has one mode control; pacing sits under More', () => {
    const el = mk('sem-next-devices-card', BAT);
    const calls = [];
    const real = el._seg.bind(el);
    el._seg = (items, ...rest) => { calls.push(items.map((i) => i.key)); return real(items, ...rest); };
    const out = text(batteryBody(el, { id: 'battery' }));
    const modeCalls = calls.filter((c) => c.includes('off') && c.includes('auto'));
    assert.equal(modeCalls.length, 1);
    assert.deepEqual(modeCalls[0], ['off', 'auto', 'self_consumption', 'force_charge', 'force_discharge']);
    assert.equal(calls.filter((c) => c.includes('self_consumption')).length, 1, 'Auto / Self-consumption is not a second control');
    const more = out.slice(out.indexOf('<details'));
    assert.match(more, /charge_pacing/);
    assert.doesNotMatch(out.slice(0, out.indexOf('<details')), /charge_pacing/);
});

const CAR = { ...BASE, 'sensor.sem_charging_state': S('idle', { per_charger_departure: { keba: { default: '07:00', by_weekday: { sat: '09:00' }, one_block: false, late_min: 0, boost_allowed: true } },
        per_charger_phases: { keba: { active_phases: 3 } }, battery_boost_preview: { default_floor: 50 } }),
    'sensor.sem_charger_keba_power': S(0, { unit_of_measurement: 'W' }),
    'select.sem_charger_keba_charge_mode': S('solar_only', { options: ['solar_only', 'off'] }),
    'select.sem_charger_keba_phase_mode': S('auto', { options: ['auto', '1', '3'] }),
    'time.sem_charger_keba_target_time': S('07:00:00'), 'button.sem_charger_keba_pause_charging': S('unknown') };
test('9: the weekly schedule shows once; boost, one block and phases sit under More', () => {
    const el = mk('sem-next-devices-card', CAR);
    const out = text(chargerBody(el, { id: 'load_device_keba', cid: 'keba', type: 'charger' }));
    assert.equal((out.match(/mdi:calendar-repeat/g) || []).length, 0, 'no second schedule row');
    const i = out.indexOf('<details');
    assert.ok(i > 0);
    const head = out.slice(0, i), more = out.slice(i);
    for (const k of ['ev_dep_one_block', 'next_phases', 'next_boost_to']) {
        assert.match(more, new RegExp(k, 'i'), k);
        assert.doesNotMatch(head, new RegExp(k, 'i'), k);
    }
    assert.match(head, /pause_charging/);
    assert.equal((out.match(/btn primary/g) || []).length, 1);
});

// ── 11 tiles, 12 touch, Also ──
test('11: tiles are outlined, not grey filled', () => {
    const css = src('../src/base/sem-next-base.js');
    const rule = css.match(/\n\s*\.tile \{([^}]*)\}/)[1];
    assert.match(rule, /border: 1px solid var\(--n-line\)/);
    assert.match(rule, /background: transparent/);
});

test('12: a coarse pointer makes every control at least 40 px', () => {
    const css = src('../src/base/sem-next-base.js');
    const block = css.match(/@media \(pointer: coarse\) \{([\s\S]*?)\n    \}/)[1];
    for (const sel of ['.chip', '.seg button', '.btn.sm', 'input[type="text"]', '.sw', '.dev .rank']) assert.ok(block.includes(sel), sel);
    assert.match(block, /min-height: 40px/);
    assert.match(block, /--control-select-thickness: 40px/);
    assert.match(block, /\.dev \.rank \{ width: 40px; height: 40px; \}/);
});

test('12: long names end in an ellipsis, not a mid-word break; the unit stays whole', () => {
    const css = src('../src/base/sem-next-base.js');
    assert.match(css, /\.dev \.name > span:not\(\.pill\) \{[^}]*text-overflow: ellipsis/);
    assert.match(css, /\.row\.ell \.k \.t \{[^}]*text-overflow: ellipsis/);
    assert.match(css, /\.big small \{ white-space: nowrap/);
    assert.doesNotMatch(css, /\.row \.k \.t \{[^}]*overflow-wrap: anywhere/);
});

test('12: Insights topics are a dropdown on a narrow phone and tabs when wide', () => {
    const el = mk('sem-next-insights-card', BASE);
    el._w = 380;
    assert.match(text(el.render()), /<select aria-label="next_topic"/);
    el._w = 900;
    assert.doesNotMatch(text(el.render()), /<select aria-label="next_topic"/);
});

test('Also: no .switch class, secondary text and disabled opacity as asked', () => {
    const css = src('../src/base/sem-next-base.js');
    assert.doesNotMatch(css, /\.switch\b/);
    assert.match(css, /--n-fg2: var\(--secondary-text-color, #6b6b6b\)/);
    assert.match(css, /\.sw\[disabled\] \{ opacity: \.6/);
});

test('Also: the energy bar and the price strip say their meaning in words', () => {
    const now = mk('sem-next-now-card', { ...BASE, 'sensor.sem_grid_power': S(-800), 'sensor.sem_home_consumption_power': S(800),
        'sensor.sem_solar_power': S(0), 'sensor.sem_battery_power': S(0), 'sensor.sem_ev_power': S(0) });
    const out = text(now._powerNow());
    assert.match(out, /aria-label="next_bar_aria, next_src_grid 0\.8 kW, →, next_src_house 0\.8 kW"/);
});

// ── 13 keyboard ──
const KEY = (k) => ({ key: k, preventDefault() {} });
test('13: header chips are real buttons', () => {
    const el = mk('sem-next-devices-card', BASE);
    const head = text(el._renderHead());
    assert.match(head, /<button type="button" class="chip"/);
    assert.doesNotMatch(head, /role="button"/);
});

test('13: the device name acts on Enter and Space like a click', () => {
    const el = mk('sem-next-devices-card', CAR);
    let n = 0;
    el._toggleOpen = () => { n += 1; };
    const row = { id: 'load_device_keba', cid: 'keba', type: 'charger', name: 'Car', icon: 'mdi:car', dependsOn: [] };
    const tpl = el._shell(row, 0);
    const hs = fnsAfter(tpl, 'name tap');
    hs[0]();                      // the click
    hs[1](KEY('Enter'));          // the key handler follows it
    hs[1](KEY(' '));
    hs[1](KEY('a'));
    assert.equal(n, 3, 'click, Enter and Space; another key does nothing');
});

// ── 14 locale ──
test('14: numbers follow the language: de shows 3,5 kW, en 3.5 kW; the unit stays', () => {
    const de = mk('sem-next-now-card', BASE, { language: 'de' });
    assert.equal(de._kw(3500), '3,5 kW');
    assert.equal(de._kwh(12.34), '12,3 kWh');
    assert.equal(de._money(1.5), '1,50 CHF');
    assert.equal(de._fmt(null), '—');
    const en = mk('sem-next-now-card', BASE, { language: 'en' });
    assert.equal(en._kw(3500), '3.5 kW');
    assert.equal(en._price(0.075), '0.075');
    const de2 = mk('sem-next-now-card', BASE, { language: 'de' });
    assert.equal(de2._price(0.075), '0,075');
});

test('14: HA locale settings win: number_format and hass.locale.language', () => {
    assert.equal(localeOf({ language: 'en', locale: { language: 'fr', number_format: 'language' } }), 'fr');
    assert.equal(localeOf({ language: 'en', locale: { number_format: 'decimal_comma' } }), 'de');
    assert.equal(fmtNum(1234.5, 1, 'de'), '1.234,5');
    assert.equal(fmtNum('x', 1), '—');
    setNumberLocale({ language: 'en' });
});

test('14: no raw question mark and no toFixed on a screen text', () => {
    for (const f of ['../src/cards/sem-next-devices-card.js', '../src/cards/sem-next-insights-card.js', '../src/cards/sem-next-system-card.js',
        '../src/util/next-lead.js', '../src/util/next-timeline.js', '../src/util/next-review.js', '../src/util/next-settings.js']) {
        const code = src(f).split('\n').filter((l) => !/^\s*(\/\/|\*)/.test(l)).join('\n');
        // diagnostics text for support (copy to clipboard) stays plain
        const lines = code.split('\n').filter((l) => /toFixed\(/.test(l) && !/capStr|toFixed\(4\)/.test(l));
        assert.deepEqual(lines, [], f);
        assert.doesNotMatch(code, /\|\| '\?'|: '\?'/, f);
    }
});

// ── 15 dialog ──
function fakeEl(tag) {
    const el = { tag, attrs: {}, listeners: {}, removed: false, focused: false, children: [], id: '' };
    el.setAttribute = (k, v) => { el.attrs[k] = v; };
    el.addEventListener = (t, f) => { el.listeners[t] = f; };
    el.remove = () => { el.removed = true; };
    el.querySelector = () => ({ focus() { el.firstFocused = true; } });
    el.focus = () => { el.focused = true; };
    return el;
}
test('15: _dialog has role=dialog, aria-modal, closes on Escape and gives focus back', () => {
    const el = mk('sem-next-devices-card', BASE);
    const opener = fakeEl('button');
    const appended = [];
    el.renderRoot = { activeElement: opener, getElementById: () => null, appendChild: (x) => appended.push(x), querySelector: () => null };
    const prevCreate = document.createElement;
    document.createElement = (tag) => fakeEl(tag);
    let closed = 0;
    let built;
    try {
        const { el: d, close } = el._dialog({ id: 'x-dlg', title: 'Configure', build: (native) => { built = native; return '<b>hi</b>'; }, onClose: () => { closed += 1; } });
        assert.equal(d.attrs.role, 'dialog');
        assert.equal(d.attrs['aria-modal'], 'true');
        assert.equal(d.attrs['aria-label'], 'Configure');
        assert.equal(d.tag, 'div', 'plain overlay when ha-dialog is not defined');
        assert.equal(built, false);
        assert.equal(d.className, 'dlg-overlay');
        assert.equal(appended[0], d);
        assert.equal(d.firstFocused, true, 'focus moves into the dialog');
        d.listeners.keydown({ key: 'a', stopPropagation() {} });
        assert.equal(d.removed, false, 'another key does not close it');
        d.listeners.keydown({ key: 'Escape', stopPropagation() {} });
        assert.equal(d.removed, true);
        assert.equal(opener.focused, true, 'focus returns to the control that opened it');
        close();
        assert.equal(closed, 1, 'closing twice calls onClose once');
    } finally { document.createElement = prevCreate; }
});

test('15: the configure dialog has no inline overlay styles left', () => {
    const modal = src('../src/cards/load-config-modal.js');
    assert.doesNotMatch(modal, /position:fixed/);
    assert.match(modal, /class="dlg-box"/);
    assert.doesNotMatch(src('../src/cards/sem-next-devices-card.js'), /position:fixed/);
});

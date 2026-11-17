/**
 * (#1354) The classic and the new dashboard render the same settings from ONE
 * shared model each (dashboard/card/src/util/*-questions.js, settings-applies,
 * plan-notes). Here both cards are drawn from the same state and must show
 * the same values under the same text keys — a card that grows its own copy
 * of the logic, or its own words, fails here.
 *
 * Text keys are compared, not English: the stub has no translations, so a
 * card prints the key it asks for.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';
import { readFileSync } from 'node:fs';

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
        part.strings.forEach((s, i) => { out += s; if (i < part.values.length) out += text(part.values[i]); });
        return out;
    }
    if (typeof part === 'function') return '';
    return String(part);
}
const words = (s) => s.replace(/<style[\s\S]*?<\/style>/g, ' ').replace(/<!--[\s\S]*?-->/g, ' ')
    .replace(/<[^>]*>/g, ' ').replace(/&nbsp;/g, ' ').replace(/\s+/g, ' ').trim();

const TAGS = ['sem-battery-zones-card', 'sem-battery-card', 'sem-load-priority-card', 'sem-ev-status-card',
    'sem-next-devices-card', 'sem-next-system-card', 'sem-next-now-card'];
for (const c of TAGS) await import(`../src/cards/${c}.js`);
const { PEAK_TEXT, peakQuestion } = await import('../src/util/peak-questions.js');
const { BATTERY_LEVELS, batteryLevels, batterySaysFromStates } = await import('../src/util/battery-questions.js');
const { CHARGER_TEXT, targetEntities } = await import('../src/util/charger-questions.js');

const S = (state, attributes = {}) => ({ entity_id: '', state: String(state), attributes, last_updated: '2026-11-07T12:40:00+01:00' });

function baseStates(extra = {}) {
    return {
        'number.sem_battery_priority_soc': S(30, { min: 0, max: 100, step: 5, unit_of_measurement: '%' }),
        'number.sem_battery_buffer_soc': S(70, { min: 0, max: 100, step: 5, unit_of_measurement: '%' }),
        'number.sem_battery_auto_start_soc': S(85, { min: 0, max: 100, step: 5, unit_of_measurement: '%' }),
        'sensor.sem_battery_soc': S(65), 'sensor.sem_battery_power': S(-800, { unit_of_measurement: 'W' }),
        'sensor.sem_battery_dynamic_floor_pct': S(40),
        'select.sem_battery_mode': S('auto', { options: ['auto', 'off'] }),
        'sensor.sem_target_peak_limit': S(6.5, { unit_of_measurement: 'kW', peak_limit_unlimited: false }),
        'sensor.sem_consecutive_peak_15min': S(1.2, { unit_of_measurement: 'kW' }),
        ...extra,
    };
}

function draw(tag, states) {
    const el = new (customElements.get(tag))();
    el.setConfig({ type: `custom:${tag}` });
    el._scheduleUpdate = () => {};
    el.hass = {
        states, language: 'en', locale: { language: 'en' },
        config: { currency: 'CHF', unit_system: { temperature: '°C' }, time_zone: 'UTC' },
        callWS: async () => ({}), callService: async () => ({}),
        connection: { subscribeMessage: async () => () => {}, subscribeEvents: async () => () => {} },
    };
    el._all = true;
    return words(text(el.render()));
}

test('peak: both cards ask "Limit grid draw to" with the value the shared model reads', () => {
    const st = baseStates();
    const q = peakQuestion({ unlimited: false, limitKw: 6.5 });
    const classic = draw('sem-load-priority-card', st);
    const next = draw('sem-next-devices-card', st);
    for (const [name, out] of [['classic', classic], ['next', next]]) {
        assert.match(out, new RegExp(`${PEAK_TEXT.label} ${q.kw.toFixed(1)} kW`), `${name}: ${out.slice(0, 400)}`);
        assert.ok(out.includes(PEAK_TEXT.sub), `${name}: the limit says what it does`);
        assert.ok(!out.includes('unlimited'), `${name}: no second name for "no limit"`);
    }
});

test('peak: with no limit both cards say "No limit" and what that means', () => {
    const st = baseStates({ 'sensor.sem_target_peak_limit': S(6.5, { unit_of_measurement: 'kW', peak_limit_unlimited: true }) });
    for (const tag of ['sem-load-priority-card', 'sem-next-devices-card']) {
        const out = draw(tag, st);
        assert.ok(out.includes(PEAK_TEXT.none), `${tag}: ${out.slice(0, 400)}`);
        assert.ok(out.includes(PEAK_TEXT.subNone), tag);
    }
});

test('battery: both cards show the three levels the shared model reads, and the same now/next words', () => {
    const st = baseStates();
    const lv = batteryLevels(st);
    const says = batterySaysFromStates(st);
    const zones = draw('sem-battery-zones-card', st);
    const classic = draw('sem-battery-card', st);
    const next = draw('sem-next-devices-card', st);
    for (const id of ['priority', 'buffer', 'autostart']) {
        assert.ok(zones.includes(`${lv[id]}%`), `classic levels: ${id}`);
        assert.match(next, new RegExp(`next_zone_\\w+ ${lv[id]}\\b`), `next levels: ${id}`);
    }
    for (const [name, out] of [['classic', classic], ['next', next]]) {
        assert.ok(out.includes(says.now.key), `${name}: ${says.now.key}`);
        assert.ok(out.includes(says.next.key), `${name}: ${says.next.key}`);
    }
    // the levels are asked by their shared entities, nowhere a copy of the ids
    assert.deepEqual(BATTERY_LEVELS.map((l) => l.entity),
        ['number.sem_battery_priority_soc', 'number.sem_battery_buffer_soc', 'number.sem_battery_auto_start_soc']);
});

test('charger: both cards name the target pair "At least / Up to" and the departure "Charge by"', () => {
    const cid = 'keba';
    const te = targetEntities(cid, 'kwh');
    const st = baseStates({
        'sensor.sem_charger_keba_power': S(0, { unit_of_measurement: 'W' }),
        'select.sem_charger_keba_charge_mode': S('min_plus_solar', { options: ['off', 'solar_only', 'min_plus_solar', 'always_max'] }),
        [te.atLeast]: S(10, { min: 0, max: 100, step: 1 }), [te.upTo]: S(40, { min: 0, max: 100, step: 1 }),
        'time.sem_charger_keba_target_time': S('07:00:00'),
        'binary_sensor.sem_charger_keba_connected': S('on'),
    });
    const classic = draw('sem-ev-status-card', st);
    const next = draw('sem-next-devices-card', st);
    for (const [name, out] of [['classic', classic], ['next', next]]) {
        assert.ok(out.includes(CHARGER_TEXT.atLeast) && out.includes(CHARGER_TEXT.upTo), `${name}: the pair`);
        assert.match(out, new RegExp(`${CHARGER_TEXT.atLeast}[^0-9]{0,40}10\\b`), `${name}: at least 10`);
        assert.match(out, new RegExp(`${CHARGER_TEXT.upTo}[^0-9]{0,40}40\\b`), `${name}: up to 40`);
    }
    assert.ok(next.includes(CHARGER_TEXT.departure), 'next: the departure is "Charge by"');
    for (const old of ['next_target', 'next_departures', 'next_plan ']) assert.ok(!next.includes(old), old);
});

test('hide rules: one module answers for both cards', async () => {
    const { taxesApply, priceAddOns, loadRunsBySem } = await import('../src/util/settings-applies.js');
    const { groups } = await import('../src/util/next-settings.js');
    const t = (k) => k;
    for (const basis of ['all_in', 'spot_incl_vat', 'spot', undefined]) {
        const ctx = { options: { import_price_basis: basis, tariff_mode: 'static' }, currency: 'CHF', chargers: [] };
        const pay = groups({}, t, ctx).find((g) => g.key === 'pay');
        const asked = pay.more.filter((p) => typeof p === 'string').join('');
        assert.equal(asked.includes('next_more_vat'), taxesApply(basis), `new card, basis ${basis}`);
        assert.equal(priceAddOns(basis, 'static').vat, taxesApply(basis), `one rule, basis ${basis}`);
    }
    assert.equal(loadRunsBySem('peak_only'), false);
    const src = (f) => readFileSync(new URL(f, import.meta.url), 'utf8');
    assert.ok(src('../src/cards/sem-config-card.js').includes("from '../util/settings-applies.js'"));
    assert.ok(src('../src/util/next-settings.js').includes("from './settings-applies.js'"));
    assert.ok(src('../src/util/next-devices-load.js').includes("from './settings-applies.js'"));
});

test('plan notes: both plan cards translate the planner\'s codes through one helper', async () => {
    const { planNoteText } = await import('../src/util/plan-notes.js');
    const words = { plan_note_unpriced_slots: '{count} hours have no price yet' };
    const t = (k) => words[k] || k;
    const d = { note: '13 slot(s) unpriced — replans when the day-ahead series lands', notes: [{ code: 'unpriced_slots', params: { count: 13 } }] };
    assert.equal(planNoteText(d, t), '13 hours have no price yet');
    const src = (f) => readFileSync(new URL(f, import.meta.url), 'utf8');
    for (const f of ['../src/cards/sem-energy-plan-card.js', '../src/cards/sem-next-plan-card.js']) {
        const s = src(f);
        assert.ok(s.includes("from '../util/plan-notes.js'"), f);
        assert.ok(!s.includes('String(d.note)'), `${f}: no English planner note printed as is`);
    }
});

test('charger: both cards take the "why" line from the shared chargerSays', async () => {
    const { chargerSays } = await import('../src/util/charger-questions.js');
    const words = { charge_mode_min_plus_solar: 'Min + Solar', why_reason_surplus: 'It runs on spare sun.' };
    const t = (k) => words[k] || k;
    const { plainReason } = await import('../src/util/why-rows.js');
    const st = { 'sensor.sem_charging_strategy': S('min_plus_solar charging', { reason: 'min_plus_solar charging', reason_code: 'surplus', reason_params: {} }) };
    assert.deepEqual(chargerSays(st, t, plainReason), { title: 'Min + Solar', text: 'It runs on spare sun.' });
    assert.equal(chargerSays({}, t, plainReason), null);
    const src = (f) => readFileSync(new URL(f, import.meta.url), 'utf8');
    for (const f of ['../src/cards/sem-ev-status-card.js', '../src/cards/sem-next-now-card.js']) {
        assert.ok(src(f).includes('chargerSays('), f);
    }
    assert.ok(!src('../src/cards/sem-next-now-card.js').includes('strategyWords('), 'no second path in the new Now card');
});

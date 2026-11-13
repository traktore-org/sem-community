/**
 * #830 — Everyday shows the essential list, and only that.
 *
 * The Configuration tab has two views on one switch: Everyday (the default)
 * and All settings. Only some row helpers used to ask whether a row belongs
 * in Everyday; the battery knobs, the entity toggles and selects, every
 * per-charger row and the free-text rows did not. A home with a battery and
 * one charger saw 20 setting rows in the "small" view.
 *
 * Rows are counted from the rendered templates (picker, stepper, knob and
 * text-input cells), not from the helpers, so a new helper that forgets to
 * ask is counted too.
 *
 * The real card code runs here; lit is replaced by a stub that keeps the
 * template parts (CI runs `node --test` with no node_modules).
 *
 * Run: `npm test` (from dashboard/card).
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';

const FAKE_LIT = `
export class LitElement {
    constructor() { this.style = {}; this.renderRoot = { querySelector: () => null, querySelectorAll: () => [] }; }
    connectedCallback() {}
    disconnectedCallback() {}
    requestUpdate() {}
    updated() {}
    get updateComplete() { return Promise.resolve(true); }
}
export const html = (strings, ...values) => ({ tpl: true, strings: [...strings], values });
export const css = () => '', svg = html;
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

const listeners = new Map();
const events = [];
const store = new Map();
globalThis.window = globalThis;
globalThis.document = {
    addEventListener() {}, removeEventListener() {},
    documentElement: {}, head: { appendChild() {} }, createElement: () => ({}),
};
globalThis.addEventListener = (type, fn) => {
    if (!listeners.has(type)) listeners.set(type, new Set());
    listeners.get(type).add(fn);
};
globalThis.removeEventListener = (type, fn) => { listeners.get(type)?.delete(fn); };
globalThis.dispatchEvent = (ev) => {
    events.push(ev);
    for (const fn of listeners.get(ev.type) || []) fn(ev);
    return true;
};
const registry = new Map();
globalThis.customElements = { get: (t) => registry.get(t), define: (t, c) => registry.set(t, c) };
globalThis.getComputedStyle = () => ({ getPropertyValue: () => '' });
globalThis.localStorage = {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => { store.set(k, String(v)); },
};
globalThis.navigator ??= {};

const viewMode = await import('../src/util/view-mode.js');
await import('../src/cards/sem-config-card.js');

// ── a home with a battery and one charger, static tariff ──
const knob = (state, min = 0, max = 100) => ({ state: String(state), attributes: { min, max, step: 1 } });
const STATES = {
    'sensor.sem_battery_soc': { state: '55', attributes: {} },
    'sensor.sem_battery_power': { state: '0', attributes: {} },
    'sensor.sem_charging_state': { state: 'idle', attributes: {} },
    'number.sem_battery_priority_soc': knob(20),
    'number.sem_battery_buffer_soc': knob(40),
    'number.sem_battery_auto_start_soc': knob(80),
    'number.sem_battery_assist_min_surplus': knob(500, 0, 5000),
    'number.sem_battery_assist_max_power': knob(3000, 0, 10000),
    'number.sem_battery_max_discharge_power': knob(5000, 0, 10000),
    'number.sem_cheap_price_threshold': knob(10),
    'number.sem_expensive_price_threshold': knob(30),
    'number.sem_charger_ev1_minimum_current': { state: '6', attributes: { min: 6, max: 32, step: 1, friendly_name: 'Wallbox Min Amps' } },
    'number.sem_charger_ev1_maximum_current': knob(16, 6, 32),
    'number.sem_charger_ev1_daily_ev_target': knob(10),
    'number.sem_charger_ev1_daily_ev_target_max': knob(40),
    'number.sem_charger_ev1_ev_battery_capacity_kwh': knob(60),
    'number.sem_charger_ev1_ev_kwh_per_100km': knob(18),
    'number.sem_charger_ev1_ev_phases': knob(3, 1, 3),
    // Fine-tuning and device entities, so All settings has rows there too.
    'switch.sem_forecast_spending_enabled': { state: 'off', attributes: {} },
    'switch.sem_observer_mode': { state: 'off', attributes: {} },
    'select.sem_hints': { state: 'off', attributes: { options: ['off', 'weekly', 'all'] } },
    'number.sem_update_interval': knob(10, 5, 60),
};
const OPTIONS = {
    tariff_mode: 'static',
    electricity_import_rate: 0.3,
    ev_chargers: [{
        id: 'ev1', name: 'Wallbox',
        ev_charging_power_sensor: 'sensor.wallbox_power',
        ev_current_control_entity: 'number.wallbox_current',
        ev_connected_sensor: 'binary_sensor.wallbox_plug',
    }],
};

function card({ advanced = false, options = OPTIONS, states = STATES } = {}) {
    const el = new (customElements.get('sem-config-card'))();
    el.setConfig({});
    el._advanced = advanced;
    el._options = JSON.parse(JSON.stringify(options));
    el._entryId = 'entry1';
    el._hass = {
        states, config: { currency: 'EUR' }, language: 'en', services: {},
        callService: async () => {}, callWS: async () => [],
    };
    return el;
}

// A setting row is a template that draws one of the row cells.
const ROW_MARKERS = ['class="picker-cell', 'class="stepper-cell', 'class="zone-knob', 'class="txt-opt', 'class="pv-name-input'];
function countRows(node) {
    if (Array.isArray(node)) return node.reduce((n, v) => n + countRows(v), 0);
    if (!node || !node.tpl) return 0;
    const own = ROW_MARKERS.some((m) => node.strings.join('').includes(m)) ? 1 : 0;
    return own + node.values.reduce((n, v) => n + countRows(v), 0);
}
function findTemplates(node, marker, out = []) {
    if (Array.isArray(node)) { node.forEach((v) => findTemplates(v, marker, out)); return out; }
    if (!node || !node.tpl) return out;
    if (node.strings.join('').includes(marker)) out.push(node);
    node.values.forEach((v) => findTemplates(v, marker, out));
    return out;
}
const text = (node) => (Array.isArray(node) ? node.map(text).join('')
    : node && node.tpl ? node.strings.map((s, i) => s + (i < node.values.length ? text(node.values[i]) : '')).join('')
    : typeof node === 'string' ? node : '');

// Render the whole tab and record the rows each section drew.
function renderTab(el) {
    const per = {};
    const real = el._renderSection.bind(el);
    el._renderSection = (section, fn, T) => {
        const out = real(section, fn, T);
        per[section.id] = countRows(out);
        return out;
    };
    const tree = el.render();
    return { tree, per, total: Object.values(per).reduce((a, b) => a + b, 0) };
}

test('battery + one charger: Everyday shows 6 setting rows, not 20', () => {
    const { per, total } = renderTab(card());
    assert.deepEqual(per, { overview: 0, tariff: 3, ev_chargers: 2, battery_zones: 1, sensor_sources: 0 });
    assert.equal(total, 6);
});

test('All settings still shows every row', () => {
    // 97 rows on this home, as before the Everyday filter was closed;
    // (#1077) +6 for the value fields (preset, price basis, fee model, and
    // markup, tax and VAT, greyed out on an all-in price); the fee amount
    // and tiers show only for their model.
    // (#1090) +1 for the export threshold.
    // (#812) +3 for the heat pump's own tariff (rate, price entity, meter).
    // (#1166) +1 for the battery's own end-of-charge level.
    // (#1079) +2 for "Steered by another party": the battery's and the
    // charger's mode select (the indicator picker shows only when a mode is set).
    // (#1308) +1 for the charger's Finish by departure toggle.
    // (#1323) +1 for the heat pump's Step down when power is short.
    // (#1354) −3: markup, tax and VAT are not asked beside an all-in price
    // (they were greyed out); a spot price shows them again, see below.
    // (#1354) −1: "No grid limit" and the limit are one question.
    const everyday = renderTab(card()).total;
    const { per, total } = renderTab(card({ advanced: true }));
    assert.equal(total, 108, `All settings drew ${total} rows`);
    assert.ok(per.battery_zones >= 9, 'battery knobs and pickers');
    assert.ok(per.ev_chargers >= 15, 'every per-charger row');
    assert.ok(total > everyday * 5);
});

test('a spot price asks markup, tax and VAT again', () => {
    const allIn = renderTab(card({ advanced: true })).per.tariff;
    const spot = renderTab(card({ advanced: true, options: { ...OPTIONS, import_price_basis: 'spot' } })).per.tariff;
    assert.equal(spot - allIn, 3);
});

test('the charger keeps its power and its control in Everyday', () => {
    const el = card();
    const seen = [];
    const real = el._renderPickerNested.bind(el);
    el._renderPickerNested = (i, cid, key, ...rest) => {
        const out = real(i, cid, key, ...rest);
        if (out !== undefined && typeof out !== 'symbol') seen.push(key);
        return out;
    };
    el._renderEvChargers(new Proxy({}, { get: () => '' }));
    assert.deepEqual(seen, ['ev_charging_power_sensor', 'ev_current_control_entity']);
});

// Each formerly unfiltered helper, one by one: hidden in Everyday, shown in
// All settings.
const CASES = [
    ['_renderZoneKnob', (el) => el._renderZoneKnob('number.sem_battery_priority_soc', 'priority_soc', {}, '')],
    ['_renderStepper', (el) => el._renderStepper('number.sem_charger_ev1_ev_phases', 'config_ev_phases', {}, '')],
    ['_renderToggle', (el) => el._renderToggle('switch.sem_observer_mode', 'observer_mode', {}, '')],
    ['_renderSelect', (el) => el._renderSelect('select.sem_hints', 'hints', {}, '')],
    ['_renderTextOption', (el) => el._renderTextOption('battery_setpoint_model', 'config_setpoint_model', el._options, '', 'signed')],
    ['_renderBatteryListPicker', (el) => el._renderBatteryListPicker('battery_strategy_entities', 'config_strategy_entity', ['select'], 0, 2, el._options)],
    ['_renderPickerNested', (el) => el._renderPickerNested(0, 'ev1', 'vehicle_soc_entity', 'config_ev_vehicle_soc', 'sensor', null, el._options, '')],
    ['_renderToggleNested', (el) => el._renderToggleNested(0, 'ev1', 'ev_phase_switching_enabled', 'config_ev_phase_switching', el._options, '')],
    ['_renderTextNested', (el) => el._renderTextNested(0, 'ev1', 'ev_charge_mode_start', 'config_ev_charge_mode_start', el._options, '', '')],
    ['_renderTargetTypeSelectNested', (el) => el._renderTargetTypeSelectNested(0, 'ev1', el._options.ev_chargers[0], el._options)],
    ['_renderPicker', (el) => el._renderPicker('battery_soc_sensor', 'config_battery_soc_sensor', 'sensor', null, el._options, '')],
    ['_renderOptionToggle', (el) => el._renderOptionToggle('peak_limit_unlimited', 'config_lm_unlimited', el._options, '', false)],
    ['_renderOptionSelect', (el) => el._renderOptionSelect('solar_forecast_source', 'x', [], el._options, '', 'auto')],
    ['_renderOptionNumberInput', (el) => el._renderOptionNumberInput('grid_import_surcharge', 'x', { min: 0, max: 1, step: 0.1, default: 0 }, el._options, '')],
    ['_renderOptionTextInput', (el) => el._renderOptionTextInput('heat_pump_relay1_on_value', 'x', el._options, '', '')],
    ['_renderOptionSlider', (el) => el._renderOptionSlider('vpp_reserve_soc', 'x', { min: 0, max: 80, step: 5, default: 20 }, el._options, '')],
    ['_renderGridSignFix', (el) => el._renderGridSignFix({})],
    ['_renderPvStrings', (el) => el._renderPvStrings({})],
];
for (const [name, call] of CASES) {
    test(`${name} respects Everyday`, () => {
        const hidden = call(card());
        assert.equal(typeof hidden, 'symbol', `${name} drew a row in Everyday`);
        const shown = call(card({ advanced: true }));
        assert.ok(shown && shown.tpl, `${name} drew nothing in All settings`);
    });
}

test('the essential controls still render in Everyday', () => {
    const el = card();
    const opts = el._options;
    assert.ok(el._renderOptionSelect('tariff_mode', 'x', [], opts, '', 'static').tpl);
    assert.ok(el._renderOptionToggle('battery_discharge_protection_enabled', 'x', opts, '', true).tpl);
    assert.ok(el._renderPickerNested(0, 'ev1', 'ev_current_control_entity', 'x', 'number', null, opts, '').tpl);
});

test('a section with nothing essential says so and offers the rest', () => {
    const el = card({ options: { ...OPTIONS, hot_water_entity: 'switch.boiler' } });
    const { tree, per } = renderTab(el);
    assert.equal(per.hot_water, 0, 'hot water is set up, so it shows, with no rows');
    const more = findTemplates(tree, 'class="everyday-more"');
    const hw = more.find((t) => text(t).includes('config_everyday_nothing_here'));
    assert.ok(hw, 'no one-line summary for a section with no essential row');
    assert.match(text(hw), /config_more_in_all/);
});

test('"N more in All settings" counts the hidden rows and turns the switch on', () => {
    const el = card();
    let rows;
    const real = el._renderEverydayMore.bind(el);
    el._renderEverydayMore = (r) => { rows = { ...r }; return real(r); };
    el._renderSection({ id: 'battery_zones', color: '', icon: '', titleKey: 't', subtitleFn: () => '' },
        (T) => el._renderBatteryZones(T), new Proxy({}, { get: () => '' }));
    // six knobs + four pickers hidden (#1166: the end-of-charge level),
    // plus the external-control mode select (#1079); the protection toggle shown
    assert.deepEqual(rows, { shown: 1, hidden: 11 });
    const btn = findTemplates(real(rows), 'class="everyday-more-btn"')[0];
    assert.ok(btn);
    store.clear();
    btn.values.find((v) => typeof v === 'function')();
    assert.equal(el._advanced, true);
    assert.equal(store.get(viewMode.VIEW_MODE_KEY), '1');
});

test('Fine-tuning folds to one line in Everyday', () => {
    const { tree, per } = renderTab(card());
    for (const id of ['battery_scheduler', 'battery_intelligence', 'forecast', 'notifications', 'advanced']) {
        assert.equal(per[id], undefined, `${id} rendered in Everyday`);
    }
    const folded = findTemplates(tree, 'class="group-folded"');
    assert.equal(folded.length, 1);
    assert.match(text(folded[0]), /config_finetuning_folded/);
    const headings = findTemplates(tree, 'class="group-heading"').map(text);
    assert.ok(headings.some((h) => h.includes('config_group_basics')));
    assert.ok(headings.some((h) => h.includes('config_group_finetuning')));
});

test('a Fine-tuning section with unsaved edits shows in Everyday', () => {
    const el = card();
    el._secOf['switch.sem_observer_mode'] = 'advanced';
    el._staged = { 'switch.sem_observer_mode': { kind: 'switch', value: 'on' } };
    const { per } = renderTab(el);
    assert.notEqual(per.advanced, undefined);
    assert.equal(per.battery_scheduler, undefined);
});

test('All settings shows the three groups unfolded', () => {
    const { tree, per } = renderTab(card({ advanced: true }));
    assert.equal(findTemplates(tree, 'class="group-folded"').length, 0);
    assert.equal(findTemplates(tree, 'class="group-heading"').length, 3);
    assert.ok('advanced' in per && 'forecast' in per && 'sensor_sources' in per);
});

// ── the shared switch (util/view-mode.js) ──

test('view-mode: the key the Configuration tab has always used, as "1" / "0"', () => {
    assert.equal(viewMode.VIEW_MODE_KEY, 'sem_config_advanced_v1');
    store.clear();
    assert.equal(viewMode.getAllSettings(), false);
    store.set(viewMode.VIEW_MODE_KEY, '1');
    assert.equal(viewMode.getAllSettings(), true);
    store.set(viewMode.VIEW_MODE_KEY, '0');
    assert.equal(viewMode.getAllSettings(), false);
});

test('view-mode: setting it stores it and tells the other cards', () => {
    store.clear();
    events.length = 0;
    viewMode.setAllSettings(true);
    assert.equal(store.get(viewMode.VIEW_MODE_KEY), '1');
    assert.equal(events.at(-1).type, viewMode.VIEW_MODE_EVENT);
    assert.deepEqual(events.at(-1).detail, { all: true });
    viewMode.setAllSettings(false);
    assert.equal(store.get(viewMode.VIEW_MODE_KEY), '0');
    assert.deepEqual(events.at(-1).detail, { all: false });
});

test('view-mode: blocked storage reads Everyday and still announces', () => {
    const saved = globalThis.localStorage;
    globalThis.localStorage = { getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); } };
    try {
        events.length = 0;
        assert.equal(viewMode.getAllSettings(), false);
        viewMode.setAllSettings(true);
        assert.deepEqual(events.at(-1).detail, { all: true });
    } finally {
        globalThis.localStorage = saved;
    }
});

test('the card starts in the stored view and follows the switch from other cards', () => {
    store.set(viewMode.VIEW_MODE_KEY, '1');
    const el = new (customElements.get('sem-config-card'))();
    assert.equal(el._advanced, true, 'a stored "All settings" is lost');
    el.connectedCallback();
    viewMode.setAllSettings(false);
    assert.equal(el._advanced, false, 'the card missed the event');
    el.disconnectedCallback();
    viewMode.setAllSettings(true);
    assert.equal(el._advanced, false, 'a detached card still listens');
});

test('the segmented switch picks a view and stores it', () => {
    store.clear();
    const el = card();
    el._setView(true);
    assert.equal(el._advanced, true);
    assert.equal(store.get(viewMode.VIEW_MODE_KEY), '1');
    el._setView(false);
    assert.equal(el._advanced, false);
    assert.equal(store.get(viewMode.VIEW_MODE_KEY), '0');
});

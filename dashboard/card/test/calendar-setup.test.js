/**
 * #1040 — Calendar mode, set up from the Config tab's default view.
 *
 * The mode prices each hour at one of two rates: the import rate inside the
 * Schedule helper's blocks, the off-peak rate outside them. Two users chose
 * Calendar, picked a helper and read "no price difference":
 *
 *  - the off-peak rate was hidden until Advanced was turned on, so the mode
 *    had one visible price (@lostcontrol, @mdscgan);
 *  - the Peak-time schedule waited, unsaved, for a bar at the top of the
 *    card. Its own section said nothing was unsaved and offered no Apply.
 *
 * The real card code runs here; lit is replaced by a stub (CI runs
 * `node --test` with no node_modules).
 *
 * Run: `npm test` (from dashboard/card).
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';
import { readFileSync } from 'node:fs';

const FAKE_LIT = `
export class LitElement {
    constructor() { this.style = {}; this.renderRoot = { querySelector: () => null, querySelectorAll: () => [] }; }
    connectedCallback() {}
    disconnectedCallback() {}
    requestUpdate() {}
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

globalThis.window = globalThis;
globalThis.document = {
    addEventListener() {}, removeEventListener() {},
    documentElement: {}, head: { appendChild() {} }, createElement: () => ({}),
};
globalThis.addEventListener = () => {};
globalThis.removeEventListener = () => {};
const registry = new Map();
globalThis.customElements = { get: (t) => registry.get(t), define: (t, c) => registry.set(t, c) };
globalThis.getComputedStyle = () => ({ getPropertyValue: () => '' });
globalThis.localStorage = { getItem: () => null, setItem() {} };
globalThis.navigator ??= {};

await import('../src/cards/sem-config-card.js');

const HELPER = 'schedule.octopus_ht';
const T = new Proxy({}, { get: () => '' });
const TARIFF = { id: 'tariff', color: '', titleKey: 'config_section_tariff', subtitleFn: () => '' };
const SOURCES = { id: 'sensor_sources', color: '', titleKey: 'config_section_sensor_sources', subtitleFn: () => '' };

function card(options, { advanced = false } = {}) {
    const el = new (customElements.get('sem-config-card'))();
    el.setConfig({});
    el._advanced = advanced;
    el._options = { ...options };
    el._entryId = 'entry1';
    el.calls = [];
    el._hass = {
        states: {}, config: { currency: 'EUR' }, language: 'en',
        callService: async (domain, service, data) => { el.calls.push({ domain, service, data }); },
        callWS: async () => [],
    };
    return el;
}

// Render the Tariff section the way render() does, so every row binds itself
// to the section (and a hidden row does not).
function renderTariff(el) {
    el._renderSection(TARIFF, (t) => el._renderTariff(t), T);
}

test('Calendar: the default view shows the off-peak rate', () => {
    assert.equal(card({ tariff_mode: 'calendar' })._showsControl('electricity_off_peak_rate'), true);
});

test('Static and Dynamic: the default view still shows one rate', () => {
    assert.equal(card({ tariff_mode: 'static' })._showsControl('electricity_off_peak_rate'), false);
    assert.equal(card({})._showsControl('electricity_off_peak_rate'), false);
    assert.equal(card({ tariff_mode: 'dynamic' })._showsControl('electricity_off_peak_rate'), false);
    assert.equal(card({ tariff_mode: 'static' })._showsControl('electricity_import_rate'), true);
});

test('Advanced still shows the off-peak rate in every mode', () => {
    for (const mode of ['static', 'dynamic', 'calendar']) {
        assert.equal(card({ tariff_mode: mode }, { advanced: true })
            ._showsControl('electricity_off_peak_rate'), true, mode);
    }
});

test('picking Calendar shows its fields before Apply', () => {
    const el = card({ tariff_mode: 'static' });
    el._pickTariffMode('calendar');
    assert.equal(el._tariffMode(), 'calendar');
    assert.equal(el._showsControl('electricity_off_peak_rate'), true);
    renderTariff(el);
    assert.equal(el._secOf['pending:tariff_schedule_entity'], 'tariff',
        'the Peak-time schedule did not render for the picked mode');
    assert.equal(el._secOf['opt:electricity_off_peak_rate'], 'tariff',
        'the off-peak rate did not render for the picked mode');
});

test('a Static page does not render the Calendar fields', () => {
    const el = card({ tariff_mode: 'static' });
    renderTariff(el);
    assert.equal(el._secOf['pending:tariff_schedule_entity'], undefined);
    assert.equal(el._secOf['opt:electricity_off_peak_rate'], undefined);
});

test('the Tariff section counts a picked schedule as unsaved', () => {
    const el = card({ tariff_mode: 'calendar' });
    renderTariff(el);
    assert.equal(el._sectionUnsaved('tariff'), 0);
    el._pending = { [`tariff_schedule_entity`]: HELPER };
    assert.equal(el._sectionUnsaved('tariff'), 1);
    assert.deepEqual(el._sectionPending('tariff'), ['tariff_schedule_entity']);
});

test("the section's Apply saves the schedule, with the rest, in one call", async () => {
    const el = card({ tariff_mode: 'static' });
    el._pickTariffMode('calendar');
    renderTariff(el);
    el._stage('opt:electricity_off_peak_rate', 'option', 0.22);
    el._pending = { tariff_schedule_entity: HELPER };
    assert.equal(el._sectionUnsaved('tariff'), 3);
    await el._applySection('tariff');
    const sets = el.calls.filter((c) => c.service === 'set_option');
    assert.equal(sets.length, 1, 'one call, so the entry reloads once');
    assert.deepEqual(sets[0].data.options, {
        tariff_mode: 'calendar', electricity_off_peak_rate: 0.22, tariff_schedule_entity: HELPER,
    });
    assert.equal(sets[0].data.entry_id, 'entry1');
    assert.deepEqual(el._pending, {});
    assert.deepEqual(el._staged, {});
    assert.equal(el._options.tariff_schedule_entity, HELPER);
    assert.equal(el._sectionUnsaved('tariff'), 0);
});

test('a failed Apply keeps the schedule waiting', async () => {
    const el = card({ tariff_mode: 'calendar' });
    renderTariff(el);
    el._pending = { tariff_schedule_entity: HELPER };
    el._hass.callService = async () => { throw new Error('nope'); };
    await el._applySection('tariff');
    assert.deepEqual(el._pending, { tariff_schedule_entity: HELPER });
    assert.equal(el._saveStatus._sec_tariff, 'nope');
});

test("the section's Revert drops the schedule too", () => {
    const el = card({ tariff_mode: 'calendar' });
    renderTariff(el);
    el._pending = { tariff_schedule_entity: HELPER };
    el._revertSection('tariff');
    assert.deepEqual(el._pending, {});
});

test("one section's Apply leaves another section's edit waiting", async () => {
    const el = card({ tariff_mode: 'calendar' }, { advanced: true });
    renderTariff(el);
    el._renderSection(SOURCES, () => el._renderPicker('grid_power_sensor',
        'config_grid_power_sensor', 'sensor', 'power', el._options, ''), T);
    el._pending = { tariff_schedule_entity: HELPER, grid_power_sensor: 'sensor.grid' };
    assert.equal(el._sectionUnsaved('tariff'), 1);
    assert.equal(el._sectionUnsaved('sensor_sources'), 1);
    await el._applySection('tariff');
    assert.deepEqual(el.calls[0].data.options, { tariff_schedule_entity: HELPER });
    assert.deepEqual(el._pending, { grid_power_sensor: 'sensor.grid' },
        'the bar at the top still holds the other edit');
});

test('a structural toggle belongs to its section as well', () => {
    const el = card({ tariff_mode: 'calendar' }, { advanced: true });
    el._renderSection(TARIFF, () => el._renderOptionToggle('battery_setpoint_bidirectional',
        'config_battery_bidirectional', el._options, '', false), T);
    el._pending = { battery_setpoint_bidirectional: true };
    assert.deepEqual(el._sectionPending('tariff'), ['battery_setpoint_bidirectional']);
});

test('going back to Static drops the Calendar edits', async () => {
    const el = card({ tariff_mode: 'static' });
    el._pickTariffMode('calendar');
    renderTariff(el);
    el._stage('opt:electricity_off_peak_rate', 'option', 0.22);
    el._pending = { tariff_schedule_entity: HELPER };
    assert.equal(el._sectionUnsaved('tariff'), 3);
    el._pickTariffMode('static');                 // back to the saved mode
    renderTariff(el);
    assert.equal(el._sectionUnsaved('tariff'), 0, 'hidden fields are still unsaved');
    assert.deepEqual(el._pending, {});
    await el._applySection('tariff');
    assert.equal(el.calls.length, 0, 'Apply saved fields the page no longer shows');
});

test('leaving Dynamic drops its unsaved price grouping', () => {
    const el = card({ tariff_mode: 'dynamic' });
    renderTariff(el);
    el._stage('opt:tariff_classification_mode', 'option', 'static');
    el._pickTariffMode('calendar');
    assert.equal(el._isDirty('opt:tariff_classification_mode'), false);
});

test('in Advanced the off-peak rate stays, so its edit stays', () => {
    const el = card({ tariff_mode: 'calendar' }, { advanced: true });
    renderTariff(el);
    el._stage('opt:electricity_off_peak_rate', 'option', 0.22);
    el._pickTariffMode('static');
    assert.equal(el._isDirty('opt:electricity_off_peak_rate'), true);
    assert.equal(el._sectionUnsaved('tariff'), 2);   // the mode and the rate
});

test('an edit hidden by turning Advanced off still counts and saves', async () => {
    // Only a mode change drops edits. Hiding a row by view keeps it on the
    // section's count, so nothing waits without the user seeing a number.
    const el = card({ tariff_mode: 'static' }, { advanced: true });
    renderTariff(el);
    el._stage('opt:demand_charge_rate', 'option', 5);
    el._advanced = false;
    renderTariff(el);
    assert.equal(el._sectionUnsaved('tariff'), 1);
    await el._applySection('tariff');
    assert.deepEqual(el.calls[0].data.options, { demand_charge_rate: 5 });
});

test('the mode select picks through _pickTariffMode', () => {
    const src = readFileSync(new URL('../src/cards/sem-config-card.js', import.meta.url), 'utf8');
    assert.match(src, /_renderOptionSelect\('tariff_mode',[^;]*?\(m\) => this\._pickTariffMode\(m\)\)/s);
    assert.match(src, /onPick\s*\?\s*onPick\(e\.target\.value\)/);
});

test('an unsaved off-peak rate shows the import rate', () => {
    const el = card({ tariff_mode: 'calendar', electricity_import_rate: 0.25 });
    const seen = [];
    const real = el._renderOptionNumberInput.bind(el);
    el._renderOptionNumberInput = (key, label, cfg, opts, help) => {
        if (key === 'electricity_off_peak_rate') seen.push(cfg.default);
        return real(key, label, cfg, opts, help);
    };
    renderTariff(el);
    assert.deepEqual(seen, [0.25]);
    el._options = { tariff_mode: 'calendar', electricity_import_rate: 0.25, electricity_nt_rate: 0.2 };
    renderTariff(el);
    assert.deepEqual(seen, [0.25, 0.2]);
});

test('the two Apply buttons wait for each other', async () => {
    const el = card({ tariff_mode: 'calendar' });
    renderTariff(el);
    el._pending = { tariff_schedule_entity: HELPER };
    el._secApplying = 'tariff';
    await el._applyPending();
    el._secApplying = '';
    el._applying = true;
    await el._applySection('tariff');
    assert.equal(el.calls.length, 0);
    assert.deepEqual(el._pending, { tariff_schedule_entity: HELPER });
});

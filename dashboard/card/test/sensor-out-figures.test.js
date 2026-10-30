/**
 * #1200 — a card must not print 0 for a sensor that is out.
 *
 * Each card kept a small reader, `_val(suffix, fallback = 0)`, that handed
 * back 0 for an unavailable or unknown sensor, and the card printed it: the
 * EV card read "0 W" for a charger power that was out, the same as a car that
 * is not charging; the battery card "0%" health and "0.00 kWh" for the day.
 * `parseFloat(state) ?? fallback` let a state that is no number through as
 * NaN. Found while fixing the tab header (#1198, class 164).
 *
 * Every card in src/cards is drawn here with every SEM sensor out. It may
 * print only the numbers listed for it below: settings, counts and labels,
 * never a sensor's fallback. A new card, or a new figure that prints its
 * fallback, fails here.
 *
 * The real card code runs here; lit is replaced by a stub that keeps the
 * template parts (CI runs `node --test` with no node_modules).
 *
 * Run: `npm test` (from dashboard/card).
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';
import { readdirSync, readFileSync } from 'node:fs';

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
        part.strings.forEach((s, i) => {
            out += s;
            if (i < part.values.length) out += text(part.values[i]);
        });
        return out;
    }
    if (typeof part === 'function') return '';
    return String(part);
}
const words = (s) => s
    .replace(/<style[\s\S]*?<\/style>/g, ' ')
    .replace(/<!--[\s\S]*?-->/g, ' ')
    .replace(/<[^>]*>/g, ' ')
    .replace(/&nbsp;/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
// Every number a person reads: "0", "0.00", "+56", "−3" — not the 1 in "PV1".
const numbers = (s) => [...s.matchAll(/(?<![\w.])[+\-−]?\d+(?:[.,]\d+)?(?![\w])/g)].map((m) => m[0]);

const CARDS = readdirSync(new URL('../src/cards/', import.meta.url))
    .filter((f) => f.startsWith('sem-') && f.endsWith('.js'))
    .map((f) => f.replace(/\.js$/, ''));
for (const c of CARDS) await import(`../src/cards/${c}.js`);

// A card that needs a config to draw at all gets one.
const CONFIG = {
    'sem-flow-card': { entity_prefix: 'sensor.sem_' },
    'sem-gauge-card': { entity: 'sensor.sem_battery_soc' },
    'sem-chart-card': { preset: 'power' },
    'sem-weather-card': { entity: 'weather.home' },
};

// Every SEM sensor reads `state`; settings (number, select, switch) are not
// there, so a card shows its own default for them. A charger and a battery
// exist. `state === undefined`: no SEM sensor exists at all.
function hassWith(state) {
    const base = {};
    if (state !== undefined) {
        for (const id of DISCOVERY) base[id] = { entity_id: id, state, attributes: {} };
    }
    const states = new Proxy(base, {
        get(t, k) {
            if (typeof k !== 'string') return undefined;
            if (k in t) return t[k];
            if (state !== undefined && k.startsWith('sensor.')) return { entity_id: k, state, attributes: {} };
            return undefined;
        },
    });
    return {
        states, language: 'en', locale: { language: 'en' },
        config: { currency: 'EUR', unit_system: { temperature: '°C' }, time_zone: 'UTC' },
        callWS: async () => ({}), callService: async () => ({}),
        connection: { subscribeMessage: async () => () => {}, subscribeEvents: async () => () => {} },
    };
}
const DISCOVERY = ['sensor.sem_charger_keba_power', 'sensor.sem_battery_b1_power',
    'sensor.sem_battery_power', 'sensor.sem_solar_power', 'sensor.sem_ev_power'];

function card(tag, hass) {
    const el = new (customElements.get(tag))();
    el.setConfig({ type: `custom:${tag}`, ...(CONFIG[tag] || {}) });
    el._scheduleUpdate = () => {};
    el.hass = hass;
    return el;
}
const draw = (tag, state) => words(text(card(tag, hassWith(state)).render()));
const dashes = (s) => s.split('—').length - 1;

// The numbers a card may print with every SEM sensor out: settings shown with
// their own default (no number entity here), counts, labels, the hours of a
// day. Never a sensor's fallback.
const ALLOWED_OUT = {
    'sem-battery-card': [],
    'sem-battery-zones-card': [],
    'sem-charger-status-card': ['1'],                          // chargers found
    'sem-chart-card': [],
    'sem-config-card': ['0', '33', '0'],                       // counts, setup steps done
    'sem-control-card': ['551', '60', '385', '1', '60', '5019', '60', '70', '3'],  // the hot-water norms
    'sem-costs-card': [],
    'sem-costs-detail-card': [],
    'sem-diagnose-button': [],
    'sem-energy-impact-card': [],
    'sem-energy-plan-card': [],
    'sem-ev-progress-card': ['10.0'],                          // daily target setting
    'sem-ev-status-card': ['10', '40', '6', '18', '100'],      // charger settings
    'sem-flow-card': [],
    'sem-gauge-card': [],
    'sem-grid-card': [],
    'sem-home-status-card': [],
    'sem-load-priority-card': [],
    'sem-onboarding-banner': [],
    'sem-period-selector-card': [],
    'sem-price-card': [],
    'sem-schedule-card': ['00', '02', '04', '06', '08', '10', '12', '14', '16', '18', '20', '22', '24'],
    'sem-simulation-card': ['0'],                              // days stored, from its own query
    'sem-solar-card': [],
    'sem-solar-kpi-card': [],
    'sem-solar-summary-card': [],
    'sem-system-card': [],
    'sem-system-diagram-card': ['6'],                          // "⚠ 6 sensors unavailable"
    'sem-tab-header': [],
    'sem-title-card': [],
    'sem-today-plan-card': [],
    'sem-weather-card': [],
    'sem-why-card': [],
};
// The dashes a card prints with every sensor reading: the settings, times and
// query results that are not here. A sensor that reads never prints the dash.
const DASHES_WITH_READINGS = {
    'sem-battery-card': 1,        // "until full": a full pack has no time left
    'sem-grid-card': 1,           // export, while importing
    'sem-battery-zones-card': 6, 'sem-control-card': 1, 'sem-costs-detail-card': 1,
    'sem-ev-status-card': 1, 'sem-price-card': 3, 'sem-schedule-card': 1,
    'sem-simulation-card': 2,
    // drawn before the first update writes its labels (tested below)
    'sem-flow-card': 6,
};
const DRAWN = CARDS.filter((t) => typeof customElements.get(t) === 'function');

test('every card is listed: a new card says what it prints', () => {
    assert.deepEqual([...DRAWN].sort(), Object.keys(ALLOWED_OUT).sort());
});

for (const tag of DRAWN) {
    test(`${tag}: a sensor that is out prints no number`, () => {
        for (const state of ['unavailable', 'unknown', 'n/a', 'nan', '']) {
            const out = draw(tag, state);
            assert.doesNotMatch(out, /NaN|undefined|null|Infinity/, `${state}: ${out}`);
            assert.deepEqual(numbers(out), ALLOWED_OUT[tag], `"${state}": ${out}`);
        }
        // No sensor at all: fewer sections, and still no fallback. The
        // charger count is then 0.
        const none = numbers(draw(tag, undefined));
        const may = [...ALLOWED_OUT[tag], ...(tag === 'sem-charger-status-card' ? ['0'] : [])];
        for (const n of none) assert.ok(may.includes(n), `missing: ${n}`);
    });

    test(`${tag}: a sensor that reads never prints the dash`, () => {
        const out = draw(tag, '1234');
        assert.doesNotMatch(out, /NaN|undefined|null|Infinity/, out);
        assert.equal(dashes(out), DASHES_WITH_READINGS[tag] ?? 0, out);
    });
}

// ── The readers ────────────────────────────────────────────────────────────

const { readNumber, fmtValue, MISSING } = await import('../src/util/missing-value.js');
const { importKw } = await import('../src/util/peak-slot.js');

test('readNumber: a number, or null when the sensor gives none', () => {
    const st = (state) => ({ state });
    assert.equal(readNumber(st('12.5')), 12.5);
    assert.equal(readNumber(st('0')), 0, 'a real 0 is a reading');
    assert.equal(readNumber(st('-300')), -300);
    for (const s of ['unavailable', 'unknown', '', 'n/a', 'nan', 'NaN', 'Infinity', 'none']) {
        assert.equal(readNumber(st(s)), null, s);
    }
    assert.equal(readNumber(undefined), null);
    assert.equal(fmtValue(null, 1), MISSING);
    assert.equal(fmtValue(NaN, 1), MISSING);
    assert.equal(fmtValue(0, 1), '0.0');
    assert.equal(importKw(''), null, 'an empty state imports nothing known');
    assert.equal(importKw('-1500'), 1.5);
});

// Every card reader: no number as a default, and no `parseFloat(x) ?? y`,
// which lets NaN through. A sum that wants 0 passes it.
test('no card reader keeps a number as its default', () => {
    const dir = new URL('../src/', import.meta.url);
    const files = [];
    for (const sub of ['cards/', 'base/']) {
        for (const f of readdirSync(new URL(sub, dir))) {
            if (f.endsWith('.js')) files.push(new URL(sub + f, dir));
        }
    }
    for (const f of files) {
        const src = readFileSync(f, 'utf8');
        const name = f.pathname.split('/src/')[1];
        assert.doesNotMatch(src, /^\s+_\w+\([\w, ]*\bfallback\s*=\s*-?\d/m,
            `${name}: a reader's default is a number again`);
        // The readers by name, whatever their parameters are called.
        for (const m of src.matchAll(/^\s+_(val|state|valNum|numVal|entityVal|getState)\(([^)]*)\)\s*\{/gm)) {
            assert.doesNotMatch(m[2], /=\s*-?\d/, `${name}: _${m[1]}(${m[2]})`);
        }
        assert.doesNotMatch(src, /parseFloat\([^()]*\)\s*\?\?/,
            `${name}: parseFloat(x) ?? y lets NaN through`);
    }
});

// ── Sums and checks keep their own 0 ───────────────────────────────────────

const st = (state, attributes = {}) => ({ state: String(state), attributes });
const OUT = st('unavailable');
const hassOf = (states) => ({ states, language: 'en', config: { currency: 'EUR' } });
function made(tag, states, config = {}) {
    const el = new (customElements.get(tag))();
    el.setConfig({ type: `custom:${tag}`, ...config });
    el._scheduleUpdate = () => {};
    el.hass = hassOf(states);
    return el;
}

test('EV card: a charger power that is out reads "— W", a real 0 "0 W"', () => {
    const states = {
        'sensor.sem_charger_a_power': OUT,
        'sensor.sem_charger_b_power': st('3000'),
        'sensor.sem_charger_a_daily_energy': OUT,
        'sensor.sem_charger_b_daily_energy': st('0'),
    };
    const el = made('sem-ev-status-card', states);
    assert.deepEqual(el._chargers, ['a', 'b']);
    const a = words(text(el._renderChargerSection('a', 0)));
    const b = words(text(el._renderChargerSection('b', 1)));
    assert.match(a, /power — W/, a);
    assert.doesNotMatch(a, /\b0 W\b|0\.0 kWh/, a);
    assert.match(b, /power 3\.0 kW/, b);
    assert.match(b, /today 0\.0 kWh/, 'a real 0 still prints 0');
    // The header adds the charger that reads; the one that is out adds 0.
    assert.match(words(text(el.render())), /power 3\.0 kW/);
});

test('EV card: no charge range from a day count that is out', () => {
    const el = made('sem-ev-status-card', {
        'sensor.sem_charger_a_power': st('0'),
        'sensor.sem_charger_a_daily_energy': OUT,
    });
    assert.doesNotMatch(words(text(el._renderChargerSection('a', 0))), /\+\d+ km/);
    const live = made('sem-ev-status-card', {
        'sensor.sem_charger_a_power': st('0'),
        'sensor.sem_charger_a_daily_energy': st('1'),
    });
    assert.match(words(text(live._renderChargerSection('a', 0))), /\+50 km/,
        '9 kWh left at 18 kWh/100 km');
});

test('battery card: a running session whose figures are out prints "—"', () => {
    const el = made('sem-battery-card', {
        'sensor.sem_battery_power': st('1500'),
        'sensor.sem_battery_session_type': st('charge'),
        'sensor.sem_battery_session_energy': OUT,
        'sensor.sem_battery_session_avg_power': OUT,
        'sensor.sem_battery_session_cost': OUT,
    });
    const out = words(text(el.render()));
    assert.match(out, /current_session/);
    assert.doesNotMatch(out, /0\.00 kWh|\b0 W\b|0\.00 EUR/, out);
});

test('load list: a load whose power entity is out reads "— W", not 0 W', () => {
    const devices = {
        boiler: { name: 'Boiler', power_entity: 'sensor.boiler_power', priority: 3 },
        pump: { name: 'Pump', power_entity: 'sensor.pump_power', priority: 4 },
    };
    const el = made('sem-load-priority-card', {
        'sensor.sem_controllable_devices_count': st('2', { devices }),
        'sensor.boiler_power': OUT,
        'sensor.pump_power': st('800'),
    });
    el._updateDeviceData();
    const byId = Object.fromEntries(el.devices.map((d) => [d.id, d]));
    assert.equal(byId.boiler.power, null);
    assert.equal(byId.pump.power, 0.8);
    assert.equal(byId.boiler.isOn === true || byId.boiler.power > 0.01, false,
        'out is not on');
    const out = words(text(el.render()));
    assert.doesNotMatch(out, /\b0 W\b/, out);
});

test('load list: the peak block prints "—" while its sensors are out', () => {
    const el = made('sem-load-priority-card', {
        'sensor.sem_target_peak_limit': OUT,
        'sensor.sem_consecutive_peak_15min': OUT,
    });
    el._updateDeviceData();
    const out = words(text(el.render()));
    assert.match(out, /target_limit — kW/);
    assert.match(out, /margin — kW/);
    assert.doesNotMatch(out, /5\.0|1\.0 kW|0\.00 kW/, out);
    const live = made('sem-load-priority-card', {
        'sensor.sem_target_peak_limit': st('6'),
        'sensor.sem_consecutive_peak_15min': st('2.5'),
    });
    live._updateDeviceData();
    assert.match(words(text(live.render())), /margin 3\.50 kW/);
});

test('grid card: net and allocated need both of their parts', () => {
    const el = made('sem-grid-card', {
        'sensor.sem_daily_grid_import_energy': st('5'),
        'sensor.sem_daily_grid_export_energy': OUT,
        'sensor.sem_surplus_total_w': OUT,
        'sensor.sem_surplus_unallocated_w': st('200'),
    });
    const out = words(text(el.render()));
    assert.match(out, /net_(import|export) — kWh/, out);
    assert.match(out, /allocated — W/, out);
    const live = made('sem-grid-card', {
        'sensor.sem_daily_grid_import_energy': st('5'),
        'sensor.sem_daily_grid_export_energy': st('2'),
        'sensor.sem_surplus_total_w': st('900'),
        'sensor.sem_surplus_unallocated_w': st('200'),
    });
    const l = words(text(live.render()));
    assert.match(l, /net_import 3\.00 kWh/);
    assert.match(l, /allocated 700 W/);
});

test('costs card: a net cost that is out is not "+0.00"', () => {
    const el = made('sem-costs-card', {
        'sensor.sem_daily_net_cost': OUT,
        'sensor.sem_daily_savings': st('1.5'),
        'sensor.sem_daily_battery_savings': OUT,
    });
    const out = words(text(el.render()));
    assert.doesNotMatch(out, /\+0\.00/, out);
    assert.match(out, /solar_savings 1\.50 EUR/);
    // the subtotal needs both parts
    assert.match(out, /cost_block_avoided_total — /, out);
});

test('diagram: Home is out only when it cannot be worked out', () => {
    const base = {
        'sensor.sem_solar_power': st('2000'),
        'sensor.sem_grid_import_power': st('0'),
        'sensor.sem_grid_export_power': st('500'),
        'sensor.sem_home_consumption_power': OUT,
        'sensor.sem_daily_solar_energy': OUT,
    };
    const homeLabel = (states) => {
        const el = made('sem-system-diagram-card', states, { show_battery: false, show_ev: false });
        el._homeDisp = 1500;
        return words(text(el.render()));
    };
    // The home sensor is out but solar and grid read: Home is their sum.
    let out = homeLabel(base);
    assert.match(out, /home 1\.5 kW/, out);
    assert.match(out, /today — kWh/, 'a day count that is out');
    // Solar out too: Home cannot be worked out.
    out = homeLabel({ ...base, 'sensor.sem_solar_power': OUT });
    assert.match(out, /solar — W/, out);
    assert.match(out, /home — W/, out);
});

test('flow card: a node whose sensor is out reads "— W" after an update', () => {
    const el = made('sem-flow-card', {
        'sensor.sem_solar_power': OUT,
        'sensor.sem_grid_import_power': st('700'),
        'sensor.sem_grid_export_power': st('0'),
        'sensor.sem_battery_power': OUT,
        'sensor.sem_battery_soc': OUT,
        'sensor.sem_ev_power': st('0'),
        'sensor.sem_home_consumption_power': st('700'),
    }, { entity_prefix: 'sensor.sem_' });
    const nodes = {};
    el.renderRoot = {
        getElementById: (id) => (id.startsWith('val-') ? (nodes[id] ??= { textContent: '', style: {}, setAttribute() {} }) : null),
        querySelector: () => null, querySelectorAll: () => [],
    };
    // A count that does not move is written at once (no frames run here).
    el._currentValues = { 'val-grid': 700, 'val-home': 700, 'val-solar': 2000, 'val-battery-power': 900 };
    el._updateFlowsImperative();
    assert.equal(nodes['val-solar'].textContent, '— W', 'no count down from 2 kW to 0 W');
    assert.equal(nodes['val-battery-power'].textContent, '— W');
    assert.equal(nodes['val-battery-soc'].textContent, '—%');
    assert.equal(nodes['val-grid'].textContent, '↓ 700 W');
    assert.equal(nodes['val-home'].textContent, '700 W');
    assert.equal(nodes['val-ev'].textContent, '0 W', 'a real 0 still prints 0');
});

// ── Found in review ────────────────────────────────────────────────────────

test('costs card: a home with no battery keeps its avoided total', () => {
    // SEM makes no battery savings sensor without a battery: that part is 0.
    const el = made('sem-costs-card', {
        'sensor.sem_daily_savings': st('1.5'),
        'sensor.sem_daily_net_cost': st('-0.4'),
    });
    const out = words(text(el.render()));
    assert.match(out, /cost_block_avoided_total 1\.50 EUR/, out);
    // With a battery whose sensor is out, the total is not known.
    const dark = made('sem-costs-card', {
        'sensor.sem_daily_savings': st('1.5'),
        'sensor.sem_daily_battery_savings': OUT,
    });
    assert.match(words(text(dark.render())), /cost_block_avoided_total — /);
});

test('costs detail: a home with no charger still says "no EV data"', () => {
    const none = made('sem-costs-detail-card', {});
    assert.equal(none._sectionSubtitle('ev_econ', 'EUR'), 'no_ev_data');
    assert.match(words(text(none._renderSectionBody('ev_econ', 'EUR'))), /no_ev_data/);
    const dark = made('sem-costs-detail-card', { 'sensor.sem_lifetime_ev_energy': OUT });
    assert.equal(dark._sectionSubtitle('ev_econ', 'EUR'), '—');
    const zero = made('sem-costs-detail-card', { 'sensor.sem_lifetime_ev_energy': st('0') });
    assert.equal(zero._sectionSubtitle('ev_econ', 'EUR'), 'no_ev_data');
});

test('charger tile: a power that is out says neither Charging nor Idle', () => {
    const el = made('sem-charger-status-card', { 'sensor.sem_charger_a_power': OUT });
    el._chargers = ['a'];
    const out = words(text(el._renderChargerTile('a')));
    assert.doesNotMatch(out, /idle|charging/, out);
    const live = made('sem-charger-status-card', { 'sensor.sem_charger_a_power': st('0') });
    assert.match(words(text(live._renderChargerTile('a'))), /idle/);
});

test('grid card: a real 0 rate prints 0, an out one the dash', () => {
    const el = made('sem-grid-card', {
        'sensor.sem_tariff_current_export_rate': st('0'),
        'sensor.sem_tariff_current_import_rate': OUT,
    });
    const out = words(text(el.render()));
    assert.match(out, /export_rate 0\.0000 EUR\/kWh/, out);
    assert.match(out, /import_rate — /, out);
});

test('flow card: a real 0 that goes out turns into "— W" on the next update', () => {
    const states = {
        'sensor.sem_solar_power': st('0'),
        'sensor.sem_grid_import_power': st('300'),
        'sensor.sem_grid_export_power': st('0'),
        'sensor.sem_home_consumption_power': st('300'),
    };
    const el = made('sem-flow-card', states, { entity_prefix: 'sensor.sem_' });
    const nodes = {};
    el.renderRoot = {
        getElementById: (id) => (id.startsWith('val-') ? (nodes[id] ??= { textContent: '', style: {}, setAttribute() {} }) : null),
        querySelector: () => null, querySelectorAll: () => [],
    };
    el._currentValues = { 'val-grid': 300, 'val-home': 300 };
    el._updateFlowsImperative();
    assert.equal(nodes['val-solar'].textContent, '0 W');
    el._hass = hassOf({ ...states, 'sensor.sem_solar_power': OUT });
    el._updateFlowsImperative();
    assert.equal(nodes['val-solar'].textContent, '— W', 'the flows did not move, the label must');
});

test('diagram and flow card: a load whose power entity is out reads "— W"', () => {
    const info = { name: 'Boiler', power_entity: 'sensor.boiler_power', is_on: true };
    const states = {
        'sensor.sem_controllable_devices_count': st('1', { devices: { boiler: info } }),
        'sensor.boiler_power': OUT,
    };
    const el = made('sem-system-diagram-card', states);
    const loads = el._collectDevices();
    assert.equal(loads.length, 1);
    assert.equal(loads[0].power, null);
    assert.match(words(text(el._renderDeviceChips())), /— W/);

    const flow = made('sem-flow-card', states, { entity_prefix: 'sensor.sem_' });
    const nodes = {};
    flow.renderRoot = {
        getElementById: (id) => (id.startsWith('dev-val-') ? (nodes[id] ??= { textContent: '', style: {}, setAttribute() {} }) : null),
        querySelector: () => null, querySelectorAll: () => [],
    };
    flow._devicePositions = [{ x: 0, y: 0 }];
    flow._currentValues = { 'dev-val-0': 1200 };
    flow._updateDeviceValues([['boiler', info]]);
    assert.equal(nodes['dev-val-0'].textContent, '— W', 'not a count down to 0 W');
});

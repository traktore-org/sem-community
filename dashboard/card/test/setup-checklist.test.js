/**
 * (#1379) The setup checklist card: banner while SEM only watches, an inline
 * confirm before the take-control call, chip once done, Hide per browser,
 * and where each row's button goes.
 *
 * Run: `node --test test/setup-checklist.test.js` (from dashboard/card).
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';

const FAKE_LIT = `
export class LitElement {
    constructor() { this.style = {}; this.renderRoot = { querySelector: () => null, querySelectorAll: () => [] }; }
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
globalThis.addEventListener = () => {};
globalThis.removeEventListener = () => {};
globalThis.getComputedStyle = () => ({ getPropertyValue: () => '' });
globalThis.CustomEvent = class { constructor(type, init) { this.type = type; this.detail = init?.detail; } };
globalThis.dispatchEvent = () => true;
const store = new Map();
globalThis.localStorage = { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)) };
const session = new Map();
globalThis.sessionStorage = { getItem: (k) => (session.has(k) ? session.get(k) : null), setItem: (k, v) => session.set(k, String(v)), removeItem: (k) => session.delete(k) };
const pushed = [];
globalThis.history = { pushState: (_a, _b, url) => pushed.push(url) };
globalThis.location = { pathname: '/my-energy/now' };
const registry = new Map();
globalThis.customElements = { get: (t) => registry.get(t), define: (t, c) => registry.set(t, c) };
globalThis.semLocalize = (key) => key;

await import('../src/cards/sem-setup-checklist-card.js');
const util = await import('../src/util/setup-checklist.js');
const Card = registry.get('sem-setup-checklist-card');

const items = (over = {}) => [
    { key: 'hardware', done: true, brands: ['huawei_solar'] },
    { key: 'dashboard', done: true },
    { key: 'charger', done: false, count: 0, detected: 'KEBA P30' },
    { key: 'forecast', done: false },
    { key: 'price', done: false },
].map((i) => ({ ...i, ...(over[i.key] || {}) }));

function states({ watch = true, must = true, repairs = { count: 1, first: 'Sign is a guess' }, over = {}, switchOff = false } = {}) {
    const it = items(over);
    const s = {
        'sensor.sem_diag_charger_control': { state: 'number', attributes: { setup_checklist: {
            watch_only: watch, items: it, done: it.filter((i) => i.done).length, total: it.length,
            must_open: must, repairs } } },
    };
    if (!switchOff) s['switch.sem_observer_mode'] = { state: watch ? 'on' : 'off', attributes: {} };
    return s;
}

function card(st, layout) {
    store.clear(); session.clear(); pushed.length = 0;
    const c = new Card();
    c.setConfig(layout ? { layout } : {});
    c._hass = { states: st, language: 'en', callService: async (...a) => { c.calls.push(a); } };
    c.calls = [];
    return c;
}

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
/** Every function bound to an @click, in render order. */
function handlers(part, acc = []) {
    if (Array.isArray(part)) part.forEach((p) => handlers(p, acc));
    else if (part && part.strings && part.values) {
        part.values.forEach((v) => { if (typeof v === 'function') acc.push(v); else handlers(v, acc); });
    }
    return acc;
}
const shown = (c) => text(c.render());

test('watch-only: the banner shows, with the take-control button', () => {
    const c = card(states());
    const t = shown(c);
    assert.match(t, /setup_watch_title/);
    assert.match(t, /setup_take_control/);
    assert.match(t, /setup_list_title/);
});

test('the take-control button asks first and calls nothing yet', async () => {
    const c = card(states());
    const open = handlers(c.render()).find((h) => h.toString().includes('_confirming = true'));
    open();
    assert.equal(c.calls.length, 0);
    const t = shown(c);
    assert.match(t, /setup_confirm_text/);
    assert.match(t, /setup_confirm_yes/);
    assert.match(t, /setup_confirm_no/);
    assert.equal(c.calls.length, 0);
});

test('Yes calls switch.turn_off on the observer switch, exactly once', () => {
    const c = card(states());
    c._confirming = true;
    const yes = handlers(c.render())[0];
    yes();
    assert.deepEqual(c.calls, [['switch', 'turn_off', { entity_id: 'switch.sem_observer_mode' }]]);
    assert.equal(c._confirming, false);
});

test('Not yet closes the confirm and never calls', () => {
    const c = card(states());
    c._confirming = true;
    const no = handlers(c.render())[1];
    no();
    assert.equal(c._confirming, false);
    assert.equal(c.calls.length, 0);
});

test('without the switch, the attribute decides watch-only', () => {
    assert.equal(util.isWatchOnly({}, { watch_only: true }), true);
    assert.equal(util.isWatchOnly({}, { watch_only: false }), false);
    assert.equal(util.isWatchOnly({ 'switch.sem_observer_mode': { state: 'off' } }, { watch_only: true }), false);
});

test('in control and nothing must be done: only the control chip, no setup chip, no banner, no list', () => {
    const c = card(states({ watch: false, must: false, over: { charger: { done: true }, forecast: { done: true }, price: { done: true } }, repairs: { count: 0 } }));
    const t = shown(c);
    assert.match(t, /setup_chip_control/);
    assert.doesNotMatch(t, /setup_chip_setup/, 'a finished setup has no "5 of 5" chip');
    assert.doesNotMatch(t, /setup_watch_title|setup_list_title|setup_take_control/);
});

test('in control but a must-do is open: the list stays, no banner', () => {
    const t = shown(card(states({ watch: false, must: true })));
    assert.match(t, /setup_list_title/);
    assert.doesNotMatch(t, /setup_watch_title/);
});

test('the chip reopens the list', () => {
    const c = card(states({ watch: false, must: false }));
    assert.doesNotMatch(shown(c), /setup_list_title/);
    handlers(c.render()).find((h) => h.toString().includes('_reopen'))();
    assert.match(shown(c), /setup_list_title/);
});

test('Hide folds the list for this browser and survives a new card', () => {
    const c = card(states());
    handlers(c.render()).find((h) => h.toString().includes('_hide'))();
    assert.doesNotMatch(shown(c), /setup_list_title/);
    assert.match(shown(c), /setup_watch_title/, 'the banner stays while SEM only watches');
    assert.equal(globalThis.localStorage.getItem(util.HIDE_KEY), '1');
    const again = new Card();
    again.setConfig({});
    again._hass = c._hass;
    assert.doesNotMatch(text(again.render()), /setup_list_title/);
});

test('Hide still works when storage throws', () => {
    const keep = globalThis.localStorage;
    globalThis.localStorage = { getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); } };
    try {
        const c = new Card();
        c.setConfig({});
        c._hass = { states: states(), language: 'en', callService: async () => {} };
        c._hide();
        assert.equal(c._hidden, true);
    } finally { globalThis.localStorage = keep; }
});

test('no checklist from the backend: the card draws nothing', () => {
    const c = card({});
    assert.equal(typeof c.render(), 'symbol');
});

test('a found charger offers Use it; none found offers Add', () => {
    assert.match(shown(card(states())), /setup_btn_use/);
    assert.match(shown(card(states({ over: { charger: { detected: null } } }))), /setup_btn_add/);
});

test('things to check shows the count, the first title and an Open button', () => {
    const t = shown(card(states({ repairs: { count: 3, first: 'Sign is a guess' } })));
    assert.match(t, /setup_check_n/);
    assert.match(t, /Sign is a guess/);
    assert.match(shown(card(states({ repairs: { count: 0, first: null } }))), /^(?!.*setup_check_)/s);
});

test('targets: Devices for the charger, System setup check for forecast and price, on any dashboard URL', () => {
    for (const base of ['/sem-next', '/my-energy']) {
        assert.deepEqual(util.rowTarget('charger', base + '/now'), { path: base + '/devices' });
        assert.deepEqual(util.rowTarget('forecast', base + '/now'),
            { path: base + '/system', store: [util.OPEN_PANEL_KEY, 'setup'] });
        assert.deepEqual(util.rowTarget('price', base + '/now').path, base + '/system');
        assert.deepEqual(util.rowTarget('repairs', base + '/now'), { path: '/config/repairs' });
    }
});

test('a row button navigates and leaves its hint; Repairs leaves none', () => {
    const c = card(states());
    c._go('charger');
    assert.deepEqual(pushed, ['/my-energy/devices']);
    c._go('forecast');
    assert.equal(pushed.at(-1), '/my-energy/system');
    assert.equal(util.takeStored(util.OPEN_PANEL_KEY), 'setup');
    assert.equal(util.takeStored(util.OPEN_PANEL_KEY), '', 'taken once');
    c._go('repairs');
    assert.equal(pushed.at(-1), '/config/repairs');
});

test('brand domains read as words', () => {
    assert.equal(util.brandLabel('huawei_solar'), 'Huawei Solar');
});

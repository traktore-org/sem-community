/**
 * #1058 — the Energy tab's charts drew once. Leave the tab, come back, and
 * both charts were empty until a page reload.
 *
 * Home Assistant takes a view's cards off the page when you leave a tab and
 * puts the SAME card objects back when you return. Lit runs firstUpdated()
 * once per object, so a part built there (or only when hass changes) and
 * torn down in disconnectedCallback() never comes back.
 *
 * Part 1 drives the real card code through leave-and-return. Lit itself is
 * replaced by a stub (CI runs `node --test` with no node_modules), so only
 * the cards' own lifecycle code runs. Part 2 reads every card's source and
 * fails when disconnectedCallback() tears down a part that nothing builds
 * again when the card returns.
 *
 * Run: `npm test` (from dashboard/card).
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';
import { readFileSync, readdirSync } from 'node:fs';

// ── Part 1: the real cards, with a stub in place of lit ──────────────────

// Lit's update cycle, as Lit runs it: the constructor asks for an update,
// the first connect turns updating on, and an update runs a microtask after
// it is asked for — on or off the page. firstUpdated() runs on the first
// update only. Putting a card back on the page asks for nothing.
const FAKE_LIT = `
export class LitElement {
    constructor() {
        this.hasUpdated = false;
        this.isConnected = false;
        this.style = {};
        this.renderRoot = globalThis.__semFakeRoot();
        this.updates = 0;
        this.__enabled = false;
        this.__pending = true;
    }
    connectedCallback() {
        if (this.__enabled) return;
        this.__enabled = true;
        queueMicrotask(() => this.__perform());
    }
    disconnectedCallback() {}
    requestUpdate() {
        if (this.__pending) return;
        this.__pending = true;
        if (this.__enabled) queueMicrotask(() => this.__perform());
    }
    __perform() {
        if (!this.__pending) return;
        this.__pending = false;
        this.updates++;
        if (!this.hasUpdated) { this.hasUpdated = true; this.firstUpdated?.(new Map()); }
        this.updated?.(new Map());
    }
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

const listeners = new Map();          // event → Set of handlers on document/window
const on = (t, h) => { if (!listeners.has(t)) listeners.set(t, new Set()); listeners.get(t).add(h); };
const off = (t, h) => listeners.get(t)?.delete(h);
const watching = { ResizeObserver: new Set(), IntersectionObserver: new Set() };
function fakeObserver(kind) {
    return class {
        constructor(cb) { this.cb = cb; }
        observe() { watching[kind].add(this); }
        disconnect() { watching[kind].delete(this); }
    };
}
// Each test counts from zero, so one failed test cannot fail the next.
const clearWatchers = () => Object.values(watching).forEach((set) => set.clear());
const canvas = { getContext: () => ({}) };
globalThis.__semFakeRoot = () => ({
    querySelector: (sel) => (sel === 'canvas' ? canvas : null),
    querySelectorAll: () => [],
    getElementById: () => null,
});
globalThis.window = globalThis;
globalThis.document = {
    addEventListener: on, removeEventListener: off,
    documentElement: {}, head: { appendChild() {} }, createElement: () => ({}),
    hidden: false, visibilityState: 'visible',
};
globalThis.addEventListener = on;
globalThis.removeEventListener = off;
const registry = new Map();
globalThis.customElements = { get: (t) => registry.get(t), define: (t, c) => registry.set(t, c) };
globalThis.getComputedStyle = () => ({ getPropertyValue: () => '' });
globalThis.ResizeObserver = fakeObserver('ResizeObserver');
globalThis.IntersectionObserver = fakeObserver('IntersectionObserver');
// A failed assertion skips the test's detach(); a card's 5-minute timer must
// not then keep the run open.
const realSetInterval = setInterval;
globalThis.setInterval = (...args) => realSetInterval(...args).unref();
let rafId = 0;
globalThis.requestAnimationFrame = () => ++rafId;
globalThis.cancelAnimationFrame = () => {};

// Chart.js stand-in: counts the charts that exist (made and not destroyed).
const liveCharts = new Set();
globalThis.Chart = class {
    constructor() { liveCharts.add(this); }
    destroy() { liveCharts.delete(this); }
};
globalThis.Chart._adapters = { _date: class { formats() { return {}; } } };

globalThis.localStorage = { getItem: () => null, setItem() {} };
globalThis.navigator ??= {};

for (const f of ['sem-chart-card', 'sem-flow-card', 'sem-system-diagram-card', 'sem-title-card',
    'sem-ev-status-card', 'sem-config-card', 'sem-diagnose-button']) {
    await import(`../src/cards/${f}.js`);
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
// HA puts the card on the page (connectedCallback), and Lit's pending update
// runs a microtask later.
async function attach(el) {
    el.isConnected = true;
    el.connectedCallback();
    await sleep(0);
}
function detach(el) {
    el.isConnected = false;
    el.disconnectedCallback();
}
// The card is put on the page and taken off again in one go, so its first
// update — firstUpdated() — runs while it is off the page.
async function attachAndLeaveBeforeFirstUpdate(el) {
    el.isConnected = true;
    el.connectedCallback();
    detach(el);
    await sleep(0);
    assert.ok(el.hasUpdated, 'the first update ran');
}

function statsHass(gate) {
    const hass = {
        language: 'en', config: { time_zone: 'UTC' }, states: {}, calls: 0,
        callWS: async (msg) => {
            hass.calls++;
            if (gate) await gate;
            const now = Date.now();
            return Object.fromEntries(msg.statistic_ids.map((id) => [id, [
                { start: now - 2 * 3600e3, state: 4, max: 4, mean: 4 },
                { start: now - 3600e3, state: 5, max: 5, mean: 5 },
            ]]));
        },
    };
    return hass;
}

for (const preset of ['power', 'energy']) {
    test(`the ${preset} chart is drawn again when you come back to the tab`, async () => {
        liveCharts.clear();
        const el = new (customElements.get('sem-chart-card'))();
        el.setConfig({ preset });
        el.hass = statsHass();
        await attach(el);
        await sleep(250);                       // the 150 ms fetch debounce
        assert.equal(el.hass.calls, 1, 'first visit fetched');
        assert.equal(liveCharts.size, 1, 'first visit drew a chart');

        detach(el);                             // leave the tab
        assert.equal(liveCharts.size, 0, 'leaving the tab frees the chart');

        await attach(el);                       // come back
        await sleep(250);
        assert.equal(el.hass.calls, 2, 'coming back fetched the data again');
        assert.equal(liveCharts.size, 1, 'coming back drew the chart again');
        detach(el);
    });
}

test('coming back draws the window that ends now, not the one from the first visit', async () => {
    const el = new (customElements.get('sem-chart-card'))();
    el.setConfig({ preset: 'power' });
    el.hass = statsHass();
    await attach(el);
    await sleep(200);
    detach(el);
    const first = el._period;
    // An hour away from the tab.
    el._period = { ...first, start: new Date(first.start - 3600e3), end: new Date(first.end - 3600e3) };
    await attach(el);
    await sleep(200);
    assert.equal(el._period.key, '24h');
    assert.ok(Date.now() - el._period.end.getTime() < 5000, 'window must end now');
    detach(el);
});

test('a range the user picked is kept when you come back', async () => {
    const el = new (customElements.get('sem-chart-card'))();
    el.setConfig({ preset: 'costs' });
    el.hass = statsHass();
    await attach(el);
    await sleep(200);
    const picked = { key: 'month', start: new Date(2026, 8, 1), end: new Date(2026, 8, 30), granularity: 'day' };
    el._onPeriodChange(picked);
    await sleep(200);
    detach(el);
    const calls = el.hass.calls;
    await attach(el);
    await sleep(200);
    assert.equal(el._period.key, 'month');
    assert.equal(el._period.start.getTime(), picked.start.getTime());
    assert.equal(el.hass.calls, calls + 1, 'the picked range was fetched again');
    detach(el);
});

test('a chart whose first update runs off the page asks for no data', async () => {
    const el = new (customElements.get('sem-chart-card'))();
    el.setConfig({ preset: 'power' });
    el.hass = statsHass();
    await attachAndLeaveBeforeFirstUpdate(el);
    await sleep(250);
    assert.equal(el.hass.calls, 0);
    await attach(el);
    await sleep(250);
    assert.equal(el.hass.calls, 1, 'drawn once it is on the page');
    detach(el);
});

test('a chart that gets hass twice before it is first put on the page draws', async () => {
    liveCharts.clear();
    const el = new (customElements.get('sem-chart-card'))();
    el.setConfig({ preset: 'power' });
    const hass = statsHass();
    el.hass = hass;
    el.hass = hass;                             // sets the window and schedules a fetch off the page
    await sleep(250);
    assert.equal(liveCharts.size, 0);
    await attach(el);
    await sleep(250);
    assert.equal(liveCharts.size, 1, 'the canvas stayed empty');
    assert.equal(hass.calls, 1);
    detach(el);
});

test('data that lands after you left the tab draws nothing', async () => {
    liveCharts.clear();
    let release;
    const gate = new Promise((r) => { release = r; });
    const el = new (customElements.get('sem-chart-card'))();
    el.setConfig({ preset: 'power' });
    el.hass = statsHass(gate);
    await attach(el);
    await sleep(200);                           // fetch sent, answer not back yet
    assert.equal(el.hass.calls, 1);
    detach(el);
    release();
    await sleep(50);
    assert.equal(liveCharts.size, 0, 'a chart was made on a card that is off the page');
});

test('the hourly charts keep rolling to now (#541)', () => {
    const el = new (customElements.get('sem-chart-card'))();
    for (const [preset, key] of [['power', '24h'], ['battery', '24h'], ['forecast', '24h'],
        ['ev', 'today'], ['energy', '7d'], ['costs', 'week'], ['savings', 'week']]) {
        el.setConfig({ preset });
        assert.equal(el._defaultKey(), key, `${preset} opens on ${key}`);
    }
});

test('the power chart moves to now when the app comes back (#541 roll)', async () => {
    const el = new (customElements.get('sem-chart-card'))();
    el.setConfig({ preset: 'power' });
    el.hass = statsHass();
    await attach(el);
    await sleep(200);
    const first = el._period;
    el._period = { ...first, start: new Date(first.start - 3600e3), end: new Date(first.end - 3600e3) };
    el._boundVisibility();                      // the app comes back to the front
    await sleep(200);
    assert.ok(Date.now() - el._period.end.getTime() < 5000, 'window must end now');
    assert.equal(el.hass.calls, 2, 'the new window was fetched');
    detach(el);
});

test('every SEM card draws again when you come back (Lit does not)', async () => {
    for (const tag of ['sem-chart-card', 'sem-flow-card', 'sem-system-diagram-card', 'sem-title-card',
        'sem-ev-status-card', 'sem-config-card', 'sem-diagnose-button']) {
        const el = new (customElements.get(tag))();
        el.setConfig({ preset: 'power', title: 'T', entity_prefix: 'sensor.sem_' });
        await attach(el);
        const drawn = el.updates;
        detach(el);
        await attach(el);
        assert.ok(el.updates > drawn, `${tag} kept what it drew before you left`);
        detach(el);
    }
});

test('the EV card restarts its pause countdown when you come back', async () => {
    const el = new (customElements.get('sem-ev-status-card'))();
    el.setConfig({ entity_prefix: 'sensor.sem_' });
    el.hass = {
        language: 'en', config: { time_zone: 'UTC' },
        states: { 'select.sem_charger_a_charge_mode':
            { state: 'off', attributes: { paused_until: '2026-10-06T20:00:00+00:00' } } },
    };
    await attach(el);
    assert.ok(el._pauseTimer, 'the countdown runs');
    detach(el);
    assert.equal(el._pauseTimer, null);
    await attach(el);                           // no new hass: nothing changed while away
    assert.ok(el._pauseTimer, 'the countdown did not restart');
    detach(el);
});

test('the Config card drops a ✓ whose timer stopped when you left; an error stays', async () => {
    const el = new (customElements.get('sem-config-card'))();
    el.setConfig({});
    await attach(el);
    el._saveStatus = { a: 'ok', b: 'save failed', c: 'saving' };
    el._statusTimers.add(setTimeout(() => {}, 60000));
    detach(el);
    assert.deepEqual(el._saveStatus, { b: 'save failed', c: 'saving' });
});

test('the Diagnose button hides "Copied" when its timer stopped because you left', async () => {
    const el = new (customElements.get('sem-diagnose-button'))();
    el.setConfig({});
    await attach(el);
    el._copied = true;
    el._copiedTimer = setTimeout(() => {}, 60000);
    detach(el);
    assert.equal(el._copied, false);
});

for (const tag of ['sem-flow-card', 'sem-system-diagram-card']) {
    test(`${tag} starts no watchers when its first update runs off the page`, async () => {
        clearWatchers();
        const el = new (customElements.get(tag))();
        const listening = listeners.get('visibilitychange')?.size || 0;
        await attachAndLeaveBeforeFirstUpdate(el);
        assert.equal(watching.ResizeObserver.size, 0);
        assert.equal(watching.IntersectionObserver.size, 0);
        assert.equal(listeners.get('visibilitychange')?.size || 0, listening);
        await attach(el);
        assert.equal(watching.ResizeObserver.size, 1);
        assert.equal(watching.IntersectionObserver.size, 1);
        detach(el);
    });
}

for (const tag of ['sem-flow-card', 'sem-system-diagram-card']) {
    test(`${tag} watches its size and visibility again when you come back`, async () => {
        clearWatchers();
        const el = new (customElements.get(tag))();
        await attach(el);
        assert.equal(watching.ResizeObserver.size, 1);
        assert.equal(watching.IntersectionObserver.size, 1);
        detach(el);
        assert.equal(watching.ResizeObserver.size, 0);
        assert.equal(watching.IntersectionObserver.size, 0);
        await attach(el);
        assert.equal(watching.ResizeObserver.size, 1, 'size watcher not back');
        assert.equal(watching.IntersectionObserver.size, 1, 'visibility watcher not back');
        detach(el);
    });
}

test('sem-flow-card listens for the app coming back again when you come back', async () => {
    const el = new (customElements.get('sem-flow-card'))();
    const before = listeners.get('visibilitychange')?.size || 0;
    await attach(el);
    detach(el);
    await attach(el);
    assert.equal(listeners.get('visibilitychange')?.size || 0, before + 1);
    detach(el);
    assert.equal(listeners.get('visibilitychange')?.size || 0, before);
});

test('sem-system-diagram-card finishes its number count when you come back', async () => {
    const el = new (customElements.get('sem-system-diagram-card'))();
    await attach(el);
    el._targets = { solar: 1000, batt: 0, home: 500, ev: 0, grid: 0, gridMode: 'import' };
    el._counterRaf = requestAnimationFrame(() => {});
    detach(el);
    assert.equal(el._counterRaf, null);
    await attach(el);
    assert.ok(el._counterRaf, 'the count stopped half way');
    detach(el);
});

function templateHass(delayMs = 0) {
    const sub = { opened: 0, closed: 0 };
    return {
        sub, language: 'en', states: {},
        connection: {
            subscribeMessage: async (cb) => {
                sub.opened++;
                if (delayMs) await sleep(delayMs);
                cb({ result: `text ${sub.opened}` });
                return () => { sub.closed++; };
            },
        },
    };
}

test('sem-title-card subscribes to its template again when you come back', async () => {
    const el = new (customElements.get('sem-title-card'))();
    el.setConfig({ title: 'T', subtitle: '{{ states("sensor.x") }}' });
    const hass = templateHass();
    el.hass = hass;
    await attach(el);
    await sleep(10);
    assert.equal(hass.sub.opened, 1);
    detach(el);
    assert.equal(hass.sub.closed, 1);
    await attach(el);                           // no new hass: nothing changed while away
    await sleep(10);
    assert.equal(hass.sub.opened, 2, 'the subtitle stopped following its template');
    detach(el);
    assert.equal(hass.sub.opened - hass.sub.closed, 0, 'a subscription was left open');
});

test('sem-title-card closes a subscription that comes back after the card left', async () => {
    const el = new (customElements.get('sem-title-card'))();
    el.setConfig({ title: 'T', subtitle: '{{ now() }}' });
    const hass = templateHass(30);
    el.hass = hass;
    await attach(el);
    detach(el);                                 // left before the server answered
    await attach(el);
    await sleep(80);
    assert.equal(hass.sub.opened - hass.sub.closed, 1, 'exactly one subscription is open');
    detach(el);
    await sleep(10);
    assert.equal(hass.sub.opened - hass.sub.closed, 0);
});

test('sem-title-card opens no subscription while it is off the page', async () => {
    const el = new (customElements.get('sem-title-card'))();
    el.setConfig({ title: 'T', subtitle: '{{ now() }}' });
    const hass = templateHass();
    el.hass = hass;                             // HA sets hass before it puts the card on the page
    assert.equal(hass.sub.opened, 0);
    await attach(el);
    assert.equal(hass.sub.opened, 1);
    detach(el);
    el.hass = { ...hass };                      // a new hass reaches a card that is off the page
    await sleep(10);
    assert.equal(hass.sub.opened - hass.sub.closed, 0, 'a card off the page opened a subscription');
});

test('sem-title-card ignores a template answer or failure that comes after it left', async () => {
    for (const late of ['message', 'failure']) {
        let send, fail;
        const hass = {
            language: 'en', states: {},
            connection: { subscribeMessage: (cb) => { send = cb; return new Promise((res, rej) => { fail = rej; }); } },
        };
        const el = new (customElements.get('sem-title-card'))();
        el.setConfig({ title: 'T', subtitle: '{{ now() }}' });
        el.hass = hass;
        await attach(el);
        detach(el);
        if (late === 'message') send({ result: 'late text' });
        else fail(new Error('gone'));
        await sleep(10);
        assert.equal(el._renderedSubtitle, null, `a late ${late} changed the subtitle`);
    }
});

// ── Part 2: every card — what disconnectedCallback() frees, connectedCallback() builds ──

// Class methods at the cards' 4-space indent: `    name(args) {` … `    }`.
function methods(src) {
    const out = new Map();
    const lines = src.split('\n');
    const head = /^    (?:static\s+)?(?:async\s+)?(get\s+|set\s+)?(\w+)\s*\(.*\)\s*\{\s*$/;
    for (let i = 0; i < lines.length; i++) {
        const m = lines[i].match(head);
        if (!m || /^(if|for|while|switch|catch|function)$/.test(m[2])) continue;
        let j = i + 1;
        while (j < lines.length && lines[j] !== '    }') j++;
        const body = lines.slice(i + 1, j).filter((l) => !/^\s*(\/\/|\*|\/\*)/.test(l));
        out.set(m[1] ? `${m[1].trim()} ${m[2]}` : m[2], body);
    }
    return out;
}

// The methods `roots` run, and the methods those call. A call made from
// setInterval() or from a function stored for later (a listener) runs later
// or never, so it does not count.
function reach(ms, roots) {
    const seen = new Set();
    const todo = [...roots];
    while (todo.length) {
        const name = todo.pop();
        if (seen.has(name) || !ms.has(name)) continue;
        seen.add(name);
        for (const line of ms.get(name)) {
            if (/setInterval\(/.test(line)) continue;
            if (/this\.\w+\s*=\s*(\([^)]*\)|\w+)\s*=>/.test(line)) continue;
            for (const m of line.matchAll(/this\.(\w+)\(/g)) todo.push(m[1]);
        }
    }
    return seen;
}

const GESTURE = /^(pointer|mouse|touch|key)/;   // ends with the gesture; not rebuilt

function teardowns(ms) {
    const out = [];
    const lines = [...reach(ms, ['disconnectedCallback'])].flatMap((name) => ms.get(name));
    for (const line of lines) {
        for (const m of line.matchAll(/this\.(_\w+)\??\.(?:disconnect|destroy)\(/g)) {
            out.push({ what: m[1], built: new RegExp(`this\\.${m[1]}\\s*=\\s*(?!null|undefined)`) });
        }
        for (const m of line.matchAll(/clearInterval\(\s*this\.(_\w+)\s*\)/g)) {
            out.push({ what: m[1], built: new RegExp(`this\\.${m[1]}\\s*=\\s*(?!null|undefined)`) });
        }
        for (const m of line.matchAll(/\.removeEventListener\(\s*['"]([\w-]+)['"]\s*,\s*this\.(_\w+)/g)) {
            if (GESTURE.test(m[1])) continue;
            out.push({ what: `${m[1]} listener`, built: new RegExp(`addEventListener\\(\\s*['"]${m[1]}['"]\\s*,\\s*this\\.${m[2]}\\b`) });
        }
        if (/this\._unsub\w*(?:\?\.)?\(/.test(line)) {
            out.push({ what: 'subscription', built: /\.subscribe\w*\(/ });
        }
    }
    return out;
}

const SRC = new URL('../src/', import.meta.url);
const FILES = [
    ...readdirSync(new URL('cards/', SRC)).map((f) => `cards/${f}`),
    ...readdirSync(new URL('base/', SRC)).map((f) => `base/${f}`),
    ...readdirSync(new URL('elements/', SRC)).map((f) => `elements/${f}`),
].filter((f) => f.endsWith('.js'));

function missingOnReturn(src) {
    const ms = methods(src);
    // What runs every time HA puts the card back: connectedCallback(), and
    // updated() in a card on SEMLitBase, which asks for a render on return.
    const roots = /extends SEMLitBase\b/.test(src) ? ['connectedCallback', 'updated'] : ['connectedCallback'];
    const back = reach(ms, roots);
    return teardowns(ms).filter((t) =>
        ![...back].some((name) => ms.get(name).some((line) => t.built.test(line))),
    ).map((t) => t.what);
}

// Any spelling of the method head — a card the check cannot read must fail
// it, not drop out of it.
const DEFINES_DISCONNECT = /^\s*disconnectedCallback\s*\(\s*\)\s*\{/m;

test('every part a card frees when it leaves the page is built again when it returns', () => {
    const broken = [];
    for (const f of FILES) {
        const src = readFileSync(new URL(f, SRC), 'utf8');
        if (!DEFINES_DISCONNECT.test(src)) continue;
        assert.ok(methods(src).has('disconnectedCallback'),
            `${f}: disconnectedCallback() is not written as \`    disconnectedCallback() {\` — the check cannot read it`);
        const missing = missingOnReturn(src);
        if (missing.length) broken.push(`${f}: ${missing.join(', ')}`);
    }
    assert.deepEqual(broken, [],
        'freed in disconnectedCallback(), never built again when HA puts the card back:\n'
        + broken.join('\n'));
});

test('the source check sees the parts it is meant to see', () => {
    const seen = (f) => teardowns(methods(readFileSync(new URL(f, SRC), 'utf8'))).map((t) => t.what);
    assert.ok(seen('cards/sem-chart-card.js').includes('_chart'));
    assert.ok(seen('cards/sem-flow-card.js').includes('_resizeObserver'));
    assert.ok(seen('cards/sem-flow-card.js').includes('visibilitychange listener'));
    assert.ok(seen('cards/sem-system-diagram-card.js').includes('_intersectionObserver'));
    assert.ok(seen('cards/sem-title-card.js').includes('subscription'));
    assert.ok(seen('base/sem-lit-base.js').includes('sem-localize-ready listener'));
    const checked = FILES.filter((f) => DEFINES_DISCONNECT.test(readFileSync(new URL(f, SRC), 'utf8')));
    assert.ok(checked.length >= 11, `only ${checked.length} files checked`);
});

test('the source check fails a card that builds its chart only once', () => {
    const once = [
        'class X {',
        '    connectedCallback() {',
        '        super.connectedCallback();',
        '        this._roll = setInterval(() => this._draw(), 300000);',
        '    }',
        '    disconnectedCallback() {',
        '        clearInterval(this._roll);',
        '        if (this._chart) { this._chart.destroy(); this._chart = null; }',
        '    }',
        '    firstUpdated() {',
        '        this._draw();',
        '    }',
        '    _draw() {',
        '        this._chart = new Chart();',
        '    }',
        '}',
    ].join('\n');
    assert.deepEqual(missingOnReturn(once), ['_chart']);
    const fixed = once.replace('super.connectedCallback();',
        'super.connectedCallback();\n        if (this.hasUpdated) this._draw();');
    assert.deepEqual(missingOnReturn(fixed), []);
    assert.deepEqual(missingOnReturn(once.replace('this._chart.destroy();', 'this._chart?.destroy();')), ['_chart']);

    // A timer built in updated() comes back only where SEMLitBase renders on return.
    const inUpdated = [
        'class X extends SEMLitBase {',
        '    disconnectedCallback() {',
        '        clearInterval(this._tick);',
        '    }',
        '    updated() {',
        '        if (!this._tick) this._tick = setInterval(() => {}, 1000);',
        '    }',
        '}',
    ].join('\n');
    assert.deepEqual(missingOnReturn(inUpdated), []);
    assert.deepEqual(missingOnReturn(inUpdated.replace('extends SEMLitBase', 'extends LitElement')), ['_tick']);
});

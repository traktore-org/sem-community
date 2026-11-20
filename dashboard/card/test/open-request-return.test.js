/**
 * (#1398, class 123) Home Assistant keeps a screen's cards when you leave it and
 * puts the SAME card objects back on return. A tap on one screen that asks another
 * screen to open something ("Charge by" ✎ on Plan → the charger's day times on
 * Devices; a Home checklist row → the setup check on System) is left in
 * sessionStorage. The card must read it on every return, not once per object:
 * the Devices card read it only on its first render, so after one visit to
 * Devices the Plan screen's pencil did nothing.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';

const { mount, S, text } = await import('./card-harness.js');
// after the harness: these load the cards' Lit, which the harness replaces
const { OPEN_CHARGE_PLAN_KEY, CHARGER_PREFIX } = await import('../src/util/next-devices.js');
const { OPEN_PANEL_KEY } = await import('../src/util/setup-checklist.js');
const { chargerBody } = await import('../src/util/next-devices-charger.js');

globalThis.location ??= { pathname: '/sem-next/plan', hash: '' };
const store = new Map();
globalThis.sessionStorage = {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => { store.set(k, String(v)); },
    removeItem: (k) => { store.delete(k); },
};

const CHARGER = { 'sensor.sem_charger_c1_power': S(0, { unit_of_measurement: 'W' }) };

/** The Plan screen's "Charge by" pencil: what sem-next-plan-card writes before it switches screens. */
function planTap(cid) {
    const plan = mount('sem-next-plan-card', CHARGER);
    plan._go = () => {};
    plan._openChargePlan(cid);
}

test('Plan → Devices opens the charge plan on the first visit', () => {
    store.clear();
    planTap('c1');
    const el = mount('sem-next-devices-card', CHARGER);
    el.connectedCallback();
    el.updated(new Map());
    assert.equal(el._depOpen.c1, true, 'day times open');
    assert.equal(el._open[CHARGER_PREFIX + 'c1'], true, 'charger card open');
    assert.equal(store.has(OPEN_CHARGE_PLAN_KEY), false, 'the request is used up');
});

test('Plan → Devices opens the charge plan again when HA puts the same Devices card back', () => {
    store.clear();
    const el = mount('sem-next-devices-card', CHARGER);
    el.connectedCallback();
    el.updated(new Map());          // a first visit to Devices, nothing asked
    assert.ok(!el._depOpen.c1);
    el.disconnectedCallback();      // to the Plan screen
    planTap('c1');
    el.connectedCallback();         // back on Devices: the same object
    el.updated(new Map());
    assert.equal(el._depOpen.c1, true, 'the pencil opened the day times');
    assert.equal(store.has(OPEN_CHARGE_PLAN_KEY), false);

    el._depOpen = {};               // closed by hand
    el.disconnectedCallback();
    planTap('c1');
    el.connectedCallback();
    el.updated(new Map());
    assert.equal(el._depOpen.c1, true, 'and every time after');
});

test('a return with no tap opens nothing', () => {
    store.clear();
    const el = mount('sem-next-devices-card', CHARGER);
    el.connectedCallback();
    el.disconnectedCallback();
    el.connectedCallback();
    el.updated(new Map());
    assert.ok(!el._depOpen.c1);
    assert.ok(!el._scrollTo);
});

function scrollRoot(found) {
    const seen = [];
    return {
        seen,
        querySelector: (sel) => {
            if (!found.some((f) => sel.includes(f))) return null;
            return { scrollIntoView: (o) => seen.push([sel, o.block]) };
        },
        querySelectorAll: () => [], getElementById: () => null, appendChild() {},
    };
}

/** Frames held until flushed: HA sets a screen's scroll position after it draws it. */
const frames = [];
globalThis.requestAnimationFrame = (fn) => { frames.push(fn); return frames.length; };
async function nextFrame() {
    for (const fn of frames.splice(0)) fn();
    await new Promise((r) => setTimeout(r, 5));
}

test('the screen scrolls to the day times that opened, after the next frame', async () => {
    store.clear();
    planTap('c1');
    const el = mount('sem-next-devices-card', CHARGER);
    el.renderRoot = scrollRoot(['data-plan="c1"', `data-id="${CHARGER_PREFIX}c1"`]);
    el.connectedCallback();
    el.updated(new Map());
    assert.deepEqual(el.renderRoot.seen, [], 'not before the frame is drawn');
    await nextFrame();
    assert.deepEqual(el.renderRoot.seen, [['[data-plan="c1"]', 'center']]);
    el.updated(new Map());
    await nextFrame();
    assert.equal(el.renderRoot.seen.length, 1, 'scrolls once');
});

test('the card top when the day times are not drawn (reordering)', async () => {
    store.clear();
    planTap('c1');
    const el = mount('sem-next-devices-card', CHARGER);
    el.renderRoot = scrollRoot([`data-id="${CHARGER_PREFIX}c1"`]);
    el.connectedCallback();
    el.updated(new Map());
    await nextFrame();
    assert.deepEqual(el.renderRoot.seen, [[`[data-id="${CHARGER_PREFIX}c1"]`, 'start']]);
});

test('a scroll that found nothing does not wait for a later visit', async () => {
    store.clear();
    planTap('gone');                // a charger removed since the tap
    const el = mount('sem-next-devices-card', CHARGER);
    el.renderRoot = scrollRoot([`data-id="${CHARGER_PREFIX}c1"`]);
    el.connectedCallback();
    el.updated(new Map());
    assert.equal(el._scrollTo, 'gone', 'waits while the screen is shown');
    el.disconnectedCallback();
    assert.equal(el._scrollTo, null);
    el.connectedCallback();
    el.updated(new Map());
    await nextFrame();
    assert.deepEqual(el.renderRoot.seen, []);
});

test('the day times carry the mark the scroll looks for', () => {
    const el = mount('sem-next-devices-card', { ...CHARGER, 'time.sem_charger_c1_target_time': S('06:30:00') });
    el._depOpen = { c1: true };
    const out = text(chargerBody(el, { cid: 'c1', name: 'Zaptec', id: CHARGER_PREFIX + 'c1' }));
    assert.match(out, /class="days" data-plan=c1>/);
    el._depOpen = {};
    assert.doesNotMatch(text(chargerBody(el, { cid: 'c1', name: 'Zaptec', id: CHARGER_PREFIX + 'c1' })), /data-plan=/);
});

test('Home checklist → System opens the setup check when HA puts the same System card back', () => {
    store.clear();
    const el = mount('sem-next-system-card', {});
    el.connectedCallback();
    assert.equal(el._panel, '');
    el.disconnectedCallback();      // to Home; the checklist row stores its target, then the route changes
    store.set(OPEN_PANEL_KEY, 'setup');
    el.connectedCallback();         // the route listener was off the page and never heard it
    assert.equal(el._panel, 'setup');
    assert.equal(store.has(OPEN_PANEL_KEY), false);
    el.disconnectedCallback();
});

/**
 * What `name() { … }` runs itself: its body at the top level, without nested
 * blocks and without the part of a statement after `=>` (a listener runs later).
 */
function ownStatements(src, name) {
    const at = src.search(new RegExp('\\n\\s+' + name + '\\(\\)\\s*\\{'));
    if (at < 0) return null;
    let i = src.indexOf('{', at) + 1, depth = 1, top = '';
    for (; i < src.length && depth > 0; i++) {
        const ch = src[i];
        if (ch === '{') depth++;
        else if (ch === '}') depth--;
        else if (depth === 1) top += ch;
    }
    return top.split(';').map((st) => st.split('=>')[0]).join(';');
}

function jsFiles(dir) {
    const out = [];
    for (const e of readdirSync(dir, { withFileTypes: true })) {
        const p = new URL(e.name + (e.isDirectory() ? '/' : ''), dir);
        if (e.isDirectory()) out.push(...jsFiles(p)); else if (e.name.endsWith('.js')) out.push(p);
    }
    return out;
}

test('every card that takes a stored request takes it on each connect, through the one reader', () => {
    const src = new URL('../src/', import.meta.url);
    const takers = [];
    for (const url of jsFiles(src)) {
        const f = url.pathname.slice(src.pathname.length);
        const code = readFileSync(url, 'utf8');
        if (f !== 'util/setup-checklist.js') {
            assert.doesNotMatch(code, /sessionStorage\.getItem/, `${f}: read a stored request through takeStored()`);
        }
        if (!/\btakeStored\(/.test(code) || f === 'util/setup-checklist.js') continue;
        takers.push(f);
        const own = ownStatements(code, 'connectedCallback');
        assert.ok(own && /\btakeStored\(/.test(own), `${f}: HA puts the same card back — connectedCallback() itself must take the request`);
        // a card HA builds but never shows (the card picker) must not use up the request
        assert.doesNotMatch(ownStatements(code, 'constructor') || '', /\btakeStored\(/, `${f}: not in the constructor`);
    }
    assert.deepEqual(takers.sort(), ['cards/sem-next-devices-card.js', 'cards/sem-next-system-card.js']);
});

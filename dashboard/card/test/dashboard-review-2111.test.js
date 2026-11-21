/**
 * (#1321, review 21.11) Interaction gaps of the kind a user hit in #1397/#1398/#1400:
 * a charge-plan jump that waits forever, an Insights tab that ignores a link while the
 * card stays attached, a tab that is not remembered, folds that flip on resize, and
 * raw codes on screen.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

const { mount, S } = await import('./card-harness.js');
// after the harness: these load the cards' Lit, which the harness replaces
const { OPEN_CHARGE_PLAN_KEY, CHARGER_PREFIX } = await import('../src/util/next-devices.js');
const { SCROLL_WAIT_MS, _resetNarrow } = await import('../src/cards/sem-next-devices-card.js');
const { INSIGHTS_TAB_KEY } = await import('../src/cards/sem-next-insights-card.js');

const session = new Map();
globalThis.sessionStorage = {
    getItem: (k) => (session.has(k) ? session.get(k) : null),
    setItem: (k, v) => { session.set(k, String(v)); },
    removeItem: (k) => { session.delete(k); },
};
const local = new Map();
globalThis.localStorage = {
    getItem: (k) => (local.has(k) ? local.get(k) : null),
    setItem: (k, v) => { local.set(k, String(v)); },
    removeItem: (k) => { local.delete(k); },
};
const listeners = new Map();
globalThis.addEventListener = (ev, fn) => { listeners.set(ev, [...(listeners.get(ev) || []), fn]); };
globalThis.removeEventListener = (ev, fn) => { listeners.set(ev, (listeners.get(ev) || []).filter((f) => f !== fn)); };
const fire = (ev) => { for (const fn of listeners.get(ev) || []) fn({ type: ev }); };
globalThis.location = { pathname: '/sem-next/insights', hash: '' };

const CHARGER = { 'sensor.sem_charger_c1_power': S(0, { unit_of_measurement: 'W' }) };

// ── 1 · the charge-plan jump ───────────────────────────────────────────────
test('a charge-plan jump waits for a late charger, then gives up instead of jumping much later', () => {
    session.clear();
    session.set(OPEN_CHARGE_PLAN_KEY, 'c9');            // a charger not drawn (yet)
    const el = mount('sem-next-devices-card', CHARGER);
    el.connectedCallback();
    el.updated(new Map());
    assert.equal(el._open[CHARGER_PREFIX + 'c9'], true, 'its card is set to open when it appears');
    assert.equal(el._scrollTo, 'c9', 'still waiting to scroll to it');
    const real = Date.now;
    try {
        Date.now = () => real() + SCROLL_WAIT_MS + 1000;
        el.updated(new Map());
        assert.equal(el._scrollTo, null, 'after the wait it no longer jumps');
    } finally { Date.now = real; }
});

// ── 2 + 4 · the Insights tab ──────────────────────────────────────────────
test('a #car link opens the car tab while the Insights card stays attached', () => {
    local.clear(); listeners.clear();
    globalThis.location.hash = '';
    const el = mount('sem-next-insights-card', {});
    el.connectedCallback();
    assert.equal(el._tab, 'energy');
    globalThis.location.hash = '#car';                  // the charger's Sessions link
    fire('location-changed');
    assert.equal(el._tab, 'car');
    el.disconnectedCallback();
    assert.equal((listeners.get('location-changed') || []).length, 0, 'the listener goes with the card');
});

test('the Insights tab is remembered per user; a #tab in the address still wins', () => {
    local.clear(); listeners.clear();
    globalThis.location.hash = '';
    const a = mount('sem-next-insights-card', {});
    a.connectedCallback();
    a._pickTab('money');
    assert.equal(local.get(INSIGHTS_TAB_KEY), 'money');
    const b = mount('sem-next-insights-card', {});       // a reload: a new card
    b.connectedCallback();
    assert.equal(b._tab, 'money');
    globalThis.location.hash = '#battery';
    const c = mount('sem-next-insights-card', {});
    c.connectedCallback();
    assert.equal(c._tab, 'battery');
    local.set(INSIGHTS_TAB_KEY, 'gone_tab');             // a tab that no longer exists
    globalThis.location.hash = '';
    const d = mount('sem-next-insights-card', {});
    assert.equal(d._tab, 'energy');
    for (const el of [a, b, c]) el.disconnectedCallback();   // their refresh timers end
});

// ── 6 · folds do not flip on resize ───────────────────────────────────────
test('an untouched card keeps its fold when the window is resized across the phone width', () => {
    local.clear();
    _resetNarrow();
    let phone = false;
    globalThis.matchMedia = () => ({ matches: phone });
    const el = mount('sem-next-devices-card', CHARGER);
    const row = { id: 'load_x', type: 'load' };
    const before = el._isOpen(row);
    phone = !phone;                                      // the window crosses 720 px
    assert.equal(el._isOpen(row), before, 'decided once per page load');
});

// ── 9 · never a raw code on screen ───────────────────────────────────────
test('a code with no text shows a plain word, never the code', () => {
    const el = mount('sem-next-plan-card', {});
    globalThis.semLocalize = (k) => ({ next_status_fits: 'fits', next_code_unknown: 'Unknown' })[k] || k;
    try {
        assert.equal(el._tCode('next_status_', 'fits'), 'fits');
        assert.equal(el._tCode('next_status_', 'missed'), 'Unknown');
        assert.equal(el._tCode('next_health_', undefined), 'Unknown');
    } finally { delete globalThis.semLocalize; }
});

/**
 * #1055 follow-up — a grid limit saved on the Configuration tab did not
 * reach the Control tab's slider until a browser reload.
 *
 * A card does not draw on every hass push: it compares a few inputs and
 * draws only when one of them changed. The load list card compared three
 * sensors and none of them was the limit; with load management off all
 * three stand still, so it read the limit once and never again. The
 * Control and Home cards compared sensor states only, and "no grid limit"
 * is an attribute.
 *
 * Part 1 drives the real cards (Lit replaced by a stub, as in
 * reconnect.test.js). Part 2 reads the card sources: every sensor a card
 * reads must be in what its gate compares.
 *
 * Run: `npm test` (from dashboard/card).
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';
import { readFileSync, readdirSync } from 'node:fs';

// ── Part 1: the real cards, with a stub in place of lit ──────────────────

const FAKE_LIT = `
export class LitElement {
    constructor() { this.updates = 0; this.renderRoot = globalThis.__semFakeRoot(); this.style = {}; }
    connectedCallback() {}
    disconnectedCallback() {}
    requestUpdate() { this.updates++; }
    get updateComplete() { return Promise.resolve(true); }
}
const tag = () => '';
export const html = tag, css = tag, svg = tag;
export const nothing = Symbol('nothing');
export const unsafeSVG = (s) => s;
export const repeat = () => '';
`;
const LOADER = `
const FAKE = ${JSON.stringify('data:text/javascript,' + encodeURIComponent(FAKE_LIT))};
export async function resolve(specifier, context, next) {
    if (specifier === 'lit' || specifier.startsWith('lit/')) return { url: FAKE, shortCircuit: true };
    return next(specifier, context);
}`;
register('data:text/javascript,' + encodeURIComponent(LOADER));

globalThis.__semFakeRoot = () => ({
    querySelector: () => null, querySelectorAll: () => [], getElementById: () => null,
});
globalThis.window ??= globalThis;
globalThis.document ??= {
    addEventListener() {}, removeEventListener() {},
    documentElement: {}, head: { appendChild() {} }, createElement: () => ({}),
};
globalThis.addEventListener ??= () => {};
globalThis.removeEventListener ??= () => {};
const registry = new Map();
globalThis.customElements ??= { get: (t) => registry.get(t), define: (t, c) => registry.set(t, c) };
globalThis.getComputedStyle ??= () => ({ getPropertyValue: () => '' });
globalThis.localStorage ??= { getItem: () => null, setItem() {} };

const { LOAD_PRIORITY_READS } = await import('../src/cards/sem-load-priority-card.js');
await import('../src/cards/sem-control-card.js');
await import('../src/cards/sem-home-status-card.js');

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// A home with load management off: these three never change (#897).
function lmOffStates(limitKw, unlimited = false) {
    return {
        'sensor.sem_controllable_devices_count': { state: '0', attributes: { devices: {} } },
        'sensor.sem_consecutive_peak_15min': { state: '0.0', attributes: {} },
        'sensor.sem_load_management_status': { state: 'idle', attributes: {} },
        'sensor.sem_grid_power': { state: '0', attributes: {} },
        'sensor.sem_target_peak_limit': limit(limitKw, unlimited),
    };
}
const limit = (kw, unlimited = false) => ({
    state: String(kw), attributes: { peak_limit_unlimited: unlimited },
});
// HA's next hass: the same state objects, except the ones that changed.
const next = (hass, changed) => ({ ...hass, states: { ...hass.states, ...changed } });

function loadCard(callService = async () => {}) {
    const el = new (customElements.get('sem-load-priority-card'))();
    el.setConfig({ entity_prefix: 'sensor.sem_' });
    el.hass = { language: 'en', states: lmOffStates(7), callService };
    el.hass = next(el.hass, {});                     // HA sets hass again and again
    assert.equal(el.targetPeakLimit, 7, 'the card read the first limit');
    return el;
}

test('the load list reads a limit saved elsewhere while the other sensors stand still', () => {
    const el = loadCard();
    assert.equal(el.targetPeakLimit, 7);
    const before = el.updates;
    el.hass = next(el.hass, { 'sensor.sem_target_peak_limit': limit(9) });
    assert.equal(el.targetPeakLimit, 9, 'the slider kept the old limit');
    assert.ok(el.updates > before, 'the card did not draw again');
});

test('the load list reads "no grid limit" when only the flag changed', () => {
    const el = loadCard();
    el.hass = next(el.hass, { 'sensor.sem_target_peak_limit': limit(7, true) });
    assert.equal(el.peakLimitUnlimited, true);
    el.hass = next(el.hass, { 'sensor.sem_target_peak_limit': limit(7, false) });
    assert.equal(el.peakLimitUnlimited, false);
});

test('back on the Control tab, one hass push shows the limit saved while away', () => {
    const el = loadCard();
    el.disconnectedCallback();                       // leave for the Configuration tab
    const away = next(el.hass, { 'sensor.sem_target_peak_limit': limit(6) });
    el.connectedCallback();                          // HA puts the same card back
    el.hass = away;
    assert.equal(el.targetPeakLimit, 6);
});

test('an unrelated hass push does not draw the load list again', () => {
    const el = loadCard();
    const before = el.updates;
    el.hass = next(el.hass, { 'light.kitchen': { state: 'on', attributes: {} } });
    assert.equal(el.updates, before);
});

test('a slider value is kept until the sensor has it', () => {
    const el = loadCard();
    el._commitPeakLimit(10, false);
    // A push from before the save: the sensor still says 7.
    el.hass = next(el.hass, { 'sensor.sem_grid_power': { state: '120', attributes: {} } });
    assert.equal(el.targetPeakLimit, 10, 'the slider jumped back');
    el.hass = next(el.hass, { 'sensor.sem_target_peak_limit': limit(10) });
    assert.equal(el._peakHold, null, 'the hold ends when the sensor has the value');
    el.hass = next(el.hass, { 'sensor.sem_target_peak_limit': limit(12) });
    assert.equal(el.targetPeakLimit, 12, 'a later change elsewhere shows');
});

test('the slider at the top is kept as "no grid limit" until the flag arrives', () => {
    const el = loadCard();
    el._commitPeakLimit(80, true);
    el.hass = next(el.hass, { 'sensor.sem_grid_power': { state: '50', attributes: {} } });
    assert.equal(el.peakLimitUnlimited, true);
    // The sensor keeps its saved number while the flag is set.
    el.hass = next(el.hass, { 'sensor.sem_target_peak_limit': limit(7, true) });
    assert.equal(el._peakHold, null);
    assert.equal(el.peakLimitUnlimited, true);
});

test('a slider hold ends after its time even if the sensor never has the value', () => {
    const el = loadCard();
    el._commitPeakLimit(10, false);
    el._peakHold.until = Date.now() - 1;
    el.hass = next(el.hass, { 'sensor.sem_grid_power': { state: '80', attributes: {} } });
    assert.equal(el.targetPeakLimit, 7);
});

test('a refused older drag does not drop the hold of a newer one', async () => {
    let refuse;
    const calls = [];
    const el = loadCard((d, s, data) => {
        calls.push(data);
        return calls.length === 1 ? new Promise((_, rej) => { refuse = rej; }) : Promise.resolve();
    });
    el._commitPeakLimit(10, false);
    el._commitPeakLimit(12, false);
    refuse(new Error('refused'));
    await sleep(0);
    el.hass = next(el.hass, { 'sensor.sem_grid_power': { state: '90', attributes: {} } });
    assert.equal(el.targetPeakLimit, 12);
    clearTimeout(el._serviceErrorTimer);
});

test('a refused slider write shows the sensor again on the next push', async () => {
    const el = loadCard(async () => { throw new Error('refused'); });
    el._commitPeakLimit(10, false);
    await sleep(0);
    assert.equal(el._peakHold, null);
    el.hass = { ...el.hass };                         // nothing changed, a new hass
    assert.equal(el.targetPeakLimit, 7);
    clearTimeout(el._serviceErrorTimer);
});

// Cards on SEMLitBase's own gate: the update goes through _scheduleUpdate.
function spyCard(tag, states) {
    const el = new (customElements.get(tag))();
    el.setConfig({ entity_prefix: 'sensor.sem_' });
    let scheduled = 0;
    el._scheduleUpdate = () => { scheduled++; };
    el.hass = { language: 'en', states };
    return { el, scheduled: () => scheduled };
}
const watchedStates = (Card, extra) => Object.fromEntries(
    Card.watchedEntities.map((id) => [id, { state: '1', attributes: {} }])
        .concat(Object.entries(extra)));

for (const tag of ['sem-control-card', 'sem-home-status-card']) {
    test(`${tag} draws again when only "no grid limit" changed`, () => {
        const Card = customElements.get(tag);
        const { el, scheduled } = spyCard(tag, watchedStates(Card, {
            'sensor.sem_target_peak_limit': limit(7, false),
        }));
        const before = scheduled();
        el.hass = next(el.hass, { 'sensor.sem_target_peak_limit': limit(7, true) });
        assert.equal(scheduled(), before + 1);
        el.hass = next(el.hass, { 'sensor.sem_target_peak_limit': limit(8, true) });
        assert.equal(scheduled(), before + 2, 'a new limit draws too');
        el.hass = next(el.hass, { 'sensor.sem_target_peak_limit': limit(8, true) });
        assert.equal(scheduled(), before + 2, 'the same values do not draw');
    });
}

// ── Part 2: what a card reads is in what its gate compares ───────────────

const CARD_DIR = new URL('../src/cards/', import.meta.url);
const source = (f) => readFileSync(new URL(f, CARD_DIR), 'utf8');

test('the load list compares every SEM sensor it reads', () => {
    const src = source('sem-load-priority-card.js');
    const reads = new Set([...src.matchAll(/\$\{this\.entityPrefix\}([a-z0-9_]+)`/g)].map((m) => m[1]));
    assert.ok(reads.has('target_peak_limit'), 'the check reads nothing');
    const missing = [...reads].filter((s) => !LOAD_PRIORITY_READS.includes(s));
    assert.deepEqual(missing, [], 'read but not compared');
    assert.doesNotMatch(src, /_lastKey/, 'a second, hand-made key is back');
});

// Read but not watched, on purpose. Each needs a reason.
const NOT_WATCHED = {
    // The Hot water live block reads sensors SEM does not create
    // (`hot_water_registered` never exists), so the block never shows.
    'sem-config-card.js': ['hot_water_current_temperature', 'hot_water_solar_target',
        'hot_water_hours_since_legionella', 'hot_water_temperature_reading_path',
        'hot_water_temperature_safety_path', 'hot_water_activation_path'],
};

// Cards that keep SEMLitBase's gate: no hass setter of their own, or one
// that hands hass to the base.
function baseGatedCards() {
    return readdirSync(CARD_DIR).filter((f) => f.startsWith('sem-') && f.endsWith('.js'))
        .filter((f) => {
            const src = source(f);
            if (!/extends SEMLitBase/.test(src)) return false;
            return !/\bset hass\(/.test(src) || /super\.hass\s*=/.test(src);
        });
}

test('every card on the base gate watches each sensor it reads', async () => {
    const files = baseGatedCards();
    assert.ok(files.includes('sem-control-card.js') && files.includes('sem-home-status-card.js'),
        `the card list is wrong: ${files}`);
    const problems = [];
    for (const f of files) {
        await import(new URL(f, CARD_DIR));
        const src = source(f);
        const tag = src.match(/semDefineCard\(\s*'([a-z-]+)'/)?.[1]
            ?? src.match(/customElements\.define\(\s*'([a-z-]+)'/)?.[1];
        const Card = customElements.get(tag);
        if (!Card) { problems.push(`${f}: no card found`); continue; }
        const watched = new Set((Card.watchedEntities || []).map((id) => id.split('.sem_')[1]));
        const reads = new Set([
            ...[...src.matchAll(/_val(?:Num|Str|Label)?\(\s*'([a-z0-9_]+)'/g)].map((m) => m[1]),
            ...[...src.matchAll(/\$\{this\._prefix\}([a-z0-9_]+)`/g)].map((m) => m[1]),
        ]);
        const allowed = NOT_WATCHED[f] || [];
        for (const r of reads) {
            if (!watched.has(r) && !allowed.includes(r)) problems.push(`${f}: reads ${r}, does not watch it`);
        }
        for (const r of allowed) {
            if (!reads.has(r) || watched.has(r)) problems.push(`${f}: ${r} is allowed but no longer needs it`);
        }
        // The "no grid limit" flag is an attribute: a state compare misses it.
        if (/isUncapped\(|peakLimitText\(|attributes\??\.peak_limit_unlimited/.test(src)) {
            const names = Card.watchedAttributes?.['sensor.sem_target_peak_limit'] || [];
            if (!names.includes('peak_limit_unlimited')) problems.push(`${f}: shows "no grid limit", does not watch the flag`);
        }
        for (const id of Object.keys(Card.watchedAttributes || {})) {
            if (!(Card.watchedEntities || []).includes(id)) problems.push(`${f}: watches attributes of ${id}, not the entity`);
        }
    }
    assert.deepEqual(problems, []);
});

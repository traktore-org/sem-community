/**
 * (#1397, class 187) A link between SEM's screens goes to the dashboard the
 * user is on. The SEM dashboard has no fixed address: a migrated install keeps
 * /sem-dashboard, generate_dashboard takes any dashboard_path, a fresh one is
 * /sem-next. Beta.18-20 sent "Charge by" on Plan to /sem-next/devices; on a
 * dashboard elsewhere Home Assistant has no such page and opens its own start
 * dashboard. Each link now swaps the last part of the address (the screen) and
 * keeps the dashboard.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

const { mount, S } = await import('./card-harness.js');
const { sibling, rowTarget } = await import('../src/util/setup-checklist.js');
const { navTarget } = await import('../src/util/next-settings.js');

const DASHBOARDS = ['sem-dashboard', 'sem-next', 'my-energy'];

globalThis.location = { pathname: '/sem-next/plan', hash: '', search: '' };
const pushed = [];
const events = [];
globalThis.history = { pushState: (_s, _t, url) => { pushed.push(url); } };
globalThis.CustomEvent = globalThis.CustomEvent || class { constructor(type, init) { this.type = type; this.detail = init?.detail; } };
globalThis.dispatchEvent = (e) => { events.push(e.type); return true; };
globalThis.sessionStorage = { getItem: () => null, setItem() {}, removeItem() {} };

const CHARGER = { 'sensor.sem_charger_c1_power': S(0, { unit_of_measurement: 'W' }) };

test('"Charge by" on Plan opens Devices on the same dashboard, whatever its address', () => {
    for (const dash of DASHBOARDS) {
        globalThis.location.pathname = `/${dash}/plan`;
        pushed.length = 0;
        events.length = 0;
        const plan = mount('sem-next-plan-card', CHARGER);
        plan._openChargePlan('c1');     // the real button handler and the real _go
        assert.deepEqual(pushed, [`/${dash}/devices`], dash);
        assert.deepEqual(events, ['location-changed'], 'HA is told the page moved');
    }
});

test('every card asks for a screen of the dashboard it is on', () => {
    for (const tag of ['sem-next-now-card', 'sem-next-plan-card', 'sem-next-devices-card', 'sem-next-insights-card', 'sem-next-system-card']) {
        for (const dash of DASHBOARDS) {
            globalThis.location.pathname = `/${dash}/now`;
            const el = mount(tag, CHARGER);
            for (const view of ['now', 'plan', 'devices', 'insights', 'system']) {
                assert.equal(el._screen(view), `/${dash}/${view}`, `${tag} on /${dash}`);
            }
        }
    }
});

test('the address helpers keep the dashboard and swap the screen', () => {
    for (const dash of DASHBOARDS) {
        assert.equal(sibling(`/${dash}/plan`, 'devices'), `/${dash}/devices`);
        assert.equal(sibling(`/${dash}/plan/`, 'devices'), `/${dash}/devices`, 'a closing slash');
        assert.equal(navTarget(`/${dash}/system`, 'open_battery'), `/${dash}/devices`);
        assert.equal(rowTarget('charger', `/${dash}/now`).path, `/${dash}/devices`);
        assert.equal(rowTarget('forecast', `/${dash}/now`).path, `/${dash}/system`);
    }
    assert.equal(rowTarget('repairs', '/sem-dashboard/now').path, '/config/repairs', "HA's own page");
});

function sources(dir) {
    return readdirSync(dir).flatMap((f) => {
        const p = join(dir, f);
        return statSync(p).isDirectory() ? sources(p) : (p.endsWith('.js') ? [p] : []);
    });
}

const SRC = new URL('../src/', import.meta.url).pathname;
const FIXED_SEM_ADDRESS = /['"`]\/(sem-next|sem-dashboard)\b/;

test('no card names a fixed SEM dashboard address', () => {
    const files = sources(SRC);
    assert.ok(files.length > 20, 'the scan reads the cards');
    const hits = files.filter((f) => FIXED_SEM_ADDRESS.test(readFileSync(f, 'utf8')));
    assert.deepEqual(hits, []);
    const bundle = readFileSync(new URL('../dist/sem-cards.js', import.meta.url), 'utf8');
    assert.ok(!FIXED_SEM_ADDRESS.test(bundle), 'the built bundle has none either');
});

test("a card's _go with a written address only goes to Home Assistant's own pages", () => {
    // an address starts with '/'; the checklist card's own _go(key) takes a row name
    const literal = /_go\(\s*['"`](\/[^'"`]*)['"`]/g;
    let seen = 0;
    for (const f of sources(SRC)) {
        for (const m of readFileSync(f, 'utf8').matchAll(literal)) {
            seen += 1;
            assert.ok(m[1].startsWith('/config/'), `${f}: _go('${m[1]}')`);
        }
    }
    assert.ok(seen > 0, 'the scan finds the /config links');
});

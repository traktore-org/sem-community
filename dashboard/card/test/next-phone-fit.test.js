// (#1321) Phone fit: the "at least" label stays inside the card, and a row of
// many modes becomes a dropdown on a narrow screen.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mount, S } from './card-harness.js';

const { chargerBody } = await import('../src/util/next-devices-charger.js');

// collect every class string a template draws, through nested templates
function classes(part, out = []) {
    if (!part || typeof part !== 'object') return out;
    if (Array.isArray(part)) { part.forEach((p) => classes(p, out)); return out; }
    if (part.tpl) {
        part.strings.forEach((s, i) => {
            const m = /class="([^"]*)$/.exec(s);
            if (m) out.push(m[1] + String(part.values[i] ?? ''));
        });
        part.values.forEach((v) => classes(v, out));
    }
    return out;
}

function body(minKwh, maxKwh) {
    const st = {
        'switch.sem_observer_mode': S('off'), 'sensor.sem_charging_state': S('idle'),
        'sensor.sem_charger_keba_power': S(4000, { charger_name: 'EV Charger' }),
        'select.sem_charger_keba_ev_target_type': S('kwh', { options: ['kwh', 'soc'] }),
        'number.sem_charger_keba_daily_ev_target': S(minKwh, { min: 0, max: 200, step: 1 }),
        'number.sem_charger_keba_daily_ev_target_max': S(maxKwh, { min: 0, max: 200, step: 1 }),
    };
    const el = mount('sem-next-devices-card', st);
    el._chargers = ['keba'];
    return chargerBody(el, { cid: 'keba', type: 'charger' });
}

test('a target near the left edge: the label grows to the right, inside the card', () => {
    // 8 kWh of a 100 kWh scale sits at 8 % — the screenshot's case
    const flag = classes(body(8, 100)).find((c) => /^flag\b/.test(c));
    assert.ok(flag, 'the at-least flag is drawn');
    assert.match(flag, /\bstart\b/);
});

test('a target in the middle keeps the centred label', () => {
    const flag = classes(body(50, 100)).find((c) => /^flag\b/.test(c));
    assert.ok(flag);
    assert.doesNotMatch(flag, /\b(start|end)\b/);
});

test('six modes on a phone: a dropdown, not a row of cut labels', () => {
    const real = globalThis.matchMedia;
    globalThis.matchMedia = (q) => ({ matches: /max-width: 600px/.test(q) });
    try {
        const el = mount('sem-next-devices-card', {});
        let picked = null;
        el._select = (opts, cur, onChange) => { picked = { opts, cur, onChange }; return 'select'; };
        const items = ['off', 'solar_only', 'solar_plus_battery', 'solar_plus_cheap', 'min_plus_solar', 'always_max']
            .map((k) => ({ key: k, label: k }));
        let chosen = null;
        assert.equal(el._seg(items, 'min_plus_solar', (k) => { chosen = k; }), 'select');
        assert.equal(picked.opts.length, 6);
        picked.onChange('solar_only');
        assert.equal(chosen, 'solar_only', 'the dropdown writes through the same pick');
        // four or fewer stay buttons
        picked = null;
        el._seg(items.slice(0, 4), 'off', () => {});
        assert.equal(picked, null);
    } finally { globalThis.matchMedia = real; }
});

test('a wide screen keeps the buttons', () => {
    const real = globalThis.matchMedia;
    globalThis.matchMedia = () => ({ matches: false });
    try {
        const el = mount('sem-next-devices-card', {});
        let picked = null;
        el._select = () => { picked = true; return 'select'; };
        el._seg([1, 2, 3, 4, 5, 6].map((k) => ({ key: k, label: String(k) })), 1, () => {});
        assert.equal(picked, null);
    } finally { globalThis.matchMedia = real; }
});

// (#1321) From the owner's phone: a chart chip into the card's edge, "Cheapest
// hours" on a one-rate tariff, and "Copy failed" on an iPhone over plain http.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mount, S } from './card-harness.js';

test('a chart chip near the right edge stays inside the chart', () => {
    const el = mount('sem-next-plan-card', {});
    const W = 320;
    const chip = el._svgChip(W - 10, 20, '13.7 kWh tomorrow', '#f90', '#000', 0, W);
    const x = Number(chip.values[0]), w = Number(chip.values[2]);
    assert.ok(x + w <= W, `chip ends at ${x + w}, chart is ${W} wide`);
    assert.ok(w >= '13.7 kWh tomorrow'.length * 7.2 + 14, 'the width allows for bold digits plus padding');
});

const WORDS = { next_reason_cheapest_hours: 'Cheapest hours', next_reason_one_rate: 'One rate', next_tip_price: '{price} {cur}' };
function withWords(el) {
    el._t = (k) => WORDS[k] ?? k;
    el._tf = (k, p = {}) => String(WORDS[k] ?? k).replace(/\{(\w+)\}/g, (_, n) => p[n] ?? '');
    return el;
}

test('one rate all day: a block never reads "Cheapest hours"', () => {
    const flat = { 'sensor.sem_tariff_current_import_rate': S(0.36, { is_dynamic: false }), 'sensor.sem_tariff_price_level': S('flat') };
    const el = withWords(mount('sem-next-plan-card', flat));
    const out = el._reasonText('cheapest_hours', { price: 0.36 });
    assert.doesNotMatch(out, /next_reason_cheapest_hours|Cheapest/);
    assert.match(out, /next_reason_one_rate|One rate/);
});

test('a dynamic tariff keeps "Cheapest hours"', () => {
    const dyn = { 'sensor.sem_tariff_current_import_rate': S(0.2, { is_dynamic: true }), 'sensor.sem_tariff_price_level': S('cheap') };
    const el = withWords(mount('sem-next-plan-card', dyn));
    assert.match(el._reasonText('cheapest_hours', {}), /next_reason_cheapest_hours|Cheapest/);
});

test('copy refused by the browser: the text opens selected for a copy by hand', async () => {
    const el = mount('sem-next-system-card', {});
    const realNav = globalThis.navigator, realDoc = globalThis.document;
    let shown = null;
    el._showCopyText = (t) => { shown = t; };
    el._say = () => {};
    try {
        Object.defineProperty(globalThis, 'navigator', { value: {}, configurable: true });
        globalThis.document = { ...realDoc, execCommand: () => false,
            createElement: () => ({ style: {}, focus() {}, select() {}, setSelectionRange() {} }),
            body: { appendChild() {}, removeChild() {} } };
        const ok = await el._writeClipboard('SEM 2.3 | Grid: …');
        assert.equal(ok, false);
        assert.equal(shown, 'SEM 2.3 | Grid: …');
    } finally {
        Object.defineProperty(globalThis, 'navigator', { value: realNav, configurable: true });
        globalThis.document = realDoc;
    }
});

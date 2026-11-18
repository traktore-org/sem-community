// (#1321) The Now headline stays one line: many charge runs are counted, not listed.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mount, S } from './card-harness.js';

const at = (h, m = 0, d = 18) => Date.parse(`2026-11-${d}T${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:00+01:00`);
const iso = (ms) => new Date(ms).toISOString();

function fact(blocks) {
    const real = Date.now; Date.now = () => at(22, 30);
    try {
        const el = mount('sem-next-now-card', {
            'sensor.sem_charger_keba_power': S(0), 'binary_sensor.sem_charger_keba_connected': S('on'),
            'sensor.sem_energy_plan': S('fits', { blocks, demands: [{ id: 'ev:keba', needed_kwh: 10, planned_kwh: 9.4 }] }),
        });
        Object.defineProperty(el, '_chargers', { get: () => ['keba'] });
        el._remainingKwh = () => 10;
        el._winText = (a, b) => `${new Date(a).getUTCHours()}–${new Date(b).getUTCHours()}`;
        el._tf = (k, p) => `${k}:${p.n}:${p.window}`;
        return el._carFact();
    } finally { Date.now = real; }
}
const run = (h0, h1, d = 18) => ({ id: 'ev:keba', start: iso(at(h0, 0, d)), end: iso(at(h1, 0, d)), power_w: 4000 });

test('four runs: counted with the span from the first start to the last end', () => {
    const f = fact([run(23, 24), run(1, 2, 19), run(3, 4, 19), run(6, 7, 19)]);
    assert.match(f.planWindow, /^next_runs_span:4:/);
    assert.equal(f.planWindow.split(',').length, 1, 'no list of windows');
});

test('two runs are still named one by one', () => {
    const f = fact([run(23, 24), run(1, 2, 19)]);
    assert.doesNotMatch(f.planWindow, /next_runs_span/);
    assert.equal(f.planWindow.split(', ').length, 2);
});

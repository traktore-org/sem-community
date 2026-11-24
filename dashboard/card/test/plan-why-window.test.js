// (#1418) "Cheapest hours" is judged inside the plan's window only.
import test from 'node:test';
import assert from 'node:assert/strict';
import './card-harness.js';
const { whyLines, gotCheapest } = await import('../src/util/plan-why.js');

const NOW = Date.parse('2026-11-23T21:52:00+01:00');
const at = (s) => new Date(Date.parse(s)).toISOString();
// 15-minute prices from 21:45 to the end of tomorrow: 0.22 at night, 0.10 tomorrow 12:00-15:00, else 0.40
const upcoming = [];
for (let t = Date.parse('2026-11-23T21:45:00+01:00'); t < Date.parse('2026-11-25T00:00:00+01:00'); t += 900e3) {
    const h = new Date(t).getUTCHours() + 1;   // CET
    const day2 = t >= Date.parse('2026-11-24T00:00:00+01:00');
    const price = day2 && h >= 2 && h < 5 ? 0.22 : (day2 && h >= 12 && h < 15 ? 0.10 : 0.40);
    upcoming.push({ t: new Date(t).toISOString(), price });
}
const plan = (endsAt) => ({
    ends_at: endsAt,
    blocks: [{ id: 'ev:c1', start: at('2026-11-24T02:00:00+01:00'), end: at('2026-11-24T05:00:00+01:00'), power_w: 5000, reason: 'cheapest_hours' }],
    demands: [{ id: 'ev:c1', planned_kwh: 15, why: { code: 'cheapest_hours', params: { from: at('2026-11-24T02:00:00+01:00'), to: at('2026-11-24T05:00:00+01:00'), price: 0.22 } } }],
});
const runs = [{ s: Date.parse('2026-11-24T02:00:00+01:00'), e: Date.parse('2026-11-24T05:00:00+01:00') }];

test('(#1418) cheaper hours after the plan ends do not make the night "the cheapest left"', () => {
    const p = plan(at('2026-11-24T07:00:00+01:00'));
    assert.equal(gotCheapest(p, runs, 0.22, NOW, upcoming), true);
    assert.equal(whyLines(p, NOW, 4, upcoming)[0].code, 'cheapest_hours');
});

test('(#1418) inside the window a cheaper hour still says another demand took it', () => {
    const p = plan(at('2026-11-24T16:00:00+01:00'));   // a plan that reaches the midday low
    assert.equal(gotCheapest(p, runs, 0.22, NOW, upcoming), false);
    assert.equal(whyLines(p, NOW, 4, upcoming)[0].code, 'cheapest_left');
});

test('(#1418) a plan with no known end compares the whole list, as before', () => {
    const p = plan(undefined);
    assert.equal(gotCheapest(p, runs, 0.22, NOW, upcoming), false);
});

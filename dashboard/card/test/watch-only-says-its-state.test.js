/**
 * (#1377, beta.21 retest) What the Plan and System screens say about control
 * must follow the two switches that decide it: watch-only and plan execution.
 *
 * The reporter read "Watch only: enabled — SEM only observes and sends no
 * commands" on the System screen while the Plan screen said SEM controls the
 * devices. Watch-only was off: the System line was the French help text
 * "Activé, SEM observe seulement…", shown under the switch whatever it read.
 * Two more lines said a state their switch did not have: the Plan pill read
 * "Live" while watch-only held every write, and "SEM controls devices from
 * this plan" stood beside a plan switch that was off.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

const { mount, S, text } = await import('./card-harness.js');

const PLAN = { computed_at: '2026-11-20T23:00:00+01:00', blocks: [], demands: [] };
const states = (watch, plan) => ({
    'switch.sem_observer_mode': S(watch),
    'switch.sem_energy_plan_actuation': S(plan),
    'sensor.sem_energy_plan': S('fits', PLAN),
});
const COMBOS = [['on', 'on'], ['on', 'off'], ['off', 'on'], ['off', 'off']];
// what the backend publishes: ``actuation`` follows the plan switch alone
const actuation = (plan) => plan === 'on';

test('System: the watch-only line says the state the switch shows', () => {
    const on = text(mount('sem-next-system-card', states('on', 'on'))._observerRow());
    assert.match(on, /next_observer_on_sub/);
    assert.doesNotMatch(on, /next_observer_off_sub/);
    const off = text(mount('sem-next-system-card', states('off', 'on'))._observerRow());
    assert.match(off, /next_observer_off_sub/);
    assert.doesNotMatch(off, /next_observer_on_sub/);
});

test('Plan pill: never "Live" while watch-only is on or the plan switch is off', () => {
    for (const [watch, plan] of COMBOS) {
        const el = mount('sem-next-plan-card', states(watch, plan));
        const out = text(el._stripPills({ ...PLAN, actuation: actuation(plan) }));
        const live = watch === 'off' && plan === 'on';
        assert.equal(/next_pill_live/.test(out), live, `watch ${watch}, plan ${plan}: ${out}`);
        if (watch === 'on') assert.match(out, /next_pill_observing/, 'watch-only is named');
    }
});

test('Plan row: "SEM controls devices" only with watch-only off and the plan switch on', () => {
    for (const [watch, plan] of COMBOS) {
        const el = mount('sem-next-plan-card', states(watch, plan));
        const out = text(el._expectedSec(el._plan(), el._model()));
        const acts = watch === 'off' && plan === 'on';
        assert.equal(/next_actuation_sub/.test(out), acts, `watch ${watch}, plan ${plan}`);
        if (watch === 'on') assert.match(out, /next_actuation_watch/);
        else if (plan === 'off') assert.match(out, /next_actuation_off/);
    }
});

test('the header chip and the plan pill agree on watch-only', () => {
    for (const [watch, plan] of COMBOS) {
        const el = mount('sem-next-plan-card', states(watch, plan));
        const chip = text(el._renderHead());
        const pill = text(el._stripPills({ ...PLAN, actuation: actuation(plan) }));
        if (/next_pill_live/.test(pill)) assert.match(chip, /next_pill_live/, `watch ${watch}, plan ${plan}`);
        if (watch === 'on') assert.match(chip, /next_pill_observing/);
    }
});

test('(review) a switch that reads neither on nor off gets no state line, and no "Live"', () => {
    for (const [watch, plan] of [['unavailable', 'on'], ['off', 'unavailable'], ['unknown', 'off']]) {
        const el = mount('sem-next-plan-card', states(watch, plan));
        const row = text(el._expectedSec(el._plan(), el._model()));
        assert.doesNotMatch(row, /next_actuation_(sub|off|watch)/, `watch ${watch}, plan ${plan}`);
        const pill = text(el._stripPills({ ...PLAN, actuation: true }));
        if (watch !== 'off') assert.doesNotMatch(pill, /next_pill_live/, `watch ${watch}`);
    }
    const sys = text(mount('sem-next-system-card', states('unavailable', 'on'))._observerRow());
    assert.doesNotMatch(sys, /next_observer_(on|off)_sub/);
});

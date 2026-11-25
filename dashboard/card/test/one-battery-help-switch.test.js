/**
 * (#1381) One battery-help switch: the charger's. The battery card no longer
 * carries an install-wide "May the battery help charge the car?"; its levels
 * stay, under a line saying they are used when a charger allows battery help.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

await import('./card-harness.js');
const { BATTERY_QUESTIONS } = await import('../src/util/battery-questions.js');

test('the battery card has no install-wide battery-help switch any more', () => {
    assert.equal(BATTERY_QUESTIONS.may_assist, undefined);
    const src = readFileSync(new URL('../src/util/next-devices-battery.js', import.meta.url), 'utf8');
    assert.doesNotMatch(src, /sem_battery_may_assist_ev|Q\.may_assist/);
    assert.match(src, /next_batt_help_used_when/);
});

test('no screen reads the removed switch', () => {
    for (const f of ['cards/sem-next-devices-card.js', 'cards/sem-next-system-card.js', 'cards/sem-next-now-card.js']) {
        const src = readFileSync(new URL('../src/' + f, import.meta.url), 'utf8');
        assert.doesNotMatch(src, /switch\.sem_battery_may_assist_ev/, f);
    }
});

test('the charger switch says when the battery really helps', () => {
    const en = JSON.parse(readFileSync(new URL('../../translations.json', import.meta.url))).en;
    assert.doesNotMatch(en.next_battery_help_on, /any hour/i);
    assert.match(en.next_battery_help_on, /spare sun after the house/);
    assert.match(en.next_battery_help_on, /at night only if/);
    assert.equal(en.next_batt_help_used_when, 'Used when a charger allows battery help.');
});

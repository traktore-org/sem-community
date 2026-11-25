/**
 * (#1427) A battery SEM cannot cap: the watch-only list and the Why? log say
 * "cannot stop powering the car" with no "limited to" figure.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { setsLimit, wouldVerb, commandLabel, WHY_VERBS, plainReason } from '../src/util/why-rows.js';

const tr = JSON.parse(readFileSync(new URL('../../translations.json', import.meta.url), 'utf8'));
const en = (k) => tr.en[k] || k;

const noLimit = { kind: 'battery', device_id: 'battery:b1', action: 'no_limit', power_w: 0, reason_code: 'battery_no_limit' };
const limit = { kind: 'battery', device_id: 'battery:b1', action: 'limit_discharge', power_w: 4500 };

test('a battery SEM cannot cap shows no limit figure', () => {
    assert.equal(setsLimit(noLimit), false);
    assert.equal(setsLimit(limit), true, 'twin: a real limit still shows its figure');
});

test('the would-row and the log say SEM cannot, never that it stops the car', () => {
    assert.equal(wouldVerb(noLimit, en), en('next_act_no_limit'));
    assert.notEqual(wouldVerb(noLimit, en), en('next_act_limit_discharge'));
    assert.equal(commandLabel('no_limit', en), en('why_verb_no_limit'));
    assert.ok(WHY_VERBS.includes('no_limit'));
    assert.equal(plainReason(noLimit, en), en('why_reason_battery_no_limit'));
});

test('every language has the words', () => {
    for (const [lang, table] of Object.entries(tr)) {
        for (const key of ['next_act_no_limit', 'why_verb_no_limit', 'why_reason_battery_no_limit']) {
            assert.ok(table[key], `${lang} ${key}`);
        }
    }
});

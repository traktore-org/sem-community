import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { batteryListEdit } from '../src/util/battery-slot-edit.js';

const KEY = 'battery_discharge_control_entities';

describe('batteryListEdit (#1204)', () => {
    it('sends only the changed slot, with the battery order the copy was read in', () => {
        const opts = {
            battery_slot_units: ['sensor.a_power', 'sensor.b_power'],
            [KEY]: ['number.a_limit', 'number.b_limit'],
        };
        const { payload } = batteryListEdit(opts, KEY, 1, 'number.b_new', 2);
        assert.deepEqual(payload, { [KEY]: {
            slot: 1, value: 'number.b_new',
            battery_slot_units: ['sensor.a_power', 'sensor.b_power'] } });
    });
    it('the list shown until the next read is the copy with the slot set', () => {
        const opts = { [KEY]: ['number.a_limit'] };
        const { shown } = batteryListEdit(opts, KEY, 2, 'number.c', 3);
        assert.deepEqual(shown, { [KEY]: ['number.a_limit', null, 'number.c'] });
    });
    it('an emptied slot is null', () => {
        const { payload } = batteryListEdit({}, KEY, 0, '', 2);
        assert.equal(payload[KEY].value, null);
    });
    it('a copy that failed to read sends no order and no other slot', () => {
        // the old whole list was [null, value]: it emptied B1
        const { payload } = batteryListEdit({}, KEY, 1, 'number.b', 2);
        assert.deepEqual(payload, { [KEY]: { slot: 1, value: 'number.b', battery_slot_units: null } });
    });
    it('does not change the copy it was given', () => {
        const opts = { battery_slot_units: ['sensor.a'], [KEY]: ['number.a'] };
        batteryListEdit(opts, KEY, 0, 'number.x', 1);
        assert.deepEqual(opts, { battery_slot_units: ['sensor.a'], [KEY]: ['number.a'] });
    });
    it('the Config card saves a per-battery list only through it', () => {
        const src = readFileSync(new URL('../src/cards/sem-config-card.js', import.meta.url), 'utf8');
        const body = src.slice(src.indexOf('async _saveListField('));
        const fn = body.slice(0, body.indexOf('\n    }\n') + 6);
        assert.match(fn, /batteryListEdit\(/);
        assert.match(fn, /_refreshOptions\(\)/);
        assert.doesNotMatch(fn, /_saveOption\(listKey/);
    });
});

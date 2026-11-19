/**
 * (#1224) One "Use this" click on half of a split grid pair saves the whole
 * pair, in one write. Saving only the clicked half read the other half as
 * 0 W: a home that sends power to the grid looked like it never does.
 */
import { test } from 'node:test';
import assert from 'node:assert';
import { readFileSync } from 'node:fs';
import { proposalWrite, writeIsSaved } from '../src/util/detect-rows.js';

const IMP = 'grid_import_power_entity';
const EXP = 'grid_export_power_entity';
// each choice of a half → the other half's choices on the same device
const impRow = { config_key: IMP, entity: 'sensor.imp', action: 'set_option', pair: {
    'sensor.imp': { [EXP]: ['sensor.exp'] },
    'sensor.imp2': { [EXP]: ['sensor.exp'] },
} };
const expRow = { config_key: EXP, entity: 'sensor.exp', action: 'set_option', pair: {
    'sensor.exp': { [IMP]: ['sensor.imp', 'sensor.imp2'] },
} };

test('a click on either half saves both', () => {
    const both = { [IMP]: 'sensor.imp', [EXP]: 'sensor.exp' };
    assert.deepEqual(proposalWrite(impRow, 'sensor.imp', {}), both);
    assert.deepEqual(proposalWrite(expRow, 'sensor.exp', {}), both);
});

test('an alternative pairs with the other half', () => {
    assert.deepEqual(proposalWrite(impRow, 'sensor.imp2', {}),
        { [IMP]: 'sensor.imp2', [EXP]: 'sensor.exp' });
});

test("the other half keeps the user's earlier choice from this device", () => {
    const saved = { [IMP]: 'sensor.imp2' };
    assert.deepEqual(proposalWrite(expRow, 'sensor.exp', saved),
        { [IMP]: 'sensor.imp2', [EXP]: 'sensor.exp' });
});

test('a saved half from another device is replaced, never mixed in', () => {
    const saved = { [IMP]: 'sensor.other_meter' };
    assert.deepEqual(proposalWrite(expRow, 'sensor.exp', saved),
        { [IMP]: 'sensor.imp', [EXP]: 'sensor.exp' });
});

test('two meters of one integration never mix', () => {
    const row = { config_key: IMP, entity: 'sensor.a_imp', pair: {
        'sensor.a_imp': { [EXP]: ['sensor.a_exp'] },
        'sensor.b_imp': { [EXP]: ['sensor.b_exp'] },
    } };
    // home B's pair is saved; a click on home A's import saves home A's pair
    const saved = { [IMP]: 'sensor.b_imp', [EXP]: 'sensor.b_exp' };
    assert.deepEqual(proposalWrite(row, 'sensor.a_imp', saved),
        { [IMP]: 'sensor.a_imp', [EXP]: 'sensor.a_exp' });
    assert.deepEqual(proposalWrite(row, 'sensor.b_imp', {}),
        { [IMP]: 'sensor.b_imp', [EXP]: 'sensor.b_exp' });
});

test('a choice with no partner on its device saves nothing', () => {
    assert.equal(proposalWrite(impRow, 'sensor.elsewhere', {}), null);
    const empty = { config_key: IMP, pair: { 'sensor.x': { [EXP]: [] } } };
    assert.equal(proposalWrite(empty, 'sensor.x', {}), null);
    assert.equal(proposalWrite({ config_key: IMP, pair: { 'sensor.x': {} } }, 'sensor.x', {}), null);
});

test('one entity is never both halves', () => {
    const odd = { config_key: IMP, pair: { 'sensor.x': { [EXP]: ['sensor.x'] } } };
    assert.equal(proposalWrite(odd, 'sensor.x', {}), null);
    const self = { config_key: IMP, pair: { 'sensor.x': { [IMP]: ['sensor.y'] } } };
    assert.equal(proposalWrite(self, 'sensor.x', {}), null);
});

test('a role outside a pair saves its own key only', () => {
    assert.deepEqual(proposalWrite({ config_key: 'battery_soc_sensor' }, 'sensor.soc', {}),
        { battery_soc_sensor: 'sensor.soc' });
    assert.equal(proposalWrite({ config_key: null }, 'sensor.soc', {}), null);
    assert.equal(proposalWrite({ config_key: 'k' }, undefined, {}), null);
});

test('a half saved alone is not "in use": the pair is not whole', () => {
    const write = proposalWrite(expRow, 'sensor.exp', { [IMP]: 'sensor.imp' });
    assert.equal(writeIsSaved(write, { [IMP]: 'sensor.imp' }), false);
    assert.equal(writeIsSaved(write, { [IMP]: 'sensor.imp', [EXP]: 'sensor.exp' }), true);
});

test('nothing to write is never "in use"', () => {
    // a service-shaped proposal (no entity, no option key) used to read as
    // "in use": undefined === undefined
    assert.equal(writeIsSaved(null, {}), false);
    assert.equal(writeIsSaved(proposalWrite({ config_key: null }, undefined, {}), {}), false);
});

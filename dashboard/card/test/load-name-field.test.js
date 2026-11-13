/**
 * (#1341) The load editor's name field: a load's own name in SEM.
 */
import { test } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import {
    LOAD_NAME_MAX, cleanLoadName, buildLoadConfigModalHTML,
} from '../src/cards/load-config-modal.js';

const here = new URL('.', import.meta.url);
const words = JSON.parse(fs.readFileSync(new URL('../../translations.json', here), 'utf8'));
const t = (k) => k;
const values = { type: 'switch', entity: '', service: '', param: '', shed_value: '', restore_value: '' };

test('a typed name is one trimmed line, capped', () => {
    assert.equal(cleanLoadName('  Pool   pump \n'), 'Pool pump');
    assert.equal(cleanLoadName(''), '');
    assert.equal(cleanLoadName(null), '');
    assert.equal(cleanLoadName('x'.repeat(200)).length, LOAD_NAME_MAX);
});

test('a load gets the field, filled with its own name', () => {
    const html = buildLoadConfigModalHTML({
        deviceName: 'Pool pump', values, t, ownName: 'Pool pump', autoName: 'Boiler' });
    assert.ok(html.includes('id="cfg-name"'));
    assert.ok(html.includes('value="Pool pump"'));
    assert.ok(html.includes('placeholder="Boiler"'));
    assert.ok(html.includes('maxlength="' + LOAD_NAME_MAX + '"'));
});

test('no own name: the field is empty and hints at the automatic name', () => {
    const html = buildLoadConfigModalHTML({
        deviceName: 'Boiler', values, t, ownName: '', autoName: 'Boiler' });
    assert.ok(html.includes('id="cfg-name"'));
    assert.ok(html.includes('value=""'));
});

test('a charger or the battery has no name field', () => {
    const html = buildLoadConfigModalHTML({ deviceName: 'Wallbox', values, t });
    assert.ok(!html.includes('cfg-name'));
});

test('a name is shown as text, never as markup', () => {
    const html = buildLoadConfigModalHTML({
        deviceName: '<img src=x onerror=1>', values, t,
        ownName: '"><script>x</script>', autoName: '<b>auto</b>' });
    assert.ok(!html.includes('<script>'));
    assert.ok(!html.includes('<img'));
    assert.ok(!html.includes('<b>auto</b>'));
});

test('the label and the hint are translated in every language', () => {
    for (const [lang, table] of Object.entries(words)) {
        for (const key of ['cfg_own_name', 'cfg_own_name_hint']) {
            assert.ok(table[key], lang + ' lacks ' + key);
        }
    }
});

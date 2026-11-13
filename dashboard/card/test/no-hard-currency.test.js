// (#1354) A unit on a settings field follows the install's currency. A
// card that printed "EUR/kWh" on a CHF install named the wrong money.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const dir = new URL('../src/cards/', import.meta.url);

test('no card names a currency of its own in a unit', () => {
    const bad = [];
    for (const f of fs.readdirSync(dir).filter((n) => n.endsWith('.js'))) {
        const src = fs.readFileSync(new URL(f, dir), 'utf8');
        src.split('\n').forEach((line, i) => {
            if (/^\s*(\/\/|\*)/.test(line)) return;
            if (/['"`](EUR|CHF|USD|GBP|€)\s*\/\s*k?W/.test(line) || /\/kW\/Mt/.test(line)) bad.push(`${f}:${i + 1}`);
        });
    }
    assert.deepEqual(bad, []);
});

test('the demand charge unit is a translated text with the currency filled in', () => {
    const src = fs.readFileSync(new URL('sem-config-card.js', dir), 'utf8');
    assert.ok(src.includes("this._t('config_unit_per_kw_month').replace('{currency}', currency)"));
});

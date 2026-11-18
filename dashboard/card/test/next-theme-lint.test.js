/**
 * (#1321) The SEM dashboard takes its colours from Home Assistant's theme.
 * A hex or rgba literal in the screens' CSS or code is allowed only as the
 * fallback of a variable: `var(--primary-color, #03a9f4)`. Anything else
 * breaks a light or a dark theme (white on white, black on black).
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';

const SRC = fileURLToPath(new URL('../src/', import.meta.url));
const pick = (dir, re) => readdirSync(join(SRC, dir)).filter((f) => re.test(f)).map((f) => join(SRC, dir, f));
const FILES = [
    join(SRC, 'base/sem-next-base.js'),
    ...pick('cards', /^sem-next-.*\.js$/),
    join(SRC, 'cards/load-config-modal.js'),
    join(SRC, 'cards/sem-setup-checklist-card.js'),
    join(SRC, 'cards/sem-simulation-card.js'),
    join(SRC, 'cards/sem-retired-card.js'),
    join(SRC, 'util/ha-ui.js'),
    ...pick('util', /^next-.*\.js$/),
];

const COLOR = /#[0-9a-fA-F]{8}\b|#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3,4}\b|\b(?:rgba?|hsla?)\(/g;

/** Comments out: a block comment, a line comment that is not part of a URL. */
function stripComments(src) {
    return src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:'"`\\])\/\/[^\n]*/g, '$1');
}

/** Every var(--x, fallback) replaced, innermost first, so its fallback does not count. */
function stripVars(src) {
    let out = src;
    for (let i = 0; i < 8; i++) {
        const next = out.replace(/var\(--[\w-]+(?:\s*,\s*[^()]*)?\)/g, 'VAR');
        if (next === out) break;
        out = next;
    }
    return out;
}

/** Colour literals outside a var() fallback. `#1321` (3-4 digits only) is an issue number, not a colour. */
export function colourLiterals(src) {
    const body = stripVars(stripComments(src));
    return (body.match(COLOR) || []).filter((m) => !/^#\d{3,4}$/.test(m));
}

test('no hex or rgba literal outside a var() fallback in the SEM dashboard', () => {
    const bad = [];
    for (const file of FILES) {
        const hits = colourLiterals(readFileSync(file, 'utf8'));
        if (hits.length) bad.push(`${file.slice(SRC.length)}: ${[...new Set(hits)].join(' ')}`);
    }
    assert.deepEqual(bad, [], 'use a theme variable: var(--primary-text-color, #212121)');
});

test('the lint sees the files it is meant to guard', () => {
    assert.ok(FILES.length >= 20);
    assert.ok(FILES.some((f) => f.endsWith('sem-next-base.js')));
    assert.ok(FILES.some((f) => f.endsWith('next-timeline.js')));
});

test('the lint refuses a bare literal and accepts a fallback', () => {
    assert.deepEqual(colourLiterals('a { color: #ff9800; }'), ['#ff9800']);
    assert.deepEqual(colourLiterals('a { background: rgba(0, 0, 0, .3); }'), ['rgba(']);
    assert.deepEqual(colourLiterals('a { color: var(--primary-color, #03a9f4); }'), []);
    assert.deepEqual(colourLiterals('a { color: var(--a, var(--b, #fff)); }'), []);
    assert.deepEqual(colourLiterals('a { color: #fff; border: 1px solid var(--x, #000); }'), ['#fff']);
    assert.deepEqual(colourLiterals('// a note about #fff\n/* and #000 */ x'), []);
    assert.deepEqual(colourLiterals("const s = '(#1321)';"), []);
});

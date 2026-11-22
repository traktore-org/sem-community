/**
 * (#1321) A text with a {placeholder} must be filled before it is shown. The
 * Insights accuracy rows showed "{pct} % trusted 55 %" on 22.11: the text was
 * read with _t() and the number glued on behind it.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

const ROOT = new URL('../src/', import.meta.url).pathname;
const EN = JSON.parse(readFileSync(new URL('../../translations.json', import.meta.url))).en;
const WITH_SLOT = new Set(Object.keys(EN).filter((k) => /\{[a-z_]+\}/.test(String(EN[k]))));

function files(dir) {
    return readdirSync(dir).flatMap((f) => {
        const p = join(dir, f);
        return statSync(p).isDirectory() ? files(p) : (p.endsWith('.js') ? [p] : []);
    });
}

test('no text with a {slot} is read with a plain _t() and shown unfilled', () => {
    const bad = [];
    const read = /(?<![A-Za-z_])(?:_t|t)\('([a-z0-9_]+)'\)/g;
    for (const f of files(ROOT)) {
        readFileSync(f, 'utf8').split('\n').forEach((line, i) => {
            for (const m of line.matchAll(read)) {
                if (!WITH_SLOT.has(m[1])) continue;
                const before = line.slice(Math.max(0, m.index - 12), m.index);
                const after = line.slice(m.index + m[0].length, m.index + m[0].length + 12);
                if (after.includes('.replace') || /(fill|tf)\($/.test(before) || before.includes('fill(') || before.includes('tf(')) continue;
                bad.push(`${f.replace(ROOT, '')}:${i + 1} ${m[1]}`);
            }
        });
    }
    assert.deepEqual(bad, []);
});

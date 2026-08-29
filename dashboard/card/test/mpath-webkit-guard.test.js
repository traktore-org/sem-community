/**
 * Structural guard for the #591 bug class: "engine-specific SMIL reference form".
 *
 * The flow-dot animations move a <circle> along a curve. They used to do this
 * with `<animateMotion><mpath href="#pathId"/></animateMotion>`. WebKit's SMIL
 * resolver only matches `xlink:href` on <mpath> (the XLink-namespaced form);
 * the plain `href` never resolved, so on EVERY iOS browser (Safari, Chrome and
 * the HA Companion app all use WebKit) the dots stood still — while Blink/Gecko
 * (desktop, Android) accepted plain `href` and animated fine. That's exactly
 * the report in #591.
 *
 * The fix removed <mpath> entirely: every animateMotion now carries its path
 * data inline via the `path="M…"` attribute (the SVG 1.1 form, supported on
 * every engine including old WebKit). This guard keeps the broken form from
 * ever coming back — any reintroduced `<mpath …>` fails the build.
 *
 * The guard forbids the `<mpath` opening tag anywhere in card source. The
 * fix-explaining comments deliberately write "mpath" without the angle
 * bracket, so the only way `<mpath` reappears is an actual element.
 *
 * Run: `npm test` (from dashboard/card). No browser needed.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const cardRoot = join(here, '..');

// All hand-written card sources that emit SVG — every Lit source under src/.
// `dist/` is generated, so it's covered transitively: if a source is clean,
// the built bundle is too. (#784 retired the last vanilla top-level card, so
// src/ is now the whole surface.)
function cardSourceFiles() {
    const files = [];
    const walk = (dir) => {
        for (const ent of readdirSync(dir, { withFileTypes: true })) {
            const p = join(dir, ent.name);
            if (ent.isDirectory()) walk(p);
            else if (ent.name.endsWith('.js')) files.push(p);
        }
    };
    walk(join(cardRoot, 'src'));
    return files;
}

// The `<mpath` opening tag, in any casing/whitespace.
const MPATH_TAG = /<\s*mpath\b/i;

test('#591: no <mpath> element in any card source (WebKit ignores its href)', () => {
    const offenders = [];
    for (const file of cardSourceFiles()) {
        const src = readFileSync(file, 'utf8');
        src.split('\n').forEach((line, i) => {
            if (MPATH_TAG.test(line)) {
                offenders.push(`${file}:${i + 1}: ${line.trim()}`);
            }
        });
    }
    assert.deepEqual(
        offenders,
        [],
        '<mpath> reintroduced — move the dots with animateMotion path="M…" ' +
        'instead; an mpath href reference does not resolve on iOS/WebKit (#591):\n' +
        offenders.join('\n'),
    );
});

test('#591: flow dots still move — every card emits animateMotion with inline path=', () => {
    // Positive counterpart to the ban above: the dots must follow an inline
    // `path="…"`, not just "no <mpath>". Guards against a regression that
    // silences the animation altogether (which would also pass the ban).
    const INLINE_PATH = /<\s*animateMotion\b[^>]*\bpath=/i;
    for (const file of cardSourceFiles()) {
        const src = readFileSync(file, 'utf8');
        if (!/<\s*animateMotion\b/i.test(src)) continue;  // no motion in this file
        assert.ok(
            INLINE_PATH.test(src),
            `${file} has <animateMotion> without an inline path= — the flow ` +
            `dots need their motion path inlined (iOS/WebKit, #591).`,
        );
    }
});

test('#591: the guard actually detects an <mpath> element (not vacuous)', () => {
    assert.ok(MPATH_TAG.test('<mpath href="#p"/>'));
    assert.ok(MPATH_TAG.test('  <mpath  xlink:href="#p" />'));
    // Prose that names the element without the angle bracket must NOT trip it —
    // this is exactly how the fix comments are written.
    assert.ok(!MPATH_TAG.test('// inline path= instead of an mpath href reference'));
    assert.ok(!MPATH_TAG.test('the sparks previously used mpath here'));
});

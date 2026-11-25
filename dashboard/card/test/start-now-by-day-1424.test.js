/**
 * (#1424) No card button sends full power until the plan's end.
 *
 * In 2.3.0-beta.27 the Plan card's "Start now" sent the plan override
 * `force` for `minutesToPlanEnd(...)`: pressed by day, a Sun charger ran at
 * full power until the next morning and the house battery fed the car. Since
 * #1381 the Plan card picks Now on the charger, which ends at the car's next
 * plan block or after two hours. A `force` may carry a time the user picked
 * (`fixed_end`) or minutes the user picked — never the plan's end. `skip`
 * until the plan's end stays right: it sends nothing.
 *
 * Run: `npm test` (from dashboard/card).
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const src = join(here, '..', 'src');

function files(dir) {
    return readdirSync(dir).flatMap((n) => {
        const p = join(dir, n);
        return statSync(p).isDirectory() ? files(p) : (p.endsWith('.js') ? [p] : []);
    });
}

/** A statement that asks for a `force` with an end read off the plan. */
const forceToPlanEnd = (line) => /['"]force['"]/.test(line) && /minutesToPlanEnd|planEndMs|nightEndMs/.test(line);

test('the detector finds the beta.27 Start now line', () => {
    const old = "btns.push(this._btn(t('next_start_now'), () => this._override(cid, 'force', minutesToPlanEnd(plan, new Date(), 720, this._nightEnd()), plan), { small: true }));";
    assert.ok(forceToPlanEnd(old));
    const skip = "btns.push(this._btn(t('next_skip_tonight'), () => this._override(cid, 'skip', minutesToPlanEnd(plan, new Date(), 720, this._nightEnd()), plan)));";
    assert.ok(!forceToPlanEnd(skip), 'a skip to the plan end is allowed');
});

/** Statements of a source, split at `;`, so a call laid over several lines stays whole. */
function statements(text) {
    const out = [];
    let line = 1;
    for (const part of text.split(';')) {
        out.push({ line, text: part });
        line += (part.match(/\n/g) || []).length;
    }
    return out;
}

test('a call laid over several lines is still one statement', () => {
    const old = "btns.push(this._btn(t('next_start_now'), () => this._override(cid, 'force',\n    minutesToPlanEnd(plan, new Date(), 720, this._nightEnd()), plan)));";
    assert.ok(statements(old).some((st) => forceToPlanEnd(st.text)));
});

// Not caught: an action word held in a variable (`this._override(cid, a, minutesToPlanEnd(…))`).
test('no card source sends a force until the plan end', () => {
    const all = files(src);
    assert.ok(all.length > 20, 'the card sources were found');
    const hits = [];
    for (const f of all) {
        for (const st of statements(readFileSync(f, 'utf8'))) {
            if (forceToPlanEnd(st.text)) hits.push(`${f.slice(src.length + 1)}:${st.line}`);
        }
    }
    assert.deepEqual(hits, []);
});

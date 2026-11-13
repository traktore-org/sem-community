// #1354 — planner notes reach the card as codes; one helper translates them.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { planNoteText, PLAN_NOTE_CODES } from '../src/util/plan-notes.js';

const TR = JSON.parse(readFileSync(new URL('../../translations.json', import.meta.url)));

test('every code has a text in every language', () => {
    for (const [lang, keys] of Object.entries(TR)) {
        for (const c of PLAN_NOTE_CODES) assert.ok(keys['plan_note_' + c], `${lang} plan_note_${c}`);
    }
});

test('codes render in the user language with their params', () => {
    const t = (k) => TR.de[k] || k;
    const d = { note: 'English', notes: [{ code: 'unpriced_slots', params: { count: 13 } },
                                       { code: 'cost_unknown', params: {} }] };
    const s = planNoteText(d, t);
    assert.match(s, /^13 Zeitfenster ohne Preis/);
    assert.match(s, /Kosten unbekannt$/);
    assert.ok(!s.includes('English'));
});

test('an old payload or an unknown code keeps the English note', () => {
    const t = (k) => TR.en[k] || k;
    assert.equal(planNoteText({ note: 'old' }, t), 'old');
    assert.equal(planNoteText({ note: 'x', notes: [{ code: 'nope' }] }, t), 'x');
    assert.equal(planNoteText({ notes: [] }, t), null);
});

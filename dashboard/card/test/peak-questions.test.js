// (#1354) The peak limit is one question: "Limit grid draw to [x kW] / No
// limit". It writes the two stored fields the old switch and number wrote.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { PEAK_KW, clampPeakKw, peakQuestion, peakWrites, sliderAnswer } from '../src/util/peak-questions.js';

test('the stored pair reads as one answer, keeping the saved number while unlimited', () => {
    assert.deepEqual(peakQuestion({ unlimited: false, limitKw: 6 }), { limited: true, kw: 6 });
    assert.deepEqual(peakQuestion({ unlimited: true, limitKw: 6 }), { limited: false, kw: 6 });
    assert.deepEqual(peakQuestion({ unlimited: false, limitKw: undefined }), { limited: true, kw: PEAK_KW.fallback });
});

test('an answer writes exactly the two stored fields', () => {
    assert.deepEqual(peakWrites(false, 6), { peak_limit_unlimited: true });
    assert.deepEqual(peakWrites(true, 6.04), { peak_limit_unlimited: false, target_peak_limit: 6 });
    assert.deepEqual(peakWrites(true, 200), { peak_limit_unlimited: false, target_peak_limit: 80 });
    assert.deepEqual(peakWrites(true, 0.2), { peak_limit_unlimited: false, target_peak_limit: 1 });
    assert.deepEqual(peakWrites(true, 'abc'), { peak_limit_unlimited: false });
});

test('the slider end is "no limit"; elsewhere a limit', () => {
    assert.deepEqual(sliderAnswer(80), { limited: false, kw: 80 });
    assert.deepEqual(sliderAnswer(7.5), { limited: true, kw: 7.5 });
    assert.equal(clampPeakKw(''), null);
});

test('the classic cards ask it with the shared words', () => {
    const cards = new URL('../src/cards/', import.meta.url);
    const cfg = fs.readFileSync(new URL('sem-config-card.js', cards), 'utf8');
    const lpc = fs.readFileSync(new URL('sem-load-priority-card.js', cards), 'utf8');
    assert.ok(cfg.includes('_renderPeakQuestion(opts)') && cfg.includes('peakWrites(limited, kw)'));
    assert.ok(!cfg.includes("'config_lm_unlimited'"), 'no separate "No grid limit" switch');
    assert.ok(lpc.includes('sliderAnswer(toVal(ev.clientX))') && lpc.includes('PEAK_TEXT.label'));
    for (const f of ['sem-load-priority-card.js', 'sem-control-card.js', 'sem-home-status-card.js', 'sem-tab-header.js']) {
        const src = fs.readFileSync(new URL(f, cards), 'utf8');
        assert.ok(src.includes('PEAK_TEXT.none'), `${f} says "No limit" in the shared word`);
    }
});

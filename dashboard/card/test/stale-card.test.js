/**
 * (#1381) PROD 25.11: after the update the phone app kept the old card. It
 * knew only the old mode names, so it drew one button, "Off", and a tap on
 * it stopped the night charge. Two guards:
 *  1. every SEM Next screen compares its own bundle token with the one the
 *     server registered (sensor.sem_diag_version, attribute `card`) and asks
 *     for a reload when they differ;
 *  2. the mode control never hides an option the select offers.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const { mount, S, text } = await import('./card-harness.js');
const { staleCard, setOwnCardVersion } = await import('../src/util/version-check.js');
const { chargerModeItems } = await import('../src/util/charger-questions.js');

globalThis.location = { pathname: '/sem-next/now', hash: '', reload() { globalThis.__reloaded = true; } };

test('staleCard: only a known own token that differs from a known server token is stale', () => {
    assert.equal(staleCard('2.3.0-beta.27-aaaa', '2.3.0-beta.27-bbbb'), true);
    assert.equal(staleCard('2.3.0-beta.27-aaaa', '2.3.0-beta.27-aaaa'), false);
    assert.equal(staleCard('', '2.3.0-beta.27-bbbb'), false, 'a card loaded without a token never nags');
    assert.equal(staleCard('2.3.0-beta.27-aaaa', null), false, 'an old server without the attribute never nags');
});

test('a screen whose card is older than the server says so at the top, with a reload button', () => {
    setOwnCardVersion('2.3.0-beta.27-old11111');
    try {
        const el = mount('sem-next-system-card', { 'sensor.sem_diag_version': S('2.3.0-beta.27', { card: '2.3.0-beta.27-new22222' }) });
        const out = text(el.render());
        assert.match(out, /class="stale"[^>]*>.*next_card_stale.*next_card_reload/s, 'the banner and its reload button');
        const en = JSON.parse(readFileSync(new URL('../../translations.json', import.meta.url))).en;
        assert.equal(en.next_card_stale, 'SEM was updated. Reload this page to use the new version.');
        const same = mount('sem-next-system-card', { 'sensor.sem_diag_version': S('2.3.0-beta.27', { card: '2.3.0-beta.27-old11111' }) });
        assert.doesNotMatch(text(same.render()), /next_card_stale/);
    } finally { setOwnCardVersion(''); }
});

test('the mode control shows every option the select offers, unknown ones by their raw name', () => {
    const items = chargerModeItems(['sun', 'sun_tariff', 'now', 'off', 'future_mode'], (k) => ({ mode_sun: 'Sun' }[k] || ''));
    assert.deepEqual(items.map((i) => i.key), ['off', 'sun', 'sun_tariff', 'now', 'future_mode']);
    assert.equal(items.find((i) => i.key === 'future_mode').label, 'future_mode');
    const old = chargerModeItems(['solar_only', 'min_plus_solar', 'off'], () => '');
    assert.deepEqual(old.map((i) => i.key), ['off', 'solar_only', 'min_plus_solar'], 'never only one button');
});

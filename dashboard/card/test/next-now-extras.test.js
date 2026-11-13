/**
 * (#1321) The three additions to the SEM-dashboard Now screen (Rien's review
 * of PR 1322): the source mix, the 24 h price strip and the device chips.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { sourceMix, levelOf, priceStrip, deviceChips } from '../src/util/next-now-extras.js';
import { powerBar } from '../src/util/next-power-bar.js';
import { priceModel } from '../src/util/next-plan-chart.js';

const H = 3600e3;

test('the mix adds up to 100 % and leaves idle sources out', () => {
    const bar = powerBar({ solarW: 1000, gridW: -500, batteryW: -1500, homeW: 3000, evW: 0 });
    const mix = sourceMix(bar);
    assert.deepEqual(mix.map((m) => m.key).sort(), ['battery_out', 'grid_in', 'solar']);
    assert.equal(mix.reduce((a, m) => a + m.pct, 0), 100);
    assert.equal(mix.find((m) => m.key === 'battery_out').pct, 50);
    const night = sourceMix(powerBar({ solarW: 0, gridW: 0, batteryW: -800, homeW: 800 }));
    assert.deepEqual(night.map((m) => [m.key, m.pct]), [['battery_out', 100]]);
});

test('three equal sources round to 100, not 99', () => {
    const mix = sourceMix({ sources: [{ key: 'solar', w: 1 }, { key: 'battery_out', w: 1 }, { key: 'grid_in', w: 1 }] });
    assert.equal(mix.reduce((a, m) => a + m.pct, 0), 100);
});

test('nothing flowing gives no mix', () => {
    assert.deepEqual(sourceMix({ sources: [] }), []);
    assert.deepEqual(sourceMix(null), []);
});

test('a level uses the install thresholds, else thirds of the window', () => {
    assert.equal(levelOf(0.10, { cheap: 0.15, expensive: 0.30 }), 'cheap');
    assert.equal(levelOf(0.20, { cheap: 0.15, expensive: 0.30 }), 'normal');
    assert.equal(levelOf(0.35, { cheap: 0.15, expensive: 0.30 }), 'expensive');
    assert.equal(levelOf(0.10, { min: 0.10, max: 0.40 }), 'cheap');
    assert.equal(levelOf(0.39, { min: 0.10, max: 0.40 }), 'expensive');
    assert.equal(levelOf(null, {}), 'unknown');
});

test('the strip joins equal levels and knows the level now', () => {
    const start = Date.UTC(2026, 10, 13, 0), win = { start, end: start + 24 * H };
    const upcoming = [];
    for (let h = 0; h < 24; h += 1) for (let q = 0; q < 4; q += 1) {
        upcoming.push({ t: new Date(start + h * H + q * 15 * 60e3).toISOString(), price: h < 6 ? 0.10 : (h < 18 ? 0.20 : 0.40) });
    }
    const pm = priceModel({ win, tz: 'UTC', nowMs: start + 7 * H, upcoming, isDynamic: true, level: 'normal' });
    const s = priceStrip(pm, win, start + 7 * H, { cheap: 0.15, expensive: 0.30 });
    assert.deepEqual(s.runs.map((r) => [r.level, (r.e - r.s) / H]), [['cheap', 6], ['normal', 12], ['expensive', 6]]);
    assert.equal(s.nowLevel, 'normal');
});

test('a flat tariff gives no strip', () => {
    const start = Date.UTC(2026, 10, 13, 0), win = { start, end: start + 24 * H };
    const pm = priceModel({ win, tz: 'UTC', nowMs: start, isDynamic: false, level: 'flat', todayAvg: 0.36 });
    assert.equal(priceStrip(pm, win, start, {}), null);
});

test('hours with no price yet are shown as unknown, never as a level', () => {
    const start = Date.UTC(2026, 10, 13, 0), win = { start, end: start + 24 * H };
    const upcoming = [{ t: new Date(start).toISOString(), price: 0.1 }, { t: new Date(start + 15 * 60e3).toISOString(), price: 0.3 }];
    const pm = priceModel({ win, tz: 'UTC', nowMs: start, upcoming, isDynamic: true, level: 'normal' });
    const s = priceStrip(pm, win, start, {});
    assert.equal(s.runs[s.runs.length - 1].level, 'unknown');
});

test('one chip per device, in order: battery, cars, heaters', () => {
    const chips = deviceChips({ batterySoc: 36.4, cars: [
        { name: 'Laadpaal Links', connected: true, charging: true, soc: 61.6 },
        { name: 'Garage', connected: false, charging: false, soc: null },
    ], heaters: [{ name: 'Boiler', on: false }] });
    assert.deepEqual(chips.map((c) => [c.kind, c.label, c.state, c.soc]), [
        ['battery', null, null, 36],
        ['car', 'Laadpaal Links', 'charging', 62],
        ['car', 'Garage', 'unplugged', null],
        ['heater', 'Boiler', 'off', null],
    ]);
    assert.deepEqual(deviceChips({ batterySoc: null }), []);
});

import { sourceEntityOf } from '../src/util/next-freshness.js';

test('a source row names the real entity SEM reads', () => {
    const ed = { solar: { power: 'sensor.inverter_eingangsleistung' }, grid: { power: 'sensor.grid_power_ha_convention' },
        battery: { power: 'sensor.battery_1_lade_entladeleistung' } };
    assert.equal(sourceEntityOf('next_src_solar', ed), 'sensor.inverter_eingangsleistung');
    assert.equal(sourceEntityOf('next_src_battery', ed), 'sensor.battery_1_lade_entladeleistung');
    assert.equal(sourceEntityOf('next_src_price', ed), '');
    assert.equal(sourceEntityOf('next_src_solar', undefined), '');
});

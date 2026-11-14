/**
 * (#1321) The Power-now bar's model: SEM signs, missing readings, labels.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { powerBar, LABEL_SHARE } from '../src/util/next-power-bar.js';

test('a sunny day with the car: sun, a little battery and grid feed house and car', () => {
    const b = powerBar({ solarW: 4600, batteryW: -300, gridW: -400, homeW: 1200, evW: 4100 });
    assert.deepEqual(b.sources.map((s) => s.key), ['solar', 'battery_out', 'grid_in']);
    assert.deepEqual(b.sinks.map((s) => s.key), ['home', 'ev']);
    assert.equal(b.total, 5300);
    assert.equal(b.inW, 5300);
    assert.equal(b.outW, 5300);
    const solar = b.sources[0];
    assert.ok(solar.label, 'the big segment carries its number');
    assert.ok(!b.sources[1].label, 'a thin segment carries none');
    assert.ok(Math.abs(solar.share - 4600 / 5300) < 1e-9);
});

test('SEM signs: grid positive is export, battery positive is charging', () => {
    const b = powerBar({ solarW: 3000, batteryW: 800, gridW: 1000, homeW: 1200, evW: 0 });
    assert.deepEqual(b.sources.map((s) => s.key), ['solar']);
    assert.deepEqual(b.sinks.map((s) => s.key), ['home', 'battery_in', 'grid_out']);
    assert.equal(b.sinks.find((s) => s.key === 'grid_out').w, 1000);
    assert.equal(b.sinks.find((s) => s.key === 'battery_in').w, 800);
});

test('a missing reading leaves its segment out, never a fake value', () => {
    const b = powerBar({ solarW: null, batteryW: undefined, gridW: 'unavailable', homeW: 900, evW: '' });
    assert.deepEqual(b.sources, []);
    assert.deepEqual(b.sinks.map((s) => s.key), ['home']);
    assert.equal(b.total, 900, 'with no source the sinks give the total');
});

test('nothing flowing gives empty lanes and a zero total', () => {
    const b = powerBar({ solarW: 0, batteryW: 0, gridW: 0, homeW: 0, evW: 0 });
    assert.deepEqual(b.sources, []);
    assert.deepEqual(b.sinks, []);
    assert.equal(b.total, 0);
    assert.equal(b.idle, true);
    assert.deepEqual(powerBar(), { sources: [], sinks: [], total: 0, inW: 0, outW: 0, idle: false });
});

test('the label threshold is one fifth of the lane', () => {
    const b = powerBar({ solarW: 800, gridW: -200, homeW: 1000 });
    const grid = b.sources.find((s) => s.key === 'grid_in');
    assert.ok(Math.abs(grid.share - 0.2) < 1e-9);
    assert.equal(grid.label, 0.2 >= LABEL_SHARE);
});

test('meter noise is not a flow: a few watts leave the bar empty and idle', () => {
    const b = powerBar({ solarW: 3, gridW: -5, batteryW: 0, homeW: 8, evW: 0 });
    assert.equal(b.sources.length, 0);
    assert.equal(b.sinks.length, 0);
    assert.equal(b.idle, true);
});

test('no readings at all is unknown, not idle', () => {
    const b = powerBar({});
    assert.equal(b.idle, false);
});

test('a real flow next to noise keeps only the real flow', () => {
    const b = powerBar({ solarW: 20, gridW: -600, batteryW: 0, homeW: 610, evW: 0 });
    assert.deepEqual(b.sources.map((s) => s.key), ['grid_in']);
    assert.deepEqual(b.sinks.map((s) => s.key), ['home']);
    assert.equal(b.idle, false);
});

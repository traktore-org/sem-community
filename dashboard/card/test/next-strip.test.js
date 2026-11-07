/**
 * (#1321) The Plan screen's price-and-plan strip: pure geometry from the
 * plan sensor's attributes. Every x is a fraction of the chosen day.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { stripModel, dayBounds, topQuartile, clockMs, smoothPath, minutesToPlanEnd, LANES } from '../src/util/next-strip.js';

// Saturday 07.11.2026 12:40 local, like the mockup.
const NOW = new Date(2026, 10, 7, 12, 40);
const at = (dayOff, h, m = 0) => new Date(2026, 10, 7 + dayOff, h, m).toISOString();

/** 15-minute slots from `h0` to `h1` on `dayOff`, one price per hour. */
function quarterSlots(dayOff, h0, h1, priceOf, cheapOf = () => false) {
    const out = [];
    for (let h = h0; h < h1; h++) {
        for (let q = 0; q < 4; q++) {
            out.push({ start: at(dayOff, h, q * 15), end: q === 3 ? at(dayOff, h + 1, 0) : at(dayOff, h, q * 15 + 15),
                       price: priceOf(h), cheap: cheapOf(h) });
        }
    }
    return out;
}

const near = (a, b, eps = 1e-6) => assert.ok(Math.abs(a - b) < eps, `${a} is not near ${b}`);

test('dayBounds gives 00:00 of today or tomorrow', () => {
    const t = dayBounds(NOW, 'today');
    assert.equal(new Date(t.start).getHours(), 0);
    assert.equal(new Date(t.start).getDate(), 7);
    assert.equal(new Date(dayBounds(NOW, 'tomorrow').start).getDate(), 8);
    assert.equal(t.end - t.start, 24 * 3600e3);
});

test('15-minute slots become one bar per hour, the mean of its slots, past hours marked', () => {
    const slots = quarterSlots(0, 0, 24, (h) => 0.20 + h * 0.01);
    slots[0].price = 0.24; // one odd quarter pulls the first hour's mean up a little
    const m = stripModel({ plan: { slots }, day: 'today', now: NOW });
    assert.equal(m.bars.length, 24);
    near(m.bars[0].price, (0.24 + 0.20 * 3) / 4);
    near(m.bars[5].price, 0.25);
    near(m.bars[0].x0, 0);
    near(m.bars[0].x1, 1 / 24);
    assert.equal(m.bars[11].past, true);   // 11:00-12:00 is over at 12:40
    assert.equal(m.bars[12].past, false);  // 12:00-13:00 is the hour now
    near(m.price.min, 0.21);
    near(m.price.max, 0.43);
});

test('no slots give no bars and no price text, not fake ones', () => {
    const m = stripModel({ plan: {}, day: 'today', now: NOW });
    assert.deepEqual(m.bars, []);
    assert.equal(m.price, null);
    assert.equal(m.sun, null);
    assert.deepEqual(m.blocks, []);
});

test('cheap hours merge into one band; the expensive band uses the threshold', () => {
    const slots = quarterSlots(0, 0, 24, (h) => (h >= 18 && h < 20 ? 0.38 : 0.25), (h) => h >= 13 && h < 15);
    const m = stripModel({ plan: { slots }, day: 'today', now: NOW, expensiveThreshold: 0.30 });
    assert.equal(m.bands.cheap.length, 1);
    near(m.bands.cheap[0].x0, 13 / 24);
    near(m.bands.cheap[0].x1, 15 / 24);
    assert.equal(m.bands.expensive.length, 1);
    near(m.bands.expensive[0].x0, 18 / 24);
    near(m.bands.expensive[0].x1, 20 / 24);
    assert.equal(m.threshold, 0.30);
});

test('without a threshold the top quartile marks the expensive hours', () => {
    assert.equal(topQuartile([0.2, 0.2, 0.2, 0.2]), null);
    assert.equal(topQuartile([0.1, 0.2]), null);
    const slots = quarterSlots(0, 0, 24, (h) => 0.20 + h * 0.01);
    const m = stripModel({ plan: { slots }, day: 'today', now: NOW });
    assert.ok(m.threshold > 0.36 && m.threshold < 0.40, String(m.threshold));
    assert.equal(m.bands.expensive.length, 1);
    assert.ok(m.bands.expensive[0].x0 >= 18 / 24);
    near(m.bands.expensive[0].x1, 1);
});

test('the sun is a bell between night end and night start, scaled by the forecast', () => {
    const m = stripModel({ plan: {}, day: 'today', now: NOW, nightStart: '17:30', nightEnd: '07:00', forecastKwh: 24.8 });
    assert.ok(m.sun);
    near(m.sun.x0, 7 / 24);
    near(m.sun.x1, 17.5 / 24);
    assert.equal(m.sun.kwh, 24.8);
    assert.equal(m.sun.points.length, 25);
    near(m.sun.points[0][1], 0, 1e-9);
    near(m.sun.points[12][1], 1);
    // no forecast, no curve
    assert.equal(stripModel({ plan: {}, day: 'today', now: NOW, nightStart: '17:30', nightEnd: '07:00' }).sun, null);
    assert.equal(stripModel({ plan: {}, day: 'today', now: NOW, forecastKwh: 5 }).sun, null);
});

test('blocks land on their lane, running is solid, planned is dashed, clipped to the day', () => {
    const plan = {
        blocks: [
            { id: 'ev:keba', start: at(0, 9, 30), end: at(0, 15, 18), power_w: 4140, label: 'Car' },
            { id: 'battery', start: at(0, 11), end: at(0, 16), power_w: 1000 },
            { id: 'load:hp', start: at(0, 13), end: at(0, 15), power_w: 1200 },
            { id: 'ev:keba', start: at(0, 23), end: at(1, 2), power_w: 4140 },      // crosses midnight
            { id: 'load:pool', start: at(2, 10), end: at(2, 12), power_w: 800 },    // another day
        ],
    };
    const m = stripModel({ plan, day: 'today', now: NOW });
    assert.equal(m.blocks.length, 4);
    const ev = m.blocks.find((b) => b.id === 'ev:keba' && b.run);
    assert.equal(ev.lane, LANES.ev);
    assert.equal(ev.kind, 'ev');
    assert.equal(ev.run, true);
    near(ev.x0, 9.5 / 24);
    near(ev.kwh, 4.14 * 5.8);
    const bat = m.blocks.find((b) => b.id === 'battery');
    assert.equal(bat.lane, LANES.battery);
    assert.equal(bat.kind, 'battery_in');
    const hp = m.blocks.find((b) => b.id === 'load:hp');
    assert.equal(hp.lane, LANES.load);
    assert.equal(hp.run, false);
    const night = m.blocks.find((b) => b.id === 'ev:keba' && !b.run);
    near(night.x1, 1);  // clipped at 24:00
    // the same night block shows on tomorrow from 00:00 to 02:00
    const t = stripModel({ plan, day: 'tomorrow', now: NOW });
    assert.equal(t.blocks.length, 1);
    near(t.blocks[0].x0, 0);
    near(t.blocks[0].x1, 2 / 24);
    assert.equal(t.blocks[0].run, false);
});

test('battery runs over the slots become battery-to-house blocks', () => {
    const slots = quarterSlots(0, 16, 24, () => 0.3);
    const plan = { slots, batt_runs: [[6, 25]] };   // 17:30 to 22:30
    const m = stripModel({ plan, day: 'today', now: NOW });
    assert.equal(m.blocks.length, 1);
    assert.equal(m.blocks[0].kind, 'battery_out');
    assert.equal(m.blocks[0].lane, LANES.battery);
    near(m.blocks[0].x0, 17.5 / 24);
    near(m.blocks[0].x1, 22.5 / 24);
});

test('tomorrow draws the provisional blocks and the cheap windows the preview names', () => {
    const plan = {
        tomorrow: {
            prices: 'preliminary',
            cheap_windows: [{ start: at(1, 2), end: at(1, 4, 30) }],
            provisional: { blocks: [{ id: 'load:0', label: 'Heat pump', start: at(1, 13), end: at(1, 15) }] },
        },
    };
    const m = stripModel({ plan, day: 'tomorrow', now: NOW });
    assert.equal(m.blocks.length, 1);
    assert.equal(m.blocks[0].provisional, true);
    assert.equal(m.blocks[0].lane, LANES.load);
    assert.equal(m.blocks[0].label, 'Heat pump');
    assert.equal(m.bands.cheap.length, 1);
    near(m.bands.cheap[0].x0, 2 / 24);
    near(m.bands.cheap[0].x1, 4.5 / 24);
    // today shows none of it
    assert.equal(stripModel({ plan, day: 'today', now: NOW }).blocks.length, 0);
});

test('the now line sits on today only; the departure line on tomorrow', () => {
    const today = stripModel({ plan: {}, day: 'today', now: NOW, departure: '07:00' });
    near(today.lines.now, (12 * 60 + 40) / (24 * 60));
    assert.equal(today.lines.departure, null);   // 07:00 today is past
    const tmw = stripModel({ plan: {}, day: 'tomorrow', now: NOW, departure: '07:00' });
    assert.equal(tmw.lines.now, null);
    near(tmw.lines.departure.x, 7 / 24);
    assert.equal(tmw.lines.departure.label, '07:00');
    assert.equal(tmw.ticks.length, 5);
    assert.equal(tmw.ticks[4].label, '24');
});

test('clockMs, smoothPath and minutesToPlanEnd', () => {
    const { start } = dayBounds(NOW, 'today');
    assert.equal(clockMs('07:00', start), start + 7 * 3600e3);
    assert.equal(clockMs('', start), null);
    assert.equal(smoothPath([]), '');
    assert.equal(smoothPath([[0, 0], [10, 5]]), 'M0.0 0.0 L10.0 5.0');
    assert.match(smoothPath([[0, 0], [10, 5], [20, 0]]), /^M0\.0 0\.0 C/);
    const slots = quarterSlots(0, 18, 24, () => 0.3).concat(quarterSlots(1, 0, 7, () => 0.3));
    assert.equal(minutesToPlanEnd({ slots }, NOW), (24 - 12) * 60 - 40 + 7 * 60);
    assert.equal(minutesToPlanEnd({}, NOW), 720);
    assert.equal(minutesToPlanEnd({ slots: quarterSlots(0, 0, 6, () => 0.2) }, NOW), 720);
});

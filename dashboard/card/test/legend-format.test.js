/**
 * Regression tests for the #574 cost-chart legend fix.
 *
 * Chart.js builds legend items from a list SORTED by each dataset's
 * ``order``, so on the mixed line+bar "costs" chart the legend array is
 * a reordering of ``chart.data.datasets``. ``formatLegendLabels`` must
 * pair each label's text with its OWN dataset (via ``datasetIndex``),
 * not with whatever dataset happens to sit at the same array position.
 *
 * Run: `npm test` (from dashboard/card). No browser/Chart.js needed.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { formatLegendLabels } from '../src/util/legend-format.js';

// The costs chart's datasets, in true array order (as chart.data.datasets):
//   0: Import (bar,  order:2) — last value 0.05
//   1: export (bar,  order:2) — last value 1.8
//   2: net    (line, order:1) — last value -1.8
function costsDatasets() {
    return [
        { yAxisID: 'y', data: [{ x: 1, y: 0.0 }, { x: 2, y: 0.05 }] },
        { yAxisID: 'y', data: [{ x: 1, y: 0.9 }, { x: 2, y: 1.8 }] },
        { yAxisID: 'y', data: [{ x: 1, y: -0.9 }, { x: 2, y: -1.8 }] },
    ];
}

// Chart.js legend items are sorted by `order`: the net LINE (order:1)
// comes first, then the two bars (order:2) in array order. Each item
// keeps its true datasetIndex. This is the exact ordering that produced
// the rotated legend in #574.
function sortedByOrderLegendItems() {
    return [
        { text: 'net', datasetIndex: 2 },
        { text: 'Import', datasetIndex: 0 },
        { text: 'export', datasetIndex: 1 },
    ];
}

test('#574: legend value follows datasetIndex, not legend position', () => {
    const labels = formatLegendLabels(
        sortedByOrderLegendItems(), costsDatasets(), 'EUR',
    );
    const byText = Object.fromEntries(labels.map(l => [l.text.split(':')[0], l.text]));

    // Each label must show ITS OWN series' last value — no rotation.
    assert.equal(byText['Import'], 'Import: 0.1 EUR');  // 0.05 → 0.1 (abs<10, 1 dp)
    assert.equal(byText['export'], 'export: 1.8 EUR');
    assert.equal(byText['net'], 'net: -1.8 EUR');

    // Guard against the specific #574 rotation ever coming back.
    assert.notEqual(byText['Import'], 'Import: 1.8 EUR');
    assert.notEqual(byText['net'], 'net: 0.1 EUR');
});

test('#574: uniform-order charts (identity legend order) still format correctly', () => {
    // All-bar chart → sorted order == array order → datasetIndex == position.
    const datasets = [
        { yAxisID: 'y', data: [{ x: 1, y: 3.2 }] },
        { yAxisID: 'y', data: [{ x: 1, y: 5.7 }] },
    ];
    const items = [
        { text: 'solar', datasetIndex: 0 },
        { text: 'home', datasetIndex: 1 },
    ];
    const labels = formatLegendLabels(items, datasets, 'kWh');
    assert.equal(labels[0].text, 'solar: 3.2 kWh');
    assert.equal(labels[1].text, 'home: 5.7 kWh');
});

test('percent axis (y1) overrides the chart unit; empty series → 0', () => {
    const datasets = [
        { yAxisID: 'y1', data: [{ x: 1, y: 82 }] },
        { yAxisID: 'y', data: [] },
    ];
    const items = [
        { text: 'soc', datasetIndex: 0 },
        { text: 'power', datasetIndex: 1 },
    ];
    const labels = formatLegendLabels(items, datasets, 'W');
    assert.equal(labels[0].text, 'soc: 82 %');
    assert.equal(labels[1].text, 'power: 0.0 W');
});

test('missing dataset for a label is passed through untouched', () => {
    const items = [{ text: 'ghost', datasetIndex: 9 }];
    const labels = formatLegendLabels(items, [], 'EUR');
    assert.equal(labels[0].text, 'ghost');  // no ": … EUR" appended
});

/* ── #792: accumulating series legend the PERIOD, not the last bucket ──
   The savings/costs/energy charts plot per-bucket totals (monthly_savings,
   daily_costs, …). Labelling them with the newest bucket put "105 CHF"
   under a chart headed "This Year" — August month-to-date, while single
   months on the same chart were larger. Instantaneous series (W, %) keep
   the last sample, because for those the newest value IS the answer. */

// Eight monthly savings buckets as seen on PROD 2026-08-17. August is
// partial (the 17th), which is what made the old legend so misleading.
function yearOfSavingsBuckets() {
    return [
        { cumulative: true, yAxisID: 'y', data: [
            { x: 1, y: 12.4 }, { x: 2, y: 48.9 }, { x: 3, y: 233.0 },
            { x: 4, y: 251.7 }, { x: 5, y: 9.2 }, { x: 6, y: 246.3 },
            { x: 7, y: 185.8 }, { x: 8, y: 104.96 },
        ] },
    ];
}

test('#792: a cumulative series legends the sum of the plotted buckets', () => {
    const labels = formatLegendLabels(
        [{ text: 'Solar Savings', datasetIndex: 0 }],
        yearOfSavingsBuckets(), 'CHF',
    );
    // 12.4+48.9+233+251.7+9.2+246.3+185.8+104.96 = 1092.26 → "1.1k"
    assert.equal(labels[0].text, 'Solar Savings: 1.1k CHF');
    // The exact shape of the bug: August MTD standing in for the year.
    assert.notEqual(labels[0].text, 'Solar Savings: 105 CHF');
});

test('#792: an instantaneous series still legends its newest sample', () => {
    // preset: power on a day range resolves to the HOURLY defs (watts in
    // day buckets) — summing daily maxima of W would invent a number that
    // is not a quantity of anything. No `cumulative` flag → last value.
    const datasets = [{ yAxisID: 'y', data: [
        { x: 1, y: 4200 }, { x: 2, y: 3100 }, { x: 3, y: 900 },
    ] }];
    const labels = formatLegendLabels(
        [{ text: 'solar', datasetIndex: 0 }], datasets, 'W',
    );
    assert.equal(labels[0].text, 'solar: 900 W');
});

test('#792: summing keeps the #585 cash-flow sign', () => {
    // Import is plotted negated (spending points down); the period total
    // must stay negative rather than flipping into an apparent earning.
    const datasets = [{ cumulative: true, yAxisID: 'y', data: [
        { x: 1, y: -8.2 }, { x: 2, y: -15.08 },
    ] }];
    const labels = formatLegendLabels(
        [{ text: 'Import', datasetIndex: 0 }], datasets, 'CHF',
    );
    assert.equal(labels[0].text, 'Import: -23 CHF');
});

test('#792: the sum still follows datasetIndex, not legend position', () => {
    // #574's rotation must not reappear through the new code path.
    const datasets = [
        { cumulative: true, yAxisID: 'y', data: [{ x: 1, y: 1 }, { x: 2, y: 2 }] },
        { cumulative: true, yAxisID: 'y', data: [{ x: 1, y: 30 }, { x: 2, y: 40 }] },
    ];
    const labels = formatLegendLabels(
        [{ text: 'export', datasetIndex: 1 }, { text: 'Import', datasetIndex: 0 }],
        datasets, 'CHF',
    );
    assert.equal(labels[0].text, 'export: 70 CHF');
    assert.equal(labels[1].text, 'Import: 3.0 CHF');
});

test('#792: an empty cumulative series reads 0, not NaN', () => {
    const labels = formatLegendLabels(
        [{ text: 'battery_savings', datasetIndex: 0 }],
        [{ cumulative: true, yAxisID: 'y', data: [] }], 'CHF',
    );
    assert.equal(labels[0].text, 'battery_savings: 0.0 CHF');
});

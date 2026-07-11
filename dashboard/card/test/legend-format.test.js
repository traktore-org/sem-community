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

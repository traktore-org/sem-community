/**
 * Legend label formatting for sem-chart-card.
 *
 * Appends each series' value to its legend text, e.g.
 * "Import" → "Import: 0.1 EUR". Extracted from the card so the
 * dataset↔label pairing is unit-testable without a browser/Chart.js
 * (see ``test/legend-format.test.js``).
 *
 * #792 — which value depends on what the series IS. Accumulating series
 * (``daily_*`` / ``monthly_*``: money, kWh) carry one total per bucket, so
 * the legend under a "This Year" chart must be the SUM of the buckets; the
 * newest bucket is one month out of twelve, and mid-month not even a whole
 * one. Instantaneous series (W, %) keep their latest sample, because there
 * the newest value is the answer and a sum would not be a quantity of
 * anything. The card decides which is which in ``_resolveSeries`` — where
 * the hourly-vs-daily/monthly choice is actually made — and flags the
 * dataset, so the flag stays paired with its own series (see #574 below).
 *
 * #574 — the load-bearing fix: index the datasets array by each
 * label's ``datasetIndex``, NOT by its position in the legend array.
 * Chart.js builds legend items from ``chart._getSortedDatasetMetas()``,
 * which SORTS by each dataset's ``order``. On the mixed line+bar "costs"
 * chart the net LINE (order:1) is legended before the order:2 import/
 * export BARS, so the legend order differs from ``chart.data.datasets``.
 * The old code read ``datasets[i]`` by legend position, pairing each
 * label's TEXT with the WRONG dataset's value — a one-step rotation that
 * showed "Import: 1.8" (export's number) while import was ~0, and
 * "Net: 0.1" while the net line sat at −1.8. Same chart, contradictory
 * numbers vs. the costs summary card, which reads live states directly.
 */

/**
 * @param {Array} orig     legend items from Chart.js' default generateLabels;
 *                         each carries a ``datasetIndex`` and mutable ``text``.
 * @param {Array} datasets ``chart.data.datasets`` in their true array order;
 *                         ``cumulative: true`` marks a per-bucket total that
 *                         is summed over the period rather than sampled.
 * @param {string} yLabel  unit appended to non-percent axes (e.g. currency).
 * @returns {Array} the same label objects, with value+unit appended to text.
 */
export function formatLegendLabels(orig, datasets, yLabel) {
    return orig.map((label) => {
        const ds = datasets[label.datasetIndex];
        if (!ds) return label;
        const val = ds.cumulative
            ? ds.data.reduce((sum, p) => sum + (p?.y ?? 0), 0)
            : (ds.data[ds.data.length - 1]?.y ?? 0);
        const unit = ds.yAxisID === 'y1' ? '%' : (yLabel || '');
        const abs = Math.abs(val);
        const fmt = abs >= 1000
            ? (val / 1000).toFixed(1) + 'k'
            : abs < 10 ? val.toFixed(1) : val.toFixed(0);
        label.text = `${label.text}: ${fmt} ${unit}`;
        return label;
    });
}

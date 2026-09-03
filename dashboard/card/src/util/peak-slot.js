/**
 * The peak block reads two different quantities, and the card used to show
 * only one of them under a name that fits neither.
 *
 * Guido, 03.09, looking at the Home diagram and the Load Management card at
 * the same moment: *"How is this possible? 4.3 kW charging and 4.36 kW
 * margin."* Both numbers were right. "Current Peak" is the **15-minute
 * rolling average** of grid import — the metric the demand tariff bills —
 * and the car had been running six of those fifteen minutes. Nothing on the
 * card said so, and the number that actually bounds the next command (the
 * #864 slot budget) was not on the card at all.
 *
 * These helpers are pure so the labels can be unit-tested without a browser:
 * the billing slot's own window, how much of its energy budget is spent, and
 * what the rest of it may average.
 */

/** Length of a billing slot in minutes — the utility bills :00/:15/:30/:45. */
export const SLOT_MIN = 15;

/** The clock-aligned billing slot containing `date`, as `{start, end, elapsedS}`. */
export function slotWindow(date = new Date()) {
    const start = new Date(date);
    start.setMinutes(Math.floor(start.getMinutes() / SLOT_MIN) * SLOT_MIN, 0, 0);
    const end = new Date(start.getTime() + SLOT_MIN * 60_000);
    return { start, end, elapsedS: Math.max(0, (date - start) / 1000) };
}

/** `HH:MM` in the viewer's locale, zero-padded. */
export function hhmm(date) {
    return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
}

/**
 * The slot's energy budget in kWh at a target of `targetKw`, or null when the
 * install is uncapped (no target means no budget, never a budget of zero).
 */
export function slotBudgetKwh(targetKw) {
    const t = Number(targetKw);
    if (!Number.isFinite(t) || t <= 0) return null;
    return t * (SLOT_MIN / 60);
}

/**
 * Everything the card needs to render the slot row, or null when there is
 * nothing honest to say (uncapped install, or the guard has published no
 * numbers yet).
 *
 * `usedKwh` is the tracker's integral for THIS slot; `allowedW` is what the
 * guard says the rest of the slot may average. `fraction` drives the bar and
 * is clamped to [0, 1] — a slot already over budget shows a full bar, not a
 * bar wider than its box.
 */
export function slotStatus({ targetKw, usedKwh, allowedW, now = new Date() }) {
    const budget = slotBudgetKwh(targetKw);
    if (budget === null) return null;
    // null/undefined mean "not published" — never coerced to 0, which would
    // draw an empty slot the guard has not actually measured.
    const used = usedKwh == null ? NaN : Number(usedKwh);
    if (!Number.isFinite(used)) return null;
    const { start, end } = slotWindow(now);
    const allowed = allowedW == null ? NaN : Number(allowedW);
    return {
        label: `${hhmm(start)}–${hhmm(end)}`,
        usedKwh: used,
        budgetKwh: budget,
        fraction: Math.max(0, Math.min(1, used / budget)),
        overBudget: used >= budget,
        allowedKw: Number.isFinite(allowed) ? allowed / 1000 : null,
    };
}

/**
 * Grid import in kW from SEM's signed grid power (negative = import), or null
 * when the reading is absent. Export reads as 0 imported, not as a negative
 * import — the peak block only ever asks "how much is coming in".
 */
export function importKw(gridPowerW) {
    const w = Number(gridPowerW);
    if (!Number.isFinite(w)) return null;
    return Math.max(0, -w) / 1000;
}

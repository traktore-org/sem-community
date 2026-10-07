/**
 * (#967) The EV card's 12-h plan strip, as a pure state walk.
 *
 * `sem-ev-status-card._renderPlanStrip` used to hold this inline, with one
 * rule that lied: `night_open → charging` unless some start row carried the
 * private-selector detail `plan_ev_charge_tariff`. The joint plan's starts
 * (`plan_ev_charge_joint`) never counted, and by day the composer's fallback
 * row sat AT the window open — so @alexmc1510's strip painted "charging" from
 * 20:36, inside the punta band it painted pink itself, for a charge that
 * either waits for 00:00 or is only an estimate.
 *
 * The rule now reads the ROWS, not a detail string:
 *   - at `night_open` the state is `charging` only when an `ev_charge_start`
 *     sits at the open itself (the in-night reactive row) — a start LATER in
 *     the night, whatever produced it, means the car WAITS until then;
 *   - a start whose detail is `plan_ev_charge_estimate` (the daytime preview
 *     before the plan has seen the night) is drawn as `estimate`, never as a
 *     booked charge;
 *   - `ev_min_reached` / `ev_deadline` → `done`.
 *   - (#1023) a start whose detail is `plan_ev_charge_late` is the top-up
 *     before departure, drawn as `late`; a start that carries `until` (its
 *     window's end) charges until then and WAITS in the gap after it,
 *     instead of drawing one bar to the next row.
 * The fleet attribute `ev_tariff_waiting` is primary-charger-scoped and is
 * trusted only while the fleet fallback plan is being drawn.
 *
 * @param {Array<{kind:string, when:string, detail?:string}>} evRows
 *        the plan rows of kinds now / night_open / ev_charge_start /
 *        ev_min_reached / ev_deadline (any order)
 * @param {{now:number, end:number, usingPerPlan:boolean, fleetTariffWait:boolean}} opts
 * @returns {Array<{s:number, e:number, state:string}>}
 */
export const EV_STRIP_KINDS = ['now', 'night_open', 'ev_charge_start',
    'ev_min_reached', 'ev_deadline'];

const AT_OPEN_MS = 60 * 1000;   // the composer strips seconds; one minute is "at"

// `usingPerPlan` / `fleetTariffWait` are still passed by the card but no
// longer decide anything: a start AT the open is the only thing that makes
// the open "charging", so the fleet-scoped flag cannot mislabel a charger.
export function evStripSegments(evRows, { now, end }) {
    const rows = (evRows || [])
        .filter(r => r && EV_STRIP_KINDS.includes(r.kind))
        .map(r => ({ ...r, t: new Date(r.when).getTime() }))
        .filter(r => Number.isFinite(r.t))
        .sort((a, b) => a.t - b.t);
    const starts = rows.filter(r => r.kind === 'ev_charge_start');
    const startState = (r) => {
        if (r.detail === 'plan_ev_charge_estimate') return 'estimate';
        if (r.detail === 'plan_ev_charge_late') return 'late';
        return 'charging';
    };

    const segments = [];
    let cursor = now;
    let state = 'idle';
    let until = null;   // (#1023) the running window's own end, when known
    const closeWindow = () => {
        const at = Math.min(until, end);
        if (at > cursor) segments.push({ s: cursor, e: at, state });
        cursor = Math.max(cursor, at);
        state = 'wait';
        until = null;
    };
    for (const r of rows) {
        // A window that ends before this row leaves a gap: the car waits.
        if (until != null && until < r.t) closeWindow();
        // Clamp each transition to the horizon so the fill always covers the
        // visible window (a first event beyond it must leave a full idle bar).
        const segEnd = Math.min(r.t, end);
        if (segEnd > cursor) segments.push({ s: cursor, e: segEnd, state });
        cursor = Math.max(cursor, segEnd);
        if (r.kind === 'night_open') {
            const atOpen = starts.find(s => Math.abs(s.t - r.t) <= AT_OPEN_MS);
            // No start AT the open means the car is not charging at the
            // open — whether a later start exists (joint / tariff / estimate)
            // or the plan has not spoken yet. Either way: WAIT, never a bar.
            if (atOpen) state = startState(atOpen);
            else state = 'wait';
        } else if (r.kind === 'ev_charge_start') {
            state = startState(r);
            const u = r.until ? new Date(r.until).getTime() : NaN;
            until = Number.isFinite(u) && u > r.t ? u : null;
        } else if (r.kind === 'ev_min_reached' || r.kind === 'ev_deadline') {
            state = 'done';
            until = null;
        }
    }
    if (until != null && until < end) closeWindow();
    if (cursor < end) segments.push({ s: cursor, e: end, state });
    return segments;
}


/**
 * (#967, second round) How far the strip must look.
 *
 * The strip was a FIXED 12 hours, but what it draws is a NIGHT plan.
 * @alexmc1510 read his at 09:37: the window ended at 21:37, his charge was
 * booked 00:00 → 05:39 against a 06:00 deadline, and all that fitted on the
 * bar was a wait band starting at the window open and running off the right
 * edge — "wait status start around 9pm, not 00:00". The plan was right; the
 * window could not show it.
 *
 * So the window ends where the EV's own plan ends: the last EV row, rounded
 * up to the next whole hour so the axis reads in clean times. Never shorter
 * than the 12 h it has always been, never longer than the 24 h the composer
 * itself looks ahead (``compose_today_plan(horizon_hours=24)``) — a row
 * beyond that cannot exist.
 *
 * @param {Array<{kind:string, when:string}>} evRows the plan's EV rows
 * @param {number} now epoch ms
 * @returns {{end:number, hours:number}} the window end and its whole hours
 */
export const STRIP_MIN_HOURS = 12;
export const STRIP_MAX_HOURS = 24;      // == compose_today_plan(horizon_hours)

const HOUR_MS = 3600 * 1000;
//: the kinds that are the PLAN's own end; `night_open` is a window opening,
//: not a charge, so it never stretches the strip on its own.
const EV_PLAN_KINDS = ['ev_charge_start', 'ev_min_reached', 'ev_deadline'];

export function evStripWindow(evRows, now) {
    const floor = now + STRIP_MIN_HOURS * HOUR_MS;
    const cap = now + STRIP_MAX_HOURS * HOUR_MS;
    let last = 0;
    for (const r of evRows || []) {
        if (!r || !EV_PLAN_KINDS.includes(r.kind)) continue;
        const t = new Date(r.when).getTime();
        if (Number.isFinite(t) && t > last) last = t;
    }
    // Round UP past the last row: a deadline sitting exactly on the right
    // edge is a deadline the eye cannot find.
    const wanted = last > now ? Math.ceil((last + 1) / HOUR_MS) * HOUR_MS : 0;
    const end = Math.min(cap, Math.max(floor, wanted));
    return { end, hours: Math.max(1, Math.round((end - now) / HOUR_MS)) };
}

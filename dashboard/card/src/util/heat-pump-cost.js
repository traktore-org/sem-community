/**
 * (#1081) A heat pump's COP against the outdoor temperature — pure helpers,
 * no DOM. Both dashboards read through these.
 *
 * The curve is a goal of the device: text "°C:COP, °C:COP[, °C:COP]",
 * 2 or 3 points, written with update_device_config property cop_curve.
 * Empty = no curve: the one flat COP, the plan as before.
 *
 * The live line comes from the cost-of-heat sensor: its state is the price
 * of one kWh of heat, its attributes cop_used, cop_source ("curve" | "flat")
 * and outdoor_c (only with a curve).
 */

export const COP_CURVE_MIN_POINTS = 2;
export const COP_CURVE_MAX_POINTS = 3;

const num = (v) => {
    if (v === null || v === undefined || v === '' || typeof v === 'boolean') return null;
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
};

/** "-7:2.5, 2:3.2" → [{c:-7, cop:2.5}, …] sorted by °C, or null when it
 *  cannot be read (the same rules the server checks). */
export function parseCopCurve(raw) {
    if (raw === null || raw === undefined) return null;
    const parts = String(raw).split(',').map((p) => p.trim()).filter((p) => p !== '');
    if (parts.length < COP_CURVE_MIN_POINTS || parts.length > COP_CURVE_MAX_POINTS) return null;
    const out = [];
    for (const p of parts) {
        const bits = p.split(':');
        if (bits.length !== 2) return null;
        const c = num(bits[0].trim());
        const cop = num(bits[1].trim());
        if (c === null || cop === null || cop <= 0) return null;
        out.push({ c, cop });
    }
    out.sort((a, b) => a.c - b.c);
    for (let i = 1; i < out.length; i += 1) {
        if (out[i].c === out[i - 1].c) return null;
    }
    return out;
}

const fmt = (n) => String(Math.round(n * 10) / 10);

/** [{c, cop}] → "-7:2.5, 2:3.2"; empty or null → "" (no curve). Rows with
 *  an empty field are left out, so a half-typed row clears nothing. */
export function formatCopCurve(points) {
    const rows = (points || []).filter((p) => num(p?.c) !== null && num(p?.cop) !== null);
    if (!rows.length) return '';
    return [...rows].sort((a, b) => num(a.c) - num(b.c))
        .map((p) => `${fmt(num(p.c))}:${fmt(num(p.cop))}`).join(', ');
}

/** The editor's rows: the curve's points, padded with empty rows to 3. */
export function curveRows(raw) {
    const pts = parseCopCurve(raw) || [];
    const rows = pts.map((p) => ({ c: p.c, cop: p.cop }));
    while (rows.length < COP_CURVE_MAX_POINTS) rows.push({ c: null, cop: null });
    return rows;
}

/** What the editor may send for these rows: the text, "" to clear, or
 *  null when the rows are not a curve yet (send nothing). */
export function curveToSend(rows) {
    const text = formatCopCurve(rows);
    if (text === '') return '';
    return parseCopCurve(text) ? text : null;
}

/** The live line's numbers from the cost-of-heat sensor, or null when it
 *  has no COP. { cop, source, outdoorC, price, unit }. */
export function heatCostNow(stateObj) {
    if (!stateObj) return null;
    const a = stateObj.attributes || {};
    const cop = num(a.cop_used);
    if (cop === null || cop <= 0) return null;
    const bad = ['unknown', 'unavailable', ''].includes(String(stateObj.state ?? ''));
    return {
        cop,
        source: ['curve', 'learned'].includes(a.cop_source) ? a.cop_source : 'flat',
        outdoorC: ['curve', 'learned'].includes(a.cop_source) ? num(a.outdoor_c) : null,
        price: bad ? null : num(stateObj.state),
        unit: a.unit_of_measurement || '',
    };
}

/** The line itself, in the user's words: "COP now 3.4 at 6 °C · heat
 *  costs 0.081 CHF/kWh". ``t`` is the card's translate. */
export function heatCostLine(now, t) {
    if (!now) return '';
    const cop = fmt(now.cop);
    let line = now.outdoorC !== null
        ? t('hp_cop_now_at').replace('{cop}', cop).replace('{temp}', `${fmt(now.outdoorC)} °C`)
        : t('hp_cop_now').replace('{cop}', cop);
    if (now.price !== null) {
        const price = `${now.price.toFixed(3)} ${now.unit}`.trim();
        line += ` · ${t('hp_heat_costs').replace('{price}', price)}`;
    }
    return line;
}

/** (#1081) Where the COP comes from, as the user picks it. "" (never
 *  picked) reads as the curve when one is set, else the flat COP. */
export const COP_SOURCES = ['flat', 'curve', 'learned'];

/** The source the select shows for these goals. */
export function copSourceOf(goals) {
    const g = goals || {};
    const s = String(g.cop_source || '');
    if (COP_SOURCES.includes(s)) return s;
    return parseCopCurve(g.cop_curve) ? 'curve' : 'flat';
}

/** The choices the select offers: "learned" only once the learner has a
 *  curve (or it is already the pick, so it never vanishes from under it),
 *  "curve" only with a curve set (or already picked). */
export function copSourceOptions(goals) {
    const g = goals || {};
    const cur = copSourceOf(g);
    const out = ['flat'];
    if (parseCopCurve(g.cop_curve) || cur === 'curve') out.push('curve');
    if (g.cop_learn?.state === 'learned' || cur === 'learned') out.push('learned');
    return out;
}

/** The learner's line: "Learned from 54 hours, -6 to 11 °C", "Learning:
 *  12 hours so far", or "" without a heat meter. */
export function copLearnLine(learn, t) {
    if (!learn || learn.state === 'no_meter') return '';
    const hours = String(Math.round(num(learn.hours) || 0));
    if (learn.state === 'learned') {
        return t('hp_cop_learned_from').replace('{hours}', hours)
            .replace('{tmin}', fmt(num(learn.tmin))).replace('{tmax}', fmt(num(learn.tmax)));
    }
    return t('hp_cop_learning').replace('{hours}', hours);
}

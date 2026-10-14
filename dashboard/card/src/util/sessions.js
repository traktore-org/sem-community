/**
 * (#1024) The EV card's session list, as pure helpers.
 *
 * Rows come from the websocket command `solar_energy_management/session_history`
 * (newest first, exact doubles already dropped). Times are read from the
 * stored ISO strings as written — the local wall time of the install — so a
 * browser in another time zone shows the same 17:52 the house saw.
 */

/** 'YYYY-MM' of a stored row, or '' when it has no start. */
export function sessionMonth(row) {
    const t = String(row?.timestamp || '');
    return /^\d{4}-\d{2}/.test(t) ? t.slice(0, 7) : '';
}

/** The month before/after 'YYYY-MM'. */
export function shiftMonth(month, delta) {
    const [y, m] = month.split('-').map(Number);
    const idx = y * 12 + (m - 1) + delta;
    const ny = Math.floor(idx / 12);
    const nm = idx - ny * 12 + 1;
    return `${ny}-${String(nm).padStart(2, '0')}`;
}

/** Rows whose start falls in 'YYYY-MM', order kept. */
export function rowsForMonth(rows, month) {
    return (rows || []).filter(r => sessionMonth(r) === month);
}

const num = (v) => {
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
};

/** Totals for a set of rows. Solar share is energy-weighted; cost counts
 *  only rows that carry one (sessions stored before 2.2 have none). */
export function monthTotals(rows) {
    let kwh = 0, solarKwh = 0, cost = 0, costRows = 0, currency = '';
    let co2 = 0, co2Rows = 0;   // (#1088) only rows that carry a CO2 value
    for (const r of rows || []) {
        const e = num(r.energy_kwh) || 0;
        kwh += e;
        solarKwh += e * ((num(r.solar_share_pct) || 0) / 100);
        const c = num(r.cost);
        if (c !== null && r.cost !== '' && r.cost !== undefined && r.cost !== null) {
            cost += c; costRows += 1;
        }
        if (!currency && r.currency) currency = String(r.currency);
        if (r.co2_kg !== null && r.co2_kg !== undefined && r.co2_kg !== '' && num(r.co2_kg) !== null) {
            co2 += num(r.co2_kg); co2Rows += 1;
        }
    }
    return {
        count: (rows || []).length,
        kwh: Math.round(kwh * 10) / 10,
        solarPct: kwh > 0 ? Math.round((solarKwh / kwh) * 100) : 0,
        cost: costRows ? Math.round(cost * 100) / 100 : null,
        co2: co2Rows ? Math.round(co2 * 10) / 10 : null,
        currency,
    };
}

/** One table row, formatted. `lang` picks the weekday name. */
export function sessionRowView(row, lang = 'en') {
    const t = String(row?.timestamp || '');
    const e = String(row?.end || '');
    const date = t.slice(0, 10);
    let day = '';
    if (/^\d{4}-\d{2}-\d{2}$/.test(date)) {
        const d = new Date(`${date}T12:00:00Z`);
        let wd = '';
        try {
            wd = d.toLocaleDateString(lang || 'en', { weekday: 'short', timeZone: 'UTC' });
        } catch (_err) {
            wd = d.toLocaleDateString('en', { weekday: 'short', timeZone: 'UTC' });
        }
        day = `${wd} ${date.slice(8, 10)}.${date.slice(5, 7)}`;
    }
    const start = t.length >= 16 ? t.slice(11, 16) : '';
    const end = e.length >= 16 ? e.slice(11, 16) : '';
    const solar = num(row?.solar_share_pct);
    const cost = (row?.cost === null || row?.cost === undefined || row?.cost === '')
        ? null : num(row.cost);
    const co2 = (row?.co2_kg === null || row?.co2_kg === undefined || row?.co2_kg === '')
        ? null : num(row.co2_kg);
    const mins = num(row?.duration_min);
    const kwh = num(row?.energy_kwh);
    return {
        day,
        span: start && end ? `${start}–${end}` : start,
        kwh: kwh === null ? '' : kwh.toFixed(1),
        solar: solar === null ? '' : `${Math.round(solar)}%`,
        solarHigh: solar !== null && Math.round(solar) >= 80,   // as shown
        cost: cost === null ? '' : cost.toFixed(2),
        co2: co2 === null ? '' : co2.toFixed(1),
        min: mins === null ? '' : String(Math.round(mins)),
    };
}

/** Rows as CSV — the same columns the export service writes. */
export const CSV_COLUMNS = [
    ['start', 'timestamp'], ['end', 'end'], ['charger', 'charger_id'],
    ['energy_kwh', 'energy_kwh'], ['solar_share_pct', 'solar_share_pct'],
    ['cost', 'cost'], ['currency', 'currency'], ['duration_min', 'duration_min'],
    ['energy_source', 'energy_source'], ['co2_kg', 'co2_kg'],
];

function csvCell(v) {
    if (v === null || v === undefined) return '';
    const s = String(v);
    return /[",\n\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
}

export function sessionsCsv(rows) {
    const lines = [CSV_COLUMNS.map(c => c[0]).join(',')];
    for (const r of rows || []) {
        lines.push(CSV_COLUMNS.map(([, key]) => csvCell(r[key])).join(','));
    }
    return lines.join('\n') + '\n';
}

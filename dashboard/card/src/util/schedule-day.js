/** Pure calendar-day helpers shared by the schedule card and node tests. */

function parseTime(value) {
    if (!value || typeof value !== 'string') return null;
    const match = value.match(/^(\d{1,2}):(\d{2})$/);
    if (!match) return null;
    const hour = Number.parseInt(match[1], 10);
    const minute = Number.parseInt(match[2], 10);
    if (hour > 24 || minute > 59) return null;
    return (hour + minute / 60) / 24;
}

function normaliseBlock(block) {
    const rawType = (block.tariff || block.type || 'HT').toUpperCase();
    return {
        start: parseTime(block.start) ?? 0,
        end: parseTime(block.end) ?? 1,
        level: block.level || (rawType === 'NT' ? 'cheap' : 'normal'),
        type: rawType,
        avgPrice: block.avg_price,
    };
}

export function getScheduleForDay(attributes, day, currentLevel) {
    const key = day === 'tomorrow' ? 'schedule_tomorrow' : 'schedule_today';
    const legacyKey = day === 'tomorrow'
        ? 'tariff_schedule_tomorrow'
        : 'tariff_schedule_today';
    const schedule = attributes?.[key] || attributes?.[legacyKey];
    const status = day === 'tomorrow'
        ? (attributes?.schedule_tomorrow_status || (schedule?.length ? 'final' : 'preliminary'))
        : 'final';
    if (Array.isArray(schedule) && schedule.length > 0) {
        return { blocks: schedule.map(normaliseBlock), status };
    }

    const knownLevels = new Set([
        'cheap', 'very_cheap', 'normal', 'expensive', 'very_expensive',
    ]);
    const level = knownLevels.has(currentLevel) ? currentLevel : 'normal';
    return {
        blocks: [{
            start: 0,
            end: 1,
            level,
            type: ['cheap', 'very_cheap'].includes(level) ? 'NT' : 'HT',
            isFallback: true,
        }],
        status,
    };
}

export function getPlanWindowForDay(plan, dayStart) {
    if (!Array.isArray(plan) || !(dayStart instanceof Date)) return null;
    const dayStartDate = new Date(dayStart);
    dayStartDate.setHours(0, 0, 0, 0);
    const dayEnd = new Date(dayStartDate);
    dayEnd.setDate(dayEnd.getDate() + 1);
    const startMs = dayStartDate.getTime();
    const endMs = dayEnd.getTime();
    const dayDurationMs = endMs - startMs;
    const fraction = (when) => {
        const timestamp = new Date(when).getTime();
        if (!Number.isFinite(timestamp) || timestamp < startMs || timestamp >= endMs) {
            return null;
        }
        return (timestamp - startMs) / dayDurationMs;
    };

    let chargeStart;
    let minReached;
    let deadline;
    let kwh;
    for (const row of plan) {
        if (row.kind === 'ev_charge_start') chargeStart = fraction(row.when);
        else if (row.kind === 'ev_min_reached') {
            minReached = fraction(row.when);
            kwh = row.values?.kwh;
        } else if (row.kind === 'ev_deadline') deadline = fraction(row.when);
    }
    const end = minReached ?? deadline;
    // Charging may start before midnight. If tomorrow contains a completion or
    // deadline but no in-day start row, render the carry-over from 00:00.
    const start = chargeStart ?? (end != null ? 0 : null);
    if (start == null && end == null && deadline == null) return null;
    return {
        plan: start != null && end != null && end > start
            ? [{ start, end, kwh }] : [],
        deadlineFrac: deadline,
        minReachedFrac: minReached,
    };
}

export function getSolarIntensityForDay(peakRaw, forecastKwh) {
    const kwh = Number.parseFloat(forecastKwh);
    if (!peakRaw || Number.isNaN(kwh) || kwh < 0.5) return null;
    const peak = parseTime(String(peakRaw).slice(0, 5));
    if (peak == null) return null;
    const sigma = 0.13;
    const values = new Array(24).fill(0).map((_, hour) => {
        const x = (hour / 24) - peak;
        return Math.exp(-(x * x) / (2 * sigma * sigma));
    });
    const max = Math.max(...values);
    return values.map(value => value / max);
}

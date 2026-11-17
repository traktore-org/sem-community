// (#822) "Recommend it": the forecast source that has been closest for this
// roof. Advice only. The tap goes through the same option path the picker
// uses, and nothing switches by itself.

// The recommendation the sensor published, or null. Wrong shapes give null so
// a half-published hint never renders as a sentence with holes.
export function recommendationFrom(attrs, current) {
    const a = attrs || {};
    const source = a.recommended_source;
    const pct = Number(a.recommended_by_pct);
    const days = Number(a.recommended_days);
    if (!source || source === current) return null;
    if (!Number.isFinite(pct) || pct <= 0 || !Number.isFinite(days) || days <= 0) return null;
    return { source, pct: Math.round(pct), days: Math.round(days) };
}

// ``t`` is the card translator; ``label`` turns a source id into its name.
export function recommendationText(rec, label, t) {
    return t('forecast_recommend_text')
        .replace('{provider}', label(rec.source))
        .replace('{days}', String(rec.days))
        .replace('{pct}', String(rec.pct));
}

// ``save`` is the card's own option writer (the picker's path).
export function applyRecommendation(save, rec) {
    return save('solar_forecast_source', rec.source);
}

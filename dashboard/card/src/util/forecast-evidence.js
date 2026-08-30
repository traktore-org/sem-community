/**
 * Turning the forecast-evidence cells from statistics into explanations.
 *
 * Guido, 30.08, reading the live card: *"1D and 2D these are placeholders"*
 * (they are not — they are HORIZONS) and *"the forecast accuracy is showing
 * 119d settled, we might want to use this as well"* (it already is — the
 * ledger's p20 of those 119 ratios scales the refill, and having measured
 * trust is what removes the 1.2 pessimism margin).
 *
 * Both questions have the same root: the card states numbers and never says
 * what they MEAN or what they BOUGHT. That is #830's lesson in one line —
 * a number the user cannot explain is one they will not trust. These helpers
 * are pure so the wording is testable without a browser.
 */

/** Human names for the forecast integrations SEM can read. */
const PROVIDER_NAMES = {
    solcast: 'Solcast',
    forecast_solar: 'Forecast.Solar',
    open_meteo: 'Open-Meteo',
};

/**
 * Display name for the active forecast source.
 * Unknown/empty → null, so a caller can fall back rather than print junk.
 */
export function providerName(sourceState) {
    if (!sourceState || typeof sourceState !== 'string') return null;
    const key = sourceState.trim().toLowerCase();
    if (!key || key === 'unknown' || key === 'unavailable' || key === 'none') return null;
    return PROVIDER_NAMES[key] || key.replace(/_/g, ' ');
}

/**
 * The label for one horizon cell: the provider and the horizon in words.
 * `t` is the card's translator; `days` is 1 or 2.
 */
export function horizonLabel(sourceState, days, t) {
    const provider = providerName(sourceState);
    const when = days === 1 ? t('horizon_tomorrow') : t('horizon_two_days');
    return provider ? `${provider} · ${when}` : `${t('forecast_accuracy')} · ${when}`;
}

/**
 * What this horizon's evidence BOUGHT — the consequence line.
 *
 * `trusted` mirrors `RefillEstimate.trusted`: a measured per-horizon factor
 * was applied. When it is, `spendable_budget` drops the blanket pessimism
 * margin ("caution is not counted twice"); when it is not, that margin is
 * what stands in for the missing measurement.
 */
export function trustConsequence({ available, trust, days, minDays, t }) {
    if (available === false) return t('horizon_not_published');
    if (trust == null) {
        return t('horizon_learning_effect').replace('{days}', String(days ?? 0))
                                           .replace('{needed}', String(minDays ?? 7));
    }
    return t('horizon_trusted_effect');
}

/** What the pack-size evidence bought: measured capacity, or the nameplate. */
export function capacityConsequence({ measuredKwh, nameplateKwh, t }) {
    if (measuredKwh == null) return t('capacity_using_nameplate');
    if (nameplateKwh == null) return t('capacity_using_measured');
    const delta = measuredKwh - nameplateKwh;
    if (Math.abs(delta) < 0.05) return t('capacity_matches_nameplate');
    return t('capacity_using_measured');
}

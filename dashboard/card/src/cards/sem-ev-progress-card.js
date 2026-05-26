/**
 * SEM EV Progress Card — LitElement migration
 *
 * Shows EV daily progress bar against a configurable kWh target,
 * plus lifetime statistics (energy, solar share, cost, sessions).
 *
 * Entities watched:
 *   sensor.sem_daily_ev_energy
 *   sensor.sem_lifetime_ev_energy
 *   sensor.sem_lifetime_ev_solar_share
 *   sensor.sem_lifetime_ev_cost
 *   sensor.sem_lifetime_ev_sessions
 *   number.sem_daily_ev_target
 */

import { SEMLitBase, html, css, nothing } from '../base/sem-lit-base.js';
import { semTheme, semDefineCard, semGetCurrency } from '../base/sem-shared.js';

/* ── Watched entity IDs (resolved from prefix at render time) ── */
const SUFFIX_DAILY_EV_ENERGY       = 'daily_ev_energy';
const SUFFIX_LIFETIME_EV_ENERGY    = 'lifetime_ev_energy';
const SUFFIX_LIFETIME_EV_SOLAR     = 'lifetime_ev_solar_share';
const SUFFIX_LIFETIME_EV_COST      = 'lifetime_ev_cost';
const SUFFIX_LIFETIME_EV_SESSIONS  = 'lifetime_ev_sessions';
const DEFAULT_PREFIX               = 'sensor.sem_';

class SEMEvProgressCard extends SEMLitBase {
    /**
     * Static list used by SEMLitBase.hass setter to detect relevant state changes.
     * The prefix is baked in at class level with the default; cards with a custom
     * prefix still benefit because any change to the sensor namespace triggers a
     * re-render — the minor over-fire is acceptable.
     */
    static get watchedEntities() {
        return [
            `${DEFAULT_PREFIX}${SUFFIX_DAILY_EV_ENERGY}`,
            `${DEFAULT_PREFIX}${SUFFIX_LIFETIME_EV_ENERGY}`,
            `${DEFAULT_PREFIX}${SUFFIX_LIFETIME_EV_SOLAR}`,
            `${DEFAULT_PREFIX}${SUFFIX_LIFETIME_EV_COST}`,
            `${DEFAULT_PREFIX}${SUFFIX_LIFETIME_EV_SESSIONS}`,
            'number.sem_daily_ev_target',
            // Per-charger target (default charger id) so the bar reacts to the
            // EV-card slider; other ids still refresh on the energy tick. (#245)
            'number.sem_charger_ev_charger_daily_ev_target',
        ];
    }

    /** EV daily kWh target — prefer the per-charger value the EV-card slider
     *  edits; fall back to the legacy global number entity. (#245) */
    _evDailyTarget() {
        const st = this._hass?.states || {};
        const perCharger = Object.keys(st)
            .filter(id => /^number\.sem_charger_.+_daily_ev_target$/.test(id))
            .sort();
        if (perCharger.length) {
            const v = parseFloat(st[perCharger[0]]?.state);
            if (!isNaN(v)) return v;
        }
        return this._state('number.sem_daily_ev_target', 10);
    }

    setConfig(config) {
        super.setConfig(config);
    }

    /* ── Derived helpers ── */

    /** Resolve prefix — sensor entities share DEFAULT_PREFIX; number entity is fixed. */
    _prefix() {
        return this._config?.entity_prefix ?? DEFAULT_PREFIX;
    }

    _pct(daily, target) {
        if (target <= 0) return 0;
        return Math.min(100, (daily / target) * 100);
    }

    _barColor(target, pct) {
        if (target === 0) return '#666';
        if (pct >= 100) return '#8DC892';
        if (pct >= 70)  return '#ff9800';
        return '#f44336';
    }

    _fmtEnergy(kwh) {
        if (kwh == null || isNaN(kwh)) return '—';
        return kwh.toFixed(kwh < 10 ? 2 : 1) + ' kWh';
    }

    _fmtCost(value, currency) {
        if (value == null || isNaN(value)) return '—';
        return value.toFixed(2) + ' ' + currency;
    }

    _fmtSessions(n) {
        if (n == null || isNaN(n)) return '—';
        return String(Math.round(n));
    }

    /* ── Render ── */

    render() {
        if (!this._hass || !this._config) return nothing;

        const T      = this._theme();
        const prefix = this._prefix();

        const daily    = this._state(`${prefix}${SUFFIX_DAILY_EV_ENERGY}`);
        const target   = this._evDailyTarget();
        const ltEnergy = this._state(`${prefix}${SUFFIX_LIFETIME_EV_ENERGY}`);
        const ltSolar  = this._state(`${prefix}${SUFFIX_LIFETIME_EV_SOLAR}`);
        const ltCost   = this._state(`${prefix}${SUFFIX_LIFETIME_EV_COST}`);
        const ltSess   = this._state(`${prefix}${SUFFIX_LIFETIME_EV_SESSIONS}`);
        const currency = semGetCurrency(this._hass);

        const pct   = this._pct(daily, target);
        const color = this._barColor(target, pct);

        const targetLabel = target > 0
            ? html`<span class="target-pct">${Math.round(pct)}% ${this._t('of_target')}</span>`
            : html`<span class="target-pct no-target">${this._t('no_target')}</span>`;

        /* dot-grid background: green glow matching EV palette */
        const dotGridBg = [
            'radial-gradient(ellipse 80% 70% at 20% 50%, rgba(141,200,146,0.06) 0%, transparent 70%)',
            `radial-gradient(circle at 2px 2px, ${T.dotColor} 0.7px, transparent 0.7px)`,
        ].join(', ');

        return html`
            <style>
                :host {
                    display: block;
                    font-family: 'Segoe UI', 'Roboto', sans-serif;
                }

                .card {
                    background: ${T.cardBg};
                    background-image: ${dotGridBg};
                    background-size: auto, 16px 16px;
                    border-radius: 12px;
                    padding: 16px;
                    box-shadow: ${T.shadow};
                    color: ${T.text};
                }

                /* ── Progress section ── */
                .progress-header {
                    display: flex;
                    align-items: center;
                    gap: 10px;
                    margin-bottom: 10px;
                }

                .ev-icon {
                    font-size: 22px;
                    color: #8DC892;
                    flex-shrink: 0;
                    display: flex;
                    align-items: center;
                }

                .ev-icon ha-icon {
                    --mdc-icon-size: 22px;
                    color: #8DC892;
                }

                .progress-info {
                    flex: 1;
                    min-width: 0;
                }

                .progress-label {
                    font-size: 13px;
                    font-weight: 600;
                    color: ${T.text};
                    letter-spacing: 0.3px;
                }

                .progress-values {
                    font-size: 12px;
                    color: ${T.textSec};
                    margin-top: 2px;
                }

                .target-pct {
                    font-size: 11px;
                    color: ${T.textSec};
                    margin-top: 1px;
                    display: block;
                }

                .no-target {
                    opacity: 0.6;
                    font-style: italic;
                }

                /* ── Progress bar ── */
                .progress-track {
                    height: 6px;
                    border-radius: 3px;
                    background: ${T.surface};
                    border: 1px solid ${T.surfaceBorder};
                    overflow: hidden;
                    margin-top: 10px;
                }

                .progress-fill {
                    height: 100%;
                    border-radius: 3px;
                    transition: width 0.5s ease, background 0.3s ease;
                }

                /* ── Section divider ── */
                .divider {
                    height: 1px;
                    background: ${T.divider};
                    margin: 14px 0;
                }

                /* ── Lifetime stats section ── */
                .lifetime-label {
                    font-size: 11px;
                    font-weight: 600;
                    text-transform: uppercase;
                    letter-spacing: 1px;
                    color: ${T.textSec};
                    margin-bottom: 10px;
                }

                .stats-grid {
                    display: grid;
                    grid-template-columns: 1fr 1fr 1fr 1fr;
                    gap: 8px;
                }

                @media (max-width: 400px) {
                    .stats-grid {
                        grid-template-columns: 1fr 1fr;
                    }
                }

                .stat-tile {
                    background: ${T.surface};
                    border: 1px solid ${T.surfaceBorder};
                    border-radius: 8px;
                    padding: 10px 8px;
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    gap: 4px;
                    text-align: center;
                }

                .stat-icon ha-icon {
                    --mdc-icon-size: 18px;
                    color: #8DC892;
                }

                .stat-value {
                    font-size: 13px;
                    font-weight: 700;
                    color: ${T.text};
                    line-height: 1.2;
                }

                .stat-label {
                    font-size: 10px;
                    color: ${T.textSec};
                    letter-spacing: 0.3px;
                    line-height: 1.2;
                }
            </style>

            <div class="card">
                <!-- Progress section -->
                <div class="progress-header">
                    <div class="ev-icon">
                        <ha-icon icon="mdi:car-electric"></ha-icon>
                    </div>
                    <div class="progress-info">
                        <div class="progress-label">${this._t('daily_progress')}</div>
                        <div class="progress-values">
                            ${this._fmtEnergy(daily)}${target > 0 ? ` / ${this._fmtEnergy(target)}` : ''}
                        </div>
                        ${targetLabel}
                    </div>
                </div>

                <div class="progress-track">
                    <div
                        class="progress-fill"
                        style="width:${pct}%;background:${color}"
                    ></div>
                </div>

                <div class="divider"></div>

                <!-- Lifetime stats section -->
                <div class="lifetime-label">${this._t('lifetime_stats')}</div>
                <div class="stats-grid">
                    <div class="stat-tile">
                        <div class="stat-icon"><ha-icon icon="mdi:lightning-bolt"></ha-icon></div>
                        <div class="stat-value">${this._fmtEnergy(ltEnergy)}</div>
                        <div class="stat-label">${this._t('energy')}</div>
                    </div>
                    <div class="stat-tile">
                        <div class="stat-icon"><ha-icon icon="mdi:weather-sunny"></ha-icon></div>
                        <div class="stat-value">${Math.round(ltSolar)}%</div>
                        <div class="stat-label">${this._t('solar')}</div>
                    </div>
                    <div class="stat-tile">
                        <div class="stat-icon"><ha-icon icon="mdi:currency-usd"></ha-icon></div>
                        <div class="stat-value">${this._fmtCost(ltCost, currency)}</div>
                        <div class="stat-label">${this._t('cost')}</div>
                    </div>
                    <div class="stat-tile">
                        <div class="stat-icon"><ha-icon icon="mdi:counter"></ha-icon></div>
                        <div class="stat-value">${this._fmtSessions(ltSess)}</div>
                        <div class="stat-label">${this._t('sessions')}</div>
                    </div>
                </div>
            </div>
        `;
    }

    getCardSize() { return 3; }

    static getStubConfig() {
        return { entity_prefix: DEFAULT_PREFIX };
    }
}

const cardInfo = {
    type: 'sem-ev-progress-card',
    name: 'SEM EV Progress Card',
    description: 'Daily EV progress bar and lifetime charging statistics',
};

semDefineCard('sem-ev-progress-card', SEMEvProgressCard, cardInfo);

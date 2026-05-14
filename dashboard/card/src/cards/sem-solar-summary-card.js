/**
 * SEM Solar Summary Card — LitElement migration
 *
 * Solar overview with glow ring, production metrics, self-use/autarky/cost/savings.
 * SVG progress arc shows daily yield vs forecast.
 *
 * Config:
 *   type: custom:sem-solar-summary-card
 *   entity_prefix: sensor.sem_   # default
 */

import { SEMLitBase, html, css, nothing } from '../base/sem-lit-base.js';
import { semTheme, semFormatPower, semGetCurrency, semDefineCard } from '../base/sem-shared.js';

const DEFAULT_PREFIX = 'sensor.sem_';

const ENTITY_SUFFIXES = [
    'solar_power',
    'daily_solar_energy',
    'monthly_solar_yield_energy',
    'forecast_today_kwh',
    'forecast_tomorrow_kwh',
    'self_consumption_rate',
    'autarky_rate',
    'daily_costs',
    'daily_savings',
    'daily_ev_energy',
    'daily_grid_import_energy',
];

function buildEntityIds(prefix) {
    return ENTITY_SUFFIXES.map(s => `${prefix}${s}`);
}

class SEMSolarSummaryCard extends SEMLitBase {
    static get watchedEntities() {
        return buildEntityIds(DEFAULT_PREFIX);
    }

    setConfig(config) {
        super.setConfig(config);
        this._prefix = config.entity_prefix || DEFAULT_PREFIX;
        if (this._prefix !== DEFAULT_PREFIX) {
            this._prevVals = {};
        }
    }

    // ── Override hass setter for dynamic prefix entity tracking ──
    set hass(hass) {
        this._hass = hass;

        const lang = hass?.language;
        const hasLocalize = typeof semLocalize === 'function';
        let localeChanged = false;
        if (lang !== this._lang || (hasLocalize && !this._localizeReady)) {
            this._lang = lang;
            this._localizeReady = hasLocalize;
            localeChanged = true;
        }

        if (this._isFrozen() && !localeChanged) return;

        const ids = buildEntityIds(this._prefix || DEFAULT_PREFIX);
        let changed = false;
        for (const id of ids) {
            if (this._prevVals[id] !== hass.states[id]?.state) {
                changed = true;
                break;
            }
        }
        if (!changed && !localeChanged) return;

        for (const id of ids) {
            this._prevVals[id] = hass.states[id]?.state;
        }

        this._scheduleUpdate();
    }

    get hass() {
        return this._hass;
    }

    // ── Prefix-scoped entity helpers ──
    _val(suffix, fallback = 0) {
        return this._state(`${this._prefix}${suffix}`, fallback);
    }

    _valStr(suffix) {
        return this._stateStr(`${this._prefix}${suffix}`);
    }

    _fmt(val, decimals = 1) {
        if (val == null || isNaN(val)) return '—';
        return val.toFixed(decimals);
    }

    // ── Render ──
    render() {
        if (!this._config) return nothing;

        const T = this._theme();

        const solarPower    = this._val('solar_power');
        const dailySolar    = this._val('daily_solar_energy');
        const monthlySolar  = this._val('monthly_solar_yield_energy');
        const forecastToday = this._val('forecast_today_kwh');
        const fcTomorrow    = this._val('forecast_tomorrow_kwh');
        const selfUse       = this._val('self_consumption_rate');
        const autarky       = this._val('autarky_rate');
        const dailyCost     = this._val('daily_costs');
        const dailySavings  = this._val('daily_savings');
        const dailyEv       = this._val('daily_ev_energy');
        const gridToday     = this._val('daily_grid_import_energy');

        const currency = semGetCurrency(this._hass);

        // Glow ring opacity based on power ratio (0–10 kW)
        const maxExpected = 10000;
        const powerRatio  = Math.min(solarPower / maxExpected, 1);
        const glowOpacity = (0.15 + powerRatio * 0.6).toFixed(3);

        // Progress arc: daily yield vs forecast
        const circumference = 2 * Math.PI * 42;
        const arcPct        = forecastToday > 0 ? Math.min(dailySolar / forecastToday, 1) : 0;
        const arcOffset     = (circumference * (1 - arcPct)).toFixed(1);

        return html`
            <style>
                :host { display: block; }
                .wrap {
                    padding: 20px;
                    position: relative;
                    background:
                        radial-gradient(ellipse 70% 60% at 50% 25%, rgba(255,152,0,0.06) 0%, transparent 100%),
                        radial-gradient(circle at 2px 2px, ${T.dotColor} 0.7px, transparent 0.7px);
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    color: var(--primary-text-color, ${T.text});
                }
                .glow-svg { position: absolute; width: 0; height: 0; overflow: hidden; }

                /* Hero section */
                .hero {
                    display: flex;
                    align-items: center;
                    gap: 20px;
                    margin-bottom: 20px;
                }
                .solar-ring {
                    position: relative;
                    width: 100px;
                    height: 100px;
                    flex-shrink: 0;
                }
                .solar-ring svg {
                    width: 100%;
                    height: 100%;
                    transform: rotate(-90deg);
                }
                .ring-bg {
                    fill: none;
                    stroke: rgba(255,152,0,0.12);
                    stroke-width: 5;
                }
                .progress-arc {
                    fill: none;
                    stroke: #ff9800;
                    stroke-width: 5;
                    stroke-linecap: round;
                    transition: stroke-dashoffset 1.5s cubic-bezier(0.4,0,0.2,1);
                    filter: url(#solar-glow);
                }
                .ring-icon {
                    position: absolute;
                    top: 50%;
                    left: 50%;
                    transform: translate(-50%, -50%);
                    text-align: center;
                }
                .ring-icon .power {
                    font-size: 18px;
                    font-weight: 700;
                    font-variant-numeric: tabular-nums;
                    color: #ff9800;
                    text-shadow: 0 0 8px rgba(255,152,0,0.3);
                }
                .ring-icon .label {
                    font-size: 10px;
                    color: rgba(255,152,0,0.6);
                    font-weight: 500;
                    letter-spacing: 1px;
                    text-transform: uppercase;
                }
                .hero-stats {
                    flex: 1;
                    min-width: 0;
                }
                .hero-title {
                    font-size: 13px;
                    font-weight: 600;
                    color: rgba(255,152,0,0.85);
                    letter-spacing: 0.5px;
                    margin-bottom: 8px;
                }
                .hero-row {
                    display: flex;
                    justify-content: space-between;
                    align-items: baseline;
                    padding: 3px 0;
                }
                .hero-label {
                    font-size: 12px;
                    color: var(--secondary-text-color, ${T.textSec});
                    font-weight: 500;
                }
                .hero-value {
                    font-size: 13px;
                    font-weight: 600;
                    font-variant-numeric: tabular-nums;
                }

                /* Metrics grid */
                .metrics {
                    display: grid;
                    grid-template-columns: repeat(3, 1fr);
                    gap: 10px;
                }
                .metric {
                    background: var(--secondary-background-color, ${T.surface});
                    border: 1px solid var(--divider-color, ${T.surfaceBorder});
                    border-radius: 10px;
                    padding: 10px;
                    text-align: center;
                    transition: border-color 0.3s cubic-bezier(0.4,0,0.2,1);
                }
                .metric:hover {
                    border-color: var(--divider-color, ${T.surfaceHover});
                }
                .metric-label {
                    font-size: 10px;
                    color: var(--secondary-text-color, ${T.textTertiary});
                    font-weight: 500;
                    letter-spacing: 0.3px;
                    margin-bottom: 4px;
                }
                .metric-value {
                    font-size: 14px;
                    font-weight: 600;
                    font-variant-numeric: tabular-nums;
                }
                .c-solar   { color: #ff9800; }
                .c-grid    { color: #488fc2; }
                .c-ev      { color: #8DC892; }
                .c-home    { color: #5BC8D8; }
                .c-savings { color: #4db6ac; }
                .c-cost    { color: #f06292; }
            </style>

            <!-- SVG glow filters -->
            <svg class="glow-svg" aria-hidden="true">
                <defs>
                    <filter id="solar-glow" x="-50%" y="-50%" width="200%" height="200%">
                        <feGaussianBlur stdDeviation="3" result="blur"/>
                        <feFlood flood-color="#ff9800" flood-opacity="0.25" result="color"/>
                        <feComposite in="color" in2="blur" operator="in" result="glow"/>
                        <feMerge><feMergeNode in="glow"/><feMergeNode in="SourceGraphic"/></feMerge>
                    </filter>
                    <filter id="solar-glow-soft" x="-50%" y="-50%" width="200%" height="200%">
                        <feGaussianBlur stdDeviation="6" result="blur"/>
                        <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
                    </filter>
                </defs>
            </svg>

            <ha-card>
                <div class="wrap">

                    <!-- Hero -->
                    <div class="hero">
                        <div class="solar-ring">
                            <svg viewBox="0 0 100 100">
                                <circle cx="50" cy="50" r="42"
                                    fill="none" stroke="#ff9800" stroke-width="8"
                                    filter="url(#solar-glow-soft)"
                                    style="opacity:${glowOpacity}">
                                    <animate attributeName="r" values="42;45;42" dur="3s" repeatCount="indefinite"/>
                                    <animate attributeName="opacity" values="${glowOpacity};${(parseFloat(glowOpacity)*0.4).toFixed(3)};${glowOpacity}" dur="3s" repeatCount="indefinite"/>
                                </circle>
                                <circle class="ring-bg" cx="50" cy="50" r="42"/>
                                <circle class="progress-arc" cx="50" cy="50" r="42"
                                    stroke-dasharray="${circumference.toFixed(1)}"
                                    style="stroke-dashoffset:${arcOffset}"/>
                            </svg>
                            <div class="ring-icon">
                                <div class="power">${semFormatPower(solarPower)}</div>
                                <div class="label">${this._t('solar').toUpperCase()}</div>
                            </div>
                        </div>

                        <div class="hero-stats">
                            <div class="hero-title">${this._t('production')}</div>
                            <div class="hero-row">
                                <span class="hero-label">${this._t('yield_today')}</span>
                                <span class="hero-value c-solar">${this._fmt(dailySolar, 2)} kWh</span>
                            </div>
                            <div class="hero-row">
                                <span class="hero-label">${this._t('grid_today')}</span>
                                <span class="hero-value c-grid">${this._fmt(gridToday, 2)} kWh</span>
                            </div>
                            <div class="hero-row">
                                <span class="hero-label">${this._t('forecast')}</span>
                                <span class="hero-value c-solar">${this._fmt(forecastToday, 1)} kWh</span>
                            </div>
                            <div class="hero-row">
                                <span class="hero-label">${this._t('tomorrow')}</span>
                                <span class="hero-value" style="color:var(--secondary-text-color)">${this._fmt(fcTomorrow, 1)} kWh</span>
                            </div>
                        </div>
                    </div>

                    <!-- Metrics 3x2 grid -->
                    <div class="metrics">
                        <div class="metric">
                            <div class="metric-label">${this._t('self_use')}</div>
                            <div class="metric-value c-home">${this._fmt(selfUse, 1)}%</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">${this._t('autarky')}</div>
                            <div class="metric-value c-savings">${this._fmt(autarky, 1)}%</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">${this._t('ev_today')}</div>
                            <div class="metric-value c-ev">${this._fmt(dailyEv, 1)} kWh</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">${this._t('cost')}</div>
                            <div class="metric-value c-cost">${this._fmt(dailyCost, 2)} ${currency}</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">${this._t('saved')}</div>
                            <div class="metric-value c-savings">${this._fmt(dailySavings, 2)} ${currency}</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">${this._t('monthly')}</div>
                            <div class="metric-value c-solar">${this._fmt(monthlySolar, 1)} kWh</div>
                        </div>
                    </div>

                </div>
            </ha-card>
        `;
    }

    getCardSize() { return 4; }

    static getStubConfig() {
        return { entity_prefix: DEFAULT_PREFIX };
    }
}

semDefineCard('sem-solar-summary-card', SEMSolarSummaryCard, {
    type: 'sem-solar-summary-card',
    name: 'SEM Solar Summary',
    description: 'Lumina-styled solar overview with glow ring and production metrics',
});

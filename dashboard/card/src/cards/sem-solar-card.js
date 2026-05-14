/**
 * SEM Solar Card — LitElement migration
 *
 * Consolidated solar production card with SVG arc ring, flow breakdown,
 * forecast, and performance metrics.
 *
 * Config:
 *   type: custom:sem-solar-card
 *   entity_prefix: sensor.sem_   # default
 */

import { SEMLitBase, html, css, nothing } from '../base/sem-lit-base.js';
import { semTheme, semFormatPower, semDefineCard } from '../base/sem-shared.js';

const DEFAULT_PREFIX = 'sensor.sem_';

const ENTITY_SUFFIXES = [
    'solar_power',
    'daily_solar_energy',
    'monthly_solar_yield_energy',
    'yearly_solar_yield_energy',
    'flow_solar_to_home_power',
    'flow_solar_to_battery_power',
    'flow_solar_to_ev_power',
    'flow_solar_to_grid_power',
    'flow_solar_to_home_energy',
    'flow_solar_to_battery_energy',
    'flow_solar_to_ev_energy',
    'flow_solar_to_grid_energy',
    'forecast_today_kwh',
    'forecast_tomorrow_kwh',
    'forecast_remaining_today_kwh',
    'forecast_peak_power_today_w',
    'forecast_peak_time_today',
    'best_surplus_window',
    'pv_daily_specific_yield',
    'pv_performance_vs_forecast',
    'pv_estimated_annual_degradation',
    'pv_degradation_trend',
];

function buildEntityIds(prefix) {
    return ENTITY_SUFFIXES.map(s => `${prefix}${s}`);
}

class SEMSolarCard extends SEMLitBase {
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

        const power         = this._val('solar_power');
        const dailyEnergy   = this._val('daily_solar_energy');
        const monthlyEnergy = this._val('monthly_solar_yield_energy');
        const yearlyEnergy  = this._val('yearly_solar_yield_energy');

        // Arc ring (0–10 kW)
        const maxPower     = 10000;
        const pct          = Math.min(Math.max(power / maxPower, 0), 1);
        const circumference = 2 * Math.PI * 42;
        const arcOffset    = (circumference * (1 - pct)).toFixed(1);
        const arcAnim      = power > 50 ? 'solarPulse 3s ease-in-out infinite' : 'none';

        // Flow values
        const fHomePow  = this._val('flow_solar_to_home_power');
        const fHomeEn   = this._val('flow_solar_to_home_energy');
        const fBattPow  = this._val('flow_solar_to_battery_power');
        const fBattEn   = this._val('flow_solar_to_battery_energy');
        const fEvPow    = this._val('flow_solar_to_ev_power');
        const fEvEn     = this._val('flow_solar_to_ev_energy');
        const fGridPow  = this._val('flow_solar_to_grid_power');
        const fGridEn   = this._val('flow_solar_to_grid_energy');

        // Forecast values
        const fcToday     = this._val('forecast_today_kwh');
        const fcTomorrow  = this._val('forecast_tomorrow_kwh');
        const fcRemaining = this._val('forecast_remaining_today_kwh');
        const peakW       = this._val('forecast_peak_power_today_w');
        const peakTime    = this._valStr('forecast_peak_time_today');
        const surplusWin  = this._valStr('best_surplus_window');

        // Performance values
        const specYield  = this._val('pv_daily_specific_yield');
        const vsFC       = this._val('pv_performance_vs_forecast');
        const degradation = this._val('pv_estimated_annual_degradation');
        const trend      = this._valStr('pv_degradation_trend');

        const vsFCText  = vsFC !== 0 ? this._fmt(vsFC, 0) + '%' : '—';
        const vsFCColor = vsFC >= 0 ? '#8DC892' : '#f06292';

        return html`
            <style>
                :host { display: block; }
                .wrap {
                    padding: 16px 20px;
                    position: relative;
                    background:
                        radial-gradient(ellipse 70% 60% at 50% 20%, rgba(255,152,0,0.07) 0%, transparent 100%),
                        radial-gradient(circle at 2px 2px, ${T.dotColor} 0.7px, transparent 0.7px);
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    color: var(--primary-text-color, ${T.text});
                }
                .glow-svg { position: absolute; width: 0; height: 0; overflow: hidden; }

                /* ── Hero ── */
                .hero { display: flex; align-items: center; gap: 20px; }
                @media (max-width: 400px) { .hero { flex-direction: column; gap: 12px; } }

                .solar-ring { position: relative; width: 100px; height: 100px; flex-shrink: 0; }
                .solar-ring svg { width: 100%; height: 100%; transform: rotate(-90deg); }
                .ring-bg { fill: none; stroke: rgba(255,152,0,0.12); stroke-width: 5; }
                .solar-arc {
                    fill: none; stroke: #ff9800; stroke-width: 5; stroke-linecap: round;
                    transition: stroke-dashoffset 1.5s cubic-bezier(0.4,0,0.2,1);
                    filter: url(#solar-glow);
                }
                .solar-glow-ring {
                    fill: none; stroke: #ff9800; stroke-width: 8; opacity: 0.2;
                    filter: url(#solar-glow-soft);
                }
                @keyframes solarPulse { 0%,100%{opacity:1}50%{opacity:0.6} }

                .ring-center {
                    position: absolute; top: 50%; left: 50%;
                    transform: translate(-50%, -50%);
                    text-align: center; pointer-events: none;
                }
                .solar-power-value {
                    font-size: 13px; font-weight: 700;
                    font-variant-numeric: tabular-nums;
                    color: #ff9800;
                    text-shadow: 0 0 8px rgba(255,152,0,0.35);
                    line-height: 1.2;
                }
                .solar-daily-value {
                    font-size: 10px; color: var(--secondary-text-color,${T.textSec});
                    font-variant-numeric: tabular-nums;
                }

                /* ── Section ── */
                .section {
                    margin-top: 12px;
                    padding: 10px 12px;
                    background: var(--secondary-background-color, ${T.surface});
                    border: 1px solid var(--divider-color, ${T.surfaceBorder});
                    border-radius: 10px;
                }
                .section-title {
                    font-size: 10px; font-weight: 600; text-transform: uppercase;
                    letter-spacing: 0.6px; color: #ff9800; margin-bottom: 8px;
                }

                /* ── Flows grid ── */
                .flows-grid {
                    display: grid;
                    grid-template-columns: 1fr 1fr;
                    gap: 8px 24px;
                }
                .flow-row { display: flex; align-items: center; gap: 6px; }
                .flow-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
                .flow-label { font-size: 11px; color: var(--secondary-text-color,${T.textSec}); flex: 1; }
                .flow-vals { text-align: right; }
                .flow-power {
                    font-size: 11px; font-weight: 600;
                    font-variant-numeric: tabular-nums;
                    color: var(--primary-text-color,${T.text});
                }
                .flow-energy {
                    font-size: 9px; color: var(--secondary-text-color,${T.textSec});
                    font-variant-numeric: tabular-nums;
                }

                /* ── Two-column section ── */
                .two-col {
                    display: grid;
                    grid-template-columns: 1fr 1fr;
                    gap: 0 20px;
                }
                @media (max-width: 400px) { .two-col { grid-template-columns: 1fr; } }

                /* ── Metric rows ── */
                .metric-row {
                    display: flex; justify-content: space-between; align-items: baseline;
                    padding: 2px 0;
                }
                .metric-label {
                    font-size: 11px; color: var(--secondary-text-color,${T.textSec});
                    font-weight: 500;
                }
                .metric-val {
                    font-size: 12px; font-weight: 600;
                    font-variant-numeric: tabular-nums;
                    color: var(--primary-text-color,${T.text});
                }

                /* ── Monthly / yearly chips ── */
                .chips { display: flex; gap: 8px; margin-top: 10px; }
                .chip {
                    flex: 1; text-align: center; padding: 7px 8px;
                    background: var(--secondary-background-color, ${T.surface});
                    border: 1px solid var(--divider-color, ${T.surfaceBorder});
                    border-radius: 10px;
                }
                .chip-label {
                    font-size: 10px; color: var(--secondary-text-color,${T.textTertiary});
                    font-weight: 500; margin-bottom: 2px;
                }
                .chip-value {
                    font-size: 13px; font-weight: 600; color: #ff9800;
                    font-variant-numeric: tabular-nums;
                }
            </style>

            <!-- SVG glow filters -->
            <svg class="glow-svg" aria-hidden="true">
                <defs>
                    <filter id="solar-glow" x="-50%" y="-50%" width="200%" height="200%">
                        <feGaussianBlur stdDeviation="4" result="blur"/>
                        <feFlood flood-color="#ff9800" flood-opacity="0.3" result="color"/>
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
                                <circle class="solar-glow-ring" cx="50" cy="50" r="42">
                                    <animate attributeName="opacity" values="0.2;0.07;0.2" dur="4s" repeatCount="indefinite"/>
                                </circle>
                                <circle class="ring-bg" cx="50" cy="50" r="42"/>
                                <circle class="solar-arc" cx="50" cy="50" r="42"
                                    stroke-dasharray="${circumference.toFixed(1)}"
                                    style="stroke-dashoffset:${arcOffset};animation:${arcAnim}"/>
                            </svg>
                            <div class="ring-center">
                                <ha-icon icon="mdi:solar-power" style="--mdc-icon-size:22px;color:#ff9800;opacity:0.8"></ha-icon>
                                <div class="solar-power-value">${semFormatPower(power)}</div>
                                <div class="solar-daily-value">${this._fmt(dailyEnergy, 2)} kWh</div>
                            </div>
                        </div>

                        <!-- Monthly + Yearly chips -->
                        <div style="flex:1;min-width:0">
                            <div class="chips" style="margin-top:0">
                                <div class="chip">
                                    <div class="chip-label">${this._t('monthly')}</div>
                                    <div class="chip-value">${this._fmt(monthlyEnergy, 1)} kWh</div>
                                </div>
                                <div class="chip">
                                    <div class="chip-label">${this._t('yearly')}</div>
                                    <div class="chip-value">${this._fmt(yearlyEnergy, 1)} kWh</div>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- Today's Flows -->
                    <div class="section">
                        <div class="section-title">${this._t('solar_flows_today')}</div>
                        <div class="flows-grid">
                            <div class="flow-row">
                                <div class="flow-dot" style="background:#5BC8D8"></div>
                                <span class="flow-label">${this._t('home')}</span>
                                <div class="flow-vals">
                                    <div class="flow-power">${semFormatPower(fHomePow)}</div>
                                    <div class="flow-energy">${this._fmt(fHomeEn, 2)} kWh</div>
                                </div>
                            </div>
                            <div class="flow-row">
                                <div class="flow-dot" style="background:#f06292"></div>
                                <span class="flow-label">${this._t('battery')}</span>
                                <div class="flow-vals">
                                    <div class="flow-power">${semFormatPower(fBattPow)}</div>
                                    <div class="flow-energy">${this._fmt(fBattEn, 2)} kWh</div>
                                </div>
                            </div>
                            <div class="flow-row">
                                <div class="flow-dot" style="background:#8DC892"></div>
                                <span class="flow-label">${this._t('ev')}</span>
                                <div class="flow-vals">
                                    <div class="flow-power">${semFormatPower(fEvPow)}</div>
                                    <div class="flow-energy">${this._fmt(fEvEn, 2)} kWh</div>
                                </div>
                            </div>
                            <div class="flow-row">
                                <div class="flow-dot" style="background:#8353d1"></div>
                                <span class="flow-label">${this._t('grid_export')}</span>
                                <div class="flow-vals">
                                    <div class="flow-power">${semFormatPower(fGridPow)}</div>
                                    <div class="flow-energy">${this._fmt(fGridEn, 2)} kWh</div>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- Forecast + Performance (side by side) -->
                    <div class="section two-col">
                        <div>
                            <div class="section-title">${this._t('forecast')}</div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t('today')}</span>
                                <span class="metric-val">${this._fmt(fcToday, 1)} kWh</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t('tomorrow')}</span>
                                <span class="metric-val">${this._fmt(fcTomorrow, 1)} kWh</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t('remaining')}</span>
                                <span class="metric-val">${this._fmt(fcRemaining, 1)} kWh</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t('peak_power')}</span>
                                <span class="metric-val">
                                    ${peakW > 0 ? semFormatPower(peakW) : '—'}
                                    <span style="font-size:10px;opacity:0.7;margin-left:4px">${peakTime || '—'}</span>
                                </span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t('best_surplus_window')}</span>
                                <span class="metric-val" style="color:#ff9800;font-size:11px">${surplusWin || '—'}</span>
                            </div>
                        </div>
                        <div>
                            <div class="section-title">${this._t('performance')}</div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t('specific_yield')}</span>
                                <span class="metric-val">${specYield > 0 ? this._fmt(specYield, 2) + ' kWh/kWp' : '—'}</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t('vs_forecast')}</span>
                                <span class="metric-val" style="color:${vsFCColor}">${vsFCText}</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t('degradation')}</span>
                                <span class="metric-val">${degradation !== 0 ? this._fmt(degradation, 2) + '%/yr' : '—'}</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t('trend')}</span>
                                <span class="metric-val">${trend || '—'}</span>
                            </div>
                        </div>
                    </div>

                </div>
            </ha-card>
        `;
    }

    getCardSize() { return 5; }

    static getStubConfig() {
        return { entity_prefix: DEFAULT_PREFIX };
    }
}

semDefineCard('sem-solar-card', SEMSolarCard, {
    type: 'sem-solar-card',
    name: 'SEM Solar',
    description: 'Consolidated solar production card with flows, forecast, and performance metrics',
});

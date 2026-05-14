/**
 * SEM Home Status Card — LitElement migration
 *
 * Consolidated status panel for the Home tab.
 * Replaces 7 mushroom cards with a single interactive card showing:
 *  1. Status chips row (solar, battery, autarky, EV, score)
 *  2. Smart energy tip + best surplus window
 *  3. Peak load status
 *  4. Quick controls (observer toggle + forecast provider)
 *  5. Environmental impact (CO2 today + lifetime)
 *
 * Config:
 *   type: custom:sem-home-status-card
 *   entity_prefix: sensor.sem_   # optional, default
 */

import { SEMLitBase, html, css, nothing } from '../base/sem-lit-base.js';
import { semTheme, semFormatPower, semDefineCard } from '../base/sem-shared.js';

const DEFAULT_PREFIX = 'sensor.sem_';

const WATCHED = [
    'sensor.sem_solar_power',
    'sensor.sem_battery_soc',
    'sensor.sem_autarky_rate',
    'sensor.sem_ev_power',
    'sensor.sem_energy_optimization_score',
    'sensor.sem_energy_tip',
    'sensor.sem_best_surplus_window',
    'sensor.sem_forecast_remaining_today_kwh',
    'sensor.sem_current_vs_peak_percentage',
    'sensor.sem_consecutive_peak_15min',
    'sensor.sem_target_peak_limit',
    'sensor.sem_daily_co2_avoided',
    'sensor.sem_lifetime_co2_avoided',
    'sensor.sem_diag_forecast_provider',
    'switch.sem_observer_mode',
];

class SEMHomeStatusCard extends SEMLitBase {
    static get watchedEntities() {
        return WATCHED;
    }

    setConfig(config) {
        super.setConfig(config);
        this._prefix = config.entity_prefix || DEFAULT_PREFIX;
    }

    _val(suffix, fallback = 0) {
        const e = this._hass?.states[`${this._prefix}${suffix}`];
        if (!e || e.state === 'unavailable' || e.state === 'unknown') return fallback;
        return parseFloat(e.state) || fallback;
    }

    _valStr(suffix) {
        const e = this._hass?.states[`${this._prefix}${suffix}`];
        return (e && e.state !== 'unavailable' && e.state !== 'unknown') ? e.state : '';
    }

    _switchOn(entityId) {
        const frozen = this._frozenEntities[entityId];
        if (frozen) return frozen.value === 'on';
        return this._hass?.states[entityId]?.state === 'on';
    }

    _scoreColor(score) {
        if (score >= 80) return '#8DC892';
        if (score >= 50) return '#ff9800';
        return '#f44336';
    }

    _peakColor(pct) {
        if (pct > 90) return '#f44336';
        if (pct > 70) return '#ff9800';
        return '#8DC892';
    }

    _peakStatusKey(pct) {
        if (pct > 90) return 'peak_critical';
        if (pct > 70) return 'peak_warning';
        return 'peak_safe';
    }

    _renderChip(icon, color, value) {
        return html`
            <div class="chip">
                <ha-icon icon="${icon}" style="--mdc-icon-size:16px;color:${color}"></ha-icon>
                <span class="chip-val">${value}</span>
            </div>
        `;
    }

    render() {
        if (!this._config || !this._hass) return nothing;

        const solar = this._val('solar_power');
        const soc = this._val('battery_soc');
        const autarky = this._val('autarky_rate');
        const evPower = this._val('ev_power');
        const score = this._val('energy_optimization_score');
        const scoreColor = this._scoreColor(score);

        const tip = this._valStr('energy_tip');
        const surplusWindow = this._valStr('best_surplus_window') || '—';
        const remaining = this._val('forecast_remaining_today_kwh').toFixed(1);

        const peakPct = this._val('current_vs_peak_percentage');
        const peakColor = this._peakColor(peakPct);
        const currentPeak = this._val('consecutive_peak_15min').toFixed(1);
        const targetLimit = this._val('target_peak_limit').toFixed(1);

        const observerOn = this._switchOn('switch.sem_observer_mode');
        const provider = this._valStr('diag_forecast_provider') || '—';

        const co2Today = this._val('daily_co2_avoided').toFixed(2);
        const co2Life = this._val('lifetime_co2_avoided').toFixed(1);

        return html`
            <div class="wrap">

                <!-- 1. Status Chips -->
                <div class="chips-row">
                    ${this._renderChip('mdi:solar-power', '#ff9800', semFormatPower(solar))}
                    ${this._renderChip('mdi:battery', '#4db6ac', `${soc.toFixed(0)}%`)}
                    ${this._renderChip('mdi:leaf', '#8DC892', `${autarky.toFixed(0)}%`)}
                    ${this._renderChip('mdi:car-electric', '#8DC892', evPower > 0 ? semFormatPower(evPower) : '—')}
                    <div class="chip">
                        <ha-icon icon="mdi:speedometer" style="--mdc-icon-size:16px;color:${scoreColor}"></ha-icon>
                        <span class="chip-val">${score.toFixed(0)}</span>
                    </div>
                </div>

                <div class="divider"></div>

                <!-- 2. Smart Tip -->
                <div class="tip-section" style="opacity:${tip ? '1' : '0'};pointer-events:${tip ? 'auto' : 'none'}">
                    <ha-icon icon="mdi:lightbulb-on-outline"
                             style="--mdc-icon-size:20px;color:#ff9800"></ha-icon>
                    <div class="tip-content">
                        <span class="section-label">${this._t('smart_tip')}</span>
                        <span class="tip-primary">${tip || ''}</span>
                        <span class="tip-secondary">
                            ${this._t('best_window')}: ${surplusWindow} &middot; ${this._t('surplus')}: ${remaining} kWh
                        </span>
                    </div>
                </div>
                <div class="divider" style="opacity:${tip ? '1' : '0'}"></div>

                <!-- 3. Peak Load -->
                <div class="section-label">${this._t('peak_load')}</div>
                <div class="peak-row">
                    <div class="peak-icon-wrap">
                        <ha-icon icon="mdi:flash-alert"
                                 style="--mdc-icon-size:22px;color:#ff9800"></ha-icon>
                        <span class="peak-pct" style="color:${peakColor}">${peakPct.toFixed(0)}%</span>
                    </div>
                    <div class="peak-text-wrap">
                        <span class="peak-detail">${currentPeak} / ${targetLimit} kW (${peakPct.toFixed(0)}%)</span>
                        <span class="peak-status-badge" style="color:${peakColor};border-color:${peakColor}">
                            ${this._t(this._peakStatusKey(peakPct))}
                        </span>
                    </div>
                </div>

                <div class="divider"></div>

                <!-- 4. Forecast Info -->
                <div class="section-label">${this._t('quick_controls')}</div>
                <div class="controls-row">
                    <div class="forecast-chip">
                        <ha-icon icon="mdi:weather-partly-cloudy"
                                 style="--mdc-icon-size:16px;color:#96CAEE"></ha-icon>
                        <span class="forecast-label">${this._t('forecast')}</span>
                        <span class="forecast-val">${provider}</span>
                    </div>
                </div>

                <div class="divider"></div>

                <!-- 5. Environmental Impact -->
                <div class="section-label">${this._t('environmental_impact')}</div>
                <div class="env-row">
                    <div class="env-chip">
                        <ha-icon icon="mdi:leaf"
                                 style="--mdc-icon-size:18px;color:#8DC892"></ha-icon>
                        <div class="env-chip-content">
                            <span class="env-chip-val">${co2Today} kg</span>
                            <span class="env-chip-label">${this._t('co2_today')}</span>
                        </div>
                    </div>
                    <div class="env-chip">
                        <ha-icon icon="mdi:tree"
                                 style="--mdc-icon-size:18px;color:#8DC892"></ha-icon>
                        <div class="env-chip-content">
                            <span class="env-chip-val">${co2Life} kg</span>
                            <span class="env-chip-label">${this._t('co2_lifetime')}</span>
                        </div>
                    </div>
                </div>

            </div>
        `;
    }

    static get styles() {
        return css`
            :host { display: block; }

            .wrap {
                padding: 16px;
                position: relative;
                font-family: 'Segoe UI','Roboto',sans-serif;
                color: var(--primary-text-color, #e0e0e0);
                background:
                    radial-gradient(ellipse 70% 60% at 50% 25%, rgba(91,200,216,0.06) 0%, transparent 100%),
                    radial-gradient(circle at 2px 2px, rgba(128,128,128,0.05) 0.7px, transparent 0.7px);
                background-size: 100% 100%, 50px 50px;
            }

            /* ── Section label ── */
            .section-label {
                font-size: 10px;
                font-weight: 600;
                text-transform: uppercase;
                letter-spacing: 0.6px;
                color: var(--secondary-text-color, #999);
                margin-bottom: 6px;
            }

            /* ── Divider ── */
            .divider {
                height: 1px;
                background: var(--divider-color, rgba(255,255,255,0.12));
                margin: 12px 0;
            }

            /* ─────────────────── 1. Chips ─────────────────── */
            .chips-row {
                display: flex;
                gap: 6px;
                overflow-x: auto;
                padding-bottom: 4px;
                scrollbar-width: none;
                -ms-overflow-style: none;
            }
            .chips-row::-webkit-scrollbar { display: none; }

            .chip {
                display: inline-flex; align-items: center; gap: 4px;
                padding: 4px 10px;
                border-radius: 12px;
                border: 1px solid var(--divider-color, rgba(255,255,255,0.12));
                background: var(--secondary-background-color, rgba(255,255,255,0.06));
                white-space: nowrap;
                flex-shrink: 0;
                backdrop-filter: blur(16px) saturate(160%);
                -webkit-backdrop-filter: blur(16px) saturate(160%);
            }
            .chip-val {
                font-size: 12px;
                font-weight: 600;
                font-variant-numeric: tabular-nums;
            }

            /* ─────────────────── 2. Tip ─────────────────── */
            .tip-section {
                display: flex; gap: 10px; align-items: flex-start;
                padding: 10px 12px;
                border-radius: 12px;
                background: rgba(255,152,0,0.06);
                border: 1px solid rgba(255,152,0,0.20);
            }
            .tip-section ha-icon { flex-shrink: 0; margin-top: 1px; }
            .tip-content { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
            .tip-primary {
                font-size: 13px; font-weight: 500; line-height: 1.4;
            }
            .tip-secondary {
                font-size: 11px;
                color: var(--secondary-text-color, #999);
                line-height: 1.3;
            }

            /* ─────────────────── 3. Peak ─────────────────── */
            .peak-row {
                display: flex; align-items: center; gap: 10px;
            }
            .peak-icon-wrap {
                display: flex; align-items: center; gap: 6px;
                flex-shrink: 0;
            }
            .peak-pct {
                font-size: 22px; font-weight: 700;
                font-variant-numeric: tabular-nums;
                line-height: 1;
            }
            .peak-text-wrap {
                display: flex; flex-direction: column; gap: 2px;
                min-width: 0;
            }
            .peak-detail {
                font-size: 12px;
                color: var(--secondary-text-color, #999);
                white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
            }
            .peak-status-badge {
                display: inline-block;
                font-size: 10px; font-weight: 600;
                text-transform: uppercase; letter-spacing: 0.4px;
                padding: 2px 7px;
                border-radius: 8px;
                border: 1px solid;
                align-self: flex-start;
            }

            /* ─────────────────── 4. Quick controls ─────────────────── */
            .controls-row {
                display: flex; gap: 12px; align-items: center;
                flex-wrap: wrap;
            }
            .observer-toggle {
                display: flex; align-items: center; gap: 8px;
                flex: 1; min-width: 120px;
            }
            .observer-toggle-label {
                font-size: 13px; font-weight: 500; flex: 1;
            }
            .toggle-track {
                position: relative;
                width: 42px; height: 24px;
                border-radius: 12px;
                background: rgba(255,255,255,0.15);
                cursor: pointer;
                transition: background 0.2s;
                flex-shrink: 0;
            }
            .toggle-track.on { background: var(--primary-color, #42a5f5); }
            .toggle-thumb {
                position: absolute;
                top: 2px; left: 2px;
                width: 20px; height: 20px;
                border-radius: 50%;
                background: white;
                box-shadow: 0 1px 3px rgba(0,0,0,0.3);
                transition: left 0.2s;
            }
            .toggle-track.on .toggle-thumb { left: 20px; }

            .forecast-chip {
                display: flex; align-items: center; gap: 6px;
                padding: 4px 10px;
                border-radius: 12px;
                border: 1px solid var(--divider-color, rgba(255,255,255,0.12));
                background: var(--secondary-background-color, rgba(255,255,255,0.06));
                flex-shrink: 0;
            }
            .forecast-label {
                font-size: 11px;
                color: var(--secondary-text-color, #999);
                font-weight: 500;
            }
            .forecast-val { font-size: 12px; font-weight: 600; }

            /* ─────────────────── 5. Environmental ─────────────────── */
            .env-row {
                display: flex; gap: 8px; flex-wrap: wrap;
            }
            .env-chip {
                display: flex; align-items: center; gap: 6px;
                padding: 6px 12px;
                border-radius: 12px;
                border: 1px solid rgba(141,200,146,0.25);
                background: rgba(141,200,146,0.06);
                flex: 1; min-width: 120px;
            }
            .env-chip ha-icon { flex-shrink: 0; }
            .env-chip-content { display: flex; flex-direction: column; gap: 0; }
            .env-chip-val {
                font-size: 13px; font-weight: 600;
                font-variant-numeric: tabular-nums;
            }
            .env-chip-label {
                font-size: 10px;
                color: var(--secondary-text-color, #999);
                text-transform: uppercase; letter-spacing: 0.3px;
            }

            @media (max-width: 400px) {
                .env-row { flex-direction: column; }
                .controls-row { flex-direction: column; align-items: flex-start; }
            }
        `;
    }

    getCardSize() { return 5; }

    static getStubConfig() {
        return { entity_prefix: 'sensor.sem_' };
    }
}

semDefineCard('sem-home-status-card', SEMHomeStatusCard, {
    type: 'custom:sem-home-status-card',
    name: 'SEM Home Status Card',
    description: 'Consolidated status panel for the SEM Home tab',
    preview: false,
});

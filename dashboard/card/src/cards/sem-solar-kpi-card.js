/**
 * SEM Solar KPI Card (#556)
 *
 * Prominent "Today's Solar Production" hero for the top of the Home
 * tab — the daily kWh in large type (requested by @hrdilshan: the
 * header chip was too easy to miss), with the live solar power as a
 * small secondary chip while the sun is up.
 *
 * Config:
 *   type: custom:sem-solar-kpi-card
 *   entity_prefix: sensor.sem_   # optional, default
 */

import { SEMLitBase, html, css, nothing } from '../base/sem-lit-base.js';
import { semFormatPower, semDefineCard } from '../base/sem-shared.js';

const DEFAULT_PREFIX = 'sensor.sem_';

const WATCHED = [
    'sensor.sem_daily_solar_energy',
    'sensor.sem_solar_power',
];

class SEMSolarKpiCard extends SEMLitBase {
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
        const v = parseFloat(e.state);
        return Number.isFinite(v) ? v : fallback;
    }

    static get styles() {
        return css`
                :host { display: block; }
                .kpi {
                    display: flex;
                    align-items: center;
                    gap: 18px;
                    padding: 18px 22px;
                }
                .kpi-icon {
                    flex: 0 0 auto;
                    width: 52px;
                    height: 52px;
                    border-radius: 14px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    background: rgba(255, 152, 0, 0.14);
                }
                .kpi-icon ha-icon {
                    color: #ff9800;
                    --mdc-icon-size: 32px;
                }
                .kpi-main { flex: 1 1 auto; min-width: 0; }
                .kpi-value {
                    font-size: 2.6rem;
                    font-weight: 700;
                    line-height: 1.1;
                    color: #ff9800;
                    letter-spacing: -0.5px;
                    white-space: nowrap;
                }
                .kpi-value .unit {
                    font-size: 1.3rem;
                    font-weight: 500;
                    opacity: 0.85;
                    margin-left: 4px;
                }
                .kpi-label {
                    margin-top: 2px;
                    font-size: 0.85rem;
                    color: var(--secondary-text-color);
                    text-transform: uppercase;
                    letter-spacing: 0.6px;
                }
                .kpi-now {
                    flex: 0 0 auto;
                    display: flex;
                    align-items: center;
                    gap: 6px;
                    padding: 6px 12px;
                    border-radius: 999px;
                    background: var(--secondary-background-color, rgba(255,255,255,0.06));
                    font-size: 0.9rem;
                    color: var(--primary-text-color);
                }
                .kpi-now ha-icon {
                    color: #ff9800;
                    --mdc-icon-size: 16px;
                }
                @media (max-width: 460px) {
                    .kpi { padding: 14px 16px; gap: 12px; }
                    .kpi-value { font-size: 2.1rem; }
                    .kpi-icon { width: 44px; height: 44px; }
                }
            `;
    }

    render() {
        if (!this._hass) return nothing;
        const today = this._val('daily_solar_energy');
        const power = this._val('solar_power');
        return html`
            <ha-card>
                <div class="kpi">
                    <div class="kpi-icon"><ha-icon icon="mdi:solar-power-variant"></ha-icon></div>
                    <div class="kpi-main">
                        <div class="kpi-value">${today.toFixed(1)}<span class="unit">kWh</span></div>
                        <div class="kpi-label">${this._t('todays_solar_production')}</div>
                    </div>
                    ${power > 0 ? html`
                        <div class="kpi-now">
                            <ha-icon icon="mdi:white-balance-sunny"></ha-icon>
                            <span>${semFormatPower(power)}</span>
                        </div>
                    ` : nothing}
                </div>
            </ha-card>
        `;
    }

    getCardSize() { return 1; }
    static getStubConfig() { return {}; }
}

semDefineCard('sem-solar-kpi-card', SEMSolarKpiCard, {
    type: 'sem-solar-kpi-card',
    name: 'SEM Solar KPI Card',
    description: "Prominent Today's Solar Production KPI for the Home tab",
    documentationURL:
        'https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-solar-kpi-card',
    preview: true,
});

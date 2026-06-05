/**
 * SEM Battery Zones Card — LitElement SOC zone configuration
 *
 * Stepper grid for priority/buffer/auto-start/floor SOC thresholds,
 * with a visual gradient zone bar and hold-to-repeat interaction.
 */

import { SEMLitBase, html, css, nothing } from '../base/sem-lit-base.js';
import { semTheme, semDefineCard } from '../base/sem-shared.js';

const ZONES = [
    { id: 'autostart', entity: 'number.sem_battery_auto_start_soc', icon: 'mdi:play-circle',        labelKey: 'auto_start_soc', color: '#4db6ac' },
    { id: 'buffer',    entity: 'number.sem_battery_buffer_soc',    icon: 'mdi:shield-half-full',    labelKey: 'buffer_soc',    color: '#ff9800' },
    { id: 'floor',     entity: 'number.sem_battery_assist_floor_soc', icon: 'mdi:arrow-collapse-down', labelKey: 'assist_floor', color: '#488fc2' },
    { id: 'priority',  entity: 'number.sem_battery_priority_soc',  icon: 'mdi:shield-alert',       labelKey: 'priority_soc',  color: '#f44336' },
];

class SEMBatteryZonesCard extends SEMLitBase {
    static get watchedEntities() {
        return ZONES.map(z => z.entity);
    }

    setConfig(config) {
        super.setConfig(config);
    }

    _getDecimalsForZone(entityId) {
        const entity = this._hass?.states[entityId];
        const step = entity ? parseFloat(entity.attributes.step) || 1 : 1;
        return step < 1 ? 1 : 0;
    }

    _renderZoneMarkers(T) {
        return ZONES.map(z => {
            const val = this._state(z.entity);
            return html`
                <div class="zone-marker" style="left:${val}%">
                    <div class="zone-dot" style="background:${z.color};border-color:${T.isDark ? '#1e232d' : '#fff'}"></div>
                    <span class="zone-marker-label">${val.toFixed(0)}%</span>
                </div>
            `;
        });
    }

    _renderStepper(z, T) {
        const val = this._state(z.entity);
        const decimals = this._getDecimalsForZone(z.entity);
        const label = this._t(z.labelKey);

        return html`
            <div class="stepper-row">
                <ha-icon icon="${z.icon}" style="--mdc-icon-size:18px;color:${z.color}"></ha-icon>
                <span class="stepper-label">${label}</span>
                <div class="stepper-controls">
                    <button
                        class="stepper-minus"
                        aria-label="Decrease ${label}"
                        @click=${() => this._stepNumber(z.entity, -1)}
                        @pointerdown=${() => this._startHold(z.entity, -1)}
                        @pointerup=${() => this._stopHold(z.entity)}
                        @pointerleave=${() => this._stopHold(z.entity)}
                    >−</button>
                    <span class="stepper-value">${val.toFixed(decimals)}%</span>
                    <button
                        class="stepper-plus"
                        aria-label="Increase ${label}"
                        @click=${() => this._stepNumber(z.entity, 1)}
                        @pointerdown=${() => this._startHold(z.entity, 1)}
                        @pointerup=${() => this._stopHold(z.entity)}
                        @pointerleave=${() => this._stopHold(z.entity)}
                    >+</button>
                </div>
            </div>
        `;
    }

    render() {
        if (!this._config) return nothing;

        const T = this._theme();
        const autostart = this._state(ZONES[0].entity);
        const buffer    = this._state(ZONES[1].entity);
        const priority  = this._state(ZONES[3].entity);
        const subtitle  = `${this._t('auto_start_soc')} ${autostart.toFixed(0)}% · Buffer ${buffer.toFixed(0)}% · ${this._t('priority_soc')} ${priority.toFixed(0)}%`;

        return html`
            <style>
                :host { display: block; contain: layout style paint; }
                .wrap {
                    padding: 16px;
                    background:
                        radial-gradient(ellipse 70% 60% at 50% 25%, rgba(77,182,172,0.06) 0%, transparent 100%),
                        radial-gradient(circle at 2px 2px, ${T.dotColor} 0.7px, transparent 0.7px);
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    color: var(--primary-text-color, ${T.text});
                }
                .header {
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    margin-bottom: 12px;
                }
                .header-title {
                    font-size: 14px;
                    font-weight: 600;
                    color: #4db6ac;
                }
                .subtitle {
                    flex: 1;
                    text-align: right;
                    font-size: 12px;
                    color: var(--secondary-text-color, ${T.textSec});
                    overflow: hidden;
                    text-overflow: ellipsis;
                    white-space: nowrap;
                }
                .zone-bar-wrap {
                    margin: 0 0 14px;
                    padding: 0 4px;
                }
                .zone-bar {
                    position: relative;
                    height: 8px;
                    border-radius: 4px;
                    background: linear-gradient(90deg, #f44336 0%, #ff9800 30%, #4db6ac 60%, #488fc2 80%, #8DC892 100%);
                    opacity: 0.6;
                }
                .zone-marker {
                    position: absolute;
                    top: -6px;
                    transform: translateX(-50%);
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    transition: left 0.3s ease;
                }
                .zone-dot {
                    width: 10px;
                    height: 10px;
                    border-radius: 50%;
                    border: 2px solid;
                    box-shadow: 0 0 4px rgba(0,0,0,0.3);
                }
                .zone-marker-label {
                    font-size: 9px;
                    font-weight: 600;
                    margin-top: 2px;
                    color: var(--secondary-text-color, ${T.textSec});
                    font-variant-numeric: tabular-nums;
                }
                .stepper-grid {
                    display: grid;
                    grid-template-columns: 1fr 1fr;
                    gap: 4px 16px;
                }
                .stepper-row {
                    display: flex;
                    align-items: center;
                    gap: 6px;
                    padding: 6px 0;
                }
                .stepper-label {
                    font-size: 12px;
                    font-weight: 500;
                    flex: 1;
                    min-width: 0;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    white-space: nowrap;
                }
                .stepper-controls {
                    display: flex;
                    align-items: center;
                    gap: 2px;
                    flex-shrink: 0;
                }
                .stepper-minus, .stepper-plus {
                    width: 28px;
                    height: 28px;
                    border-radius: 7px;
                    border: 1px solid ${T.surfaceBorder};
                    background: ${T.surface};
                    color: var(--primary-text-color, ${T.text});
                    font-size: 15px;
                    font-weight: 600;
                    cursor: pointer;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    transition: background 0.15s;
                    user-select: none;
                    -webkit-user-select: none;
                    touch-action: manipulation;
                    padding: 0;
                    line-height: 1;
                }
                .stepper-minus:hover, .stepper-plus:hover {
                    background: ${T.surfaceHover};
                }
                .stepper-value {
                    font-size: 13px;
                    font-weight: 600;
                    min-width: 48px;
                    text-align: center;
                    font-variant-numeric: tabular-nums;
                }
                @media (max-width: 480px) {
                    .stepper-grid { grid-template-columns: 1fr; }
                }
            </style>
            <div class="wrap">
                <div class="header">
                    <ha-icon icon="mdi:battery-charging-medium" style="--mdc-icon-size:18px;color:#4db6ac"></ha-icon>
                    <span class="header-title">${this._t('soc_zones')}</span>
                    <span class="subtitle">${subtitle}</span>
                </div>
                <div class="zone-bar-wrap">
                    <div class="zone-bar">
                        ${this._renderZoneMarkers(T)}
                    </div>
                </div>
                <div class="stepper-grid">
                    ${ZONES.map(z => this._renderStepper(z, T))}
                </div>
            </div>
        `;
    }

    getCardSize() { return 4; }
    static getStubConfig() { return {}; }
}

semDefineCard('sem-battery-zones-card', SEMBatteryZonesCard, {
    type: 'custom:sem-battery-zones-card',
    name: 'SEM Battery Zones Card',
    description: 'SOC zone configuration for Solar Energy Management',
    preview: false,
});

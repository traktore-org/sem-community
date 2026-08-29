/**
 * SEM Gauge Card — Lumina-styled arc gauge
 *
 * Replaces native HA gauge cards with a dark-theme-consistent SVG arc.
 * Used for Self-consumption and Autarky on the Energy tab.
 *
 * Config:
 *   type: custom:sem-gauge-card
 *   entity: sensor.sem_self_consumption_rate
 *   name: Self-consumption      # optional override
 *   min: 0                      # default 0
 *   max: 100                    # default 100
 *   color: '#4db6ac'            # arc color, default teal
 */

import { SEMLitBase, html, css, svg, nothing } from '../base/sem-lit-base.js';
import { semTheme, semDefineCard } from '../base/sem-shared.js';

class SEMGaugeCard extends SEMLitBase {
    static get watchedEntities() { return []; }

    setConfig(config) {
        if (!config.entity) throw new Error('sem-gauge-card requires entity');
        super.setConfig(config);
        this._entity = config.entity;
        this._name = config.name || null;
        this._min = config.min ?? 0;
        this._max = config.max ?? 100;
        this._color = config.color || '#4db6ac';
        this._unit = config.unit || '%';
    }

    set hass(hass) {
        const old = this._hass;
        this._hass = hass;
        const newState = hass?.states[this._entity]?.state;
        if (newState !== this._lastState) {
            this._lastState = newState;
            this.requestUpdate();
        }
    }
    get hass() { return this._hass; }

    render() {
        if (!this._hass || !this._config) return nothing;

        const entity = this._hass.states[this._entity];
        const val = entity ? parseFloat(entity.state) || 0 : 0;
        const name = this._name || entity?.attributes?.friendly_name || this._entity;
        const pct = Math.min(Math.max((val - this._min) / (this._max - this._min), 0), 1);
        const T = this._theme();
        const color = this._color;

        // SVG arc: 240 degree sweep (from -210 to 30 degrees)
        const R = 58;
        const sweep = 240;
        const startAngle = -210;
        const endAngle = startAngle + sweep * pct;
        const totalArc = sweep;

        const toXY = (angle) => {
            const rad = (angle * Math.PI) / 180;
            return { x: 70 + R * Math.cos(rad), y: 70 + R * Math.sin(rad) };
        };

        const bgStart = toXY(startAngle);
        const bgEnd = toXY(startAngle + totalArc);
        const arcEnd = toXY(endAngle);
        const bgLargeArc = totalArc > 180 ? 1 : 0;
        const arcSweep = sweep * pct;
        const largeArc = arcSweep > 180 ? 1 : 0;

        // Color interpolation: red at 0%, yellow at 50%, green at 100%
        const dynamicColor = pct < 0.5
            ? `color-mix(in srgb, #f44336 ${Math.round((1 - pct * 2) * 100)}%, #ff9800)`
            : `color-mix(in srgb, ${color} ${Math.round((pct - 0.5) * 2 * 100)}%, #ff9800)`;

        return html`
            <ha-card>
                <div class="gauge-wrap">
                    <svg viewBox="0 0 140 100" xmlns="http://www.w3.org/2000/svg">
                        <defs>
                            <filter id="glow-${this._entity.replace(/\./g, '_')}" x="-20%" y="-20%" width="140%" height="140%">
                                <feGaussianBlur stdDeviation="3" result="blur"/>
                                <feFlood flood-color="${dynamicColor}" flood-opacity="0.3"/>
                                <feComposite in2="blur" operator="in"/>
                                <feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge>
                            </filter>
                        </defs>
                        <!-- Background arc -->
                        <path d="M ${bgStart.x} ${bgStart.y} A ${R} ${R} 0 ${bgLargeArc} 1 ${bgEnd.x} ${bgEnd.y}"
                              fill="none" stroke="${T.surface || 'rgba(255,255,255,0.08)'}" stroke-width="8"
                              stroke-linecap="round"/>
                        <!-- Value arc -->
                        ${pct > 0.01 ? svg`
                            <path d="M ${bgStart.x} ${bgStart.y} A ${R} ${R} 0 ${largeArc} 1 ${arcEnd.x} ${arcEnd.y}"
                                  fill="none" stroke="${dynamicColor}" stroke-width="8"
                                  stroke-linecap="round"
                                  filter="url(#glow-${this._entity.replace(/\./g, '_')})"
                                  style="transition: d 1s ease"/>
                        ` : ''}
                    </svg>
                    <div class="gauge-center">
                        <span class="gauge-value" style="color:${dynamicColor}">${val.toFixed(1)}${this._unit}</span>
                    </div>
                    <div class="gauge-label">${name}</div>
                </div>
            </ha-card>
        `;
    }

    static get styles() {
        return css`
            :host { display: block; }
            ha-card {
                background: transparent !important;
                border: none !important;
                box-shadow: none !important;
            }
            .gauge-wrap {
                position: relative;
                display: flex;
                flex-direction: column;
                align-items: center;
                padding: 16px 16px 8px;
            }
            svg {
                width: 180px;
                height: 130px;
            }
            .gauge-center {
                position: absolute;
                top: 65px;
                left: 50%;
                transform: translateX(-50%);
                text-align: center;
            }
            .gauge-value {
                font-size: 28px;
                font-weight: 700;
                font-variant-numeric: tabular-nums;
                font-family: 'Segoe UI', 'Roboto', sans-serif;
            }
            .gauge-label {
                font-size: 13px;
                font-weight: 500;
                color: var(--secondary-text-color, #9e9e9e);
                text-align: center;
                margin-top: -8px;
                font-family: 'Segoe UI', 'Roboto', sans-serif;
            }
        `;
    }

    getCardSize() { return 3; }
    static getStubConfig() { return { entity: 'sensor.sem_self_consumption_rate' }; }
}

semDefineCard('sem-gauge-card', SEMGaugeCard, {
    type: 'sem-gauge-card',
    name: 'SEM Gauge Card',
    description: 'Lumina-styled arc gauge for percentage values',
    documentationURL:
        'https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-gauge-card',
    preview: false,
});

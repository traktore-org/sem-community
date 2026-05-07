/**
 * SEM Charger Status Card — Multi-charger status display
 *
 * Dynamically discovers all SEM charger entities and renders
 * per-charger tiles with power, session energy, solar share,
 * and taper status. Fully translatable via semLocalize().
 *
 * Config:
 *   type: custom:sem-charger-status-card
 *   entity_prefix: sensor.sem_   # optional, default
 */

class SEMChargerStatusCard extends HTMLElement {
    constructor() {
        super();
        this.attachShadow({ mode: 'open' });
        this._rendered = false;
        this._lastKey = '';
        this._chargers = [];
    }

    setConfig(config) {
        this.config = config;
        this._prefix = config.entity_prefix || 'sensor.sem_';
    }

    _t(key) {
        const lang = this._hass?.language;
        return (typeof semLocalize === 'function') ? semLocalize(key, lang) : key;
    }

    set hass(hass) {
        this._hass = hass;

        // Discover chargers dynamically from sensor.sem_charger_*_power
        const chargers = [];
        for (const eid of Object.keys(hass.states)) {
            const match = eid.match(/^sensor\.sem_charger_(.+)_power$/);
            if (match) {
                chargers.push(match[1]);
            }
        }
        this._chargers = chargers;

        // Build reactivity key
        const key = chargers.map(id => [
            `charger_${id}_power`, `charger_${id}_session_energy`,
            `charger_${id}_session_solar_share`, `charger_${id}_taper_trend`,
        ].map(s => hass.states[`${this._prefix}${s}`]?.state || '').join(':')).join('|');

        if (key === this._lastKey) return;
        this._lastKey = key;

        if (!this._rendered) {
            this._renderSkeleton();
            this._rendered = true;
        }
        this._update();
    }

    _state(suffix, fallback = 0) {
        const e = this._hass?.states[`${this._prefix}${suffix}`];
        if (!e || e.state === 'unavailable' || e.state === 'unknown') return fallback;
        return parseFloat(e.state) || fallback;
    }

    _stateStr(suffix) {
        const e = this._hass?.states[`${this._prefix}${suffix}`];
        return (e && e.state !== 'unavailable' && e.state !== 'unknown') ? e.state : '';
    }

    _update() {
        const grid = this.shadowRoot.querySelector('.charger-grid');
        if (!grid) return;

        grid.innerHTML = this._chargers.map(id => {
            const power = this._state(`charger_${id}_power`);
            const session = this._state(`charger_${id}_session_energy`);
            const solar = this._state(`charger_${id}_session_solar_share`);
            const taper = this._stateStr(`charger_${id}_taper_trend`) || 'stable';

            // Derive name from friendly_name or charger id
            const entity = this._hass?.states[`${this._prefix}charger_${id}_power`];
            let name = id.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
            if (entity?.attributes?.friendly_name) {
                name = entity.attributes.friendly_name
                    .replace(/^SEM\s+/i, '')
                    .replace(/\s+Power$/i, '');
            }

            const isCharging = power > 50;
            const statusColor = isCharging ? '#8DC892' : '#888';
            const statusText = isCharging ? this._t('charging') : this._t('idle');
            const glowOpacity = isCharging ? '0.15' : '0';

            return `
                <div class="charger-tile">
                    <div class="charger-glow" style="opacity:${glowOpacity}"></div>
                    <div class="charger-header">
                        <ha-icon icon="mdi:ev-station" style="--mdc-icon-size:20px;color:${statusColor}"></ha-icon>
                        <span class="charger-name">${name}</span>
                        <span class="charger-status" style="color:${statusColor}">${statusText}</span>
                    </div>
                    <div class="charger-metrics">
                        <div class="metric">
                            <span class="metric-value">${power.toFixed(0)}</span>
                            <span class="metric-unit">W</span>
                            <span class="metric-label">${this._t('power')}</span>
                        </div>
                        <div class="metric">
                            <span class="metric-value">${session.toFixed(1)}</span>
                            <span class="metric-unit">kWh</span>
                            <span class="metric-label">${this._t('session')}</span>
                        </div>
                        <div class="metric">
                            <span class="metric-value">${solar.toFixed(0)}</span>
                            <span class="metric-unit">%</span>
                            <span class="metric-label">${this._t('solar')}</span>
                        </div>
                        <div class="metric">
                            <span class="metric-value taper-${taper}">${taper}</span>
                            <span class="metric-label">${this._t('taper')}</span>
                        </div>
                    </div>
                </div>
            `;
        }).join('');

        // Update subtitle with charger count
        const subtitle = this.shadowRoot.querySelector('.card-subtitle');
        if (subtitle) {
            subtitle.textContent = `${this._chargers.length} ${this._t('chargers_configured')}`;
        }
    }

    _renderSkeleton() {
        const T = (typeof semTheme === 'function') ? semTheme() : {};
        const textCol = T.text || '#e0e0e0';
        const textSecCol = T.textSec || '#999';
        const surfaceCol = T.surface || 'rgba(255,255,255,0.06)';
        const surfBorder = T.surfaceBorder || 'rgba(255,255,255,0.12)';

        this.shadowRoot.innerHTML = `
            <style>
                :host { display: block; }
                .card-wrap {
                    padding: 16px;
                    position: relative;
                }
                .card-title {
                    font-size: 1.1em;
                    font-weight: 500;
                    color: ${textCol};
                    margin-bottom: 4px;
                }
                .card-subtitle {
                    font-size: 0.85em;
                    color: ${textSecCol};
                    margin-bottom: 16px;
                }
                .charger-grid {
                    display: grid;
                    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
                    gap: 12px;
                }
                .charger-tile {
                    position: relative;
                    background: ${surfaceCol};
                    border: 1px solid ${surfBorder};
                    border-radius: 12px;
                    padding: 14px;
                    overflow: hidden;
                }
                .charger-glow {
                    position: absolute;
                    top: -20px; right: -20px;
                    width: 80px; height: 80px;
                    border-radius: 50%;
                    background: radial-gradient(circle, rgba(141,200,146,0.4), transparent 70%);
                    pointer-events: none;
                    transition: opacity 0.5s ease;
                }
                .charger-header {
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    margin-bottom: 12px;
                }
                .charger-name {
                    flex: 1;
                    font-weight: 500;
                    color: ${textCol};
                    font-size: 0.95em;
                }
                .charger-status {
                    font-size: 0.8em;
                    font-weight: 500;
                    text-transform: uppercase;
                    letter-spacing: 0.05em;
                }
                .charger-metrics {
                    display: grid;
                    grid-template-columns: repeat(4, 1fr);
                    gap: 8px;
                    text-align: center;
                }
                .metric-value {
                    display: block;
                    font-size: 1.15em;
                    font-weight: 600;
                    color: ${textCol};
                }
                .metric-unit {
                    font-size: 0.75em;
                    color: ${textSecCol};
                    margin-left: 1px;
                }
                .metric-label {
                    display: block;
                    font-size: 0.7em;
                    color: ${textSecCol};
                    margin-top: 2px;
                    text-transform: uppercase;
                    letter-spacing: 0.03em;
                }
                .taper-rising { color: #f06292; }
                .taper-falling { color: #8DC892; }
                .taper-stable { color: ${textSecCol}; }
            </style>
            <div class="card-wrap">
                <div class="card-title">${this._t('Charger Status')}</div>
                <div class="card-subtitle"></div>
                <div class="charger-grid"></div>
            </div>
        `;
    }

    getCardSize() {
        return Math.max(2, this._chargers.length);
    }

    static getStubConfig() {
        return {};
    }
}

customElements.define('sem-charger-status-card', SEMChargerStatusCard);

window.customCards = window.customCards || [];
window.customCards.push({
    type: 'sem-charger-status-card',
    name: 'SEM Charger Status',
    description: 'Multi-charger status display with per-charger tiles',
});

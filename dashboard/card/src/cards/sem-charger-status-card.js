/**
 * SEM Charger Status Card — LitElement migration
 *
 * Dynamically discovers all SEM charger entities and renders
 * per-charger tiles with power, session energy, solar share,
 * and taper status. Fully translatable via semLocalize().
 *
 * Config:
 *   type: custom:sem-charger-status-card
 *   entity_prefix: sensor.sem_   # optional, default
 */

import { SEMLitBase, html, css, nothing } from '../base/sem-lit-base.js';
import { semDefineCard } from '../base/sem-shared.js';

const DEFAULT_PREFIX = 'sensor.sem_';

class SEMChargerStatusCard extends SEMLitBase {
    constructor() {
        super();
        this._chargers = [];
        this._lastStateCount = 0;
    }

    /**
     * Dynamic charger discovery means watchedEntities is instance-level.
     * Override set hass() to re-scan chargers and drive requestUpdate
     * only when relevant charger states actually change.
     */
    set hass(hass) {
        const old = this._hass;
        this._hass = hass;

        // Locale change detection (from base class logic)
        const lang = hass?.language;
        const hasLocalize = typeof semLocalize === 'function';
        let localeChanged = false;
        if (lang !== this._lang || (hasLocalize && !this._localizeReady)) {
            this._lang = lang;
            this._localizeReady = hasLocalize;
            localeChanged = true;
        }


        // Skip while frozen (optimistic update in progress)
        if (this._isFrozen() && !localeChanged) return;

        // Skip transient unavailable states caused by coordinator refresh
        if (this._chargers?.length > 0 && !localeChanged) {
            const prefix = this._config?.entity_prefix || DEFAULT_PREFIX;
            const canary = hass.states[`${prefix}charger_${this._chargers[0]}_power`]?.state;
            if (canary === 'unavailable' || canary === 'unknown') return;
        }

        // Re-discover chargers when entity count changes
        const stateCount = Object.keys(hass.states).length;
        if (stateCount !== this._lastStateCount) {
            this._lastStateCount = stateCount;
            const chargers = [];
            for (const eid of Object.keys(hass.states)) {
                // #356 — same ghost-charger trap as sem-ev-status-card: the
                // per-charger flow sensors (sensor.sem_charger_<id>_flow_*_power)
                // match the regex below. Filter them out before extracting the id.
                if (eid.includes('_flow_')) continue;
                const match = eid.match(/^sensor\.sem_charger_(.+)_power$/);
                if (match) chargers.push(match[1]);
            }
            this._chargers = chargers;
        }

        // Build reactivity key from charger states
        const prefix = this._config?.entity_prefix || DEFAULT_PREFIX;
        const key = this._chargers.map(id => [
            `charger_${id}_power`, `charger_${id}_session_energy`,
            `charger_${id}_session_solar_share`, `charger_${id}_taper_trend`,
        ].map(s => hass.states[`${prefix}${s}`]?.state || '').join(':')).join('|');

        if (key === this._lastKey && !localeChanged) return;
        this._lastKey = key;
        this._scheduleUpdate();
    }

    get hass() {
        return this._hass;
    }

    setConfig(config) {
        super.setConfig(config);
        this._prefix = config.entity_prefix || DEFAULT_PREFIX;
    }

    _val(suffix, fallback = 0) {
        const e = this._hass?.states[`${this._prefix}${suffix}`];
        if (!e || e.state === 'unavailable' || e.state === 'unknown') return fallback;
        return parseFloat(e.state) ?? fallback;
    }

    _valStr(suffix) {
        const e = this._hass?.states[`${this._prefix}${suffix}`];
        return (e && e.state !== 'unavailable' && e.state !== 'unknown') ? e.state : '';
    }

    _chargerName(id) {
        const entity = this._hass?.states[`${this._prefix}charger_${id}_power`];
        let name = id.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
        if (entity?.attributes?.friendly_name) {
            name = entity.attributes.friendly_name
                .replace(/^SEM\s+/i, '')
                .replace(/\s+Power$/i, '');
        }
        return name;
    }

    _renderChargerTile(id) {
        const power = this._val(`charger_${id}_power`);
        const session = this._val(`charger_${id}_session_energy`);
        const solar = this._val(`charger_${id}_session_solar_share`);
        const taperRaw = this._valStr(`charger_${id}_taper_trend`) || 'stable';
        const taper = this._t(taperRaw);
        const name = this._chargerName(id);
        const isCharging = power > 50;
        const statusColor = isCharging ? '#8DC892' : '#888';
        const statusText = isCharging ? this._t('charging') : this._t('idle');
        const glowOpacity = isCharging ? '0.15' : '0';

        return html`
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
                        <span class="metric-value taper-${taperRaw}">${taper}</span>
                        <span class="metric-label">${this._t('taper')}</span>
                    </div>
                </div>
            </div>
        `;
    }

    render() {
        if (!this._config || !this._hass) return nothing;

        return html`
            <div class="card-wrap">
                <div class="card-title">${this._t('charger_status')}</div>
                <div class="card-subtitle">${this._chargers.length} ${this._t('chargers_configured')}</div>
                <div class="charger-grid">
                    ${this._chargers.map(id => this._renderChargerTile(id))}
                </div>
            </div>
        `;
    }

    static get styles() {
        return css`
            :host { display: block; }
            .card-wrap {
                padding: 16px;
                position: relative;
            }
            .card-title {
                font-size: 1.1em;
                font-weight: 500;
                color: var(--primary-text-color, #e0e0e0);
                margin-bottom: 4px;
            }
            .card-subtitle {
                font-size: 0.85em;
                color: var(--secondary-text-color, #999);
                margin-bottom: 16px;
            }
            .charger-grid {
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
                gap: 12px;
            }
            .charger-tile {
                position: relative;
                background: var(--secondary-background-color, rgba(255,255,255,0.06));
                border: 1px solid var(--divider-color, rgba(255,255,255,0.12));
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
                color: var(--primary-text-color, #e0e0e0);
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
                color: var(--primary-text-color, #e0e0e0);
            }
            .metric-unit {
                font-size: 0.8em;
                color: var(--secondary-text-color, #999);
                margin-left: 1px;
            }
            .metric-label {
                display: block;
                font-size: 0.8em;
                color: var(--secondary-text-color, #999);
                margin-top: 2px;
                text-transform: uppercase;
                letter-spacing: 0.03em;
            }
            .taper-rising  { color: #f06292; }
            .taper-falling { color: #8DC892; }
            .taper-stable  { color: var(--secondary-text-color, #999); }
        `;
    }

    getCardSize() {
        return Math.max(2, this._chargers.length);
    }

    static getStubConfig() {
        return {};
    }
}

semDefineCard('sem-charger-status-card', SEMChargerStatusCard, {
    type: 'sem-charger-status-card',
    name: 'SEM Charger Status',
    description: 'Multi-charger status display with per-charger tiles',
    documentationURL:
        'https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-charger-status-card',
});

/**
 * SEM EV Status Card — LitElement migration
 *
 * Animated charging visualization with glow ring, lightning bolt,
 * and key EV metrics. When multiple chargers are configured,
 * renders per-charger sections with intelligence and settings.
 *
 * Config:
 *   type: custom:sem-ev-status-card
 *   entity_prefix: sensor.sem_   # default
 */

import { SEMLitBase, html, css, nothing } from '../base/sem-lit-base.js';
import { semTheme, semFormatPower, semGetCurrency, semDefineCard } from '../base/sem-shared.js';

const DEFAULT_PREFIX = 'sensor.sem_';
const CHARGER_COLORS = ['#8DC892', '#64B5F6'];

class SEMEVStatusCard extends SEMLitBase {
    constructor() {
        super();
        this._chargers = [];
        this._lastStateCount = 0;
    }

    /**
     * Override hass setter: dynamic charger discovery + per-charger key comparison.
     */
    set hass(hass) {
        const old = this._hass;
        this._hass = hass;

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

        // Re-discover chargers when entity count changes
        const stateCount = Object.keys(hass.states).length;
        if (stateCount !== this._lastStateCount) {
            this._lastStateCount = stateCount;
            const chargers = [];
            for (const eid of Object.keys(hass.states)) {
                const match = eid.match(/^sensor\.sem_charger_(.+)_power$/);
                if (match) chargers.push(match[1]);
            }
            this._chargers = chargers;
        }

        const prefix = this._config?.entity_prefix || DEFAULT_PREFIX;

        // Build reactivity key
        let key = [
            'ev_connected', 'ev_charging', 'ev_power', 'calculated_current',
            'session_energy', 'session_solar_share', 'session_cost',
            'daily_ev_energy', 'charging_state',
        ].map(s => {
            const pfx = (s === 'ev_connected' || s === 'ev_charging')
                ? 'binary_sensor.sem_' : prefix;
            return hass.states[`${pfx}${s}`]?.state || '';
        }).join(',');

        // Per-charger reactivity
        if (this._chargers.length >= 1) {
            key += '|' + this._chargers.map(id => [
                `charger_${id}_power`, `charger_${id}_session_energy`,
                `charger_${id}_daily_energy`, `charger_${id}_session_solar_share`,
                `charger_${id}_estimated_soc`, `charger_${id}_nights_until_charge`,
                `charger_${id}_charge_needed`,
            ].map(s => hass.states[`${prefix}${s}`]?.state || '').join(':')).join('|');

            key += '|' + this._chargers.map(id =>
                hass.states[`switch.sem_charger_${id}_night_charging`]?.state || ''
            ).join(':');

            key += '|' + this._chargers.map(id =>
                hass.states[`number.sem_charger_${id}_daily_ev_target`]?.state || ''
            ).join(':');
        }

        key += '|' + this._localizeReady + '|' + this._lang;

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

    _binaryState(suffix) {
        const e = this._hass?.states[`binary_sensor.sem_${suffix}`];
        return e?.state === 'on';
    }

    _val(suffix, fallback = 0) {
        const e = this._hass?.states[`${this._prefix}${suffix}`];
        if (!e || e.state === 'unavailable' || e.state === 'unknown') return fallback;
        return parseFloat(e.state) ?? fallback;
    }

    _valStr(suffix) {
        const e = this._hass?.states[`${this._prefix}${suffix}`];
        return e?.state || '';
    }

    _entityVal(entityId, fallback = 0) {
        const frozen = this._frozenEntities[entityId];
        if (frozen) return frozen.value;
        const e = this._hass?.states[entityId];
        if (!e || e.state === 'unavailable' || e.state === 'unknown') return fallback;
        return parseFloat(e.state) ?? fallback;
    }

    _fmt(val, decimals = 1) {
        if (val == null || isNaN(val)) return '\u2014';
        return val.toFixed(decimals);
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

    _renderSocGauge(soc) {
        const socVal = soc != null ? Math.max(0, Math.min(100, soc)) : 0;
        const socColor = socVal > 60 ? '#8DC892' : socVal > 30 ? '#ff9800' : '#f06292';
        const socFill = Math.max(2, (socVal / 100) * 52);

        return html`
            <svg viewBox="0 0 44 76" width="44" height="76">
                <rect x="14" y="0" width="16" height="5" rx="2" fill="rgba(255,255,255,0.15)"/>
                <rect x="6" y="4" width="32" height="60" rx="4"
                    fill="none" stroke="rgba(255,255,255,0.15)" stroke-width="2"/>
                <rect x="9" y="${7 + (52 - socFill)}" width="26" height="${socFill}" rx="2"
                    fill="${socColor}" opacity="0.7"/>
                <text x="22" y="40" text-anchor="middle"
                    fill="white" font-size="14" font-weight="700"
                    font-family="'Segoe UI','Roboto',sans-serif"
                    opacity="0.95">
                    ${soc != null ? Math.round(soc) + '%' : '\u2014'}
                </text>
            </svg>
        `;
    }

    _renderChargerSection(id, idx) {
        const color = CHARGER_COLORS[idx % CHARGER_COLORS.length];
        const power = this._val(`charger_${id}_power`, 0);
        const session = this._val(`charger_${id}_session_energy`, 0);
        const dailyEnergy = this._val(`charger_${id}_daily_energy`, 0);
        const solar = this._val(`charger_${id}_session_solar_share`, 0);
        // Prefer real vehicle SOC over estimated (#193)
        const vehicleSoc = this._val(`charger_${id}_vehicle_soc`, null);
        const estimatedSoc = this._val(`charger_${id}_estimated_soc`, null);
        const soc = vehicleSoc != null ? vehicleSoc : estimatedSoc;
        const nights = this._entityVal(`number.sem_charger_${id}_nights_until_charge`, null);
        const chargeNeeded = this._valStr(`charger_${id}_charge_needed`);
        const name = this._chargerName(id);

        // Per-charger connected status (#193)
        const perChargerConnected = this._hass?.states[`binary_sensor.sem_charger_${id}_connected`];
        const isConnected = perChargerConnected?.state === 'on';
        const isCharging = power > 50;
        const statusText = isCharging ? this._t('charging') : isConnected ? this._t('connected') : this._t('idle');

        const nightSwitch = this._hass?.states[`switch.sem_charger_${id}_night_charging`];
        const nightOn = nightSwitch?.state === 'on';

        const nightTarget = this._entityVal(`number.sem_charger_${id}_daily_ev_target`, 10);
        const startAmps = this._entityVal(`number.sem_charger_${id}_night_initial_current`, 10);
        const minAmps = this._entityVal(`number.sem_charger_${id}_minimum_current`, 6);

        const needsCharge = chargeNeeded === 'True' || chargeNeeded === 'true';
        const chargeIcon = needsCharge ? 'mdi:battery-alert' : 'mdi:battery-check';
        const chargeColor = needsCharge ? '#f06292' : '#8DC892';
        const chargeText = needsCharge ? this._t('yes') : this._t('no');

        const nightEntityId = `switch.sem_charger_${id}_night_charging`;

        return html`
            <div class="charger-section">
                <div class="charger-header">
                    <div class="charger-dot" style="background:${color}"></div>
                    <span class="charger-name">${name}</span>
                    <span class="charger-status" style="color:${isCharging ? color : ''}">${statusText}</span>
                </div>

                <div class="charger-body">
                    <div class="charger-soc">
                        ${this._renderSocGauge(soc)}
                        <span class="soc-label">SOC</span>
                    </div>

                    <div class="charger-metrics">
                        <div class="cm-row">
                            <span class="cm-label">${this._t('power')}</span>
                            <span class="cm-value" style="color:${isCharging ? color : ''}">${semFormatPower(power)}</span>
                        </div>
                        <div class="cm-row">
                            <span class="cm-label">${this._t('today')}</span>
                            <span class="cm-value">${this._fmt(dailyEnergy, 1)} kWh</span>
                        </div>
                        <div class="cm-row">
                            <span class="cm-label">${this._t('session')}</span>
                            <span class="cm-value">${this._fmt(session, 1)} kWh</span>
                        </div>
                        <div class="cm-row">
                            <span class="cm-label">${this._t('solar_share')}</span>
                            <span class="cm-value" style="color:#ff9800">${this._fmt(solar, 0)}%</span>
                        </div>
                        <div class="cm-row">
                            <span class="cm-label">${this._t('charge_tonight')}</span>
                            <span class="cm-value" style="color:${chargeColor}">
                                <ha-icon icon="${chargeIcon}" style="--mdc-icon-size:14px;vertical-align:middle;color:${chargeColor}"></ha-icon>
                                ${chargeText}
                            </span>
                        </div>
                        ${nights != null ? html`
                            <div class="cm-row">
                                <span class="cm-label">${this._t('nights_until_charge')}</span>
                                <span class="cm-value">${Math.round(nights)}</span>
                            </div>
                        ` : nothing}
                    </div>
                </div>

                <div class="charger-settings">
                    <div class="setting-item">
                        <ha-icon icon="mdi:weather-night" style="--mdc-icon-size:16px;color:${nightOn ? '#7986CB' : '#666'}"></ha-icon>
                        <span class="setting-label">${this._t('night')}</span>
                        <span
                            class="setting-toggle ${nightOn ? 'on' : 'off'}"
                            @click=${(e) => {
                                e.stopPropagation();
                                this._toggleSwitch(nightEntityId);
                            }}
                        >${nightOn ? 'ON' : 'OFF'}</span>
                    </div>
                    <div
                        class="setting-item clickable"
                        @click=${() => {
                            const event = new CustomEvent('hass-more-info', { bubbles: true, composed: true, detail: { entityId: `number.sem_charger_${id}_daily_ev_target` } });
                            this.dispatchEvent(event);
                        }}
                    >
                        <ha-icon icon="mdi:bullseye-arrow" style="--mdc-icon-size:16px;color:#8DC892"></ha-icon>
                        <span class="setting-label">${this._t('night_target')}</span>
                        <span class="setting-value">${this._fmt(nightTarget, 1)} kWh</span>
                    </div>
                    <div
                        class="setting-item clickable"
                        @click=${() => {
                            const event = new CustomEvent('hass-more-info', { bubbles: true, composed: true, detail: { entityId: `number.sem_charger_${id}_night_initial_current` } });
                            this.dispatchEvent(event);
                        }}
                    >
                        <ha-icon icon="mdi:current-ac" style="--mdc-icon-size:16px;color:#64B5F6"></ha-icon>
                        <span class="setting-value">${this._fmt(startAmps, 0)}A</span>
                    </div>
                    <div
                        class="setting-item clickable"
                        @click=${() => {
                            const event = new CustomEvent('hass-more-info', { bubbles: true, composed: true, detail: { entityId: `number.sem_charger_${id}_minimum_current` } });
                            this.dispatchEvent(event);
                        }}
                    >
                        <ha-icon icon="mdi:speedometer-slow" style="--mdc-icon-size:16px;color:#ff9800"></ha-icon>
                        <span class="setting-value">${this._fmt(minAmps, 0)}A</span>
                    </div>
                </div>
            </div>
        `;
    }

    render() {
        if (!this._config || !this._hass) return nothing;

        const connected = this._binaryState('ev_connected');
        const charging = this._binaryState('ev_charging');
        const power = this._val('ev_power', 0);
        const current = this._val('calculated_current', 0);
        const sessionEnergy = this._val('session_energy', 0);
        const solarShare = this._val('session_solar_share', 0);
        const sessionCost = this._val('session_cost', 0);
        const dailyEnergy = this._val('daily_ev_energy', 0);
        const strategy = this._valStr('charging_state');
        const curr = semGetCurrency(this._hass);

        const modeEntity = this._hass?.states['select.sem_ev_charging_mode'];
        const mode = modeEntity?.state || 'auto';
        const modeLabels = {
            auto: this._t('mode_auto'),
            minpv: this._t('mode_minpv'),
            now: this._t('maximum'),
            off: this._t('off'),
        };

        const wrapClass = charging ? 'wrap state-charging'
            : connected ? 'wrap state-connected'
            : 'wrap state-disconnected';

        const statusText = charging ? this._t('charging')
            : connected ? this._t('connected')
            : this._t('disconnected');

        const statusClass = charging ? 'status-value charging'
            : connected ? 'status-value connected'
            : 'status-value disconnected';

        const ringOpacity = charging ? '0.6' : connected ? '0.25' : '0.08';
        const boltOpacity = charging ? '1' : '0';

        return html`
            <svg class="glow-svg">
                <defs>
                    <filter id="ev-glow" x="-50%" y="-50%" width="200%" height="200%">
                        <feGaussianBlur stdDeviation="3" result="blur"/>
                        <feFlood flood-color="#8DC892" flood-opacity="0.3" result="color"/>
                        <feComposite in="color" in2="blur" operator="in" result="glow"/>
                        <feMerge><feMergeNode in="glow"/><feMergeNode in="SourceGraphic"/></feMerge>
                    </filter>
                    <filter id="ev-glow-soft" x="-50%" y="-50%" width="200%" height="200%">
                        <feGaussianBlur stdDeviation="6" result="blur"/>
                        <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
                    </filter>
                </defs>
            </svg>

            <ha-card>
                <div class="${wrapClass}">
                    <div class="hero">
                        <div class="ev-icon-area">
                            <svg viewBox="0 0 100 100">
                                <circle class="glow-ring" cx="50" cy="50" r="42" style="opacity:${ringOpacity}"/>
                                <circle class="ring-bg" cx="50" cy="50" r="42"/>
                                <circle class="ring-fill" cx="50" cy="50" r="39"/>
                                <g class="charger-icon" transform="translate(50,46)">
                                    <rect x="-10" y="-16" width="20" height="26" rx="3"/>
                                    <rect x="-6.5" y="-11" width="13" height="10" rx="2"/>
                                    <path d="M-1.5,-1 L0,4 L1.5,-1"/>
                                    <line x1="0" y1="10" x2="0" y2="15"/>
                                    <circle class="indicator-dot" cx="0" cy="18" r="2" stroke="none"/>
                                </g>
                                <g class="lightning-bolt" transform="translate(50,42)" style="opacity:${boltOpacity}">
                                    <path d="M-2,-8 L-4,1 L-0.5,0 L-1,8 L4,-1 L0.5,0 L2,-8Z" stroke="none"/>
                                </g>
                            </svg>
                        </div>

                        ${this._chargers.length > 1 ? nothing : html`
                            <div class="metrics-col">
                                <div class="metric-row">
                                    <span class="metric-label">${this._t('status')}</span>
                                    <span class="${statusClass}">${statusText}</span>
                                </div>
                                ${charging ? html`
                                    <div class="metric-row power-row">
                                        <span class="metric-label">${this._t('power')}</span>
                                        <span class="metric-value power-value">${semFormatPower(power)}</span>
                                    </div>
                                ` : nothing}
                                <div class="metric-row">
                                    <span class="metric-label">${this._t('current')}</span>
                                    <span class="metric-value">${this._fmt(current, 0)} A</span>
                                </div>
                                <div class="metric-row">
                                    <span class="metric-label">${this._t('session')}</span>
                                    <span class="metric-value">${this._fmt(sessionEnergy, 1)} kWh</span>
                                </div>
                                <div class="metric-row">
                                    <span class="metric-label">${this._t('today')}</span>
                                    <span class="metric-value">${this._fmt(dailyEnergy, 1)} kWh</span>
                                </div>
                                <div class="metric-row">
                                    <span class="metric-label">${this._t('solar_share')}</span>
                                    <span class="metric-value solar-share-value">${this._fmt(solarShare, 0)}%</span>
                                </div>
                                <div class="metric-row">
                                    <span class="metric-label">${this._t('strategy')}</span>
                                    <span class="strategy-value">${strategy ? this._t(strategy) : '\u2014'}</span>
                                </div>
                                <div class="metric-row">
                                    <span class="metric-label">${this._t('mode')}</span>
                                    <span class="metric-value">${modeLabels[mode] || mode}</span>
                                </div>
                            </div>
                        `}
                    </div>

                    ${this._chargers.length > 1 ? nothing : html`
                        <div class="bottom-bar">
                            <div class="chip">
                                <span class="chip-label">${this._t('session_cost')}</span>
                                <span class="cost-chip-value">${this._fmt(sessionCost, 2)} ${curr}</span>
                            </div>
                        </div>
                    `}

                    ${this._chargers.length >= 1 ? html`
                        <div class="charger-sections">
                            ${this._chargers.map((id, idx) => this._renderChargerSection(id, idx))}
                        </div>
                    ` : nothing}
                </div>
            </ha-card>
        `;
    }

    static get styles() {
        return css`
            :host { display: block; }
            .glow-svg { position: absolute; width: 0; height: 0; }

            .wrap {
                padding: 16px 20px;
                position: relative;
                background:
                    radial-gradient(ellipse 70% 60% at 50% 25%, rgba(141,200,146,0.06) 0%, transparent 100%),
                    radial-gradient(circle at 2px 2px, rgba(128,128,128,0.05) 0.7px, transparent 0.7px);
                background-size: 100% 100%, 50px 50px;
                font-family: 'Segoe UI','Roboto',sans-serif;
                color: var(--primary-text-color, #e0e0e0);
                min-height: 108px;
                overflow: hidden;
            }

            /* Hero layout */
            .hero {
                display: flex;
                align-items: center;
                gap: 20px;
            }

            /* Icon area */
            .ev-icon-area {
                position: relative;
                width: 90px; height: 90px;
                flex-shrink: 0;
            }
            .ev-icon-area svg { width: 100%; height: 100%; }

            /* Glow ring */
            .glow-ring {
                fill: none;
                stroke: #8DC892;
                stroke-width: 6;
                filter: url(#ev-glow-soft);
                transition: opacity 0.6s ease;
            }
            .state-charging .glow-ring {
                animation: pulse-ring 2s ease-in-out infinite;
            }
            @keyframes pulse-ring {
                0%, 100% { stroke-width: 6; opacity: 0.5; }
                50% { stroke-width: 10; opacity: 0.7; }
            }

            .ring-bg {
                fill: none;
                stroke: rgba(141,200,146,0.12);
                stroke-width: 3;
            }
            .ring-fill {
                fill: rgba(141,200,146,0.07);
            }

            .charger-icon {
                stroke: #8DC892;
                fill: none;
                stroke-width: 1.8;
                stroke-linecap: round;
                stroke-linejoin: round;
                opacity: 0.7;
                transition: opacity 0.4s ease;
            }
            .state-disconnected .charger-icon { stroke: #666; opacity: 0.35; }
            .state-disconnected .ring-bg { stroke: rgba(100,100,100,0.12); }
            .state-disconnected .ring-fill { fill: rgba(100,100,100,0.05); }
            .state-disconnected .glow-ring { stroke: #666; }

            .lightning-bolt {
                fill: #8DC892;
                transition: opacity 0.4s ease;
                filter: url(#ev-glow);
            }
            .state-charging .lightning-bolt {
                animation: bolt-pulse 1.5s ease-in-out infinite;
            }
            @keyframes bolt-pulse {
                0%, 100% { opacity: 0.9; }
                50% { opacity: 0.5; }
            }

            .indicator-dot {
                fill: #666;
                opacity: 0.3;
                transition: fill 0.4s ease, opacity 0.4s ease;
            }
            .state-connected .indicator-dot { fill: #8DC892; opacity: 0.5; }
            .state-charging .indicator-dot {
                fill: #8DC892; opacity: 1;
                animation: dot-blink 1s ease-in-out infinite;
            }
            @keyframes dot-blink {
                0%, 100% { opacity: 1; }
                50% { opacity: 0.3; }
            }

            /* Metrics column */
            .metrics-col {
                flex: 1; min-width: 0;
                display: flex;
                flex-direction: column;
                gap: 2px;
            }
            .metric-row {
                display: flex;
                justify-content: space-between;
                align-items: baseline;
                padding: 1.5px 0;
            }
            .metric-label {
                font-size: 11px;
                color: var(--secondary-text-color, #999);
                font-weight: 500;
            }
            .metric-value {
                font-size: 12px;
                font-weight: 600;
                font-variant-numeric: tabular-nums;
                color: var(--primary-text-color, #e0e0e0);
            }

            .status-value { font-size: 13px; font-weight: 700; font-variant-numeric: tabular-nums; }
            .status-value.charging { color: #8DC892; text-shadow: 0 0 8px rgba(141,200,146,0.4); }
            .status-value.connected { color: #8DC892; }
            .status-value.disconnected { color: var(--secondary-text-color, #999); }

            .power-row .metric-value {
                font-size: 16px;
                font-weight: 700;
                color: #8DC892;
                text-shadow: 0 0 6px rgba(141,200,146,0.3);
            }

            .solar-share-value { color: #ff9800 !important; }

            .strategy-value {
                font-size: 10px;
                color: #8DC892; opacity: 0.7;
                font-weight: 500;
                white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
            }

            /* Bottom bar */
            .bottom-bar {
                display: flex;
                align-items: center;
                gap: 8px;
                margin-top: 10px;
                flex-wrap: wrap;
            }
            .chip {
                display: inline-flex; align-items: center; gap: 4px;
                background: var(--secondary-background-color, rgba(255,255,255,0.06));
                border: 1px solid var(--divider-color, rgba(255,255,255,0.12));
                border-radius: 12px;
                padding: 3px 10px;
                font-size: 11px; font-weight: 500;
                color: var(--primary-text-color, #e0e0e0);
                font-variant-numeric: tabular-nums;
            }
            .chip-label { color: var(--secondary-text-color, #888); }
            .cost-chip-value { color: #f06292; }

            /* Per-charger sections */
            .charger-sections {
                margin-top: 16px;
                display: flex;
                flex-direction: column;
                gap: 12px;
            }
            .charger-section {
                background: var(--secondary-background-color, rgba(255,255,255,0.06));
                border: 1px solid var(--divider-color, rgba(255,255,255,0.12));
                border-radius: 12px;
                padding: 12px 14px;
            }
            .charger-header {
                display: flex; align-items: center; gap: 8px;
                margin-bottom: 10px;
            }
            .charger-dot {
                width: 8px; height: 8px;
                border-radius: 50%;
                flex-shrink: 0;
            }
            .charger-name {
                flex: 1; font-weight: 600; font-size: 0.95em;
                color: var(--primary-text-color, #e0e0e0);
            }
            .charger-status {
                font-size: 0.75em; font-weight: 500;
                text-transform: uppercase; letter-spacing: 0.05em;
                color: var(--secondary-text-color, #999);
            }
            .charger-body {
                display: flex; align-items: center; gap: 12px;
            }
            .charger-soc {
                flex-shrink: 0; width: 44px; text-align: center;
            }
            .soc-label {
                display: block;
                font-size: 9px; color: var(--secondary-text-color, #999);
                margin-top: 2px;
                text-transform: uppercase; letter-spacing: 0.05em;
            }
            .charger-metrics {
                flex: 1;
                display: flex; flex-direction: column; gap: 2px;
            }
            .cm-row {
                display: flex; justify-content: space-between; align-items: baseline;
                padding: 1px 0;
            }
            .cm-label { font-size: 10px; color: var(--secondary-text-color, #999); font-weight: 500; }
            .cm-value {
                font-size: 11px; font-weight: 600;
                color: var(--primary-text-color, #e0e0e0);
                font-variant-numeric: tabular-nums;
            }
            .charger-settings {
                display: flex; align-items: center; gap: 6px;
                margin-top: 8px; padding-top: 8px;
                border-top: 1px solid var(--divider-color, rgba(255,255,255,0.12));
                flex-wrap: wrap;
            }
            .setting-item {
                display: flex; align-items: center; gap: 3px;
                font-size: 10px; color: var(--secondary-text-color, #999);
            }
            .setting-item.clickable { cursor: pointer; }
            .setting-label { font-size: 10px; color: var(--secondary-text-color, #999); }
            .setting-value { font-size: 11px; font-weight: 600; color: var(--primary-text-color, #e0e0e0); }
            .setting-toggle {
                font-size: 10px; font-weight: 700;
                padding: 1px 6px;
                border-radius: 6px;
                cursor: pointer;
                user-select: none;
                transition: background 0.2s, color 0.2s;
            }
            .setting-toggle.on  { background: rgba(121,134,203,0.25); color: #7986CB; }
            .setting-toggle.off { background: rgba(100,100,100,0.15); color: #666; }
            .setting-toggle:hover { opacity: 0.8; }

            @media (max-width: 400px) {
                .hero { flex-direction: column; align-items: center; text-align: center; }
                .ev-icon-area { width: 80px; height: 80px; }
                .metric-row { justify-content: center; gap: 8px; }
                .metrics-col { align-items: center; }
            }
        `;
    }

    getCardSize() { return this._chargers.length >= 1 ? 3 + this._chargers.length * 2 : 3; }

    static getStubConfig() { return {}; }
}

semDefineCard('sem-ev-status-card', SEMEVStatusCard, {
    type: 'sem-ev-status-card',
    name: 'SEM EV Status',
    description: 'Lumina-styled EV charging hero card with per-charger intelligence and settings',
});

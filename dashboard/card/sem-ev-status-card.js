(window.semReady || (fn => { window._semReadyQueue = window._semReadyQueue || []; window._semReadyQueue.push(fn); }))(function() {
/**
 * SEM EV Status Card — Lumina-styled EV charging hero card
 *
 * Animated charging visualization with glow ring, lightning bolt,
 * and key EV metrics. When multiple chargers are configured,
 * renders per-charger sections with intelligence and settings (#193).
 *
 * Config:
 *   type: custom:sem-ev-status-card
 *   entity_prefix: sensor.sem_   # default
 */

const CHARGER_COLORS = ['#8DC892', '#64B5F6'];

class SEMEVStatusCard extends SEMBaseCard {
    constructor() {
        super();
        this._rendered = false;
        this._chargers = [];
        this._lastStateCount = 0;
    }

    setConfig(config) {
        this.config = config;
        this._prefix = config.entity_prefix || 'sensor.sem_';
    }

    set hass(hass) {
        const localeChanged = this._checkLocaleChange(hass);

        // Discover chargers (re-scan when entity count changes)
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

        // Build reactivity key from global + per-charger states
        let key = [
            'ev_connected', 'ev_charging', 'ev_power', 'calculated_current',
            'session_energy', 'session_solar_share', 'session_cost',
            'daily_ev_energy', 'charging_state'
        ].map(s => {
            const pfx = s.startsWith('ev_connected') || s.startsWith('ev_charging')
                ? 'binary_sensor.sem_' : this._prefix;
            return this._hass?.states[`${pfx}${s}`]?.state || '';
        }).join(',');

        // Per-charger reactivity
        if (this._chargers.length >= 1) {
            key += '|' + this._chargers.map(id => [
                `charger_${id}_power`, `charger_${id}_session_energy`,
                `charger_${id}_daily_energy`, `charger_${id}_session_solar_share`,
                `charger_${id}_estimated_soc`, `charger_${id}_nights_until_charge`,
                `charger_${id}_charge_needed`,
            ].map(s => hass.states[`${this._prefix}${s}`]?.state || '').join(':')).join('|');

            // Night charging switches
            key += '|' + this._chargers.map(id =>
                hass.states[`switch.sem_charger_${id}_night_charging`]?.state || ''
            ).join(':');

            // Night target numbers
            key += '|' + this._chargers.map(id =>
                hass.states[`number.sem_charger_${id}_daily_ev_target`]?.state || ''
            ).join(':');
        }

        key += '|' + this._localizeReady + '|' + this._lang;
        if (key === this._lastKey) return;
        this._lastKey = key;
        if (localeChanged) {
            this._rendered = false;
        }
        this._update();
    }

    _binaryState(suffix) {
        const e = this._hass?.states[`binary_sensor.sem_${suffix}`];
        return e?.state === 'on';
    }

    _state(suffix, fallback) {
        const e = this._hass?.states[`${this._prefix}${suffix}`];
        if (!e || e.state === 'unavailable' || e.state === 'unknown') return fallback;
        return parseFloat(e.state) || fallback;
    }

    _stateStr(suffix) {
        const e = this._hass?.states[`${this._prefix}${suffix}`];
        return e?.state || '';
    }

    _entityState(entityId, fallback) {
        const e = this._hass?.states[entityId];
        if (!e || e.state === 'unavailable' || e.state === 'unknown') return fallback;
        return parseFloat(e.state) ?? fallback;
    }

    _fmt(val, decimals = 1) {
        if (val == null || isNaN(val)) return '\u2014';
        return val.toFixed(decimals);
    }

    _fmtPower(w) { return semFormatPower(w); }

    _update() {
        if (!this._hass) return;

        const connected = this._binaryState('ev_connected');
        const charging = this._binaryState('ev_charging');
        const power = this._state('ev_power', 0);
        const current = this._state('calculated_current', 0);
        const sessionEnergy = this._state('session_energy', 0);
        const solarShare = this._state('session_solar_share', 0);
        const sessionCost = this._state('session_cost', 0);
        const dailyEnergy = this._state('daily_ev_energy', 0);
        const strategy = this._stateStr('charging_state');

        if (!this._rendered) {
            this._renderSkeleton();
            this._rendered = true;
        }

        const $ = (sel) => this.shadowRoot.querySelector(sel);
        const setVal = (sel, text) => { const el = $(sel); if (el) el.textContent = text; };

        // Determine visual state
        const wrap = $('.wrap');
        if (wrap) {
            wrap.classList.toggle('state-charging', charging);
            wrap.classList.toggle('state-connected', connected && !charging);
            wrap.classList.toggle('state-disconnected', !connected);
        }

        // Status text
        const statusEl = $('.status-value');
        if (statusEl) {
            if (charging) {
                statusEl.textContent = this._t('charging');
                statusEl.className = 'status-value charging';
            } else if (connected) {
                statusEl.textContent = this._t('connected');
                statusEl.className = 'status-value connected';
            } else {
                statusEl.textContent = this._t('disconnected');
                statusEl.className = 'status-value disconnected';
            }
        }

        // Power (only shown when charging)
        const powerRow = $('.power-row');
        if (powerRow) powerRow.style.display = charging ? 'flex' : 'none';
        setVal('.power-value', this._fmtPower(power));

        // Current
        setVal('.current-value', this._fmt(current, 0) + ' A');

        // Session energy
        setVal('.session-value', this._fmt(sessionEnergy, 1) + ' kWh');

        // Daily energy
        setVal('.daily-value', this._fmt(dailyEnergy, 1) + ' kWh');

        // Solar share
        setVal('.solar-share-value', this._fmt(solarShare, 0) + '%');

        // Strategy
        const strategyEl = $('.strategy-value');
        if (strategyEl) {
            const text = strategy || '\u2014';
            strategyEl.textContent = text.length > 30 ? text.substring(0, 28) + '\u2026' : text;
        }

        // Charging mode (from select entity)
        const modeEntity = this._hass?.states['select.sem_ev_charging_mode'];
        const mode = modeEntity?.state || 'auto';
        const modeLabels = { auto: this._t('mode_auto'), minpv: this._t('mode_minpv'), now: this._t('maximum'), off: this._t('off') };
        setVal('.mode-value', modeLabels[mode] || mode);

        // Bottom chips
        setVal('.cost-chip-value', this._fmt(sessionCost, 2) + ' ' + (window.semGetCurrency?.(this._hass) || 'EUR'));

        // Translate labels
        const setLabel = (sel, text) => { const el = $(sel); if (el) el.textContent = text; };
        setLabel('.lbl-status', this._t('status'));
        setLabel('.lbl-power', this._t('power'));
        setLabel('.lbl-current', this._t('current'));
        setLabel('.lbl-session', this._t('session'));
        setLabel('.lbl-today', this._t('today'));
        setLabel('.lbl-solar-share', this._t('solar_share'));
        setLabel('.lbl-strategy', this._t('strategy'));
        setLabel('.lbl-mode', this._t('mode'));
        setLabel('.lbl-session-cost', this._t('session_cost'));

        // Glow ring animation state
        const ring = $('.glow-ring');
        if (ring) {
            ring.style.opacity = charging ? '0.6' : (connected ? '0.25' : '0.08');
        }

        // Lightning bolt visibility
        const bolt = $('.lightning-bolt');
        if (bolt) bolt.style.opacity = charging ? '1' : '0';

        // Multi-charger sections (#193)
        if (this._chargers.length >= 1) {
            this._updateChargerSections();
        }
    }

    _updateChargerSections() {
        const container = this.shadowRoot.querySelector('.charger-sections');
        if (!container) return;

        container.innerHTML = this._chargers.map((id, idx) => {
            const color = CHARGER_COLORS[idx % CHARGER_COLORS.length];
            const power = this._state(`charger_${id}_power`, 0);
            const session = this._state(`charger_${id}_session_energy`, 0);
            const dailyEnergy = this._state(`charger_${id}_daily_energy`, 0);
            const solar = this._state(`charger_${id}_session_solar_share`, 0);
            const soc = this._state(`charger_${id}_estimated_soc`, null);
            const nights = this._state(`charger_${id}_nights_until_charge`, null);
            const chargeNeeded = this._stateStr(`charger_${id}_charge_needed`);
            const taperTrend = this._stateStr(`charger_${id}_taper_trend`) || 'stable';

            // Derive charger name from friendly_name
            const entity = this._hass?.states[`${this._prefix}charger_${id}_power`];
            let name = id.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
            if (entity?.attributes?.friendly_name) {
                name = entity.attributes.friendly_name
                    .replace(/^SEM\s+/i, '')
                    .replace(/\s+Power$/i, '');
            }

            const isCharging = power > 50;
            const statusText = isCharging ? this._t('charging') : this._t('idle');

            // Night charging switch state
            const nightSwitch = this._hass?.states[`switch.sem_charger_${id}_night_charging`];
            const nightOn = nightSwitch?.state === 'on';

            // Night target number
            const nightTarget = this._entityState(`number.sem_charger_${id}_daily_ev_target`, 10);
            const startAmps = this._entityState(`number.sem_charger_${id}_night_initial_current`, 10);
            const minAmps = this._entityState(`number.sem_charger_${id}_minimum_current`, 6);

            // Charge needed indicator
            const needsCharge = chargeNeeded === 'True' || chargeNeeded === 'true';
            const chargeIcon = needsCharge ? 'mdi:battery-alert' : 'mdi:battery-check';
            const chargeColor = needsCharge ? '#f06292' : '#8DC892';
            const chargeText = needsCharge ? this._t('yes') : this._t('no');

            // SOC battery gauge (0-100%)
            const socVal = soc != null ? Math.max(0, Math.min(100, soc)) : 0;
            const socColor = socVal > 60 ? '#8DC892' : socVal > 30 ? '#ff9800' : '#f06292';
            const socFill = Math.max(2, (socVal / 100) * 52); // fill height in SVG units

            return `
                <div class="charger-section">
                    <div class="charger-header">
                        <div class="charger-dot" style="background:${color}"></div>
                        <span class="charger-name">${name}</span>
                        <span class="charger-status" style="color:${isCharging ? color : ''}">${statusText}</span>
                    </div>

                    <div class="charger-body">
                        <!-- Left: Battery SOC gauge -->
                        <div class="charger-soc">
                            <svg viewBox="0 0 44 76">
                                <!-- Battery terminal -->
                                <rect x="14" y="0" width="16" height="5" rx="2"
                                    fill="rgba(255,255,255,0.15)"/>
                                <!-- Battery body outline -->
                                <rect x="6" y="4" width="32" height="60" rx="4"
                                    fill="none" stroke="rgba(255,255,255,0.15)" stroke-width="2"/>
                                <!-- Fill level -->
                                <rect x="9" y="${7 + (52 - socFill)}" width="26" height="${socFill}" rx="2"
                                    fill="${socColor}" opacity="0.7"/>
                                <!-- Percentage text -->
                                <text x="22" y="40" text-anchor="middle"
                                    fill="white" font-size="14" font-weight="700"
                                    font-family="'Segoe UI','Roboto',sans-serif"
                                    opacity="0.95">
                                    ${soc != null ? Math.round(soc) + '%' : '\u2014'}
                                </text>
                            </svg>
                            <span class="soc-label">SOC</span>
                        </div>

                        <!-- Right: metrics -->
                        <div class="charger-metrics">
                            <div class="cm-row">
                                <span class="cm-label">${this._t('power')}</span>
                                <span class="cm-value" style="color:${isCharging ? color : ''}">${this._fmtPower(power)}</span>
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
                            ${nights != null ? `
                            <div class="cm-row">
                                <span class="cm-label">${this._t('nights_until_charge')}</span>
                                <span class="cm-value">${Math.round(nights)}</span>
                            </div>` : ''}
                        </div>
                    </div>

                    <!-- Settings row -->
                    <div class="charger-settings">
                        <div class="setting-item" data-entity="switch.sem_charger_${id}_night_charging">
                            <ha-icon icon="mdi:weather-night" style="--mdc-icon-size:16px;color:${nightOn ? '#7986CB' : '#666'}"></ha-icon>
                            <span class="setting-label">${this._t('night')}</span>
                            <span class="setting-toggle ${nightOn ? 'on' : 'off'}"
                                  data-switch="switch.sem_charger_${id}_night_charging">
                                ${nightOn ? 'ON' : 'OFF'}
                            </span>
                        </div>
                        <div class="setting-item" data-entity="number.sem_charger_${id}_daily_ev_target">
                            <ha-icon icon="mdi:bullseye-arrow" style="--mdc-icon-size:16px;color:#8DC892"></ha-icon>
                            <span class="setting-label">${this._t('night_target')}</span>
                            <span class="setting-value">${this._fmt(nightTarget, 1)} kWh</span>
                        </div>
                        <div class="setting-item" data-entity="number.sem_charger_${id}_night_initial_current">
                            <ha-icon icon="mdi:current-ac" style="--mdc-icon-size:16px;color:#64B5F6"></ha-icon>
                            <span class="setting-value">${this._fmt(startAmps, 0)}A</span>
                        </div>
                        <div class="setting-item" data-entity="number.sem_charger_${id}_minimum_current">
                            <ha-icon icon="mdi:speedometer-slow" style="--mdc-icon-size:16px;color:#ff9800"></ha-icon>
                            <span class="setting-value">${this._fmt(minAmps, 0)}A</span>
                        </div>
                    </div>
                </div>
            `;
        }).join('');

        // Wire up click handlers for settings and switches
        container.querySelectorAll('.setting-toggle').forEach(el => {
            el.onclick = (e) => {
                e.stopPropagation();
                const entityId = el.dataset.switch;
                if (entityId && this._hass) {
                    const isOn = this._hass.states[entityId]?.state === 'on';
                    this._hass.callService('switch', isOn ? 'turn_off' : 'turn_on', {
                        entity_id: entityId,
                    });
                }
            };
        });

        container.querySelectorAll('.setting-item[data-entity]').forEach(el => {
            const entityId = el.dataset.entity;
            if (entityId && !entityId.startsWith('switch.')) {
                el.onclick = () => {
                    const event = new Event('hass-more-info', { bubbles: true, composed: true });
                    event.detail = { entityId };
                    this.dispatchEvent(event);
                };
                el.style.cursor = 'pointer';
            }
        });
    }

    _renderSkeleton() {
        const T = (typeof semTheme === 'function') ? semTheme() : {};
        const textCol    = T.text        || '#e0e0e0';
        const textSecCol = T.textSec     || '#999';
        const textTertCol = T.textTertiary || '#888';
        const surfaceCol = T.surface     || 'rgba(255,255,255,0.06)';
        const surfBorder = T.surfaceBorder || 'rgba(255,255,255,0.12)';
        const dotCol     = T.dotColor    || 'rgba(128,128,128,0.05)';
        const disabledCol = T.textDisabled || '#666';

        const multiChargerCSS = this._chargers.length >= 1 ? `
                /* Per-charger sections (#193) */
                .charger-sections {
                    margin-top: 16px;
                    display: flex;
                    flex-direction: column;
                    gap: 12px;
                }
                .charger-section {
                    background: ${surfaceCol};
                    border: 1px solid ${surfBorder};
                    border-radius: 12px;
                    padding: 12px 14px;
                }
                .charger-header {
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    margin-bottom: 10px;
                }
                .charger-dot {
                    width: 8px; height: 8px;
                    border-radius: 50%;
                    flex-shrink: 0;
                }
                .charger-name {
                    flex: 1;
                    font-weight: 600;
                    font-size: 0.95em;
                    color: ${textCol};
                }
                .charger-status {
                    font-size: 0.75em;
                    font-weight: 500;
                    text-transform: uppercase;
                    letter-spacing: 0.05em;
                    color: ${textSecCol};
                }
                .charger-body {
                    display: flex;
                    align-items: center;
                    gap: 12px;
                }
                .charger-soc {
                    flex-shrink: 0;
                    width: 44px;
                    text-align: center;
                }
                .charger-soc svg { width: 44px; height: 76px; }
                .soc-label {
                    display: block;
                    font-size: 9px;
                    color: ${textSecCol};
                    margin-top: 2px;
                    text-transform: uppercase;
                    letter-spacing: 0.05em;
                }
                .charger-metrics {
                    flex: 1;
                    display: flex;
                    flex-direction: column;
                    gap: 2px;
                }
                .cm-row {
                    display: flex;
                    justify-content: space-between;
                    align-items: baseline;
                    padding: 1px 0;
                }
                .cm-label {
                    font-size: 10px;
                    color: ${textSecCol};
                    font-weight: 500;
                }
                .cm-value {
                    font-size: 11px;
                    font-weight: 600;
                    color: ${textCol};
                    font-variant-numeric: tabular-nums;
                }
                .charger-settings {
                    display: flex;
                    align-items: center;
                    gap: 6px;
                    margin-top: 8px;
                    padding-top: 8px;
                    border-top: 1px solid ${surfBorder};
                    flex-wrap: wrap;
                }
                .setting-item {
                    display: flex;
                    align-items: center;
                    gap: 3px;
                    font-size: 10px;
                    color: ${textSecCol};
                }
                .setting-label {
                    font-size: 10px;
                    color: ${textSecCol};
                }
                .setting-value {
                    font-size: 11px;
                    font-weight: 600;
                    color: ${textCol};
                }
                .setting-toggle {
                    font-size: 10px;
                    font-weight: 700;
                    padding: 1px 6px;
                    border-radius: 6px;
                    cursor: pointer;
                    user-select: none;
                    transition: background 0.2s, color 0.2s;
                }
                .setting-toggle.on {
                    background: rgba(121,134,203,0.25);
                    color: #7986CB;
                }
                .setting-toggle.off {
                    background: rgba(100,100,100,0.15);
                    color: ${disabledCol};
                }
                .setting-toggle:hover {
                    opacity: 0.8;
                }
        ` : '';

        this.shadowRoot.innerHTML = `
            <style>
                :host { display: block; }
                .wrap {
                    padding: 16px 20px;
                    position: relative;
                    background:
                        radial-gradient(ellipse 70% 60% at 50% 30%, rgba(141,200,146,0.06) 0%, transparent 100%),
                        radial-gradient(circle at 2px 2px, ${dotCol} 0.7px, transparent 0.7px);
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    color: var(--primary-text-color, ${textCol});
                    min-height: 108px;
                    overflow: hidden;
                }

                /* SVG glow filter */
                .glow-svg { position: absolute; width: 0; height: 0; }

                /* Hero layout */
                .hero {
                    display: flex;
                    align-items: center;
                    gap: 20px;
                }

                /* Icon area */
                .ev-icon-area {
                    position: relative;
                    width: 90px;
                    height: 90px;
                    flex-shrink: 0;
                }
                .ev-icon-area svg {
                    width: 100%;
                    height: 100%;
                }

                /* Glow ring */
                .glow-ring {
                    fill: none;
                    stroke: #8DC892;
                    stroke-width: 6;
                    opacity: 0.08;
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

                /* Charger icon inside circle */
                .charger-icon {
                    stroke: #8DC892;
                    fill: none;
                    stroke-width: 1.8;
                    stroke-linecap: round;
                    stroke-linejoin: round;
                    opacity: 0.7;
                    transition: opacity 0.4s ease;
                }
                .state-disconnected .charger-icon {
                    stroke: ${disabledCol};
                    opacity: 0.35;
                }
                .state-disconnected .ring-bg { stroke: rgba(100,100,100,0.12); }
                .state-disconnected .ring-fill { fill: rgba(100,100,100,0.05); }
                .state-disconnected .glow-ring { stroke: ${disabledCol}; }

                /* Lightning bolt */
                .lightning-bolt {
                    fill: #8DC892;
                    opacity: 0;
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

                /* Indicator dot */
                .indicator-dot {
                    fill: ${disabledCol};
                    opacity: 0.3;
                    transition: fill 0.4s ease, opacity 0.4s ease;
                }
                .state-connected .indicator-dot { fill: #8DC892; opacity: 0.5; }
                .state-charging .indicator-dot {
                    fill: #8DC892;
                    opacity: 1;
                    animation: dot-blink 1s ease-in-out infinite;
                }
                @keyframes dot-blink {
                    0%, 100% { opacity: 1; }
                    50% { opacity: 0.3; }
                }

                /* Metrics column */
                .metrics-col {
                    flex: 1;
                    min-width: 0;
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
                    color: var(--secondary-text-color, ${textSecCol});
                    font-weight: 500;
                }
                .metric-value {
                    font-size: 12px;
                    font-weight: 600;
                    font-variant-numeric: tabular-nums;
                    color: var(--primary-text-color, ${textCol});
                }

                /* Status text colors */
                .status-value {
                    font-size: 13px;
                    font-weight: 700;
                    font-variant-numeric: tabular-nums;
                }
                .status-value.charging { color: #8DC892; text-shadow: 0 0 8px rgba(141,200,146,0.4); }
                .status-value.connected { color: #8DC892; }
                .status-value.disconnected { color: var(--secondary-text-color, ${textSecCol}); }

                /* Power value (large) */
                .power-row .metric-value {
                    font-size: 16px;
                    font-weight: 700;
                    color: #8DC892;
                    text-shadow: 0 0 6px rgba(141,200,146,0.3);
                }
                .power-row .metric-label {
                    font-size: 12px;
                }

                /* Solar share color */
                .solar-share-value { color: #ff9800 !important; }

                /* Strategy text */
                .strategy-value {
                    font-size: 10px;
                    color: #8DC892;
                    opacity: 0.7;
                    font-weight: 500;
                    white-space: nowrap;
                    overflow: hidden;
                    text-overflow: ellipsis;
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
                    display: inline-flex;
                    align-items: center;
                    gap: 4px;
                    background: var(--secondary-background-color, ${surfaceCol});
                    border: 1px solid var(--divider-color, ${surfBorder});
                    border-radius: 12px;
                    padding: 3px 10px;
                    font-size: 11px;
                    font-weight: 500;
                    color: var(--primary-text-color, ${textCol});
                    font-variant-numeric: tabular-nums;
                }
                .chip-label { color: var(--secondary-text-color, ${textTertCol}); }
                .chip-value { color: var(--primary-text-color, ${textCol}); }
                .cost-chip-value { color: #f06292; }

                /* Responsive: stack on narrow */
                @media (max-width: 400px) {
                    .hero {
                        flex-direction: column;
                        align-items: center;
                        text-align: center;
                    }
                    .ev-icon-area {
                        width: 80px;
                        height: 80px;
                    }
                    .metric-row {
                        justify-content: center;
                        gap: 8px;
                    }
                    .metrics-col {
                        align-items: center;
                    }
                }

                ${multiChargerCSS}
            </style>

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
                <div class="wrap">
                    <div class="hero">
                        <div class="ev-icon-area">
                            <svg viewBox="0 0 100 100">
                                <!-- Glow ring -->
                                <circle class="glow-ring" cx="50" cy="50" r="42"/>
                                <!-- Background ring -->
                                <circle class="ring-bg" cx="50" cy="50" r="42"/>
                                <circle class="ring-fill" cx="50" cy="50" r="39"/>

                                <!-- Charger plug icon -->
                                <g class="charger-icon" transform="translate(50,46)">
                                    <rect x="-10" y="-16" width="20" height="26" rx="3"/>
                                    <rect x="-6.5" y="-11" width="13" height="10" rx="2"/>
                                    <path d="M-1.5,-1 L0,4 L1.5,-1"/>
                                    <line x1="0" y1="10" x2="0" y2="15"/>
                                    <circle class="indicator-dot" cx="0" cy="18" r="2" stroke="none"/>
                                </g>

                                <!-- Lightning bolt (charging animation) -->
                                <g class="lightning-bolt" transform="translate(50,42)">
                                    <path d="M-2,-8 L-4,1 L-0.5,0 L-1,8 L4,-1 L0.5,0 L2,-8Z"
                                          stroke="none"/>
                                </g>
                            </svg>
                        </div>

                        <div class="metrics-col">
                            <div class="metric-row">
                                <span class="metric-label lbl-status">${this._t('status')}</span>
                                <span class="status-value disconnected">${this._t('disconnected')}</span>
                            </div>
                            <div class="metric-row power-row" style="display:none">
                                <span class="metric-label lbl-power">${this._t('power')}</span>
                                <span class="metric-value power-value">\u2014 W</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label lbl-current">${this._t('current')}</span>
                                <span class="metric-value current-value">\u2014 A</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label lbl-session">${this._t('session')}</span>
                                <span class="metric-value session-value">\u2014 kWh</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label lbl-today">${this._t('today')}</span>
                                <span class="metric-value daily-value">\u2014 kWh</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label lbl-solar-share">${this._t('solar_share')}</span>
                                <span class="metric-value solar-share-value">\u2014%</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label lbl-strategy">${this._t('strategy')}</span>
                                <span class="strategy-value">\u2014</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label lbl-mode">${this._t('mode')}</span>
                                <span class="mode-value">\u2014</span>
                            </div>
                        </div>
                    </div>

                    <div class="bottom-bar">
                        <div class="chip">
                            <span class="chip-label lbl-session-cost">${this._t('session_cost')}</span>
                            <span class="cost-chip-value">\u2014</span>
                        </div>
                    </div>

                    ${this._chargers.length >= 1 ? '<div class="charger-sections"></div>' : ''}
                </div>
            </ha-card>
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

});

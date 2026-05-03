/**
 * SEM EV Status Card — Lumina-styled EV charging hero card
 *
 * Animated charging visualization with glow ring, lightning bolt,
 * and key EV metrics. Replaces mushroom-template-card on EV tab.
 *
 * Config:
 *   type: custom:sem-ev-status-card
 *   entity_prefix: sensor.sem_   # default
 */

class SEMEVStatusCard extends HTMLElement {
    constructor() {
        super();
        this.attachShadow({ mode: 'open' });
        this._rendered = false;
    }

    setConfig(config) {
        this.config = config;
        this._prefix = config.entity_prefix || 'sensor.sem_';
    }

    set hass(hass) {
        this._hass = hass;
        const key = [
            'ev_connected', 'ev_charging', 'ev_power', 'calculated_current',
            'session_energy', 'session_solar_share', 'session_cost',
            'daily_ev_energy', 'charging_state'
        ].map(s => {
            const pfx = s.startsWith('ev_connected') || s.startsWith('ev_charging')
                ? 'binary_sensor.sem_' : this._prefix;
            return this._hass?.states[`${pfx}${s}`]?.state || '';
        }).join(',');
        if (key === this._lastKey) return;
        this._lastKey = key;
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

    _fmt(val, decimals = 1) {
        if (val == null || isNaN(val)) return '\u2014';
        return val.toFixed(decimals);
    }

    _fmtPower(w) {
        if (w == null || isNaN(w)) return '\u2014 W';
        if (Math.abs(w) >= 1000) return (w / 1000).toFixed(1) + ' kW';
        return Math.round(w) + ' W';
    }

    _t(key) {
        const lang = this._hass?.language;
        return (typeof semLocalize === 'function') ? semLocalize(key, lang) : key;
    }

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
        const modeLabels = { auto: 'Auto', minpv: 'Min+PV', now: 'Maximum', off: 'Off' };
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
                    color: ${textCol};
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
                    color: ${textSecCol};
                    font-weight: 500;
                }
                .metric-value {
                    font-size: 12px;
                    font-weight: 600;
                    font-variant-numeric: tabular-nums;
                    color: ${textCol};
                }

                /* Status text colors */
                .status-value {
                    font-size: 13px;
                    font-weight: 700;
                    font-variant-numeric: tabular-nums;
                }
                .status-value.charging { color: #8DC892; text-shadow: 0 0 8px rgba(141,200,146,0.4); }
                .status-value.connected { color: #8DC892; }
                .status-value.disconnected { color: ${textSecCol}; }

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
                    background: ${surfaceCol};
                    border: 1px solid ${surfBorder};
                    border-radius: 12px;
                    padding: 3px 10px;
                    font-size: 11px;
                    font-weight: 500;
                    color: ${textCol};
                    font-variant-numeric: tabular-nums;
                }
                .chip-label { color: ${textTertCol}; }
                .chip-value { color: ${textCol}; }
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
                                <span class="metric-label lbl-status">Status</span>
                                <span class="status-value disconnected">Disconnected</span>
                            </div>
                            <div class="metric-row power-row" style="display:none">
                                <span class="metric-label lbl-power">Power</span>
                                <span class="metric-value power-value">\u2014 W</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label lbl-current">Current</span>
                                <span class="metric-value current-value">\u2014 A</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label lbl-session">Session</span>
                                <span class="metric-value session-value">\u2014 kWh</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label lbl-today">Today</span>
                                <span class="metric-value daily-value">\u2014 kWh</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label lbl-solar-share">Solar share</span>
                                <span class="metric-value solar-share-value">\u2014%</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label lbl-strategy">Strategy</span>
                                <span class="strategy-value">\u2014</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label lbl-mode">Mode</span>
                                <span class="mode-value">\u2014</span>
                            </div>
                        </div>
                    </div>

                    <div class="bottom-bar">
                        <div class="chip">
                            <span class="chip-label lbl-session-cost">Session cost</span>
                            <span class="cost-chip-value">\u2014</span>
                        </div>
                    </div>
                </div>
            </ha-card>
        `;
    }

    getCardSize() { return 3; }

    static getStubConfig() { return {}; }
}

customElements.define('sem-ev-status-card', SEMEVStatusCard);

window.customCards = window.customCards || [];
window.customCards.push({
    type: 'sem-ev-status-card',
    name: 'SEM EV Status',
    description: 'Lumina-styled EV charging hero card with animated charging visualization',
});

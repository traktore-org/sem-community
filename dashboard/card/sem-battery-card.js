(window.semReady || (fn => { window._semReadyQueue = window._semReadyQueue || []; window._semReadyQueue.push(fn); }))(function() {
/**
 * SEM Battery Card — Lumina-styled battery hero card
 *
 * Replaces the mushroom-template-card on the Battery tab with
 * a themed card matching the system diagram aesthetic (dot grid,
 * radial glow, SOC arc ring, tabular-nums typography).
 *
 * Config:
 *   type: custom:sem-battery-card
 *   entity_prefix: sensor.sem_   # default
 */

class SEMBatteryCard extends SEMBaseCard {
    constructor() {
        super();
        this._rendered = false;
    }

    setConfig(config) {
        this.config = config;
        this._prefix = config.entity_prefix || 'sensor.sem_';
    }

    set hass(hass) {
        const localeChanged = this._checkLocaleChange(hass);
        const key = [
            'battery_soc', 'battery_power', 'battery_status',
            'battery_health_score', 'battery_cycles_estimated',
            'daily_battery_charge_energy', 'daily_battery_discharge_energy',
            'daily_battery_savings', 'battery_session_type', 'battery_session_energy',
            'battery_session_solar_share', 'battery_session_duration',
            'battery_session_cost', 'battery_session_savings',
            'flow_solar_to_battery_energy', 'flow_grid_to_battery_energy',
            'monthly_battery_charge_energy', 'monthly_battery_discharge_energy',
        ].map(s => this._hass?.states[`${this._prefix}${s}`]?.state || '').join(',')
            + '|' + this._hass?.language;
        if (key === this._lastKey && !localeChanged) return;
        this._lastKey = key;
        if (localeChanged) {
            this._rendered = false;  // Force skeleton re-render with translations
        }
        const wasUnrendered = !this._rendered;
        this._update();
        if (wasUnrendered) {
            requestAnimationFrame(() => { this.style.visibility = ''; });
        }
    }

    _state(suffix, fallback) {
        const e = this._hass?.states[`${this._prefix}${suffix}`];
        if (!e || e.state === 'unavailable' || e.state === 'unknown') return fallback;
        return parseFloat(e.state) || fallback;
    }

    _stateStr(suffix) {
        const e = this._hass?.states[`${this._prefix}${suffix}`];
        return e?.state || '—';
    }

    _fmt(val, decimals = 1) {
        if (val == null || isNaN(val)) return '—';
        return val.toFixed(decimals);
    }

    _fmtPower(w) { return semFormatPower(w); }

    _update() {
        if (!this._hass) return;

        const soc = this._state('battery_soc', 0);
        const power = this._state('battery_power', 0);
        const chargePower = this._state('battery_charge_power', 0);
        const dischargePower = this._state('battery_discharge_power', 0);
        const statusRaw = this._stateStr('battery_status');
        const health = this._state('battery_health_score', 0);
        const cycles = this._state('battery_cycles_estimated', 0);
        const dailyCharge = this._state('daily_battery_charge_energy', 0);
        const dailyDischarge = this._state('daily_battery_discharge_energy', 0);
        const dailySavings = this._state('daily_battery_savings', 0);

        // Determine status
        const isCharging = statusRaw === 'charging' || chargePower > 10;
        const isDischarging = statusRaw === 'discharging' || dischargePower > 10;
        const status = isCharging ? this._t('charging') : isDischarging ? this._t('discharging') : this._t('idle');

        // Temperature: try battery_temperature sensor
        const tempEntity = this._hass?.states[`${this._prefix}battery_temperature`];
        const temp = (tempEntity && tempEntity.state !== 'unavailable' && tempEntity.state !== 'unknown')
            ? parseFloat(tempEntity.state) : null;

        if (!this._rendered) {
            this.style.visibility = 'hidden';
            this._renderSkeleton();
            this._rendered = true;
        }

        const $ = (sel) => this.shadowRoot.querySelector(sel);
        const setVal = (sel, text) => { const el = $(sel); if (el && el.textContent !== text) el.textContent = text; };

        // SOC arc
        const circumference = 2 * Math.PI * 42;
        const arc = $('.soc-arc');
        if (arc) {
            const pct = Math.min(Math.max(soc / 100, 0), 1);
            const offset = (circumference * (1 - pct)).toFixed(1);
            if (arc.style.strokeDashoffset !== offset) arc.style.strokeDashoffset = offset;
            const arcColor = isCharging ? '#f06292' : '#4db6ac';
            if (arc.style.stroke !== arcColor) arc.style.stroke = arcColor;
            const arcAnim = (isCharging || isDischarging) ? 'socPulse 2s ease-in-out infinite' : 'none';
            if (arc.style.animation !== arcAnim) arc.style.animation = arcAnim;
        }

        // Glow ring color
        const glowRing = $('.glow-ring');
        if (glowRing) {
            const intensity = String((isCharging || isDischarging) ? 0.5 : 0.2);
            if (glowRing.style.opacity !== intensity) glowRing.style.opacity = intensity;
            const ringColor = isCharging ? '#f06292' : '#4db6ac';
            if (glowRing.style.stroke !== ringColor) glowRing.style.stroke = ringColor;
        }

        // Glow filter flood color
        const flood = $('.glow-flood');
        const floodColor = isCharging ? '#f06292' : '#4db6ac';
        if (flood && flood.getAttribute('flood-color') !== floodColor) flood.setAttribute('flood-color', floodColor);

        // Center SOC text
        setVal('.soc-value', `${soc.toFixed(0)}%`);
        const socEl = $('.soc-value');
        const socColor = isCharging ? '#f06292' : '#4db6ac';
        if (socEl && socEl.style.color !== socColor) socEl.style.color = socColor;

        // Metrics
        setVal('.m-soc', `${soc.toFixed(1)}%`);
        setVal('.m-power', this._fmtPower(power));
        setVal('.m-status', status);
        setVal('.m-health', `${this._fmt(health, 1)}%`);
        setVal('.m-cycles', this._fmt(cycles, 1));
        setVal('.m-temp', temp != null ? `${this._fmt(temp, 1)}°C` : '—');

        // Status color
        const statusEl = $('.m-status');
        if (statusEl) {
            const idleColor = (typeof semTheme === 'function') ? semTheme().textSec : '#888';
            const statusColor = isCharging ? '#f06292' : isDischarging ? '#4db6ac' : idleColor;
            if (statusEl.style.color !== statusColor) statusEl.style.color = statusColor;
        }

        // Translate labels
        setVal('.lbl-soc', this._t('soc'));
        setVal('.lbl-power', this._t('power'));
        setVal('.lbl-status', this._t('status'));
        setVal('.lbl-health', this._t('health'));
        setVal('.lbl-cycles', this._t('cycles'));
        setVal('.lbl-temp', this._t('temperature'));
        setVal('.lbl-charge-today', this._t('charge_today'));
        setVal('.lbl-discharge-today', this._t('discharge_today'));
        setVal('.lbl-savings-today', this._t('savings_today'));

        // Daily source attribution
        const solarToBatt = this._state('flow_solar_to_battery_energy', 0);
        const gridToBatt = this._state('flow_grid_to_battery_energy', 0);
        const solarPct = dailyCharge > 0 ? Math.round(solarToBatt / dailyCharge * 100) : 0;

        // Bottom chips — daily
        const currency = window.semGetCurrency?.(this._hass) || 'EUR';
        setVal('.chip-charge', this._fmt(dailyCharge, 2) + ' kWh');
        setVal('.chip-charge-src', solarPct > 0 ? `${solarPct}% ${this._t('solar')}` : '');
        setVal('.chip-discharge', this._fmt(dailyDischarge, 2) + ' kWh');
        setVal('.chip-savings', this._fmt(dailySavings, 2) + ' ' + currency);

        // Battery session section
        const sessionType = this._stateStr('battery_session_type');
        const sessionActive = sessionType === 'charge' || sessionType === 'discharge';
        const sessionEl = $('.session-section');
        if (sessionEl) {
            const sessDisplay = sessionActive ? 'block' : 'none';
            if (sessionEl.style.display !== sessDisplay) sessionEl.style.display = sessDisplay;
            if (sessionActive) {
                const sEnergy = this._state('battery_session_energy', 0);
                const sDuration = this._state('battery_session_duration', 0);
                const sAvgPower = this._state('battery_session_avg_power', 0);
                const sSolarShare = this._state('battery_session_solar_share', 0);
                const sCost = this._state('battery_session_cost', 0);
                const sSavings = this._state('battery_session_savings', 0);
                const isChargeSess = sessionType === 'charge';

                setVal('.sess-title', isChargeSess ? this._t('charging') : this._t('discharging'));
                const sessTitleEl = $('.sess-title');
                const sessColor = isChargeSess ? '#f06292' : '#4db6ac';
                if (sessTitleEl && sessTitleEl.style.color !== sessColor) sessTitleEl.style.color = sessColor;
                setVal('.sess-energy', this._fmt(sEnergy, 2) + ' kWh');
                setVal('.sess-duration', Math.round(sDuration) + ' min');
                setVal('.sess-power', this._fmtPower(sAvgPower));
                if (isChargeSess) {
                    setVal('.sess-source', `${this._t('solar')}: ${this._fmt(sSolarShare, 0)}%`);
                    setVal('.sess-cost', this._fmt(sCost, 2) + ' ' + currency);
                } else {
                    setVal('.sess-source', '');
                    setVal('.sess-cost', this._t('saved') + ' ' + this._fmt(sSavings, 2) + ' ' + currency);
                }
            }
        }

        // Monthly stats
        const monthCharge = this._state('monthly_battery_charge_energy', 0);
        const monthDischarge = this._state('monthly_battery_discharge_energy', 0);
        setVal('.month-charge', this._fmt(monthCharge, 1) + ' kWh');
        setVal('.month-discharge', this._fmt(monthDischarge, 1) + ' kWh');
    }

    _renderSkeleton() {
        const circumference = (2 * Math.PI * 42).toFixed(1);
        const T = (typeof semTheme === 'function') ? semTheme() : {};
        const textCol    = T.text       || '#e0e0e0';
        const textSecCol = T.textSec    || '#999';
        const chipLblCol = T.textTertiary || '#888';
        const surfaceCol = T.surface    || 'rgba(255,255,255,0.06)';
        const surfBorder = T.surfaceBorder || 'rgba(255,255,255,0.05)';
        const surfHover  = T.surfaceHover  || 'rgba(255,255,255,0.12)';
        const dotCol     = T.dotColor   || 'rgba(128,128,128,0.05)';

        this.shadowRoot.innerHTML = `
            <style>
                :host { display: block; contain: layout style paint; }
                .wrap {
                    padding: 16px 20px;
                    position: relative;
                    background:
                        radial-gradient(ellipse 70% 60% at 50% 30%, rgba(77,182,172,0.06) 0%, transparent 100%),
                        radial-gradient(circle at 2px 2px, ${dotCol} 0.7px, transparent 0.7px);
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    color: var(--primary-text-color, ${textCol});
                }
                .glow-svg { position: absolute; width: 0; height: 0; }

                /* Hero layout */
                .hero {
                    display: flex;
                    align-items: center;
                    gap: 20px;
                }
                @media (max-width: 400px) {
                    .hero {
                        flex-direction: column;
                        gap: 12px;
                    }
                }

                /* Battery ring */
                .battery-ring {
                    position: relative;
                    width: 100px;
                    height: 100px;
                    flex-shrink: 0;
                }
                .battery-ring svg {
                    width: 100%;
                    height: 100%;
                    transform: rotate(-90deg);
                }
                .ring-bg {
                    fill: none;
                    stroke: rgba(77,182,172,0.12);
                    stroke-width: 5;
                }
                .soc-arc {
                    fill: none;
                    stroke: #4db6ac;
                    stroke-width: 5;
                    stroke-linecap: round;
                    transition: stroke-dashoffset 1.5s cubic-bezier(0.4,0,0.2,1);
                    filter: url(#batt-glow);
                }
                .glow-ring {
                    fill: none;
                    stroke: #4db6ac;
                    stroke-width: 8;
                    opacity: 0.2;
                    filter: url(#batt-glow-soft);
                    animation: glowPulse 3s ease-in-out infinite;
                    will-change: opacity, r;
                }
                @keyframes glowPulse {
                    0%, 100% { opacity: 0.2; }
                    50% { opacity: 0.08; }
                }
                @keyframes socPulse {
                    0%, 100% { opacity: 1; }
                    50% { opacity: 0.6; }
                }

                .ring-center {
                    position: absolute;
                    top: 50%;
                    left: 50%;
                    transform: translate(-50%, -50%);
                    text-align: center;
                    pointer-events: none;
                }
                .battery-icon {
                    display: block;
                    margin: 0 auto 1px;
                }
                .soc-value {
                    font-size: 14px;
                    font-weight: 700;
                    font-variant-numeric: tabular-nums;
                    color: #4db6ac;
                    text-shadow: 0 0 8px rgba(77,182,172,0.3);
                    line-height: 1;
                }

                /* Metrics column */
                .metrics-col {
                    flex: 1;
                    min-width: 0;
                    display: flex;
                    flex-direction: column;
                    gap: 3px;
                }
                .metric-row {
                    display: flex;
                    justify-content: space-between;
                    align-items: baseline;
                    padding: 2px 0;
                }
                .metric-label {
                    font-size: 12px;
                    color: var(--secondary-text-color, ${textSecCol});
                    font-weight: 500;
                }
                .metric-val {
                    font-size: 13px;
                    font-weight: 600;
                    font-variant-numeric: tabular-nums;
                    color: #4db6ac;
                }

                /* Bottom chips */
                .chips {
                    display: flex;
                    gap: 8px;
                    margin-top: 14px;
                    flex-wrap: wrap;
                }
                .chip {
                    flex: 1;
                    min-width: 80px;
                    background: var(--secondary-background-color, ${surfaceCol});
                    border: 1px solid var(--divider-color, ${surfBorder});
                    border-radius: 10px;
                    padding: 8px 10px;
                    text-align: center;
                    transition: border-color 0.3s cubic-bezier(0.4,0,0.2,1);
                }
                .chip:hover {
                    border-color: var(--divider-color, ${surfHover});
                }
                .chip-label {
                    font-size: 10px;
                    color: var(--secondary-text-color, ${chipLblCol});
                    font-weight: 500;
                    letter-spacing: 0.3px;
                    margin-bottom: 3px;
                }
                .chip-value {
                    font-size: 13px;
                    font-weight: 600;
                    font-variant-numeric: tabular-nums;
                }
                .c-charge { color: #f06292; }
                .c-discharge { color: #4db6ac; }
                .c-savings { color: #8DC892; }
                .chip-src { font-size: 9px; color: var(--secondary-text-color, ${chipLblCol}); margin-top: 1px; }

                /* Session section */
                .session-section {
                    display: none;
                    margin-top: 14px;
                    padding: 10px 12px;
                    background: var(--secondary-background-color, ${surfaceCol});
                    border: 1px solid var(--divider-color, ${surfBorder});
                    border-radius: 10px;
                }
                .sess-header {
                    display: flex;
                    align-items: center;
                    gap: 6px;
                    margin-bottom: 6px;
                }
                .sess-title {
                    font-size: 12px;
                    font-weight: 600;
                    text-transform: uppercase;
                    letter-spacing: 0.5px;
                }
                .sess-grid {
                    display: grid;
                    grid-template-columns: 1fr 1fr 1fr;
                    gap: 4px;
                }
                .sess-item-label {
                    font-size: 10px;
                    color: var(--secondary-text-color, ${chipLblCol});
                }
                .sess-item-value {
                    font-size: 12px;
                    font-weight: 600;
                    font-variant-numeric: tabular-nums;
                    color: var(--primary-text-color, ${textCol});
                }

                /* Monthly section */
                .monthly-section {
                    display: flex;
                    gap: 8px;
                    margin-top: 10px;
                }
                .month-chip {
                    flex: 1;
                    text-align: center;
                    padding: 6px 8px;
                    background: var(--secondary-background-color, ${surfaceCol});
                    border: 1px solid var(--divider-color, ${surfBorder});
                    border-radius: 8px;
                }
            </style>

            <svg class="glow-svg">
                <defs>
                    <filter id="batt-glow" x="-50%" y="-50%" width="200%" height="200%">
                        <feGaussianBlur stdDeviation="4" result="blur"/>
                        <feFlood class="glow-flood" flood-color="#4db6ac" flood-opacity="0.25" result="color"/>
                        <feComposite in="color" in2="blur" operator="in" result="glow"/>
                        <feMerge><feMergeNode in="glow"/><feMergeNode in="SourceGraphic"/></feMerge>
                    </filter>
                    <filter id="batt-glow-soft" x="-50%" y="-50%" width="200%" height="200%">
                        <feGaussianBlur stdDeviation="6" result="blur"/>
                        <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
                    </filter>
                </defs>
            </svg>

            <ha-card>
                <div class="wrap">
                    <div class="hero">
                        <div class="battery-ring">
                            <svg viewBox="0 0 100 100">
                                <circle class="glow-ring" cx="50" cy="50" r="42"/>
                                <circle class="ring-bg" cx="50" cy="50" r="42"/>
                                <circle class="soc-arc" cx="50" cy="50" r="42"
                                    stroke-dasharray="${circumference}"
                                    stroke-dashoffset="${circumference}"/>
                            </svg>
                            <div class="ring-center">
                                <svg class="battery-icon" width="16" height="22" viewBox="0 0 20 30" fill="none" stroke="#4db6ac" stroke-width="1.8" opacity="0.7">
                                    <rect x="2" y="4" width="16" height="26" rx="3"/>
                                    <rect x="6" y="0" width="8" height="5" rx="2" fill="#4db6ac" opacity="0.5" stroke="none"/>
                                </svg>
                                <div class="soc-value">0%</div>
                            </div>
                        </div>
                        <div class="metrics-col">
                            <div class="metric-row">
                                <span class="metric-label lbl-soc">${this._t('soc')}</span>
                                <span class="metric-val m-soc">—</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label lbl-power">${this._t('power')}</span>
                                <span class="metric-val m-power">—</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label lbl-status">${this._t('status')}</span>
                                <span class="metric-val m-status" style="color:#888">—</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label lbl-health">${this._t('health')}</span>
                                <span class="metric-val m-health">—</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label lbl-cycles">${this._t('cycles')}</span>
                                <span class="metric-val m-cycles">—</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label lbl-temp">${this._t('temperature')}</span>
                                <span class="metric-val m-temp">—</span>
                            </div>
                        </div>
                    </div>

                    <!-- Active Session -->
                    <div class="session-section">
                        <div class="sess-header">
                            <ha-icon icon="mdi:battery-sync" style="--mdc-icon-size:14px;color:#4db6ac"></ha-icon>
                            <span class="sess-title">${this._t('charging')}</span>
                        </div>
                        <div class="sess-grid">
                            <div>
                                <div class="sess-item-label">${this._t('energy')}</div>
                                <div class="sess-item-value sess-energy">—</div>
                            </div>
                            <div>
                                <div class="sess-item-label">${this._t('duration')}</div>
                                <div class="sess-item-value sess-duration">—</div>
                            </div>
                            <div>
                                <div class="sess-item-label">${this._t('avg_power')}</div>
                                <div class="sess-item-value sess-power">—</div>
                            </div>
                            <div>
                                <div class="sess-item-label">${this._t('source')}</div>
                                <div class="sess-item-value sess-source">—</div>
                            </div>
                            <div>
                                <div class="sess-item-label">${this._t('cost')}</div>
                                <div class="sess-item-value sess-cost">—</div>
                            </div>
                        </div>
                    </div>

                    <!-- Daily -->
                    <div class="chips">
                        <div class="chip">
                            <div class="chip-label lbl-charge-today">${this._t('charge_today')}</div>
                            <div class="chip-value c-charge chip-charge">—</div>
                            <div class="chip-src chip-charge-src"></div>
                        </div>
                        <div class="chip">
                            <div class="chip-label lbl-discharge-today">${this._t('discharge_today')}</div>
                            <div class="chip-value c-discharge chip-discharge">—</div>
                        </div>
                        <div class="chip">
                            <div class="chip-label lbl-savings-today">${this._t('savings_today')}</div>
                            <div class="chip-value c-savings chip-savings">—</div>
                        </div>
                    </div>

                    <!-- Monthly -->
                    <div class="monthly-section">
                        <div class="month-chip">
                            <div class="chip-label">${this._t('monthly')} ${this._t('charge')}</div>
                            <div class="chip-value c-charge month-charge">—</div>
                        </div>
                        <div class="month-chip">
                            <div class="chip-label">${this._t('monthly')} ${this._t('discharge')}</div>
                            <div class="chip-value c-discharge month-discharge">—</div>
                        </div>
                    </div>
                </div>
            </ha-card>
        `;
    }

    getCardSize() { return 3; }

    static getStubConfig() { return {}; }
}

semDefineCard('sem-battery-card', SEMBatteryCard, {
    type: 'sem-battery-card',
    name: 'SEM Battery',
    description: 'Lumina-styled battery hero card with SOC arc ring and key metrics',
});

});

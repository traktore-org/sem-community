(window.semReady || (fn => { window._semReadyQueue = window._semReadyQueue || []; window._semReadyQueue.push(fn); }))(function() {
/**
 * SEM Solar Card — Lumina-styled consolidated solar production card
 *
 * Shows live solar power, daily/monthly/yearly totals, flow breakdown,
 * forecast, and performance metrics in a single themed card.
 *
 * Config:
 *   type: custom:sem-solar-card
 *   entity_prefix: sensor.sem_   # default
 */

class SEMSolarCard extends SEMBaseCard {
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
            'solar_power', 'daily_solar_energy', 'monthly_solar_yield_energy', 'yearly_solar_yield_energy',
            'flow_solar_to_home_power', 'flow_solar_to_battery_power', 'flow_solar_to_ev_power', 'flow_solar_to_grid_power',
            'flow_solar_to_home_energy', 'flow_solar_to_battery_energy', 'flow_solar_to_ev_energy', 'flow_solar_to_grid_energy',
            'forecast_today_kwh', 'forecast_tomorrow_kwh', 'forecast_remaining_today_kwh',
            'forecast_peak_power_today_w', 'forecast_peak_time_today', 'best_surplus_window',
            'pv_daily_specific_yield', 'pv_performance_vs_forecast',
            'pv_estimated_annual_degradation', 'pv_degradation_trend',
        ].map(s => this._hass?.states[`${this._prefix}${s}`]?.state || '').join(',')
            + '|' + this._hass?.language;
        if (key === this._lastKey && !localeChanged) return;
        this._lastKey = key;
        if (localeChanged) this._rendered = false;
        this._update();
    }

    _state(suffix, fallback = 0) {
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

    _update() {
        if (!this._hass) return;
        const isFirstRender = !this._rendered;
        if (isFirstRender) {
            this.style.visibility = 'hidden';
            this._renderSkeleton();
            this._rendered = true;
        }

        const $ = (sel) => this.shadowRoot.querySelector(sel);
        const setVal = (sel, text) => { const el = $(sel); if (el && el.textContent !== text) el.textContent = text; };

        const power = this._state('solar_power');
        const dailyEnergy = this._state('daily_solar_energy');
        const monthlyEnergy = this._state('monthly_solar_yield_energy');
        const yearlyEnergy = this._state('yearly_solar_yield_energy');

        // Production level for ring (0-10kW typical max)
        const maxPower = 10000;
        const pct = Math.min(Math.max(power / maxPower, 0), 1);
        const circumference = 2 * Math.PI * 42;
        const arc = $('.solar-arc');
        if (arc) {
            const arcOffset = (circumference * (1 - pct)).toFixed(1);
            const arcAnim = power > 50 ? 'solarPulse 3s ease-in-out infinite' : 'none';
            if (arc.style.strokeDashoffset !== arcOffset) arc.style.strokeDashoffset = arcOffset;
            if (arc.style.animation !== arcAnim) arc.style.animation = arcAnim;
        }
        const glowFlood = $('.solar-glow-flood');
        if (glowFlood && glowFlood.getAttribute('flood-color') !== '#ff9800') glowFlood.setAttribute('flood-color', '#ff9800');

        setVal('.solar-power-value', semFormatPower(power));
        setVal('.solar-daily-value', this._fmt(dailyEnergy, 2) + ' kWh');

        // Today flows
        setVal('.flow-home-power', semFormatPower(this._state('flow_solar_to_home_power')));
        setVal('.flow-home-energy', this._fmt(this._state('flow_solar_to_home_energy'), 2) + ' kWh');
        setVal('.flow-batt-power', semFormatPower(this._state('flow_solar_to_battery_power')));
        setVal('.flow-batt-energy', this._fmt(this._state('flow_solar_to_battery_energy'), 2) + ' kWh');
        setVal('.flow-ev-power', semFormatPower(this._state('flow_solar_to_ev_power')));
        setVal('.flow-ev-energy', this._fmt(this._state('flow_solar_to_ev_energy'), 2) + ' kWh');
        setVal('.flow-grid-power', semFormatPower(this._state('flow_solar_to_grid_power')));
        setVal('.flow-grid-energy', this._fmt(this._state('flow_solar_to_grid_energy'), 2) + ' kWh');

        // Forecast
        setVal('.fc-today', this._fmt(this._state('forecast_today_kwh'), 1) + ' kWh');
        setVal('.fc-tomorrow', this._fmt(this._state('forecast_tomorrow_kwh'), 1) + ' kWh');
        setVal('.fc-remaining', this._fmt(this._state('forecast_remaining_today_kwh'), 1) + ' kWh');
        const peakW = this._state('forecast_peak_power_today_w');
        setVal('.fc-peak', peakW > 0 ? semFormatPower(peakW) : '—');
        const peakTime = this._stateStr('forecast_peak_time_today');
        setVal('.fc-peak-time', peakTime !== '—' ? peakTime : '—');
        setVal('.fc-window', this._stateStr('best_surplus_window'));

        // Performance
        const specYield = this._state('pv_daily_specific_yield');
        const vsFC = this._state('pv_performance_vs_forecast');
        const degradation = this._state('pv_estimated_annual_degradation');
        const trend = this._stateStr('pv_degradation_trend');
        setVal('.perf-yield', specYield > 0 ? this._fmt(specYield, 2) + ' kWh/kWp' : '—');
        const vsFCEl = $('.perf-vs-fc');
        if (vsFCEl) {
            const vsFCText = vsFC !== 0 ? this._fmt(vsFC, 0) + '%' : '—';
            const vsFCColor = vsFC >= 0 ? '#8DC892' : '#f06292';
            if (vsFCEl.textContent !== vsFCText) vsFCEl.textContent = vsFCText;
            if (vsFCEl.style.color !== vsFCColor) vsFCEl.style.color = vsFCColor;
        }
        setVal('.perf-degradation', degradation !== 0 ? this._fmt(degradation, 2) + '%/yr' : '—');
        setVal('.perf-trend', trend !== '—' ? trend : '—');

        // Monthly / Yearly totals
        setVal('.monthly-total', this._fmt(monthlyEnergy, 1) + ' kWh');
        setVal('.yearly-total', this._fmt(yearlyEnergy, 1) + ' kWh');

        // Labels (translated)
        setVal('.lbl-today-flows', this._t('solar_flows_today'));
        setVal('.lbl-forecast', this._t('forecast'));
        setVal('.lbl-performance', this._t('performance'));
        setVal('.lbl-monthly', this._t('monthly'));
        setVal('.lbl-yearly', this._t('yearly'));
        setVal('.lbl-home', this._t('home'));
        setVal('.lbl-battery', this._t('battery'));
        setVal('.lbl-ev', this._t('ev'));
        setVal('.lbl-grid-exp', this._t('grid_export'));
        setVal('.lbl-fc-today', this._t('today'));
        setVal('.lbl-fc-tomorrow', this._t('tomorrow'));
        setVal('.lbl-fc-remaining', this._t('remaining'));
        setVal('.lbl-fc-peak', this._t('peak_power'));
        setVal('.lbl-fc-window', this._t('best_surplus_window'));
        setVal('.lbl-spec-yield', this._t('specific_yield'));
        setVal('.lbl-vs-fc', this._t('vs_forecast'));
        setVal('.lbl-degradation', this._t('degradation'));
        setVal('.lbl-trend', this._t('trend'));
        if (isFirstRender) requestAnimationFrame(() => { this.style.visibility = ''; });
    }

    _renderSkeleton() {
        const T = (typeof semTheme === 'function') ? semTheme() : {};
        const textCol    = T.text          || '#e0e0e0';
        const textSecCol = T.textSec       || '#999';
        const chipLblCol = T.textTertiary  || '#888';
        const surfaceCol = T.surface       || 'rgba(255,255,255,0.06)';
        const surfBorder = T.surfaceBorder || 'rgba(255,255,255,0.12)';
        const dotCol     = T.dotColor      || 'rgba(128,128,128,0.05)';
        const circumference = (2 * Math.PI * 42).toFixed(1);

        this.shadowRoot.innerHTML = `
            <style>
                :host { display: block; }
                .wrap {
                    padding: 16px 20px;
                    position: relative;
                    background:
                        radial-gradient(ellipse 70% 60% at 50% 20%, rgba(255,152,0,0.07) 0%, transparent 100%),
                        radial-gradient(circle at 2px 2px, ${dotCol} 0.7px, transparent 0.7px);
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    color: var(--primary-text-color, ${textCol});
                }
                .glow-svg { position: absolute; width: 0; height: 0; }

                /* ── Hero ── */
                .hero { display: flex; align-items: center; gap: 20px; }
                @media (max-width: 400px) { .hero { flex-direction: column; gap: 12px; } }

                .solar-ring { position: relative; width: 100px; height: 100px; flex-shrink: 0; }
                .solar-ring svg { width: 100%; height: 100%; transform: rotate(-90deg); }
                .ring-bg { fill: none; stroke: rgba(255,152,0,0.12); stroke-width: 5; }
                .solar-arc {
                    fill: none; stroke: #ff9800; stroke-width: 5; stroke-linecap: round;
                    transition: stroke-dashoffset 1.5s cubic-bezier(0.4,0,0.2,1);
                    filter: url(#solar-glow);
                }
                .solar-glow-ring {
                    fill: none; stroke: #ff9800; stroke-width: 8; opacity: 0.2;
                    filter: url(#solar-glow-soft);
                }
                @keyframes solarPulse { 0%,100%{opacity:1}50%{opacity:0.6} }

                .ring-center {
                    position: absolute; top: 50%; left: 50%;
                    transform: translate(-50%, -50%);
                    text-align: center; pointer-events: none;
                }
                .solar-power-value {
                    font-size: 13px; font-weight: 700;
                    font-variant-numeric: tabular-nums;
                    color: #ff9800;
                    text-shadow: 0 0 8px rgba(255,152,0,0.35);
                    line-height: 1.2;
                }
                .solar-daily-value {
                    font-size: 10px; color: var(--secondary-text-color,${textSecCol});
                    font-variant-numeric: tabular-nums;
                }

                /* ── Section divider ── */
                .section {
                    margin-top: 12px;
                    padding: 10px 12px;
                    background: var(--secondary-background-color, ${surfaceCol});
                    border: 1px solid var(--divider-color, ${surfBorder});
                    border-radius: 10px;
                }
                .section-title {
                    font-size: 10px; font-weight: 600; text-transform: uppercase;
                    letter-spacing: 0.6px; color: #ff9800; margin-bottom: 8px;
                }

                /* ── Flows grid ── */
                .flows-grid {
                    display: grid;
                    grid-template-columns: 1fr 1fr;
                    gap: 8px 24px;
                }
                .flow-row { display: flex; align-items: center; gap: 6px; }
                .flow-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
                .flow-label { font-size: 11px; color: var(--secondary-text-color,${textSecCol}); flex: 1; }
                .flow-vals { text-align: right; }
                .flow-power {
                    font-size: 11px; font-weight: 600;
                    font-variant-numeric: tabular-nums;
                    color: var(--primary-text-color,${textCol});
                }
                .flow-energy {
                    font-size: 9px; color: var(--secondary-text-color,${textSecCol});
                    font-variant-numeric: tabular-nums;
                }

                /* ── Two-column section layout ── */
                .two-col {
                    display: grid;
                    grid-template-columns: 1fr 1fr;
                    gap: 0 20px;
                }
                @media (max-width: 400px) {
                    .two-col { grid-template-columns: 1fr; }
                }

                /* ── Metric rows (forecast / performance) ── */
                .metric-row {
                    display: flex; justify-content: space-between; align-items: baseline;
                    padding: 2px 0;
                }
                .metric-label {
                    font-size: 11px; color: var(--secondary-text-color,${textSecCol});
                    font-weight: 500;
                }
                .metric-val {
                    font-size: 12px; font-weight: 600;
                    font-variant-numeric: tabular-nums;
                    color: var(--primary-text-color,${textCol});
                }

                /* ── Monthly / yearly chips ── */
                .chips { display: flex; gap: 8px; margin-top: 10px; }
                .chip {
                    flex: 1; text-align: center; padding: 7px 8px;
                    background: var(--secondary-background-color, ${surfaceCol});
                    border: 1px solid var(--divider-color, ${surfBorder});
                    border-radius: 10px;
                }
                .chip-label {
                    font-size: 10px; color: var(--secondary-text-color,${chipLblCol});
                    font-weight: 500; margin-bottom: 2px;
                }
                .chip-value {
                    font-size: 13px; font-weight: 600; color: #ff9800;
                    font-variant-numeric: tabular-nums;
                }
            </style>

            <svg class="glow-svg">
                <defs>
                    <filter id="solar-glow" x="-50%" y="-50%" width="200%" height="200%">
                        <feGaussianBlur stdDeviation="4" result="blur"/>
                        <feFlood class="solar-glow-flood" flood-color="#ff9800" flood-opacity="0.3" result="color"/>
                        <feComposite in="color" in2="blur" operator="in" result="glow"/>
                        <feMerge><feMergeNode in="glow"/><feMergeNode in="SourceGraphic"/></feMerge>
                    </filter>
                    <filter id="solar-glow-soft" x="-50%" y="-50%" width="200%" height="200%">
                        <feGaussianBlur stdDeviation="6" result="blur"/>
                        <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
                    </filter>
                </defs>
            </svg>

            <ha-card>
                <div class="wrap">
                    <!-- Hero -->
                    <div class="hero">
                        <div class="solar-ring">
                            <svg viewBox="0 0 100 100">
                                <circle class="solar-glow-ring" cx="50" cy="50" r="42">
                                    <animate attributeName="opacity" values="0.2;0.07;0.2" dur="4s" repeatCount="indefinite"/>
                                </circle>
                                <circle class="ring-bg" cx="50" cy="50" r="42"/>
                                <circle class="solar-arc" cx="50" cy="50" r="42"
                                    stroke-dasharray="${circumference}"
                                    stroke-dashoffset="${circumference}"/>
                            </svg>
                            <div class="ring-center">
                                <ha-icon icon="mdi:solar-power" style="--mdc-icon-size:22px;color:#ff9800;opacity:0.8"></ha-icon>
                                <div class="solar-power-value">— W</div>
                                <div class="solar-daily-value">— kWh</div>
                            </div>
                        </div>

                        <!-- Right column: monthly + yearly quick stats -->
                        <div style="flex:1;min-width:0">
                            <div class="chips" style="margin-top:0">
                                <div class="chip">
                                    <div class="chip-label lbl-monthly">${this._t('monthly')}</div>
                                    <div class="chip-value monthly-total">—</div>
                                </div>
                                <div class="chip">
                                    <div class="chip-label lbl-yearly">${this._t('yearly')}</div>
                                    <div class="chip-value yearly-total">—</div>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- Today's Flows -->
                    <div class="section">
                        <div class="section-title lbl-today-flows">${this._t('solar_flows_today')}</div>
                        <div class="flows-grid">
                            <div class="flow-row">
                                <div class="flow-dot" style="background:#5BC8D8"></div>
                                <span class="flow-label lbl-home">${this._t('home')}</span>
                                <div class="flow-vals">
                                    <div class="flow-power flow-home-power">—</div>
                                    <div class="flow-energy flow-home-energy">—</div>
                                </div>
                            </div>
                            <div class="flow-row">
                                <div class="flow-dot" style="background:#f06292"></div>
                                <span class="flow-label lbl-battery">${this._t('battery')}</span>
                                <div class="flow-vals">
                                    <div class="flow-power flow-batt-power">—</div>
                                    <div class="flow-energy flow-batt-energy">—</div>
                                </div>
                            </div>
                            <div class="flow-row">
                                <div class="flow-dot" style="background:#8DC892"></div>
                                <span class="flow-label lbl-ev">${this._t('ev')}</span>
                                <div class="flow-vals">
                                    <div class="flow-power flow-ev-power">—</div>
                                    <div class="flow-energy flow-ev-energy">—</div>
                                </div>
                            </div>
                            <div class="flow-row">
                                <div class="flow-dot" style="background:#8353d1"></div>
                                <span class="flow-label lbl-grid-exp">${this._t('grid_export')}</span>
                                <div class="flow-vals">
                                    <div class="flow-power flow-grid-power">—</div>
                                    <div class="flow-energy flow-grid-energy">—</div>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- Forecast + Performance (side by side) -->
                    <div class="section two-col">
                        <div>
                            <div class="section-title lbl-forecast">${this._t('forecast')}</div>
                            <div class="metric-row">
                                <span class="metric-label lbl-fc-today">${this._t('today')}</span>
                                <span class="metric-val fc-today">—</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label lbl-fc-tomorrow">${this._t('tomorrow')}</span>
                                <span class="metric-val fc-tomorrow">—</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label lbl-fc-remaining">${this._t('remaining')}</span>
                                <span class="metric-val fc-remaining">—</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label lbl-fc-peak">${this._t('peak_power')}</span>
                                <span class="metric-val">
                                    <span class="fc-peak">—</span>
                                    <span class="fc-peak-time" style="font-size:10px;opacity:0.7;margin-left:4px">—</span>
                                </span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label lbl-fc-window">${this._t('best_surplus_window')}</span>
                                <span class="metric-val fc-window" style="color:#ff9800;font-size:11px">—</span>
                            </div>
                        </div>
                        <div>
                            <div class="section-title lbl-performance">${this._t('performance')}</div>
                            <div class="metric-row">
                                <span class="metric-label lbl-spec-yield">${this._t('specific_yield')}</span>
                                <span class="metric-val perf-yield">—</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label lbl-vs-fc">${this._t('vs_forecast')}</span>
                                <span class="metric-val perf-vs-fc">—</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label lbl-degradation">${this._t('degradation')}</span>
                                <span class="metric-val perf-degradation">—</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label lbl-trend">${this._t('trend')}</span>
                                <span class="metric-val perf-trend">—</span>
                            </div>
                        </div>
                    </div>
                </div>
            </ha-card>
        `;
    }

    getCardSize() { return 5; }

    static getStubConfig() { return { entity_prefix: 'sensor.sem_' }; }
}

semDefineCard('sem-solar-card', SEMSolarCard, {
    type: 'sem-solar-card',
    name: 'SEM Solar',
    description: 'Consolidated solar production card with flows, forecast, and performance metrics',
});

});

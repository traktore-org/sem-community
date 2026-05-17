(window.semReady || (fn => { window._semReadyQueue = window._semReadyQueue || []; window._semReadyQueue.push(fn); }))(function() {
/**
 * SEM Home Status Card — Consolidated status panel for the Home tab
 *
 * Replaces 7 mushroom cards with a single interactive card showing:
 *  1. Status chips row (solar, battery, autarky, EV, score)
 *  2. Smart energy tip + best surplus window
 *  3. Peak load status
 *  4. Quick controls (observer toggle + forecast provider)
 *  5. Environmental impact (CO2 today + lifetime)
 *
 * Config:
 *   type: custom:sem-home-status-card
 *   entity_prefix: sensor.sem_   # optional, default
 */

class SEMHomeStatusCard extends SEMBaseCard {
    constructor() {
        super();
        this._rendered = false;
        this._lastKey = '';
    }

    setConfig(config) {
        this.config = config;
        this._prefix = config.entity_prefix || 'sensor.sem_';
    }

    // ── Entity readers ──

    _state(suffix, fallback = 0) {
        const e = this._hass?.states[`${this._prefix}${suffix}`];
        if (!e || e.state === 'unavailable' || e.state === 'unknown') return fallback;
        return parseFloat(e.state) ?? fallback;
    }

    _stateStr(suffix) {
        const e = this._hass?.states[`${this._prefix}${suffix}`];
        return (e && e.state !== 'unavailable' && e.state !== 'unknown') ? e.state : '';
    }

    _switchState(suffix) {
        const e = this._hass?.states[`switch.sem_${suffix}`];
        return e?.state === 'on';
    }

    // ── Lifecycle ──

    set hass(hass) {
        const localeChanged = this._checkLocaleChange(hass);

        const watchKeys = [
            'sensor.sem_solar_power',
            'sensor.sem_battery_soc',
            'sensor.sem_autarky_rate',
            'sensor.sem_ev_power',
            'sensor.sem_energy_optimization_score',
            'sensor.sem_energy_tip',
            'sensor.sem_best_surplus_window',
            'sensor.sem_forecast_remaining_today_kwh',
            'sensor.sem_current_vs_peak_percentage',
            'sensor.sem_consecutive_peak_15min',
            'sensor.sem_target_peak_limit',
            'sensor.sem_daily_co2_avoided',
            'sensor.sem_lifetime_co2_avoided',
            'sensor.sem_diag_forecast_provider',
            'switch.sem_observer_mode',
        ];
        const key = watchKeys.map(k => hass.states[k]?.state || '').join(',');

        if (key === this._lastKey && !localeChanged) return;
        this._lastKey = key;

        if (!this._rendered || localeChanged) {
            this.style.visibility = 'hidden';
            this._renderSkeleton();
            this._rendered = true;
            this._update();
            requestAnimationFrame(() => { this.style.visibility = ''; });
            return;
        }
        this._update();
    }

    // ── Service call ──

    async _callService(domain, service, data) {
        if (!this._hass) return;
        try {
            await this._hass.callService(domain, service, data);
        } catch (e) {
            console.error('[SEM Home Status]', domain, service, data, e);
        }
    }

    _toggleSwitch(entityId) {
        const state = this._hass?.states[entityId];
        if (!state) return;
        const svc = state.state === 'on' ? 'turn_off' : 'turn_on';
        this._callService('switch', svc, { entity_id: entityId });
    }

    // ── Score color ──

    _scoreColor(score) {
        if (score >= 80) return '#8DC892';
        if (score >= 50) return '#ff9800';
        return '#f44336';
    }

    // ── Peak color ──

    _peakColor(pct) {
        if (pct > 90) return '#f44336';
        if (pct > 70) return '#ff9800';
        return '#8DC892';
    }

    _peakStatusKey(pct) {
        if (pct > 90) return 'peak_critical';
        if (pct > 70) return 'peak_warning';
        return 'peak_safe';
    }

    // ── DOM update (no full re-render) ──

    _update() {
        if (!this._hass) return;
        const root = this.shadowRoot;
        const $ = (sel) => root.querySelector(sel);
        const setText = (sel, text) => {
            const el = $(sel);
            if (el && el.textContent !== text) el.textContent = text;
        };

        // ── 1. Status chips ──
        const solar = this._state('solar_power');
        setText('.chip-solar .chip-val', semFormatPower(solar));

        const soc = this._state('battery_soc');
        setText('.chip-battery .chip-val', `${soc.toFixed(0)}%`);

        const autarky = this._state('autarky_rate');
        setText('.chip-autarky .chip-val', `${autarky.toFixed(0)}%`);

        const evPower = this._state('ev_power');
        setText('.chip-ev .chip-val', evPower > 0 ? semFormatPower(evPower) : '—');

        const score = this._state('energy_optimization_score');
        setText('.chip-score .chip-val', score.toFixed(0));
        const scoreEl = $('.chip-score .chip-icon');
        const scoreColor = this._scoreColor(score);
        if (scoreEl && scoreEl.style.color !== scoreColor) scoreEl.style.color = scoreColor;

        // ── 2. Smart tip ──
        const tip = this._stateStr('energy_tip');
        const tipSection = $('.tip-section');
        if (tipSection) {
            const tipDisplay = tip ? '' : 'none';
            if (tipSection.style.display !== tipDisplay) tipSection.style.display = tipDisplay;
        }
        if (tip) {
            setText('.tip-primary', tip);
            const window_ = this._stateStr('best_surplus_window') || '—';
            const remaining = this._state('forecast_remaining_today_kwh').toFixed(1);
            setText('.tip-secondary', `${this._t('best_window')}: ${window_} · ${this._t('surplus')}: ${remaining} kWh`);
        }

        // ── 3. Peak load ──
        const peakPct = this._state('current_vs_peak_percentage');
        const peakColor = this._peakColor(peakPct);
        const peakPctEl = $('.peak-pct');
        if (peakPctEl) {
            const text = `${peakPct.toFixed(0)}%`;
            if (peakPctEl.textContent !== text) peakPctEl.textContent = text;
            if (peakPctEl.style.color !== peakColor) peakPctEl.style.color = peakColor;
        }

        const currentPeak = this._state('consecutive_peak_15min').toFixed(1);
        const targetLimit = this._state('target_peak_limit').toFixed(1);
        setText('.peak-detail', `${currentPeak} / ${targetLimit} kW (${peakPct.toFixed(0)}%)`);

        const peakStatusEl = $('.peak-status-badge');
        if (peakStatusEl) {
            const statusText = this._t(this._peakStatusKey(peakPct));
            if (peakStatusEl.textContent !== statusText) peakStatusEl.textContent = statusText;
            if (peakStatusEl.style.color !== peakColor) peakStatusEl.style.color = peakColor;
            if (peakStatusEl.style.borderColor !== peakColor) peakStatusEl.style.borderColor = peakColor;
        }

        // ── 4. Quick controls ──
        this._updateObserverToggle();

        const provider = this._stateStr('diag_forecast_provider') || '—';
        setText('.forecast-val', provider);

        // ── 5. Environmental impact ──
        const co2Today = this._state('daily_co2_avoided').toFixed(2);
        const co2Life = this._state('lifetime_co2_avoided').toFixed(1);
        setText('.co2-today-val', `${co2Today} kg`);
        setText('.co2-life-val', `${co2Life} kg`);

        // Translated labels
        setText('.tip-label', this._t('smart_tip'));
        setText('.peak-label', this._t('peak_load'));
        setText('.controls-label', this._t('quick_controls'));
        setText('.env-label', this._t('environmental_impact'));
        setText('.observer-toggle-label', this._t('observer'));
        setText('.forecast-label', this._t('forecast'));
        setText('.co2-today-label', this._t('co2_today'));
        setText('.co2-life-label', this._t('co2_lifetime'));
    }

    _updateObserverToggle() {
        const isOn = this._switchState('observer_mode');
        const track = this.shadowRoot.querySelector('.observer-track');
        if (!track) return;
        track.classList.toggle('on', isOn);
        if (!track._semBound) {
            track._semBound = true;
            track.addEventListener('click', () => this._toggleSwitch('switch.sem_observer_mode'));
        }
    }

    // ── Chip HTML helper ──

    _chipHTML(cls, icon, color, label, valCls) {
        return `
            <div class="chip ${cls}" title="${label}">
                <ha-icon class="chip-icon" icon="${icon}"
                         style="--mdc-icon-size:16px;color:${color}"></ha-icon>
                <span class="${valCls} chip-val">—</span>
            </div>`;
    }

    // ── Full skeleton render ──

    _renderSkeleton() {
        const T = (typeof semTheme === 'function') ? semTheme() : {};
        const textCol    = T.text            || '#e0e0e0';
        const textSecCol = T.textSec         || '#999';
        const surfaceCol = T.surface         || 'rgba(255,255,255,0.06)';
        const surfBorder = T.surfaceBorder   || 'rgba(255,255,255,0.12)';
        const surfHover  = T.surfaceHover    || 'rgba(255,255,255,0.10)';
        const dotCol     = T.dotColor        || 'rgba(128,128,128,0.05)';
        const isDark     = T.isDark !== false;
        const accent     = T.accent          || '#42a5f5';

        this.shadowRoot.innerHTML = `
            <style>
                :host { display: block; }

                .wrap {
                    padding: 16px;
                    position: relative;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    color: var(--primary-text-color, ${textCol});
                    background:
                        radial-gradient(ellipse 70% 60% at 50% 20%, rgba(91,200,216,0.06) 0%, transparent 100%),
                        radial-gradient(circle at 2px 2px, ${dotCol} 0.7px, transparent 0.7px);
                    background-size: 100% 100%, 50px 50px;
                }

                /* ── Section label ── */
                .section-label {
                    font-size: 10px;
                    font-weight: 600;
                    text-transform: uppercase;
                    letter-spacing: 0.6px;
                    color: var(--secondary-text-color, ${textSecCol});
                    margin-bottom: 6px;
                }

                /* ── Divider ── */
                .divider {
                    height: 1px;
                    background: ${surfBorder};
                    margin: 12px 0;
                }

                /* ─────────────────── 1. Chips ─────────────────── */
                .chips-row {
                    display: flex;
                    gap: 6px;
                    overflow-x: auto;
                    padding-bottom: 4px;
                    scrollbar-width: none;
                    -ms-overflow-style: none;
                }
                .chips-row::-webkit-scrollbar { display: none; }

                .chip {
                    display: inline-flex;
                    align-items: center;
                    gap: 4px;
                    padding: 4px 10px;
                    border-radius: 12px;
                    border: 1px solid ${surfBorder};
                    background: ${surfaceCol};
                    white-space: nowrap;
                    flex-shrink: 0;
                    backdrop-filter: blur(16px) saturate(160%);
                    -webkit-backdrop-filter: blur(16px) saturate(160%);
                }
                .chip-val {
                    font-size: 12px;
                    font-weight: 600;
                    font-variant-numeric: tabular-nums;
                }

                /* ─────────────────── 2. Tip ─────────────────── */
                .tip-section {
                    display: flex;
                    gap: 10px;
                    align-items: flex-start;
                    padding: 10px 12px;
                    border-radius: 12px;
                    background: ${isDark ? 'rgba(255,152,0,0.06)' : 'rgba(255,152,0,0.05)'};
                    border: 1px solid rgba(255,152,0,0.20);
                }
                .tip-section ha-icon { flex-shrink: 0; margin-top: 1px; }
                .tip-content { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
                .tip-primary {
                    font-size: 13px;
                    font-weight: 500;
                    line-height: 1.4;
                }
                .tip-secondary {
                    font-size: 11px;
                    color: var(--secondary-text-color, ${textSecCol});
                    line-height: 1.3;
                }

                /* ─────────────────── 3. Peak ─────────────────── */
                .peak-row {
                    display: flex;
                    align-items: center;
                    gap: 10px;
                }
                .peak-icon-wrap {
                    display: flex;
                    align-items: center;
                    gap: 6px;
                    flex-shrink: 0;
                }
                .peak-pct {
                    font-size: 22px;
                    font-weight: 700;
                    font-variant-numeric: tabular-nums;
                    line-height: 1;
                }
                .peak-text-wrap {
                    display: flex;
                    flex-direction: column;
                    gap: 2px;
                    min-width: 0;
                }
                .peak-detail {
                    font-size: 12px;
                    color: var(--secondary-text-color, ${textSecCol});
                    white-space: nowrap;
                    overflow: hidden;
                    text-overflow: ellipsis;
                }
                .peak-status-badge {
                    display: inline-block;
                    font-size: 10px;
                    font-weight: 600;
                    text-transform: uppercase;
                    letter-spacing: 0.4px;
                    padding: 2px 7px;
                    border-radius: 8px;
                    border: 1px solid;
                    align-self: flex-start;
                }

                /* ─────────────────── 4. Quick controls ─────────────────── */
                .controls-row {
                    display: flex;
                    gap: 12px;
                    align-items: center;
                    flex-wrap: wrap;
                }
                .observer-toggle {
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    flex: 1;
                    min-width: 120px;
                }
                .observer-toggle-label {
                    font-size: 13px;
                    font-weight: 500;
                    flex: 1;
                }
                .observer-indicator {
                    width: 8px; height: 8px;
                    border-radius: 50%;
                    background: #f44336;
                    display: none;
                    flex-shrink: 0;
                }
                .toggle-track.on ~ .observer-indicator { display: block; }
                .toggle-track {
                    position: relative;
                    width: 42px; height: 24px;
                    border-radius: 12px;
                    background: ${isDark ? 'rgba(255,255,255,0.15)' : 'rgba(0,0,0,0.18)'};
                    cursor: pointer;
                    transition: background 0.2s;
                    flex-shrink: 0;
                }
                .toggle-track.on { background: ${accent}; }
                .toggle-thumb {
                    position: absolute;
                    top: 2px; left: 2px;
                    width: 20px; height: 20px;
                    border-radius: 50%;
                    background: white;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.3);
                    transition: left 0.2s;
                }
                .toggle-track.on .toggle-thumb { left: 20px; }

                .forecast-chip {
                    display: flex;
                    align-items: center;
                    gap: 6px;
                    padding: 4px 10px;
                    border-radius: 12px;
                    border: 1px solid ${surfBorder};
                    background: ${surfaceCol};
                    flex-shrink: 0;
                }
                .forecast-label {
                    font-size: 11px;
                    color: var(--secondary-text-color, ${textSecCol});
                    font-weight: 500;
                }
                .forecast-val {
                    font-size: 12px;
                    font-weight: 600;
                }

                /* ─────────────────── 5. Environmental ─────────────────── */
                .env-row {
                    display: flex;
                    gap: 8px;
                    flex-wrap: wrap;
                }
                .env-chip {
                    display: flex;
                    align-items: center;
                    gap: 6px;
                    padding: 6px 12px;
                    border-radius: 12px;
                    border: 1px solid rgba(141,200,146,0.25);
                    background: ${isDark ? 'rgba(141,200,146,0.06)' : 'rgba(141,200,146,0.05)'};
                    flex: 1;
                    min-width: 120px;
                }
                .env-chip ha-icon { flex-shrink: 0; }
                .env-chip-content { display: flex; flex-direction: column; gap: 0; }
                .env-chip-val {
                    font-size: 13px;
                    font-weight: 600;
                    font-variant-numeric: tabular-nums;
                }
                .env-chip-label {
                    font-size: 10px;
                    color: var(--secondary-text-color, ${textSecCol});
                    text-transform: uppercase;
                    letter-spacing: 0.3px;
                }

                @media (max-width: 400px) {
                    .env-row { flex-direction: column; }
                    .controls-row { flex-direction: column; align-items: flex-start; }
                }
            </style>

            <div class="wrap">

                <!-- 1. Status Chips -->
                <div class="section-label chip-title-label"></div>
                <div class="chips-row">
                    ${this._chipHTML('chip-solar',   'mdi:solar-power',   '#ff9800', 'Solar',   'solar-val')}
                    ${this._chipHTML('chip-battery',  'mdi:battery',       '#4db6ac', 'Battery', 'battery-val')}
                    ${this._chipHTML('chip-autarky',  'mdi:leaf',          '#8DC892', 'Autarky', 'autarky-val')}
                    ${this._chipHTML('chip-ev',       'mdi:car-electric',  '#8DC892', 'EV',      'ev-val')}
                    ${this._chipHTML('chip-score',    'mdi:speedometer',   '#8DC892', 'Score',   'score-val')}
                </div>

                <div class="divider"></div>

                <!-- 2. Smart Tip -->
                <div class="tip-section">
                    <ha-icon icon="mdi:lightbulb-on-outline"
                             style="--mdc-icon-size:20px;color:#ff9800"></ha-icon>
                    <div class="tip-content">
                        <span class="section-label tip-label"></span>
                        <span class="tip-primary"></span>
                        <span class="tip-secondary"></span>
                    </div>
                </div>

                <div class="divider"></div>

                <!-- 3. Peak Load -->
                <div class="section-label peak-label"></div>
                <div class="peak-row">
                    <div class="peak-icon-wrap">
                        <ha-icon icon="mdi:flash-alert"
                                 style="--mdc-icon-size:22px;color:#ff9800"></ha-icon>
                        <span class="peak-pct">—</span>
                    </div>
                    <div class="peak-text-wrap">
                        <span class="peak-detail">—</span>
                        <span class="peak-status-badge">—</span>
                    </div>
                </div>

                <div class="divider"></div>

                <!-- 4. Quick Controls -->
                <div class="section-label controls-label"></div>
                <div class="controls-row">
                    <div class="observer-toggle">
                        <ha-icon icon="mdi:eye-outline"
                                 style="--mdc-icon-size:18px;color:#96CAEE"></ha-icon>
                        <span class="observer-toggle-label"></span>
                        <div class="toggle-track observer-track">
                            <div class="toggle-thumb"></div>
                        </div>
                    </div>
                    <div class="forecast-chip">
                        <ha-icon icon="mdi:weather-partly-cloudy"
                                 style="--mdc-icon-size:16px;color:#96CAEE"></ha-icon>
                        <span class="forecast-label"></span>
                        <span class="forecast-val">—</span>
                    </div>
                </div>

                <div class="divider"></div>

                <!-- 5. Environmental Impact -->
                <div class="section-label env-label"></div>
                <div class="env-row">
                    <div class="env-chip">
                        <ha-icon icon="mdi:leaf"
                                 style="--mdc-icon-size:18px;color:#8DC892"></ha-icon>
                        <div class="env-chip-content">
                            <span class="env-chip-val co2-today-val">— kg</span>
                            <span class="env-chip-label co2-today-label"></span>
                        </div>
                    </div>
                    <div class="env-chip">
                        <ha-icon icon="mdi:tree"
                                 style="--mdc-icon-size:18px;color:#8DC892"></ha-icon>
                        <div class="env-chip-content">
                            <span class="env-chip-val co2-life-val">— kg</span>
                            <span class="env-chip-label co2-life-label"></span>
                        </div>
                    </div>
                </div>

            </div>`;
    }

    getCardSize() { return 5; }

    static getStubConfig() {
        return { entity_prefix: 'sensor.sem_' };
    }
}

semDefineCard('sem-home-status-card', SEMHomeStatusCard, {
    type: 'custom:sem-home-status-card',
    name: 'SEM Home Status Card',
    description: 'Consolidated status panel for the SEM Home tab',
    preview: false,
});

});

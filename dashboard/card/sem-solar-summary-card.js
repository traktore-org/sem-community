/**
 * SEM Solar Summary Card — Lumina-styled solar overview
 *
 * Replaces the HACS solar-card with a fully themed card matching
 * the system diagram aesthetic (dot grid, radial glow, glow filters,
 * tabular-nums typography).
 *
 * Config:
 *   type: custom:sem-solar-summary-card
 *   entity_prefix: sensor.sem_   # default
 */

class SEMSolarSummaryCard extends HTMLElement {
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
        // Skip update if key sensors haven't changed
        const key = ['solar_power', 'daily_solar_energy', 'self_consumption_rate', 'autarky_rate', 'daily_costs']
            .map(s => this._hass?.states[`${this._prefix}${s}`]?.state || '').join(',');
        if (key === this._lastKey) return;
        this._lastKey = key;
        this._update();
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

    _fmtPower(w) {
        if (w == null || isNaN(w)) return '— W';
        if (Math.abs(w) >= 1000) return (w / 1000).toFixed(1) + ' kW';
        return Math.round(w) + ' W';
    }

    _update() {
        if (!this._hass) return;

        const solarPower = this._state('solar_power', 0);
        const dailySolar = this._state('daily_solar_energy', 0);
        const monthlySolar = this._state('monthly_solar_yield_energy', 0);
        const forecastToday = this._state('forecast_today_kwh', 0);
        const forecastTomorrow = this._state('forecast_tomorrow_kwh', 0);
        const selfUse = this._state('self_consumption_rate', 0);
        const autarky = this._state('autarky_rate', 0);
        const dailyCost = this._state('daily_costs', 0);
        const dailySavings = this._state('daily_savings', 0);
        const dailyEv = this._state('daily_ev_energy', 0);
        const gridToday = this._state('daily_grid_import_energy', 0);

        // Solar power ratio for glow intensity (0-1)
        const maxExpected = 10000; // 10kW system
        const powerRatio = Math.min(solarPower / maxExpected, 1);
        const glowOpacity = 0.15 + powerRatio * 0.6;

        if (!this._rendered) {
            this._renderSkeleton();
            this._rendered = true;
        }

        // Update dynamic values
        const $ = (sel) => this.shadowRoot.querySelector(sel);
        const setVal = (sel, text) => { const el = $(sel); if (el) el.textContent = text; };

        setVal('.solar-power', this._fmtPower(solarPower));
        setVal('.daily-solar', this._fmt(dailySolar, 2) + ' kWh');
        setVal('.monthly-solar', this._fmt(monthlySolar, 1) + ' kWh');
        setVal('.forecast-today', this._fmt(forecastToday, 1) + ' kWh');
        setVal('.forecast-tomorrow', this._fmt(forecastTomorrow, 1) + ' kWh');
        setVal('.self-use', this._fmt(selfUse, 1) + '%');
        setVal('.autarky', this._fmt(autarky, 1) + '%');
        const _c = window.semGetCurrency?.(this._hass) || 'EUR';
        setVal('.daily-cost', this._fmt(dailyCost, 2) + ' ' + _c);
        setVal('.daily-savings', this._fmt(dailySavings, 2) + ' ' + _c);
        setVal('.daily-ev', this._fmt(dailyEv, 1) + ' kWh');
        setVal('.grid-today', this._fmt(gridToday, 2) + ' kWh');

        // Update glow ring opacity
        const ring = $('.glow-ring');
        if (ring) ring.style.opacity = glowOpacity;

        // Update progress arc (daily solar vs forecast)
        const arc = $('.progress-arc');
        if (arc && forecastToday > 0) {
            const pct = Math.min(dailySolar / forecastToday, 1);
            const circumference = 2 * Math.PI * 42;
            arc.style.strokeDasharray = `${circumference}`;
            arc.style.strokeDashoffset = `${circumference * (1 - pct)}`;
        }
    }

    _renderSkeleton() {
        this.shadowRoot.innerHTML = `
            <style>
                :host { display: block; }
                .wrap {
                    padding: 20px;
                    position: relative;
                    background:
                        radial-gradient(ellipse 70% 60% at 50% 30%, rgba(255,152,0,0.06) 0%, transparent 100%),
                        radial-gradient(circle at 2px 2px, rgba(128,128,128,0.05) 0.7px, transparent 0.7px);
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    color: #e0e0e0;
                }
                /* SVG glow filter */
                .glow-svg { position: absolute; width: 0; height: 0; }

                /* Hero section */
                .hero {
                    display: flex;
                    align-items: center;
                    gap: 20px;
                    margin-bottom: 20px;
                }
                .solar-ring {
                    position: relative;
                    width: 100px;
                    height: 100px;
                    flex-shrink: 0;
                }
                .solar-ring svg {
                    width: 100%;
                    height: 100%;
                    transform: rotate(-90deg);
                }
                .ring-bg {
                    fill: none;
                    stroke: rgba(255,152,0,0.12);
                    stroke-width: 5;
                }
                .progress-arc {
                    fill: none;
                    stroke: #ff9800;
                    stroke-width: 5;
                    stroke-linecap: round;
                    transition: stroke-dashoffset 1.5s cubic-bezier(0.4,0,0.2,1);
                    filter: url(#solar-glow);
                }
                .glow-ring {
                    fill: none;
                    stroke: #ff9800;
                    stroke-width: 8;
                    opacity: 0.15;
                    filter: url(#solar-glow-soft);
                }
                .ring-icon {
                    position: absolute;
                    top: 50%;
                    left: 50%;
                    transform: translate(-50%, -50%);
                    text-align: center;
                }
                .ring-icon .power {
                    font-size: 18px;
                    font-weight: 700;
                    font-variant-numeric: tabular-nums;
                    color: #ff9800;
                    text-shadow: 0 0 8px rgba(255,152,0,0.3);
                }
                .ring-icon .label {
                    font-size: 10px;
                    color: rgba(255,152,0,0.6);
                    font-weight: 500;
                    letter-spacing: 1px;
                    text-transform: uppercase;
                }
                .hero-stats {
                    flex: 1;
                    min-width: 0;
                }
                .hero-title {
                    font-size: 13px;
                    font-weight: 600;
                    color: rgba(255,152,0,0.85);
                    letter-spacing: 0.5px;
                    margin-bottom: 8px;
                }
                .hero-row {
                    display: flex;
                    justify-content: space-between;
                    align-items: baseline;
                    padding: 3px 0;
                }
                .hero-label {
                    font-size: 12px;
                    color: #999;
                    font-weight: 500;
                }
                .hero-value {
                    font-size: 13px;
                    font-weight: 600;
                    font-variant-numeric: tabular-nums;
                }

                /* Metrics grid */
                .metrics {
                    display: grid;
                    grid-template-columns: repeat(3, 1fr);
                    gap: 10px;
                }
                .metric {
                    background:
                        radial-gradient(ellipse 80% 60% at 50% 50%, rgba(200,220,240,0.03) 0%, transparent 100%),
                        rgba(40, 40, 55, 0.4);
                    border: 1px solid rgba(255,255,255,0.05);
                    border-radius: 10px;
                    padding: 10px;
                    text-align: center;
                    transition: border-color 0.3s cubic-bezier(0.4,0,0.2,1);
                }
                .metric:hover {
                    border-color: rgba(255,255,255,0.12);
                }
                .metric-label {
                    font-size: 10px;
                    color: #888;
                    font-weight: 500;
                    letter-spacing: 0.3px;
                    margin-bottom: 4px;
                }
                .metric-value {
                    font-size: 14px;
                    font-weight: 600;
                    font-variant-numeric: tabular-nums;
                }
                .c-solar { color: #ff9800; }
                .c-grid { color: #488fc2; }
                .c-ev { color: #8DC892; }
                .c-home { color: #5BC8D8; }
                .c-savings { color: #4db6ac; }
                .c-cost { color: #f06292; }
            </style>

            <svg class="glow-svg">
                <defs>
                    <filter id="solar-glow" x="-50%" y="-50%" width="200%" height="200%">
                        <feGaussianBlur stdDeviation="3" result="blur"/>
                        <feFlood flood-color="#ff9800" flood-opacity="0.25" result="color"/>
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
                    <div class="hero">
                        <div class="solar-ring">
                            <svg viewBox="0 0 100 100">
                                <circle class="glow-ring" cx="50" cy="50" r="42">
                                    <animate attributeName="r" values="42;45;42" dur="3s" repeatCount="indefinite"/>
                                    <animate attributeName="opacity" values="0.15;0.06;0.15" dur="3s" repeatCount="indefinite"/>
                                </circle>
                                <circle class="ring-bg" cx="50" cy="50" r="42"/>
                                <circle class="progress-arc" cx="50" cy="50" r="42"
                                    stroke-dasharray="${2 * Math.PI * 42}"
                                    stroke-dashoffset="${2 * Math.PI * 42}"/>
                            </svg>
                            <div class="ring-icon">
                                <div class="power solar-power">0 W</div>
                                <div class="label">SOLAR</div>
                            </div>
                        </div>
                        <div class="hero-stats">
                            <div class="hero-title">Production</div>
                            <div class="hero-row">
                                <span class="hero-label">Yield today</span>
                                <span class="hero-value c-solar daily-solar">—</span>
                            </div>
                            <div class="hero-row">
                                <span class="hero-label">Grid today</span>
                                <span class="hero-value c-grid grid-today">—</span>
                            </div>
                            <div class="hero-row">
                                <span class="hero-label">Forecast</span>
                                <span class="hero-value c-solar forecast-today">—</span>
                            </div>
                            <div class="hero-row">
                                <span class="hero-label">Tomorrow</span>
                                <span class="hero-value forecast-tomorrow" style="color:#b0b0b0">—</span>
                            </div>
                        </div>
                    </div>

                    <div class="metrics">
                        <div class="metric">
                            <div class="metric-label">Self-use</div>
                            <div class="metric-value c-home self-use">—</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">Autarky</div>
                            <div class="metric-value c-savings autarky">—</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">EV Today</div>
                            <div class="metric-value c-ev daily-ev">—</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">Cost</div>
                            <div class="metric-value c-cost daily-cost">—</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">Saved</div>
                            <div class="metric-value c-savings daily-savings">—</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">Monthly</div>
                            <div class="metric-value c-solar monthly-solar">—</div>
                        </div>
                    </div>
                </div>
            </ha-card>
        `;
    }

    getCardSize() { return 4; }

    static getStubConfig() { return {}; }
}

customElements.define('sem-solar-summary-card', SEMSolarSummaryCard);

window.customCards = window.customCards || [];
window.customCards.push({
    type: 'sem-solar-summary-card',
    name: 'SEM Solar Summary',
    description: 'Lumina-styled solar overview with glow ring and production metrics',
});

/**
 * SEM Weather Card — Lumina-styled weather display
 *
 * Replaces the HACS clock-weather-card with a fully themed card matching
 * the system diagram aesthetic (dot grid, radial glow, glow filters).
 *
 * Config:
 *   type: custom:sem-weather-card
 *   entity: weather.home   # weather entity
 *   forecast_rows: 5       # number of forecast rows (default 5)
 */

const WEATHER_ICONS = {
    'clear-night': { icon: '\u{1F319}', label: 'Clear' },
    'cloudy': { icon: '\u2601\uFE0F', label: 'Cloudy' },
    'fog': { icon: '\u{1F32B}\uFE0F', label: 'Fog' },
    'hail': { icon: '\u{1F9CA}', label: 'Hail' },
    'lightning': { icon: '\u26A1', label: 'Thunder' },
    'lightning-rainy': { icon: '\u26C8\uFE0F', label: 'Thunderstorm' },
    'partlycloudy': { icon: '\u26C5', label: 'Partly Cloudy' },
    'pouring': { icon: '\u{1F327}\uFE0F', label: 'Pouring' },
    'rainy': { icon: '\u{1F326}\uFE0F', label: 'Rain' },
    'snowy': { icon: '\u2744\uFE0F', label: 'Snow' },
    'snowy-rainy': { icon: '\u{1F328}\uFE0F', label: 'Sleet' },
    'sunny': { icon: '\u2600\uFE0F', label: 'Sunny' },
    'windy': { icon: '\u{1F4A8}', label: 'Windy' },
    'windy-variant': { icon: '\u{1F4A8}', label: 'Windy' },
    'exceptional': { icon: '\u26A0\uFE0F', label: 'Exceptional' },
};

class SEMWeatherCard extends HTMLElement {
    constructor() {
        super();
        this.attachShadow({ mode: 'open' });
        this._rendered = false;
    }

    setConfig(config) {
        if (!config.entity) throw new Error('sem-weather-card requires entity');
        this.config = config;
        this._forecastRows = config.forecast_rows || 5;
    }

    set hass(hass) {
        this._hass = hass;
        this._update();
    }

    _update() {
        if (!this._hass) return;
        const entity = this._hass.states[this.config.entity];
        if (!entity) {
            if (!this._rendered) this._renderError('Entity not found');
            return;
        }

        if (!this._rendered) {
            this._renderSkeleton();
            this._rendered = true;
        }

        const state = entity.state;
        const attrs = entity.attributes;
        const temp = attrs.temperature != null ? Math.round(attrs.temperature) : '—';
        const unit = attrs.temperature_unit || '\u00B0C';
        const humidity = attrs.humidity != null ? Math.round(attrs.humidity) : '—';
        const windSpeed = attrs.wind_speed != null ? Math.round(attrs.wind_speed) : '—';
        const windUnit = attrs.wind_speed_unit || 'km/h';
        const weatherInfo = WEATHER_ICONS[state] || { icon: '\u2753', label: state };

        // Current time
        const now = new Date();
        const locale = this._hass?.language || navigator.language || 'en';
        const timeStr = now.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' });
        const dateStr = now.toLocaleDateString(locale, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });

        const $ = (sel) => this.shadowRoot.querySelector(sel);

        const setVal = (sel, text) => { const el = $(sel); if (el) el.textContent = text; };
        const setHtml = (sel, html) => { const el = $(sel); if (el) el.innerHTML = html; };

        setVal('.time', timeStr);
        setVal('.date', dateStr);
        setVal('.weather-icon', weatherInfo.icon);
        setVal('.weather-label', weatherInfo.label);
        setVal('.temp', `${temp}${unit}`);
        setVal('.humidity', `${humidity}%`);
        setVal('.wind', `${windSpeed} ${windUnit}`);

        // Forecast
        const forecast = attrs.forecast || [];
        const forecastEl = $('.forecast-rows');
        if (forecastEl && forecast.length) {
            const rows = forecast.slice(0, this._forecastRows).map(f => {
                const dt = new Date(f.datetime);
                const day = dt.toLocaleDateString(this._hass?.language || navigator.language || 'en', { weekday: 'short' });
                const fIcon = WEATHER_ICONS[f.condition]?.icon || '\u2753';
                const low = f.templow != null ? Math.round(f.templow) : '—';
                const high = f.temperature != null ? Math.round(f.temperature) : '—';
                const range = high - low;
                const maxRange = 30; // normalize bar width
                const barWidth = Math.max(range / maxRange * 100, 10);
                // Color temperature bar from blue (cold) to orange (warm)
                const midTemp = (low + high) / 2;
                const warmth = Math.min(Math.max((midTemp - 0) / 30, 0), 1);
                const barColor = warmth > 0.5
                    ? `rgba(255,${Math.round(200 - warmth * 100)},0,0.6)`
                    : `rgba(${Math.round(100 + warmth * 200)},${Math.round(180 + warmth * 40)},255,0.5)`;

                return `
                    <div class="forecast-row">
                        <span class="f-day">${day}</span>
                        <span class="f-icon">${fIcon}</span>
                        <span class="f-low">${low}°</span>
                        <div class="f-bar-wrap">
                            <div class="f-bar" style="width:${barWidth}%;background:${barColor}"></div>
                        </div>
                        <span class="f-high">${high}°</span>
                    </div>
                `;
            }).join('');
            forecastEl.innerHTML = rows;
        }

        // Update clock periodically
        if (!this._clockInterval) {
            this._clockInterval = setInterval(() => {
                const n = new Date();
                const loc = this._hass?.language || navigator.language || 'en';
                setVal('.time', n.toLocaleTimeString(loc, { hour: '2-digit', minute: '2-digit' }));
            }, 30000);
        }
    }

    disconnectedCallback() {
        if (this._clockInterval) {
            clearInterval(this._clockInterval);
            this._clockInterval = null;
        }
    }

    _renderError(msg) {
        this.shadowRoot.innerHTML = `<ha-card><div style="padding:16px;color:#ef5350">${msg}</div></ha-card>`;
        this._rendered = true;
    }

    _renderSkeleton() {
        const T = (typeof semTheme === 'function') ? semTheme() : {};
        const textCol    = T.text        || '#e0e0e0';
        const textSecCol = T.textSec     || '#999';
        const surfaceCol = T.surface     || 'rgba(255,255,255,0.06)';
        const surfBorder = T.surfaceBorder || 'rgba(255,255,255,0.06)';
        const dotCol     = T.dotColor    || 'rgba(128,128,128,0.05)';

        this.shadowRoot.innerHTML = `
            <style>
                :host { display: block; }
                .wrap {
                    padding: 24px 20px 16px;
                    position: relative;
                    background:
                        radial-gradient(ellipse 70% 60% at 50% 35%, rgba(200,220,240,0.06) 0%, transparent 100%),
                        radial-gradient(circle at 2px 2px, ${dotCol} 0.7px, transparent 0.7px);
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    color: var(--primary-text-color, ${textCol});
                }

                /* Clock section */
                .clock-section {
                    display: flex;
                    justify-content: space-between;
                    align-items: flex-start;
                    margin-bottom: 20px;
                }
                .clock-left {
                    flex: 1;
                }
                .time {
                    font-size: 48px;
                    font-weight: 700;
                    font-variant-numeric: tabular-nums;
                    letter-spacing: -1px;
                    line-height: 1;
                    color: var(--primary-text-color, ${textCol});
                    text-shadow: 0 0 20px rgba(200,220,240,0.15);
                }
                .date {
                    font-size: 13px;
                    color: var(--secondary-text-color, ${textSecCol});
                    margin-top: 6px;
                    font-weight: 500;
                }

                /* Weather current */
                .weather-current {
                    text-align: right;
                    flex-shrink: 0;
                }
                .weather-icon {
                    font-size: 40px;
                    line-height: 1;
                    filter: drop-shadow(0 0 8px rgba(200,220,240,0.2));
                }
                .weather-label {
                    font-size: 12px;
                    color: var(--secondary-text-color, ${textSecCol});
                    margin-top: 2px;
                    font-weight: 500;
                }
                .temp {
                    font-size: 28px;
                    font-weight: 700;
                    font-variant-numeric: tabular-nums;
                    color: var(--primary-text-color, ${textCol});
                    text-shadow: 0 0 12px rgba(200,220,240,0.1);
                }

                /* Weather details */
                .weather-details {
                    display: flex;
                    gap: 16px;
                    margin-bottom: 16px;
                    padding-bottom: 14px;
                    border-bottom: 1px solid ${surfBorder};
                }
                .detail {
                    display: flex;
                    align-items: center;
                    gap: 6px;
                    font-size: 12px;
                    color: var(--secondary-text-color, ${textSecCol});
                }
                .detail-icon {
                    font-size: 14px;
                    opacity: 0.7;
                }

                /* Forecast */
                .forecast-rows {
                    display: flex;
                    flex-direction: column;
                    gap: 6px;
                }
                .forecast-row {
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    font-size: 13px;
                    font-variant-numeric: tabular-nums;
                    padding: 4px 0;
                }
                .f-day {
                    width: 32px;
                    color: var(--secondary-text-color, ${textSecCol});
                    font-weight: 500;
                    font-size: 12px;
                }
                .f-icon {
                    font-size: 16px;
                    width: 24px;
                    text-align: center;
                }
                .f-low {
                    width: 30px;
                    text-align: right;
                    color: #78a8d8;
                    font-weight: 500;
                    font-size: 12px;
                }
                .f-bar-wrap {
                    flex: 1;
                    height: 4px;
                    background: ${surfaceCol};
                    border-radius: 2px;
                    overflow: hidden;
                }
                .f-bar {
                    height: 100%;
                    border-radius: 2px;
                    transition: width 0.5s cubic-bezier(0.4,0,0.2,1);
                }
                .f-high {
                    width: 30px;
                    text-align: right;
                    color: #e0a050;
                    font-weight: 600;
                    font-size: 12px;
                }
            </style>

            <ha-card>
                <div class="wrap">
                    <div class="clock-section">
                        <div class="clock-left">
                            <div class="time">--:--</div>
                            <div class="date"></div>
                        </div>
                        <div class="weather-current">
                            <div class="weather-icon"></div>
                            <div class="weather-label"></div>
                            <div class="temp">—</div>
                        </div>
                    </div>

                    <div class="weather-details">
                        <div class="detail">
                            <span class="detail-icon">\u{1F4A7}</span>
                            <span class="humidity">—</span>
                        </div>
                        <div class="detail">
                            <span class="detail-icon">\u{1F4A8}</span>
                            <span class="wind">—</span>
                        </div>
                    </div>

                    <div class="forecast-rows"></div>
                </div>
            </ha-card>
        `;
    }

    getCardSize() { return 5; }

    static getStubConfig() { return { entity: 'weather.home' }; }
}

customElements.define('sem-weather-card', SEMWeatherCard);

window.customCards = window.customCards || [];
window.customCards.push({
    type: 'sem-weather-card',
    name: 'SEM Weather',
    description: 'Lumina-styled clock + weather card with forecast',
});

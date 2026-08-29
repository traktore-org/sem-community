/**
 * SEM Weather Card — LitElement clock + weather display with forecast
 *
 * Config:
 *   type: custom:sem-weather-card
 *   entity: weather.home   # required weather entity
 *   forecast_rows: 5       # number of forecast rows (default 5)
 */

import { SEMLitBase, html, css, nothing, semGlassCss } from '../base/sem-lit-base.js';
import { semTheme, semDefineCard } from '../base/sem-shared.js';

const WEATHER_ICONS = {
    'clear-night':     { icon: '🌙', key: 'weather_clear' },
    'cloudy':          { icon: '☁️', key: 'weather_cloudy' },
    'fog':             { icon: '🌫️', key: 'weather_fog' },
    'hail':            { icon: '🧊', key: 'weather_hail' },
    'lightning':       { icon: '⚡', key: 'weather_thunder' },
    'lightning-rainy': { icon: '⛈️', key: 'weather_thunderstorm' },
    'partlycloudy':    { icon: '⛅', key: 'weather_partly_cloudy' },
    'pouring':         { icon: '🌧️', key: 'weather_pouring' },
    'rainy':           { icon: '🌦️', key: 'weather_rain' },
    'snowy':           { icon: '❄️', key: 'weather_snow' },
    'snowy-rainy':     { icon: '🌨️', key: 'weather_sleet' },
    'sunny':           { icon: '☀️', key: 'weather_sunny' },
    'windy':           { icon: '💨', key: 'weather_windy' },
    'windy-variant':   { icon: '💨', key: 'weather_windy' },
    'exceptional':     { icon: '⚠️', key: 'weather_exceptional' },
};

class SEMWeatherCard extends SEMLitBase {
    // #617 — glass chrome baked in (was card-mod *glass_card)
    static get styles() { return [semGlassCss]; }

    constructor() {
        super();
        this._clockTime = '--:--';
        this._clockDate = '';
        this._clockInterval = null;
    }

    // Watched entities are dynamic — derived from config
    static get watchedEntities() { return []; }

    setConfig(config) {
        if (!config.entity) throw new Error('sem-weather-card requires entity');
        super.setConfig(config);
    }

    // Override hass setter to check weather entity state/forecast
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

        const entityId = this._config?.entity;
        if (!entityId) return;

        const weatherEntity = hass?.states[entityId];
        const newKey = (weatherEntity?.state || '')
            + JSON.stringify(weatherEntity?.attributes?.forecast?.[0] || '')
            + '|' + (lang || '');

        if (newKey === this._lastWeatherKey && !localeChanged) return;
        this._lastWeatherKey = newKey;

        this.requestUpdate();
    }

    get hass() {
        return this._hass;
    }

    connectedCallback() {
        super.connectedCallback();
        this._updateClock();
        this._clockInterval = setInterval(() => {
            this._updateClock();
        }, 30000);
    }

    disconnectedCallback() {
        super.disconnectedCallback();
        if (this._clockInterval) {
            clearInterval(this._clockInterval);
            this._clockInterval = null;
        }
    }

    _updateClock() {
        const now = new Date();
        const locale = this._hass?.language || navigator.language || 'en';
        // Show the home's local time (HA tz, DST-aware), not the viewer's browser tz.
        const tz = this._hass?.config?.time_zone || undefined;
        this._clockTime = now.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit', timeZone: tz });
        this._clockDate = now.toLocaleDateString(locale, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric', timeZone: tz });
        this.requestUpdate();
    }

    _renderForecastRows(forecast, forecastRows) {
        const locale = this._hass?.language || navigator.language || 'en';
        const tz = this._hass?.config?.time_zone || undefined;
        return forecast.slice(0, forecastRows).map(f => {
            const dt = new Date(f.datetime);
            const day = dt.toLocaleDateString(locale, { weekday: 'short', timeZone: tz });
            const fIcon = WEATHER_ICONS[f.condition]?.icon || '❓';
            const low = f.templow != null ? Math.round(f.templow) : '—';
            const high = f.temperature != null ? Math.round(f.temperature) : '—';
            const range = (typeof high === 'number' && typeof low === 'number') ? high - low : 0;
            const barWidth = Math.max(range / 30 * 100, 10);
            const midTemp = (typeof high === 'number' && typeof low === 'number') ? (low + high) / 2 : 15;
            const warmth = Math.min(Math.max((midTemp - 0) / 30, 0), 1);
            const barColor = warmth > 0.5
                ? `rgba(255,${Math.round(200 - warmth * 100)},0,0.6)`
                : `rgba(${Math.round(100 + warmth * 200)},${Math.round(180 + warmth * 40)},255,0.5)`;

            return html`
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
        });
    }

    // #516: find a weather.* entity that actually carries usable current
    // data (a numeric ``temperature``, not unavailable/unknown). Prefer
    // real entities over the auto-generated ``weather.forecast_*`` subentity.
    _findUsableWeatherEntity() {
        const states = this._hass?.states;
        if (!states) return null;
        const usable = Object.keys(states).filter((id) => {
            if (!id.startsWith('weather.')) return false;
            const s = states[id];
            return s && s.state !== 'unavailable' && s.state !== 'unknown'
                && s.attributes && s.attributes.temperature != null;
        });
        const nonForecast = usable.filter((id) => !id.startsWith('weather.forecast_'));
        return nonForecast[0] || usable[0] || null;
    }

    render() {
        if (!this._config) return nothing;

        let entityId = this._config.entity;
        const forecastRows = this._config.forecast_rows || 5;
        let entity = this._hass?.states[entityId];

        // #516: the configured entity can be missing, ``unavailable``, or a
        // ``weather.forecast_*`` subentity that carries no ``temperature``
        // (RienduPre saw a "?" + "—°C" tile). The dashboard generator picks
        // one weather entity at build time; if it was reloading then, or the
        // user only has forecast subentities, that pick is useless. Fall back
        // at render time to any weather.* entity that actually has a
        // temperature — preferring non-forecast — so the tile self-heals.
        if (!entity || entity.state === 'unavailable'
                || entity.attributes?.temperature == null) {
            const fallbackId = this._findUsableWeatherEntity();
            if (fallbackId) {
                entityId = fallbackId;
                entity = this._hass.states[fallbackId];
            }
        }

        if (!entity) {
            return html`
                <ha-card>
                    <div style="padding:16px;color:#ef5350">Entity ${entityId} not found</div>
                </ha-card>
            `;
        }

        const T = this._theme();
        const state = entity.state;
        const attrs = entity.attributes;
        const temp = attrs.temperature != null ? Math.round(attrs.temperature) : '—';
        const unit = attrs.temperature_unit || '°C';
        const humidity = attrs.humidity != null ? Math.round(attrs.humidity) : '—';
        const windSpeed = attrs.wind_speed != null ? Math.round(attrs.wind_speed) : '—';
        const windUnit = attrs.wind_speed_unit || 'km/h';
        const weatherInfo = WEATHER_ICONS[state] || { icon: '❓', key: '' };
        const forecast = attrs.forecast || [];

        return html`
            <style>
                :host { display: block; }
                .wrap {
                    padding: 24px 20px 16px;
                    position: relative;
                    background:
                        radial-gradient(ellipse 70% 60% at 50% 35%, rgba(200,220,240,0.06) 0%, transparent 100%),
                        radial-gradient(circle at 2px 2px, ${T.dotColor} 0.7px, transparent 0.7px);
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    color: var(--primary-text-color, ${T.text});
                }
                .clock-section {
                    display: flex;
                    justify-content: space-between;
                    align-items: flex-start;
                    margin-bottom: 20px;
                }
                .clock-left { flex: 1; }
                .time {
                    font-size: 48px;
                    font-weight: 700;
                    font-variant-numeric: tabular-nums;
                    letter-spacing: -1px;
                    line-height: 1;
                    color: var(--primary-text-color, ${T.text});
                    text-shadow: 0 0 20px rgba(200,220,240,0.15);
                }
                .date {
                    font-size: 13px;
                    color: var(--secondary-text-color, ${T.textSec});
                    margin-top: 6px;
                    font-weight: 500;
                }
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
                    color: var(--secondary-text-color, ${T.textSec});
                    margin-top: 2px;
                    font-weight: 500;
                }
                .temp {
                    font-size: 28px;
                    font-weight: 700;
                    font-variant-numeric: tabular-nums;
                    color: var(--primary-text-color, ${T.text});
                    text-shadow: 0 0 12px rgba(200,220,240,0.1);
                }
                .weather-details {
                    display: flex;
                    gap: 16px;
                    margin-bottom: 16px;
                    padding-bottom: 14px;
                    border-bottom: 1px solid var(--divider-color, ${T.surfaceBorder});
                }
                .detail {
                    display: flex;
                    align-items: center;
                    gap: 6px;
                    font-size: 12px;
                    color: var(--secondary-text-color, ${T.textSec});
                }
                .detail-icon { font-size: 14px; opacity: 0.7; }
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
                    color: var(--secondary-text-color, ${T.textSec});
                    font-weight: 500;
                    font-size: 12px;
                }
                .f-icon { font-size: 16px; width: 24px; text-align: center; }
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
                    background: var(--secondary-background-color, ${T.surface});
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
                            <div class="time">${this._clockTime}</div>
                            <div class="date">${this._clockDate}</div>
                        </div>
                        <div class="weather-current">
                            <div class="weather-icon">${weatherInfo.icon}</div>
                            <div class="weather-label">${this._t(weatherInfo.key)}</div>
                            <div class="temp">${temp}${unit}</div>
                        </div>
                    </div>

                    <div class="weather-details">
                        <div class="detail">
                            <span class="detail-icon">💧</span>
                            <span>${humidity}%</span>
                        </div>
                        <div class="detail">
                            <span class="detail-icon">💨</span>
                            <span>${windSpeed} ${windUnit}</span>
                        </div>
                    </div>

                    <div class="forecast-rows">
                        ${forecast.length ? this._renderForecastRows(forecast, forecastRows) : nothing}
                    </div>
                </div>
            </ha-card>
        `;
    }

    getCardSize() { return 5; }
    static getStubConfig() { return { entity: 'weather.home' }; }
}

semDefineCard('sem-weather-card', SEMWeatherCard, {
    type: 'sem-weather-card',
    name: 'SEM Weather',
    description: 'Lumina-styled clock + weather card with forecast',
    documentationURL:
        'https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-weather-card',
    preview: false,
});

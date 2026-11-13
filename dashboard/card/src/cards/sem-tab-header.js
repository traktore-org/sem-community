/**
 * SEM Tab Header Card — Lumina-styled section header with glow icon
 *
 * Placed at the top of each dashboard tab. Shows a custom SVG icon
 * with glow ring, tab title, subtitle, and live stats.
 */

import { SEMLitBase, html, css, svg, nothing } from '../base/sem-lit-base.js';
import { semTheme, semFormatPower, semGetCurrency, semDefineCard } from '../base/sem-shared.js';
import { peakLimitText } from '../util/peak-slot.js';
import { PEAK_TEXT } from '../util/peak-questions.js';
import { MISSING, isMissing, socDisplay } from '../util/missing-value.js';

const _t = (key, hass) => (typeof semLocalize === 'function') ? semLocalize(key, hass?.language) : key;

// (#1198) A figure: the number in its format, or the dash when its sensor
// is out. A 0 printed for a sensor that is out looks like a reading.
const fig = (v, fmt) => (v == null ? MISSING : fmt(v));
const pct = (v) => v.toFixed(0) + '%';
const kwh = (v) => v.toFixed(1) + ' kWh';

// Icon templates use Lit's `svg` tag so child elements are created in the SVG
// namespace. With plain `html` they get the HTML namespace, render as
// HTMLUnknownElement, and show up blank inside the icon ring.
const SEM_TAB_CONFIG = {
    home: {
        titleKey: 'home', subtitleKey: 'home_sub', color: '#5BC8D8',
        icon: () => svg`
            <path d="M-20,2 L0,-16 L20,2" stroke-width="2"/>
            <rect x="-15" y="2" width="30" height="22" rx="2" stroke-width="2"/>
            <rect x="-5" y="12" width="10" height="12" stroke-width="1.5"/>`,
    },
    energy: {
        titleKey: 'energy', subtitleKey: 'energy_sub', color: '#ff9800',
        icon: () => svg`
            <path d="M-4,-18 L-10,2 L-2,2 L-6,18 L12,-4 L2,-4 L8,-18 Z" stroke-width="2"/>`,
    },
    battery: {
        titleKey: 'battery', subtitleKey: 'battery_sub', color: '#4db6ac',
        icon: () => svg`
            <rect x="-10" y="-16" width="20" height="32" rx="4" stroke-width="2"/>
            <rect x="-4" y="-20" width="8" height="5" rx="2" fill="currentColor" opacity="0.4" stroke="none"/>
            <line x1="-5" y1="-4" x2="5" y2="-4" stroke-width="1.5" opacity="0.5"/>
            <line x1="-5" y1="4" x2="5" y2="4" stroke-width="1.5" opacity="0.5"/>`,
    },
    ev: {
        titleKey: 'ev_charging', subtitleKey: 'ev_sub', color: '#8DC892',
        icon: () => svg`
            <rect x="-12" y="-14" width="24" height="24" rx="5" stroke-width="2"/>
            <path d="M-3,-6 L-1,0 L-5,0 L3,8" stroke-width="2" fill="none"/>
            <line x1="0" y1="10" x2="0" y2="16" stroke-width="2"/>
            <circle cx="0" cy="18" r="2" fill="currentColor" opacity="0.4" stroke="none"/>`,
    },
    control: {
        titleKey: 'control', subtitleKey: 'control_sub', color: '#96CAEE',
        icon: () => svg`
            <line x1="-12" y1="-12" x2="-12" y2="12" stroke-width="2"/>
            <line x1="0" y1="-12" x2="0" y2="12" stroke-width="2"/>
            <line x1="12" y1="-12" x2="12" y2="12" stroke-width="2"/>
            <circle cx="-12" cy="-4" r="4" fill="currentColor" opacity="0.6" stroke="none"/>
            <circle cx="0" cy="4" r="4" fill="currentColor" opacity="0.6" stroke="none"/>
            <circle cx="12" cy="-8" r="4" fill="currentColor" opacity="0.6" stroke="none"/>`,
    },
    config: {
        titleKey: 'config_tab_title', subtitleKey: 'config_tab_subtitle', color: '#8DC892',
        icon: () => svg`
            <circle cx="0" cy="0" r="6" stroke-width="2"/>
            <g stroke-width="2" stroke-linecap="round">
                <line x1="0" y1="-16" x2="0" y2="-10"/>
                <line x1="0" y1="10" x2="0" y2="16"/>
                <line x1="-16" y1="0" x2="-10" y2="0"/>
                <line x1="10" y1="0" x2="16" y2="0"/>
                <line x1="-11" y1="-11" x2="-7" y2="-7"/>
                <line x1="7" y1="7" x2="11" y2="11"/>
                <line x1="11" y1="-11" x2="7" y2="-7"/>
                <line x1="-7" y1="7" x2="-11" y2="11"/>
            </g>`,
    },
    costs: {
        titleKey: 'costs', subtitleKey: 'costs_sub', color: '#f06292',
        icon: () => svg`
            <circle cx="0" cy="0" r="16" stroke-width="2"/>
            <text x="0" y="6" text-anchor="middle" font-size="18" font-weight="700"
                  fill="currentColor" opacity="0.7" stroke="none"
                  font-family="'Segoe UI','Roboto',sans-serif">$</text>`,
    },
    system: {
        titleKey: 'system', subtitleKey: 'system_sub', color: '#96CAEE',
        icon: () => svg`
            <path d="M-16,4 L-8,-8 L0,0 L6,-12 L10,-4 L16,4" stroke-width="2" fill="none"/>
            <line x1="-16" y1="8" x2="16" y2="8" stroke-width="1" opacity="0.3"/>`,
    },
    // #1083 — shown only while the Simulation tab switch is on (the
    // generator drops the view otherwise). Flask, like mdi:flask-outline.
    simulation: {
        titleKey: 'simulation', subtitleKey: 'simulation_sub', color: '#8353d1',
        icon: () => svg`
            <path d="M-5,-15 L5,-15 M-4,-15 L-4,-4 L-14,13 Q-15,16 -11,16 L11,16 Q15,16 14,13 L4,-4 L4,-15" stroke-width="2"/>
            <line x1="-9" y1="6" x2="9" y2="6" stroke-width="1.5" opacity="0.6"/>`,
    },
};

class SEMTabHeader extends SEMLitBase {
    static get watchedEntities() {
        // Dynamic — depends on tab config. We handle this in the hass setter.
        return [];
    }

    constructor() {
        super();
        this._tab = 'home';
        this._prefix = 'sensor.sem_';
        this._responsiveApplied = false;
        this._lastStatsKey = '';
    }

    connectedCallback() {
        super.connectedCallback();
        this._applyResponsiveContainer();
    }

    _applyResponsiveContainer() {
        if (this._responsiveApplied) return;
        requestAnimationFrame(() => {
            let el = this;
            while (el) {
                const host = el.getRootNode()?.host;
                if (!host) break;
                if (host.tagName === 'HUI-VERTICAL-STACK-CARD') {
                    const huiCard = host.parentElement;
                    if (huiCard && huiCard.tagName === 'HUI-CARD') {
                        huiCard.style.maxWidth = '900px';
                        huiCard.style.margin = '0 auto';
                        huiCard.style.display = 'block';
                        this._responsiveApplied = true;
                        return;
                    }
                }
                el = host;
            }
        });
    }

    setConfig(config) {
        super.setConfig(config);
        this._tab = config.tab || 'home';
        this._prefix = config.entity_prefix || 'sensor.sem_';
    }

    set hass(hass) {
        const old = this._hass;
        this._hass = hass;

        // Locale change
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

        // Stats key check — only re-render when relevant entities change
        const statsKey = this._buildStatsKey(hass);
        if (statsKey !== this._lastStatsKey || localeChanged) {
            this._lastStatsKey = statsKey;
            this.requestUpdate();
        }

        if (!this._responsiveApplied) this._applyResponsiveContainer();
    }

    // (#1198, class 127) The key is the text the header shows, so no figure
    // can be left out of it. The old hand-made list missed the EV tab's
    // session and the Config tab's SOC, and those figures stood still.
    _buildStatsKey(hass) {
        if (!hass) return '';
        if (this._tab === 'home') return this._heroValues().join('|');
        return this._getStatValues().join('|');
    }

    // (#1198) null when the sensor is out: unavailable, unknown, missing or
    // not a number. There is no fallback on purpose; `fig` prints the dash.
    _getState(suffix) {
        const e = this._hass?.states[`${this._prefix}${suffix}`];
        return isMissing(e) ? null : parseFloat(e.state);
    }

    _getStatLabels() {
        const t = (k) => _t(k, this._hass);
        const tab = this._tab;
        if (tab === 'energy') return [t('solar'), t('home'), t('self_use')];
        if (tab === 'battery') return [t('soc'), t('power'), t('health')];
        if (tab === 'ev') return [t('power'), t('today'), t('session')];
        if (tab === 'control') return [t('peak'), t('devices'), t('active')];
        if (tab === 'config') return [t('config_stat_chargers'), t('config_stat_heatpump'), t('config_stat_battery')];
        if (tab === 'costs') return [t('cost'), t('saved'), t('net')];
        if (tab === 'system') return [t('score'), t('saved'), t('co2')];
        if (tab === 'simulation') return [t('simulation_days_stored'), t('simulation_selected'), t('simulation_gaps')];
        return ['—', '—', '—'];
    }

    _getStatValues() {
        const tab = this._tab;
        const _c = semGetCurrency(this._hass) || 'EUR';
        const money = (d) => (v) => v.toFixed(d) + ' ' + _c;
        // The Home tab shows its hero, not these figures (`_heroValues`).
        if (tab === 'energy') return [
            fig(this._getState('daily_solar_energy'), kwh),
            fig(this._getState('daily_home_energy'), kwh),
            fig(this._getState('self_consumption_rate'), pct),
        ];
        if (tab === 'battery') return [
            socDisplay(this._getState('battery_soc')).label,
            fig(this._getState('battery_power'), semFormatPower),
            fig(this._getState('battery_health_score'), pct),
        ];
        if (tab === 'ev') return [
            fig(this._getState('ev_power'), semFormatPower),
            fig(this._getState('daily_ev_energy'), kwh),
            fig(this._getState('session_energy'), kwh),
        ];
        if (tab === 'control') return [
            peakLimitText(this._hass?.states[`${this._prefix}target_peak_limit`],
                _t(PEAK_TEXT.none, this._hass)),
            fig(this._getState('controllable_devices_count'), (v) => v.toFixed(0)),
            fig(this._getState('surplus_active_devices'), (v) => v.toFixed(0)),
        ];
        if (tab === 'config') {
            const t = (k) => _t(k, this._hass);
            // The key reads this on every hass update: test the cheap prefix first.
            const chargers = Object.keys(this._hass?.states || {})
                .filter(e => e.startsWith('number.sem_charger_')
                    && /^number\.sem_charger_.+_minimum_current$/.test(e)).length;
            // (#1198) A binary sensor (#437), so not under the sensor. prefix:
            // read there, this always said Off. No entity means no heat pump
            // module, so Off; an entity that is out is the dash.
            const hpState = this._hass?.states[
                this._prefix.replace(/^sensor\./, 'binary_sensor.') + 'heat_pump_registered']?.state;
            return [
                String(chargers),
                hpState === 'on' ? t('on')
                    : (hpState === undefined || hpState === 'off') ? t('off') : MISSING,
                socDisplay(this._getState('battery_soc')).label,
            ];
        }
        if (tab === 'costs') return [
            fig(this._getState('daily_costs'), money(2)),
            fig(this._getState('daily_savings'), money(2)),
            // #554 — savings-positive framing, consistent with the costs card
            fig(this._getState('daily_net_cost'),
                (n) => (n <= 0 ? '+' : '') + Math.abs(n).toFixed(2) + ' ' + _c),
        ];
        if (tab === 'system') return [
            fig(this._getState('energy_optimization_score'), (v) => v.toFixed(0)),
            fig(this._getState('lifetime_total_savings'), money(0)),
            fig(this._getState('lifetime_co2_avoided'),
                (v) => v.toFixed(0) + ' ' + this._kgUnit('lifetime_co2_avoided')),
        ];
        return [MISSING, MISSING, MISSING];
    }

    // Today's solar energy and the solar power now; null when out.
    _heroValues() {
        return [this._getState('daily_solar_energy'), this._getState('solar_power')];
    }

    _renderHomeHero() {
        const [today, power] = this._heroValues();
        return html`
            <div class="hero">
                <div class="hero-main">
                    <div class="hero-value">${today == null ? MISSING
                        : html`${today.toFixed(1)}<span class="unit">kWh</span>`}</div>
                    <div class="hero-label">${_t('todays_solar_production', this._hass)}</div>
                </div>
                ${power > 0 ? html`
                <div class="hero-now">
                    <ha-icon icon="mdi:white-balance-sunny"></ha-icon>
                    <span>${semFormatPower(power)}</span>
                </div>` : nothing}
            </div>`;
    }

    render() {
        if (!this._hass || !this._config) return nothing;

        const cfg = SEM_TAB_CONFIG[this._tab] || SEM_TAB_CONFIG.home;
        const title = this._config.title || _t(cfg.titleKey, this._hass);
        const subtitle = this._config.subtitle || _t(cfg.subtitleKey, this._hass);
        const color = cfg.color;
        const labels = this._getStatLabels();
        const values = this._getStatValues();
        const T = this._theme();

        // Accent colours (cyan/lime/etc.) wash out on light HA themes. Darken
        // the title via color-mix in light mode and drop the colored
        // text-shadow that adds noise without contrast.
        const titleColor = T.isDark
            ? color
            : `color-mix(in srgb, ${color} 65%, black)`;
        const titleShadow = T.isDark ? `0 0 12px ${color}40` : 'none';
        // Glow ring is barely visible on dark and overpowering on light.
        // Halve the flood opacity for light themes.
        const glowOpacity = T.isDark ? 0.30 : 0.18;

        return html`
            <style>
                :host { display: block; }
                .header-wrap {
                    display: flex; align-items: center; gap: 16px;
                    padding: 16px 20px; position: relative; overflow: hidden;
                    background:
                        radial-gradient(ellipse 80% 70% at 20% 50%, ${color}0D 0%, transparent 70%),
                        radial-gradient(circle at 2px 2px, ${T.dotColor} 0.7px, transparent 0.7px);
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                }
                .icon-ring { position: relative; flex-shrink: 0; width: 64px; height: 64px; }
                .icon-ring svg { width: 100%; height: 100%; }
                /* min-width keeps the title readable next to the stats;
                   when there isn't room for both, the stats wrap below
                   instead of crushing the title to zero width. */
                .title-area { flex: 1 1 auto; min-width: 140px; }
                .tab-title {
                    font-size: 20px; font-weight: 700; color: ${titleColor};
                    letter-spacing: 0.5px; text-shadow: ${titleShadow};
                    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
                }
                .tab-subtitle {
                    font-size: 12px; color: var(--secondary-text-color, ${T.textSec});
                    margin-top: 2px; font-weight: 500;
                    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
                }
                .stats { display: flex; gap: 16px; flex-shrink: 0; }
                .stat { text-align: center; min-width: 50px; }
                .stat-value {
                    font-size: 15px; font-weight: 700; font-variant-numeric: tabular-nums;
                    color: var(--primary-text-color, ${T.text});
                }
                .stat-label {
                    font-size: 11px; color: var(--secondary-text-color, ${T.textTertiary});
                    font-weight: 500; margin-top: 1px;
                }
                /* Home hero — Today's production merged from the KPI card
                   (maintainer UI review: chips duplicated the KPI below) */
                .hero { display: flex; align-items: center; gap: 14px; flex-shrink: 0; }
                .hero-main { text-align: left; }
                .hero-value {
                    font-size: 26px; font-weight: 700; line-height: 1.05;
                    color: #ff9800; letter-spacing: -0.5px;
                    font-variant-numeric: tabular-nums; white-space: nowrap;
                }
                .hero-value .unit { font-size: 14px; font-weight: 500; opacity: 0.85; margin-left: 3px; }
                .hero-label {
                    font-size: 10px; text-transform: uppercase; letter-spacing: 0.5px;
                    color: var(--secondary-text-color, ${T.textTertiary});
                    margin-top: 2px;
                }
                .hero-now {
                    display: flex; align-items: center; gap: 5px;
                    padding: 5px 10px; border-radius: 999px;
                    background: var(--secondary-background-color, rgba(255,255,255,0.06));
                    font-size: 12px; color: var(--primary-text-color, ${T.text});
                    white-space: nowrap;
                }
                .hero-now ha-icon { color: #ff9800; --mdc-icon-size: 14px; }
                @media (max-width: 500px) {
                    .hero-value { font-size: 21px; }
                }
                @media (max-width: 500px) {
                    .header-wrap { padding: 12px 14px; gap: 8px 12px; flex-wrap: wrap; }
                    .icon-ring { width: 48px; height: 48px; }
                    .tab-title { font-size: 16px; }
                    .stats { gap: 10px; }
                    .stat-value { font-size: 13px; }
                }
            </style>
            <ha-card>
                <div class="header-wrap">
                    <div class="icon-ring">
                        <svg viewBox="-34 -34 68 68" xmlns="http://www.w3.org/2000/svg">
                            <defs>
                                <filter id="glow-${this._tab}" x="-40%" y="-40%" width="180%" height="180%">
                                    <feGaussianBlur stdDeviation="4" result="blur"/>
                                    <feFlood flood-color="${color}" flood-opacity="${glowOpacity}"/>
                                    <feComposite in2="blur" operator="in"/>
                                    <feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge>
                                </filter>
                            </defs>
                            <circle r="28" fill="none" stroke="${color}" stroke-width="1.2" opacity="0.25">
                                <animate attributeName="r" values="28;31;28" dur="3s" repeatCount="indefinite"/>
                                <animate attributeName="opacity" values="0.25;0.10;0.25" dur="3s" repeatCount="indefinite"/>
                            </circle>
                            <circle r="24" fill="${color}0F" stroke="${color}" stroke-width="1.5" filter="url(#glow-${this._tab})"/>
                            <g stroke="${color}" fill="none" opacity="0.75" stroke-linecap="round" stroke-linejoin="round">
                                ${cfg.icon()}
                            </g>
                        </svg>
                    </div>
                    <div class="title-area">
                        <div class="tab-title">${title}</div>
                        <div class="tab-subtitle">${subtitle}</div>
                    </div>
                    ${this._tab === 'home' ? this._renderHomeHero() : html`
                    <div class="stats">
                        ${labels.map((label, i) => html`
                            <div class="stat">
                                <div class="stat-value">${values[i]}</div>
                                <div class="stat-label">${label}</div>
                            </div>
                        `)}
                    </div>`}
                </div>
            </ha-card>
        `;
    }

    getCardSize() { return 1; }
    static getStubConfig() { return { tab: 'home' }; }
}

semDefineCard('sem-tab-header', SEMTabHeader, {
    type: 'sem-tab-header',
    name: 'SEM Tab Header',
    description: 'Lumina-styled tab header with glow icon and live stats',
    documentationURL:
        'https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-tab-header',
});

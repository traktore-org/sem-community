/**
 * SEM Tab Header Card — Lumina-styled section header with glow icon
 *
 * Placed at the top of each dashboard tab. Shows a custom SVG icon
 * with glow ring, tab title, subtitle, and live stats.
 */

import { SEMLitBase, html, css, svg, nothing } from '../base/sem-lit-base.js';
import { semTheme, semFormatPower, semGetCurrency, semDefineCard } from '../base/sem-shared.js';

const _t = (key, hass) => (typeof semLocalize === 'function') ? semLocalize(key, hass?.language) : key;

// Icon templates use Lit's `svg` tag so child elements are created in the SVG
// namespace. With plain `html` they get the HTML namespace, render as
// HTMLUnknownElement, and show up blank inside the icon ring.
const SEM_TAB_CONFIG = {
    home: {
        titleKey: 'home', subtitleKey: 'home_sub', color: '#5BC8D8',
        icon: () => svg`
            <path d="M-20,2 L0,-16 L20,2" stroke-width="2.2"/>
            <rect x="-15" y="2" width="30" height="22" rx="2" stroke-width="2"/>
            <rect x="-5" y="12" width="10" height="12" stroke-width="1.5"/>`,
    },
    energy: {
        titleKey: 'energy', subtitleKey: 'energy_sub', color: '#ff9800',
        icon: () => svg`
            <path d="M-4,-18 L-10,2 L-2,2 L-6,18 L12,-4 L2,-4 L8,-18 Z" stroke-width="1.8"/>`,
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
            <path d="M-3,-6 L-1,0 L-5,0 L3,8" stroke-width="2.2" fill="none"/>
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
            <path d="M-16,4 L-8,-8 L0,0 L6,-12 L10,-4 L16,4" stroke-width="2.2" fill="none"/>
            <line x1="-16" y1="8" x2="16" y2="8" stroke-width="1" opacity="0.3"/>`,
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

    _buildStatsKey(hass) {
        if (!hass) return '';
        const g = (s) => hass.states[`${this._prefix}${s}`]?.state || '';
        const tab = this._tab;
        if (tab === 'home') return [g('solar_power'), g('autarky_rate'), g('daily_solar_energy')].join(',');
        if (tab === 'energy') return [g('daily_solar_energy'), g('daily_home_energy'), g('self_consumption_rate')].join(',');
        if (tab === 'battery') return [g('battery_soc'), g('battery_power'), g('battery_health')].join(',');
        if (tab === 'ev') return [g('ev_power'), g('daily_ev_energy'), g('charging_state')].join(',');
        if (tab === 'control') return [g('target_peak_limit'), g('controllable_devices_count'), g('surplus_active_devices')].join(',');
        if (tab === 'costs') return [g('daily_costs'), g('daily_savings'), g('daily_net_cost')].join(',');
        if (tab === 'system') return [g('energy_optimization_score'), g('lifetime_total_savings'), g('lifetime_co2_avoided')].join(',');
        return '';
    }

    _getState(suffix, fallback = 0) {
        const e = this._hass?.states[`${this._prefix}${suffix}`];
        if (!e || e.state === 'unavailable' || e.state === 'unknown') return fallback;
        return parseFloat(e.state) || fallback;
    }

    _getStatLabels() {
        const t = (k) => _t(k, this._hass);
        const tab = this._tab;
        if (tab === 'home') return [t('solar'), t('autarky'), t('today')];
        if (tab === 'energy') return [t('solar'), t('home'), t('self_use')];
        if (tab === 'battery') return [t('soc'), t('power'), t('health')];
        if (tab === 'ev') return [t('power'), t('today'), t('session')];
        if (tab === 'control') return [t('peak'), t('devices'), t('active')];
        if (tab === 'costs') return [t('cost'), t('saved'), t('net')];
        if (tab === 'system') return [t('score'), t('saved'), t('co2')];
        return ['—', '—', '—'];
    }

    _getStatValues() {
        const tab = this._tab;
        const _c = semGetCurrency(this._hass) || 'EUR';
        if (tab === 'home') return [
            semFormatPower(this._getState('solar_power', 0)),
            this._getState('autarky_rate', 0).toFixed(0) + '%',
            this._getState('daily_solar_energy', 0).toFixed(1) + ' kWh',
        ];
        if (tab === 'energy') return [
            this._getState('daily_solar_energy', 0).toFixed(1) + ' kWh',
            this._getState('daily_home_energy', 0).toFixed(1) + ' kWh',
            this._getState('self_consumption_rate', 0).toFixed(0) + '%',
        ];
        if (tab === 'battery') return [
            this._getState('battery_soc', 0).toFixed(0) + '%',
            semFormatPower(this._getState('battery_power', 0)),
            this._getState('battery_health_score', 100).toFixed(0) + '%',
        ];
        if (tab === 'ev') return [
            semFormatPower(this._getState('ev_power', 0)),
            this._getState('daily_ev_energy', 0).toFixed(1) + ' kWh',
            this._getState('session_energy', 0).toFixed(1) + ' kWh',
        ];
        if (tab === 'control') return [
            this._getState('target_peak_limit', 5).toFixed(1) + ' kW',
            this._getState('controllable_devices_count', 0).toFixed(0),
            this._getState('surplus_active_devices', 0).toFixed(0),
        ];
        if (tab === 'costs') return [
            this._getState('daily_costs', 0).toFixed(2) + ' ' + _c,
            this._getState('daily_savings', 0).toFixed(2) + ' ' + _c,
            this._getState('daily_net_cost', 0).toFixed(2) + ' ' + _c,
        ];
        if (tab === 'system') return [
            this._getState('energy_optimization_score', 0).toFixed(0),
            this._getState('lifetime_savings', 0).toFixed(0) + ' ' + _c,
            this._getState('lifetime_co2_avoided', 0).toFixed(0) + ' kg',
        ];
        return ['—', '—', '—'];
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
                .title-area { flex: 1; min-width: 0; }
                .tab-title {
                    font-size: 20px; font-weight: 700; color: ${color};
                    letter-spacing: 0.5px; text-shadow: 0 0 12px ${color}40;
                }
                .tab-subtitle {
                    font-size: 12px; color: var(--secondary-text-color, ${T.textSec});
                    margin-top: 2px; font-weight: 500;
                }
                .stats { display: flex; gap: 16px; flex-shrink: 0; }
                .stat { text-align: center; min-width: 50px; }
                .stat-value {
                    font-size: 15px; font-weight: 700; font-variant-numeric: tabular-nums;
                    color: var(--primary-text-color, ${T.text});
                }
                .stat-label {
                    font-size: 10px; color: var(--secondary-text-color, ${T.textTertiary});
                    font-weight: 500; margin-top: 1px;
                }
                @media (max-width: 500px) {
                    .header-wrap { padding: 12px 14px; gap: 12px; }
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
                                    <feFlood flood-color="${color}" flood-opacity="0.3"/>
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
                    <div class="stats">
                        ${labels.map((label, i) => html`
                            <div class="stat">
                                <div class="stat-value">${values[i]}</div>
                                <div class="stat-label">${label}</div>
                            </div>
                        `)}
                    </div>
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
});

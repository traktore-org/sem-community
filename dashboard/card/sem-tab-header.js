/**
 * SEM Tab Header Card — Lumina-styled section header with glow icon
 *
 * Placed at the top of each dashboard tab to establish the Lumina
 * visual identity. Shows a custom SVG icon with glow ring, tab title,
 * subtitle, and dot-grid background.
 *
 * Config:
 *   type: custom:sem-tab-header
 *   tab: home | energy | battery | ev | control | costs | system
 *   title: "Home"             # optional override
 *   subtitle: "Solar overview" # optional override
 *   entity_prefix: sensor.sem_ # default
 */

// Localization helper — uses sem-localize.js if loaded
// Fallback table for when sem-localize.js hasn't loaded yet
const _FALLBACK = {
    home: 'Home', energy: 'Energy', battery: 'Battery', ev_charging: 'EV Charging',
    control: 'Control', costs: 'Costs', system: 'System',
    home_sub: 'Energy overview', energy_sub: 'Production & consumption',
    battery_sub: 'Storage & health', ev_sub: 'Vehicle & sessions',
    control_sub: 'Devices & scheduling', costs_sub: 'Savings & tariffs',
    system_sub: 'Health & diagnostics',
    solar: 'Solar', autarky: 'Autarky', today: 'Today', soc: 'SOC',
    power: 'Power', health: 'Health', session: 'Session', peak: 'Peak',
    devices: 'Devices', active: 'Active', cost: 'Cost', saved: 'Saved',
    net: 'Net', score: 'Score', co2: 'CO₂', self_use: 'Self-use',
};
const _t = (key, hass) => (typeof semLocalize === 'function') ? semLocalize(key, hass?.language) : (_FALLBACK[key] || key);

const SEM_TAB_CONFIG = {
    home: {
        titleKey: 'home',
        subtitleKey: 'home_sub',
        color: '#5BC8D8',
        icon: (s) => `
            <path d="M-20,2 L0,-16 L20,2" stroke-width="2.2"/>
            <rect x="-15" y="2" width="30" height="22" rx="2" stroke-width="2"/>
            <rect x="-5" y="12" width="10" height="12" stroke-width="1.5"/>`,
    },
    energy: {
        titleKey: 'energy',
        subtitleKey: 'energy_sub',
        color: '#ff9800',
        icon: (s) => `
            <path d="M-4,-18 L-10,2 L-2,2 L-6,18 L12,-4 L2,-4 L8,-18 Z" stroke-width="1.8"/>`,
    },
    battery: {
        titleKey: 'battery',
        subtitleKey: 'battery_sub',
        color: '#4db6ac',
        icon: (s) => `
            <rect x="-10" y="-16" width="20" height="32" rx="4" stroke-width="2"/>
            <rect x="-4" y="-20" width="8" height="5" rx="2" fill="currentColor" opacity="0.4" stroke="none"/>
            <line x1="-5" y1="-4" x2="5" y2="-4" stroke-width="1.5" opacity="0.5"/>
            <line x1="-5" y1="4" x2="5" y2="4" stroke-width="1.5" opacity="0.5"/>`,
    },
    ev: {
        titleKey: 'ev_charging',
        subtitleKey: 'ev_sub',
        color: '#8DC892',
        icon: (s) => `
            <rect x="-12" y="-14" width="24" height="24" rx="5" stroke-width="2"/>
            <path d="M-3,-6 L-1,0 L-5,0 L3,8" stroke-width="2.2" fill="none"/>
            <line x1="0" y1="10" x2="0" y2="16" stroke-width="2"/>
            <circle cx="0" cy="18" r="2" fill="currentColor" opacity="0.4" stroke="none"/>`,
    },
    control: {
        titleKey: 'control',
        subtitleKey: 'control_sub',
        color: '#96CAEE',
        icon: (s) => `
            <line x1="-12" y1="-12" x2="-12" y2="12" stroke-width="2"/>
            <line x1="0" y1="-12" x2="0" y2="12" stroke-width="2"/>
            <line x1="12" y1="-12" x2="12" y2="12" stroke-width="2"/>
            <circle cx="-12" cy="-4" r="4" fill="currentColor" opacity="0.6" stroke="none"/>
            <circle cx="0" cy="4" r="4" fill="currentColor" opacity="0.6" stroke="none"/>
            <circle cx="12" cy="-8" r="4" fill="currentColor" opacity="0.6" stroke="none"/>`,
    },
    costs: {
        titleKey: 'costs',
        subtitleKey: 'costs_sub',
        color: '#f06292',
        icon: (s) => `
            <circle cx="0" cy="0" r="16" stroke-width="2"/>
            <text x="0" y="6" text-anchor="middle" font-size="18" font-weight="700"
                  fill="currentColor" opacity="0.7" stroke="none"
                  font-family="'Segoe UI','Roboto',sans-serif">$</text>`,
    },
    system: {
        titleKey: 'system',
        subtitleKey: 'system_sub',
        color: '#96CAEE',
        icon: (s) => `
            <path d="M-16,4 L-8,-8 L0,0 L6,-12 L10,-4 L16,4" stroke-width="2.2" fill="none"/>
            <line x1="-16" y1="8" x2="16" y2="8" stroke-width="1" opacity="0.3"/>`,
    },
};

class SEMTabHeader extends HTMLElement {
    constructor() {
        super();
        this.attachShadow({ mode: 'open' });
        this._rendered = false;
    }

    setConfig(config) {
        this.config = config;
        this._tab = config.tab || 'home';
        this._prefix = config.entity_prefix || 'sensor.sem_';
    }

    set hass(hass) {
        this._hass = hass;
        // Re-render when sem-localize.js finishes loading (it may race with
        // the first hass assignment) or when the user's language changes —
        // otherwise English fallback labels would stick forever.
        const hasLocalize = typeof semLocalize === 'function';
        const lang = hass?.language;
        if (
            !this._rendered
            || this._renderedLang !== lang
            || (hasLocalize && !this._renderedWithLocalize)
        ) {
            this._render();
            this._rendered = true;
            this._renderedLang = lang;
            this._renderedWithLocalize = hasLocalize;
        }
        this._updateStats();
    }

    _getState(suffix, fallback) {
        const e = this._hass?.states[`${this._prefix}${suffix}`];
        if (!e || e.state === 'unavailable' || e.state === 'unknown') return fallback;
        return parseFloat(e.state) || fallback;
    }

    _fmtPower(w) {
        if (w == null || isNaN(w)) return '—';
        const abs = Math.abs(w);
        if (abs >= 1000) return (w / 1000).toFixed(1) + ' kW';
        return Math.round(w) + ' W';
    }

    _updateStats() {
        if (!this._hass) return;
        const root = this.shadowRoot;
        const stat1 = root.getElementById('stat1');
        const stat2 = root.getElementById('stat2');
        const stat3 = root.getElementById('stat3');
        if (!stat1) return;

        const tab = this._tab;
        if (tab === 'home') {
            stat1.textContent = this._fmtPower(this._getState('solar_power', 0));
            stat2.textContent = this._getState('autarky_rate', 0).toFixed(0) + '%';
            stat3.textContent = this._getState('daily_solar_energy', 0).toFixed(1) + ' kWh';
        } else if (tab === 'energy') {
            stat1.textContent = this._getState('daily_solar_energy', 0).toFixed(1) + ' kWh';
            stat2.textContent = this._getState('daily_home_energy', 0).toFixed(1) + ' kWh';
            stat3.textContent = this._getState('self_consumption_rate', 0).toFixed(0) + '%';
        } else if (tab === 'battery') {
            stat1.textContent = this._getState('battery_soc', 0).toFixed(0) + '%';
            stat2.textContent = this._fmtPower(this._getState('battery_power', 0));
            stat3.textContent = this._getState('battery_health_score', 100).toFixed(0) + '%';
        } else if (tab === 'ev') {
            stat1.textContent = this._fmtPower(this._getState('ev_power', 0));
            stat2.textContent = this._getState('daily_ev_energy', 0).toFixed(1) + ' kWh';
            stat3.textContent = this._getState('session_energy', 0).toFixed(1) + ' kWh';
        } else if (tab === 'control') {
            stat1.textContent = this._getState('target_peak_limit', 5).toFixed(1) + ' kW';
            stat2.textContent = this._getState('controllable_devices_count', 0).toFixed(0);
            stat3.textContent = this._getState('surplus_active_devices', 0).toFixed(0);
        } else if (tab === 'costs') {
            const _c = window.semGetCurrency?.(this._hass) || 'EUR';
            stat1.textContent = this._getState('daily_costs', 0).toFixed(2) + ' ' + _c;
            stat2.textContent = this._getState('daily_savings', 0).toFixed(2) + ' ' + _c;
            stat3.textContent = this._getState('daily_net_cost', 0).toFixed(2) + ' ' + _c;
        } else if (tab === 'system') {
            stat1.textContent = this._getState('energy_optimization_score', 0).toFixed(0);
            stat2.textContent = this._getState('lifetime_savings', 0).toFixed(0) + ' ' + (window.semGetCurrency?.(this._hass) || 'EUR');
            stat3.textContent = this._getState('lifetime_co2_avoided', 0).toFixed(0) + ' kg';
        }
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

    _render() {
        const cfg = SEM_TAB_CONFIG[this._tab] || SEM_TAB_CONFIG.home;
        const title = this.config.title || _t(cfg.titleKey, this._hass);
        const subtitle = this.config.subtitle || _t(cfg.subtitleKey, this._hass);
        const color = cfg.color;
        const labels = this._getStatLabels();
        const F = "'Segoe UI','Roboto',sans-serif";

        this.shadowRoot.innerHTML = `
            <style>
                :host { display: block; }
                .header-wrap {
                    display: flex;
                    align-items: center;
                    gap: 16px;
                    padding: 16px 20px;
                    position: relative;
                    overflow: hidden;
                    background:
                        radial-gradient(ellipse 80% 70% at 20% 50%, ${color}0D 0%, transparent 70%),
                        radial-gradient(circle at 2px 2px, rgba(128,128,128,0.05) 0.7px, transparent 0.7px);
                    background-size: 100% 100%, 50px 50px;
                    font-family: ${F};
                }
                .icon-ring {
                    position: relative;
                    flex-shrink: 0;
                    width: 64px;
                    height: 64px;
                }
                .icon-ring svg {
                    width: 100%;
                    height: 100%;
                }
                .title-area {
                    flex: 1;
                    min-width: 0;
                }
                .tab-title {
                    font-size: 20px;
                    font-weight: 700;
                    color: ${color};
                    letter-spacing: 0.5px;
                    text-shadow: 0 0 12px ${color}40;
                }
                .tab-subtitle {
                    font-size: 12px;
                    color: #888;
                    margin-top: 2px;
                    font-weight: 500;
                }
                .stats {
                    display: flex;
                    gap: 16px;
                    flex-shrink: 0;
                }
                .stat {
                    text-align: center;
                    min-width: 50px;
                }
                .stat-value {
                    font-size: 15px;
                    font-weight: 700;
                    font-variant-numeric: tabular-nums;
                    color: #e0e0e0;
                }
                .stat-label {
                    font-size: 10px;
                    color: #777;
                    font-weight: 500;
                    margin-top: 1px;
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
                            <!-- Glow ring -->
                            <circle r="28" fill="none" stroke="${color}" stroke-width="1.2" opacity="0.25">
                                <animate attributeName="r" values="28;31;28" dur="3s" repeatCount="indefinite"/>
                                <animate attributeName="opacity" values="0.25;0.10;0.25" dur="3s" repeatCount="indefinite"/>
                            </circle>
                            <!-- Node circle -->
                            <circle r="24" fill="${color}0F" stroke="${color}" stroke-width="1.5" filter="url(#glow-${this._tab})"/>
                            <!-- Icon -->
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
                        <div class="stat">
                            <div class="stat-value" id="stat1">—</div>
                            <div class="stat-label">${labels[0]}</div>
                        </div>
                        <div class="stat">
                            <div class="stat-value" id="stat2">—</div>
                            <div class="stat-label">${labels[1]}</div>
                        </div>
                        <div class="stat">
                            <div class="stat-value" id="stat3">—</div>
                            <div class="stat-label">${labels[2]}</div>
                        </div>
                    </div>
                </div>
            </ha-card>
        `;
    }

    getCardSize() { return 1; }
    static getStubConfig() { return { tab: 'home' }; }
}

customElements.define('sem-tab-header', SEMTabHeader);

window.customCards = window.customCards || [];
window.customCards.push({
    type: 'sem-tab-header',
    name: 'SEM Tab Header',
    description: 'Lumina-styled tab header with glow icon and live stats',
});

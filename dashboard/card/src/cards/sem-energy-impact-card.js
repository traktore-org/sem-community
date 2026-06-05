/**
 * SEM Energy Impact Card — Environmental impact display (LitElement)
 *
 * Displays two tiles:
 *   - Carbon Avoided Today (with kWh × g/kWh calculation breakdown)
 *   - Trees Equivalent (yearly count + yearly/lifetime CO2 and tree stats)
 *
 * Config:
 *   type: custom:sem-energy-impact-card
 *   entity_prefix: sensor.sem_   # optional, defaults to 'sensor.sem_'
 */

import { SEMLitBase, html, css, nothing } from '../base/sem-lit-base.js';
import { semTheme, semDefineCard } from '../base/sem-shared.js';

const DEFAULT_PREFIX = 'sensor.sem_';

const ENTITY_SUFFIXES = [
    'flow_solar_to_home_energy',
    'flow_solar_to_ev_energy',
    'daily_co2_avoided',
    'yearly_co2_avoided',
    'lifetime_co2_avoided',
    'yearly_trees_equivalent',
    'lifetime_trees_equivalent',
];

/** Build full entity IDs from a prefix. */
function buildEntityIds(prefix) {
    return ENTITY_SUFFIXES.map(s => `${prefix}${s}`);
}

class SEMEnergyImpactCard extends SEMLitBase {
    static get watchedEntities() {
        return buildEntityIds(DEFAULT_PREFIX);
    }

    setConfig(config) {
        super.setConfig(config);
        this._prefix = config.entity_prefix || DEFAULT_PREFIX;

        // If user configured a non-default prefix, update _prevVals keys so
        // the base class hass setter tracks the right entities.
        if (this._prefix !== DEFAULT_PREFIX) {
            this._prevVals = {};
        }
    }

    // ── Override hass setter to watch configurable-prefix entities ──
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

        if (this._isFrozen() && !localeChanged) return;

        const ids = buildEntityIds(this._prefix || DEFAULT_PREFIX);
        let changed = false;
        for (const id of ids) {
            if (this._prevVals[id] !== hass.states[id]?.state) {
                changed = true;
                break;
            }
        }
        if (!changed && !localeChanged) return;

        for (const id of ids) {
            this._prevVals[id] = hass.states[id]?.state;
        }

        this._scheduleUpdate();
    }

    get hass() {
        return this._hass;
    }

    // ── Helpers ──

    /** Read a numeric entity state by suffix (prepends configured prefix). */
    _val(suffix, fallback = 0) {
        return this._state(`${this._prefix || DEFAULT_PREFIX}${suffix}`, fallback);
    }

    _treeIcon(count) {
        if (count >= 50) return 'mdi:forest';
        if (count >= 10) return 'mdi:pine-tree';
        if (count >= 1)  return 'mdi:tree';
        return 'mdi:sprout';
    }

    // ── Render ──

    render() {
        if (!this._config) return nothing;

        const T = this._theme();

        // CO2 calculation from self-consumed solar energy
        const solarHome = this._val('flow_solar_to_home_energy');
        const solarEV   = this._val('flow_solar_to_ev_energy');
        const selfConsumed = solarHome + solarEV;
        const co2Today     = (selfConsumed * 0.128).toFixed(1);
        const co2Detail    = `${selfConsumed.toFixed(1)} kWh × 128 g/kWh`;

        // Trees equivalent
        const yearlyTrees   = this._val('yearly_trees_equivalent');
        const lifetimeTrees = this._val('lifetime_trees_equivalent');
        const yearlyCO2     = this._val('yearly_co2_avoided');
        const lifetimeCO2   = this._val('lifetime_co2_avoided');

        const treesDisplay = yearlyTrees >= 10
            ? yearlyTrees.toFixed(0)
            : yearlyTrees.toFixed(1);

        const treeIcon = this._treeIcon(yearlyTrees);

        return html`
            <style>
                :host { display: block; }

                .wrap {
                    padding: 16px;
                    background:
                        radial-gradient(ellipse 70% 60% at 50% 25%, rgba(255,152,0,0.06) 0%, transparent 100%),
                        radial-gradient(circle at 2px 2px, ${T.dotColor} 0.7px, transparent 0.7px);
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI', 'Roboto', sans-serif;
                    color: var(--primary-text-color, ${T.text});
                }

                .tiles {
                    display: grid;
                    grid-template-columns: 1fr 1fr;
                    gap: 12px;
                }

                .tile {
                    display: flex;
                    align-items: flex-start;
                    gap: 10px;
                    padding: 14px;
                    border-radius: 12px;
                    background: ${T.surface};
                    border: 1px solid ${T.surfaceBorder};
                }

                .tile ha-icon {
                    flex-shrink: 0;
                    margin-top: 2px;
                }

                .tile-content {
                    display: flex;
                    flex-direction: column;
                    gap: 4px;
                    min-width: 0;
                }

                .tile-label {
                    font-size: 12px;
                    font-weight: 500;
                    text-transform: uppercase;
                    letter-spacing: 0.3px;
                    color: var(--secondary-text-color, ${T.textSec});
                }

                .tile-hero {
                    font-size: 22px;
                    font-weight: 700;
                    font-variant-numeric: tabular-nums;
                    line-height: 1.1;
                }

                .tile-detail {
                    font-size: 12px;
                    color: var(--secondary-text-color, ${T.textSec});
                }

                .stats {
                    display: flex;
                    gap: 16px;
                    margin-top: 4px;
                    flex-wrap: wrap;
                }

                .stat {
                    display: flex;
                    flex-direction: column;
                    gap: 1px;
                }

                .stat-val {
                    font-size: 13px;
                    font-weight: 600;
                    font-variant-numeric: tabular-nums;
                }

                .stat-lbl {
                    font-size: 12px;
                    text-transform: uppercase;
                    letter-spacing: 0.3px;
                    color: var(--secondary-text-color, ${T.textSec});
                }

                /* Hidden SVG filter */
                .glow-svg {
                    position: absolute;
                    width: 0;
                    height: 0;
                    overflow: hidden;
                }

                @media (max-width: 480px) {
                    .tiles { grid-template-columns: 1fr; }
                }
            </style>

            <!-- SVG glow filter for leaf/tree icons -->
            <svg class="glow-svg" aria-hidden="true">
                <defs>
                    <filter id="leaf-glow" x="-50%" y="-50%" width="200%" height="200%">
                        <feGaussianBlur stdDeviation="3" result="blur"/>
                        <feFlood flood-color="#8DC892" flood-opacity="0.25" result="color"/>
                        <feComposite in="color" in2="blur" operator="in" result="glow"/>
                        <feMerge>
                            <feMergeNode in="glow"/>
                            <feMergeNode in="SourceGraphic"/>
                        </feMerge>
                    </filter>
                </defs>
            </svg>

            <div class="wrap">
                <div class="tiles">

                    <!-- Left tile: Carbon Avoided Today -->
                    <div class="tile">
                        <ha-icon
                            icon="mdi:leaf"
                            style="--mdc-icon-size:24px;color:#8DC892;filter:url(#leaf-glow)"
                        ></ha-icon>
                        <div class="tile-content">
                            <span class="tile-label">${this._t('carbon_avoided_today')}</span>
                            <span class="tile-hero" style="color:#8DC892">${co2Today} kg</span>
                            <span class="tile-detail">${co2Detail}</span>
                        </div>
                    </div>

                    <!-- Right tile: Trees Equivalent -->
                    <div class="tile">
                        <ha-icon
                            icon="${treeIcon}"
                            style="--mdc-icon-size:24px;color:#8DC892;filter:url(#leaf-glow)"
                        ></ha-icon>
                        <div class="tile-content">
                            <span class="tile-label">${this._t('trees_equivalent')}</span>
                            <span class="tile-hero" style="color:#8DC892">${treesDisplay}</span>
                            <div class="stats">
                                <div class="stat">
                                    <span class="stat-val">${yearlyCO2.toFixed(0)} kg</span>
                                    <span class="stat-lbl">${this._t('co2_yearly')}</span>
                                </div>
                                <div class="stat">
                                    <span class="stat-val">${lifetimeCO2.toFixed(0)} kg</span>
                                    <span class="stat-lbl">${this._t('co2_lifetime')}</span>
                                </div>
                                <div class="stat">
                                    <span class="stat-val">${lifetimeTrees.toFixed(0)}</span>
                                    <span class="stat-lbl">${this._t('trees_lifetime')}</span>
                                </div>
                            </div>
                        </div>
                    </div>

                </div>
            </div>
        `;
    }

    getCardSize() { return 3; }

    static getStubConfig() {
        return { entity_prefix: DEFAULT_PREFIX };
    }
}

semDefineCard('sem-energy-impact-card', SEMEnergyImpactCard, {
    type: 'custom:sem-energy-impact-card',
    name: 'SEM Energy Impact Card',
    description: 'Environmental impact display for Solar Energy Management',
    preview: false,
});

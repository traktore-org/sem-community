(window.semReady || (fn => { window._semReadyQueue = window._semReadyQueue || []; window._semReadyQueue.push(fn); }))(function() {
/**
 * SEM Energy Impact Card — Environmental impact display
 *
 * Replaces 2 mushroom cards on the Energy tab:
 * - Carbon Avoided Today (with calculation breakdown)
 * - Trees Equivalent (yearly + lifetime)
 *
 * Config:
 *   type: custom:sem-energy-impact-card
 *   entity_prefix: sensor.sem_   # optional
 */

class SEMEnergyImpactCard extends SEMBaseCard {
    constructor() {
        super();
        this._rendered = false;
        this._lastKey = '';
    }

    setConfig(config) {
        this.config = config;
        this._prefix = config.entity_prefix || 'sensor.sem_';
    }

    _state(suffix, fallback = 0) {
        const e = this._hass?.states[`${this._prefix}${suffix}`];
        if (!e || e.state === 'unavailable' || e.state === 'unknown') return fallback;
        return parseFloat(e.state) ?? fallback;
    }

    set hass(hass) {
        const localeChanged = this._checkLocaleChange(hass);
        const key = [
            'flow_solar_to_home_energy', 'flow_solar_to_ev_energy',
            'daily_co2_avoided', 'yearly_co2_avoided', 'lifetime_co2_avoided',
            'yearly_trees_equivalent', 'lifetime_trees_equivalent',
        ].map(s => this._hass?.states[`${this._prefix}${s}`]?.state || '').join(',');

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

    _update() {
        if (!this._hass) return;
        const $ = (sel) => this.shadowRoot.querySelector(sel);
        const setVal = (sel, text) => { const el = $(sel); if (el && el.textContent !== text) el.textContent = text; };

        // CO2 calculation
        const solarHome = this._state('flow_solar_to_home_energy');
        const solarEV = this._state('flow_solar_to_ev_energy');
        const selfConsumed = solarHome + solarEV;
        const co2Today = (selfConsumed * 0.128).toFixed(1);
        setVal('.co2-value', `${co2Today} kg`);
        setVal('.co2-detail', `${selfConsumed.toFixed(1)} kWh × 128 g/kWh`);

        // Trees equivalent
        const yearlyTrees = this._state('yearly_trees_equivalent');
        const yearlyTreesText = yearlyTrees >= 10 ? yearlyTrees.toFixed(0) : yearlyTrees.toFixed(1);
        setVal('.trees-value', yearlyTreesText);

        // Tree icon
        const treeIcon = $('.tree-icon');
        if (treeIcon) {
            const icon = yearlyTrees >= 50 ? 'mdi:forest'
                : yearlyTrees >= 10 ? 'mdi:pine-tree'
                : yearlyTrees >= 1 ? 'mdi:tree' : 'mdi:sprout';
            if (treeIcon.getAttribute('icon') !== icon) treeIcon.setAttribute('icon', icon);
        }

        // Yearly/lifetime stats
        const yearlyCO2 = this._state('yearly_co2_avoided');
        const lifetimeCO2 = this._state('lifetime_co2_avoided');
        const lifetimeTrees = this._state('lifetime_trees_equivalent');
        setVal('.yearly-co2', `${yearlyCO2.toFixed(0)} kg`);
        setVal('.lifetime-co2', `${lifetimeCO2.toFixed(0)} kg`);
        setVal('.lifetime-trees', lifetimeTrees.toFixed(0));

        // Labels
        setVal('.lbl-co2', this._t('carbon_avoided_today'));
        setVal('.lbl-trees', this._t('trees_equivalent'));
        setVal('.lbl-yearly', this._t('co2_yearly'));
        setVal('.lbl-lifetime', this._t('co2_lifetime'));
        setVal('.lbl-lt-trees', this._t('trees_lifetime'));
    }

    _renderSkeleton() {
        const T = (typeof semTheme === 'function') ? semTheme() : {};
        const textCol = T.text || '#e0e0e0';
        const textSecCol = T.textSec || '#999';
        const surfaceCol = T.surface || 'rgba(255,255,255,0.06)';
        const surfBorder = T.surfaceBorder || 'rgba(255,255,255,0.12)';
        const dotCol = T.dotColor || 'rgba(128,128,128,0.05)';
        const isDark = T.isDark !== false;

        this.shadowRoot.innerHTML = `
            <style>
                :host { display: block; }
                .wrap {
                    padding: 16px;
                    background:
                        radial-gradient(ellipse 70% 60% at 50% 20%, rgba(255,152,0,0.06) 0%, transparent 100%),
                        radial-gradient(circle at 2px 2px, ${dotCol} 0.7px, transparent 0.7px);
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    color: var(--primary-text-color, ${textCol});
                }
                .tiles {
                    display: grid; grid-template-columns: 1fr 1fr; gap: 12px;
                }
                .tile {
                    display: flex; align-items: flex-start; gap: 10px;
                    padding: 14px;
                    border-radius: 12px;
                    background: ${surfaceCol};
                    border: 1px solid ${surfBorder};
                }
                .tile ha-icon { flex-shrink: 0; margin-top: 2px; }
                .tile-content { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
                .tile-label {
                    font-size: 11px; font-weight: 500; text-transform: uppercase;
                    letter-spacing: 0.3px;
                    color: var(--secondary-text-color, ${textSecCol});
                }
                .tile-hero {
                    font-size: 22px; font-weight: 700;
                    font-variant-numeric: tabular-nums;
                    line-height: 1.1;
                }
                .tile-detail {
                    font-size: 11px;
                    color: var(--secondary-text-color, ${textSecCol});
                }
                .stats {
                    display: flex; gap: 16px; margin-top: 4px;
                    flex-wrap: wrap;
                }
                .stat {
                    display: flex; flex-direction: column; gap: 1px;
                }
                .stat-val {
                    font-size: 13px; font-weight: 600;
                    font-variant-numeric: tabular-nums;
                }
                .stat-lbl {
                    font-size: 10px; text-transform: uppercase; letter-spacing: 0.3px;
                    color: var(--secondary-text-color, ${textSecCol});
                }
                /* Glow filter */
                .glow-svg { position: absolute; width: 0; height: 0; }
                @media (max-width: 480px) {
                    .tiles { grid-template-columns: 1fr; }
                }
            </style>
            <svg class="glow-svg">
                <filter id="leaf-glow" x="-50%" y="-50%" width="200%" height="200%">
                    <feGaussianBlur stdDeviation="3" result="blur"/>
                    <feFlood flood-color="#8DC892" flood-opacity="0.25" result="color"/>
                    <feComposite in="color" in2="blur" operator="in" result="glow"/>
                    <feMerge><feMergeNode in="glow"/><feMergeNode in="SourceGraphic"/></feMerge>
                </filter>
            </svg>
            <div class="wrap">
                <div class="tiles">
                    <div class="tile">
                        <ha-icon icon="mdi:leaf" style="--mdc-icon-size:24px;color:#8DC892;filter:url(#leaf-glow)"></ha-icon>
                        <div class="tile-content">
                            <span class="lbl-co2 tile-label">${this._t('carbon_avoided_today')}</span>
                            <span class="co2-value tile-hero" style="color:#8DC892">—</span>
                            <span class="co2-detail tile-detail">—</span>
                        </div>
                    </div>
                    <div class="tile">
                        <ha-icon class="tree-icon" icon="mdi:tree" style="--mdc-icon-size:24px;color:#8DC892;filter:url(#leaf-glow)"></ha-icon>
                        <div class="tile-content">
                            <span class="lbl-trees tile-label">${this._t('trees_equivalent')}</span>
                            <span class="trees-value tile-hero" style="color:#8DC892">—</span>
                            <div class="stats">
                                <div class="stat">
                                    <span class="yearly-co2 stat-val">—</span>
                                    <span class="lbl-yearly stat-lbl">${this._t('co2_yearly')}</span>
                                </div>
                                <div class="stat">
                                    <span class="lifetime-co2 stat-val">—</span>
                                    <span class="lbl-lifetime stat-lbl">${this._t('co2_lifetime')}</span>
                                </div>
                                <div class="stat">
                                    <span class="lifetime-trees stat-val">—</span>
                                    <span class="lbl-lt-trees stat-lbl">${this._t('trees_lifetime')}</span>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>`;
    }

    getCardSize() { return 3; }
    static getStubConfig() { return { entity_prefix: 'sensor.sem_' }; }
}

semDefineCard('sem-energy-impact-card', SEMEnergyImpactCard, {
    type: 'custom:sem-energy-impact-card',
    name: 'SEM Energy Impact Card',
    description: 'Environmental impact display for Solar Energy Management',
    preview: false,
});

});

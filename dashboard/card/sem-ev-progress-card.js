(window.semReady || (fn => { window._semReadyQueue = window._semReadyQueue || []; window._semReadyQueue.push(fn); }))(function() {
/**
 * SEM EV Progress Card — Daily progress + lifetime stats
 *
 * Replaces 2 mushroom cards on the EV tab:
 * - Daily EV progress bar (with target)
 * - Lifetime EV statistics chips
 *
 * Config:
 *   type: custom:sem-ev-progress-card
 *   entity_prefix: sensor.sem_   # optional
 */

class SEMEvProgressCard extends SEMBaseCard {
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
        return parseFloat(e.state) || fallback;
    }

    _numState(suffix, fallback = 0) {
        const e = this._hass?.states[`number.sem_${suffix}`];
        if (!e || e.state === 'unavailable' || e.state === 'unknown') return fallback;
        return parseFloat(e.state) || fallback;
    }

    set hass(hass) {
        const localeChanged = this._checkLocaleChange(hass);
        const key = [
            'daily_ev_energy', 'lifetime_ev_energy', 'lifetime_ev_solar_share',
            'lifetime_ev_cost', 'lifetime_ev_sessions',
        ].map(s => this._hass?.states[`${this._prefix}${s}`]?.state || '').join(',')
            + '|' + (this._hass?.states['number.sem_daily_ev_target']?.state || '');

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

        const daily = this._state('daily_ev_energy');
        const target = this._numState('daily_ev_target', 10);
        const pct = target > 0 ? Math.min(100, (daily / target * 100)) : 0;

        setVal('.progress-text', `${daily.toFixed(1)} / ${target.toFixed(1)} kWh`);
        setVal('.progress-pct', target > 0 ? `${pct.toFixed(0)}% ${this._t('of_target')}` : this._t('no_target'));

        const bar = $('.progress-fill');
        const widthStr = pct + '%';
        if (bar && bar.style.width !== widthStr) bar.style.width = widthStr;

        // Color based on progress
        const color = target === 0 ? '#666' : pct >= 100 ? '#8DC892' : pct >= 70 ? '#ff9800' : '#f44336';
        if (bar && bar.style.background !== color) bar.style.background = color;
        const icon = $('.progress-icon');
        if (icon && icon.style.color !== color) icon.style.color = color;

        // Lifetime stats
        const curr = (typeof semGetCurrency === 'function') ? semGetCurrency(this._hass) : 'EUR';
        setVal('.lt-energy', `${this._state('lifetime_ev_energy').toFixed(0)} kWh`);
        setVal('.lt-solar', `${this._state('lifetime_ev_solar_share').toFixed(0)}%`);
        setVal('.lt-cost', `${this._state('lifetime_ev_cost').toFixed(2)} ${curr}`);
        setVal('.lt-sessions', `${this._state('lifetime_ev_sessions').toFixed(0)}`);

        // Labels
        setVal('.lbl-daily', this._t('daily_progress'));
        setVal('.lbl-lifetime', this._t('lifetime_stats'));
        setVal('.lbl-energy', this._t('energy'));
        setVal('.lbl-solar', this._t('solar'));
        setVal('.lbl-cost', this._t('cost'));
        setVal('.lbl-sessions', this._t('sessions'));
    }

    _renderSkeleton() {
        const T = (typeof semTheme === 'function') ? semTheme() : {};
        const textCol = T.text || '#e0e0e0';
        const textSecCol = T.textSec || '#999';
        const surfaceCol = T.surface || 'rgba(255,255,255,0.06)';
        const surfBorder = T.surfaceBorder || 'rgba(255,255,255,0.12)';
        const dotCol = T.dotColor || 'rgba(128,128,128,0.05)';

        this.shadowRoot.innerHTML = `
            <style>
                :host { display: block; }
                .wrap {
                    padding: 16px;
                    background:
                        radial-gradient(ellipse 70% 60% at 50% 20%, rgba(141,200,146,0.06) 0%, transparent 100%),
                        radial-gradient(circle at 2px 2px, ${dotCol} 0.7px, transparent 0.7px);
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    color: var(--primary-text-color, ${textCol});
                }
                /* Progress section */
                .progress-section {
                    margin-bottom: 16px;
                }
                .progress-header {
                    display: flex; align-items: center; gap: 8px; margin-bottom: 8px;
                }
                .progress-icon { transition: color 0.3s; }
                .lbl-daily { font-size: 11px; font-weight: 500; text-transform: uppercase; letter-spacing: 0.3px; color: var(--secondary-text-color, ${textSecCol}); }
                .progress-text {
                    font-size: 18px; font-weight: 700; font-variant-numeric: tabular-nums;
                    margin-bottom: 4px;
                }
                .progress-pct {
                    font-size: 12px; color: var(--secondary-text-color, ${textSecCol});
                    margin-bottom: 6px;
                }
                .progress-track {
                    height: 6px; border-radius: 3px;
                    background: ${surfaceCol};
                    overflow: hidden;
                }
                .progress-fill {
                    height: 100%; border-radius: 3px;
                    background: #8DC892;
                    transition: width 0.5s ease;
                    width: 0%;
                }
                /* Lifetime stats */
                .lifetime-section { }
                .lbl-lifetime {
                    font-size: 11px; font-weight: 500; text-transform: uppercase;
                    letter-spacing: 0.3px; margin-bottom: 8px;
                    color: var(--secondary-text-color, ${textSecCol});
                }
                .stats-grid {
                    display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px;
                }
                .stat-tile {
                    display: flex; flex-direction: column; align-items: center;
                    padding: 10px 4px;
                    border-radius: 10px;
                    background: ${surfaceCol};
                    border: 1px solid ${surfBorder};
                    text-align: center;
                }
                .stat-tile ha-icon { margin-bottom: 4px; }
                .stat-val {
                    font-size: 14px; font-weight: 700;
                    font-variant-numeric: tabular-nums;
                    line-height: 1.2;
                }
                .stat-lbl {
                    font-size: 9px; text-transform: uppercase;
                    color: var(--secondary-text-color, ${textSecCol});
                    letter-spacing: 0.3px; margin-top: 2px;
                }
                @media (max-width: 400px) {
                    .stats-grid { grid-template-columns: repeat(2, 1fr); }
                }
            </style>
            <div class="wrap">
                <div class="progress-section">
                    <div class="progress-header">
                        <ha-icon class="progress-icon" icon="mdi:car-electric" style="--mdc-icon-size:20px;color:#8DC892"></ha-icon>
                        <span class="lbl-daily">${this._t('daily_progress')}</span>
                    </div>
                    <div class="progress-text">—</div>
                    <div class="progress-pct">—</div>
                    <div class="progress-track"><div class="progress-fill"></div></div>
                </div>
                <div class="lifetime-section">
                    <div class="lbl-lifetime">${this._t('lifetime_stats')}</div>
                    <div class="stats-grid">
                        <div class="stat-tile">
                            <ha-icon icon="mdi:lightning-bolt" style="--mdc-icon-size:18px;color:#8DC892"></ha-icon>
                            <span class="lt-energy stat-val">—</span>
                            <span class="lbl-energy stat-lbl">${this._t('energy')}</span>
                        </div>
                        <div class="stat-tile">
                            <ha-icon icon="mdi:white-balance-sunny" style="--mdc-icon-size:18px;color:#ff9800"></ha-icon>
                            <span class="lt-solar stat-val">—</span>
                            <span class="lbl-solar stat-lbl">${this._t('solar')}</span>
                        </div>
                        <div class="stat-tile">
                            <ha-icon icon="mdi:cash" style="--mdc-icon-size:18px;color:#5BC8D8"></ha-icon>
                            <span class="lt-cost stat-val">—</span>
                            <span class="lbl-cost stat-lbl">${this._t('cost')}</span>
                        </div>
                        <div class="stat-tile">
                            <ha-icon icon="mdi:counter" style="--mdc-icon-size:18px;color:#8353d1"></ha-icon>
                            <span class="lt-sessions stat-val">—</span>
                            <span class="lbl-sessions stat-lbl">${this._t('sessions')}</span>
                        </div>
                    </div>
                </div>
            </div>`;
    }

    getCardSize() { return 4; }
    static getStubConfig() { return { entity_prefix: 'sensor.sem_' }; }
}

semDefineCard('sem-ev-progress-card', SEMEvProgressCard, {
    type: 'custom:sem-ev-progress-card',
    name: 'SEM EV Progress Card',
    description: 'EV daily progress and lifetime statistics',
    preview: false,
});

});

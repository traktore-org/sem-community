(window.semReady || (fn => { window._semReadyQueue = window._semReadyQueue || []; window._semReadyQueue.push(fn); }))(function() {
/**
 * SEM Costs Card — Lumina-styled consolidated financial card
 *
 * Shows costs, savings, export revenue, ROI, and environmental impact
 * broken down by today / month / year with a net hero display.
 *
 * Config:
 *   type: custom:sem-costs-card
 *   entity_prefix: sensor.sem_   # default
 */

class SEMCostsCard extends SEMBaseCard {
    constructor() {
        super();
        this._rendered = false;
    }

    setConfig(config) {
        this.config = config;
        this._prefix = config.entity_prefix || 'sensor.sem_';
    }

    set hass(hass) {
        const localeChanged = this._checkLocaleChange(hass);
        const key = [
            'daily_costs', 'daily_savings', 'daily_export_revenue', 'daily_battery_savings', 'daily_net_cost',
            'monthly_costs', 'monthly_savings', 'monthly_export_revenue', 'monthly_net_cost',
            'yearly_costs', 'yearly_savings', 'yearly_export_revenue', 'yearly_net_cost',
            'lifetime_total_savings', 'roi_percentage', 'roi_payback_years', 'roi_annual_savings',
            'daily_co2_avoided', 'yearly_co2_avoided', 'lifetime_co2_avoided',
            'yearly_trees_equivalent', 'lifetime_trees_equivalent',
        ].map(s => this._hass?.states[`${this._prefix}${s}`]?.state || '').join(',')
            + '|' + this._hass?.language;
        if (key === this._lastKey && !localeChanged) return;
        this._lastKey = key;
        if (localeChanged) this._rendered = false;
        this._update();
    }

    _state(suffix, fallback = 0) {
        const e = this._hass?.states[`${this._prefix}${suffix}`];
        if (!e || e.state === 'unavailable' || e.state === 'unknown') return fallback;
        return parseFloat(e.state) ?? fallback;
    }

    _fmt(val, decimals = 2) {
        if (val == null || isNaN(val)) return '—';
        return val.toFixed(decimals);
    }

    _fmtCurr(val, curr, decimals = 2) {
        if (val == null || isNaN(val)) return '—';
        return val.toFixed(decimals) + ' ' + curr;
    }

    _update() {
        if (!this._hass) return;
        if (!this._rendered) {
            this._renderSkeleton();
            this._rendered = true;
        }

        const $ = (sel) => this.shadowRoot.querySelector(sel);
        const setVal = (sel, text) => { const el = $(sel); if (el) el.textContent = text; };
        const curr = (typeof semGetCurrency === 'function') ? semGetCurrency(this._hass) : 'EUR';

        // Hero — daily net
        const dailyNet = this._state('daily_net_cost', null);
        const netEl = $('.hero-net');
        if (netEl) {
            const saving = dailyNet !== null && dailyNet <= 0;
            netEl.textContent = dailyNet !== null
                ? (saving ? '+' : '') + this._fmt(Math.abs(dailyNet), 2) + ' ' + curr
                : '—';
            netEl.style.color = saving ? '#8DC892' : '#f06292';
        }
        const heroLblEl = $('.hero-label');
        if (heroLblEl) {
            const dailyNetVal = this._state('daily_net_cost', null);
            heroLblEl.textContent = (dailyNetVal !== null && dailyNetVal <= 0)
                ? this._t('net_saving_today')
                : this._t('net_cost_today');
            heroLblEl.style.color = (dailyNetVal !== null && dailyNetVal <= 0) ? '#8DC892' : '#f06292';
        }

        // Today breakdown
        setVal('.d-import', this._fmtCurr(this._state('daily_costs'), curr));
        setVal('.d-solar', this._fmtCurr(this._state('daily_savings'), curr));
        setVal('.d-batt', this._fmtCurr(this._state('daily_battery_savings'), curr));
        setVal('.d-export', this._fmtCurr(this._state('daily_export_revenue'), curr));
        const dNet = this._state('daily_net_cost');
        const dNetEl = $('.d-net');
        if (dNetEl) { dNetEl.textContent = this._fmtCurr(dNet, curr); dNetEl.style.color = dNet <= 0 ? '#8DC892' : '#f06292'; }

        // Monthly
        setVal('.m-import', this._fmtCurr(this._state('monthly_costs'), curr));
        setVal('.m-solar', this._fmtCurr(this._state('monthly_savings'), curr));
        setVal('.m-export', this._fmtCurr(this._state('monthly_export_revenue'), curr));
        const mNet = this._state('monthly_net_cost');
        const mNetEl = $('.m-net');
        if (mNetEl) { mNetEl.textContent = this._fmtCurr(mNet, curr); mNetEl.style.color = mNet <= 0 ? '#8DC892' : '#f06292'; }

        setVal('.m-batt', this._fmtCurr(this._state('monthly_battery_savings'), curr));

        // Yearly
        setVal('.y-import', this._fmtCurr(this._state('yearly_costs'), curr));
        setVal('.y-solar', this._fmtCurr(this._state('yearly_savings'), curr));
        setVal('.y-batt', this._fmtCurr(this._state('yearly_battery_savings'), curr));
        setVal('.y-export', this._fmtCurr(this._state('yearly_export_revenue'), curr));
        const yNet = this._state('yearly_net_cost');
        const yNetEl = $('.y-net');
        if (yNetEl) { yNetEl.textContent = this._fmtCurr(yNet, curr); yNetEl.style.color = yNet <= 0 ? '#8DC892' : '#f06292'; }

        // ROI
        setVal('.roi-lifetime', this._fmtCurr(this._state('lifetime_total_savings'), curr, 0));
        setVal('.roi-annual', this._fmtCurr(this._state('roi_annual_savings'), curr, 0));
        const payback = this._state('roi_payback_years');
        setVal('.roi-payback', payback > 0 ? this._fmt(payback, 1) + ' ' + this._t('years') : '—');
        const roiPct = this._state('roi_percentage');
        const roiEl = $('.roi-pct');
        if (roiEl) { roiEl.textContent = roiPct !== 0 ? this._fmt(roiPct, 1) + '%' : '—'; roiEl.style.color = roiPct >= 0 ? '#8DC892' : '#f06292'; }

        // Environmental
        setVal('.env-daily-co2', this._fmt(this._state('daily_co2_avoided'), 1) + ' kg');
        setVal('.env-yearly-co2', this._fmt(this._state('yearly_co2_avoided'), 0) + ' kg');
        setVal('.env-lifetime-co2', this._fmt(this._state('lifetime_co2_avoided'), 0) + ' kg');
        setVal('.env-yearly-trees', this._fmt(this._state('yearly_trees_equivalent'), 1));
        setVal('.env-lifetime-trees', this._fmt(this._state('lifetime_trees_equivalent'), 1));

        // Labels
        setVal('.lbl-today', this._t('today'));
        setVal('.lbl-monthly', this._t('monthly'));
        setVal('.lbl-yearly', this._t('yearly'));
        setVal('.lbl-roi', this._t('roi'));
        setVal('.lbl-environment', this._t('environment'));
        setVal('.lbl-d-import', this._t('import_cost'));
        setVal('.lbl-d-solar', this._t('solar_savings'));
        setVal('.lbl-d-batt', this._t('battery_savings'));
        setVal('.lbl-d-export', this._t('export_revenue'));
        setVal('.lbl-d-net', this._t('net'));
        setVal('.lbl-m-import', this._t('import_cost'));
        setVal('.lbl-m-solar', this._t('solar_savings'));
        setVal('.lbl-m-batt', this._t('battery_savings'));
        setVal('.lbl-m-export', this._t('export_revenue'));
        setVal('.lbl-m-net', this._t('net'));
        setVal('.lbl-y-import', this._t('import_cost'));
        setVal('.lbl-y-solar', this._t('solar_savings'));
        setVal('.lbl-y-batt', this._t('battery_savings'));
        setVal('.lbl-y-export', this._t('export_revenue'));
        setVal('.lbl-y-net', this._t('net'));
        setVal('.lbl-roi-lifetime', this._t('lifetime_savings'));
        setVal('.lbl-roi-annual', this._t('annual_savings'));
        setVal('.lbl-roi-payback', this._t('payback_years'));
        setVal('.lbl-roi-pct', this._t('roi_percentage'));
        setVal('.lbl-env-daily', this._t('co2_today'));
        setVal('.lbl-env-yearly', this._t('co2_yearly'));
        setVal('.lbl-env-lifetime', this._t('co2_lifetime'));
        setVal('.lbl-env-ytrees', this._t('trees_yearly'));
        setVal('.lbl-env-ltrees', this._t('trees_lifetime'));
    }

    _renderSkeleton() {
        const T = (typeof semTheme === 'function') ? semTheme() : {};
        const textCol    = T.text          || '#e0e0e0';
        const textSecCol = T.textSec       || '#999';
        const chipLblCol = T.textTertiary  || '#888';
        const surfaceCol = T.surface       || 'rgba(255,255,255,0.06)';
        const surfBorder = T.surfaceBorder || 'rgba(255,255,255,0.12)';
        const dotCol     = T.dotColor      || 'rgba(128,128,128,0.05)';

        this.shadowRoot.innerHTML = `
            <style>
                :host { display: block; }
                .wrap {
                    padding: 16px 20px;
                    position: relative;
                    background:
                        radial-gradient(ellipse 70% 60% at 50% 20%, rgba(141,200,146,0.07) 0%, transparent 100%),
                        radial-gradient(circle at 2px 2px, ${dotCol} 0.7px, transparent 0.7px);
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    color: var(--primary-text-color, ${textCol});
                }
                .glow-svg { position: absolute; width: 0; height: 0; }

                /* ── Hero ── */
                .hero {
                    display: flex; align-items: center; justify-content: center;
                    flex-direction: column; padding: 4px 0 8px;
                    text-align: center;
                }
                .hero-net {
                    font-size: 28px; font-weight: 700;
                    font-variant-numeric: tabular-nums;
                    text-shadow: 0 0 12px rgba(141,200,146,0.3);
                    line-height: 1.1;
                }
                .hero-label {
                    font-size: 11px; font-weight: 500; text-transform: uppercase;
                    letter-spacing: 0.6px; margin-top: 2px;
                    color: var(--secondary-text-color,${textSecCol});
                }

                /* ── Section ── */
                .section {
                    margin-top: 10px; padding: 10px 12px;
                    background: var(--secondary-background-color, ${surfaceCol});
                    border: 1px solid var(--divider-color, ${surfBorder});
                    border-radius: 10px;
                }
                .section-title {
                    font-size: 10px; font-weight: 600; text-transform: uppercase;
                    letter-spacing: 0.6px; color: #8DC892; margin-bottom: 6px;
                }

                /* ── Multi-column layouts ── */
                .three-col {
                    display: grid;
                    grid-template-columns: 1fr 1fr 1fr;
                    gap: 0 10px;
                }
                .two-col {
                    display: grid;
                    grid-template-columns: 1fr 1fr;
                    gap: 0 10px;
                }
                @media (max-width: 400px) {
                    .three-col { grid-template-columns: 1fr; }
                    .two-col { grid-template-columns: 1fr; }
                }

                /* ── Metric rows ── */
                .metric-row {
                    display: flex; justify-content: space-between; align-items: baseline;
                    padding: 2px 0;
                }
                .metric-label {
                    font-size: 11px; color: var(--secondary-text-color,${textSecCol});
                    font-weight: 500;
                }
                .metric-val {
                    font-size: 12px; font-weight: 600;
                    font-variant-numeric: tabular-nums;
                    color: var(--primary-text-color,${textCol});
                }
                .metric-val.saving { color: #8DC892; }
                .metric-val.cost   { color: #f06292; }

                /* Color helpers */
                .c-import  { color: #488fc2; }
                .c-solar   { color: #ff9800; }
                .c-battery { color: #4db6ac; }
                .c-export  { color: #8353d1; }
                .c-green   { color: #8DC892; }
                .c-leaf    { color: #8DC892; }
            </style>

            <svg class="glow-svg">
                <defs>
                    <filter id="costs-glow" x="-50%" y="-50%" width="200%" height="200%">
                        <feGaussianBlur stdDeviation="5" result="blur"/>
                        <feFlood flood-color="#8DC892" flood-opacity="0.25" result="color"/>
                        <feComposite in="color" in2="blur" operator="in" result="glow"/>
                        <feMerge><feMergeNode in="glow"/><feMergeNode in="SourceGraphic"/></feMerge>
                    </filter>
                </defs>
            </svg>

            <ha-card>
                <div class="wrap">
                    <!-- Hero -->
                    <div class="hero">
                        <div class="hero-net" style="color:#8DC892">—</div>
                        <div class="hero-label">${this._t('net_saving_today')}</div>
                    </div>

                    <!-- Today / Monthly / Yearly (3 columns) -->
                    <div class="three-col">
                        <div class="section">
                            <div class="section-title lbl-today">${this._t('today')}</div>
                            <div class="metric-row">
                                <span class="metric-label lbl-d-import">${this._t('import_cost')}</span>
                                <span class="metric-val c-import d-import">—</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label lbl-d-solar">${this._t('solar_savings')}</span>
                                <span class="metric-val c-solar d-solar">—</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label lbl-d-batt">${this._t('battery_savings')}</span>
                                <span class="metric-val c-battery d-batt">—</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label lbl-d-export">${this._t('export_revenue')}</span>
                                <span class="metric-val c-export d-export">—</span>
                            </div>
                            <div class="metric-row" style="margin-top:4px;padding-top:4px;border-top:1px solid var(--divider-color,${surfBorder})">
                                <span class="metric-label lbl-d-net"><strong>${this._t('net')}</strong></span>
                                <span class="metric-val d-net">—</span>
                            </div>
                        </div>
                        <div class="section">
                            <div class="section-title lbl-monthly">${this._t('monthly')}</div>
                            <div class="metric-row">
                                <span class="metric-label lbl-m-import">${this._t('import_cost')}</span>
                                <span class="metric-val c-import m-import">—</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label lbl-m-solar">${this._t('solar_savings')}</span>
                                <span class="metric-val c-solar m-solar">—</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label lbl-m-batt">${this._t('battery_savings')}</span>
                                <span class="metric-val c-battery m-batt">—</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label lbl-m-export">${this._t('export_revenue')}</span>
                                <span class="metric-val c-export m-export">—</span>
                            </div>
                            <div class="metric-row" style="margin-top:4px;padding-top:4px;border-top:1px solid var(--divider-color,${surfBorder})">
                                <span class="metric-label lbl-m-net"><strong>${this._t('net')}</strong></span>
                                <span class="metric-val m-net">—</span>
                            </div>
                        </div>
                        <div class="section">
                            <div class="section-title lbl-yearly">${this._t('yearly')}</div>
                            <div class="metric-row">
                                <span class="metric-label lbl-y-import">${this._t('import_cost')}</span>
                                <span class="metric-val c-import y-import">—</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label lbl-y-solar">${this._t('solar_savings')}</span>
                                <span class="metric-val c-solar y-solar">—</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label lbl-y-batt">${this._t('battery_savings')}</span>
                                <span class="metric-val c-battery y-batt">—</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label lbl-y-export">${this._t('export_revenue')}</span>
                                <span class="metric-val c-export y-export">—</span>
                            </div>
                            <div class="metric-row" style="margin-top:4px;padding-top:4px;border-top:1px solid var(--divider-color,${surfBorder})">
                                <span class="metric-label lbl-y-net"><strong>${this._t('net')}</strong></span>
                                <span class="metric-val y-net">—</span>
                            </div>
                        </div>
                    </div>

                    <!-- ROI + Environmental (2 columns) -->
                    <div class="two-col">
                        <div class="section">
                            <div class="section-title lbl-roi">${this._t('roi')}</div>
                            <div class="metric-row">
                                <span class="metric-label lbl-roi-lifetime">${this._t('lifetime_savings')}</span>
                                <span class="metric-val c-green roi-lifetime">—</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label lbl-roi-annual">${this._t('annual_savings')}</span>
                                <span class="metric-val c-green roi-annual">—</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label lbl-roi-payback">${this._t('payback_years')}</span>
                                <span class="metric-val roi-payback">—</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label lbl-roi-pct">${this._t('roi_percentage')}</span>
                                <span class="metric-val roi-pct">—</span>
                            </div>
                        </div>
                        <div class="section">
                            <div class="section-title lbl-environment">${this._t('environment')}</div>
                            <div class="metric-row">
                                <span class="metric-label lbl-env-daily">${this._t('co2_today')}</span>
                                <span class="metric-val c-leaf env-daily-co2">—</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label lbl-env-yearly">${this._t('co2_yearly')}</span>
                                <span class="metric-val c-leaf env-yearly-co2">—</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label lbl-env-lifetime">${this._t('co2_lifetime')}</span>
                                <span class="metric-val c-leaf env-lifetime-co2">—</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label lbl-env-ytrees">${this._t('trees_yearly')}</span>
                                <span class="metric-val c-leaf env-yearly-trees">—</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label lbl-env-ltrees">${this._t('trees_lifetime')}</span>
                                <span class="metric-val c-leaf env-lifetime-trees">—</span>
                            </div>
                        </div>
                    </div>
                </div>
            </ha-card>
        `;
    }

    getCardSize() { return 5; }

    static getStubConfig() { return { entity_prefix: 'sensor.sem_' }; }
}

semDefineCard('sem-costs-card', SEMCostsCard, {
    type: 'sem-costs-card',
    name: 'SEM Costs',
    description: 'Consolidated financial card with daily/monthly/yearly costs, savings, ROI, and environmental impact',
});

});

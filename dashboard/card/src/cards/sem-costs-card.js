/**
 * SEM Costs Card — LitElement migration
 *
 * Financial hero + breakdown display (read-only).
 * Shows costs, savings, export revenue, ROI, and environmental impact
 * broken down by today / month / year with a net hero display.
 *
 * Config:
 *   type: custom:sem-costs-card
 *   entity_prefix: sensor.sem_   # default
 */

import { SEMLitBase, html, css, nothing } from '../base/sem-lit-base.js';
import { semTheme, semGetCurrency, semDefineCard } from '../base/sem-shared.js';

const DEFAULT_PREFIX = 'sensor.sem_';

const WATCHED_SUFFIXES = [
    'daily_costs', 'daily_savings', 'daily_export_revenue', 'daily_battery_savings', 'daily_net_cost',
    'monthly_costs', 'monthly_savings', 'monthly_export_revenue', 'monthly_net_cost', 'monthly_battery_savings',
    'yearly_costs', 'yearly_savings', 'yearly_export_revenue', 'yearly_net_cost', 'yearly_battery_savings',
    'lifetime_total_savings', 'roi_percentage', 'roi_payback_years', 'roi_annual_savings',
    'daily_co2_avoided', 'yearly_co2_avoided', 'lifetime_co2_avoided',
    'yearly_trees_equivalent', 'lifetime_trees_equivalent',
];

class SEMCostsCard extends SEMLitBase {
    static get watchedEntities() {
        return WATCHED_SUFFIXES.map(s => `${DEFAULT_PREFIX}${s}`);
    }

    setConfig(config) {
        super.setConfig(config);
        this._prefix = config.entity_prefix || DEFAULT_PREFIX;
    }

    /** Read numeric state from prefixed entity */
    _val(suffix, fallback = 0) {
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

    _netColor(net) {
        return net <= 0 ? '#8DC892' : '#f06292';
    }

    _renderPeriodSection(period, labelKey, clsPrefix, curr, T) {
        const imp = this._val(`${period}_costs`);
        const solar = this._val(`${period}_savings`);
        const batt = this._val(`${period}_battery_savings`);
        const exp = this._val(`${period}_export_revenue`);
        const net = this._val(`${period}_net_cost`);
        const netColor = this._netColor(net);
        // #554 — net_cost is COST-signed (import − export; negative = you
        // earned). The hero already presents it savings-positive ("+1.71
        // net saving"); the rows printed the raw −1.71 next to it — same
        // number, contradictory signs on one page. Render rows with the
        // hero's framing: '+' and green when earning, plain and pink when
        // it's a cost.
        const netText = (net <= 0 ? '+' : '') + this._fmtCurr(Math.abs(net), curr);

        // (#797) Two blocks, not one column. Cash flow (import/export/net)
        // and avoided cost (solar/battery savings) were listed as visually
        // parallel rows, which invites adding them up — a double count,
        // because the savings are already the reason the net cost is low.
        // Mockup approved by Guido 21.08: label each block, subtotal each,
        // and say once that avoided cost is not cash.
        const avoided = solar + batt;
        return html`
            <div class="section">
                <div class="section-title">${this._t(labelKey)}</div>

                <div class="block-title">${this._t('cost_block_moved')}</div>
                <div class="metric-row">
                    <span class="metric-label">${this._t('import_cost')}</span>
                    <span class="metric-val c-import">${this._fmtCurr(imp, curr)}</span>
                </div>
                <div class="metric-row">
                    <span class="metric-label">${this._t('export_revenue')}</span>
                    <span class="metric-val c-export">${this._fmtCurr(exp, curr)}</span>
                </div>
                <div class="metric-row net-row">
                    <span class="metric-label"><strong>${this._t(net <= 0 ? 'net_saving' : 'net_cost')}</strong></span>
                    <span class="metric-val" style="color:${netColor}">${netText}</span>
                </div>

                <div class="block-title">${this._t('cost_block_avoided')}</div>
                <div class="metric-row">
                    <span class="metric-label">${this._t('solar_savings')}</span>
                    <span class="metric-val c-solar">${this._fmtCurr(solar, curr)}</span>
                </div>
                <div class="metric-row">
                    <span class="metric-label">${this._t('battery_savings')}</span>
                    <span class="metric-val c-battery">${this._fmtCurr(batt, curr)}</span>
                </div>
                <div class="metric-row net-row">
                    <span class="metric-label"><strong>${this._t('cost_block_avoided_total')}</strong></span>
                    <span class="metric-val c-solar">${this._fmtCurr(avoided, curr)}</span>
                </div>

                <div class="block-note">${this._t('cost_block_note')}</div>
            </div>
        `;
    }

    render() {
        if (!this._config || !this._hass) return nothing;

        const curr = semGetCurrency(this._hass);
        const T = this._theme();

        const dailyNet = this._val('daily_net_cost');
        const heroSaving = dailyNet <= 0;
        const heroColor = heroSaving ? '#8DC892' : '#f06292';
        const heroText = (heroSaving ? '+' : '') + this._fmt(Math.abs(dailyNet), 2) + ' ' + curr;
        const heroLabel = heroSaving ? this._t('net_saving_today') : this._t('net_cost_today');

        const roiPct = this._val('roi_percentage');
        const roiColor = roiPct >= 0 ? '#8DC892' : '#f06292';
        const payback = this._val('roi_payback_years');

        return html`
            <ha-card>
                <div class="wrap">
                    <!-- Hero -->
                    <div class="hero">
                        <div class="hero-net" style="color:${heroColor}">${heroText}</div>
                        <div class="hero-label" style="color:${heroColor}">${heroLabel}</div>
                    </div>

                    <!-- Today / Monthly / Yearly (3 columns) -->
                    <div class="three-col">
                        ${this._renderPeriodSection('daily', 'today', 'd', curr, T)}
                        ${this._renderPeriodSection('monthly', 'monthly', 'm', curr, T)}
                        ${this._renderPeriodSection('yearly', 'yearly', 'y', curr, T)}
                    </div>

                    <!-- ROI + Environmental (2 columns) -->
                    <div class="two-col">
                        <div class="section">
                            <div class="section-title">${this._t('roi')}</div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t('lifetime_savings')}</span>
                                <span class="metric-val c-green">${this._fmtCurr(this._val('lifetime_total_savings'), curr, 0)}</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t('annual_savings')}</span>
                                <span class="metric-val c-green">${this._fmtCurr(this._val('roi_annual_savings'), curr, 0)}</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t('payback_years')}</span>
                                <span class="metric-val">${payback > 0 ? this._fmt(payback, 1) + ' ' + this._t('years') : '—'}</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t('roi_percentage')}</span>
                                <span class="metric-val" style="color:${roiColor}">${roiPct !== 0 ? this._fmt(roiPct, 1) + '%' : '—'}</span>
                            </div>
                        </div>
                        <div class="section">
                            <div class="section-title">${this._t('environment')}</div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t('co2_today')}</span>
                                <span class="metric-val c-leaf">${this._fmt(this._val('daily_co2_avoided'), 1)} kg</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t('co2_yearly')}</span>
                                <span class="metric-val c-leaf">${this._fmt(this._val('yearly_co2_avoided'), 0)} kg</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t('co2_lifetime')}</span>
                                <span class="metric-val c-leaf">${this._fmt(this._val('lifetime_co2_avoided'), 0)} kg</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t('trees_yearly')}</span>
                                <span class="metric-val c-leaf">${this._fmt(this._val('yearly_trees_equivalent'), 1)}</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t('trees_lifetime')}</span>
                                <span class="metric-val c-leaf">${this._fmt(this._val('lifetime_trees_equivalent'), 1)}</span>
                            </div>
                        </div>
                    </div>
                </div>
            </ha-card>
        `;
    }

    static get styles() {
        return css`
            :host { display: block; }
            .wrap {
                padding: 16px 20px;
                position: relative;
                background:
                    radial-gradient(ellipse 70% 60% at 50% 25%, rgba(240,98,146,0.06) 0%, transparent 100%),
                    radial-gradient(circle at 2px 2px, rgba(128,128,128,0.05) 0.7px, transparent 0.7px);
                background-size: 100% 100%, 50px 50px;
                font-family: 'Segoe UI','Roboto',sans-serif;
                color: var(--primary-text-color, #e0e0e0);
            }

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
                font-size: 12px; font-weight: 500; text-transform: uppercase;
                letter-spacing: 0.6px; margin-top: 2px;
                color: var(--secondary-text-color, #999);
            }

            /* ── Section ── */
            .section {
                margin-top: 10px; padding: 10px 12px;
                background: var(--secondary-background-color, rgba(255,255,255,0.06));
                border: 1px solid var(--divider-color, rgba(255,255,255,0.12));
                border-radius: 10px;
            }
            .section-title {
                font-size: 12px; font-weight: 600; text-transform: uppercase;
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
            .block-title {
                font-size: 12px; letter-spacing: .06em; text-transform: uppercase;
                opacity: .55; margin: 10px 0 2px;
            }
            .block-note {
                font-size: 12px; opacity: .55; margin-top: 8px; line-height: 1.35;
            }
            .net-row {
                margin-top: 4px; padding-top: 4px;
                border-top: 1px solid var(--divider-color, rgba(255,255,255,0.12));
            }
            .metric-label {
                font-size: 12px; color: var(--secondary-text-color, #999);
                font-weight: 500;
            }
            .metric-val {
                font-size: 12px; font-weight: 600;
                font-variant-numeric: tabular-nums;
                color: var(--primary-text-color, #e0e0e0);
            }

            /* Color helpers */
            .c-import  { color: #488fc2; }
            .c-solar   { color: #ff9800; }
            .c-battery { color: #4db6ac; }
            .c-export  { color: #8353d1; }
            .c-green   { color: #8DC892; }
            .c-leaf    { color: #8DC892; }
        `;
    }

    getCardSize() { return 5; }

    static getStubConfig() { return { entity_prefix: 'sensor.sem_' }; }
}

semDefineCard('sem-costs-card', SEMCostsCard, {
    type: 'sem-costs-card',
    name: 'SEM Costs',
    description: 'Consolidated financial card with daily/monthly/yearly costs, savings, ROI, and environmental impact',
    documentationURL:
        'https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-costs-card',
});

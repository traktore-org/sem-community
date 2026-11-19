/**
 * Retired SEM cards (#1321)
 *
 * The classic dashboard is gone. A card of it that a user placed by hand
 * on another dashboard would turn into a red "custom element doesn't
 * exist" error. Every retired tag is defined here instead and shows one
 * short line with a link to the SEM dashboard.
 */

import { SEMLitBase, html, css } from '../base/sem-lit-base.js';

/** Every card tag the classic dashboard had. */
export const RETIRED_TAGS = [
    'sem-battery-card', 'sem-battery-zones-card', 'sem-charger-status-card',
    'sem-chart-card', 'sem-config-card', 'sem-control-card', 'sem-costs-card',
    'sem-costs-detail-card', 'sem-diagnose-button', 'sem-energy-impact-card',
    'sem-energy-plan-card', 'sem-overnight-plan-card', 'sem-ev-progress-card',
    'sem-ev-status-card', 'sem-flow-card', 'sem-gauge-card', 'sem-grid-card',
    'sem-home-status-card', 'sem-load-priority-card', 'sem-next-link-card',
    'sem-onboarding-banner', 'sem-period-selector-card', 'sem-price-card',
    'sem-require', 'sem-require-card', 'sem-schedule-card', 'sem-solar-card',
    'sem-solar-kpi-card', 'sem-solar-summary-card', 'sem-system-card',
    'sem-system-diagram-card', 'sem-tab-header', 'sem-title-card',
    'sem-today-plan-card', 'sem-weather-card', 'sem-why-card',
];

const CANDIDATES = ['sem-next', 'sem-dashboard'];

class SEMRetiredCard extends SEMLitBase {
    static get properties() {
        return { ...super.properties, _path: { state: true } };
    }

    constructor() {
        super();
        this._path = '';
    }

    set hass(hass) {
        const first = !this._hass;
        super.hass = hass;
        if (first && hass) this._findDashboard();
    }
    get hass() { return this._hass; }

    /** The live SEM dashboard, whichever URL it has. */
    async _findDashboard() {
        try {
            const list = await this._hass.callWS({ type: 'lovelace/dashboards/list' });
            const hit = CANDIDATES.find((p) => Array.isArray(list) && list.some((d) => d.url_path === p));
            this._path = hit || '';
        } catch (e) {
            this._path = '';
        }
    }

    static get styles() {
        return css`
            :host { display: block; }
            .row { padding: 12px 16px; display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
                   color: var(--secondary-text-color); font-size: 14px; }
            a { color: var(--primary-color); text-decoration: none; font-weight: 500; }
        `;
    }

    render() {
        return html`<ha-card><div class="row">
            <span>${this._t('retired_card')}</span>
            ${this._path ? html`<a href="/${this._path}">${this._t('retired_card_open')}</a>` : ''}
        </div></ha-card>`;
    }
}

for (const tag of RETIRED_TAGS) {
    // one class per tag: a custom element class can only be defined once
    if (!customElements.get(tag)) customElements.define(tag, class extends SEMRetiredCard {});
}

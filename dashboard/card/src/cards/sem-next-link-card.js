/**
 * SEM Next link (#1321)
 *
 * One row on the classic System tab: create the SEM Next dashboard (five
 * screens by question) beside this one, or open it when it exists. The
 * classic dashboard is never touched.
 *
 * Config:
 *   type: custom:sem-next-link-card
 */

import { SEMLitBase, html, css, nothing } from '../base/sem-lit-base.js';
import { semDefineCard } from '../base/sem-shared.js';

const NEXT_PATH = 'sem-next';

class SEMNextLinkCard extends SEMLitBase {
    static get properties() {
        return { _exists: { state: true }, _busy: { state: true } };
    }

    constructor() {
        super();
        this._exists = null;    // unknown until the list answers
        this._busy = false;
    }

    set hass(hass) {
        const first = !this._hass;
        super.hass = hass;
        if (first && hass) this._refresh();
    }
    get hass() { return this._hass; }

    async _refresh() {
        try {
            const list = await this._hass.callWS({ type: 'lovelace/dashboards/list' });
            this._exists = Array.isArray(list) && list.some((d) => d.url_path === NEXT_PATH);
        } catch (e) {
            this._exists = null;
        }
    }

    async _create() {
        if (this._busy) return;
        this._busy = true;
        try {
            await this._hass.callService('solar_energy_management', 'generate_dashboard', { template: 'next' });
            setTimeout(() => { this._refresh(); this._busy = false; }, 4000);
        } catch (e) {
            this._busy = false;
        }
    }

    static get styles() {
        return css`
            :host { display: block; }
            .row { display: flex; align-items: center; gap: 14px; padding: 14px 18px; flex-wrap: wrap; }
            .icon { width: 44px; height: 44px; border-radius: 12px; display: grid; place-items: center;
                    background: rgba(31, 122, 140, 0.14); }
            .icon ha-icon { color: #4FB3C4; --mdc-icon-size: 26px; }
            .text { flex: 1 1 200px; min-width: 0; }
            .title { font-weight: 700; font-size: 1rem; }
            .sub { font-size: 0.85rem; color: var(--secondary-text-color); }
            .btn { border: 1px solid var(--divider-color); background: var(--secondary-background-color);
                   color: var(--primary-text-color); font: 600 13px inherit; padding: 10px 16px; border-radius: 12px;
                   cursor: pointer; min-height: 40px; text-decoration: none; display: inline-flex; align-items: center; }
            .btn.primary { background: #1F7A8C; color: #fff; border-color: transparent; }
            .btn[disabled] { opacity: 0.6; cursor: default; }
        `;
    }

    render() {
        if (!this._hass) return nothing;
        return html`
            <ha-card>
                <div class="row">
                    <div class="icon"><ha-icon icon="mdi:view-dashboard-variant-outline"></ha-icon></div>
                    <div class="text">
                        <div class="title">${this._t('next_link_title')}</div>
                        <div class="sub">${this._t('next_link_sub')}</div>
                    </div>
                    ${this._exists
                        ? html`<a class="btn primary" href="/${NEXT_PATH}/now">${this._t('next_link_open')}</a>`
                        : html`<button class="btn primary" ?disabled=${this._busy} @click=${() => this._create()}>
                                   ${this._busy ? this._t('next_link_creating') : this._t('next_link_create')}
                               </button>`}
                </div>
            </ha-card>
        `;
    }

    getCardSize() { return 1; }
    static getStubConfig() { return {}; }
}

semDefineCard('sem-next-link-card', SEMNextLinkCard, {
    type: 'sem-next-link-card',
    name: 'SEM Next link',
    description: 'Create or open the SEM Next dashboard beside the classic one',
    documentationURL:
        'https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-next-link-card',
    preview: true,
});

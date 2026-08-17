/**
 * sem-require-card — dependency-aware wrapper for required HACS cards (#555).
 *
 * Wraps a card whose custom element comes from a HACS frontend package
 * (e.g. sankey-chart). When the element is registered, the wrapped card
 * renders normally — zero visual difference. When it is NOT (the user
 * skipped the required-cards install step), HA would show its cryptic
 * collapsed "Configuration error" bar; instead this renders a friendly,
 * actionable notice: which card is missing, that it is installed via
 * HACS, and that a hard-refresh completes it. Re-renders automatically
 * the moment the element gets defined (customElements.whenDefined), so
 * an install in the same session heals without a reload.
 *
 * Config:
 *   type: custom:sem-require
 *   requires: sankey-chart            # custom element tag to test for
 *   name: Sankey Chart                # human name for the notice
 *   card: { ...the real card config }
 */
import { SEMLitBase, html, css, nothing } from '../base/sem-lit-base.js';
import { semDefineCard } from '../base/sem-shared.js';

class SEMRequireCard extends SEMLitBase {
    static properties = {
        ...SEMLitBase.properties,
        _available: { state: true },
    };

    setConfig(config) {
        if (!config?.requires || !config?.card) {
            throw new Error('sem-require: "requires" and "card" are mandatory');
        }
        this._config = config;
        this._available = !!customElements.get(config.requires);
        this._inner = null;
        if (!this._available) {
            customElements.whenDefined(config.requires).then(() => {
                this._available = true;
                this._inner = null;
                this.requestUpdate();
            });
        }
    }

    set hass(hass) {
        this._hass = hass;
        if (this._inner) this._inner.hass = hass;
        this.requestUpdate();
    }

    async _buildInner() {
        if (this._inner || !this._available) return;
        const helpers = await window.loadCardHelpers();
        this._inner = helpers.createCardElement(this._config.card);
        if (this._hass) this._inner.hass = this._hass;
        this.requestUpdate();
    }

    render() {
        if (!this._config) return nothing;
        if (this._available) {
            if (!this._inner) {
                this._buildInner();
                return nothing;
            }
            return html`${this._inner}`;
        }
        const name = this._config.name || this._config.requires;
        return html`
            <ha-card>
                <div class="notice">
                    <ha-icon icon="mdi:puzzle-outline"></ha-icon>
                    <div class="text">
                        <div class="title">${this._t('require_missing_title').replace('{name}', name)}</div>
                        <div class="body">${this._t('require_missing_body').replace('{name}', name)}</div>
                    </div>
                </div>
            </ha-card>
        `;
    }

    static styles = css`
        .notice {
            display: flex; gap: 14px; align-items: center;
            padding: 16px;
        }
        .notice ha-icon { --mdc-icon-size: 30px; color: var(--warning-color, #ffa726); }
        .title { font-weight: 600; margin-bottom: 4px; }
        .body { font-size: 13px; opacity: 0.85; line-height: 1.4; }
    `;

    getCardSize() { return this._inner?.getCardSize?.() || 3; }
}

semDefineCard('sem-require', SEMRequireCard, {
    type: 'sem-require',
    name: 'SEM Require Wrapper',
    description: 'Renders a card only when its HACS dependency is installed; otherwise a friendly install notice',
    documentationURL:
        'https://github.com/traktore-org/sem-community/blob/main/docs/DASHBOARD_GUIDE.md#sem-require',
    preview: false,
});

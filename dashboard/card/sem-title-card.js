/**
 * SEM Title Card — Runtime-translated section header
 *
 * Replaces mushroom-title-card for SEM dashboard sections.
 * Translates title and subtitle at render time using semLocalize()
 * so each user sees their own language instantly.
 *
 * Config:
 *   type: custom:sem-title-card
 *   title: SOC Zone Configuration     # English text (used as translation key)
 *   subtitle: Priority < 30% ...      # optional, supports Jinja via HA template
 *   title_key: soc_zone_config        # optional explicit key (overrides title lookup)
 *   icon: mdi:battery-outline         # optional icon
 *   card_mod:                          # optional card-mod styling
 *     style: ...
 */

class SEMTitleCard extends HTMLElement {
    constructor() {
        super();
        this.attachShadow({ mode: 'open' });
        this._lang = null;
        this._hasLocalize = false;
        this._renderedSubtitle = null;
        this._templateUnsub = null;
        this._templateSubbed = false;
    }

    setConfig(config) {
        this.config = config;
        // Reset template subscription if config changes
        this._unsubTemplate();
        this._templateSubbed = false;
        this._renderedSubtitle = null;
    }

    _t(key) {
        if (!key) return '';
        const lang = this._hass?.language;
        return (typeof semLocalize === 'function') ? semLocalize(key, lang) : key;
    }

    _hasJinja(str) {
        return str && (str.includes('{%') || str.includes('{{'));
    }

    set hass(hass) {
        this._hass = hass;
        const lang = hass?.language;
        const hasLocalize = typeof semLocalize === 'function';

        // Re-render when language changes or semLocalize loads
        if (lang !== this._lang || (hasLocalize && !this._hasLocalize)) {
            this._lang = lang;
            this._hasLocalize = hasLocalize;
            this._render();
        }

        // Subscribe to HA template rendering for Jinja subtitles
        if (this._hasJinja(this.config.subtitle) && !this._templateSubbed) {
            this._subscribeTemplate();
        }
    }

    _subscribeTemplate() {
        if (!this._hass?.connection || this._templateSubbed) return;
        this._templateSubbed = true;

        const template = this.config.subtitle;
        this._hass.connection.subscribeMessage(
            (msg) => {
                const result = msg.result;
                if (result !== this._renderedSubtitle) {
                    this._renderedSubtitle = result;
                    this._render();
                }
            },
            { type: 'render_template', template, variables: {} }
        ).then(unsub => {
            this._templateUnsub = unsub;
        }).catch(() => {
            // Fallback: show raw subtitle
            this._renderedSubtitle = this.config.subtitle;
            this._render();
        });
    }

    _unsubTemplate() {
        if (this._templateUnsub) {
            this._templateUnsub();
            this._templateUnsub = null;
        }
    }

    _render() {
        const title = this._t(this.config.title_key || this.config.title || '');

        let subtitle = '';
        if (this._hasJinja(this.config.subtitle)) {
            // Jinja subtitle — use rendered result from HA template engine
            subtitle = this._renderedSubtitle || '';
        } else {
            // Plain text subtitle — translate via semLocalize
            subtitle = this._t(this.config.subtitle || '');
        }

        const T = (typeof semTheme === 'function') ? semTheme() : {};
        const textCol = T.text || '#e0e0e0';
        const textSecCol = T.textSec || '#888';

        this.shadowRoot.innerHTML = `
            <style>
                :host { display: block; }
                .sem-title-wrap {
                    padding: 8px 0 0 0;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                }
                .title {
                    font-size: 16px;
                    font-weight: 600;
                    letter-spacing: 0.5px;
                    color: ${textCol};
                    line-height: 1.3;
                    padding: 0 16px;
                }
                .subtitle {
                    font-size: 12px;
                    color: ${textSecCol};
                    margin-top: 2px;
                    line-height: 1.4;
                    padding: 0 16px;
                }
                .divider {
                    height: 1px;
                    margin: 4px 16px 0;
                    background: linear-gradient(90deg, rgba(150,202,238,0.25) 0%, transparent 70%);
                }
            </style>
            <div class="sem-title-wrap">
                <div class="title">${title}</div>
                ${subtitle ? `<div class="subtitle">${subtitle}</div>` : ''}
                <div class="divider"></div>
            </div>
        `;
    }

    disconnectedCallback() {
        this._unsubTemplate();
    }

    getCardSize() { return 1; }

    static getStubConfig() {
        return { title: 'Section Title' };
    }
}

customElements.define('sem-title-card', SEMTitleCard);

window.customCards = window.customCards || [];
window.customCards.push({
    type: 'sem-title-card',
    name: 'SEM Title Card',
    description: 'Runtime-translated section header for SEM dashboard',
});

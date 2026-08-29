/**
 * SEM Title Card — Runtime-translated section header
 *
 * Replaces mushroom-title-card for SEM dashboard sections.
 * Translates title and subtitle at render time using semLocalize()
 * so each user sees their own language instantly.
 */

import { SEMLitBase, html, css, nothing } from '../base/sem-lit-base.js';
import { semTheme, semDefineCard } from '../base/sem-shared.js';

class SEMTitleCard extends SEMLitBase {
    static get watchedEntities() { return []; }

    constructor() {
        super();
        this._renderedSubtitle = null;
        this._templateUnsub = null;
        this._templateSubbed = false;
    }

    setConfig(config) {
        super.setConfig(config);
        this._unsubTemplate();
        this._templateSubbed = false;
        this._renderedSubtitle = null;
    }

    _hasJinja(str) {
        return str && (str.includes('{%') || str.includes('{{'));
    }

    set hass(hass) {
        const old = this._hass;
        this._hass = hass;

        // Locale change detection
        const lang = hass?.language;
        const hasLocalize = typeof semLocalize === 'function';
        if (lang !== this._lang || (hasLocalize && !this._localizeReady)) {
            this._lang = lang;
            this._localizeReady = hasLocalize;
            this.requestUpdate();
        }

        // Subscribe to HA template rendering for Jinja subtitles
        if (this._hasJinja(this._config?.subtitle) && !this._templateSubbed) {
            this._subscribeTemplate();
        }
    }

    _subscribeTemplate() {
        if (!this._hass?.connection || this._templateSubbed) return;
        this._templateSubbed = true;

        const template = this._config.subtitle;
        this._hass.connection.subscribeMessage(
            (msg) => {
                const result = msg.result;
                if (result !== this._renderedSubtitle) {
                    this._renderedSubtitle = result;
                    this.requestUpdate();
                }
            },
            { type: 'render_template', template, variables: {} }
        ).then(unsub => {
            this._templateUnsub = unsub;
        }).catch(() => {
            this._renderedSubtitle = this._config.subtitle;
            this.requestUpdate();
        });
    }

    _unsubTemplate() {
        if (this._templateUnsub) {
            this._templateUnsub();
            this._templateUnsub = null;
        }
    }

    disconnectedCallback() {
        super.disconnectedCallback();
        this._unsubTemplate();
    }

    render() {
        if (!this._config) return nothing;

        const title = this._t(this._config.title_key || this._config.title || '');
        let subtitle = '';
        if (this._hasJinja(this._config.subtitle)) {
            subtitle = this._renderedSubtitle || '';
        } else {
            subtitle = this._t(this._config.subtitle || '');
        }

        const T = this._theme();

        return html`
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
                    color: ${T.text};
                    line-height: 1.3;
                    padding: 0 16px;
                }
                .subtitle {
                    font-size: 12px;
                    color: ${T.textSec};
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
                ${subtitle ? html`<div class="subtitle">${subtitle}</div>` : nothing}
                <div class="divider"></div>
            </div>
        `;
    }

    getCardSize() { return 1; }
    static getStubConfig() { return { title: 'Section Title' }; }
}

semDefineCard('sem-title-card', SEMTitleCard, {
    type: 'sem-title-card',
    name: 'SEM Title Card',
    description: 'Runtime-translated section header for SEM dashboard',
    documentationURL:
        'https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-title-card',
});

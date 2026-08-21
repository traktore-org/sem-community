/**
 * SEM Onboarding Banner (#442)
 *
 * One-time welcome banner pointing existing users to the new
 * Configuration tab. Self-hides via ``localStorage`` once dismissed.
 *
 * Drop on the Home tab; the card vanishes (zero height) once the
 * user clicks either button. The localStorage key is versioned per
 * banner so we can re-introduce future banners with new content.
 */

import { SEMLitBase, html, css, nothing } from '../base/sem-lit-base.js';
import { semTheme, semDefineCard } from '../base/sem-shared.js';

const LS_KEY = 'sem-config-tab-introduced-v1';

class SEMOnboardingBanner extends SEMLitBase {
    static get watchedEntities() { return []; }

    static get properties() {
        return {
            ...super.properties,
            _dismissed: { state: true },
        };
    }

    constructor() {
        super();
        this._dismissed = this._isDismissed();
    }

    setConfig(config) {
        super.setConfig(config);
        this._configPath = config.config_tab_path || '/config';
    }

    _isDismissed() {
        try { return localStorage.getItem(LS_KEY) === '1'; }
        catch (e) { return false; }
    }
    _dismiss() {
        try { localStorage.setItem(LS_KEY, '1'); } catch (e) { }
        this._dismissed = true;
    }
    _openConfig() {
        // Lovelace dashboards use hash-path routing on the panel view.
        // The dashboard URL is /<dashboard>/<view-path>. We look up the
        // root from window.location and substitute the last segment.
        const segments = window.location.pathname.split('/').filter(Boolean);
        if (segments.length >= 2) {
            // /lovelace/home -> /lovelace/config
            const root = '/' + segments.slice(0, -1).join('/');
            window.history.pushState(null, '', `${root}/config`);
        } else {
            window.history.pushState(null, '', this._configPath);
        }
        window.dispatchEvent(new Event('location-changed', { composed: true }));
        this._dismiss();
    }

    render() {
        if (this._dismissed) return nothing;
        if (!this._config) return nothing;
        const T = this._theme();
        const accent = '#8DC892';

        return html`
            <style>
                :host { display: block; }
                .banner {
                    display: flex; align-items: center; gap: 12px;
                    padding: 14px 16px; border-radius: 14px; margin-bottom: 12px;
                    background:
                        linear-gradient(135deg, ${accent}22 0%, ${accent}0B 100%),
                        ${T.surface};
                    border: 1px solid ${accent}55;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.08);
                    color: var(--primary-text-color, ${T.text});
                    font-family: 'Segoe UI','Roboto',sans-serif;
                }
                .icon {
                    --mdc-icon-size: 28px;
                    color: ${accent};
                    flex-shrink: 0;
                }
                .text { flex: 1; min-width: 0; }
                .title {
                    font-size: 14px; font-weight: 700; letter-spacing: 0.2px;
                    margin-bottom: 2px;
                }
                .body {
                    font-size: 12px; line-height: 1.4;
                    color: var(--secondary-text-color, ${T.textSec});
                }
                .actions { display: flex; gap: 6px; flex-shrink: 0; }
                button {
                    padding: 7px 14px; border-radius: 9px;
                    font-size: 12px; font-weight: 600; font-family: inherit;
                    cursor: pointer; border: 1px solid transparent;
                    transition: background 0.15s, border-color 0.15s, transform 0.05s;
                }
                button:active { transform: scale(0.97); }
                .open {
                    background: ${accent}; color: #1a1d24;
                }
                .open:hover { background: color-mix(in srgb, ${accent} 88%, white); }
                .dismiss {
                    background: transparent; color: var(--secondary-text-color, ${T.textSec});
                    border-color: ${T.surfaceBorder};
                }
                .dismiss:hover { background: ${T.surfaceHover}; }
                @media (max-width: 500px) {
                    .banner { flex-wrap: wrap; }
                    .text { flex: 1 1 100%; order: 1; }
                    .icon { order: 0; }
                    .actions { flex: 1 1 100%; order: 2; justify-content: flex-end; }
                }
            </style>
            <div class="banner">
                <ha-icon class="icon" icon="mdi:cog-sync-outline"></ha-icon>
                <div class="text">
                    <div class="title">${this._t('onboarding_banner_title')}</div>
                    <div class="body">${this._t('onboarding_banner_body')}</div>
                </div>
                <div class="actions">
                    <button class="open" @click=${() => this._openConfig()}>
                        ${this._t('onboarding_banner_open')}
                    </button>
                    <button class="dismiss" @click=${() => this._dismiss()}>
                        ${this._t('onboarding_banner_dismiss')}
                    </button>
                </div>
            </div>
        `;
    }

    getCardSize() { return 1; }
    static getStubConfig() { return {}; }
}

semDefineCard('sem-onboarding-banner', SEMOnboardingBanner, {
    type: 'sem-onboarding-banner',
    name: 'SEM Onboarding Banner',
    description: 'One-time welcome banner pointing existing users to the new Configuration tab',
    documentationURL:
        'https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-onboarding-banner',
    preview: false,
});

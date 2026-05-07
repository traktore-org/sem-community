/**
 * SEM Dashboard Translator — Runtime per-user translation
 *
 * Invisible card placed once on the dashboard. Walks the entire
 * Lovelace DOM and replaces English strings with the user's language
 * using semLocalize(). Re-translates when hass.language changes.
 *
 * This handles mushroom cards (entity, number, template, chips)
 * whose name:/title:/primary: fields don't support runtime translation.
 *
 * Config:
 *   type: custom:sem-dashboard-translator
 */

class SEMDashboardTranslator extends HTMLElement {
    constructor() {
        super();
        this._lang = null;
        this._observer = null;
        this._translateTimer = null;
        this._reverseMap = null;
    }

    setConfig(config) {
        this.config = config;
    }

    set hass(hass) {
        this._hass = hass;
        const lang = hass?.language;
        const hasLocalize = typeof semLocalize === 'function';

        if (!hasLocalize) return;

        // Build reverse map once per language: English → translated
        if (lang !== this._lang) {
            this._lang = lang;
            this._reverseMap = this._buildReverseMap(lang);
            // Translate after a short delay to let cards render
            this._scheduleTranslate();
            // Set up mutation observer to catch late-loading cards
            this._setupObserver();
        }
    }

    _buildReverseMap(lang) {
        if (lang === 'en' || !lang) return null;  // No translation needed for English
        const translations = window.SEM_TRANSLATIONS;
        if (!translations) return null;

        const en = translations.en || {};
        const target = translations[lang] || {};
        const map = {};

        for (const [key, enText] of Object.entries(en)) {
            const translated = target[key];
            if (translated && translated !== enText && enText.length > 1) {
                map[enText] = translated;
            }
        }
        return map;
    }

    _scheduleTranslate() {
        if (this._translateTimer) clearTimeout(this._translateTimer);
        this._translateTimer = setTimeout(() => this._translateAll(), 500);
    }

    _setupObserver() {
        if (this._observer) this._observer.disconnect();

        // Find the dashboard root (panels container)
        const root = this._findDashboardRoot();
        if (!root) return;

        this._observer = new MutationObserver(() => {
            this._scheduleTranslate();
        });

        this._observer.observe(root, {
            childList: true,
            subtree: true,
        });
    }

    _findDashboardRoot() {
        // Walk up from this element to find the hui-view or panel
        let el = this;
        for (let i = 0; i < 20; i++) {
            el = el.parentElement || el.getRootNode()?.host;
            if (!el) break;
            if (el.tagName && (
                el.tagName.toLowerCase().includes('hui-view') ||
                el.tagName.toLowerCase().includes('hui-panel') ||
                el.tagName.toLowerCase() === 'hui-root'
            )) {
                return el;
            }
        }
        return document.body;
    }

    _translateAll() {
        if (!this._reverseMap) return;

        // Find all card elements in the dashboard
        const root = this._findDashboardRoot();
        if (!root) return;

        this._walkAndTranslate(root);
    }

    _walkAndTranslate(el) {
        if (!el) return;

        // Translate text nodes in specific elements
        const translatableSelectors = [
            // Mushroom card labels
            '.title', '.name', '.primary', '.secondary', '.subtitle',
            '.info .name', '.info .secondary',
            'mushroom-state-info .primary', 'mushroom-state-info .secondary',
            // Chip labels
            '.chip-label', '.chip .content',
            // Card headers
            'h1', 'h2', 'h3', '.card-header', '.header .name',
            // Generic
            'ha-card .title', 'ha-card .name',
        ];

        // Walk shadow roots recursively
        this._walkShadows(el, (node) => {
            if (node.nodeType === Node.TEXT_NODE) {
                const text = node.textContent?.trim();
                if (text && this._reverseMap[text]) {
                    node.textContent = node.textContent.replace(text, this._reverseMap[text]);
                }
            } else if (node.nodeType === Node.ELEMENT_NODE) {
                // Check direct text content of small elements
                const tag = node.tagName?.toLowerCase();
                if (['span', 'div', 'p', 'h1', 'h2', 'h3', 'label'].includes(tag)) {
                    // Only translate leaf elements (no child elements with text)
                    if (node.children.length === 0 || (node.children.length === 1 && node.children[0].tagName === 'HA-ICON')) {
                        const text = node.textContent?.trim();
                        if (text && this._reverseMap[text]) {
                            // Preserve child elements like icons
                            for (const child of node.childNodes) {
                                if (child.nodeType === Node.TEXT_NODE) {
                                    const t = child.textContent?.trim();
                                    if (t && this._reverseMap[t]) {
                                        child.textContent = child.textContent.replace(t, this._reverseMap[t]);
                                    }
                                }
                            }
                        }
                    }
                }
            }
        });
    }

    _walkShadows(el, callback) {
        if (!el) return;

        // Process this element
        callback(el);

        // Walk children
        if (el.childNodes) {
            for (const child of el.childNodes) {
                this._walkShadows(child, callback);
            }
        }

        // Walk shadow root if present
        if (el.shadowRoot) {
            for (const child of el.shadowRoot.childNodes) {
                this._walkShadows(child, callback);
            }
        }

        // Walk slotted elements
        if (el.tagName === 'SLOT') {
            const assigned = el.assignedNodes?.() || [];
            for (const node of assigned) {
                this._walkShadows(node, callback);
            }
        }
    }

    disconnectedCallback() {
        if (this._observer) {
            this._observer.disconnect();
            this._observer = null;
        }
        if (this._translateTimer) {
            clearTimeout(this._translateTimer);
            this._translateTimer = null;
        }
    }

    getCardSize() { return 0; }

    static getStubConfig() { return {}; }
}

customElements.define('sem-dashboard-translator', SEMDashboardTranslator);

window.customCards = window.customCards || [];
window.customCards.push({
    type: 'sem-dashboard-translator',
    name: 'SEM Dashboard Translator',
    description: 'Invisible card that translates all dashboard text to the user language at runtime',
});

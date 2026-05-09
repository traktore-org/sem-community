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

class SEMDashboardTranslator extends SEMBaseCard {
    constructor() {
        super();
        this._observer = null;
        this._translateTimer = null;
        this._reverseMap = null;
    }

    setConfig(config) {
        this.config = config;
    }

    set hass(hass) {
        const localeChanged = this._checkLocaleChange(hass);
        const hasLocalize = typeof semLocalize === 'function';

        if (!hasLocalize) return;

        // Build reverse map once per language: English → translated
        if (localeChanged) {
            this._reverseMap = this._buildReverseMap(this._lang);
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

        // Walk from the dashboard root, not the entire document body
        const root = this._dashboardRoot || this._findDashboardRoot();
        this._dashboardRoot = root;
        this._walkAndTranslate(root);
    }

    _walkAndTranslate(root) {
        if (!root) return;

        // Collect all elements including those in shadow roots
        const allElements = [];
        this._collectAllElements(root, allElements);

        // Translate text nodes
        for (const el of allElements) {
            if (el.nodeType === Node.TEXT_NODE) {
                const text = el.textContent?.trim();
                if (text && text.length > 1 && this._reverseMap[text]) {
                    el.textContent = el.textContent.replace(text, this._reverseMap[text]);
                }
                continue;
            }

            // For leaf elements (no child elements), translate direct text
            if (el.nodeType === Node.ELEMENT_NODE && el.children?.length === 0) {
                const text = el.textContent?.trim();
                if (text && text.length > 1 && this._reverseMap[text]) {
                    el.textContent = this._reverseMap[text];
                }
            }
        }
    }

    _collectAllElements(node, result) {
        if (!node) return;

        result.push(node);

        // Walk regular children
        if (node.childNodes) {
            for (const child of node.childNodes) {
                this._collectAllElements(child, result);
            }
        }

        // Walk shadow root children
        if (node.shadowRoot) {
            for (const child of node.shadowRoot.childNodes) {
                this._collectAllElements(child, result);
            }
        }
    }

    disconnectedCallback() {
        super.disconnectedCallback();
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

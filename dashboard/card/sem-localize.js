/**
 * SEM Localization — loads dashboard translations from translations.json
 *
 * Single source of truth: /dashboard/translations.json
 * Used by all SEM cards via semLocalize(key, lang)
 * Also loaded by dashboard_generator.py for YAML template translation
 */

let SEM_TRANSLATIONS = null;
let _loadPromise = null;

/**
 * Load translations from the JSON file (async, cached).
 */
function _loadTranslations() {
    if (_loadPromise) return _loadPromise;
    _loadPromise = fetch('/local/custom_components/solar_energy_management/dashboard/translations.json')
        .then(r => r.json())
        .then(data => {
            SEM_TRANSLATIONS = data;
            window.SEM_TRANSLATIONS = data;
            return data;
        })
        .catch(() => {
            // Fallback: minimal English if fetch fails
            SEM_TRANSLATIONS = { en: {} };
            window.SEM_TRANSLATIONS = SEM_TRANSLATIONS;
            return SEM_TRANSLATIONS;
        });
    return _loadPromise;
}

// Start loading immediately
_loadTranslations();

/**
 * Get translated string for the given key and language.
 * Falls back to English if key not found in target language.
 * Returns the key itself if no translation loaded yet.
 */
function semLocalize(key, lang) {
    if (!SEM_TRANSLATIONS) return key;
    const t = SEM_TRANSLATIONS[lang] || SEM_TRANSLATIONS.en || {};
    return t[key] || (SEM_TRANSLATIONS.en || {})[key] || key;
}

// Export globally
if (typeof window !== 'undefined') {
    window.semLocalize = semLocalize;
    window._semLoadTranslations = _loadTranslations;
}

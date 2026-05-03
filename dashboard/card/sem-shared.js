/**
 * SEM Shared Constants & Utilities
 *
 * Single source of truth for color palette, formatters, and thresholds
 * used across all SEM dashboard cards.
 */

/* ── Canonical color palette ── */
const SEM_COLORS = {
    solar: '#ff9800',
    gridImport: '#488fc2',
    gridExport: '#8353d1',
    batteryIn: '#f06292',
    batteryOut: '#4db6ac',
    battery: '#4db6ac',
    home: '#5BC8D8',
    ev: '#8DC892',
    inverter: '#96CAEE',
};

/* ── Device colors for individual device nodes ── */
const SEM_DEVICE_COLORS = ['#FF8A65', '#AED581', '#CE93D8', '#64B5F6', '#ff9800', '#96CAEE'];

/* ── Power formatting ── */
function semFormatPower(watts) {
    if (watts == null || isNaN(watts)) return '— W';
    const abs = Math.abs(watts);
    if (abs >= 1000) return `${(watts / 1000).toFixed(1)} kW`;
    return `${Math.round(watts)} W`;
}

/* ── Energy formatting ── */
function semFormatEnergy(kwh) {
    if (kwh == null || isNaN(kwh)) return '—';
    return kwh.toFixed(kwh < 10 ? 2 : 1) + ' kWh';
}

/* ── Animation duration from power (higher power = faster animation) ── */
function semCalcDuration(watts) {
    const abs = Math.abs(watts);
    if (abs <= 0) return 4;
    const dur = 4 - Math.log10(Math.max(abs, 1)) * 0.9;
    return Math.max(0.5, Math.min(4, dur));
}

/* ── Interaction timing constants ── */
const SEM_HOLD_DELAY_MS = 500;
const SEM_DOUBLE_TAP_MS = 300;
const SEM_RESIZE_DEBOUNCE_MS = 100;
const SEM_UPDATE_DEBOUNCE_MS = 100;

/* ── Power thresholds ── */
const SEM_FLOW_ACTIVE_THRESHOLD = 10; // Watts — below this, flow is considered idle
const SEM_GLOW_MAX_SOLAR = 10000;
const SEM_GLOW_MAX_BATTERY = 5000;
const SEM_GLOW_MAX_GRID = 10000;
const SEM_GLOW_MAX_HOME = 8000;
const SEM_GLOW_MAX_EV = 11000;

/* ── Currency helper (#119) ── */
/**
 * Get the HA-configured currency symbol. Reads from the SEM daily_costs
 * sensor unit_of_measurement, falling back to hass.config or "EUR".
 * @param {object} hass - Home Assistant instance
 * @returns {string} Currency code (e.g., "EUR", "CHF", "USD")
 */
function semGetCurrency(hass) {
    if (!hass) return 'EUR';
    // Try reading from a monetary SEM sensor's unit
    const costEntity = hass.states?.['sensor.sem_daily_costs'];
    if (costEntity?.attributes?.unit_of_measurement) {
        return costEntity.attributes.unit_of_measurement;
    }
    // Fall back to HA config
    return hass.config?.currency || 'EUR';
}

/* ── Theme helper — reads HA CSS variables for light/dark adaptation ── */
/**
 * Returns a theme object with colors derived from HA's active theme.
 * All SEM cards should use this instead of hardcoded colors.
 *
 * @param {HTMLElement} [root] - Element to read computed styles from (default: document.documentElement)
 * @returns {object} Theme palette with text, background, surface, and derived values
 */
function semTheme(root) {
    const el = root || document.documentElement;
    const cs = getComputedStyle(el);
    const v = (name, fb) => {
        const val = cs.getPropertyValue(name).trim();
        return val || fb;
    };

    // Core HA theme variables
    const text       = v('--primary-text-color', '#e0e0e0');
    const textSec    = v('--secondary-text-color', '#888888');
    const cardBg     = v('--card-background-color', 'rgba(30,35,45,0.5)');
    const divider    = v('--divider-color', 'rgba(255,255,255,0.12)');
    const bgSec      = v('--secondary-background-color', 'rgba(255,255,255,0.06)');
    const shadow     = v('--ha-card-box-shadow', '0 2px 8px rgba(0,0,0,0.15)');
    const accent     = v('--primary-color', '#42a5f5');

    // Detect dark vs light by parsing background luminance
    const isDark = (() => {
        const bg = v('--primary-background-color', '#111');
        const m = bg.match(/\d+/g);
        if (m && m.length >= 3) {
            const lum = (0.299 * +m[0] + 0.587 * +m[1] + 0.114 * +m[2]) / 255;
            return lum < 0.5;
        }
        return !bg.startsWith('#f') && !bg.startsWith('#e') && !bg.startsWith('#d')
            && !bg.startsWith('#c') && !bg.startsWith('rgb(2');
    })();

    return {
        // Core colors
        text, textSec, cardBg, divider, bgSec, shadow, accent, isDark,
        // Text hierarchy
        textTertiary:  isDark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.50)',
        textDisabled:  isDark ? 'rgba(255,255,255,0.26)' : 'rgba(0,0,0,0.30)',
        // Surfaces
        surface:       isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.03)',
        surfaceHover:  isDark ? 'rgba(255,255,255,0.10)' : 'rgba(0,0,0,0.06)',
        surfaceBorder: isDark ? 'rgba(255,255,255,0.12)' : 'rgba(0,0,0,0.08)',
        // Dot grid & glow for background patterns
        dotColor:      isDark ? 'rgba(128,128,128,0.05)' : 'rgba(128,128,128,0.06)',
        glowAlpha:     isDark ? 0.05 : 0.03,
        // Tooltip
        tooltipBg:     isDark ? 'rgba(20,20,30,0.95)'    : 'rgba(255,255,255,0.95)',
        tooltipText:   isDark ? '#e0e0e0'                 : '#333333',
        tooltipBorder: isDark ? 'rgba(255,255,255,0.15)'  : 'rgba(0,0,0,0.12)',
    };
}

/* ── Common CSS snippet for dot-grid background ── */
function semDotGridCSS(color, glowColor, glowAlpha) {
    const ga = glowAlpha != null ? glowAlpha : 0.05;
    return `radial-gradient(ellipse 80% 70% at 20% 50%, ${glowColor}${Math.round(ga * 255).toString(16).padStart(2,'0')} 0%, transparent 70%),
            radial-gradient(circle at 2px 2px, ${color} 0.7px, transparent 0.7px)`;
}

/* ── Export for use in other cards ── */
if (typeof window !== 'undefined') {
    window.SEM_COLORS = SEM_COLORS;
    window.SEM_DEVICE_COLORS = SEM_DEVICE_COLORS;
    window.semFormatPower = semFormatPower;
    window.semFormatEnergy = semFormatEnergy;
    window.semCalcDuration = semCalcDuration;
    window.semGetCurrency = semGetCurrency;
    window.semTheme = semTheme;
    window.semDotGridCSS = semDotGridCSS;
}

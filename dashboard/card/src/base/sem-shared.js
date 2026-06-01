/**
 * SEM Shared Constants & Utilities
 *
 * Single source of truth for color palette, formatters, and thresholds
 * used across all SEM dashboard cards.
 */

/* ── Canonical color palette ── */
export const SEM_COLORS = {
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
export const SEM_DEVICE_COLORS = ['#FF8A65', '#AED581', '#CE93D8', '#64B5F6', '#ff9800', '#96CAEE'];

/* ── Power formatting ── */
export function semFormatPower(watts) {
    if (watts == null || isNaN(watts)) return '— W';
    const abs = Math.abs(watts);
    if (abs >= 1000) return `${(watts / 1000).toFixed(1)} kW`;
    return `${Math.round(watts)} W`;
}

/* ── Energy formatting ── */
export function semFormatEnergy(kwh) {
    if (kwh == null || isNaN(kwh)) return '—';
    return kwh.toFixed(kwh < 10 ? 2 : 1) + ' kWh';
}

/* ── Animation duration from power (higher power = faster animation) ── */
export function semCalcDuration(watts) {
    const abs = Math.abs(watts);
    if (abs <= 0) return 4;
    const dur = 4 - Math.log10(Math.max(abs, 1)) * 0.9;
    return Math.max(0.5, Math.min(4, dur));
}

/* ── Interaction timing constants ── */
export const SEM_HOLD_DELAY_MS = 500;
export const SEM_DOUBLE_TAP_MS = 300;
export const SEM_RESIZE_DEBOUNCE_MS = 100;
export const SEM_UPDATE_DEBOUNCE_MS = 100;

/* ── Power thresholds ── */
export const SEM_FLOW_ACTIVE_THRESHOLD = 10;
export const SEM_GLOW_MAX_SOLAR = 10000;
export const SEM_GLOW_MAX_BATTERY = 5000;
export const SEM_GLOW_MAX_GRID = 10000;
export const SEM_GLOW_MAX_HOME = 8000;
export const SEM_GLOW_MAX_EV = 11000;

/* ── Currency helper (#119) ── */
export function semGetCurrency(hass) {
    if (!hass) return 'EUR';
    const costEntity = hass.states?.['sensor.sem_daily_costs'];
    if (costEntity?.attributes?.unit_of_measurement) {
        return costEntity.attributes.unit_of_measurement;
    }
    return hass.config?.currency || 'EUR';
}

/* ── Theme helper — reads HA CSS variables for light/dark adaptation ── */
export function semTheme(root) {
    const el = root || document.documentElement;
    const cs = getComputedStyle(el);
    const v = (name, fb) => {
        const val = cs.getPropertyValue(name).trim();
        return val || fb;
    };

    const text       = v('--primary-text-color', '#e0e0e0');
    const textSec    = v('--secondary-text-color', '#888888');
    const cardBg     = v('--card-background-color', 'rgba(30,35,45,0.5)');
    const divider    = v('--divider-color', 'rgba(255,255,255,0.12)');
    const bgSec      = v('--secondary-background-color', 'rgba(255,255,255,0.06)');
    const shadow     = v('--ha-card-box-shadow', '0 2px 8px rgba(0,0,0,0.15)');
    const accent     = v('--primary-color', '#42a5f5');

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
        text, textSec, cardBg, divider, bgSec, shadow, accent, isDark,
        textTertiary:  isDark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.50)',
        textDisabled:  isDark ? 'rgba(255,255,255,0.26)' : 'rgba(0,0,0,0.30)',
        surface:       isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.03)',
        surfaceHover:  isDark ? 'rgba(255,255,255,0.10)' : 'rgba(0,0,0,0.06)',
        surfaceBorder: isDark ? 'rgba(255,255,255,0.12)' : 'rgba(0,0,0,0.08)',
        dotColor:      isDark ? 'rgba(128,128,128,0.05)' : 'rgba(128,128,128,0.06)',
        glowAlpha:     isDark ? 0.05 : 0.03,
        tooltipBg:     isDark ? 'rgba(20,20,30,0.95)'    : 'rgba(255,255,255,0.95)',
        tooltipText:   isDark ? '#e0e0e0'                 : '#333333',
        tooltipBorder: isDark ? 'rgba(255,255,255,0.15)'  : 'rgba(0,0,0,0.12)',
    };
}

/* ── Common CSS snippet for dot-grid background ── */
export function semDotGridCSS(color, glowColor, glowAlpha) {
    const ga = glowAlpha != null ? glowAlpha : 0.05;
    return `radial-gradient(ellipse 80% 70% at 20% 50%, ${glowColor}${Math.round(ga * 255).toString(16).padStart(2,'0')} 0%, transparent 70%),
            radial-gradient(circle at 2px 2px, ${color} 0.7px, transparent 0.7px)`;
}

/* ── Canonical hero-card surface (tinted glow + dot grid) ──
 *
 * Hero cards (solar, battery, grid, ev, home, system, costs) all want the
 * same background: a soft tinted glow at the top centre over the theme's
 * dot grid. Call this in the card's :host or wrap style instead of
 * hand-coding the gradient so every card stays in sync.
 */
export function semCardSurfaceCSS(theme, tintHex, glowAlpha) {
    const ga = glowAlpha != null ? glowAlpha : 0.06;
    const hex = Math.round(ga * 255).toString(16).padStart(2, '0');
    return `radial-gradient(ellipse 70% 60% at 50% 25%, ${tintHex}${hex} 0%, transparent 100%),
            radial-gradient(circle at 2px 2px, ${theme.dotColor} 0.7px, transparent 0.7px)`;
}

/* ── Per-PV-string discovery + panel (v1.7.1 / #312) ──
 *
 * Reads the per-string sensors that v1.7.0 added to the entity
 * registry: ``sensor.{prefix}pv_string_<slot>_power`` for slots
 * ``pv1`` … ``pv4`` (max — matches the discovery cap in
 * ``hardware_detection.discover_pv_strings_from_registry``).
 *
 * Returns ``[]`` when the gate (≥ 2 strings present) isn't satisfied,
 * so every caller can pass the result directly to a Lit ``html``
 * template via the ``nothing`` sentinel. Empty array on intent: cards
 * render nothing extra for single-string installs, preserving the
 * v1.6.x behaviour.
 */
export function semDiscoverPVStrings(hass, prefix) {
    if (!hass || !hass.states) return [];
    const pfx = prefix || 'sensor.sem_';
    const found = [];
    for (const slot of ['pv1', 'pv2', 'pv3', 'pv4']) {
        const eid = `${pfx}pv_string_${slot}_power`;
        const st = hass.states[eid];
        if (!st) continue;
        const raw = parseFloat(st.state);
        if (isNaN(raw)) continue;

        // Sibling daily-energy sensor (v1.7.0). Always companions the
        // power sensor when the gate trips, so we surface it on the
        // same object — callers that just want power ignore the extra
        // fields; callers that show "today" (sem-solar-card's
        // per-string detail section) read ``energyKwh`` /
        // ``energyEntityId`` without a second hass-state walk.
        const eEid = `${pfx}pv_string_${slot}_daily_energy`;
        const eSt = hass.states[eEid];
        const eKwh = eSt ? parseFloat(eSt.state) : NaN;

        found.push({
            slot,
            watts: raw,
            entityId: eid,
            energyKwh: isNaN(eKwh) ? null : eKwh,
            energyEntityId: eSt ? eEid : null,
        });
    }
    return found.length >= 2 ? found : [];
}

/**
 * Build a compact per-string chip strip rendered as a plain HTML
 * string (Lit ``html`` callers can drop it through ``unsafeHTML`` or
 * a direct ``innerHTML`` write).
 *
 * Returns ``''`` (empty string) when fewer than 2 strings are
 * available — callers can splice ``${semBuildPVStringsHTML(...)}``
 * straight into a Lit template and the row collapses naturally on
 * single-string installs.
 *
 * Why HTML-string and not Lit ``html`` literal here: ``sem-shared``
 * is the unscoped vanilla layer (sem-system-diagram-card et al. use
 * it without Lit). Returning a plain string keeps the helper
 * dependency-free.
 */
export function semBuildPVStringsHTML(strings, theme) {
    if (!strings || strings.length < 2) return '';
    const T = theme || { text: '#fff', textSec: '#aaa' };
    const chips = strings.map(s => {
        const n = s.slot.replace(/^pv/, '');
        const kW = (Math.abs(s.watts) / 1000).toFixed(2);
        return `<div class="pv-chip" title="${s.entityId}" data-entity="${s.entityId}">
            <span class="pv-chip-label">PV${n}</span>
            <span class="pv-chip-value">${kW} kW</span>
        </div>`;
    }).join('');
    return `<div class="pv-strings-row">${chips}</div>`;
}

/**
 * Shared CSS for the per-string chip strip. Cards import + inject
 * once. ``--sem-solar`` tints the value text; falls back to the
 * orange palette.
 */
export const semPVStringsCSS = `
    .pv-strings-row {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
        padding: 6px 12px;
        font-family: 'Segoe UI','Roboto',sans-serif;
        font-size: 12px;
    }
    .pv-chip {
        display: inline-flex;
        align-items: baseline;
        gap: 4px;
        padding: 2px 8px;
        background: rgba(255, 152, 0, 0.10);
        border: 1px solid rgba(255, 152, 0, 0.25);
        border-radius: 999px;
        color: var(--secondary-text-color, #aaa);
        cursor: pointer;
        transition: background 120ms ease;
    }
    .pv-chip:hover { background: rgba(255, 152, 0, 0.18); }
    .pv-chip-label {
        font-size: 10px;
        letter-spacing: 0.5px;
        text-transform: uppercase;
        opacity: 0.7;
    }
    .pv-chip-value {
        color: var(--sem-solar, #ff9800);
        font-weight: 600;
        font-variant-numeric: tabular-nums;
    }
`;

/* ── Card registration helper ── */
export function semDefineCard(tag, cls, cardInfo) {
    if (customElements.get(tag)) return;
    customElements.define(tag, cls);
    if (cardInfo) {
        window.customCards = window.customCards || [];
        window.customCards.push(cardInfo);
    }
}

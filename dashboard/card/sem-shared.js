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

/* ── Export for use in other cards ── */
if (typeof window !== 'undefined') {
    window.SEM_COLORS = SEM_COLORS;
    window.SEM_DEVICE_COLORS = SEM_DEVICE_COLORS;
    window.semFormatPower = semFormatPower;
    window.semFormatEnergy = semFormatEnergy;
    window.semCalcDuration = semCalcDuration;
}

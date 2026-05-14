/**
 * SEM Grid Card — LitElement migration
 *
 * Consolidated grid card: import/export hero, today totals, peak management
 * progress bar, load control, tariff info, and surplus state.
 * Visual design is identical to the original sem-grid-card.js.
 *
 * Config:
 *   type: custom:sem-grid-card
 *   entity_prefix: sensor.sem_   # default
 */

import { SEMLitBase, html, css, nothing } from '../base/sem-lit-base.js';
import { semTheme, semFormatPower, semGetCurrency, semDefineCard } from '../base/sem-shared.js';

const DEFAULT_PREFIX = 'sensor.sem_';

const WATCHED_SUFFIXES = [
    'grid_power', 'grid_import_power', 'grid_export_power', 'grid_status',
    'daily_grid_import_energy', 'daily_grid_export_energy',
    'monthly_grid_import_energy', 'monthly_grid_export_energy',
    'consecutive_peak_15min', 'monthly_consecutive_peak',
    'current_vs_peak_percentage', 'target_peak_limit', 'peak_margin', 'peak_trend',
    'load_management_status', 'loads_currently_shed', 'available_load_reduction',
    'controllable_devices_count',
    'tariff_current_import_rate', 'tariff_current_export_rate', 'tariff_price_level',
    'tariff_today_min_price', 'tariff_today_max_price',
    'surplus_total_w', 'surplus_unallocated_w', 'surplus_active_devices', 'surplus_total_devices',
];

class SEMGridCard extends SEMLitBase {
    static get watchedEntities() {
        return WATCHED_SUFFIXES.map(s => `${DEFAULT_PREFIX}${s}`);
    }

    setConfig(config) {
        super.setConfig(config);
        this._prefix = config.entity_prefix || DEFAULT_PREFIX;
    }

    // Override hass setter: key-based comparison for prefix-dynamic entities
    set hass(hass) {
        this._hass = hass;

        const lang = hass?.language;
        const hasLocalize = typeof semLocalize === 'function';
        let localeChanged = false;
        if (lang !== this._lang || (hasLocalize && !this._localizeReady)) {
            this._lang = lang;
            this._localizeReady = hasLocalize;
            localeChanged = true;
        }


        // Skip while frozen (optimistic update in progress)
        if (this._isFrozen() && !localeChanged) return;

        const key = WATCHED_SUFFIXES
            .map(s => hass?.states[`${this._prefix}${s}`]?.state || '')
            .join(',') + '|' + lang;

        if (key === this._lastGridKey && !localeChanged) return;
        this._lastGridKey = key;
        this._scheduleUpdate();
    }

    get hass() { return this._hass; }

    /* ── Prefix-scoped helpers ── */
    _val(suffix, fallback = 0) {
        return this._state(`${this._prefix}${suffix}`, fallback);
    }

    _valStr(suffix) {
        return this._stateStr(`${this._prefix}${suffix}`);
    }

    _fmt(val, decimals = 1) {
        if (val == null || isNaN(val)) return '—';
        return val.toFixed(decimals);
    }

    _peakColor(pct) {
        if (pct >= 90) return '#f06292';
        if (pct >= 70) return '#ff9800';
        return '#8DC892';
    }

    _priceLevelColor(level) {
        if (level === 'high') return '#f06292';
        if (level === 'low')  return '#8DC892';
        if (level !== '—')   return '#ff9800';
        return '#888';
    }

    /* ── Section helper ── */
    _section(titleKey, titleColor, content) {
        return html`
            <div class="section">
                <div class="section-title" style="color:${titleColor}">${this._t(titleKey)}</div>
                ${content}
            </div>
        `;
    }

    _metricRow(labelKey, valueHtml) {
        return html`
            <div class="metric-row">
                <span class="metric-label">${this._t(labelKey)}</span>
                <span class="metric-val">${valueHtml}</span>
            </div>
        `;
    }

    /* ── Render ── */
    render() {
        if (!this._hass || !this._config) return nothing;

        const T = this._theme();
        const curr = semGetCurrency(this._hass);

        // Grid state
        const importPower = this._val('grid_import_power');
        const exportPower = this._val('grid_export_power');
        const isExporting = exportPower > importPower && exportPower > 10;
        const isImporting = importPower > 10;

        const iconName = isExporting ? 'mdi:transmission-tower-export' : 'mdi:transmission-tower-import';
        const gridColor = isExporting ? '#8353d1' : '#488fc2';
        const glowOpacity = (isImporting || isExporting) ? '0.45' : '0.1';

        const statusRaw = this._valStr('grid_status');
        const statusText = statusRaw !== '' && statusRaw !== '—'
            ? statusRaw
            : isExporting ? this._t('exporting')
            : isImporting ? this._t('importing')
            : this._t('idle');
        const statusColor = isExporting ? '#8353d1' : isImporting ? '#488fc2' : '#888';

        // Today totals
        const dailyImport = this._val('daily_grid_import_energy');
        const dailyExport = this._val('daily_grid_export_energy');
        const netToday = dailyImport - dailyExport;
        const netColor = netToday <= 0 ? '#8353d1' : '#488fc2';

        // Peak management
        const peakPct = this._val('current_vs_peak_percentage');
        const peak15 = this._val('consecutive_peak_15min');
        const monthlyPeak = this._val('monthly_consecutive_peak');
        const peakLimit = this._val('target_peak_limit');
        const peakMargin = this._val('peak_margin');
        const peakTrend = this._valStr('peak_trend');
        const peakColor = this._peakColor(peakPct);
        const peakMarginColor = peakMargin > 0 ? '#8DC892' : '#f06292';
        const fillW = (Math.min(Math.max(peakPct / 100, 0), 1) * 200).toFixed(1);

        // Load control
        const loadStatus = this._valStr('load_management_status');
        const loadShed = this._val('loads_currently_shed');
        const loadReduction = this._val('available_load_reduction');
        const loadDevices = this._val('controllable_devices_count');

        // Tariff
        const importRate = this._val('tariff_current_import_rate');
        const exportRate = this._val('tariff_current_export_rate');
        const priceLevel = this._valStr('tariff_price_level');
        const minPrice = this._val('tariff_today_min_price');
        const maxPrice = this._val('tariff_today_max_price');
        const levelColor = this._priceLevelColor(priceLevel);

        // Surplus
        const surplusTotal = this._val('surplus_total_w');
        const surplusUnalloc = this._val('surplus_unallocated_w');
        const surplusAllocated = Math.max(0, surplusTotal - surplusUnalloc);
        const surplusActive = this._val('surplus_active_devices');
        const surplusTotalDev = this._val('surplus_total_devices');

        const dotCol = T.dotColor || 'rgba(128,128,128,0.05)';
        const textSecCol = T.textSec || '#999';
        const surfaceCol = T.surface || 'rgba(255,255,255,0.06)';
        const surfBorder = T.surfaceBorder || 'rgba(255,255,255,0.12)';

        return html`
            <style>
                :host { display: block; }
                .wrap {
                    padding: 16px 20px;
                    position: relative;
                    background:
                        radial-gradient(ellipse 70% 60% at 50% 20%, rgba(150,202,238,0.06) 0%, transparent 100%),
                        radial-gradient(circle at 2px 2px, ${dotCol} 0.7px, transparent 0.7px);
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    color: var(--primary-text-color, ${T.text || '#e0e0e0'});
                }
                .glow-svg { position: absolute; width: 0; height: 0; }
                .hero { display: flex; align-items: center; gap: 16px; padding-bottom: 8px; }
                @media (max-width: 400px) { .hero { flex-direction: column; gap: 10px; } }
                .grid-icon-area { position: relative; width: 80px; height: 80px; flex-shrink: 0; }
                .grid-icon-area svg { width: 100%; height: 100%; }
                .grid-glow-ring {
                    fill: none; stroke-width: 6;
                    filter: url(#grid-glow-soft);
                    transition: stroke 0.4s ease, opacity 0.4s ease;
                }
                .ring-bg { fill: none; stroke: rgba(72,143,194,0.12); stroke-width: 3; }
                .ring-fill { fill: rgba(72,143,194,0.06); }
                .hero-info { flex: 1; min-width: 0; }
                .hero-power-row { display: flex; gap: 14px; margin-bottom: 4px; flex-wrap: wrap; }
                .hero-pw { display: flex; flex-direction: column; }
                .hero-pw-label {
                    font-size: 10px; text-transform: uppercase; letter-spacing: 0.4px;
                    color: var(--secondary-text-color, ${textSecCol}); margin-bottom: 1px;
                }
                .hero-pw-val { font-size: 17px; font-weight: 700; font-variant-numeric: tabular-nums; }
                .hero-pw-val.import { color: #488fc2; }
                .hero-pw-val.export { color: #8353d1; }
                .hero-status {
                    font-size: 11px; font-weight: 500;
                    text-transform: uppercase; letter-spacing: 0.5px;
                }
                .section {
                    margin-top: 10px; padding: 10px 12px;
                    background: var(--secondary-background-color, ${surfaceCol});
                    border: 1px solid var(--divider-color, ${surfBorder});
                    border-radius: 10px;
                }
                .section-title {
                    font-size: 10px; font-weight: 600; text-transform: uppercase;
                    letter-spacing: 0.6px; margin-bottom: 6px;
                }
                .metric-row {
                    display: flex; justify-content: space-between; align-items: baseline; padding: 2px 0;
                }
                .metric-label {
                    font-size: 11px; color: var(--secondary-text-color, ${textSecCol}); font-weight: 500;
                }
                .metric-val {
                    font-size: 12px; font-weight: 600; font-variant-numeric: tabular-nums;
                    color: var(--primary-text-color, ${T.text || '#e0e0e0'});
                }
                .net-row {
                    margin-top: 4px; padding-top: 4px;
                    border-top: 1px solid var(--divider-color, ${surfBorder});
                }
                .peak-bar-wrap { margin: 6px 0 4px; position: relative; }
                .peak-bar-bg { width: 100%; height: 8px; fill: rgba(72,143,194,0.12); }
                .peak-bar-fill {
                    height: 8px;
                    transition: width 0.8s cubic-bezier(0.4,0,0.2,1), fill 0.4s ease;
                }
                .peak-bar-svg { width: 100%; height: 8px; display: block; }
                .peak-pct-label {
                    font-size: 11px; font-weight: 700; font-variant-numeric: tabular-nums;
                    margin-top: 2px; text-align: right;
                }
                .c-import { color: #488fc2; }
                .c-export { color: #8353d1; }
                .c-green  { color: #8DC892; }
                .c-solar  { color: #ff9800; }
            </style>

            <svg class="glow-svg">
                <defs>
                    <filter id="grid-glow" x="-50%" y="-50%" width="200%" height="200%">
                        <feGaussianBlur stdDeviation="4" result="blur"/>
                        <feFlood flood-color="#488fc2" flood-opacity="0.3" result="color"/>
                        <feComposite in="color" in2="blur" operator="in" result="glow"/>
                        <feMerge><feMergeNode in="glow"/><feMergeNode in="SourceGraphic"/></feMerge>
                    </filter>
                    <filter id="grid-glow-soft" x="-50%" y="-50%" width="200%" height="200%">
                        <feGaussianBlur stdDeviation="6" result="blur"/>
                        <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
                    </filter>
                </defs>
            </svg>

            <ha-card>
                <div class="wrap">
                    <!-- Hero -->
                    <div class="hero">
                        <div class="grid-icon-area">
                            <svg viewBox="0 0 80 80">
                                <circle class="grid-glow-ring" cx="40" cy="40" r="34"
                                    style="stroke:${gridColor};opacity:${glowOpacity}"/>
                                <circle class="ring-bg" cx="40" cy="40" r="34"/>
                                <circle class="ring-fill" cx="40" cy="40" r="31"/>
                                <foreignObject x="14" y="14" width="52" height="52">
                                    <div xmlns="http://www.w3.org/1999/xhtml"
                                        style="width:52px;height:52px;display:flex;align-items:center;justify-content:center">
                                        <ha-icon icon="${iconName}"
                                            style="--mdc-icon-size:28px;color:${gridColor}">
                                        </ha-icon>
                                    </div>
                                </foreignObject>
                            </svg>
                        </div>

                        <div class="hero-info">
                            <div class="hero-power-row">
                                <div class="hero-pw">
                                    <span class="hero-pw-label">${this._t('import')}</span>
                                    <span class="hero-pw-val import">
                                        ${isImporting ? semFormatPower(importPower) : '—'}
                                    </span>
                                </div>
                                <div class="hero-pw">
                                    <span class="hero-pw-label">${this._t('export')}</span>
                                    <span class="hero-pw-val export">
                                        ${isExporting ? semFormatPower(exportPower) : '—'}
                                    </span>
                                </div>
                            </div>
                            <div class="hero-status" style="color:${statusColor}">${statusText}</div>
                        </div>
                    </div>

                    <!-- Today -->
                    <div class="section">
                        <div class="section-title" style="color:#488fc2">${this._t('today')}</div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t('import')}</span>
                            <span class="metric-val c-import">${this._fmt(dailyImport, 2)} kWh</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t('export')}</span>
                            <span class="metric-val c-export">${this._fmt(dailyExport, 2)} kWh</span>
                        </div>
                        <div class="metric-row net-row">
                            <span class="metric-label"><strong>${this._t('net')}</strong></span>
                            <span class="metric-val" style="color:${netColor}">
                                ${this._fmt(Math.abs(netToday), 2)} kWh
                            </span>
                        </div>
                    </div>

                    <!-- Peak Management -->
                    <div class="section">
                        <div class="section-title" style="color:#488fc2">${this._t('peak_management')}</div>
                        <div class="peak-bar-wrap">
                            <svg class="peak-bar-svg" viewBox="0 0 200 8" preserveAspectRatio="none">
                                <rect class="peak-bar-bg" x="0" y="0" width="200" height="8" rx="4" ry="4"/>
                                <rect class="peak-bar-fill" x="0" y="0"
                                    width="${fillW}" height="8" rx="4" ry="4"
                                    fill="${peakColor}"/>
                            </svg>
                        </div>
                        <div class="peak-pct-label" style="color:${peakColor}">
                            ${this._fmt(peakPct, 0)}%
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t('peak_15min')}</span>
                            <span class="metric-val">${semFormatPower(peak15)}</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t('monthly_peak')}</span>
                            <span class="metric-val">${semFormatPower(monthlyPeak)}</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t('peak_limit')}</span>
                            <span class="metric-val">${semFormatPower(peakLimit)}</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t('peak_margin')}</span>
                            <span class="metric-val" style="color:${peakMarginColor}">
                                ${semFormatPower(peakMargin)}
                            </span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t('trend')}</span>
                            <span class="metric-val">${peakTrend || '—'}</span>
                        </div>
                    </div>

                    <!-- Load Control -->
                    <div class="section">
                        <div class="section-title" style="color:#488fc2">${this._t('load_control')}</div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t('status')}</span>
                            <span class="metric-val">${loadStatus || '—'}</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t('loads_shed')}</span>
                            <span class="metric-val">${this._fmt(loadShed, 0)}</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t('available_reduction')}</span>
                            <span class="metric-val">${semFormatPower(loadReduction)}</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t('controllable_devices')}</span>
                            <span class="metric-val">${this._fmt(loadDevices, 0)}</span>
                        </div>
                    </div>

                    <!-- Tariff -->
                    <div class="section">
                        <div class="section-title" style="color:#488fc2">${this._t('tariff')}</div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t('import_rate')}</span>
                            <span class="metric-val c-import">
                                ${importRate !== 0 ? `${this._fmt(importRate, 4)} ${curr}/kWh` : '—'}
                            </span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t('export_rate')}</span>
                            <span class="metric-val c-export">
                                ${exportRate !== 0 ? `${this._fmt(exportRate, 4)} ${curr}/kWh` : '—'}
                            </span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t('price_level')}</span>
                            <span class="metric-val" style="color:${levelColor}">
                                ${priceLevel || '—'}
                            </span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t('today_min')}</span>
                            <span class="metric-val c-green">
                                ${minPrice !== 0 ? this._fmt(minPrice, 4) : '—'}
                            </span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t('today_max')}</span>
                            <span class="metric-val c-solar">
                                ${maxPrice !== 0 ? this._fmt(maxPrice, 4) : '—'}
                            </span>
                        </div>
                    </div>

                    <!-- Surplus -->
                    <div class="section">
                        <div class="section-title" style="color:#488fc2">${this._t('surplus')}</div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t('total_surplus')}</span>
                            <span class="metric-val c-solar">${semFormatPower(surplusTotal)}</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t('allocated')}</span>
                            <span class="metric-val">${semFormatPower(surplusAllocated)}</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t('unallocated')}</span>
                            <span class="metric-val c-green">${semFormatPower(surplusUnalloc)}</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t('active_devices')}</span>
                            <span class="metric-val">
                                ${Math.round(surplusActive)} / ${Math.round(surplusTotalDev)}
                            </span>
                        </div>
                    </div>
                </div>
            </ha-card>
        `;
    }

    getCardSize() { return 5; }

    static getStubConfig() { return { entity_prefix: DEFAULT_PREFIX }; }
}

semDefineCard('sem-grid-card', SEMGridCard, {
    type: 'sem-grid-card',
    name: 'SEM Grid',
    description: 'Consolidated grid card with import/export, peak management, load control, tariff, and surplus',
});

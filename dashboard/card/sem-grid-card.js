(window.semReady || (fn => { window._semReadyQueue = window._semReadyQueue || []; window._semReadyQueue.push(fn); }))(function() {
/**
 * SEM Grid Card — Lumina-styled consolidated grid card
 *
 * Shows live grid import/export power and direction, today's energy totals,
 * peak management progress bar, load control, tariff info, and surplus state.
 *
 * Config:
 *   type: custom:sem-grid-card
 *   entity_prefix: sensor.sem_   # default
 */

class SEMGridCard extends SEMBaseCard {
    constructor() {
        super();
        this._rendered = false;
    }

    setConfig(config) {
        this.config = config;
        this._prefix = config.entity_prefix || 'sensor.sem_';
    }

    set hass(hass) {
        const localeChanged = this._checkLocaleChange(hass);
        const key = [
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
        ].map(s => this._hass?.states[`${this._prefix}${s}`]?.state || '').join(',')
            + '|' + this._hass?.language;
        if (key === this._lastKey && !localeChanged) return;
        this._lastKey = key;
        if (localeChanged) this._rendered = false;
        this._update();
    }

    _state(suffix, fallback = 0) {
        const e = this._hass?.states[`${this._prefix}${suffix}`];
        if (!e || e.state === 'unavailable' || e.state === 'unknown') return fallback;
        return parseFloat(e.state) ?? fallback;
    }

    _stateStr(suffix) {
        const e = this._hass?.states[`${this._prefix}${suffix}`];
        return e?.state || '—';
    }

    _fmt(val, decimals = 1) {
        if (val == null || isNaN(val)) return '—';
        return val.toFixed(decimals);
    }

    /** Return CSS color for a peak percentage value. */
    _peakColor(pct) {
        if (pct >= 90) return '#f06292';
        if (pct >= 70) return '#ff9800';
        return '#8DC892';
    }

    _update() {
        if (!this._hass) return;
        const isFirstRender = !this._rendered;
        if (isFirstRender) {
            this.style.visibility = 'hidden';
            this._renderSkeleton();
            this._rendered = true;
        }

        const $ = (sel) => this.shadowRoot.querySelector(sel);
        const setVal = (sel, text) => { const el = $(sel); if (el && el.textContent !== text) el.textContent = text; };

        const importPower = this._state('grid_import_power');
        const exportPower = this._state('grid_export_power');
        const gridPower   = this._state('grid_power');
        const isExporting = exportPower > importPower && exportPower > 10;
        const isImporting = importPower > 10;

        // Hero icon direction
        const iconEl = $('.grid-icon');
        if (iconEl) {
            iconEl.setAttribute('icon', isExporting ? 'mdi:transmission-tower-export' : 'mdi:transmission-tower-import');
            iconEl.style.color = isExporting ? '#8353d1' : '#488fc2';
        }
        const glowEl = $('.grid-glow-ring');
        if (glowEl) {
            glowEl.style.stroke = isExporting ? '#8353d1' : '#488fc2';
            glowEl.style.opacity = (isImporting || isExporting) ? '0.45' : '0.1';
        }

        // Hero power values
        setVal('.hero-import-val', isImporting ? semFormatPower(importPower) : '—');
        setVal('.hero-export-val', isExporting ? semFormatPower(exportPower) : '—');

        const statusStr = this._stateStr('grid_status');
        setVal('.hero-status', statusStr !== '—' ? statusStr : (isExporting ? this._t('exporting') : isImporting ? this._t('importing') : this._t('idle')));
        const statusEl = $('.hero-status');
        if (statusEl) {
            const statusColor = isExporting ? '#8353d1' : isImporting ? '#488fc2' : '#888';
            if (statusEl.style.color !== statusColor) statusEl.style.color = statusColor;
        }

        // Today totals
        const curr = (typeof semGetCurrency === 'function') ? semGetCurrency(this._hass) : 'EUR';
        setVal('.today-import', this._fmt(this._state('daily_grid_import_energy'), 2) + ' kWh');
        setVal('.today-export', this._fmt(this._state('daily_grid_export_energy'), 2) + ' kWh');
        const netToday = this._state('daily_grid_import_energy') - this._state('daily_grid_export_energy');
        const netTodayEl = $('.today-net');
        if (netTodayEl) {
            const netTodayText = this._fmt(Math.abs(netToday), 2) + ' kWh';
            const netTodayColor = netToday <= 0 ? '#8353d1' : '#488fc2';
            if (netTodayEl.textContent !== netTodayText) netTodayEl.textContent = netTodayText;
            if (netTodayEl.style.color !== netTodayColor) netTodayEl.style.color = netTodayColor;
        }

        // Peak management
        const peakPct = this._state('current_vs_peak_percentage');
        const peak15 = this._state('consecutive_peak_15min');
        const monthlyPeak = this._state('monthly_consecutive_peak');
        const peakLimit = this._state('target_peak_limit');
        const peakMargin = this._state('peak_margin');
        const peakTrend = this._stateStr('peak_trend');

        const peakColor = this._peakColor(peakPct);

        // SVG progress bar
        const barFill = this.shadowRoot.querySelector('.peak-bar-fill');
        if (barFill) {
            const fillW = Math.min(Math.max(peakPct / 100, 0), 1) * 200; // bar is 200px wide
            barFill.setAttribute('width', fillW.toFixed(1));
            barFill.setAttribute('fill', peakColor);
        }
        setVal('.peak-pct-label', this._fmt(peakPct, 0) + '%');
        const peakPctEl = $('.peak-pct-label');
        if (peakPctEl && peakPctEl.style.color !== peakColor) peakPctEl.style.color = peakColor;

        setVal('.peak-15min', semFormatPower(peak15));
        setVal('.peak-monthly', semFormatPower(monthlyPeak));
        setVal('.peak-limit', semFormatPower(peakLimit));
        setVal('.peak-margin', semFormatPower(peakMargin));
        const peakMarginEl = $('.peak-margin');
        if (peakMarginEl) {
            const peakMarginColor = peakMargin > 0 ? '#8DC892' : '#f06292';
            if (peakMarginEl.style.color !== peakMarginColor) peakMarginEl.style.color = peakMarginColor;
        }
        setVal('.peak-trend', peakTrend !== '—' ? peakTrend : '—');

        // Load control
        const loadStatus = this._stateStr('load_management_status');
        setVal('.load-status', loadStatus !== '—' ? loadStatus : '—');
        setVal('.load-shed', this._fmt(this._state('loads_currently_shed'), 0));
        setVal('.load-reduction', semFormatPower(this._state('available_load_reduction')));
        setVal('.load-devices', this._fmt(this._state('controllable_devices_count'), 0));

        // Tariff
        const importRate = this._state('tariff_current_import_rate');
        const exportRate = this._state('tariff_current_export_rate');
        const priceLevel = this._stateStr('tariff_price_level');
        const minPrice = this._state('tariff_today_min_price');
        const maxPrice = this._state('tariff_today_max_price');
        setVal('.tariff-import', importRate !== 0 ? this._fmt(importRate, 4) + ' ' + curr + '/kWh' : '—');
        setVal('.tariff-export', exportRate !== 0 ? this._fmt(exportRate, 4) + ' ' + curr + '/kWh' : '—');
        const levelEl = $('.tariff-level');
        if (levelEl) {
            const levelText = priceLevel !== '—' ? priceLevel : '—';
            const levelColor = priceLevel === 'high' ? '#f06292' : priceLevel === 'low' ? '#8DC892' : '#ff9800';
            const levelFinalColor = priceLevel !== '—' ? levelColor : '#888';
            if (levelEl.textContent !== levelText) levelEl.textContent = levelText;
            if (levelEl.style.color !== levelFinalColor) levelEl.style.color = levelFinalColor;
        }
        setVal('.tariff-min', minPrice !== 0 ? this._fmt(minPrice, 4) : '—');
        setVal('.tariff-max', maxPrice !== 0 ? this._fmt(maxPrice, 4) : '—');

        // Surplus
        const surplusTotal = this._state('surplus_total_w');
        const surplusUnalloc = this._state('surplus_unallocated_w');
        const surplusAllocated = Math.max(0, surplusTotal - surplusUnalloc);
        setVal('.surplus-total', semFormatPower(surplusTotal));
        setVal('.surplus-allocated', semFormatPower(surplusAllocated));
        setVal('.surplus-free', semFormatPower(surplusUnalloc));
        const surplusActive = this._state('surplus_active_devices');
        const surplusTotal_ = this._state('surplus_total_devices');
        setVal('.surplus-devices', Math.round(surplusActive) + ' / ' + Math.round(surplusTotal_));

        // Translate labels
        const lblMap = {
            '.lbl-import': 'import', '.lbl-export': 'export',
            '.lbl-today-section': 'today', '.lbl-peak': 'peak_management',
            '.lbl-load': 'load_control', '.lbl-tariff': 'tariff', '.lbl-surplus': 'surplus',
            '.lbl-today-import': 'import', '.lbl-today-export': 'export', '.lbl-today-net': 'net',
            '.lbl-peak-15': 'peak_15min', '.lbl-peak-monthly': 'monthly_peak',
            '.lbl-peak-limit': 'peak_limit', '.lbl-peak-margin': 'peak_margin',
            '.lbl-peak-trend': 'trend', '.lbl-load-status': 'status',
            '.lbl-load-shed': 'loads_shed', '.lbl-load-reduction': 'available_reduction',
            '.lbl-load-devices': 'controllable_devices', '.lbl-tariff-import': 'import_rate',
            '.lbl-tariff-export': 'export_rate', '.lbl-tariff-level': 'price_level',
            '.lbl-tariff-min': 'today_min', '.lbl-tariff-max': 'today_max',
            '.lbl-surplus-total': 'total_surplus', '.lbl-surplus-alloc': 'allocated',
            '.lbl-surplus-free': 'unallocated', '.lbl-surplus-devices': 'active_devices',
        };
        for (const [sel, key] of Object.entries(lblMap)) setVal(sel, this._t(key));
        if (isFirstRender) requestAnimationFrame(() => { this.style.visibility = ''; });
    }

    _renderSkeleton() {
        const T = (typeof semTheme === 'function') ? semTheme() : {};
        const textCol = T.text || '#e0e0e0';
        const textSecCol = T.textSec || '#999';
        const surfaceCol = T.surface || 'rgba(255,255,255,0.06)';
        const surfBorder = T.surfaceBorder || 'rgba(255,255,255,0.12)';
        const dotCol = T.dotColor || 'rgba(128,128,128,0.05)';

        this.shadowRoot.innerHTML = `
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
                    color: var(--primary-text-color, ${textCol});
                }
                .glow-svg { position: absolute; width: 0; height: 0; }
                .hero { display: flex; align-items: center; gap: 16px; padding-bottom: 8px; }
                @media (max-width: 400px) { .hero { flex-direction: column; gap: 10px; } }

                .grid-icon-area {
                    position: relative; width: 80px; height: 80px; flex-shrink: 0;
                }
                .grid-icon-area svg { width: 100%; height: 100%; }
                .grid-glow-ring {
                    fill: none; stroke: #488fc2; stroke-width: 6; opacity: 0.1;
                    filter: url(#grid-glow-soft);
                    transition: stroke 0.4s ease, opacity 0.4s ease;
                }
                .ring-bg { fill: none; stroke: rgba(72,143,194,0.12); stroke-width: 3; }
                .ring-fill { fill: rgba(72,143,194,0.06); }
                .grid-icon {
                    --mdc-icon-size: 28px;
                    color: #488fc2;
                    transition: color 0.4s ease;
                }

                .hero-info { flex: 1; min-width: 0; }
                .hero-power-row {
                    display: flex; gap: 14px; margin-bottom: 4px; flex-wrap: wrap;
                }
                .hero-pw {
                    display: flex; flex-direction: column;
                }
                .hero-pw-label {
                    font-size: 10px; text-transform: uppercase; letter-spacing: 0.4px;
                    color: var(--secondary-text-color,${textSecCol}); margin-bottom: 1px;
                }
                .hero-pw-val {
                    font-size: 17px; font-weight: 700;
                    font-variant-numeric: tabular-nums;
                }
                .hero-pw-val.import { color: #488fc2; }
                .hero-pw-val.export { color: #8353d1; }
                .hero-status {
                    font-size: 11px; font-weight: 500;
                    text-transform: uppercase; letter-spacing: 0.5px;
                    color: var(--secondary-text-color,${textSecCol});
                }

                /* ── Section ── */
                .section {
                    margin-top: 10px; padding: 10px 12px;
                    background: var(--secondary-background-color, ${surfaceCol});
                    border: 1px solid var(--divider-color, ${surfBorder});
                    border-radius: 10px;
                }
                .section-title {
                    font-size: 10px; font-weight: 600; text-transform: uppercase;
                    letter-spacing: 0.6px; color: #488fc2; margin-bottom: 6px;
                }

                /* ── Metric rows ── */
                .metric-row {
                    display: flex; justify-content: space-between; align-items: baseline;
                    padding: 2px 0;
                }
                .metric-label {
                    font-size: 11px; color: var(--secondary-text-color,${textSecCol});
                    font-weight: 500;
                }
                .metric-val {
                    font-size: 12px; font-weight: 600;
                    font-variant-numeric: tabular-nums;
                    color: var(--primary-text-color,${textCol});
                }

                /* ── Peak progress bar ── */
                .peak-bar-wrap {
                    margin: 6px 0 4px;
                    position: relative;
                }
                .peak-bar-bg {
                    width: 100%; height: 8px; fill: rgba(72,143,194,0.12);
                    rx: 4; ry: 4;
                }
                .peak-bar-fill {
                    height: 8px; fill: #8DC892;
                    rx: 4; ry: 4;
                    transition: width 0.8s cubic-bezier(0.4,0,0.2,1), fill 0.4s ease;
                }
                .peak-bar-svg { width: 100%; height: 8px; display: block; }
                .peak-pct-label {
                    font-size: 11px; font-weight: 700;
                    font-variant-numeric: tabular-nums;
                    color: #8DC892; margin-top: 2px; text-align: right;
                }

                /* Color helpers */
                .c-import  { color: #488fc2; }
                .c-export  { color: #8353d1; }
                .c-green   { color: #8DC892; }
                .c-solar   { color: #ff9800; }
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
                                <circle class="grid-glow-ring" cx="40" cy="40" r="34"/>
                                <circle class="ring-bg" cx="40" cy="40" r="34"/>
                                <circle class="ring-fill" cx="40" cy="40" r="31"/>
                                <foreignObject x="14" y="14" width="52" height="52">
                                    <div xmlns="http://www.w3.org/1999/xhtml" style="width:52px;height:52px;display:flex;align-items:center;justify-content:center">
                                        <ha-icon class="grid-icon" icon="mdi:transmission-tower-import" style="--mdc-icon-size:28px;color:#488fc2"></ha-icon>
                                    </div>
                                </foreignObject>
                            </svg>
                        </div>

                        <div class="hero-info">
                            <div class="hero-power-row">
                                <div class="hero-pw">
                                    <span class="hero-pw-label lbl-import">${this._t('import')}</span>
                                    <span class="hero-pw-val import hero-import-val">—</span>
                                </div>
                                <div class="hero-pw">
                                    <span class="hero-pw-label lbl-export">${this._t('export')}</span>
                                    <span class="hero-pw-val export hero-export-val">—</span>
                                </div>
                            </div>
                            <div class="hero-status">—</div>
                        </div>
                    </div>

                    <!-- Today -->
                    <div class="section">
                        <div class="section-title lbl-today-section">${this._t('today')}</div>
                        <div class="metric-row">
                            <span class="metric-label lbl-today-import">${this._t('import')}</span>
                            <span class="metric-val c-import today-import">—</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label lbl-today-export">${this._t('export')}</span>
                            <span class="metric-val c-export today-export">—</span>
                        </div>
                        <div class="metric-row" style="margin-top:4px;padding-top:4px;border-top:1px solid var(--divider-color,${surfBorder})">
                            <span class="metric-label lbl-today-net"><strong>${this._t('net')}</strong></span>
                            <span class="metric-val today-net">—</span>
                        </div>
                    </div>

                    <!-- Peak Management -->
                    <div class="section">
                        <div class="section-title lbl-peak">${this._t('peak_management')}</div>
                        <div class="peak-bar-wrap">
                            <svg class="peak-bar-svg" viewBox="0 0 200 8" preserveAspectRatio="none">
                                <rect class="peak-bar-bg" x="0" y="0" width="200" height="8" rx="4" ry="4"/>
                                <rect class="peak-bar-fill" x="0" y="0" width="0" height="8" rx="4" ry="4"/>
                            </svg>
                        </div>
                        <div class="peak-pct-label">—%</div>
                        <div class="metric-row">
                            <span class="metric-label lbl-peak-15">${this._t('peak_15min')}</span>
                            <span class="metric-val peak-15min">—</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label lbl-peak-monthly">${this._t('monthly_peak')}</span>
                            <span class="metric-val peak-monthly">—</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label lbl-peak-limit">${this._t('peak_limit')}</span>
                            <span class="metric-val peak-limit">—</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label lbl-peak-margin">${this._t('peak_margin')}</span>
                            <span class="metric-val peak-margin">—</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label lbl-peak-trend">${this._t('trend')}</span>
                            <span class="metric-val peak-trend">—</span>
                        </div>
                    </div>

                    <!-- Load Control -->
                    <div class="section">
                        <div class="section-title lbl-load">${this._t('load_control')}</div>
                        <div class="metric-row">
                            <span class="metric-label lbl-load-status">${this._t('status')}</span>
                            <span class="metric-val load-status">—</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label lbl-load-shed">${this._t('loads_shed')}</span>
                            <span class="metric-val load-shed">—</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label lbl-load-reduction">${this._t('available_reduction')}</span>
                            <span class="metric-val load-reduction">—</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label lbl-load-devices">${this._t('controllable_devices')}</span>
                            <span class="metric-val load-devices">—</span>
                        </div>
                    </div>

                    <!-- Tariff -->
                    <div class="section">
                        <div class="section-title lbl-tariff">${this._t('tariff')}</div>
                        <div class="metric-row">
                            <span class="metric-label lbl-tariff-import">${this._t('import_rate')}</span>
                            <span class="metric-val c-import tariff-import">—</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label lbl-tariff-export">${this._t('export_rate')}</span>
                            <span class="metric-val c-export tariff-export">—</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label lbl-tariff-level">${this._t('price_level')}</span>
                            <span class="metric-val tariff-level">—</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label lbl-tariff-min">${this._t('today_min')}</span>
                            <span class="metric-val c-green tariff-min">—</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label lbl-tariff-max">${this._t('today_max')}</span>
                            <span class="metric-val c-solar tariff-max">—</span>
                        </div>
                    </div>

                    <!-- Surplus -->
                    <div class="section">
                        <div class="section-title lbl-surplus">${this._t('surplus')}</div>
                        <div class="metric-row">
                            <span class="metric-label lbl-surplus-total">${this._t('total_surplus')}</span>
                            <span class="metric-val c-solar surplus-total">—</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label lbl-surplus-alloc">${this._t('allocated')}</span>
                            <span class="metric-val surplus-allocated">—</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label lbl-surplus-free">${this._t('unallocated')}</span>
                            <span class="metric-val c-green surplus-free">—</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label lbl-surplus-devices">${this._t('active_devices')}</span>
                            <span class="metric-val surplus-devices">—</span>
                        </div>
                    </div>
                </div>
            </ha-card>
        `;
    }

    getCardSize() { return 5; }

    static getStubConfig() { return { entity_prefix: 'sensor.sem_' }; }
}

semDefineCard('sem-grid-card', SEMGridCard, {
    type: 'sem-grid-card',
    name: 'SEM Grid',
    description: 'Consolidated grid card with import/export, peak management, load control, tariff, and surplus',
});

});

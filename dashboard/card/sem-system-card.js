(window.semReady || (fn => { window._semReadyQueue = window._semReadyQueue || []; window._semReadyQueue.push(fn); }))(function() {
/**
 * SEM System Card — Consolidated system panel
 *
 * Replaces mushroom cards on the System tab with a single interactive card
 * featuring collapsible sections for system info, health, mode controls,
 * diagnostics, and a copy-to-clipboard button.
 *
 * Config:
 *   type: custom:sem-system-card
 *   entity_prefix: sensor.sem_   # optional, default
 */

const SECTIONS = [
    {
        id: 'info', icon: 'mdi:information-outline', color: '#96CAEE', titleKey: 'system_info',
        subtitleFn: (c) => {
            const ver = c._stateStr('diag_version') || '—';
            const mode = c._stateStr('diag_grid_mode') || '—';
            const modeTranslated = mode === 'combined' ? c._t('grid_combined')
                : mode === 'split' ? c._t('grid_split') : mode;
            return `v${ver} · ${modeTranslated}`;
        },
    },
    {
        id: 'health', icon: 'mdi:heart-pulse', color: '#8DC892', titleKey: 'health_overview',
        subtitleFn: (c) => {
            const solar = c._state('solar_power').toFixed(0);
            const soc = c._state('battery_soc').toFixed(0);
            return `${solar}W solar · SOC ${soc}%`;
        },
    },
    {
        id: 'modes', icon: 'mdi:toggle-switch-outline', color: '#96CAEE', titleKey: 'mode_controls',
        subtitleFn: (c) => {
            const obs = c._switchState('observer_mode');
            const night = c._switchState('night_charging');
            return [obs && 'Observer', night && 'Night'].filter(Boolean).join(' · ') || '—';
        },
    },
    {
        id: 'diag', icon: 'mdi:bug-outline', color: '#ff9800', titleKey: 'diagnostics',
        subtitleFn: () => '',
    },
];

const HEALTH_CHIPS = [
    { key: 'solar_power',                 icon: 'mdi:solar-power',      color: '#ff9800', suffix: 'W' },
    { key: 'grid_power',                  icon: 'mdi:transmission-tower', color: '#488fc2', suffix: 'W' },
    { key: 'battery_soc',                 icon: 'mdi:battery',           color: '#4db6ac', suffix: '%' },
    { key: 'ev_power',                    icon: 'mdi:ev-station',        color: '#8DC892', suffix: 'W' },
    { key: 'forecast_today',              icon: 'mdi:weather-sunny',     color: '#ff9800', suffix: 'kWh' },
    { key: 'tariff_current_import_rate',  icon: 'mdi:tag',               color: '#96CAEE', suffix: '' },
];

class SEMSystemCard extends SEMBaseCard {
    constructor() {
        super();
        this._rendered = false;
        this._lastKey = '';
        this._collapsed = {};
    }

    setConfig(config) {
        this.config = config;
        this._prefix = config.entity_prefix || 'sensor.sem_';
    }

    _state(suffix, fallback = 0) {
        const e = this._hass?.states[`${this._prefix}${suffix}`];
        if (!e || e.state === 'unavailable' || e.state === 'unknown') return fallback;
        return parseFloat(e.state) || fallback;
    }

    _stateStr(suffix) {
        const e = this._hass?.states[`${this._prefix}${suffix}`];
        return (e && e.state !== 'unavailable' && e.state !== 'unknown') ? e.state : '';
    }

    _switchState(suffix) {
        const e = this._hass?.states[`switch.sem_${suffix}`];
        return e?.state === 'on';
    }

    _entityAvailable(entityId) {
        const e = this._hass?.states[entityId];
        return e && e.state !== 'unavailable' && e.state !== 'unknown';
    }

    set hass(hass) {
        const localeChanged = this._checkLocaleChange(hass);

        const watchKeys = [
            'sensor.sem_diag_version', 'sensor.sem_diag_grid_mode',
            'sensor.sem_diag_battery_capacity', 'sensor.sem_diag_update_interval',
            'sensor.sem_diag_charger_count', 'sensor.sem_diag_charger_control_type',
            'sensor.sem_diag_unavailable_sensors',
            'sensor.sem_solar_power', 'sensor.sem_grid_power',
            'sensor.sem_battery_soc', 'sensor.sem_ev_power',
            'sensor.sem_forecast_today', 'sensor.sem_tariff_current_import_rate',
            'switch.sem_observer_mode', 'switch.sem_night_charging',
            'switch.sem_smart_night_charging',
            'sensor.sem_home_consumption_power', 'sensor.sem_grid_import_power',
            'sensor.sem_grid_export_power', 'sensor.sem_autarky_rate',
            'sensor.sem_self_consumption_rate', 'sensor.sem_battery_power',
            'sensor.sem_night_mode', 'sensor.sem_solar_mode', 'sensor.sem_ev_connected',
            'sensor.sem_calculated_current', 'sensor.sem_daily_ev_energy',
            'sensor.sem_daily_ev_target', 'sensor.sem_night_mode_status',
            'sensor.sem_solar_mode_status', 'sensor.sem_battery_status',
            'sensor.sem_grid_status',
        ];
        const key = watchKeys.map(k => hass.states[k]?.state || '').join(',');

        if (key === this._lastKey && !localeChanged) return;
        this._lastKey = key;

        if (!this._rendered || localeChanged) {
            this.style.visibility = 'hidden';
            this._renderSkeleton();
            this._rendered = true;
            this._update();
            requestAnimationFrame(() => { this.style.visibility = ''; });
            return;
        }
        this._update();
    }

    _toggleSection(id) {
        this._collapsed[id] = !this._collapsed[id];
        const section = this.shadowRoot.querySelector(`[data-section="${id}"]`);
        if (!section) return;
        const body = section.querySelector('.section-body');
        const chevron = section.querySelector('.chevron');
        if (this._collapsed[id]) {
            body.style.maxHeight = '0';
            body.style.opacity = '0';
            chevron.style.transform = 'rotate(-90deg)';
        } else {
            body.style.maxHeight = body.scrollHeight + 'px';
            body.style.opacity = '1';
            chevron.style.transform = 'rotate(0deg)';
            setTimeout(() => { if (!this._collapsed[id]) body.style.maxHeight = 'none'; }, 350);
        }
    }

    async _callService(domain, service, data) {
        if (!this._hass) return;
        try {
            await this._hass.callService(domain, service, data);
        } catch (e) {
            console.error('[SEM System]', domain, service, data, e);
        }
    }

    _toggleSwitch(entityId) {
        const state = this._hass?.states[entityId];
        if (!state) return;
        const svc = state.state === 'on' ? 'turn_off' : 'turn_on';
        this._callService('switch', svc, { entity_id: entityId });
    }

    _update() {
        if (!this._hass) return;
        const $ = (sel) => this.shadowRoot.querySelector(sel);
        const setVal = (sel, text) => { const el = $(sel); if (el && el.textContent !== text) el.textContent = text; };

        // ── Section subtitles ──
        for (const s of SECTIONS) {
            setVal(`[data-section="${s.id}"] .section-subtitle`, s.subtitleFn(this));
            setVal(`[data-section="${s.id}"] .section-title-text`, this._t(s.titleKey));
        }

        // ── System Info ──
        setVal('.info-version-val', this._stateStr('diag_version') || '—');
        const gridMode = this._stateStr('diag_grid_mode') || '—';
        const gridModeTranslated = gridMode === 'combined' ? this._t('grid_combined')
            : gridMode === 'split' ? this._t('grid_split') : gridMode;
        setVal('.info-grid-mode-val', gridModeTranslated);
        const cap = this._state('diag_battery_capacity');
        setVal('.info-capacity-val', cap > 0 ? cap.toFixed(1) + ' kWh' : '—');
        const interval = this._state('diag_update_interval');
        setVal('.info-interval-val', interval > 0 ? interval.toFixed(0) + ' s' : '—');
        const chargerCount = this._stateStr('diag_charger_count') || '—';
        const controlType = this._stateStr('diag_charger_control_type') || '';
        setVal('.info-chargers-val', controlType ? `${chargerCount} (${controlType})` : chargerCount);
        setVal('.info-unavailable-val', this._stateStr('diag_unavailable_sensors') || '0');

        // ── Health chips ──
        for (const chip of HEALTH_CHIPS) {
            const entityId = `${this._prefix}${chip.key}`;
            const chipEl = this.shadowRoot.querySelector(`.health-chip[data-key="${chip.key}"]`);
            if (!chipEl) continue;
            const available = this._entityAvailable(entityId);
            const e = this._hass.states[entityId];
            const val = e ? e.state : '—';
            const valEl = chipEl.querySelector('.chip-value');
            if (valEl) {
                const text = available ? `${val}${chip.suffix}` : '—';
                if (valEl.textContent !== text) valEl.textContent = text;
            }
            const chipBg = available ? 'rgba(141,200,146,0.12)' : 'rgba(244,67,54,0.12)';
            const chipBorder = available ? 'rgba(141,200,146,0.3)' : 'rgba(244,67,54,0.3)';
            if (chipEl.style.background !== chipBg) chipEl.style.background = chipBg;
            if (chipEl.style.borderColor !== chipBorder) chipEl.style.borderColor = chipBorder;
        }

        // ── Mode Controls toggles ──
        this._updateToggle('.mode-observer', 'switch.sem_observer_mode', 'observer_mode');
        this._updateToggle('.mode-night', 'switch.sem_night_charging', 'night_charging');
        this._updateToggle('.mode-smart', 'switch.sem_smart_night_charging', 'smart_night');

        // ── Diagnostics text blocks ──
        const solar = this._state('solar_power').toFixed(0);
        const grid = this._state('grid_power').toFixed(0);
        const battery = this._state('battery_power').toFixed(0);
        const soc = this._state('battery_soc').toFixed(0);
        const ev = this._state('ev_power').toFixed(0);
        setVal('.diag-source', `Solar ${solar}W · Grid ${grid}W · Battery ${battery}W · SOC ${soc}% · EV ${ev}W`);

        const home = this._state('home_consumption_power').toFixed(0);
        const imp = this._state('grid_import_power').toFixed(0);
        const exp = this._state('grid_export_power').toFixed(0);
        const autarky = this._state('autarky_rate').toFixed(0);
        const selfCons = this._state('self_consumption_rate').toFixed(0);
        setVal('.diag-derived', `Home ${home}W · Import ${imp}W · Export ${exp}W · Autarky ${autarky}% · Self ${selfCons}%`);

        const nightMode = this._stateStr('night_mode') || '—';
        const solarMode = this._stateStr('solar_mode') || '—';
        const idle = this._stateStr('ev_idle') || '—';
        const calcCurrent = this._stateStr('calculated_current') || '—';
        const dailyEv = this._state('daily_ev_energy').toFixed(1);
        const evTarget = this._stateStr('daily_ev_target') || '—';
        const evPlug = this._stateStr('ev_connected') || '—';
        setVal('.diag-ev', `Night mode: ${nightMode} · Solar: ${solarMode} · Idle: ${idle} · ${calcCurrent}A · ${dailyEv}/${evTarget}kWh · Plug: ${evPlug}`);

        const nightStatus = this._stateStr('night_mode_status') || '—';
        const solarStatus = this._stateStr('solar_mode_status') || '—';
        const battStatus = this._stateStr('battery_status') || '—';
        const gridStatus = this._stateStr('grid_status') || '—';
        setVal('.diag-modes', `Night: ${nightStatus} · Solar: ${solarStatus} · Battery: ${battStatus} · Grid: ${gridStatus}`);

        // ── Update labels ──
        this._updateLabels();
    }

    _updateToggle(selector, entityId, labelKey) {
        const el = this.shadowRoot.querySelector(selector);
        if (!el) return;
        const state = this._hass?.states[entityId];
        const isOn = state?.state === 'on';
        const track = el.querySelector('.toggle-track');
        const label = el.querySelector('.toggle-label');
        if (track) {
            track.classList.toggle('on', isOn);
            if (!track._semBound) {
                track._semBound = true;
                track.addEventListener('click', () => this._toggleSwitch(entityId));
            }
        }
        const translated = this._t(labelKey);
        if (label && label.textContent !== translated) label.textContent = translated;
    }

    _updateLabels() {
        const setLabel = (sel, key) => {
            const el = this.shadowRoot.querySelector(sel);
            const text = this._t(key);
            if (el && el.textContent !== text) el.textContent = text;
        };
        setLabel('.info-version-lbl', 'version');
        setLabel('.info-grid-mode-lbl', 'grid_mode');
        setLabel('.info-capacity-lbl', 'battery_capacity');
        setLabel('.info-interval-lbl', 'update_interval');
        setLabel('.info-chargers-lbl', 'chargers');
        setLabel('.info-unavailable-lbl', 'unavailable_sensors');
        setLabel('.diag-source-lbl', 'source_sensors');
        setLabel('.diag-derived-lbl', 'derived_values');
        setLabel('.diag-ev-lbl', 'ev_charging');
        setLabel('.diag-modes-lbl', 'mode_status');
        setLabel('.copy-btn', 'copy_diagnostics');
    }

    _makeToggleHTML(cls, labelKey) {
        return `
            <div class="${cls} toggle-row">
                <span class="toggle-label">${this._t(labelKey)}</span>
                <div class="toggle-track"><div class="toggle-thumb"></div></div>
            </div>`;
    }

    _makeInfoRowHTML(lblCls, valCls, labelKey) {
        return `
            <div class="info-row">
                <span class="${lblCls} info-row-label">${this._t(labelKey)}</span>
                <span class="${valCls} info-row-value">—</span>
            </div>`;
    }

    _makeSectionHTML(section, bodyHTML) {
        const collapsed = this._collapsed[section.id];
        return `
            <div class="section" data-section="${section.id}">
                <div class="section-header" tabindex="0" role="button" aria-expanded="${!collapsed}">
                    <ha-icon icon="${section.icon}" style="--mdc-icon-size:20px;color:${section.color}"></ha-icon>
                    <span class="section-title-text">${this._t(section.titleKey)}</span>
                    <span class="section-subtitle"></span>
                    <ha-icon class="chevron" icon="mdi:chevron-down"
                             style="--mdc-icon-size:18px;transform:rotate(${collapsed ? '-90deg' : '0deg'})"></ha-icon>
                </div>
                <div class="section-body" style="max-height:${collapsed ? '0' : 'none'};opacity:${collapsed ? '0' : '1'}">
                    ${bodyHTML}
                </div>
            </div>`;
    }

    _makeDiagBlockHTML(lblCls, valCls, labelKey) {
        return `
            <div class="diag-block">
                <span class="${lblCls} diag-block-label">${this._t(labelKey)}</span>
                <span class="${valCls} diag-block-text">—</span>
            </div>`;
    }

    _renderSkeleton() {
        const T = (typeof semTheme === 'function') ? semTheme() : {};
        const textCol = T.text || '#e0e0e0';
        const textSecCol = T.textSec || '#999';
        const surfaceCol = T.surface || 'rgba(255,255,255,0.06)';
        const surfBorder = T.surfaceBorder || 'rgba(255,255,255,0.12)';
        const surfHover = T.surfaceHover || 'rgba(255,255,255,0.10)';
        const dotCol = T.dotColor || 'rgba(128,128,128,0.05)';
        const isDark = T.isDark !== false;
        const accent = T.accent || '#42a5f5';

        // ── Section: System Info ──
        const infoBody = `
            ${this._makeInfoRowHTML('info-version-lbl', 'info-version-val', 'version')}
            ${this._makeInfoRowHTML('info-grid-mode-lbl', 'info-grid-mode-val', 'grid_mode')}
            ${this._makeInfoRowHTML('info-capacity-lbl', 'info-capacity-val', 'battery_capacity')}
            ${this._makeInfoRowHTML('info-interval-lbl', 'info-interval-val', 'update_interval')}
            ${this._makeInfoRowHTML('info-chargers-lbl', 'info-chargers-val', 'chargers')}
            ${this._makeInfoRowHTML('info-unavailable-lbl', 'info-unavailable-val', 'unavailable_sensors')}`;

        // ── Section: Health Overview ──
        const healthChipsHTML = HEALTH_CHIPS.map(chip => `
            <div class="health-chip" data-key="${chip.key}"
                 style="background:rgba(141,200,146,0.12);border:1px solid rgba(141,200,146,0.3)">
                <ha-icon icon="${chip.icon}" style="--mdc-icon-size:16px;color:${chip.color}"></ha-icon>
                <span class="chip-value">—</span>
            </div>`).join('');
        const healthBody = `<div class="health-chips">${healthChipsHTML}</div>`;

        // ── Section: Mode Controls ──
        const modesBody = `
            <div class="toggle-group">
                ${this._makeToggleHTML('mode-observer', 'observer_mode')}
                ${this._makeToggleHTML('mode-night', 'night_charging')}
                ${this._makeToggleHTML('mode-smart', 'smart_night')}
            </div>`;

        // ── Section: Diagnostics ──
        const diagBody = `
            ${this._makeDiagBlockHTML('diag-source-lbl', 'diag-source', 'source_sensors')}
            ${this._makeDiagBlockHTML('diag-derived-lbl', 'diag-derived', 'derived_values')}
            ${this._makeDiagBlockHTML('diag-ev-lbl', 'diag-ev', 'ev_charging')}
            ${this._makeDiagBlockHTML('diag-modes-lbl', 'diag-modes', 'mode_status')}`;

        const bodies = { info: infoBody, health: healthBody, modes: modesBody, diag: diagBody };

        this.shadowRoot.innerHTML = `
            <style>
                :host { display: block; }
                .wrap {
                    padding: 16px;
                    position: relative;
                    background:
                        radial-gradient(ellipse 70% 60% at 50% 20%, rgba(150,202,238,0.06) 0%, transparent 100%),
                        radial-gradient(circle at 2px 2px, ${dotCol} 0.7px, transparent 0.7px);
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    color: var(--primary-text-color, ${textCol});
                }

                /* ── Sections ── */
                .section {
                    margin-bottom: 8px;
                    border-radius: 14px;
                    background: ${surfaceCol};
                    border: 1px solid ${surfBorder};
                    overflow: hidden;
                    transition: border-color 0.2s;
                }
                .section:hover { border-color: ${isDark ? 'rgba(255,255,255,0.18)' : 'rgba(0,0,0,0.12)'}; }

                .section-header {
                    display: flex; align-items: center; gap: 8px;
                    padding: 12px 14px;
                    cursor: pointer;
                    user-select: none;
                    -webkit-user-select: none;
                    transition: background 0.15s;
                }
                .section-header:hover { background: ${surfHover}; }
                .section-title-text {
                    font-size: 14px; font-weight: 600;
                    white-space: nowrap;
                }
                .section-subtitle {
                    flex: 1;
                    font-size: 12px;
                    color: var(--secondary-text-color, ${textSecCol});
                    text-align: right;
                    white-space: nowrap;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    margin-right: 4px;
                }
                .chevron {
                    transition: transform 0.25s ease;
                    color: var(--secondary-text-color, ${textSecCol});
                    flex-shrink: 0;
                }
                .section-body {
                    padding: 0 14px;
                    overflow: hidden;
                    transition: max-height 0.3s ease, opacity 0.25s ease;
                }
                .section-body > *:last-child { margin-bottom: 14px; }

                /* ── Info rows ── */
                .info-row {
                    display: flex; align-items: center; justify-content: space-between;
                    padding: 7px 0;
                    border-bottom: 1px solid ${surfBorder};
                }
                .info-row:last-child { border-bottom: none; }
                .info-row-label {
                    font-size: 13px; font-weight: 500;
                    color: var(--secondary-text-color, ${textSecCol});
                }
                .info-row-value {
                    font-size: 13px; font-weight: 600;
                    font-variant-numeric: tabular-nums;
                }

                /* ── Health chips ── */
                .health-chips {
                    display: flex; flex-wrap: wrap; gap: 8px;
                    padding: 8px 0 4px;
                }
                .health-chip {
                    display: flex; align-items: center; gap: 6px;
                    padding: 6px 10px;
                    border-radius: 20px;
                    transition: background 0.2s, border-color 0.2s;
                }
                .chip-value {
                    font-size: 12px; font-weight: 600;
                    font-variant-numeric: tabular-nums;
                }

                /* ── Toggle ── */
                .toggle-row {
                    display: flex; align-items: center; justify-content: space-between;
                    padding: 9px 0;
                    border-bottom: 1px solid ${surfBorder};
                }
                .toggle-row:last-child { border-bottom: none; }
                .toggle-group { padding-top: 2px; }
                .toggle-label {
                    font-size: 13px; font-weight: 500;
                }
                .toggle-track {
                    position: relative;
                    width: 42px; height: 24px;
                    border-radius: 12px;
                    background: ${isDark ? 'rgba(255,255,255,0.15)' : 'rgba(0,0,0,0.18)'};
                    cursor: pointer;
                    transition: background 0.2s;
                    flex-shrink: 0;
                }
                .toggle-track.on { background: ${accent}; }
                .toggle-thumb {
                    position: absolute;
                    top: 2px; left: 2px;
                    width: 20px; height: 20px;
                    border-radius: 50%;
                    background: white;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.3);
                    transition: left 0.2s;
                }
                .toggle-track.on .toggle-thumb { left: 20px; }

                /* ── Diagnostics blocks ── */
                .diag-block {
                    padding: 8px 0;
                    border-bottom: 1px solid ${surfBorder};
                }
                .diag-block:last-child { border-bottom: none; }
                .diag-block-label {
                    display: block;
                    font-size: 11px; font-weight: 600;
                    text-transform: uppercase;
                    letter-spacing: 0.4px;
                    color: var(--secondary-text-color, ${textSecCol});
                    margin-bottom: 3px;
                }
                .diag-block-text {
                    display: block;
                    font-size: 12px; font-weight: 500;
                    line-height: 1.5;
                    word-break: break-word;
                    font-variant-numeric: tabular-nums;
                }

                /* ── Copy button row ── */
                .copy-row {
                    margin-top: 10px;
                    display: flex; justify-content: center;
                }
                .copy-btn {
                    display: flex; align-items: center; gap: 6px;
                    padding: 8px 18px;
                    border-radius: 10px;
                    border: 1px solid ${surfBorder};
                    background: ${surfaceCol};
                    color: var(--primary-text-color, ${textCol});
                    font-size: 13px; font-weight: 600;
                    font-family: inherit;
                    cursor: pointer;
                    transition: background 0.15s, border-color 0.15s;
                }
                .copy-btn:hover {
                    background: ${surfHover};
                    border-color: #96CAEE;
                }
                .copy-btn:active {
                    background: ${isDark ? 'rgba(255,255,255,0.15)' : 'rgba(0,0,0,0.08)'};
                }
                .copy-feedback {
                    font-size: 11px;
                    color: #8DC892;
                    margin-top: 4px;
                    text-align: center;
                    min-height: 16px;
                    transition: opacity 0.3s;
                }

                @media (max-width: 480px) {
                    .health-chips { gap: 6px; }
                    .health-chip { padding: 5px 8px; }
                }
            </style>
            <div class="wrap">
                ${SECTIONS.map(s => this._makeSectionHTML(s, bodies[s.id])).join('')}
                <div class="copy-row">
                    <button class="copy-btn">
                        <ha-icon icon="mdi:content-copy" style="--mdc-icon-size:16px"></ha-icon>
                        ${this._t('copy_diagnostics')}
                    </button>
                </div>
                <div class="copy-feedback"></div>
            </div>`;

        // Bind section header clicks
        for (const s of SECTIONS) {
            const header = this.shadowRoot.querySelector(`[data-section="${s.id}"] .section-header`);
            if (header) {
                header.addEventListener('click', () => this._toggleSection(s.id));
                header.addEventListener('keydown', (e) => {
                    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); this._toggleSection(s.id); }
                });
            }
        }

        // Bind copy button
        const copyBtn = this.shadowRoot.querySelector('.copy-btn');
        if (copyBtn) {
            copyBtn.addEventListener('click', () => this._copyDiagnostics());
        }
    }

    _copyDiagnostics() {
        const ver = this._stateStr('diag_version') || '—';
        const gridMode = this._stateStr('diag_grid_mode') || '—';
        const chargerCount = this._stateStr('diag_charger_count') || '—';
        const controlType = this._stateStr('diag_charger_control_type') || '—';
        const capacity = this._state('diag_battery_capacity');
        const capStr = capacity > 0 ? capacity.toFixed(1) : '—';
        const unavailable = this._stateStr('diag_unavailable_sensors') || '0';

        const text = `SEM ${ver} | Grid: ${gridMode} | Chargers: ${chargerCount} (${controlType}) | Battery: ${capStr}kWh | Unavailable: ${unavailable}`;

        navigator.clipboard.writeText(text).then(() => {
            const fb = this.shadowRoot.querySelector('.copy-feedback');
            if (fb) {
                fb.textContent = this._t('copied');
                fb.style.opacity = '1';
                setTimeout(() => { fb.style.opacity = '0'; }, 2000);
            }
        }).catch(err => {
            console.error('[SEM System] clipboard copy failed', err);
        });
    }

    getCardSize() { return 8; }

    static getStubConfig() {
        return { entity_prefix: 'sensor.sem_' };
    }
}

semDefineCard('sem-system-card', SEMSystemCard, {
    type: 'custom:sem-system-card',
    name: 'SEM System Card',
    description: 'Consolidated system panel for Solar Energy Management',
    preview: false,
});

});
